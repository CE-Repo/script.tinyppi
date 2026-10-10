# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The overlay's readings, one function per row: video, HDR, audio,
subtitles and system.

``info.publish`` writes them into the window properties the skin shows.
"""

import re

from core.helpers import format_fps, normalize_fps
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
    clean,
    cond,
    first_float,
    home_window,
    info,
    is_effective_dv,
    parse_offsets,
    picture_aspect_ratio,
)
from info.dvinfo import (
    get_bit_depth,
    get_hdr_format,
    is_status_label,
    na_label,
)
from info.imax import is_enhanced_title, is_known_imax_title

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


def separated(value: str) -> str:
    """Return *value* with pipes replaced by the display separator."""
    return value.replace("|", _DISPLAY_SEPARATOR)


def with_unit(value: str, unit: str) -> str:
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


def output_hdr_token(eoft_gamut: str) -> str:
    """Map an ``amlogic.eoft_gamut`` reading to an HDR token ('' for SDR).

    Only the mode field (the first token, see ``get_ModeVar``) is read.  The
    tokens are the keys of ``core.maps.HDR_LOGO_MAP``: dolbyvision, hdr10+,
    hlg, hdr10.
    """
    parts = (eoft_gamut or "").split()
    mode = parts[0].upper() if parts else ""
    if "DV" in mode or "DOLBY" in mode:
        return "dolbyvision"
    if "HDR10+" in mode or "HDR10PLUS" in mode or "PLUS" in mode:
        return "hdr10+"
    if "HLG" in mode:
        return "hlg"
    if "HDR" in mode:
        return "hdr10"
    return ""


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


def output_mode_from_videoplayer() -> str:
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
