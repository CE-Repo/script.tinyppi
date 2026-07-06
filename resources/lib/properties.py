"""
properties.py – Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval from your
``WindowXMLDialog`` subclass.
"""

import re

import xbmc
import xbmcgui

from maps import (
    AUDIO_CODEC_MAP,
    CHANNELS_INPUT_MAP,
    CHANNELS_MAP,
    LANGUAGE_MAP,
    LANGUAGE_MAP_SHORT,
    SUBTITLE_CODEC_MAP,
    VIDEO_CODEC_MAP,
)
from utils import clean, cond, info, set_window_properties
from helpers import format_fps, fps_display_texts, normalize_fps
from dvinfo import (
    get_bit_depth,
    get_cm_version,
    get_hdr_format,
    get_output_mode,
    get_structure,
    get_l5_offsets,
    get_l6_rpu_mdl,
    get_l6_rpu_max_cll_fall,
    is_status_label,
)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_BITRATE_DECIMAL_RE = re.compile(r"-?(?:\d+(?:[.,]\d+)?|[.,]\d+)")


def _first_float(raw: str, pattern: re.Pattern = _DECIMAL_RE) -> float | None:
    """Return the first decimal number found in *raw*, or None."""
    match = pattern.search(raw)
    if not match:
        return None

    try:
        return float(match.group(0).replace(",", "."))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Video properties
# ---------------------------------------------------------------------------

def get_VideoDecoderVar() -> str:
    """Return 'HW' or 'SW' based on the active video decoder type."""
    return "HW" if cond("Player.Process(videohwdecoder)") else "SW"


def get_VideoPixelFormatVar() -> str:
    """
    Parse ``amlogic.pixformat`` and return a human-readable string such as
    ``10-bit (YUV 4:2:0)`` or ``8-bit, RGB``.
    """
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
    """
    Parse ``amlogic.displaymode`` and return a compact string like
    ``1080p 23.976Hz``.
    """
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


def get_VideoBitrateMBVar() -> str:
    """Convert the video bitrate from kb/s to Mb/s and return a display string."""
    bitrate = clean(info("VideoPlayer.VideoBitrate"))
    try:
        mbit = float(bitrate) / 1000.0
    except (TypeError, ValueError):
        return ""

    value = f"{mbit:.2f}".rstrip("0").rstrip(".")
    return f"{value} Mb/s"


def get_VideoLiveBitrateVar() -> str:
    """
    Format the live video bitrate (``Player.Process(videolivebitrate)``)
    as e.g. ``23.45 Mb/s`` or ``850 Kb/s``, without failing on malformed
    Kodi values.  Returns ``''`` when no live bitrate is reported.
    """
    bitrate = info("Player.Process(videolivebitrate)").strip()

    if not bitrate:
        return ""

    value = _first_float(bitrate, _BITRATE_DECIMAL_RE)
    if value is None:
        return ""

    if value < 0:
        return ""

    if value < 1.0:
        return f"{int(round(value * 1000))} Kb/s"

    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{formatted} Mb/s"


def get_VideoCodecVar() -> str:
    """Return the mapped display name for the current video codec."""
    codec = info("VideoPlayer.VideoCodec").lower().strip()
    if not codec:
        return ""
    return VIDEO_CODEC_MAP.get(codec, codec.upper())


def get_VideoDecoderNameVar() -> str:
    """
    Return the display prefix for the active video decoder.

    ``Player.Process(videodecoder)`` reports values such as ``am-h264`` or
    ``ff-hevc``.  Only the vendor prefix is returned (``AML-`` / ``FF-``);
    the skin concatenates it directly with ``VideoCodecVar`` to form e.g.
    ``AML-H.265``.  Unknown decoder strings are passed through upper-cased,
    matching the previous ``[UPPERCASE]`` skin styling.
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
    """
    Return the source video bit depth for display, e.g. ``12-bit``.

    FEL Dolby Vision streams reconstruct a higher-bit-depth signal from a 10-bit
    base layer, so hdrprobe's reconstructed_bit_depth is reported for them
    (falling back to 12-bit when absent); every other format uses hdrprobe's
    container bit depth.  Detection runs in a background thread (see dvinfo.py),
    so this call never blocks the polling loop; the localized status label is
    passed through unchanged while detection is running or after it fails.
    """
    value = get_bit_depth()
    if not value or is_status_label(value):
        return value
    return f"{value}-bit"


# ---------------------------------------------------------------------------
# HDR / Dolby Vision properties
# ---------------------------------------------------------------------------

# Cached (pixformat, result) pair for get_DoviTunnelVar.  The sysfs DV mode
# only changes on a VS10 mode switch, and any switch also changes the Amlogic
# pixel format (bit depth / color format), so keying the cache on the raw
# pixformat string keeps the value fresh without re-reading sysfs every
# polling cycle.  Cleared automatically per overlay session (module state).
_dovi_tunnel_cache: tuple[str, str] | None = None


def get_DoviTunnelVar() -> str:
    """
    Read Dolby Vision mode from sysfs, cached per Amlogic pixel format.

    Only reported when the active pixel format is 8-bit, i.e.
    ``Player.Process(amlogic.pixformat)`` starts with ``8-bit``.

    Returns:
        "DV Tunnel" if the sysfs value is 1 and the output is 8-bit.
        "" otherwise.
    """
    global _dovi_tunnel_cache

    pixformat = info("Player.Process(amlogic.pixformat)").strip()
    if _dovi_tunnel_cache is not None and _dovi_tunnel_cache[0] == pixformat:
        return _dovi_tunnel_cache[1]

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
            # Keep the node readable next cycle instead of caching a failure.
            return ""

    _dovi_tunnel_cache = (pixformat, result)
    return result


def _with_unit(value: str, unit: str) -> str:
    """Append a unit only to real metadata values, not status labels."""
    if not value or is_status_label(value):
        return value
    if not unit:
        return value
    return f"{value} {unit}"


# ---------------------------------------------------------------------------
# Amlogic EOFT / gamut
# ---------------------------------------------------------------------------

def get_ModeVar() -> str:
    """Return the first token of ``amlogic.eoft_gamut`` (the mode field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[0] if parts else ""


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# Audio properties
# ---------------------------------------------------------------------------

def get_AudioBitrateKBVar() -> str:
    """Convert the audio bitrate from kb/s to Kb/s and return a display string."""
    bitrate = clean(info("VideoPlayer.AudioBitrate"))
    try:
        kbps = int(float(bitrate))
    except (TypeError, ValueError):
        return ""
    return f"{kbps:,} Kb/s".replace(",", ".")


def get_AudioLiveBitrateVar() -> str:
    """Return audio live bitrate with dot instead of comma."""
    bitrate = info("Player.Process(audiolivebitrate)")
    if not bitrate:
        return ""

    return str(bitrate).replace(",", ".")


def get_AudioCodecVar() -> str:
    """Return the mapped display name for the current audio codec."""
    codec = info("VideoPlayer.AudioCodec")
    if not codec:
        return xbmc.getLocalizedString(13205)
    return AUDIO_CODEC_MAP.get(codec, codec)


def get_AudioCodecSpatialVar() -> str:
    """Return the spatial-audio suffix: ``'(Atmos)'``, ``'(IMAX Enhanced)'``, or ``''``."""
    codec = info("VideoPlayer.AudioCodec")
    if codec == "dtshd_ma_x_imax":
        return "(IMAX Enhanced)"
    if codec in ("eac3_ddp_atmos", "truehd_atmos"):
        return "(Atmos)"
    return ""


def get_AudioChannelsVar() -> str:
    """Return the surround layout string for the current channel count, e.g. ``'7.1'``."""
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
        return CHANNELS_MAP.get(ch, "")
    except (ValueError, TypeError):
        return ""


def get_AudioChannelsInputVar() -> str:
    """Return the full speaker-label string for the current channel count."""
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
        return CHANNELS_INPUT_MAP.get(ch, xbmc.getLocalizedString(13205))
    except (ValueError, TypeError):
        return xbmc.getLocalizedString(13205)


def get_AudioSampleRateVar() -> str:
    """Convert the audio sample rate from Hz to kHz and return a display string."""
    samplerate = clean(info("Player.Process(audiosamplerate)"))
    try:
        hz = float(samplerate)
    except (TypeError, ValueError):
        return ""
    khz = hz / 1000.0
    return f"{int(khz)} kHz" if khz.is_integer() else f"{khz:.1f} kHz"


def get_AudioNameVar() -> str:
    """Return the native language name for the active audio track language code."""
    code = info("VideoPlayer.AudioLanguage").lower().strip()
    return LANGUAGE_MAP.get(code, "") if code else ""


def get_AudioNameShortVar() -> str:
    """Return the native short language name for the active audio track language code."""
    code = info("VideoPlayer.AudioLanguage").lower().strip()
    return LANGUAGE_MAP_SHORT.get(code, "") if code else ""


# ---------------------------------------------------------------------------
# Subtitle properties
# ---------------------------------------------------------------------------

def get_SubtitleNameVar() -> str:
    """
    Return the native language name for the active subtitle language code.
    """
    code = info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return LANGUAGE_MAP.get(code, "") if code else ""


def get_SubtitleNameShortVar() -> str:
    """
    Return the native short language name for the active subtitle language code.
    """
    code = info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return LANGUAGE_MAP_SHORT.get(code, "") if code else ""


def get_SubtitleCodecVar() -> str:
    """
    Return the mapped display name for the current subtitle codec.
    """
    codec = info("VideoPlayer.SubtitleCodec").lower().strip()
    return SUBTITLE_CODEC_MAP.get(codec, codec.upper()) if codec else ""


# ---------------------------------------------------------------------------
# System properties
# ---------------------------------------------------------------------------

_CPU_CORE_RE = re.compile(r"#\d+:\s*([\d.]+)%")


def _cpu_core_loads(raw: str) -> list[float]:
    """Parse ``System.CpuUsage`` into the per-core percentages."""
    loads = []
    for val in _CPU_CORE_RE.findall(raw):
        try:
            loads.append(float(val))
        except ValueError:
            continue
    return loads


def get_CpuUsageVar() -> str:
    """
    Parse ``System.CpuUsage`` and return a zero-padded, pipe-separated
    per-core usage string, e.g. ``'12 | 08 | 15 | 10'``.
    """
    raw = info("System.CpuUsage")
    if not raw:
        return ""

    loads = _cpu_core_loads(raw)
    if not loads:
        return raw

    return " | ".join(f"{int(v):02d}" for v in loads)


def get_CpuTopUsageVar() -> str:
    """
    Return the average CPU usage across all cores as a percentage string,
    e.g. ``'34%'``.

    Derived from Kodi's ``System.CpuUsage`` per-core values (the same source
    as :func:`get_CpuUsageVar`) instead of reading ``/proc/stat``, so no
    kernel access is needed.  Returns an empty string when Kodi reports no
    parseable per-core values.
    """
    loads = _cpu_core_loads(info("System.CpuUsage"))
    if not loads:
        return ""

    return f"{sum(loads) / len(loads):.0f}%"


def get_CpuTemperatureProgressVar() -> float:
    """
    Map System.CPUTemperature to a progress value from 0 to 100.

    Celsius:    0-110 C
    Fahrenheit: 32-230 F
    """
    raw = info("System.CPUTemperature").strip()
    if not raw:
        return 0.0

    temperature = _first_float(raw)
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


def get_queue_level(info_label: str) -> float:
    """
    Read a queue level from Kodi.

    Kodi may report a completely filled queue as only 99%.
    Values of 99 or higher are therefore treated as 100%.
    """
    raw = info(info_label).strip()

    value = _first_float(raw)
    if value is None:
        return 0.0

    value = max(0.0, min(value, 100.0))

    if value >= 99:
        return 100.0

    return value


def format_queue_level(value: float) -> str:
    """Format a queue level without unnecessary decimal places."""
    if value.is_integer():
        return str(int(value))

    return f"{value:.1f}".rstrip("0").rstrip(".")


def _metadata_unit() -> str:
    """Return the configured L6 metadata unit, including Kodi color markup."""
    unit_color = info("Window(10000).Property(TinyPPI.UnitColor)")
    unit_label = info("Window(10000).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return ""
    if unit_color:
        return f"[COLOR={unit_color}]{unit_label}[/COLOR]"
    return unit_label


def publish_hdr_type(home=None) -> None:
    """Publish the hdrprobe-detected HDR type on Kodi's Home window.

    ``TinyPPI.HdrType`` replaces the ``VideoPlayer.HdrType`` infolabel the skin
    branches on (SDR / HDR10 / Dolby Vision).  It lives on the global Home
    window so both the overlay and the mode-select dialog can read it, and is
    refreshed each polling cycle as background detection completes.

    The HDR10+ token is published as ``hdr10plus`` (not ``hdr10+``): Kodi's
    boolean parser treats ``+`` as the AND operator, so a skin condition like
    ``String.IsEqual(...,hdr10+)`` would not parse.  ``hdr10plus`` still
    contains ``hdr10``, so existing ``String.Contains(...,hdr10)`` branches keep
    matching it.
    """
    hdr_type = get_hdr_format()
    if hdr_type == "hdr10+":
        hdr_type = "hdr10plus"
    (home or xbmcgui.Window(10000)).setProperty("TinyPPI.HdrType", hdr_type)


def _set_progress(window, values: tuple[tuple[int, float], ...]) -> None:
    """Publish a batch of progress-control percentages."""
    for control_id, value in values:
        window.getControl(control_id).setPercent(value)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def update_properties(window) -> None:
    """
    Compute all player properties and publish them to the given window object
    via ``setProperty``.

    Call this from ``onInit()`` and from a polling loop in your
    ``WindowXMLDialog`` subclass.
    """

    publish_hdr_type()

    unit = _metadata_unit()
    video_queue = get_queue_level("Player.Process(videoqueuelevel)")
    video_queue_data = get_queue_level("Player.Process(videoqueuedatalevel)")
    audio_queue = get_queue_level("Player.Process(audioqueuelevel)")
    audio_queue_data = get_queue_level("Player.Process(audioqueuedatalevel)")
    fps_info_text, fps_out_text = fps_display_texts()

    # Output-mode line from hdrprobe, e.g. ``HDR10`` or
    # ``Dolby Vision Profile 7 [COLOR lightgreen]FEL[/COLOR]``; the Alt variant
    # uses the shorter ``DV Profile`` prefix.
    output_mode = get_output_mode()

    l5_offsets = get_l5_offsets()
    l5_offsets_icon_visible = (
        "true"
        if l5_offsets and not is_status_label(l5_offsets)
        else "false"
    )

    l6_rpu_mdl          = _with_unit(get_l6_rpu_mdl(), unit)
    l6_rpu_max_cll_fall = _with_unit(get_l6_rpu_max_cll_fall(), unit)

    set_window_properties(
        window,
        (
            ("VideoDecoderVar", get_VideoDecoderVar()),
            ("VideoPixelFormatVar", get_VideoPixelFormatVar()),
            ("DisplayModeVar", get_DisplayModeVar()),
            ("VideoResolutionVar", get_VideoResolutionVar()),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoCodecVar", get_VideoCodecVar()),
            ("VideoDecoderNameVar", get_VideoDecoderNameVar()),
            ("VideoBitDepthVar", get_VideoBitDepthVar()),
            ("DoviProfileVar", output_mode),
            ("DoviProfileAltVar", output_mode.replace("Dolby Vision Profile", "DV Profile")),
            ("DoviTunnelVar", get_DoviTunnelVar()),
            ("DoviCmVersionVar", get_cm_version()),
            ("DoviStructureVar", get_structure()),
            ("DoviLevel5OffsetsVar", l5_offsets),
            ("DoviLevel5OffsetsIconVisible", l5_offsets_icon_visible),
            ("DoviLevel6RpuMdlVar", l6_rpu_mdl),
            ("DoviLevel6RpuMaxCllFallVar", l6_rpu_max_cll_fall),
            ("ModeVar", get_ModeVar()),
            ("GamutVar", get_GamutVar()),
            ("VideoLiveBitrateVar", get_VideoLiveBitrateVar()),
            ("FpsInfoVar", fps_info_text),
            ("FpsDropVar", fps_out_text),
            ("AudioBitrateKBVar", get_AudioBitrateKBVar()),
            ("AudioLiveBitrateVar", get_AudioLiveBitrateVar()),
            ("AudioCodecVar", get_AudioCodecVar()),
            ("AudioCodecSpatialVar", get_AudioCodecSpatialVar()),
            ("AudioChannelsVar", get_AudioChannelsVar()),
            ("AudioChannelsInputVar", get_AudioChannelsInputVar()),
            ("AudioSampleRateVar", get_AudioSampleRateVar()),
            ("AudioNameVar", get_AudioNameVar()),
            ("AudioNameShortVar", get_AudioNameShortVar()),
            ("SubtitleCodecVar", get_SubtitleCodecVar()),
            ("SubtitleNameVar", get_SubtitleNameVar()),
            ("SubtitleNameShortVar", get_SubtitleNameShortVar()),
            ("CpuUsageVar", get_CpuUsageVar()),
            ("CpuTopUsageVar", get_CpuTopUsageVar()),
            ("VideoQueueLevelVar", format_queue_level(video_queue)),
            ("VideoQueueDataLevelVar", format_queue_level(video_queue_data)),
            ("AudioQueueLevelVar", format_queue_level(audio_queue)),
            ("AudioQueueDataLevelVar", format_queue_level(audio_queue_data)),
            ("CurrentSkin", xbmc.getSkinDir()),
        ),
    )

    _set_progress(
        window,
        (
            (9100, get_CpuTemperatureProgressVar()),
            (9101, video_queue),
            (9102, video_queue_data),
            (9103, audio_queue),
            (9104, audio_queue_data),
        ),
    )
