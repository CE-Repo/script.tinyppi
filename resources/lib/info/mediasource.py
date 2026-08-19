"""Compose the ``MediaSourceVar`` line shown in place of the old, redundant
"Medienquelle" row (see ``script-tinyppi-main.xml``), which used to just
repeat the Input row in a shorter form.

For a file this reads ``Release-Typ · Container · Groesse`` (e.g.
``Remux · MKV · 42GB``), each part reusing the same tag vocabulary the IMAX
title matching in ``imax.py`` already knows about release names.  While a
live channel or stream plays there is no release tag and no fixed file size,
so the line instead names the transport: the PVR backend for a live channel,
or the streaming protocol (HLS/DASH/RTMP/RTSP) for an addon-delivered
stream, still paired with the container when Kodi reports one.  Whichever
branch runs, an empty result falls back to the same localized ``N/A`` label
the DV metadata rows use, so the row is never blank.
"""

import re

import xbmcvfs

from core.utils import clean, cond, info
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

_CONTAINER_MAP = {
    "matroska": "MKV",
    "mp4": "MP4",
    "mov": "MP4",
    "mpegts": "TS",
    "avi": "AVI",
    "iso9660": "ISO",
    "iso": "ISO",
}

# Common PVR backend add-ons, mapped to a name short enough to still leave
# room for the container next to it.  An unrecognised backend still gets a
# generic label rather than being left out -- the row must never go blank
# just because a less common PVR client is running.
_BACKEND_MAP = {
    "iptv simple client": "IPTV",
    "pvr.iptvsimple": "IPTV",
    "tvheadend htsp client": "Tvheadend",
    "pvr.hts": "Tvheadend",
    "nextpvr": "NextPVR",
    "pvr.nextpvr": "NextPVR",
    "vdr-vnsi server": "VDR",
    "vbox": "VBox",
    "hdhomerun": "HDHomeRun",
    "mediaportal tv server": "MediaPortal",
    "argus tv": "ArgusTV",
}


def _tokens(name: str) -> set[str]:
    """Split a release name into lowercase tag tokens on any run of
    non-alphanumeric characters, the same separators scene names use."""
    return set(_TAG_SEP.split(name.lower())) - {""}


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
    if "webrip" in tokens:
        return "WEBRip"
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
    """Return the container label, preferring Kodi's own ``VideoPlayer.
    Container`` reading over the file extension since it also covers addon
    streams that carry no extension in their path at all."""
    raw = info("VideoPlayer.Container").strip().lower()
    if not raw:
        name = path.rsplit("/", 1)[-1]
        raw = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not raw:
        return ""
    return _CONTAINER_MAP.get(raw, raw.upper())


def _size_text(path: str) -> str:
    """Return the played file's size, rounded to whole GB (or MB under
    1 GB), or '' when the path can't be stat'd -- an addon stream or a
    disc path most often can't."""
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


def _pvr_backend() -> str:
    """Return a short label for the PVR backend serving the live channel,
    falling back to a generic one for a backend not in the map."""
    raw = clean(info("PVR.BackendName")).strip().lower()
    return _BACKEND_MAP.get(raw, "PVR")


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


def _disc_release_type(path: str) -> str:
    return "BD Disc" if path.lower().startswith("bluray://") else "DVD Disc"


def _live_segments(path: str) -> list[str]:
    is_pvr = cond("PVR.IsPlayingTV")
    transport = _pvr_backend() if is_pvr else _stream_protocol(path)
    return [transport, _container(path)]


def _file_segments(path: str) -> list[str]:
    if path.lower().startswith(_DISC_PREFIXES):
        return [_disc_release_type(path)]
    return [_release_type_from_path(path), _container(path), _size_text(path)]


def get_MediaSourceVar() -> str:
    """Return the combined release-type / container / size line, or the
    transport / container line while live, joined with ' · '.  Falls back to
    the localized N/A label when nothing about the source could be found."""
    path = playing_path()
    is_live = cond("PVR.IsPlayingTV") or cond("Player.IsInternetStream")
    segments = _live_segments(path) if is_live else _file_segments(path)

    text = " · ".join(segment for segment in segments if segment)
    return text or na_label()
