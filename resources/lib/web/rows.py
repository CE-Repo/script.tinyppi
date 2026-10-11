# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's cards and rows, as the overlay shows them.

``GROUPS`` lists the cards and their rows, each row built from value
segments like the skin's ``$INFO`` (``render``).  ``overlay_rows`` mirrors
the skin's conditional labels; ``web.snapshot`` fills the values.
"""

from collections.abc import Iterable

from core.utils import cond, info, localized
from info.mediasource import is_live, is_pvr
from web.player import is_live_tv
from web.values import clean_value, numbers


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


def is_dv_source(source: str) -> bool:
    """Return whether *source* is Dolby Vision (the only one with an RPU)."""
    return "dolby" in source


def _is_hdr(source: str) -> bool:
    """Return whether *source* is HDR (empty means SDR, as in the skin)."""
    return bool(source)


def _is_plain_hdr(source: str) -> bool:
    """Return whether *source* is non-DV HDR.

    Then the static metadata gets its own card; for Dolby Vision it opens
    the Metadata card instead (see ``GROUPS``).
    """
    return _is_hdr(source) and not is_dv_source(source)


# Cards: (group id, title string id, rows, applies-to), in page order.  The
# id lets the page style a card without matching translated titles.
# applies-to hides HDR / DV cards for other sources, since their getters pad
# missing blocks with zeros (see dvinfo._value_or), like the overlay does.
GROUPS = (
    ("video",      32218, _VIDEO,       _always),
    ("processing", 32226, _PROCESSING,  _always),
    ("audio",      32237, _AUDIO,       _always),
    ("system",     32247, _SYSTEM,      _always),
    ("hdr",        32255, _HDR_STATIC,  _is_plain_hdr),
    ("dv",         32365, _DOLBY_VISION, is_dv_source),
    # Two entries with the same id form one card (see _groups).
    ("metadata",   32264, _HDR_STATIC,   is_dv_source),
    ("metadata",   32264, _DV_METADATA,  is_dv_source),
)


def render(segments: Iterable[tuple[str, str, str]], values: dict[str, str]) -> str:
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


def _label(string_id: int) -> str:
    return localized(string_id)


def _bitrate_row(live: str, average: str) -> tuple[str, str]:
    """Return a bitrate row as the overlay shows it: ``live -`` ``(Ø avg)``."""
    if live and average:
        return f"{live} -", f"(Ø {average})"
    return live or average, ""


def overlay_rows(values: dict[str, str]) -> dict[str, str]:
    """Return the rows the skin chooses between labels for.

    Mirrors the skin's conditional labels (Passthrough, Disabled, Live TV,
    ...), so the page shows what the TV shows.
    """
    rows: dict[str, str] = {"AudioOutputRow": _audio_output_row(values)}
    rows["VideoBitrateRow"], rows["VideoBitrateDetail"] = _bitrate_row(
        values.get("VideoLiveBitrateVar", ""), values.get("VideoBitrateMBVar", ""))
    rows["AudioBitrateRow"], rows["AudioBitrateDetail"] = _bitrate_row(
        values.get("AudioLiveBitrateVar", ""), values.get("AudioBitrateKBVar", ""))
    rows.update(_subtitle_rows(values))
    rows.update(_playback_rows(values))
    return rows


def _audio_output_row(values: dict[str, str]) -> str:
    """Return the audio output: Passthrough, the sink's channels or Decoding.

    N/A (empty) without an audio codec, like the other audio rows.
    """
    if not info("VideoPlayer.AudioCodec").strip():
        return ""
    if cond("Player.Passthrough"):
        return _label(32242)
    return values.get("AudioChannelsSink", "") or _label(32243)


def _subtitle_rows(values: dict[str, str]) -> dict[str, str]:
    """Return the subtitle rows: the track when on, Disabled when off, N/A
    without any."""
    if not cond("VideoPlayer.HasSubtitles"):
        return {}
    if not cond("VideoPlayer.SubtitlesEnabled"):
        return {"SubtitleStateRow": _label(32246)}
    return {
        "SubtitleShortRow": values.get("SubtitleNameShortVar", ""),
        "SubtitleNameRow":  values.get("SubtitleNameVar", ""),
        "SubtitleCodecRow": values.get("SubtitleCodecVar", ""),
    }


def _playback_rows(values: dict[str, str]) -> dict[str, str]:
    """Return the playback times, or the label that replaces them.

    Live TV without EPG and streams without a length get a label instead
    of meaningless times.
    """
    if is_live_tv() and not values.get("BroadcastTimes"):
        return {"PlaybackStateRow": _label(32235)}
    if values.get("PlayerDuration"):
        return {
            "PlaybackTimeRow":     values.get("PlayerTime", ""),
            "PlaybackDurationRow": values.get("PlayerDuration", ""),
            "PlaybackProgressRow": values.get("PlayerProgress", ""),
        }
    if cond("Player.IsInternetStream") and not is_live_tv():
        return {"PlaybackStateRow": _label(32236)}
    return {}


def finish_time(values: dict[str, str]) -> str:
    """Return the end time by the clock, or ''.

    Live TV: the broadcast's end from the EPG.  Streams without a length,
    other live items and recordings: ''.  Also '' while the duration is
    still 00:00, which would just show the current time.
    """
    if is_live_tv():
        if not values.get("BroadcastTimes"):
            return ""
        return values.get("PlayerFinishTime", "")
    if is_live() or is_pvr():
        return ""
    # Covers both an all-zero and an empty duration.
    if not any(numbers(values.get("PlayerDuration", ""))):
        return ""
    return values.get("PlayerFinishTime", "")
