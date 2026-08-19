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

import re
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import PROP_EFFECTIVE_HDR_TYPE, cond, info
from info.dvinfo import (
    L1_EMPTY,
    L5_EMPTY,
    get_l1_nits,
    get_l5_offsets,
    is_status_label,
)
from info import dvmetadata
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
    (32069, (S("AudioBitDepthVar", "", " / "), S("AudioSampleRateVar")), ()),
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
    (32022, (S("VideoQueueLevel", "", "%"), S("VideoQueueDataLevel", " / ", "%")), ()),
    (32025, (S("AudioQueueLevel", "", "%"), S("AudioQueueDataLevel", " / ", "%")), ()),
)

_HDR_STATIC = (
    (32296, (S("Hdr10MdlVar"),), ()),
    (32297, (S("Hdr10MaxCllFallVar"),), ()),
)

_DOLBY_VISION = (
    (32290, (S("DoviProfileNumberVar"),), ()),
    (32291, (S("DoviVersionVar"),), ()),
    (32379, (S("DoviCmVersionVar"),), ()),
    (32380, (S("DoviStructureVar"),), ()),
    (32381, (S("DoviRpuPresentFlag"), S("DoviBlPresentFlag", " / ", "")), ()),
    (32382, (S("DoviElPresentFlag"),), (S("DoviElTypeVar", "(", ")"),)),
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


# (group id, title string ID, rows, applies-to).  The ids travel to the browser
# so the page can style a group without matching on a translated title.
#
# The last entry is what keeps the page honest about a source: the RPU-backed
# getters pad an absent block out to zeroes rather than leaving it empty (see
# dvinfo._value_or), so on an SDR title every Dolby Vision row would render a
# row of noughts and every HDR10 row a mastering display nothing declared.
# The overlay solves this by not drawing those panels at all; the groups here
# are left out for the same reason.
_GROUPS = (
    ("video",      32054, _VIDEO,       _always),
    ("processing", 32007, _PROCESSING,  _always),
    ("audio",      32056, _AUDIO,       _always),
    ("hdr",        32300, _HDR_STATIC,  _is_hdr),
    ("dv",         32389, _DOLBY_VISION, _is_dv),
    ("system",     32088, _SYSTEM,      _always),
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
)

# The presence flags arrive as ``true`` / ``false`` / '' (unknown); the overlay
# draws them as icons, so the dashboard gets glyphs rather than a word that
# would need translating.
_PRESENCE_GLYPH = {"true": "✔", "false": "✘"}

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


def _metadata_row(kind: str, name: str, value) -> dict:
    """One ``info.dvmetadata`` row as the page consumes it.

    A trim-table row carries its cells as a list rather than as one string
    (the on-screen view draws each in a fixed slot of its own), so the value
    is passed on as a list where it arrives as one and as text otherwise.
    """
    if isinstance(value, (list, tuple)):
        return {"kind": kind, "name": clean_value(name),
                "cells": [clean_value(str(cell)) for cell in value]}
    return {"kind": kind, "name": clean_value(name), "value": clean_value(str(value))}


# --- Snapshot --------------------------------------------------------------

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
        the per-frame blocks (L1, L2, L5, L8, HDR10+) are rebuilt every tick,
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
        """
        groups = []
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
            if rendered:
                groups.append({
                    "id":    group_id,
                    "title": addon.getLocalizedString(title_id),
                    "rows":  rendered,
                })
        return groups

    def build(self, addon=None, allow_filename: bool = True,
              metadata: bool = True) -> dict:
        """One complete snapshot.  Cheap enough for the producer's cadence:
        the whole pass shares a single side-data parse (see ``info.dvinfo``)
        and writes nothing to any window Kodi draws."""
        addon = addon or xbmcaddon.Addon()
        playing = cond("Player.HasVideo")
        self._sequence += 1

        if not playing:
            # Nothing to read; the sink keeps the last title's values, so drop
            # them rather than let the page show a film that has ended.
            self._sink   = PropertySink()
            self._published = {}
            self._static_at = 0.0
            self._meta_static = []
            self._meta_static_at = 0.0
            return {
                "seq":      self._sequence,
                "playing":  False,
                "groups":   [],
                "metrics":  {},
                "metadata": [],
                "vs10":     vs10_state("", playing=False),
            }

        self._refresh()
        values = self._values()
        home   = xbmcgui.Window(_HOME_WINDOW_ID)
        source = home.getProperty(_PROP_HDR_TYPE)
        # Lower-cased once: every branch below asks the same question of it.
        source_key = source.strip().lower()
        is_dv      = _is_dv(source_key)

        return {
            "seq":       self._sequence,
            "playing":   True,
            "paused":    cond("Player.Paused"),
            "title":     values.get("Title", ""),
            # The overlay's own file-name setting governs this too: turning it
            # off must not leave the path leaking over the network instead.
            "filename":  values.get("Filename", "") if allow_filename else "",
            "hdr_type":  source,
            "effective": home.getProperty(PROP_EFFECTIVE_HDR_TYPE),
            "time":      values.get("PlayerTime", ""),
            "duration":  values.get("PlayerDuration", ""),
            "metrics":   self._metrics(values, is_dv),
            "groups":    self._groups(values, addon, source_key),
            "metadata":  self._metadata(is_dv, metadata),
            "vs10":      vs10_state(source_key),
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
    "hlg": (
        ("original_hlg", "HLG (Original)"),
        ("sdr8",         "HLG → SDR"),
        ("dv",           "HLG → Dolby Vision"),
    ),
    "dolby vision": (
        ("original_dv",  "Dolby Vision (Original)"),
        ("sdr8",         "Dolby Vision → SDR"),
    ),
}


def _options_for(source: str, playing: bool = True) -> tuple:
    """The mode buttons that apply to ``source``.

    ``hdr10plus`` contains ``hdr10`` and takes the same three, matching the
    skin's own ``String.Contains`` branches.  An **empty** source is SDR, not
    "unknown": ``publish_hdr_type`` writes a token only for the HDR formats,
    and the dialog's own SDR group is the one behind ``String.IsEmpty`` (see
    script-tinyppi-dialog.xml).  So the buttons only fall away when nothing is
    playing at all and there is no source to convert.
    """
    if not playing:
        return ()
    key = (source or "").strip().lower()
    if "dolby" in key:
        return _VS10_OPTIONS["dolby vision"]
    if "hlg" in key:
        return _VS10_OPTIONS["hlg"]
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
