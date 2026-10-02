# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Compute and publish the overlay's window properties.

Call ``publish_scene_properties`` on every polling tick,
``update_static_properties`` on the slower one, and ``publish_properties``
before a window is shown.
"""

import re

from core import settings
from core.constants import HOME_WINDOW_ID
from core.helpers import format_fps, fps_display_texts, normalize_fps
from core.maps import (
    AUDIO_CODEC_MAP,
    CHANNELS_ICON_HEIGHT_MAP,
    CHANNELS_ICON_MAP,
    CHANNELS_INPUT_MAP,
    CHANNELS_MAP,
    HEIGHT_CHANNEL_CODECS,
    LANGUAGE_MAP,
    LANGUAGE_MAP_SHORT,
    SUBTITLE_CODEC_MAP,
    VIDEO_CODEC_MAP,
)
from core.memo import KeyedMemo
from core.utils import (
    PROP_HDR10PLUS_PRESENT,
    clean,
    cond,
    first_float,
    home_window,
    info,
    is_effective_dv,
    parse_offsets,
    picture_aspect_ratio,
    read_pass,
    set_changed_properties,
)
from info.imax import is_enhanced_title, is_known_imax_title
from info.mediasource import get_MediaSourceVar
from info.dvinfo import (
    get_bit_depth,
    get_cm_version,
    get_dv_bl_present,
    get_dv_el_present,
    get_dv_el_type,
    get_dv_profile,
    get_dv_rpu_present,
    get_dv_version,
    get_hdr10_max_cll_fall,
    get_hdr10_mdl,
    get_hdr10plus_present,
    get_hdr_format,
    get_l1_nits,
    get_l1_pq,
    get_l5_offsets,
    get_l6_rpu_max_cll_fall,
    get_output_mode,
    get_rpu_mdl,
    get_rpu_mdl_from_source,
    get_structure,
    is_status_label,
    na_label,
)

# Channel graphics ship pre-scaled to the skin's boxes, so Kodi never
# resamples them: SDR and HDR10/HDR10+/HLG use 495x298, DV the smaller
# 400x241 panel (see script-tinyppi-main.xml).
_CHANNEL_DIR_DEFAULT = "channels/495x298"
_CHANNEL_DIR_DV      = "channels/400x241"


def _channel_dir() -> str:
    """Return the channel graphics folder for the current output type."""
    return _CHANNEL_DIR_DV if is_effective_dv() else _CHANNEL_DIR_DEFAULT


def _channels_shown() -> bool:
    """Return whether the channel graphics are switched on."""
    return home_window().getProperty("TinyPPI.ShowChannelIcon") == "1"


# --- Video properties ------------------------------------------------------

def get_VideoDecoderVar() -> str:
    """Return 'HW' or 'SW' for the active video decoder."""
    return "HW" if cond("Player.Process(videohwdecoder)") else "SW"


def get_VideoDecoderLongVar() -> str:
    """Return 'Hardware' or 'Software' for the Decode mode row."""
    return "Hardware" if cond("Player.Process(videohwdecoder)") else "Software"


def get_VideoPixelFormatVar() -> str:
    """Format ``amlogic.pixformat``, e.g. ``10-bit (YUV 4:2:0)`` or ``8-bit, RGB``."""
    val = info("Player.Process(amlogic.pixformat)").strip()
    if not val:
        return ""

    match = re.search(
        r"(\d+)-bit\s*,\s*(RGB|YUV420|YUV422|YUV444)",
        val,
        re.IGNORECASE,
    )
    if not match:
        return val

    bits, fmt = match.groups()
    fmt = fmt.upper()

    if fmt == "RGB":
        return f"{bits}-bit, RGB"

    yuv_map = {
        "YUV420": "YUV 4:2:0",
        "YUV422": "YUV 4:2:2",
        "YUV444": "YUV 4:4:4",
    }
    return f"{bits}-bit ({yuv_map.get(fmt, fmt)})"


def get_DisplayModeVar() -> str:
    """Format ``amlogic.displaymode`` compactly, e.g. ``1080p 23.976Hz``."""
    val = info("Player.Process(amlogic.displaymode)").strip()
    if not val:
        return ""

    compact = re.sub(r"\s+", "", val)
    match = re.match(
        r"(\d+(?:x\d+)?)(p|i)(\d+(?:\.\d+)?)[Hh][Zz]",
        compact,
        re.IGNORECASE,
    )
    if not match:
        return val

    res, scan, raw_fps = match.groups()
    return f"{res}{scan} {normalize_fps(raw_fps)}Hz"


def get_VideoResolutionVar() -> str:
    """Return a string like ``1920x1080p 23.976FPS``."""
    width  = clean(info("Player.Process(videowidth)"))
    height = clean(info("Player.Process(videoheight)"))
    scan   = clean(info("Player.Process(videoscantype)"))
    fps    = clean(info("Player.Process(videofps)"))

    if not width or not height:
        return ""

    return f"{width}x{height}{scan} {format_fps(fps)}FPS"


# Standard aspect ratios a computed ratio snaps to.  Pixel-exact RPU offsets
# still land slightly off (a 2.39 film would read 2.40); ratios beyond the
# tolerance are shown as computed.
_STANDARD_ARS = (
    1.33, 1.37, 1.43, 1.66, 1.78, 1.85, 1.90, 2.00, 2.20, 2.35, 2.39, 2.55, 2.76,
)
_AR_SNAP_TOLERANCE = 0.02           # relative to the standard ratio


def _snapped_ar(ratio: float) -> str:
    """Format an aspect ratio to two decimals, snapping to a standard one."""
    closest = min(_STANDARD_ARS, key=lambda standard: abs(standard - ratio))
    if abs(closest - ratio) <= closest * _AR_SNAP_TOLERANCE:
        ratio = closest
    return f"{ratio:.2f}"


def get_AspectRatioVar(l5_offsets: str, is_dv: bool | None = None) -> str:
    """Return the display aspect ratio of the picture inside the black bars.

    Kodi's ``videodar`` describes the coded frame, so a letterboxed 2.39 film
    reads 1.78; scaling by the RPU's active-area offsets gives the visible
    ratio.  Falls back to Kodi's value when the bars are unknown, or when
    they are all zero outside Dolby Vision (there they are only dvinfo's
    placeholder).  In Dolby Vision all-zero is a real "no crop".  *is_dv* may
    pass in an already-read state.
    """
    raw = clean(info("Player.Process(videodar)"))

    bars = parse_offsets(l5_offsets)
    if bars is None:
        return raw

    if not any(bars):
        if is_dv is None:
            is_dv = is_effective_dv()
        if not is_dv:
            return raw

    ratio = picture_aspect_ratio(l5_offsets)
    return _snapped_ar(ratio) if ratio is not None else raw


def get_ImaxVar() -> str:
    """Return ``IMAX Enhanced``, ``IMAX`` or '' for the playing film.

    Recognised by release name or title list (see ``info.imax``) and shown
    for the whole runtime: the badge describes the film, not the current
    framing.
    """
    if not is_known_imax_title():
        return ""
    return "IMAX Enhanced" if is_enhanced_title() else "IMAX"


def get_VideoBitrateMBVar() -> str:
    """Return the video bitrate in Mb/s for display."""
    bitrate = clean(info("VideoPlayer.VideoBitrate"))
    try:
        mbit = float(bitrate) / 1000.0
    except (TypeError, ValueError):
        return ""

    value = f"{mbit:.1f}".rstrip("0").rstrip(".")
    return f"{value} Mb/s"


def get_VideoLiveBitrateVar() -> str:
    """Return the live video bitrate with a decimal point."""
    bitrate = info("Player.Process(videolivebitrate)")
    if not bitrate:
        return ""

    return str(bitrate).replace(",", ".")


def get_VideoCodecVar() -> str:
    """Return the mapped display name for the current video codec."""
    codec = info("VideoPlayer.VideoCodec").lower().strip()
    if not codec:
        return ""
    return VIDEO_CODEC_MAP.get(codec, codec.upper())


def get_VideoDecoderNameVar() -> str:
    """Return the decoder vendor prefix (``AML-`` / ``FF-``).

    ``Player.Process(videodecoder)`` reports e.g. ``am-h264``; the skin joins
    the prefix with ``VideoCodecVar`` (``AML-H.265``).  Unknown values are
    returned upper-cased.
    """
    raw = info("Player.Process(videodecoder)").strip()
    if not raw:
        return ""

    low = raw.lower()
    if low.startswith("am-"):
        return "AML-"
    if low.startswith("ff-"):
        return "FF-"
    return raw.upper()


def get_VideoBitDepthVar() -> str:
    """Return the source bit depth for display, e.g. ``12-bit``.

    Only a full enhancement layer gives 12-bit (reported by dvinfo); every
    other HDR format is 10-bit, SDR is 8-bit.
    """
    value = get_bit_depth()
    if not value or is_status_label(value):
        return "10-bit" if get_hdr_format() else "8-bit"
    return f"{value}-bit"


# --- HDR / Dolby Vision properties -----------------------------------------

# get_DoviTunnelVar's result by pixel format.  The sysfs DV mode only
# changes with a VS10 switch, which also changes the pixel format.
_dovi_tunnel = KeyedMemo()


def get_DoviTunnelVar() -> str:
    """Return ``"DV Tunnel"`` for sysfs DV mode 1 with 8-bit output, else ''.

    Cached per Amlogic pixel format.
    """
    pixformat = info("Player.Process(amlogic.pixformat)").strip()
    held = _dovi_tunnel.get(pixformat)
    if held is not None:
        return held

    result = ""
    bits = re.search(r"(\d+)-bit", pixformat, re.IGNORECASE)
    if bits and bits.group(1) == "8":
        try:
            with open(
                "/sys/module/aml_media/parameters/dolby_vision_mode",
                encoding="utf-8",
                errors="ignore",
            ) as f:
                if f.read().strip() == "1":
                    result = "DV Tunnel"
        except OSError:
            # Not cached: retry next cycle.
            return ""

    _dovi_tunnel.put(pixformat, result)
    return result


# Gap between a value and its unit (``1000 l 400 cd/m²``).
_UNIT_GAP = " "


# On-screen separator for multi-part metadata values: a lowercase L reads
# better than a pipe in font23_narrow.  Swapped only when publishing, so the
# values stay pipe-joined for parse_offsets().
_DISPLAY_SEPARATOR = "l"


def _separated(value: str) -> str:
    """Return *value* with pipes replaced by the display separator."""
    return value.replace("|", _DISPLAY_SEPARATOR)


def _with_unit(value: str, unit: str) -> str:
    """Append *unit* to a metadata value, but not to status labels.

    The ``0 | 0`` placeholder still gets the unit; ``N/A`` does not.
    """
    if not value or is_status_label(value):
        return value
    if not unit:
        return value
    return f"{value}{_UNIT_GAP}{unit}"


# --- Amlogic EOFT / gamut --------------------------------------------------

def get_ModeVar() -> str:
    """Return the first token of ``amlogic.eoft_gamut`` (the mode field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[0] if parts else ""


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


def _output_mode_from_videoplayer() -> str:
    """Map ``VideoPlayer.HDRType`` to an output-mode label.

    Uses Kodi's own HDR detection, so streams without side data still name
    their format.  Empty means SDR.
    """
    hdr = info("VideoPlayer.HDRType").lower()
    if not hdr:
        return "SDR"
    if "dolby" in hdr or "dovi" in hdr:
        return "Dolby Vision"
    if "hdr10+" in hdr or "hdr10plus" in hdr:
        return "HDR10+"
    if "hlg" in hdr:
        return "HLG"
    if "hdr10" in hdr or "hdr" in hdr or "pq" in hdr:
        return "HDR10"
    return "SDR"


# --- Audio properties ------------------------------------------------------

def _has_audio() -> bool:
    """Return whether Kodi names a codec for the current audio track.

    Without one Kodi may still report channels, a bitrate and a format;
    those rows read N/A like the codec instead.
    """
    return bool(info("VideoPlayer.AudioCodec").strip())


def get_AudioBitrateKBVar() -> str:
    """Return the audio bitrate in Kb/s for display."""
    if not _has_audio():
        return ""
    bitrate = clean(info("VideoPlayer.AudioBitrate"))
    try:
        kbps = int(float(bitrate))
    except (TypeError, ValueError):
        return ""
    return f"{kbps:,} Kb/s".replace(",", ".")


def get_AudioLiveBitrateVar() -> str:
    """Return the live audio bitrate with a decimal point."""
    if not _has_audio():
        return ""
    bitrate = info("Player.Process(audiolivebitrate)")
    if not bitrate:
        return ""

    return str(bitrate).replace(",", ".")


def get_AudioCodecVar() -> str:
    """Return the mapped display name for the current audio codec."""
    codec = info("VideoPlayer.AudioCodec")
    if not codec:
        return na_label()
    return AUDIO_CODEC_MAP.get(codec, codec)


def get_AudioCodecSpatialVar() -> str:
    """Return ``(Atmos)``, ``(IMAX Enhanced)`` or '' for the audio codec."""
    codec = info("VideoPlayer.AudioCodec")
    if codec == "dtshd_ma_x_imax":
        return "(IMAX Enhanced)"
    if codec in ("eac3_ddp_atmos", "truehd_atmos"):
        return "(Atmos)"
    return ""


def get_AudioChannelsVar() -> str:
    """Return the surround layout for the channel count, e.g. ``7.1``."""
    if not _has_audio():
        return ""
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
        return CHANNELS_MAP.get(ch, "")
    except (ValueError, TypeError):
        return ""


def get_AudioChannelsInputVar() -> str:
    """Return the speaker labels for the channel count."""
    if not _has_audio():
        return na_label()
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
        return CHANNELS_INPUT_MAP.get(ch, na_label())
    except (ValueError, TypeError):
        return na_label()


def _channel_layout() -> str:
    """Return the speaker layout of the track, e.g. ``5.1.2``, or ''.

    Atmos and DTS:X tracks with 6 or 8 channels use the height variant
    (5.1.2 / 7.1.2), since Kodi reports no height count.
    """
    if not _has_audio():
        return ""
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
    except (ValueError, TypeError):
        return ""

    layout = ""
    if info("VideoPlayer.AudioCodec") in HEIGHT_CHANNEL_CODECS:
        layout = CHANNELS_ICON_HEIGHT_MAP.get(ch, "")
    return layout or CHANNELS_ICON_MAP.get(ch, "")


def get_ChannelLayerVar() -> str:
    """Return the speaker-layout backdrop for the current panel size."""
    return f"{_channel_dir()}/layer.png" if _channels_shown() else ""


def get_ChannelIconVar() -> str:
    """Return the speaker-layout graphic for the channel count, or ''.

    Empty also hides the control in the skin.
    """
    if not _channels_shown():
        return ""

    layout = _channel_layout()
    return f"{_channel_dir()}/{layout}.png" if layout else ""


def get_AudioBitDepthVar() -> str:
    """Return the audio bit depth for display, e.g. ``24-bit``.

    Kodi reports 0 for streams without a PCM depth (lossy codecs,
    passthrough); that is shown as ''.
    """
    if not _has_audio():
        return ""
    bits = clean(info("Player.Process(AudioBitsPerSample)")).strip()
    try:
        depth = int(float(bits))
    except (TypeError, ValueError):
        return ""
    return f"{depth}-bit" if depth > 0 else ""


def get_AudioSampleRateVar() -> str:
    """Return the audio sample rate in kHz, e.g. ``96 kHz`` or ``44.1 kHz``."""
    if not _has_audio():
        return ""
    samplerate = clean(info("Player.Process(AudioSamplerate)"))
    try:
        hz = float(samplerate)
    except (TypeError, ValueError):
        return ""
    if hz <= 0:
        return ""
    khz = hz / 1000.0
    return f"{int(khz)} kHz" if khz.is_integer() else f"{khz:.1f} kHz"


def get_AudioNameVar() -> str:
    """Return the native name of the audio language."""
    if not _has_audio():
        return ""
    code = info("VideoPlayer.AudioLanguage").lower().strip()
    return LANGUAGE_MAP.get(code, "") if code else ""


def _language_short(label: str) -> str:
    """Return the short code of the language in InfoLabel *label*.

    Codes missing from the map are shown as Kodi reports them, uppercased;
    untagged tracks (common on Blu-ray .m2ts) read ``UNK``.
    """
    code = info(label).lower().strip()
    return LANGUAGE_MAP_SHORT.get(code, code.upper()) if code else "UNK"


def get_AudioNameShortVar() -> str:
    """Return the short code of the audio language, ``UNK`` if untagged.

    Empty without an audio track, so the row reads N/A.
    """
    if not _has_audio():
        return ""
    return _language_short("VideoPlayer.AudioLanguage")


# --- Subtitle properties ---------------------------------------------------

def get_SubtitleNameVar() -> str:
    """Return the native name of the subtitle language."""
    code = info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return LANGUAGE_MAP.get(code, "") if code else ""


def get_SubtitleNameShortVar() -> str:
    """Return the short code of the subtitle language, ``UNK`` if untagged.

    Without it an untagged track would read just its codec, e.g. ``(PGS)``.
    """
    return _language_short("VideoPlayer.SubtitlesLanguage")


def get_SubtitleCodecVar() -> str:
    """Return the display name of the subtitle codec."""
    codec = info("VideoPlayer.SubtitleCodec").lower().strip()
    return SUBTITLE_CODEC_MAP.get(codec, codec.upper()) if codec else ""


# --- System properties -----------------------------------------------------

_CPU_CORE_RE = re.compile(r"#\d+:\s*([\d.]+)%")


def _cpu_core_loads(raw: str) -> list[float]:
    """Return the per-core percentages from ``System.CpuUsage``."""
    loads = []
    for val in _CPU_CORE_RE.findall(raw):
        try:
            loads.append(float(val))
        except ValueError:
            continue
    return loads


def get_CpuUsageVar() -> str:
    """Return the per-core CPU load, e.g. ``12 | 08 | 15 | 10``."""
    raw = info("System.CpuUsage")
    if not raw:
        return ""

    loads = _cpu_core_loads(raw)
    if not loads:
        return raw

    return " | ".join(f"{int(v):02d}" for v in loads)


def get_CpuTopUsageVar() -> str:
    """Return the average CPU load over all cores, e.g. ``34%``, or ''."""
    loads = _cpu_core_loads(info("System.CpuUsage"))
    if not loads:
        return ""

    return f"{sum(loads) / len(loads):.0f}%"


def get_CpuTemperatureProgressVar() -> float:
    """Map ``System.CPUTemperature`` to 0-100 (0-110 °C or 32-230 °F)."""
    raw = info("System.CPUTemperature").strip()
    if not raw:
        return 0.0

    temperature = first_float(raw)
    if temperature is None:
        return 0.0

    if re.search(r"(?:°\s*)?F\b", raw, re.IGNORECASE):
        minimum = 32.0
        maximum = 230.0
    else:
        minimum = 0.0
        maximum = 110.0

    temperature = max(minimum, min(temperature, maximum))

    return (
        (temperature - minimum)
        / (maximum - minimum)
        * 100.0
    )


# The PQ row shows raw 12-bit code words (0-4095), not a brightness, so its
# unit is fixed.
_PQ_UNIT = "12-bit"


def _metadata_units() -> tuple[str, str]:
    """Return the (brightness, PQ) units with Kodi color markup.

    Hiding the unit (``unit_type``) hides both, so either all metadata rows
    show a unit or none do.
    """
    unit_color = info(f"Window({HOME_WINDOW_ID}).Property(TinyPPI.UnitColor)")
    unit_label = info(f"Window({HOME_WINDOW_ID}).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return "", ""
    if unit_color:
        return (
            f"[COLOR={unit_color}]{unit_label}[/COLOR]",
            f"[COLOR={unit_color}]{_PQ_UNIT}[/COLOR]",
        )
    return unit_label, _PQ_UNIT


def _channel_setting_for(hdr_type: str) -> str:
    """Return the channel setting for an ``EffectiveHdrType`` value.

    Mirrors the skin: DV has its own panel, HDR formats share one, empty is
    SDR.
    """
    low = hdr_type.lower()
    if "dolby" in low:
        return "channels_dv"
    if not low:
        return "channels_sdr"
    return "channels_hdr"


def publish_channel_visibility(home=None, published=None) -> None:
    """Publish ``TinyPPI.ShowChannelIcon`` for the current output type.

    Re-read on every poll: the HDR type is detected asynchronously, and a
    settings change should apply without reopening.

    *published* is the polling loop's record; without it every call writes.
    """
    home = home or home_window()
    setting = _channel_setting_for(home.getProperty("TinyPPI.EffectiveHdrType"))
    enabled = settings.addon().getSetting(setting) == "true"
    if published is None:
        published = {}
    set_changed_properties(
        home,
        published,
        (
            ("TinyPPI.ShowChannelIcon", "1" if enabled else "0"),
        ),
    )


def _effective_hdr_type(hdr_type: str) -> str:
    """Return the HDR type the overlay layout follows for source *hdr_type*.

    Normally the source type.  Two VS10 conversions can follow the output
    instead:

    * to SDR (``keep_area_on_sdr`` off): the SDR box is used;
    * DV to HDR10 (``keep_dv_area_on_hdr10`` off): the HDR static-metadata
      panel replaces the Dolby Vision one.

    Both settings keep the source layout by default.  The output comes from
    the mode field of ``amlogic.eoft_gamut``, like the skin's conversion
    rows; anything else (passthrough, unreadable field) keeps the source
    type.
    """
    mode = get_ModeVar().upper()
    addon = settings.addon()
    if mode.startswith("SDR"):
        return hdr_type if addon.getSetting("keep_area_on_sdr") == "true" else ""
    if mode.startswith("HDR") and "dolby" in hdr_type.lower():
        if addon.getSetting("keep_dv_area_on_hdr10") != "true":
            return "hdr10"
    return hdr_type


def _hdr10_panel_stands_in_for_dv() -> bool:
    """Return whether the HDR static-metadata panel is shown for a DV source.

    Only for DV -> HDR10 with ``keep_dv_area_on_hdr10`` off; a profile 5
    stream has no static SEI for those rows.  Reads the properties
    ``publish_hdr_type`` last wrote.
    """
    home = home_window()
    return (
        "dolby" in home.getProperty("TinyPPI.HdrType").lower()
        and home.getProperty("TinyPPI.EffectiveHdrType") == "hdr10"
    )


def publish_hdr_type(home=None, published=None) -> None:
    """Publish the source HDR type and the type the layout follows.

    ``TinyPPI.HdrType`` is the source, ``TinyPPI.EffectiveHdrType`` the
    layout type (they differ during VS10 conversion, see
    ``_effective_hdr_type``).  HDR10+ is published as ``hdr10plus`` because
    Kodi's condition parser reads ``+`` as AND; it still contains ``hdr10``
    for ``String.Contains``.

    ``TinyPPI.Hdr10PlusPresent`` marks a Dolby Vision source with an
    ST 2094-40 payload next to its RPU: a hybrid grade VS10 cannot convert,
    so the dialog and dashboard offer no modes for it.

    *published* is the polling loop's record; without it every call writes.
    """
    hdr_type = get_hdr_format()
    if hdr_type == "hdr10+":
        hdr_type = "hdr10plus"
    home = home or home_window()
    if published is None:
        published = {}
    set_changed_properties(
        home,
        published,
        (
            ("TinyPPI.HdrType", hdr_type),
            ("TinyPPI.EffectiveHdrType", _effective_hdr_type(hdr_type)),
            (PROP_HDR10PLUS_PRESENT, get_hdr10plus_present()),
        ),
    )


def _set_progress(window, published: dict, values: tuple[tuple[int, float], ...]) -> None:
    """Set progress controls, skipping values *published* already holds."""
    for control_id, value in values:
        key = f"__progress_{control_id}"
        if published.get(key) != value:
            window.getControl(control_id).setPercent(value)
            published[key] = value


def update_static_properties(window, published=None) -> None:
    """Publish the per-title properties and the CPU temperature bar.

    For the polling loop's slow cadence.  The progress control is addressed
    by id, which needs the loaded window; before that use
    ``publish_properties``.

    *published* is the polling loop's record, so an idle tick writes
    nothing; without it every call writes.
    """
    if published is None:
        published = {}
    with read_pass():
        publish_static_properties(window, published)
        _set_progress(
            window,
            published,
            (
                (9100, get_CpuTemperatureProgressVar()),
            ),
        )


def publish_scene_properties(window, published=None) -> None:
    """Publish the Dolby Vision / HDR10 readings that change per scene.

    Active-area offsets and L1 luminance come from the current frame, so the
    aspect ratio and brightness rows can change during playback.  The DV
    version and profile are included because overlay.py highlights them too.

    *published* is the polling loop's record; without it every call writes.
    """
    if published is None:
        published = {}
    with read_pass():
        _publish_scene_properties(window, published)


def _publish_scene_properties(window, published: dict) -> None:
    """Run the scene pass inside the caller's ``read_pass``."""
    unit, pq_unit = _metadata_units()

    # Active-area offsets of the current frame, the row's icon, and the
    # aspect ratio inside the bars.
    l5_offsets          = get_l5_offsets()
    l5_icon_visible     = (
        "true" if l5_offsets and not is_status_label(l5_offsets) else "false"
    )
    # L1 frame luminance in nits and as PQ code words.
    l1_fll              = _with_unit(_separated(get_l1_nits()), unit)
    l1_pq               = _with_unit(_separated(get_l1_pq()), pq_unit)
    # The RPU mastering display (source range if present, else L6); the flag
    # lets the panel label the rows after the block that was read.
    rpu_mdl             = _with_unit(_separated(get_rpu_mdl()), unit)
    rpu_mdl_from_source = get_rpu_mdl_from_source()
    l6_rpu_max_cll_fall = _with_unit(_separated(get_l6_rpu_max_cll_fall()), unit)
    # The static rows borrow L6 only while the HDR panel replaces the DV one.
    # The properties read may be one slow tick old; the type settles once
    # per title, so that is harmless.
    l6_fallback         = _hdr10_panel_stands_in_for_dv()
    hdr10_mdl           = _with_unit(_separated(get_hdr10_mdl(l6_fallback)), unit)
    hdr10_max_cll_fall  = _with_unit(
        _separated(get_hdr10_max_cll_fall(l6_fallback)), unit
    )

    set_changed_properties(
        window,
        published,
        (
            ("AspectRatioVar", get_AspectRatioVar(l5_offsets)),
            ("DoviLevel5OffsetsVar", _separated(l5_offsets)),
            ("DoviLevel5OffsetsIconVisible", l5_icon_visible),
            ("DoviCmVersionVar", get_cm_version()),
            ("DoviStructureVar", get_structure()),
            ("DoviLevel1FllVar", l1_fll),
            ("DoviLevel1PqVar", l1_pq),
            ("DoviRpuMdlVar", rpu_mdl),
            ("DoviRpuMdlFromSourceVar", rpu_mdl_from_source),
            ("DoviLevel6RpuMaxCllFallVar", l6_rpu_max_cll_fall),
            ("Hdr10MdlVar", hdr10_mdl),
            ("Hdr10MaxCllFallVar", hdr10_max_cll_fall),
            # Per-title facts, but overlay.py highlights them, and on the
            # slow cadence a change would be lit up to a second late.
            ("DoviVersionVar", get_dv_version()),
            ("DoviProfileNumberVar", get_dv_profile()),
        ),
    )


def publish_static_properties(window, published=None) -> None:
    """Publish the properties that change at most once per title.

    Video and audio format facts, DV / HDR10 presence flags and CPU load.
    Only sets properties, so it is safe before ``doModal()``: the values are
    then in place on the first frame instead of arriving with ``onInit()``,
    while the window is already fading in.

    *published* is the polling loop's record; without it every call writes,
    which is what the pre-``doModal()`` call needs.
    """
    if published is None:
        published = {}
    with read_pass():
        _publish_static_properties(window, published)


def _publish_static_properties(window, published: dict) -> None:
    """Run the static pass inside the caller's ``read_pass``."""
    publish_hdr_type(published=published)
    # Uses the type just published; gates the channel graphics below.
    publish_channel_visibility(published=published)

    fps_info_text, fps_out_text = fps_display_texts(
        clean(info("Player.Process(videofps)"))
    )

    # Output mode from side data, else from ``VideoPlayer.HDRType``.
    output_mode = get_output_mode()
    if is_status_label(output_mode):
        output_mode = _output_mode_from_videoplayer() or output_mode

    set_changed_properties(
        window,
        published,
        (
            ("VideoDecoderVar", get_VideoDecoderVar()),
            ("VideoDecoderLongVar", get_VideoDecoderLongVar()),
            ("VideoPixelFormatVar", get_VideoPixelFormatVar()),
            ("DisplayModeVar", get_DisplayModeVar()),
            ("VideoResolutionVar", get_VideoResolutionVar()),
            ("ImaxVar", get_ImaxVar()),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoLiveBitrateVar", get_VideoLiveBitrateVar()),
            ("VideoCodecVar", get_VideoCodecVar()),
            ("VideoDecoderNameVar", get_VideoDecoderNameVar()),
            ("VideoBitDepthVar", get_VideoBitDepthVar()),
            ("DoviProfileVar", output_mode),
            ("MediaSourceVar", get_MediaSourceVar()),
            ("DoviTunnelVar", get_DoviTunnelVar()),
            ("DoviRpuPresentVar", get_dv_rpu_present()),
            ("DoviBlPresentVar", get_dv_bl_present()),
            ("DoviElPresentVar", get_dv_el_present()),
            ("DoviElTypeVar", get_dv_el_type()),
            ("ModeVar", get_ModeVar()),
            ("GamutVar", get_GamutVar()),
            ("FpsInfoVar", fps_info_text),
            ("FpsDropVar", fps_out_text),
            ("AudioBitrateKBVar", get_AudioBitrateKBVar()),
            ("AudioLiveBitrateVar", get_AudioLiveBitrateVar()),
            ("AudioCodecVar", get_AudioCodecVar()),
            ("AudioCodecSpatialVar", get_AudioCodecSpatialVar()),
            ("AudioChannelsVar", get_AudioChannelsVar()),
            ("AudioChannelsInputVar", get_AudioChannelsInputVar()),
            ("ChannelIconVar", get_ChannelIconVar()),
            ("ChannelLayerVar", get_ChannelLayerVar()),
            ("AudioBitDepthVar", get_AudioBitDepthVar()),
            ("AudioSampleRateVar", get_AudioSampleRateVar()),
            ("AudioNameVar", get_AudioNameVar()),
            ("AudioNameShortVar", get_AudioNameShortVar()),
            ("SubtitleCodecVar", get_SubtitleCodecVar()),
            ("SubtitleNameVar", get_SubtitleNameVar()),
            ("SubtitleNameShortVar", get_SubtitleNameShortVar()),
            ("CpuUsageVar", get_CpuUsageVar()),
            ("CpuTopUsageVar", get_CpuTopUsageVar()),
        ),
    )


def publish_properties(window, published=None) -> None:
    """Publish all player properties to *window* in one pass.

    Called once before ``doModal()`` so the first frame is complete; the
    polling loop then calls the scene and static halves at their own
    cadence.  *published* works as in those two.
    """
    if published is None:
        published = {}
    # One read pass for both halves, so nothing is read twice.
    with read_pass():
        _publish_scene_properties(window, published)
        _publish_static_properties(window, published)
