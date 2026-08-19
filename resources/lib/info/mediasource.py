"""Compose the ``MediaSourceVar`` line shown in place of the old, redundant
"Medienquelle" row (see ``script-tinyppi-main.xml``), which used to just
repeat the Input row in a shorter form.

For a file this reads ``Release-Typ · Container · Groesse`` (e.g.
``Remux · MKV · 42GB``), each part reusing the same tag vocabulary the IMAX
title matching in ``imax.py`` already knows about release names.  While a
live channel, recording or stream plays there is no release tag and nothing
to stat, so the line instead names the transport: ``PVR`` for a PVR item, or
the streaming protocol (HLS/DASH/RTMP/RTSP) for an addon-delivered stream.
Whichever branch runs, an empty result falls back to the same localized
``N/A`` label the DV metadata rows use, so the row is never blank.

A file reached over a network -- smb, nfs, or the plain http(s) a media
server such as Plex or Jellyfin serves it over -- takes the file branch like
any local one, and reads the same three parts off the URL and a VFS stat.
Where that yields nothing, because the server names the file by an opaque
id, the protocol itself (HTTP / SMB / NFS / ...) stands in before N/A does.

Kodi has no container InfoLabel to ask -- there is no ``VideoPlayer.
Container``, and ``Player.Process`` exposes only decoder and stream readings
-- so the container comes from the played path's file type instead, which
means a stream delivered without one simply leaves that part out.
"""

import re

import xbmc
import xbmcvfs

from core.utils import cond
from info.dvinfo import na_label
from info.imax import playing_path

_DISC_PREFIXES = ("bluray://", "dvd://")

_TAG_SEP = re.compile(r"[^a-z0-9]+")

_BLURAY_TOKENS = frozenset({
    # No bare "bd"/"br": those double as language/region tags ("BR" for
    # Brazilian Portuguese), so only the unambiguous, longer tags count.
    "bluray", "bdrip", "brrip", "bdremux",
    "bd25", "bd50", "bd66", "bd100",
})
_HDTV_TOKENS = frozenset({"hdtv", "pdtv"})
_DVD_TOKENS = frozenset({"dvdrip", "dvd5", "dvd9", "dvd"})

# Tokens that describe the file rather than the film, used to confirm an
# otherwise ordinary word like "web" really is a release tag.
_FILE_MARKERS = frozenset({
    "x264", "x265", "h264", "h265", "hevc", "avc", "av1", "xvid", "divx",
    "ddp", "dd", "eac3", "ac3", "aac", "dts", "dtshd", "truehd", "atmos",
    "flac", "opus", "hdr", "hdr10", "sdr", "dv", "dovi", "hlg", "10bit",
})
_RESOLUTION_SHAPE = re.compile(r"^\d{3,4}[pi]$")

# Last size worked out, kept per path so the stat behind it runs once a title
# rather than on every static-properties tick; see _size_text.
_size_cache: tuple[str, str] | None = None

# Kodi exposes no container/demuxer InfoLabel of any kind (there is no
# ``VideoPlayer.Container``, and ``Player.Process`` carries only decoder and
# stream readings), so the container is read off the played path's file type.
# Only real container types are listed: a playlist or PVR wrapper extension
# (.m3u8, .strm, .pvr) names the delivery, not what the video sits in, and
# would be misleading in this row.
_CONTAINER_MAP = {
    "mkv": "MKV",
    "webm": "WEBM",
    "mp4": "MP4",
    "m4v": "MP4",
    "mov": "MOV",
    "ts": "TS",
    "m2ts": "TS",
    "mts": "TS",
    "avi": "AVI",
    "iso": "ISO",
    "img": "ISO",
    "mpg": "MPEG",
    "mpeg": "MPEG",
    "m2v": "MPEG",
    "vob": "MPEG",
    "wmv": "WMV",
    "asf": "WMV",
    "flv": "FLV",
    "divx": "DIVX",
    "ogv": "OGV",
}

# What a PVR item names itself as.  The backend behind it (Tvheadend, IPTV
# Simple, NextPVR, ...) is deliberately not spelled out: the row says where
# the picture comes from, and which client serves it is a setup detail.
_PVR_LABEL = "PVR"

# Last-resort labels: what an item travels over, shown only when nothing
# else about the source could be read (see _source_protocol).
_PROTOCOL_MAP = {
    "http": "HTTP",
    "https": "HTTP",
    "smb": "SMB",
    "nfs": "NFS",
    "upnp": "UPnP",
    "ftp": "FTP",
    "ftps": "FTP",
    "sftp": "SFTP",
    "ssh": "SFTP",
    "davs": "WebDAV",
    "dav": "WebDAV",
    "plugin": "Addon",
}


def _tokens(name: str) -> set[str]:
    """Split a release name into lowercase tag tokens on any run of
    non-alphanumeric characters, the same separators scene names use."""
    return set(_TAG_SEP.split(name.lower())) - {""}


def _describes_a_file(tokens: set[str]) -> bool:
    """Return whether a name carries a token that only a release name would:
    a resolution, or one of the codec / audio-format tags.  Used to tell a
    release apart from a plain film title (see _release_type)."""
    if tokens & _FILE_MARKERS:
        return True
    return any(_RESOLUTION_SHAPE.match(token) for token in tokens)


def _release_type(name: str) -> str:
    """Return the release-type label for a release name, or '' when it
    carries no recognised tag.  Checked in the priority order promised to
    the user: a lossless remux outranks a plain disc rip, which outranks a
    web release, so a name carrying several tags shows the best one."""
    tokens = _tokens(name)
    if "remux" in tokens:
        return "Remux"
    if tokens & _BLURAY_TOKENS:
        return "UHD BD" if "uhd" in tokens else "BD"
    if "webdl" in tokens or ("web" in tokens and "dl" in tokens):
        return "WEB-DL"
    if "webrip" in tokens or ("web" in tokens and "rip" in tokens):
        return "WEBRip"
    # A bare "WEB" is common and says only that the source was a stream, not
    # which of the two it was, so it is shown as itself rather than guessed
    # into one of them.  Unlike every other tag here it is also an ordinary
    # word, so it counts only next to something that marks the name as a
    # release rather than a title -- otherwise Charlotte's Web reads as one.
    if "web" in tokens and _describes_a_file(tokens):
        return "WEB"
    if tokens & _HDTV_TOKENS:
        return "HDTV"
    if tokens & _DVD_TOKENS:
        return "DVD"
    return ""


def _release_type_from_path(path: str) -> str:
    """Return the release type read off the played file, checking the file
    name and its parent folder -- a rip's tags sometimes live on the folder
    rather than the file inside it."""
    parts = [part for part in re.split(r"[\\/]+", path) if part and not part.endswith(":")]
    if not parts:
        return ""

    name = parts[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    candidates = [stem]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return _release_type(" ".join(candidates))


def _container(path: str) -> str:
    """Return the container label for the played path's file type, or ''
    when it names none this row would want to show (see _CONTAINER_MAP)."""
    name = path.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return _CONTAINER_MAP.get(name.rsplit(".", 1)[-1].lower(), "")


def _size_text(path: str) -> str:
    """Return the played file's size, rounded to whole GB (or MB under
    1 GB), or '' when the path can't be stat'd -- an addon stream or a
    disc path most often can't.

    Answered once per path and remembered, including a failure: the row is
    recomputed on every static-properties tick, and a file's size cannot
    change while it plays, so re-running the stat would buy nothing and
    would put a network round trip -- to an smb share, or to a media server
    that may be slow to answer -- on the overlay's update thread each time.
    """
    global _size_cache

    if not path:
        return ""
    if _size_cache and _size_cache[0] == path:
        return _size_cache[1]

    text = _measure(path)
    _size_cache = (path, text)
    return text


def _measure(path: str) -> str:
    """Stat *path* and render its size; '' when it cannot be stat'd."""
    try:
        size = xbmcvfs.Stat(path).st_size()
    except Exception:
        return ""
    if size <= 0:
        return ""

    gib = size / (1024 ** 3)
    if gib >= 1:
        return f"{round(gib)}GB"
    mib = size / (1024 ** 2)
    return f"{round(mib)}MB" if mib >= 1 else ""


def _stream_protocol(path: str) -> str:
    """Return the delivery protocol for an addon-provided internet stream,
    guessed from its URL, or '' when none of the known markers show up."""
    low = path.lower()
    if ".m3u8" in low:
        return "HLS"
    if ".mpd" in low:
        return "DASH"
    if low.startswith("rtmp"):
        return "RTMP"
    if low.startswith("rtsp"):
        return "RTSP"
    return ""


def _raw_playing_path() -> str:
    """Return the path of the playing file exactly as Kodi hands it out, or
    ''.  ``imax.playing_path`` decodes the same path for reading names off
    it; the undecoded one is what the VFS can stat and what names the real
    file type, and it resolves what a plugin or ``.strm`` item actually
    plays rather than the item's own path.
    """
    try:
        return xbmc.Player().getPlayingFile() or ""
    except RuntimeError:  # nothing playing
        return ""


def _source_protocol(path: str) -> str:
    """Return a label for the protocol the item travels over, used as the
    last thing to say about a source nothing else could be read off -- a
    media server handing out a file under an opaque id, say.  A local path
    carries no protocol and so keeps the N/A label."""
    scheme = path.split("://", 1)[0].lower() if "://" in path else ""
    return _PROTOCOL_MAP.get(scheme, "")


def _disc_release_type(path: str) -> str:
    return "BD Disc" if path.lower().startswith("bluray://") else "DVD Disc"


def _is_live() -> bool:
    """Return whether the item is a live stream rather than a file being
    served.  ``Player.IsLive`` says so directly but only exists from Kodi 22,
    and this addon runs from Kodi 19, so the test the skin itself uses for
    its Livestream row carries the older versions: an internet stream with no
    duration is live, while one that has a duration is a file on a server.
    """
    return cond("Player.IsLive") or cond(
        "Player.IsInternetStream + String.IsEmpty(Player.Duration)")


def _is_pvr() -> bool:
    """Return whether a PVR item is playing.  A recording is grouped with the
    live channels rather than with files: it has no release name and cannot be
    stat'd either, so naming its backend says more than an empty row would."""
    return (cond("PVR.IsPlayingTV") or cond("PVR.IsPlayingRadio")
            or cond("PVR.IsPlayingRecording"))


def _live_segments(raw_path: str, protocol: str) -> list[str]:
    return [_PVR_LABEL if _is_pvr() else protocol, _container(raw_path)]


def _file_segments(raw_path: str, path: str) -> list[str]:
    if path.lower().startswith(_DISC_PREFIXES):
        return [_disc_release_type(path)]
    return [_release_type_from_path(path), _container(raw_path),
            _size_text(raw_path)]


def get_MediaSourceVar() -> str:
    """Return the combined release-type / container / size line, or the
    transport / container line while live, joined with ' · '.  Falls back to
    the localized N/A label when nothing about the source could be found.

    Two readings of the path are needed: the raw one Kodi hands out, which is
    what the VFS can stat and what carries the real file type, and the decoded
    one from ``imax.playing_path``, whose unwrapping is what makes a disc
    image's own name -- and the release tags on it -- readable.

    What picks the branch is whether the item is live, not how it travels.
    ``Player.IsInternetStream`` cannot decide that: it is true for plain
    http(s), which is how a media server hands out ordinary files, so asking
    it would drop the release name and size off every Plex title.  A file
    served over http, smb or nfs is a file, and only a genuinely live item --
    PVR, a player-reported live stream, or a streaming manifest -- is not.
    """
    raw_path = _raw_playing_path()
    path = playing_path() or raw_path
    raw_path = raw_path or path

    protocol = _stream_protocol(path)
    segments = (_live_segments(raw_path, protocol)
                if _is_pvr() or protocol or _is_live()
                else _file_segments(raw_path, path))

    text = " · ".join(segment for segment in segments if segment)
    return text or _source_protocol(raw_path) or na_label()
