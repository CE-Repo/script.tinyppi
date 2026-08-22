"""Build the dashboard's data snapshot out of the overlay's own readings.

``info.properties`` reaches its window through nothing but ``setProperty``
(see ``core.utils.set_changed_properties``), so handing it a collector instead
of an ``xbmcgui.Window`` yields exactly the values the overlay draws -- same
formatting, same units, same N/A labels -- without a second copy of the
computation.  Every row the overlay gains is therefore in the dashboard the
moment it is published.

The layout below mirrors ``script-tinyppi-main.xml`` section for section and
reuses its own string IDs, so the dashboard is translated wherever the overlay
is, and a renamed label moves in both at once.
"""

import json
import re
import threading
import time
import zlib

import xbmc
import xbmcaddon
import xbmcgui
from core.maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP, IMAX_LOGO_MAP
from core.utils import PROP_EFFECTIVE_HDR_TYPE, cond, info
from info.dvinfo import (
    L1_EMPTY,
    L5_EMPTY,
    get_l1_nits,
    get_l5_offsets,
    is_status_label,
)
from info import dvmetadata
from info.imax import imax_logo, is_known_imax_title
from info.properties import (
    publish_scene_properties,
    publish_static_properties,
)

_HOME_WINDOW_ID = 10000

# Home-window property publish_hdr_type writes the source type to.
_PROP_HDR_TYPE = "TinyPPI.HdrType"


class PropertySink:
    """A stand-in for ``xbmcgui.Window`` that keeps the values instead of
    drawing them.

    Only the three property methods exist, which is all ``info.properties``
    ever calls on the window it publishes to -- the progress controls live in
    ``update_static_properties``, which the dashboard does not use.
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
    """One segment of a row's value: ``prefix + value + suffix``, or nothing at
    all when the value is empty.

    The same shape as the skin's own ``$INFO[key,prefix,suffix]``, so a row
    here reads like the label it was lifted from.
    """
    return (key, prefix, suffix)


# (label string ID, value segments, detail segments).  The detail is what the
# overlay writes in its accent color -- the parenthesised extras -- and the
# dashboard dims the same way.
_VIDEO = (
    (32000, (S("DisplayModeVar"),), ()),
    (32001, (S("VideoResolutionVar"),), ()),
    (32023, (S("VideoPixelFormatVar"),), (S("DoviTunnelVar", "(", ")"),)),
    (32099, (S("VideoBitDepthVar"),), ()),
    (32024, (S("AspectRatioVar", "", ":1"),), (S("ImaxVar", "(", ")"),)),
    (32005, (S("VideoDecoderNameVar"), S("VideoCodecVar")),
            (S("VideoDecoderVar", "(", ")"),)),
    (32287, (S("VideoDecoderLongVar"),), ()),
)

_PROCESSING = (
    (32051, (S("DoviProfileVar"),), ()),
    (32070, (S("ModeVar"),), ()),
    (32015, (S("GamutVar"),), ()),
    (32047, (S("VideoLiveBitrateVar"),), (S("VideoBitrateMBVar", "(Ø ", ")"),)),
    (32288, (S("MediaSourceVar"),), ()),
    (32013, (S("PlayerTime"), S("PlayerDuration", " / ", "")),
             (S("PlayerProgress", "(", "%)"),)),
)

_AUDIO = (
    # ``AudioCodecSpatialVar`` is stored as "(Atmos)" / "(IMAX Enhanced)",
    # parentheses and all, so this is the one detail that adds none.
    (32045, (S("AudioCodecVar"), S("AudioChannelsVar", " ", "")),
             (S("AudioCodecSpatialVar"),)),
    (32069, (S("AudioBitDepthVar", "", " | "), S("AudioSampleRateVar")), ()),
    (32429, (S("AudioChannelsInputVar"),), ()),
    (32055, (S("AudioChannelsSink"),), ()),
    (32047, (S("AudioLiveBitrateVar"),), (S("AudioBitrateKBVar", "(Ø ", ")"),)),
    (32052, (S("AudioNameShortVar"), S("AudioNameVar", " | ", "")), ()),
    (32053, (S("SubtitleNameShortVar"), S("SubtitleNameVar", " | ", "")),
             (S("SubtitleCodecVar", "(", ")"),)),
)

_SYSTEM = (
    (32036, (S("FpsInfoVar"), S("FpsDropVar", " = ", " FPS")), ()),
    (32014, (S("CpuTopUsageVar", "", " |"), S("CpuUsageVar", " ", "")), ()),
    (32018, (S("CpuTemperature"),), ()),
    (32034, (S("MemoryUsed"),), ()),
    (32032, (S("PlayerCacheLevel", "", "%"),), ()),
    (32022, (S("VideoQueueLevel", "", "%"), S("VideoQueueDataLevel", " | ", "%")), ()),
    (32025, (S("AudioQueueLevel", "", "%"), S("AudioQueueDataLevel", " | ", "%")), ()),
)

_HDR_STATIC = (
    (32296, (S("Hdr10MdlVar"),), ()),
    (32297, (S("Hdr10MaxCllFallVar"),), ()),
)

# What the stream declares itself to be: the profile, the version behind it,
# and which layers it carries.  Settled before the film was ever played.
_DOLBY_VISION = (
    (32290, (S("DoviProfileNumberVar"),), ()),
    (32291, (S("DoviVersionVar"),), ()),
    (32379, (S("DoviCmVersionVar"),), ()),
    (32380, (S("DoviStructureVar"),), ()),
    (32381, (S("DoviRpuPresentFlag"), S("DoviBlPresentFlag", " | ", "")), ()),
    (32382, (S("DoviElPresentFlag"),), (S("DoviElTypeVar", "(", ")"),)),
)

# And what the RPU says about the picture -- the mastering display it was
# graded on, how bright the frame is, what part of it is picture.  These share
# a card with the static readings above, under the overlay's own Metadata
# heading (#32289), which is where the same two sets sit there.
_DV_METADATA = (
    (32425, (S("DoviRpuMdlVar"),), ()),
    (32426, (S("DoviLevel6RpuMaxCllFallVar"),), ()),
    (32375, (S("DoviLevel1FllVar"),), ()),
    (32376, (S("DoviLevel1PqVar"),), ()),
    (32030, (S("DoviLevel5OffsetsVar"),), ()),
)

def _always(source: str) -> bool:
    return True


def _is_dv(source: str) -> bool:
    """Dolby Vision, the only source with an RPU behind these rows."""
    return "dolby" in source


def _is_hdr(source: str) -> bool:
    """Any HDR source.  ``publish_hdr_type`` leaves the property empty for
    SDR, which is what the skin's own ``String.IsEmpty`` branch tests."""
    return bool(source)


def _is_plain_hdr(source: str) -> bool:
    """HDR that is not Dolby Vision, where the static metadata is all there
    is and stands under its own heading -- as the overlay draws it.  A Dolby
    Vision title carries the same two readings, but there they are the first
    two lines of the Metadata section, above what the RPU says (see
    ``_GROUPS``)."""
    return _is_hdr(source) and not _is_dv(source)


# (group id, title string ID, rows, applies-to).  The ids travel to the browser
# so the page can style a group without matching on a translated title.
#
# The order is the order the page stacks them in, one card under the next: the
# four blocks every title has first -- picture, processing, sound, machine --
# and then the HDR blocks, which only some titles bring and which are the ones
# a viewer scrolls to on purpose.
#
# The applies-to is what keeps the page honest about a source: the RPU-backed
# getters pad an absent block out to zeroes rather than leaving it empty (see
# dvinfo._value_or), so on an SDR title every Dolby Vision row would render a
# row of noughts and every HDR10 row a mastering display nothing declared.
# The overlay solves this by not drawing those panels at all; the groups here
# are left out for the same reason.
_GROUPS = (
    ("video",      32054, _VIDEO,       _always),
    ("processing", 32007, _PROCESSING,  _always),
    ("audio",      32056, _AUDIO,       _always),
    ("system",     32088, _SYSTEM,      _always),
    ("hdr",        32300, _HDR_STATIC,  _is_plain_hdr),
    ("dv",         32472, _DOLBY_VISION, _is_dv),
    # One card out of two entries: what the file declares statically and what
    # the RPU says, in that order, which is the order the overlay's own
    # Metadata section reads in.  Entries sharing an id are one card (see
    # _groups).
    ("metadata",   32289, _HDR_STATIC,   _is_dv),
    ("metadata",   32289, _DV_METADATA,  _is_dv),
)

# Extra readings the overlay takes straight from Kodi rather than through
# info.properties.  Collected under the synthetic keys the rows above name.
_EXTRA_INFOLABELS = (
    ("PlayerTime",          "Player.Time"),
    ("PlayerDuration",      "Player.Duration"),
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
    # What the dashboard's now-playing card prints under the title; each is
    # empty for a file the library knows nothing about, and the card then
    # simply leaves the line out.
    ("Year",                "VideoPlayer.Year"),
    ("Genre",               "VideoPlayer.Genre"),
    ("Show",                "VideoPlayer.TVShowTitle"),
    ("Season",              "VideoPlayer.Season"),
    ("Episode",             "VideoPlayer.Episode"),
)

# The presence flags arrive as ``true`` / ``false`` / '' (unknown).  These
# markers are converted to image icons by the browser and to localized words
# in copied reports.
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

# Kodi's own text markup, which several readings carry: the FEL / MEL tag is
# stored uncoloured and themed at read time (see dvinfo._colourise_el_tag), so
# a value can arrive wrapped in [COLOR ...] tags.  A browser would print those
# literally, and turning them into markup of its own would mean sending HTML
# built out of file names -- so they are stripped and the reading kept plain.
_MARKUP_RE = re.compile(r"\[/?(?:COLOR|B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|CR)[^\]]*\]",
                        re.IGNORECASE)


# properties.py swaps the pipe between a composite value's readings for a
# lowercase ``l``, because that glyph reads more clearly in the overlay's
# narrow font (_DISPLAY_SEPARATOR).  In a browser it reads as a typo, so the
# pipe the metadata view uses is put back.
_SEPARATOR_RE = re.compile(r" l ")


def clean_value(value: str) -> str:
    """Return a reading fit for a browser: markup removed, the overlay's
    display separator swapped back for the pipe."""
    if not value:
        return value
    return _SEPARATOR_RE.sub(" | ", _MARKUP_RE.sub("", value)).strip()


def _render(segments, values: dict[str, str]) -> str:
    """Join the segments whose value is non-empty, dropping the glue of the
    ones that are: a row with nothing to say renders empty rather than as a
    string of stray separators.

    The segments carry their own spacing, the way the skin's ``$INFO`` prefixes
    do, so they are concatenated rather than joined -- ``Decoder`` really does
    print its two readings without a gap.
    """
    out = []
    for key, prefix, suffix in segments:
        value = clean_value(values.get(key, ""))
        if value:
            out.append(f"{prefix}{value}{suffix}")
    return "".join(out).strip()


def _numbers(value: str) -> list[float]:
    """Every number in a composite reading, in order."""
    if not value or is_status_label(value):
        return []
    return [float(match) for match in _NUMBER_RE.findall(value)]


def _first_number(value: str) -> float | None:
    numbers = _numbers(value)
    return numbers[0] if numbers else None


def _web_presence_value(value) -> str:
    """Replace standalone localized Yes/No fields with browser icon markers."""
    parts = clean_value(str(value)).split(" | ")
    return " | ".join(_PRESENCE_WORD.get(part, part) for part in parts)


def _metadata_row(kind: str, name: str, value) -> dict:
    """One ``info.dvmetadata`` row as the page consumes it.

    A trim-table row carries its cells as a list rather than as one string
    (the on-screen view draws each in a fixed slot of its own), so the value
    is passed on as a list where it arrives as one and as text otherwise.
    """
    if isinstance(value, (list, tuple)):
        return {"kind": kind, "name": clean_value(name),
                "cells": [_web_presence_value(cell) for cell in value]}
    return {"kind": kind, "name": clean_value(name),
            "value": _web_presence_value(value)}


# --- Logos -----------------------------------------------------------------


def _output_token(mode: str) -> str:
    """Classify the Amlogic output mode into an ``HDR_LOGO_MAP`` key.

    The output, not the source: a stream VS10 converts to Dolby Vision wears
    the Dolby Vision logo, which is the same thing the splash does with it
    (see ``ui.splash._amlogic_hdr_token``, whose reading this follows).
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
    """The output classified into the tokens the source side is written in, so
    the page can compare the two and name a conversion.

    Not ``TinyPPI.EffectiveHdrType``: that one answers which overlay layout to
    draw and is meant to stay on the source unless a setting says otherwise, so
    it reads the same as the source through every conversion there is.  This
    reads the output itself.

    An unreadable mode field answers with the source rather than with SDR --
    nothing read is not the same as nothing being sent, and a missing value
    must not badge a film that is being passed through untouched.
    """
    if not (mode or "").strip():
        return source
    token = _output_token(mode)
    # The logo maps spell it with the plus; the source side spells it
    # hdr10plus, since Kodi's boolean parser reads + as AND (see
    # publish_hdr_type).  One vocabulary, or every HDR10+ film badges itself.
    return "hdr10plus" if token == "hdr10+" else token


def _logos(values: dict[str, str]) -> dict:
    """The graphics for what is playing, as paths under the media route.

    Each is left empty rather than guessed at: an unknown audio codec has no
    logo, and the page simply prints the name it already has.
    """
    token = _output_token(values.get("ModeVar", ""))
    video = HDR_LOGO_MAP.get(token, HDR_LOGO_MAP[""])
    if token in IMAX_LOGO_MAP and is_known_imax_title():
        video = imax_logo(token) or video

    codec = info("VideoPlayer.AudioCodec").lower().strip()
    return {
        "video": video,
        "audio": AUDIO_LOGO_MAP.get(codec, ""),
    }


# --- Artwork ---------------------------------------------------------------

# Kind -> the info labels to try, best first.  Kodi answers with whichever art
# the item actually has, so an episode falls back to its show's and a file with
# no library entry to the thumbnail Kodi made for it.
_ART_LABELS = {
    "poster": ("Player.Art(poster)", "Player.Art(tvshow.poster)",
               "Player.Art(thumb)", "VideoPlayer.Cover"),
    "fanart": ("Player.Art(fanart)", "Player.Art(tvshow.fanart)",
               "VideoPlayer.Fanart"),
}


def art_path(kind: str) -> str:
    """The raw path Kodi holds for a kind of artwork, or ''."""
    for label in _ART_LABELS.get(kind, ()):
        path = info(label).strip()
        if path:
            return path
    return ""


def _art_tags() -> dict:
    """A short tag per artwork kind, changing only when the picture does.

    The page hangs it on the image's address, so the browser fetches a poster
    once per film rather than once per snapshot -- and swaps it the moment the
    next film brings another.
    """
    tags = {}
    for kind in _ART_LABELS:
        path = art_path(kind)
        tags[kind] = f"{zlib.crc32(path.encode('utf-8', 'replace')):08x}" if path else ""
    return tags


# --- The player ------------------------------------------------------------

def _rpc(method: str, params: dict | None = None) -> dict:
    """One JSON-RPC call into the running Kodi, as a dict (empty on failure)."""
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        request["params"] = params
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except Exception:
        return {}
    return answer if isinstance(answer, dict) else {}


def _video_player_id() -> int | None:
    """The id of the playing video, or None when nothing is playing."""
    result = _rpc("Player.GetActivePlayers").get("result") or []
    for player in result:
        if isinstance(player, dict) and player.get("type") == "video":
            return player.get("playerid")
    return None


def _stream_label(stream: dict, fallback: str) -> str:
    """A track's picker label with a canonical language-code prefix.

    Kodi supplies ISO codes such as ``ger`` and ``eng`` separately from the
    track name.  A substring check cannot tell ``eng`` from the beginning of
    ``English``, so only an already separate leading token suppresses the
    prefix.
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
    """The switchable side of the player: tracks, volume, mute.

    Read over JSON-RPC rather than from info labels, because a picker needs
    the whole list and its indices, not the name of the one in use.  Only
    gathered when the dashboard is allowed to switch anything, since that is
    the only thing it is for.
    """
    state: dict = {"audio": [], "subtitle": [], "audio_current": -1,
                   "subtitle_current": -1, "subtitle_on": False,
                   "volume": None, "muted": False}

    app = _rpc("Application.GetProperties",
               {"properties": ["volume", "muted"]}).get("result") or {}
    if isinstance(app, dict):
        state["volume"] = app.get("volume")
        state["muted"] = bool(app.get("muted"))

    player_id = _video_player_id()
    if player_id is None:
        return state

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
    """Return stable tokens for the active audio and subtitle streams.

    Stream indices are kept deliberately: two tracks can carry the same
    language and name, but changing between them is still a real player event.
    Kodi exposes the active indices only through JSON-RPC.
    """
    player_id = _video_player_id()
    if player_id is None:
        return {"audio": "", "subtitle": ""}
    result = _rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["currentaudiostream", "currentsubtitle",
                       "subtitleenabled"],
    }).get("result") or {}
    if not isinstance(result, dict):
        return {"audio": "", "subtitle": ""}

    def token(stream: dict) -> str:
        if not isinstance(stream, dict) or stream.get("index") is None:
            return ""
        index = int(stream.get("index", -1))
        label = clean_value(_stream_label(stream, f"#{index + 1}"))
        return f"#{index + 1} · {label}" if label != f"#{index + 1}" else label

    audio = token(result.get("currentaudiostream") or {})
    subtitle = (token(result.get("currentsubtitle") or {})
                if result.get("subtitleenabled") else "__off__")
    return {"audio": audio, "subtitle": subtitle}


# --- Snapshot --------------------------------------------------------------

class SessionLog:
    """What the playing title has done so far.

    The producer sees every tick and the browser only the ones it was connected
    for, so the readings that are worth keeping are kept here: the peak the
    grade ever reached, the frames that were lost, the moment an output changed.
    A page that opens halfway through a film still gets the whole picture, and
    the chart is full the second it arrives rather than a minute later.

    Reset by the title changing or by playback ending, since none of it means
    anything about the next film.  Written by the producer thread and read by
    whichever request thread asks for the history, so everything goes through
    the lock.
    """

    #: Seconds between chart samples.  The stream runs five times faster; the
    #: history is what is kept for an hour, and a second's resolution is all
    #: an hour-wide chart can show.
    SAMPLE_INTERVAL = 1.0
    #: An hour of samples.  A longer film keeps its last hour and its totals.
    MAX_SAMPLES = 3600
    #: Events worth scrolling back through; the oldest fall off the end.
    MAX_EVENTS = 60

    #: Cache level that counts as a dip, and the one that ends it.  Two
    #: figures rather than one, so a level hovering at the line writes one
    #: event instead of a hundred.
    CACHE_LOW   = 90.0
    CACHE_CLEAR = 90.0
    TEMP_HIGH   = 75.0
    CPU_FULL    = 100.0
    WARNING_KINDS = frozenset(("cache_low", "temperature", "cpu"))
    #: How long a finished title is kept after the player has stopped.  The
    #: figures are worth most in the minutes right after the credits, which is
    #: exactly when the old behaviour -- throwing them away the moment
    #: playback ended -- had already lost them.
    RETAIN_SECONDS = 600.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset("")

    def reset(self, key: str, title: str = "") -> None:
        """Start over for ``key``, the title this session belongs to."""
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
        self._watched: dict[str, str] = {}
        self._cache_dipped = False
        self._temperature_hot = False
        self._cpu_full = False
        #: The worst drop reading seen since the last chart sample.
        self._drop_peak = 0

    # -- writing --

    def end(self) -> None:
        """Close the session, for a player that has stopped.

        The readings are kept rather than dropped: the peak the grade reached
        and the frames it lost are what a viewer looks for once the credits
        roll, and the page has nothing else to show while nothing is playing.
        They are let go after ``RETAIN_SECONDS``, and the next title lets them
        go the moment it starts (see ``observe``).

        Cheap to call on every idle pass: an already-closed session that is
        still inside its window is left exactly as it is, and an empty one is
        never held at all.
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
        """Fold one pass into the session, sampling on its own slower clock.

        ``source`` is the file being played.  It rather than the title is what
        tells one session from the next, because a title is not unique -- two
        episodes of the same name would otherwise share a session -- and it
        rather than the length, because a length is not steady: a live stream's
        grows as it is watched, and restarting the session under it would leave
        every figure on the page reading zero.
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
            self._sample(metrics, now, position)

    def _is_another_title(self, title: str, source: str, key: str) -> bool:
        """Whether this pass belongs to a different title than the session.

        A reading has to be whole to be believed.  Kodi keeps saying it has a
        video for a tick or two after the labels behind it have emptied, and a
        reading that has lost half of itself is a player winding down rather
        than another film starting: taking it for one would throw away the
        figures of the title that has just finished, which are the very ones
        the page is about to show (see ``last``).

        A source that cannot say what it is playing is a title all the same, so
        where there is no file to compare, a name that changes is enough.
        """
        if not self._key:
            return True            # nothing is being tracked yet
        if key == self._key:
            return False
        if title and source:
            return True            # a whole reading, and a different one
        return bool(title) and title != self._title

    def _note_changes(self, watched: dict, now: float, position: str) -> None:
        """Log the readings that changed since the last pass.

        Off the fast clock, not the sample one: an output switch is over in
        less than a second and would otherwise be missed entirely.  The first
        pass only records what things are, since everything has "changed" then.
        """
        for name, value in watched.items():
            value = (value or "").strip()
            if not value:
                continue
            previous = self._watched.get(name)
            self._watched[name] = value
            if previous is None or previous == value:
                continue
            if name == "vs10":
                self._switches += 1
            self._add_event(now, position, name, {"from": previous, "to": value})

    def _watch_levels(self, metrics: dict, now: float, position: str) -> None:
        """Follow the two readings that come and go between chart samples.

        On the fast clock, like the output switches above and for the same
        reason: dropped frames and an emptying cache are both gone again
        within the second, and watching them from ``_sample`` -- which runs
        once a second where the producer runs five times -- meant most of them
        happened between two looks and left no trace anywhere.
        """
        drop = int(metrics.get("fps_drop") or 0)
        # Held for the chart sample to take, so a burst that came and went
        # inside one second is what that second is drawn and counted as.
        self._drop_peak = max(self._drop_peak, drop)

        cache = metrics.get("cache")
        if cache is not None:
            self._watch_cache(cache, now, position)
        temperature = metrics.get("cpu_temp")
        if temperature is not None:
            self._watch_temperature(temperature, now, position)
        cpu = metrics.get("cpu")
        if cpu is not None:
            self._watch_cpu(cpu, now, position)

    def _sample(self, metrics: dict, now: float, position: str) -> None:
        """Take one chart sample and fold it into the totals."""
        level = metrics.get("l1") or {}
        peak  = level.get("max")
        mean  = level.get("avg")
        cache = metrics.get("cache")

        # The worst second the gauge showed since the last sample, not
        # whatever it happens to read at this instant: the reading is the
        # frames lost over the last second, and it is looked at five times as
        # often as this runs (see _watch_levels).
        drop = self._drop_peak
        self._drop_peak = 0
        self._samples.append((
            round(now - self._started, 1), peak, mean, drop, cache,
        ))
        if len(self._samples) > self.MAX_SAMPLES:
            del self._samples[:len(self._samples) - self.MAX_SAMPLES]

    def _watch_cache(self, cache: float, now: float, position: str) -> None:
        if not self._cache_dipped and cache < self.CACHE_LOW:
            self._cache_dipped = True
            self._add_event(now, position, "cache_low", {"value": cache})
        elif self._cache_dipped and cache > self.CACHE_CLEAR:
            self._cache_dipped = False
            self._add_event(now, position, "cache_recovered", {"value": cache})

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

    def _add_event(self, now: float, position: str, kind: str,
                   detail: dict) -> dict:
        """Add one event and hand it back, for a caller that keeps following
        what it recorded."""
        self._seq += 1
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

    # -- reading --

    def summary(self) -> dict:
        """The figures small enough to travel with every snapshot: the two
        tiles counting up over the title, and the sequence number.

        ``seq`` is what tells the page there is something new to fetch: it
        counts events, so a page holding an older number knows to ask for the
        history again instead of being sent one five times a second.

        Everything else the title adds up to is in the samples themselves, and
        travels with the history the chart asks for rather than five times a
        second with this.
        """
        with self._lock:
            return {
                "seq":      self._seq,
                "switches": self._switches,
                "warnings": self._warnings,
            }

    def last(self) -> dict:
        """What the title that just finished came to, for the idle page.

        Empty while something is playing and again once the window has run
        out, so the page has one thing to test: either there is a last title
        to show or there is not.
        """
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
        """The whole chart and the whole event list, for a page that asks.

        Sent as one array per reading rather than an object per sample: an
        hour of samples is 3600 of them, and the names would be most of the
        bytes.  ``now`` is the session's age as the answer leaves, so the page
        can place each sample against the present without either clock
        agreeing with the other.
        """
        with self._lock:
            return {
                "now":    round(time.monotonic() - self._started, 1),
                "step":   self.SAMPLE_INTERVAL,
                "t":      [sample[0] for sample in self._samples],
                "max":    [sample[1] for sample in self._samples],
                "avg":    [sample[2] for sample in self._samples],
                "drop":   [sample[3] for sample in self._samples],
                "cache":  [sample[4] for sample in self._samples],
                "events": list(self._events),
                "seq":    self._seq,
            }


class SnapshotBuilder:
    """Produces one dashboard snapshot per call, reusing the overlay's own
    publishers.

    Holds the ``published`` dict those publishers use to skip unchanged
    writes, exactly as the overlay's poll loop does, so an idle frame costs a
    recompute and no more.  The static half is refreshed on its own slower
    cadence for the same reason it is in the overlay: those readings settle at
    most once a title.
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
        #: The running title's history and totals; read by /api/history.
        self.session    = SessionLog()
        # The switchable side of the player, refreshed on the static clock:
        # a picker needs whole track lists, which cost a JSON-RPC round trip
        # and settle at most once a title.
        self._controls: dict = {}
        self._controls_at = 0.0
        self._track_state: dict[str, str] = {"audio": "", "subtitle": ""}
        self._track_state_at = 0.0

    def _refresh(self) -> None:
        """Recompute the readings into the sink, static half on its own timer."""
        now = time.monotonic()
        if now - self._static_at >= self.STATIC_INTERVAL:
            self._static_at = now
            publish_static_properties(self._sink, self._published)
        publish_scene_properties(self._sink, self._published)

    def _values(self) -> dict[str, str]:
        """The sink's readings plus the ones taken straight from Kodi."""
        values = dict(self._sink.values)
        for key, label in _EXTRA_INFOLABELS:
            values[key] = info(label)
        for flag_key, source_key in _PRESENCE_FLAGS:
            values[flag_key] = _PRESENCE_GLYPH.get(values.get(source_key, ""), "")
        return values

    @staticmethod
    def _frame() -> dict | None:
        """The coded frame size, which the L5 offsets are measured against."""
        width  = _first_number(info("Player.Process(videowidth)").replace(",", ""))
        height = _first_number(info("Player.Process(videoheight)").replace(",", ""))
        if not width or not height:
            return None
        return {"w": int(width), "h": int(height)}

    def _metrics(self, values: dict[str, str], is_dv: bool) -> dict:
        """The numeric side of the snapshot: what the page charts rather than
        prints.  Read from the raw getters, not the formatted rows, so the
        page never has to parse a localized unit back off a string.

        L1 and L5 live in the Dolby Vision RPU and nowhere else, and both
        getters pad an absent block out to zeroes rather than leave it empty
        (see ``_value_or``).  Charting those zeroes would draw a black film
        for every HDR10 title, so they are only passed on for a source that
        can actually carry them, and only when they read as something other
        than that padding.
        """
        raw_nits = get_l1_nits()
        raw_bars = get_l5_offsets()
        nits = _numbers(raw_nits) if is_dv and raw_nits != L1_EMPTY else []
        bars = _numbers(raw_bars) if is_dv and raw_bars != L5_EMPTY else []
        # ``FpsInfoVar`` is the "input - drop" pair; ``FpsDropVar`` is what is
        # left over, i.e. the output rate (see core.helpers.fps_display_texts).
        fps  = _numbers(values.get("FpsInfoVar", ""))
        return {
            "l1": {
                "min": nits[0] if len(nits) > 0 else None,
                "max": nits[1] if len(nits) > 1 else None,
                "avg": nits[2] if len(nits) > 2 else None,
            },
            # left | right | top | bottom, in coded pixels, alongside the
            # coded frame they are offsets into: together they are enough for
            # the page to draw the letterbox the RPU declares.
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
        """The Dolby Vision metadata view's rows, the same list the on-screen
        view is built from.

        Split across the two cadences exactly as ``ui.dvmetadata`` splits it:
        the per-frame blocks (L1, L2, L4, L5, L8, HDR10+) are rebuilt every tick,
        the title-level ones on the slower timer, and ``join_rows`` decides the
        separator between them against whichever scene rows are current -- so
        the halves cannot disagree about the shape of the joined list.

        Only a Dolby Vision source has an RPU to walk, so anything else gets an
        empty list and the page leaves the section out.
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

    def _groups(self, values: dict[str, str], addon, source: str) -> list[dict]:
        """The printed rows, grouped and titled the way the overlay is.

        A row whose value renders empty is left out entirely rather than shown
        blank: the panels a stream does not carry then simply do not appear,
        which is what makes the page readable on a phone.  A whole group whose
        source cannot carry it goes the same way (see ``_GROUPS``).

        Several entries may name the same card, and then its rows are those
        of each entry that applies, in the order the entries are listed --
        which is how the Metadata card holds the static readings of a source
        that carries them and the RPU's own of a source that has an RPU,
        without either set having to know about the other.
        """
        groups: list[dict] = []
        by_id: dict[str, dict] = {}
        for group_id, title_id, rows, applies in _GROUPS:
            if not applies(source):
                continue
            rendered = []
            for label_id, segments, detail in rows:
                value = _render(segments, values)
                if not value:
                    continue
                rendered.append({
                    "id":     f"{group_id}.{label_id}",
                    "label":  addon.getLocalizedString(label_id),
                    "value":  value,
                    "detail": _render(detail, values),
                })
            if not rendered:
                continue
            group = by_id.get(group_id)
            if group is None:
                group = {
                    "id":    group_id,
                    "title": addon.getLocalizedString(title_id),
                    "rows":  rendered,
                }
                by_id[group_id] = group
                groups.append(group)
            else:
                group["rows"].extend(rendered)
        return groups

    def _player_controls(self, control: bool) -> dict:
        """The track lists and volume, on the static clock.

        Only while the dashboard may switch something: the lists exist to be
        picked from, and a read-only page would pay two JSON-RPC calls a
        second for a picker it never draws.
        """
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
        """Active tracks, refreshed at most once per static interval."""
        now = time.monotonic()
        if now - self._track_state_at >= self.STATIC_INTERVAL:
            self._track_state_at = now
            self._track_state = current_track_state()
        return self._track_state

    def build(self, addon=None, allow_filename: bool = True,
              metadata: bool = True, control: bool = False) -> dict:
        """One complete snapshot.  Cheap enough for the producer's cadence:
        the whole pass shares a single side-data parse (see ``info.dvinfo``)
        and writes nothing to any window Kodi draws."""
        addon = addon or xbmcaddon.Addon()
        playing = cond("Player.HasVideo")
        self._sequence += 1

        if not playing:
            # Nothing to read; the sink keeps the last title's values, so drop
            # them rather than let the page show a film that has ended.  The
            # session goes with them: none of what it holds is about the next.
            self._sink   = PropertySink()
            self._published = {}
            self._static_at = 0.0
            self._meta_static = []
            self._meta_static_at = 0.0
            self._controls = {}
            self._controls_at = 0.0
            self._track_state = {"audio": "", "subtitle": ""}
            self._track_state_at = 0.0
            # Closed rather than thrown away: what the title came to is worth
            # more once it has ended than at any point while it ran, and the
            # page has nothing else to show until the next one starts.
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
        home   = xbmcgui.Window(_HOME_WINDOW_ID)
        source = home.getProperty(_PROP_HDR_TYPE)
        # Lower-cased once: every branch below asks the same question of it.
        source_key = source.strip().lower()
        is_dv      = _is_dv(source_key)

        metrics  = self._metrics(values, is_dv)
        vs10     = vs10_state(source_key)
        title    = values.get("Title", "")
        position = values.get("PlayerTime", "")

        # Folded in before the snapshot is handed over, so the totals the page
        # is about to print already include the pass it is printing.  The file
        # name is what tells one session from the next and is never sent with
        # them: the overlay's own setting governs what leaves the box, and this
        # is read whether it is on or not.
        tracks = self._active_tracks()
        self.session.observe(
            title,
            values.get("Filename", ""),
            metrics,
            {"vs10": vs10.get("output", ""),
             "mode": values.get("DisplayModeVar", ""),
             "audio": tracks.get("audio", ""),
             "subtitle": tracks.get("subtitle", "")},
            position,
        )

        return {
            "seq":       self._sequence,
            "playing":   True,
            "paused":    cond("Player.Paused"),
            "title":     title,
            # The overlay's own file-name setting governs this too: turning it
            # off must not leave the path leaking over the network instead.
            "filename":  values.get("Filename", "") if allow_filename else "",
            "hdr_type":  source,
            "effective": home.getProperty(PROP_EFFECTIVE_HDR_TYPE),
            # What is actually going out, for the conversion badge; see
            # _output_hdr_type for why "effective" cannot answer that.
            "output_type": _output_hdr_type(vs10.get("output", ""), source),
            "time":      position,
            "duration":  values.get("PlayerDuration", ""),
            "metrics":   metrics,
            "groups":    self._groups(values, addon, source_key),
            "metadata":  self._metadata(is_dv, metadata),
            "vs10":      vs10,
            # What the overlay draws for this format, for the page to draw too.
            "logos":     _logos(values),
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

# The modes offered per source type, mirroring the groups the on-screen
# dialog shows (see ``_ACTIONS`` in ui.mode_select).  The labels name formats
# rather than words, so they are left untranslated exactly as the dialog's are.
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
    """Whether the lower-cased source token names HDR10+.

    Both spellings are read: the Home window carries ``hdr10plus`` (see
    ``info.properties.publish_hdr_type``, which avoids the ``+`` Kodi's boolean
    parser would take for an AND), while ``get_hdr_format`` names the format
    itself ``hdr10+``.
    """
    return "hdr10plus" in key or "hdr10+" in key


def _has_no_modes(key: str) -> bool:
    """Whether the lower-cased source token names a format VS10 cannot convert.

    HDR10+ and HLG are the two, and neither is a VS10 input: the driver has no
    group for either, and the on-screen dialog now draws none for either --
    both are left with the player-process button alone (see
    script-tinyppi-dialog.xml).
    """
    return _is_hdr10_plus(key) or "hlg" in key


def _options_for(source: str, playing: bool = True) -> tuple:
    """The mode buttons that apply to ``source``.

    ``hdr10plus`` and ``hlg`` get none -- see ``_has_no_modes``: neither is a
    VS10 input, so the dialog leaves both with the player-process button alone.
    The page follows: with no options the whole VS10 card goes, output line
    included, rather than offer a conversion that is not on offer anywhere
    else.

    An **empty** source is SDR, not "unknown": ``publish_hdr_type`` writes a
    token only for the HDR formats, and the dialog's own SDR group is the one
    behind ``String.IsEmpty``.  So the buttons otherwise only fall away when
    nothing is playing at all and there is no source to convert.
    """
    if not playing:
        return ()
    key = (source or "").strip().lower()
    if _has_no_modes(key):
        return ()
    if "dolby" in key:
        return _VS10_OPTIONS["dolby vision"]
    if "hdr10" in key:
        return _VS10_OPTIONS["hdr10"]
    return _VS10_OPTIONS["sdr"]


def vs10_state(source: str, playing: bool = True) -> dict:
    """What the dashboard needs to draw its VS10 controls: the buttons that
    apply to the playing source, and the output the driver is in now."""
    return {
        "options": [{"mode": mode, "label": label}
                    for mode, label in _options_for(source, playing)],
        "output":  info("Player.Process(amlogic.eoft_gamut)").split(",")[0].strip(),
    }


# Every mode the dashboard will act on: the union of the buttons above, which
# is the same set the on-screen dialog offers.  Checked here so a request can
# only ever ask for a mode the page itself presents, and so the request thread
# never has to import the dialog module to find out what is valid.
_KNOWN_MODES = frozenset(
    mode for options in _VS10_OPTIONS.values() for mode, _ in options
)


def apply_mode(mode: str) -> bool:
    """Apply a VS10 mode by name, returning False for one the dashboard does
    not offer.

    Goes through the documented ``RunScript`` entry point rather than calling
    ``ui.mode_select`` here: that runs the switch in its own interpreter, the
    same way a keymap shortcut does, so a native VS10 action is fired from the
    context it is fired from everywhere else, this request thread is not held
    for the driver's settling delays, and ``set_mode`` still validates the
    name itself on the far side.
    """
    if mode not in _KNOWN_MODES:
        return False
    xbmc.executebuiltin(f"RunScript(script.tinyppi,run_mode,{mode})")
    return True


# --- Player commands -------------------------------------------------------

# What the dashboard's transport row may ask for.  A fixed set, checked before
# anything reaches Kodi: the request names an action, never a JSON-RPC method,
# so the page can only ever do these seven things.
_COMMANDS = ("playpause", "stop", "seek", "seek_percent", "volume", "mute",
             "audio", "subtitle")

# How far a seek button may jump, in seconds.  Bounded so a malformed value
# cannot ask the player for something absurd.
_SEEK_LIMIT = 3600


def _number(value, low: float, high: float) -> float | None:
    """``value`` as a number inside ``[low, high]``, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or not low <= number <= high:  # NaN fails both
        return None
    return number


def apply_command(action: str, value=None) -> bool:
    """Act on one transport command, returning whether it was carried out.

    Everything goes through JSON-RPC into the running player rather than
    through a builtin: the page needs to know whether the thing happened, and
    a builtin is fire-and-forget.  A command that names no playing video is
    False rather than a silent no-op, so the page can say so.
    """
    if action not in _COMMANDS:
        return False

    if action == "volume":
        level = _number(value, 0, 100)
        if level is None:
            return False
        return "result" in _rpc("Application.SetVolume",
                                {"volume": int(level)})
    if action == "mute":
        return "result" in _rpc("Application.SetMute", {"mute": "toggle"})

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
        return "result" in _rpc("Player.Seek", {
            "playerid": player_id, "value": {"percentage": where}})
    if action == "audio":
        index = _number(value, 0, 64)
        if index is None:
            return False
        return "result" in _rpc("Player.SetAudioStream", {
            "playerid": player_id, "stream": int(index)})

    # subtitle: -1 turns them off, anything else picks that track and turns
    # them on -- one control on the page, so one command here.
    index = _number(value, -1, 64)
    if index is None:
        return False
    if index < 0:
        return "result" in _rpc("Player.SetSubtitle", {
            "playerid": player_id, "subtitle": "off"})
    return "result" in _rpc("Player.SetSubtitle", {
        "playerid": player_id, "subtitle": int(index), "enable": True})
