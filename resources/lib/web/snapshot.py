# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Build the dashboard snapshot from the overlay's own readings.

``info.properties`` only calls ``setProperty`` on its window, so passing a
collector instead of an ``xbmcgui.Window`` yields exactly the overlay's
values (formatting, units, N/A labels) without duplicating the logic.

The row layout mirrors ``script-tinyppi-main.xml`` and reuses its string
ids, so translations and label changes apply to both.
"""

import json
import re
import threading
import time
import zlib

import xbmc
from core.log import channel
from core.utils import (
    PROP_EFFECTIVE_HDR_TYPE,
    PROP_HDR10PLUS_PRESENT,
    cond,
    home_window,
    info,
    localized,
    read_pass,
)
from info.dvinfo import (
    L1_EMPTY,
    L5_EMPTY,
    get_l1_nits,
    get_l5_offsets,
    is_status_label,
    na_label,
)
from info import dvmetadata
from info.mediasource import is_live, is_pvr
from info.properties import (
    publish_scene_properties,
    publish_static_properties,
)

# Home property with the source HDR type (from publish_hdr_type).
_PROP_HDR_TYPE = "TinyPPI.HdrType"


class PropertySink:
    """Stand-in for ``xbmcgui.Window`` that collects property values.

    Only the property methods ``info.properties`` uses are provided.
    """

    __slots__ = ("values",)

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setProperty(self, name: str, value: str) -> None:
        self.values[str(name)] = "" if value is None else str(value)

    def getProperty(self, name: str) -> str:
        return self.values.get(name, "")

    def clearProperty(self, name: str) -> None:
        self.values.pop(name, None)


# --- Row definitions -------------------------------------------------------

def S(key: str, prefix: str = "", suffix: str = "") -> tuple[str, str, str]:
    """Return a value segment: ``prefix + value + suffix``, or '' if empty.

    Same shape as the skin's ``$INFO[key,prefix,suffix]``.
    """
    return (key, prefix, suffix)


# Rows: (label string id, value segments, detail segments).  The detail is
# what the overlay shows in its accent color.
_VIDEO = (
    (32219, (S("DisplayModeVar"),), ()),
    (32220, (S("VideoResolutionVar"),), ()),
    (32221, (S("VideoPixelFormatVar"),), (S("DoviTunnelVar", "(", ")"),)),
    (32222, (S("VideoBitDepthVar"),), ()),
    (32223, (S("AspectRatioVar", "", ":1"),), (S("ImaxVar", "(", ")"),)),
    (32224, (S("VideoDecoderNameVar"), S("VideoCodecVar")),
            (S("VideoDecoderVar", "(", ")"),)),
    (32225, (S("VideoDecoderLongVar"),), ()),
)

_PROCESSING = (
    (32227, (S("DoviProfileVar"),), ()),
    (32231, (S("ModeVar"),), ()),
    (32232, (S("GamutVar"),), ()),
    (32229, (S("VideoBitrateRow"),), (S("VideoBitrateDetail"),)),
    (32233, (S("MediaSourceVar"),), ()),
    (32234, (S("PlaybackStateRow"), S("PlaybackTimeRow"),
             S("PlaybackDurationRow", " / ", "")),
            (S("PlaybackProgressRow", "(", "%)"),)),
)

_AUDIO = (
    # AudioCodecSpatialVar already includes its parentheses.
    (32238, (S("AudioCodecVar"), S("AudioChannelsVar", " ", "")),
             (S("AudioCodecSpatialVar"),)),
    (32239, (S("AudioBitDepthVar", "", " / "), S("AudioSampleRateVar")), ()),
    (32240, (S("AudioChannelsInputVar"),), ()),
    (32241, (S("AudioOutputRow"),), ()),
    (32229, (S("AudioBitrateRow"),), (S("AudioBitrateDetail"),)),
    (32244, (S("AudioNameShortVar"), S("AudioNameVar", " | ", "")), ()),
    (32245, (S("SubtitleStateRow"), S("SubtitleShortRow"),
             S("SubtitleNameRow", " | ", "")),
            (S("SubtitleCodecRow", "(", ")"),)),
)

_SYSTEM = (
    (32248, (S("FpsInfoVar"), S("FpsDropVar", " = ", " FPS")), ()),
    (32249, (S("CpuTopUsageVar", "", " |"), S("CpuUsageVar", " ", "")), ()),
    (32250, (S("CpuTemperature"),), ()),
    (32251, (S("MemoryUsed"),), ()),
    (32252, (S("PlayerCacheLevel", "", "%"),), ()),
    (32253, (S("VideoQueueLevel", "", "%"), S("VideoQueueDataLevel", " | ", "%")), ()),
    (32254, (S("AudioQueueLevel", "", "%"), S("AudioQueueDataLevel", " | ", "%")), ()),
)

_HDR_STATIC = (
    (32256, (S("Hdr10MdlVar"),), ()),
    (32257, (S("Hdr10MaxCllFallVar"),), ()),
)

# Dolby Vision stream facts: profile, versions and layers.
_DOLBY_VISION = (
    (32261, (S("DoviProfileNumberVar"),), ()),
    (32260, (S("DoviVersionVar"),), ()),
    (32258, (S("DoviCmVersionVar"),), ()),
    (32259, (S("DoviStructureVar"),), ()),
    (32262, (S("DoviRpuPresentFlag"), S("DoviBlPresentFlag", " | ", "")), ()),
    (32263, (S("DoviElPresentFlag"),), (S("DoviElTypeVar", "(", ")"),)),
)

# RPU readings (mastering display, frame luminance, active area); shown in
# one "Metadata" card (#32264) with the static readings, as in the overlay.
_DV_METADATA = (
    (32265, (S("DoviRpuMdlVar"),), ()),
    (32267, (S("DoviLevel6RpuMaxCllFallVar"),), ()),
    (32269, (S("DoviLevel1FllVar"),), ()),
    (32270, (S("DoviLevel1PqVar"),), ()),
    (32271, (S("DoviLevel5OffsetsVar"),), ()),
)


def _always(source: str) -> bool:
    return True


def _is_dv(source: str) -> bool:
    """Return whether *source* is Dolby Vision (the only one with an RPU)."""
    return "dolby" in source


def _is_hdr(source: str) -> bool:
    """Return whether *source* is HDR (empty means SDR, as in the skin)."""
    return bool(source)


def _is_plain_hdr(source: str) -> bool:
    """Return whether *source* is non-DV HDR.

    Then the static metadata gets its own card; for Dolby Vision it opens
    the Metadata card instead (see ``_GROUPS``).
    """
    return _is_hdr(source) and not _is_dv(source)


# Cards: (group id, title string id, rows, applies-to), in page order.  The
# id lets the page style a card without matching translated titles.
# applies-to hides HDR / DV cards for other sources, since their getters pad
# missing blocks with zeros (see dvinfo._value_or), like the overlay does.
_GROUPS = (
    ("video",      32218, _VIDEO,       _always),
    ("processing", 32226, _PROCESSING,  _always),
    ("audio",      32237, _AUDIO,       _always),
    ("system",     32247, _SYSTEM,      _always),
    ("hdr",        32255, _HDR_STATIC,  _is_plain_hdr),
    ("dv",         32365, _DOLBY_VISION, _is_dv),
    # Two entries with the same id form one card (see _groups).
    ("metadata",   32264, _HDR_STATIC,   _is_dv),
    ("metadata",   32264, _DV_METADATA,  _is_dv),
)

# Readings taken directly from Kodi, under the keys the rows use.
_EXTRA_INFOLABELS = (
    ("PlayerTime",          "Player.Time"),
    ("PlayerDuration",      "Player.Duration"),
    # End time from Kodi's clock in the box's regional format; computing it
    # on the phone could disagree with the TV.
    ("PlayerFinishTime",    "Player.FinishTime"),
    ("PlayerProgress",      "Player.Progress"),
    ("PlayerCacheLevel",    "Player.CacheLevel"),
    ("VideoQueueLevel",     "Player.Process(VideoQueueLevel)"),
    ("VideoQueueDataLevel", "Player.Process(VideoQueueDataLevel)"),
    ("AudioQueueLevel",     "Player.Process(AudioQueueLevel)"),
    ("AudioQueueDataLevel", "Player.Process(AudioQueueDataLevel)"),
    ("AudioChannelsSink",   "Player.Process(audiochannelssink)"),
    ("CpuTemperature",      "System.CPUTemperature"),
    ("MemoryUsed",          "System.Memory(used.percent)"),
    ("Title",               "VideoPlayer.Title"),
    ("Filename",            "Player.Filename"),
    # Details for the now-playing card; empty for non-library files.
    ("Year",                "VideoPlayer.Year"),
    ("Genre",               "VideoPlayer.Genre"),
    ("Show",                "VideoPlayer.TVShowTitle"),
    ("Season",              "VideoPlayer.Season"),
    ("Episode",             "VideoPlayer.Episode"),
)

# Presence flags (true / false / '') as markers; the browser shows icons,
# copied reports use localized words.
_PRESENCE_GLYPH = {"true": "✔", "false": "✘"}
_PRESENCE_WORD = {
    xbmc.getLocalizedString(107): _PRESENCE_GLYPH["true"],
    xbmc.getLocalizedString(106): _PRESENCE_GLYPH["false"],
}

_PRESENCE_FLAGS = (
    ("DoviRpuPresentFlag", "DoviRpuPresentVar"),
    ("DoviBlPresentFlag",  "DoviBlPresentVar"),
    ("DoviElPresentFlag",  "DoviElPresentVar"),
)

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Kodi text markup (e.g. the themed FEL/MEL tag) is stripped rather than
# turned into HTML, which would mean building HTML from file names.
_MARKUP_RE = re.compile(r"\[/?(?:COLOR|B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|CR)[^\]]*\]",
                        re.IGNORECASE)


# The overlay's "l" separator (see properties._DISPLAY_SEPARATOR) is turned
# back into a pipe for the browser.
_SEPARATOR_RE = re.compile(r" l ")


def clean_value(value: str) -> str:
    """Return *value* without markup and with pipe separators."""
    if not value:
        return value
    return _SEPARATOR_RE.sub(" | ", _MARKUP_RE.sub("", value)).strip()


def _render(segments, values: dict[str, str]) -> str:
    """Concatenate the non-empty segments with their prefixes and suffixes.

    Empty segments drop their separators too; spacing comes from the
    prefixes, like the skin's ``$INFO``.
    """
    out = []
    for key, prefix, suffix in segments:
        value = clean_value(values.get(key, ""))
        if value:
            out.append(f"{prefix}{value}{suffix}")
    return "".join(out).strip()


def _numbers(value: str) -> list[float]:
    """Return every number in a composite reading."""
    if not value or is_status_label(value):
        return []
    return [float(match) for match in _NUMBER_RE.findall(value)]


def _first_number(value: str) -> float | None:
    numbers = _numbers(value)
    return numbers[0] if numbers else None


def _is_live_tv() -> bool:
    """Return whether a live PVR channel (TV or radio) is playing."""
    return cond("PVR.IsPlayingTV") or cond("PVR.IsPlayingRadio")


def _seconds(clock: str) -> int | None:
    """Return ``hh:mm:ss`` or ``mm:ss`` as seconds, or None."""
    try:
        parts = [int(part) for part in clock.strip().split(":")]
    except ValueError:
        return None
    if not 2 <= len(parts) <= 3:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def _broadcast_times() -> dict[str, str]:
    """Return position, length and progress of a live broadcast from the EPG.

    On live TV the player only knows the timeshift buffer.  Without EPG data
    the player's readings stay.
    """
    if not _is_live_tv():
        return {}
    duration = info("PVR.EpgEventDuration(hh:mm:ss)")
    if not any(_numbers(duration)):
        return {}
    elapsed = info("PVR.EpgEventElapsedTime(hh:mm:ss)")
    # Computed: PVR.EpgEventProgress is empty as a label.
    length, position = _seconds(duration), _seconds(elapsed)
    progress = (f"{min(100.0, max(0.0, position * 100 / length)):.1f}"
                if length and position is not None else "")
    return {
        "PlayerTime":       elapsed,
        "PlayerDuration":   duration,
        "PlayerProgress":   progress,
        "PlayerFinishTime": info("VideoPlayer.EndTime"),
        "BroadcastTimes":   "1",
    }


def _label(string_id: int) -> str:
    return localized(string_id)


def _bitrate_row(live: str, average: str) -> tuple[str, str]:
    """Return a bitrate row as the overlay shows it: ``live -`` ``(Ø avg)``."""
    if live and average:
        return f"{live} -", f"(Ø {average})"
    return live or average, ""


def _overlay_rows(values: dict[str, str]) -> dict[str, str]:
    """Return the rows the skin chooses between labels for.

    Mirrors the skin's conditional labels (Passthrough, Disabled, Live TV,
    ...), so the page shows what the TV shows.
    """
    rows: dict[str, str] = {}

    # Output: Passthrough, the sink's channels or Decoding; N/A (empty)
    # without an audio codec, like the other audio rows.
    if not info("VideoPlayer.AudioCodec").strip():
        rows["AudioOutputRow"] = ""
    elif cond("Player.Passthrough"):
        rows["AudioOutputRow"] = _label(32242)
    else:
        rows["AudioOutputRow"] = (values.get("AudioChannelsSink", "")
                                  or _label(32243))

    rows["VideoBitrateRow"], rows["VideoBitrateDetail"] = _bitrate_row(
        values.get("VideoLiveBitrateVar", ""), values.get("VideoBitrateMBVar", ""))
    rows["AudioBitrateRow"], rows["AudioBitrateDetail"] = _bitrate_row(
        values.get("AudioLiveBitrateVar", ""), values.get("AudioBitrateKBVar", ""))

    # Subtitles: the track when on, Disabled when off, N/A without any.
    if cond("VideoPlayer.HasSubtitles") and cond("VideoPlayer.SubtitlesEnabled"):
        rows["SubtitleShortRow"] = values.get("SubtitleNameShortVar", "")
        rows["SubtitleNameRow"] = values.get("SubtitleNameVar", "")
        rows["SubtitleCodecRow"] = values.get("SubtitleCodecVar", "")
    elif cond("VideoPlayer.HasSubtitles"):
        rows["SubtitleStateRow"] = _label(32246)

    # Live TV without EPG and streams without a length get a label instead
    # of meaningless times.
    if _is_live_tv() and not values.get("BroadcastTimes"):
        rows["PlaybackStateRow"] = _label(32235)
    elif (not values.get("PlayerDuration")
          and cond("Player.IsInternetStream") and not _is_live_tv()):
        rows["PlaybackStateRow"] = _label(32236)
    elif values.get("PlayerDuration"):
        rows["PlaybackTimeRow"] = values.get("PlayerTime", "")
        rows["PlaybackDurationRow"] = values.get("PlayerDuration", "")
        rows["PlaybackProgressRow"] = values.get("PlayerProgress", "")

    return rows


def _finish_time(values: dict[str, str]) -> str:
    """Return the end time by the clock, or ''.

    Live TV: the broadcast's end from the EPG.  Streams without a length,
    other live items and recordings: ''.  Also '' while the duration is
    still 00:00, which would just show the current time.
    """
    if _is_live_tv():
        if not values.get("BroadcastTimes"):
            return ""
        return values.get("PlayerFinishTime", "")
    if is_live() or is_pvr():
        return ""
    # Covers both an all-zero and an empty duration.
    if not any(_numbers(values.get("PlayerDuration", ""))):
        return ""
    return values.get("PlayerFinishTime", "")


def _web_presence_value(value) -> str:
    """Replace standalone Yes/No parts with icon markers."""
    parts = clean_value(str(value)).split(" | ")
    return " | ".join(_PRESENCE_WORD.get(part, part) for part in parts)


def _metadata_row(kind: str, name: str, value) -> dict:
    """Convert an ``info.dvmetadata`` row for the page (cells stay a list)."""
    if isinstance(value, (list, tuple)):
        return {"kind": kind, "name": clean_value(name),
                "cells": [_web_presence_value(cell) for cell in value]}
    return {"kind": kind, "name": clean_value(name),
            "value": _web_presence_value(value)}


# --- Output ----------------------------------------------------------------


def _output_token(mode: str) -> str:
    """Map the Amlogic output mode to an HDR token ('' for SDR).

    Follows ``ui.splash._amlogic_hdr_token``.
    """
    mode = (mode or "").upper()
    if "DV" in mode or "DOLBY" in mode:
        return "dolbyvision"
    if "HDR10+" in mode or "HDR10PLUS" in mode or "PLUS" in mode:
        return "hdr10+"
    if "HLG" in mode:
        return "hlg"
    if "HDR" in mode:
        return "hdr10"
    return ""


def _output_hdr_type(mode: str, source: str) -> str:
    """Return the output as a source-style token, to detect conversions.

    Unlike ``TinyPPI.EffectiveHdrType`` (a layout choice) this is the real
    output.  An unreadable mode returns *source*, so passthrough is never
    reported as a conversion.
    """
    if not (mode or "").strip():
        return source
    token = _output_token(mode)
    # The source side spells it hdr10plus (see publish_hdr_type).
    return "hdr10plus" if token == "hdr10+" else token


# --- Artwork ---------------------------------------------------------------

# InfoLabels per artwork kind, best first (episode -> show art, file ->
# Kodi's thumbnail).
_ART_LABELS = {
    "poster": ("Player.Art(poster)", "Player.Art(tvshow.poster)",
               "Player.Art(thumb)", "VideoPlayer.Cover"),
    "fanart": ("Player.Art(fanart)", "Player.Art(tvshow.fanart)",
               "VideoPlayer.Fanart"),
}


def _is_skin_texture(path: str) -> bool:
    """Return whether *path* is a skin texture name rather than artwork.

    Kodi answers ``VideoPlayer.Cover`` with ``DefaultVideoCover.png`` for
    files without art; real artwork is always a path or URL.
    """
    return "/" not in path and "\\" not in path


def art_path(kind: str) -> str:
    """Return the raw path of the playing title's artwork *kind*, or ''."""
    for label in _ART_LABELS.get(kind, ()):
        path = info(label).strip()
        if path and not _is_skin_texture(path):
            return path
    return ""


def _art_tags() -> dict:
    """Return a short tag per artwork kind that changes with the picture.

    Used in the image URL, so a poster is fetched once per film.
    """
    tags = {}
    for kind in _ART_LABELS:
        path = art_path(kind)
        tags[kind] = f"{zlib.crc32(path.encode('utf-8', 'replace')):08x}" if path else ""
    return tags


# --- The player ------------------------------------------------------------

def _rpc(method: str, params: dict | None = None) -> dict:
    """Call Kodi's JSON-RPC and return the answer as a dict ({} on failure)."""
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        request["params"] = params
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except Exception:
        return {}
    return answer if isinstance(answer, dict) else {}


# Public alias for web/library.py.
rpc = _rpc


def _video_player_id() -> int | None:
    """Return the video player id, or None when nothing plays."""
    result = _rpc("Player.GetActivePlayers").get("result") or []
    for player in result:
        if isinstance(player, dict) and player.get("type") == "video":
            return player.get("playerid")
    return None


def _chapter_count() -> int:
    """Return the chapter count (only available as an InfoLabel)."""
    try:
        return int(info("Player.ChapterCount") or 0)
    except ValueError:
        return 0


def _stream_label(stream: dict, fallback: str) -> str:
    """Return a track label prefixed with its upper-cased language code.

    Only a separate leading token counts as an existing prefix (``eng`` vs.
    the start of ``English``).
    """
    name = (stream.get("name") or "").strip()
    language = (stream.get("language") or "").strip()
    tag = language.upper() if re.fullmatch(r"[A-Za-z]{2,3}", language) else language
    if name and tag:
        leading_tag = re.compile(
            rf"^{re.escape(language)}(?=$|[\s·|:/-])", re.IGNORECASE
        )
        if leading_tag.search(name):
            return leading_tag.sub(tag, name, count=1)
        return f"{tag} · {name}"
    return name or tag or fallback


def player_controls() -> dict:
    """Return the controllable player state: tracks, volume, mute, chapters.

    Via JSON-RPC, since pickers need full lists with indices.  Only used
    when control is enabled.
    """
    state: dict = {"audio": [], "subtitle": [], "audio_current": -1,
                   "subtitle_current": -1, "subtitle_on": False,
                   "volume": None, "muted": False, "chapters": 0}

    app = _rpc("Application.GetProperties",
               {"properties": ["volume", "muted"]}).get("result") or {}
    if isinstance(app, dict):
        state["volume"] = app.get("volume")
        state["muted"] = bool(app.get("muted"))

    player_id = _video_player_id()
    if player_id is None:
        return state

    # Tells the page whether to show the chapter keys.
    state["chapters"] = _chapter_count()

    properties = _rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["audiostreams", "currentaudiostream",
                       "subtitles", "currentsubtitle", "subtitleenabled"],
    }).get("result") or {}
    if not isinstance(properties, dict):
        return state

    for index, stream in enumerate(properties.get("audiostreams") or []):
        state["audio"].append({
            "index": stream.get("index", index),
            "label": clean_value(_stream_label(stream, f"#{index + 1}")),
        })
    for index, stream in enumerate(properties.get("subtitles") or []):
        state["subtitle"].append({
            "index": stream.get("index", index),
            "label": clean_value(_stream_label(stream, f"#{index + 1}")),
        })

    current_audio = properties.get("currentaudiostream") or {}
    current_sub   = properties.get("currentsubtitle") or {}
    if isinstance(current_audio, dict):
        state["audio_current"] = current_audio.get("index", -1)
    if isinstance(current_sub, dict):
        state["subtitle_current"] = current_sub.get("index", -1)
    state["subtitle_on"] = bool(properties.get("subtitleenabled"))
    return state


def current_track_state() -> dict[str, str]:
    """Return identifying tokens for the active audio and subtitle streams.

    Includes the index (via JSON-RPC), since tracks may share language and
    name.
    """
    player_id = _video_player_id()
    if player_id is None:
        return {"audio": "", "audio_id": "", "subtitle": ""}
    result = _rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["currentaudiostream", "currentsubtitle",
                       "subtitleenabled"],
    }).get("result") or {}
    if not isinstance(result, dict):
        return {"audio": "", "audio_id": "", "subtitle": ""}

    def token(stream: dict) -> str:
        if not isinstance(stream, dict) or stream.get("index") is None:
            return ""
        index = int(stream.get("index", -1))
        label = clean_value(_stream_label(stream, f"#{index + 1}"))
        return f"#{index + 1} · {label}" if label != f"#{index + 1}" else label

    audio_stream = result.get("currentaudiostream") or {}
    audio = token(audio_stream)
    audio_id = (f"#{int(audio_stream.get('index', -1)) + 1}"
                if isinstance(audio_stream, dict)
                and audio_stream.get("index") is not None else "")
    subtitle = (token(result.get("currentsubtitle") or {})
                if result.get("subtitleenabled") else "__off__")
    return {"audio": audio, "audio_id": audio_id, "subtitle": subtitle}


def audio_event_label(values: dict[str, str]) -> str:
    """Return the active audio label, as in the audio card."""
    language = clean_value(values.get("AudioNameShortVar", "")).strip()
    format_parts = (
        clean_value(values.get(key, "")).strip()
        for key in ("AudioCodecVar", "AudioChannelsVar",
                    "AudioCodecSpatialVar")
    )
    audio_format = " ".join(part for part in format_parts if part)
    return " | ".join(part for part in (language, audio_format) if part)


def subtitle_event_label(values: dict[str, str]) -> str:
    """Return the active subtitle label as the card prints it.

    E.g. "DEU | Deutsch (PGS)"; Kodi's stream names are often just "FORCED".
    """
    language = clean_value(values.get("SubtitleNameShortVar", "")).strip()
    name     = clean_value(values.get("SubtitleNameVar", "")).strip()
    codec    = clean_value(values.get("SubtitleCodecVar", "")).strip()
    label = " | ".join(part for part in (language, name) if part)
    return f"{label} ({codec})".strip() if codec else label


# --- Snapshot --------------------------------------------------------------

class SessionLog:
    """History of the playing title: chart samples, events and counters.

    Kept by the producer, so a page opened mid-film gets the full chart.
    Reset for a new title.  Written by the producer and read by request
    threads, so all access goes through the lock.
    """

    #: Seconds between chart samples (enough for an hour-wide chart).
    SAMPLE_INTERVAL = 1.0
    #: One hour of samples; longer films keep the last hour.
    MAX_SAMPLES = 3600
    #: Maximum events kept; the oldest are dropped.
    MAX_EVENTS = 60

    #: How long a track reading must be stable before it counts.  Index
    #: (JSON-RPC) and label (InfoLabels) may update in different ticks; the
    #: event keeps the time the change was first seen.
    TRACK_SETTLE = 1.5

    TEMP_HIGH   = 75.0
    CPU_FULL    = 100.0
    SWITCH_KINDS = frozenset(("vs10", "mode", "audio", "subtitle"))
    WARNING_KINDS = frozenset(("temperature", "cpu"))
    #: How long a finished title's figures are kept after playback stops.
    RETAIN_SECONDS = 600.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset("")

    def reset(self, key: str, title: str = "") -> None:
        """Start a new session for *key* (title and source)."""
        self._key       = key
        self._title     = title
        self._position  = ""
        self._ended     = 0.0
        self._started   = time.monotonic()
        self._samples: list[tuple] = []
        self._events:  list[dict]  = []
        self._seq       = 0
        self._sampled   = 0.0
        self._switches  = 0
        self._warnings  = 0
        # (identity, display label) per watched reading.
        self._watched: dict[str, tuple[str, str]] = {}
        # Changed but not yet settled readings (see _settle).
        self._pending: dict[str, tuple] = {}
        self._temperature_hot = False
        self._cpu_full = False
        self._fps = None

    # --- Writing -----------------------------------------------------------

    def end(self) -> None:
        """Mark the session as ended after playback stopped.

        The figures stay for ``RETAIN_SECONDS`` (or until the next title)
        for the idle page.  Cheap to call on every idle pass.
        """
        with self._lock:
            if not (self._key or self._samples or self._events):
                return
            if not self._ended:
                self._ended = time.monotonic()
                return
            if time.monotonic() - self._ended >= self.RETAIN_SECONDS:
                self.reset("")

    def observe(self, title: str, source: str, metrics: dict, watched: dict,
                position: str) -> None:
        """Add one pass to the session; chart samples use their own interval.

        Sessions are told apart by title and *source* (the file), since titles
        repeat and lengths of live streams grow.
        """
        with self._lock:
            key = f"{title}\n{source}"
            if self._ended or self._is_another_title(title, source, key):
                self.reset(key, title)
            self._position = position
            now = time.monotonic()
            self._note_changes(watched, now, position)
            self._watch_levels(metrics, now, position)
            if now - self._sampled < self.SAMPLE_INTERVAL:
                return
            self._sampled = now
            self._sample(metrics, now)

    def _is_another_title(self, title: str, source: str, key: str) -> bool:
        """Return whether this pass belongs to a different title.

        A half-empty reading is a player winding down, not a new title, so
        the finished title's figures are kept (see ``last``).  Without a
        source, a changed title is enough.
        """
        if not self._key:
            return True            # nothing is being tracked yet
        if key == self._key:
            return False
        if title and source:
            return True            # a whole reading, and a different one
        return bool(title) and title != self._title

    def _note_changes(self, watched: dict, now: float, position: str) -> None:
        """Record events for readings that changed since the last pass.

        Runs on every producer pass (short switches would be missed on the
        sample clock).  The first pass only records the initial values.
        """
        for name, value in watched.items():
            at, at_position = now, position
            if isinstance(value, dict):
                # Two-part reading: wait until settled (see _settle), dated
                # from the first change.
                identity = str(value.get("id") or "").strip()
                label = str(value.get("label") or identity).strip()
                if not identity:
                    continue
                settled = self._settle(name, (identity, label), now, position)
                if settled is None:
                    continue
                at, at_position = settled
            else:
                identity = str(value or "").strip()
                label = identity
                if not identity:
                    continue
            previous = self._watched.get(name)
            self._watched[name] = (identity, label)
            if previous is None or previous[0] == identity:
                continue
            self._add_event(at, at_position, name,
                            {"from": previous[1], "to": label})

    def _settle(self, name: str, current: tuple[str, str], now: float,
                position: str) -> tuple[float, str] | None:
        """Hold a two-part reading back until stable for ``TRACK_SETTLE``.

        Returns the time and position of the first change once settled, else
        None.  Only settled values are committed, so ``from`` is always right.
        """
        if current == self._watched.get(name):
            self._pending.pop(name, None)
            return None
        pending = self._pending.get(name)
        if pending is None:
            self._pending[name] = (current, now, now, position)
            return None
        reading, since, first, first_position = pending
        if reading != current:
            # Changed again: restart the wait, keep the first change time.
            self._pending[name] = (current, now, first, first_position)
            return None
        if now - since < self.TRACK_SETTLE:
            return None
        del self._pending[name]
        return first, first_position

    def _watch_levels(self, metrics: dict, now: float, position: str) -> None:
        """Track warning levels and the frame rate on every pass."""
        temperature = metrics.get("cpu_temp")
        if temperature is not None:
            self._watch_temperature(temperature, now, position)
        cpu = metrics.get("cpu")
        if cpu is not None:
            self._watch_cpu(cpu, now, position)
        fps = metrics.get("fps_in")
        if fps is not None:
            self._watch_fps(fps, now, position)

    def _sample(self, metrics: dict, now: float) -> None:
        """Add one chart sample."""
        level = metrics.get("l1") or {}
        peak  = level.get("max")
        mean  = level.get("avg")
        self._samples.append((
            round(now - self._started, 1), peak, mean,
        ))
        if len(self._samples) > self.MAX_SAMPLES:
            del self._samples[:len(self._samples) - self.MAX_SAMPLES]

    def _watch_temperature(self, temperature: float, now: float,
                           position: str) -> None:
        hot = temperature >= self.TEMP_HIGH
        if hot and not self._temperature_hot:
            self._add_event(now, position, "temperature", {"value": temperature})
        self._temperature_hot = hot

    def _watch_cpu(self, cpu: float, now: float, position: str) -> None:
        full = cpu >= self.CPU_FULL
        if full and not self._cpu_full:
            self._add_event(now, position, "cpu", {"value": cpu})
        self._cpu_full = full

    def _watch_fps(self, fps: float, now: float, position: str) -> None:
        """Record an event when the input frame rate changes.

        The input rate, not the output (which drops with every lost frame).
        Recorded as a transition (see ``eventTrend`` in js/live-panels.js)
        but not counted as a switch: the display mode change is already
        counted.
        """
        try:
            rate = int(round(float(fps)))
        except (TypeError, ValueError):
            return
        if rate <= 0:
            # Not a real rate (not playing yet, or unsettled).
            return
        previous = self._fps
        self._fps = rate
        if previous is None or previous == rate:
            return
        self._add_event(now, position, "fps", {"from": previous, "to": rate})

    def _add_event(self, now: float, position: str, kind: str,
                   detail: dict) -> dict:
        """Add an event, update the counters, and return the event."""
        self._seq += 1
        # Counters change only here, so every event is counted.
        if kind in self.SWITCH_KINDS:
            self._switches += 1
        if kind in self.WARNING_KINDS:
            self._warnings += 1
        event = {
            "t": round(now - self._started, 1),
            "pos": position,
            "kind": kind,
            **detail,
        }
        self._events.append(event)
        if len(self._events) > self.MAX_EVENTS:
            del self._events[:len(self._events) - self.MAX_EVENTS]
        return event

    # --- Reading -----------------------------------------------------------

    def summary(self) -> dict:
        """Return the small per-snapshot summary: counters and event ``seq``.

        A changed ``seq`` tells the page to fetch the history again.
        """
        with self._lock:
            return {
                "seq":      self._seq,
                "switches": self._switches,
                "warnings": self._warnings,
            }

    def last(self) -> dict:
        """Return the finished title's summary for the idle page, or {}."""
        with self._lock:
            if not self._ended or not self._key:
                return {}
            ago = time.monotonic() - self._ended
            if ago >= self.RETAIN_SECONDS:
                return {}
            peaks = [sample[1] for sample in self._samples if sample[1] is not None]
            return {
                "title":    self._title,
                "position": self._position,
                "ago":      int(ago),
                "switches": self._switches,
                "warnings": self._warnings,
                "peak":     max(peaks) if peaks else None,
                "events":   len(self._events),
            }

    def history(self) -> dict:
        """Return the full chart and event list.

        One array per series (compact for 3600 samples); ``now`` is the
        session age, so the page needs no synchronised clock.
        """
        with self._lock:
            return {
                "now":    round(time.monotonic() - self._started, 1),
                "step":   self.SAMPLE_INTERVAL,
                "t":      [sample[0] for sample in self._samples],
                "max":    [sample[1] for sample in self._samples],
                "avg":    [sample[2] for sample in self._samples],
                "events": list(self._events),
                "seq":    self._seq,
                "switches": self._switches,
            }


class SnapshotBuilder:
    """Build one dashboard snapshot per call with the overlay's publishers.

    Keeps a ``published`` dict like the overlay's loop, and refreshes the
    per-title readings on a slower interval.
    """

    #: Seconds between refreshes of the static (per-title) readings.
    STATIC_INTERVAL = 1.0

    def __init__(self) -> None:
        self._sink      = PropertySink()
        self._published: dict[str, str] = {}
        self._static_at = 0.0
        self._sequence  = 0
        self._meta_static: list = []
        self._meta_static_at = 0.0
        #: The playing title's history; served by /api/history.
        self.session    = SessionLog()
        # Player controls, refreshed on the static interval (JSON-RPC).
        self._controls: dict = {}
        self._controls_at = 0.0
        self._track_state: dict[str, str] = {
            "audio": "", "audio_id": "", "subtitle": "",
        }

    def _refresh(self) -> None:
        """Recompute the readings into the sink."""
        now = time.monotonic()
        if now - self._static_at >= self.STATIC_INTERVAL:
            self._static_at = now
            publish_static_properties(self._sink, self._published)
            # Read together with the static half, so track index and label
            # come from the same moment.
            self._track_state = current_track_state()
        publish_scene_properties(self._sink, self._published)

    def _values(self) -> dict[str, str]:
        """Return the sink's values plus the direct Kodi readings."""
        values = dict(self._sink.values)
        for key, label in _EXTRA_INFOLABELS:
            values[key] = info(label)
        values.update(_broadcast_times())
        values.update(_overlay_rows(values))
        for flag_key, source_key in _PRESENCE_FLAGS:
            values[flag_key] = _PRESENCE_GLYPH.get(values.get(source_key, ""), "")
        return values

    @staticmethod
    def _frame() -> dict | None:
        """Return the coded frame size (the L5 offsets' reference)."""
        width  = _first_number(info("Player.Process(videowidth)").replace(",", ""))
        height = _first_number(info("Player.Process(videoheight)").replace(",", ""))
        if not width or not height:
            return None
        return {"w": int(width), "h": int(height)}

    def _metrics(self, values: dict[str, str], is_dv: bool) -> dict:
        """Return the numeric readings the page charts.

        From the raw getters, so no localized units need parsing.  L1 and L5
        exist only in DV and are padded with zeros otherwise (see
        ``_value_or``), so they are only passed for DV and when not padding.
        """
        raw_nits = get_l1_nits()
        raw_bars = get_l5_offsets()
        nits = _numbers(raw_nits) if is_dv and raw_nits != L1_EMPTY else []
        bars = _numbers(raw_bars) if is_dv and raw_bars != L5_EMPTY else []
        # FpsInfoVar is "input - drop" (see core.helpers.fps_display_texts).
        fps  = _numbers(values.get("FpsInfoVar", ""))
        return {
            "l1": {
                "min": nits[0] if len(nits) > 0 else None,
                "max": nits[1] if len(nits) > 1 else None,
                "avg": nits[2] if len(nits) > 2 else None,
            },
            # L5 bars (left | right | top | bottom) and the coded frame, so
            # the page can draw the letterbox.
            "bars": bars if len(bars) == 4 else None,
            "frame": self._frame(),
            "aspect":   _first_number(values.get("AspectRatioVar", "")),
            "fps_in":   fps[0] if len(fps) > 0 else None,
            "fps_drop": fps[1] if len(fps) > 1 else None,
            "fps_out":  _first_number(values.get("FpsDropVar", "")),
            "progress": _first_number(values.get("PlayerProgress", "")),
            "cpu":      _first_number(values.get("CpuUsageVar", "")),
            "cpu_temp": _first_number(values.get("CpuTemperature", "")),
            "memory":   _first_number(values.get("MemoryUsed", "")),
            "cache":    _first_number(values.get("PlayerCacheLevel", "")),
        }

    def _metadata(self, is_dv: bool, enabled: bool) -> list[dict]:
        """Return the DV metadata rows, the same list as the on-screen view.

        Scene rows every tick, static rows on the slower interval, as in
        ``ui.dvmetadata``.  Empty for non-DV sources or when disabled.
        """
        if not (is_dv and enabled):
            self._meta_static = []
            self._meta_static_at = 0.0
            return []

        scene, parsed, origin, carried = dvmetadata.build_scene_rows()
        now = time.monotonic()
        if not self._meta_static or now - self._meta_static_at >= self.STATIC_INTERVAL:
            self._meta_static_at = now
            self._meta_static = dvmetadata.build_static_rows(parsed, origin, carried)

        rows = dvmetadata.join_rows(scene, self._meta_static)
        return [_metadata_row(kind, name, value) for kind, name, value in rows]

    def _groups(self, values: dict[str, str], source: str) -> list[dict]:
        """Return the cards with their rows, grouped like the overlay.

        Empty values read N/A.  Cards without any value, or not applying to
        the source (see ``_GROUPS``), are left out.  Entries sharing an id
        are merged into one card in list order.
        """
        groups: list[dict] = []
        by_id: dict[str, dict] = {}
        for group_id, title_id, rows, applies in _GROUPS:
            if not applies(source):
                continue
            rendered = []
            for label_id, segments, detail in rows:
                value = _render(segments, values)
                rendered.append({
                    "id":     f"{group_id}.{label_id}",
                    "label":  localized(label_id),
                    "value":  value,
                    "detail": _render(detail, values) if value else "",
                })
            if not any(row["value"] for row in rendered):
                continue
            for row in rendered:
                if not row["value"]:
                    row["value"] = na_label()
            group = by_id.get(group_id)
            if group is None:
                group = {
                    "id":    group_id,
                    "title": localized(title_id),
                    "rows":  rendered,
                }
                by_id[group_id] = group
                groups.append(group)
            else:
                group["rows"].extend(rendered)
        return groups

    def _player_controls(self, control: bool) -> dict:
        """Return tracks and volume on the static interval, if control is on."""
        if not control:
            self._controls = {}
            self._controls_at = 0.0
            return {}
        now = time.monotonic()
        if not self._controls or now - self._controls_at >= self.STATIC_INTERVAL:
            self._controls_at = now
            self._controls = player_controls()
        return self._controls

    def _active_tracks(self) -> dict[str, str]:
        """Return the active tracks from the last static refresh."""
        return self._track_state

    def build(self, allow_filename: bool = True, metadata: bool = True,
              control: bool = False, detail: bool = True) -> dict | None:
        """Build one snapshot inside a single read pass.

        One side-data parse per pass (see ``info.dvinfo``).  Without *detail*
        only the session is updated and None is returned while playing (the
        producer's idle mode).
        """
        with read_pass():
            return self._build(allow_filename, metadata, control, detail)

    def _build(self, allow_filename: bool, metadata: bool, control: bool,
               detail: bool) -> dict | None:
        """Build the snapshot inside ``build``'s read pass."""
        playing = cond("Player.HasVideo")
        self._sequence += 1

        if not playing:
            # Drop the last title's values.
            self._sink   = PropertySink()
            self._published = {}
            self._static_at = 0.0
            self._meta_static = []
            self._meta_static_at = 0.0
            self._controls = {}
            self._controls_at = 0.0
            self._track_state = {
                "audio": "", "audio_id": "", "subtitle": "",
            }
            # End the session but keep its figures for the idle page.
            self.session.end()
            return {
                "seq":      self._sequence,
                "playing":  False,
                "groups":   [],
                "metrics":  {},
                "metadata": [],
                "vs10":     vs10_state("", playing=False),
                "session":  self.session.summary(),
                "last":     self.session.last(),
            }

        self._refresh()
        values = self._values()
        home   = home_window()
        source = home.getProperty(_PROP_HDR_TYPE)
        # Lower-cased once for the checks below.
        source_key = source.strip().lower()
        is_dv      = _is_dv(source_key)

        metrics  = self._metrics(values, is_dv)
        vs10     = vs10_state(
            source_key,
            hdr10plus=home.getProperty(PROP_HDR10PLUS_PRESENT) == "1",
        )
        title    = values.get("Title", "")
        position = values.get("PlayerTime", "")

        # Update the session first, so the totals include this pass.  The
        # file name identifies the session; it is only sent if allowed.
        tracks = self._active_tracks()
        audio_identity = tracks.get("audio_id", "") or tracks.get("audio", "")
        # When off, Kodi still reports the old language, so the card label
        # is only used while subtitles are on.
        subtitle = tracks.get("subtitle", "")
        subtitle_label = (subtitle if subtitle == "__off__"
                          else subtitle_event_label(values) or subtitle)
        self.session.observe(
            title,
            values.get("Filename", ""),
            metrics,
            {"vs10": vs10.get("output", ""),
             "mode": values.get("DisplayModeVar", ""),
             "audio": {"id": audio_identity,
                       "label": audio_event_label(values)
                                or tracks.get("audio", "")},
             "subtitle": {"id": subtitle, "label": subtitle_label}},
            position,
        )
        if not detail:
            return None

        return {
            "seq":       self._sequence,
            "playing":   True,
            "paused":    cond("Player.Paused"),
            "title":     title,
            # Respects the overlay's file-name setting.
            "filename":  values.get("Filename", "") if allow_filename else "",
            "hdr_type":  source,
            "effective": home.getProperty(PROP_EFFECTIVE_HDR_TYPE),
            # The real output, for the conversion badge (see
            # _output_hdr_type).
            "output_type": _output_hdr_type(vs10.get("output", ""), source),
            "time":      position,
            "duration":  values.get("PlayerDuration", ""),
            "finish":    _finish_time(values),
            "metrics":   metrics,
            "groups":    self._groups(values, source_key),
            "metadata":  self._metadata(is_dv, metadata),
            "vs10":      vs10,
            "art":       _art_tags(),
            "media":     {
                "year":    values.get("Year", ""),
                "genre":   values.get("Genre", ""),
                "show":    values.get("Show", ""),
                "season":  values.get("Season", ""),
                "episode": values.get("Episode", ""),
            },
            "controls":  self._player_controls(control),
            "session":   self.session.summary(),
        }


# --- VS10 ------------------------------------------------------------------

# Modes per source type, as in the on-screen dialog (see ui.dialog_layout).
# Format names are not translated, like in the dialog.
_VS10_OPTIONS = {
    "sdr": (
        ("original_sdr", "Original"),
        ("hdr10",        "SDR → HDR10"),
        ("dv",           "SDR → Dolby Vision"),
    ),
    "hdr10": (
        ("original_hdr", "HDR10 (Original)"),
        ("sdr8",         "HDR10 → SDR"),
        ("dv",           "HDR10 → Dolby Vision"),
    ),
    "dolby vision": (
        ("original_dv",  "Dolby Vision (Original)"),
        ("sdr8",         "Dolby Vision → SDR"),
    ),
}


def _is_hdr10_plus(key: str) -> bool:
    """Return whether the source token is HDR10+ (either spelling)."""
    return "hdr10plus" in key or "hdr10+" in key


def _has_no_modes(key: str, hdr10plus: bool = False) -> bool:
    """Return whether the source has no VS10 modes.

    HDR10+ and HLG are no VS10 inputs; *hdr10plus* covers DV + HDR10+
    hybrids (from ``TinyPPI.Hdr10PlusPresent``), which read as DV.
    """
    return hdr10plus or _is_hdr10_plus(key) or "hlg" in key


def _options_for(source: str, playing: bool = True,
                 hdr10plus: bool = False) -> tuple:
    """Return the mode buttons for *source*.

    None for sources without modes (see ``_has_no_modes``) or when nothing
    plays; the page then hides the VS10 card.  An empty source is SDR.
    """
    if not playing:
        return ()
    key = (source or "").strip().lower()
    if _has_no_modes(key, hdr10plus):
        return ()
    if "dolby" in key:
        return _VS10_OPTIONS["dolby vision"]
    if "hdr10" in key:
        return _VS10_OPTIONS["hdr10"]
    return _VS10_OPTIONS["sdr"]


def vs10_state(source: str, playing: bool = True,
               hdr10plus: bool = False) -> dict:
    """Return the VS10 buttons for the source and the current output."""
    return {
        "options": [{"mode": mode, "label": label}
                    for mode, label in _options_for(source, playing, hdr10plus)],
        "output":  info("Player.Process(amlogic.eoft_gamut)").split(",")[0].strip(),
    }


# Modes the dashboard accepts: exactly the buttons above.
_KNOWN_MODES = frozenset(
    mode for options in _VS10_OPTIONS.values() for mode, _ in options
)


_log = channel("web")


class _ModeSwitcher:
    """Apply VS10 modes one at a time, the latest request winning.

    A switch takes seconds (display resets, sometimes a stage through SDR).
    Requests arriving meanwhile replace each other, so quick taps on three
    buttons end in the last mode instead of three switches in a row.  Runs
    on a service thread (no ``RunScript``), so the request is not held
    during the driver's settling delays.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # The mode to apply next, and whether a worker is applying modes.
        self._wanted: str | None = None
        self._running = False

    def request(self, mode: str) -> None:
        """Queue *mode*, replacing any mode still waiting."""
        with self._lock:
            if self._wanted is not None:
                _log(f"VS10 mode '{self._wanted}' replaced by '{mode}' "
                     "before it started", xbmc.LOGDEBUG)
            self._wanted = mode
            if self._running:
                return
            self._running = True
        try:
            threading.Thread(target=self._work, name="TinyPPI-vs10",
                             daemon=True).start()
        except RuntimeError as exc:
            with self._lock:
                self._running = False
                self._wanted = None
            _log(f"VS10 mode '{mode}' could not be started: {exc}",
                 xbmc.LOGERROR)

    def _next(self, monitor: xbmc.Monitor) -> str | None:
        """Take the waiting mode, or end the worker (None)."""
        with self._lock:
            mode = self._wanted
            self._wanted = None
            # No new switch during shutdown (it would delay Kodi).
            if mode is None or monitor.abortRequested():
                self._running = False
                return None
            return mode

    def _work(self) -> None:
        monitor = xbmc.Monitor()
        while (mode := self._next(monitor)) is not None:
            try:
                from ui.mode_select import set_mode
                set_mode(mode)
            except Exception as exc:  # a switch must not break the service
                _log(f"VS10 mode '{mode}' failed: {exc}", xbmc.LOGERROR)


_switcher = _ModeSwitcher()


def apply_mode(mode: str) -> bool:
    """Start switching to VS10 *mode*; False for modes not offered."""
    if mode not in _KNOWN_MODES:
        return False
    _switcher.request(mode)
    return True


# --- Player commands -------------------------------------------------------

# Allowed transport commands; requests name an action, never a JSON-RPC
# method.  "volume" (absolute) is no longer used by the page but kept for
# older clients.
_COMMANDS = ("playpause", "stop", "seek", "seek_percent", "volume", "mute",
             "audio", "subtitle", "chapter_previous", "chapter_next",
             "volume_up", "volume_down")

# Maximum relative seek in seconds.
_SEEK_LIMIT = 3600


def _number(value, low: float, high: float) -> float | None:
    """Return *value* as a number within [*low*, *high*], or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or not low <= number <= high:  # NaN fails both
        return None
    return number


def apply_command(action: str, value=None) -> bool:
    """Run a transport command and return whether it succeeded.

    JSON-RPC (not builtins) so success can be reported; False without a
    playing video.
    """
    if action not in _COMMANDS:
        return False

    if action == "volume":
        level = _number(value, 0, 100)
        if level is None:
            return False
        return "result" in _rpc("Application.SetVolume",
                                {"volume": int(level)})

    # Volume and mute are sent as input actions, like a remote, not via
    # Application.SetVolume/SetMute (Kodi's software mixer).  Only the input
    # path lets a CEC adapter forward them to an amplifier; without CEC they
    # change Kodi's volume.  CEC has no absolute level, hence the steps, and
    # the volume Kodi reports may then not match the amplifier's.
    if action in ("volume_up", "volume_down"):
        name = "volumeup" if action == "volume_up" else "volumedown"
        return _rpc("Input.ExecuteAction",
                    {"action": name}).get("result") == "OK"
    if action == "mute":
        return _rpc("Input.ExecuteAction",
                    {"action": "mute"}).get("result") == "OK"

    player_id = _video_player_id()
    if player_id is None:
        return False

    if action == "playpause":
        return "result" in _rpc("Player.PlayPause", {"playerid": player_id})
    if action == "stop":
        return "result" in _rpc("Player.Stop", {"playerid": player_id})
    if action == "seek":
        step = _number(value, -_SEEK_LIMIT, _SEEK_LIMIT)
        if step is None:
            return False
        return "result" in _rpc("Player.Seek", {
            "playerid": player_id, "value": {"seconds": int(step)}})
    if action == "seek_percent":
        where = _number(value, 0, 100)
        if where is None:
            return False
        # Live TV: the bar is the broadcast (see _broadcast_times) but Kodi's
        # percentage is the timeshift buffer's, so seek relatively.
        broadcast = _broadcast_times()
        if broadcast:
            length = _seconds(broadcast["PlayerDuration"])
            now = _seconds(broadcast["PlayerTime"])
            if length is None or now is None:
                return False
            return "result" in _rpc("Player.Seek", {
                "playerid": player_id,
                "value": {"seconds": int(round(length * where / 100 - now))}})
        return "result" in _rpc("Player.Seek", {
            "playerid": player_id, "value": {"percentage": where}})
    if action in ("chapter_previous", "chapter_next"):
        # No JSON-RPC method for chapters; the input action falls back to a
        # big step without chapters, so the count is checked first.
        if _chapter_count() < 2:
            return False
        name = ("chapterorbigstepforward" if action == "chapter_next"
                else "chapterorbigstepback")
        return _rpc("Input.ExecuteAction",
                    {"action": name}).get("result") == "OK"
    if action == "audio":
        index = _number(value, 0, 64)
        if index is None:
            return False
        return "result" in _rpc("Player.SetAudioStream", {
            "playerid": player_id, "stream": int(index)})

    # subtitle: -1 turns them off, any other index selects and enables.
    index = _number(value, -1, 64)
    if index is None:
        return False
    if index < 0:
        return "result" in _rpc("Player.SetSubtitle", {
            "playerid": player_id, "subtitle": "off"})
    return "result" in _rpc("Player.SetSubtitle", {
        "playerid": player_id, "subtitle": int(index), "enable": True})
