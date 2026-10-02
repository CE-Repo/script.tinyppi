# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The ``MediaSourceVar`` row: where the playing video comes from.

For a file it reads ``release type · container · size`` (e.g.
``Remux · MKV · 42GB``), using the release tags also known to imax.py.  For a
live channel, recording or stream it names the transport instead: ``PVR``, or
the streaming protocol (HLS/DASH/RTMP/RTSP).  An empty result falls back to
the localized N/A label, so the row is never blank.

Network files (smb, nfs, or http(s) from a media server such as Plex or
Jellyfin) are treated like local ones.  When nothing can be read because the
server uses an opaque id, the protocol (HTTP, SMB, NFS, ...) is shown before
falling back to N/A.  The size stat is the only network request, so it is
skipped for addon-delivered links (see ``_statable``).

Kodi has no container InfoLabel, so the container comes from the file
extension; a stream without one leaves that part out.
"""

import re

import xbmc
import xbmcvfs

from core.memo import KeyedMemo
from core.utils import cond, info
from info.dvinfo import na_label
from info.imax import playing_path

_DISC_PREFIXES = ("bluray://", "dvd://")

_TAG_SEP = re.compile(r"[^a-z0-9]+")

_BLURAY_TOKENS = frozenset({
    # No bare "bd"/"br": they double as language/region tags ("BR" for
    # Brazilian Portuguese).
    "bluray", "bdrip", "brrip", "bdremux",
    "bd25", "bd50", "bd66", "bd100",
})
_HDTV_TOKENS = frozenset({"hdtv", "pdtv"})
_DVD_TOKENS = frozenset({"dvdrip", "dvd5", "dvd9", "dvd"})

# Tokens that describe the file rather than the film; they confirm that an
# ordinary word like "web" is a release tag.
_FILE_MARKERS = frozenset({
    "x264", "x265", "h264", "h265", "hevc", "avc", "av1", "xvid", "divx",
    "ddp", "dd", "eac3", "ac3", "aac", "dts", "dtshd", "truehd", "atmos",
    "flac", "opus", "hdr", "hdr10", "sdr", "dv", "dovi", "hlg", "10bit",
})
_RESOLUTION_SHAPE = re.compile(r"^\d{3,4}[pi]$")

# Last path and its size text, so the stat runs once per title (see
# _size_text).
_sizes = KeyedMemo()

# File extension -> container label.  Only real containers: playlist or
# wrapper extensions (.m3u8, .strm, .pvr) describe the delivery instead.
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

# Label for PVR items.  The backend (Tvheadend, IPTV Simple, ...) is a setup
# detail and deliberately not shown.
_PVR_LABEL = "PVR"

# Last-resort labels naming the transport, shown only when nothing else
# could be read (see _source_protocol).
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

# Schemes whose paths name a file a VFS stat can answer cheaply; the empty
# string is a local path.  Anything else (``plugin://`` above all) is never
# stat'd (see _statable).
_STATABLE_SCHEMES = frozenset({
    "", "file", "smb", "nfs", "ftp", "ftps", "sftp", "ssh", "dav", "davs",
    "http", "https",
})

# Internet schemes: the only ones an addon's resolved link can use.
_REMOTE_SCHEMES = ("http", "https")

# The item's own path: for an addon item the ``plugin://`` path, not the
# resolved URL that ``_raw_playing_path`` returns.
_ITEM_PATH_LABEL = "Player.FilenameAndPath"


def _tokens(name: str) -> set[str]:
    """Split a release name into lowercase tokens on non-alphanumerics."""
    return set(_TAG_SEP.split(name.lower())) - {""}


def _describes_a_file(tokens: set[str]) -> bool:
    """Return whether *tokens* mark a release name rather than a title.

    True for a resolution or a codec / audio-format tag.
    """
    if tokens & _FILE_MARKERS:
        return True
    return any(_RESOLUTION_SHAPE.match(token) for token in tokens)


def _release_type(name: str) -> str:
    """Return the release-type label for *name*, or ''.

    Checked by priority (remux, disc rip, web release, ...), so a name with
    several tags shows the best one.
    """
    tokens = _tokens(name)
    if "remux" in tokens:
        return "Remux"
    if tokens & _BLURAY_TOKENS:
        return "UHD BD" if "uhd" in tokens else "BD"
    if "webdl" in tokens or ("web" in tokens and "dl" in tokens):
        return "WEB-DL"
    if "webrip" in tokens or ("web" in tokens and "rip" in tokens):
        return "WEBRip"
    # A bare "WEB" does not say WEB-DL or WEBRip, so it is shown as is.  It
    # is also an ordinary word, so it only counts next to a release marker
    # (otherwise "Charlotte's Web" would match).
    if "web" in tokens and _describes_a_file(tokens):
        return "WEB"
    if tokens & _HDTV_TOKENS:
        return "HDTV"
    if tokens & _DVD_TOKENS:
        return "DVD"
    return ""


def _release_type_from_path(path: str) -> str:
    """Return the release type from the file name and its parent folder.

    A rip's tags are sometimes only on the folder.
    """
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
    """Return the container label for *path*'s extension, or ''."""
    name = path.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return _CONTAINER_MAP.get(name.rsplit(".", 1)[-1].lower(), "")


def _size_text(path: str) -> str:
    """Return the file size in whole GB (MB below 1 GB), or ''.

    Empty for paths that are not stat'd (addon streams, discs) or when the
    stat fails.  Cached per path, failures included: the row is rebuilt on
    every tick, and a network stat would otherwise run on the overlay thread
    each time.
    """
    if not path:
        return ""
    text = _sizes.get(path)
    if text is None:
        text = _measure(path)
        _sizes.put(path, text)
    return text


def _item_path() -> str:
    """Return the playing item's path as the playlist holds it, or ''.

    For an addon item this is the ``plugin://`` path, while
    ``_raw_playing_path`` returns the URL it resolved to.
    """
    label = info(_ITEM_PATH_LABEL)
    if label:
        return label
    try:
        return xbmc.Player().getPlayingItem().getPath() or ""
    except Exception:  # nothing playing, or no item to ask
        return ""


def _is_addon_item() -> bool:
    """Return whether an addon supplied the playing item.

    The playing file of an addon item is its resolved URL (often a signed CDN
    link); only the item's own ``plugin://`` path reveals the addon.
    """
    return _item_path().lower().startswith("plugin://")


def _statable(path: str) -> bool:
    """Return whether *path* is worth a VFS size stat.

    Addon streams are excluded: their size means nothing, and a CDN that
    stalls the request blocked the overlay thread for seconds (seen with
    every YouTube title).  So the scheme must name a file, and for http(s)
    the item must not come from an addon.  Shares and local paths are always
    fine; the worst case there is one LAN round trip.
    """
    if not path:
        return False
    scheme = path.split("://", 1)[0].lower() if "://" in path else ""
    if scheme not in _STATABLE_SCHEMES:
        return False
    return scheme not in _REMOTE_SCHEMES or not _is_addon_item()


def _measure(path: str) -> str:
    """Stat *path* and format its size, or '' (see ``_statable``)."""
    if not _statable(path):
        return ""
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
    """Return the streaming protocol guessed from the URL, or ''."""
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
    """Return the playing file exactly as Kodi reports it, or ''.

    Unlike the decoded ``imax.playing_path``, this is what the VFS can stat
    and what carries the real extension; for plugin and ``.strm`` items it is
    the resolved target.
    """
    try:
        return xbmc.Player().getPlayingFile() or ""
    except RuntimeError:  # nothing playing
        return ""


def _source_protocol(path: str) -> str:
    """Return the transport label for *path*, or '' for a local path.

    The last resort when nothing else could be read, e.g. a media server
    serving a file under an opaque id.
    """
    scheme = path.split("://", 1)[0].lower() if "://" in path else ""
    return _PROTOCOL_MAP.get(scheme, "")


def _disc_release_type(path: str) -> str:
    return "BD Disc" if path.lower().startswith("bluray://") else "DVD Disc"


def is_live() -> bool:
    """Return whether the item is a live stream rather than a served file.

    ``Player.IsLive`` exists only from Kodi 22; older versions use the skin's
    own test: an internet stream without a duration is live.
    """
    return cond("Player.IsLive") or cond(
        "Player.IsInternetStream + String.IsEmpty(Player.Duration)")


def is_pvr() -> bool:
    """Return whether a PVR item is playing.

    Recordings count as PVR too: they have no release name and cannot be
    stat'd.
    """
    return (cond("PVR.IsPlayingTV") or cond("PVR.IsPlayingRadio")
            or cond("PVR.IsPlayingRecording"))


def _live_segments(raw_path: str, protocol: str) -> list[str]:
    return [_PVR_LABEL if is_pvr() else protocol, _container(raw_path)]


def _file_segments(raw_path: str, path: str) -> list[str]:
    if path.lower().startswith(_DISC_PREFIXES):
        return [_disc_release_type(path)]
    return [_release_type_from_path(path), _container(raw_path),
            _size_text(raw_path)]


def get_MediaSourceVar() -> str:
    """Return the media source row, parts joined with ' · '.

    Release type / container / size for files, transport / container for
    live items, or the localized N/A label when nothing is known.

    Uses both the raw path (stat-able, real extension) and the decoded
    ``imax.playing_path`` (readable disc image names and release tags).

    The branch depends on whether the item is live, not on the transport:
    ``Player.IsInternetStream`` is also true for files served over http by
    a media server, which would drop release name and size from every Plex
    title.
    """
    raw_path = _raw_playing_path()
    path = playing_path() or raw_path
    raw_path = raw_path or path

    protocol = _stream_protocol(path)
    segments = (_live_segments(raw_path, protocol)
                if is_pvr() or protocol or is_live()
                else _file_segments(raw_path, path))

    text = " · ".join(segment for segment in segments if segment)
    return text or _source_protocol(raw_path) or na_label()
