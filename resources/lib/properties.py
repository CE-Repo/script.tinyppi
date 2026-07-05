"""
properties.py – Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval from your
``WindowXMLDialog`` subclass.
"""

import re

import xbmc
import xbmcgui

from maps import (
    _AUDIO_CODEC_MAP,
    _CHANNELS_INPUT_MAP,
    _CHANNELS_MAP,
    _LANGUAGE_MAP,
    _LANGUAGE_MAP_SHORT,
    _VIDEO_CODEC_MAP,
    _SUBTITLE_CODEC_MAP,
)
from utils import _cond, _info, _clean
from helpers import (
    _normalize_fps,
    _format_fps,
    _read_hdr_status,
    _read_last_dovi_log_line,
    format_fps,
)
from dvinfo import (
    get_bit_depth,
    get_cm_version,
    get_hdr_format,
    get_output_mode,
    get_l5_offsets,
    get_l6_rpu_mdl,
    get_l6_rpu_max_cll_fall,
    is_status_label,
)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Previous /proc/stat snapshot for delta-based CPU usage calculation.
_cpu_prev: tuple[int, int] | None = None

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
    return "HW" if _cond("Player.Process(videohwdecoder)") else "SW"


def get_VideoDecoderExtVar() -> str:
    """Return 'Hardware' or 'Software' based on the active video decoder type."""
    return "Hardware" if _cond("Player.Process(videohwdecoder)") else "Software"


def get_VideoPixelFormatVar() -> str:
    """
    Parse ``amlogic.pixformat`` and return a human-readable string such as
    ``10-bit (YUV 4:2:0)`` or ``8-bit, RGB``.
    """
    val = _info("Player.Process(amlogic.pixformat)").strip()
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
    val = _info("Player.Process(amlogic.displaymode)").strip()
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
    return f"{res}{scan} {_normalize_fps(raw_fps)}Hz"


def get_VideoResolutionVar() -> str:
    """Return a string like ``1920x1080p 23.976FPS``."""
    width  = _clean(_info("Player.Process(videowidth)"))
    height = _clean(_info("Player.Process(videoheight)"))
    scan   = _clean(_info("Player.Process(videoscantype)"))
    fps    = _clean(_info("Player.Process(videofps)"))

    if not width or not height:
        return ""

    return f"{width}x{height}{scan} {_format_fps(fps)}FPS"


def get_VideoBitrateMBVar() -> str:
    """Convert the video bitrate from kb/s to Mb/s and return a display string."""
    bitrate = _clean(_info("VideoPlayer.VideoBitrate"))
    try:
        mbit = float(bitrate) / 1000.0
    except (TypeError, ValueError):
        return ""

    value = f"{mbit:.2f}".rstrip("0").rstrip(".")
    return f"{value} Mb/s"


def get_VideoLiveBitrateVar() -> str:
    """Format live video bitrate without failing on malformed Kodi values."""
    bitrate = _info("Player.Process(videolivebitrate)").strip()

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
    codec = _info("VideoPlayer.VideoCodec").lower().strip()
    if not codec:
        return ""
    return _VIDEO_CODEC_MAP.get(codec, codec.upper())


def get_VideoBitDepthVar() -> str:
    """
    Return the source video bit depth for display, e.g. ``12-bit``.

    FEL Dolby Vision streams reconstruct a 12-bit signal from a 10-bit base
    layer, so 12-bit is reported for them; every other format uses hdrprobe's
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

def get_HdmiHdrStatusVar() -> str:
    """
    Return the non-Dolby HDR format currently active on the HDMI output:
    ``HDR10+``, ``HLG``, ``HDR10``, or ``SDR``.

    Returns an empty string when Dolby Vision is active or the sysfs node
    is unavailable.
    """
    status = _read_hdr_status()
    if not status or "dolby" in status:
        return ""

    if "hdr10plus" in status or "hdr10+" in status:
        return "HDR10+"
    if "hlg" in status:
        return "HLG"
    if "hdr10" in status:
        return "HDR10"
    if "sdr" in status:
        return "SDR"
    return ""


def get_DoviProfileVar() -> str:
    """
    Return the overlay's output-mode string from hdrprobe: the source format
    (``HDR10``, ``HDR10+``, ``HLG``, ``SDR``) or, for Dolby Vision, a string
    such as ``Dolby Vision Profile 7 [COLOR lightgreen]FEL[/COLOR]`` with the
    enhancement layer coloured — FEL green, MEL orange.

    Detection runs in a background thread (see dvinfo.py), so this never blocks;
    a localized ``Fetching...`` / ``N/A`` status label is shown while detection
    is running or after it fails.
    """
    return get_output_mode()


def get_DoviFelVar() -> str:
    """Return ``'FEL'`` when a full-enhancement-layer DV stream is active, else ``''``."""
    if "dolby" not in _read_hdr_status():
        return ""
    text = _read_last_dovi_log_line()
    return "FEL" if "full enhancement layer" in text else ""


def get_DoviTunnelVar() -> str:
    """
    Read Dolby Vision mode from sysfs.

    Only reported when the active pixel format is 8-bit, i.e.
    ``Player.Process(amlogic.pixformat)`` starts with ``8-bit``.

    Returns:
        "DV Tunnel" if the sysfs value is 1 and the output is 8-bit.
        "" otherwise.
    """
    pixformat = _info("Player.Process(amlogic.pixformat)").strip()
    bits = re.search(r"(\d+)-bit", pixformat, re.IGNORECASE)
    if not bits or bits.group(1) != "8":
        return ""

    path = "/sys/module/aml_media/parameters/dolby_vision_mode"

    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            value = f.read().strip()
    except OSError:
        return ""

    return "DV Tunnel" if value == "1" else ""


def get_DoviCmVersionVar() -> str:
    """
    Return the source Dolby Vision Content-Mapping version
    (``'CMv2.9'`` or ``'CMv4.0'``), or ``''`` when it is not (yet) known.

    Unlike the other fields, this never surfaces a "Fetching..." or "N/A"
    status label: the value is shown only once detected, and stays empty
    otherwise.

    Detection runs once per file in a background thread (see dvinfo.py), so
    this call never blocks the polling loop.
    """
    return get_cm_version()


def get_DoviLevel5OffsetsVar() -> str:
    """
    Return the source Dolby Vision Level 5 active-area offsets, a localized
    status while/after detection, or ``''`` when the source is not Dolby Vision.
    """
    return get_l5_offsets()


def get_DoviLevel6RpuMdlVar() -> str:
    """
    Return the source mastering-display luminance: the Dolby Vision Level 6 RPU
    value, or the static HDR10 mastering display when the source is HDR10.
    Falls back to a localized status while/after detection, and to N/A for SDR.
    """
    return get_l6_rpu_mdl()


def get_DoviLevel6RpuMaxCllFallVar() -> str:
    """
    Return the source MaxCLL/MaxFALL content light: the Dolby Vision Level 6 RPU
    value, or the static HDR10 content light when the source is HDR10.  Falls
    back to a localized status while/after detection, and to N/A for SDR.
    """
    return get_l6_rpu_max_cll_fall()


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
    parts = _info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[0] if parts else ""


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = _info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# Vdec bitrate  (Amlogic kernel sysfs)
# ---------------------------------------------------------------------------

def get_VdecBitrateVar() -> tuple[str, str]:
    """
    Read the hardware decoder bitrate from sysfs and return a
    ``(value, unit)`` tuple, e.g. ``('23.45', 'Mb/s')`` or ``('850', 'Kb/s')``.

    Returns ``('', '')`` when the node is unavailable or contains no data.
    """
    path = "/sys/class/vdec/vdec_status"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = f.read()
    except OSError:
        return "", ""

    matches = re.findall(r"bit rate\s*:\s*(\d+)\s*kbps", data, re.IGNORECASE)
    if not matches:
        return "", ""

    kbps = max(float(m) for m in matches)
    if kbps <= 0:
        return "", ""

    if kbps < 1000:
        return f"{kbps:.0f}", "Kb/s"

    mbps = kbps / 1000.0
    return f"{mbps:.2f}".rstrip("0").rstrip("."), "Mb/s"


# ---------------------------------------------------------------------------
# Audio properties
# ---------------------------------------------------------------------------

def get_AudioBitrateKBVar() -> str:
    """Convert the audio bitrate from kb/s to Kb/s and return a display string."""
    bitrate = _clean(_info("VideoPlayer.AudioBitrate"))
    try:
        kbps = int(float(bitrate))
    except (TypeError, ValueError):
        return ""
    return f"{kbps:,} Kb/s".replace(",", ".")


def get_AudioLiveBitrateVar() -> str:
    """Return audio live bitrate with dot instead of comma."""
    bitrate = _info("Player.Process(audiolivebitrate)")
    if not bitrate:
        return ""

    return str(bitrate).replace(",", ".")


def get_AudioCodecVar() -> str:
    """Return the mapped display name for the current audio codec."""
    codec = _info("VideoPlayer.AudioCodec")
    if not codec:
        return xbmc.getLocalizedString(13205)
    return _AUDIO_CODEC_MAP.get(codec, codec)


def get_AudioCodecSpatialVar() -> str:
    """Return the spatial-audio suffix: ``'(Atmos)'``, ``'(IMAX Enhanced)'``, or ``''``."""
    codec = _info("VideoPlayer.AudioCodec")
    if codec == "dtshd_ma_x_imax":
        return "(IMAX Enhanced)"
    if codec in ("eac3_ddp_atmos", "truehd_atmos"):
        return "(Atmos)"
    return ""


def get_AudioChannelsVar() -> str:
    """Return the surround layout string for the current channel count, e.g. ``'7.1'``."""
    try:
        ch = int(_info("VideoPlayer.AudioChannels"))
        return _CHANNELS_MAP.get(ch, "")
    except (ValueError, TypeError):
        return ""


def get_AudioChannelsInputVar() -> str:
    """Return the full speaker-label string for the current channel count."""
    try:
        ch = int(_info("VideoPlayer.AudioChannels"))
        return _CHANNELS_INPUT_MAP.get(ch, xbmc.getLocalizedString(13205))
    except (ValueError, TypeError):
        return xbmc.getLocalizedString(13205)


def get_AudioSampleRateVar() -> str:
    """Convert the audio sample rate from Hz to kHz and return a display string."""
    samplerate = _clean(_info("Player.Process(audiosamplerate)"))
    try:
        hz = float(samplerate)
    except (TypeError, ValueError):
        return ""
    khz = hz / 1000.0
    return f"{int(khz)} kHz" if khz.is_integer() else f"{khz:.1f} kHz"


def get_AudioNameVar() -> str:
    """Return the native language name for the active audio track language code."""
    code = _info("VideoPlayer.AudioLanguage").lower().strip()
    return _LANGUAGE_MAP.get(code, "") if code else ""


def get_AudioNameShortVar() -> str:
    """Return the native short language name for the active audio track language code."""
    code = _info("VideoPlayer.AudioLanguage").lower().strip()
    return _LANGUAGE_MAP_SHORT.get(code, "") if code else ""


# ---------------------------------------------------------------------------
# Subtitle properties
# ---------------------------------------------------------------------------

def get_SubtitleVar() -> str:
    """
    Return the active subtitle language.
    """
    lang = _info("VideoPlayer.SubtitlesLanguage").strip()

    if not lang:
        return _info("VideoPlayer.SubtitleLanguageEx")

    return lang.upper()


def get_SubtitleNameVar() -> str:
    """
    Return the native language name for the active subtitle language code.
    """
    code = _info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return _LANGUAGE_MAP.get(code, "") if code else ""


def get_SubtitleNameShortVar() -> str:
    """
    Return the native short language name for the active subtitle language code.
    """
    code = _info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return _LANGUAGE_MAP_SHORT.get(code, "") if code else ""


def get_SubtitleNameInfoVar() -> str:
    """
    Return the active subtitle track name formatted for display.
    """
    name = _info("VideoPlayer.SubtitleName").strip()

    if not name:
        return ""

    return f"| {name}"


def get_SubtitleCodecVar() -> str:
    """
    Return the mapped display name for the current subtitle codec.
    """
    codec = _info("VideoPlayer.SubtitleCodec").lower().strip()
    return _SUBTITLE_CODEC_MAP.get(codec, codec.upper()) if codec else ""


# ---------------------------------------------------------------------------
# System properties
# ---------------------------------------------------------------------------

def get_CpuUsageVar() -> str:
    """
    Parse ``System.CpuUsage`` and return a zero-padded, pipe-separated
    per-core usage string, e.g. ``'12 | 08 | 15 | 10'``.
    """
    raw = _info("System.CpuUsage")
    if not raw:
        return ""

    matches = re.findall(r"#\d+:\s*([\d.]+)%", raw)
    if not matches:
        return raw

    values = []
    for val in matches:
        try:
            values.append(f"{int(float(val)):02d}")
        except ValueError:
            continue
    return " | ".join(values)


def get_CpuTopUsageVar() -> str:
    """
    Compute total CPU usage from consecutive /proc/stat snapshots and return
    it as a percentage string, e.g. ``'34%'``.

    Returns an empty string on the very first call (no previous sample yet)
    or when /proc/stat cannot be read.
    """
    global _cpu_prev

    try:
        with open("/proc/stat") as f:
            line = f.readline()
    except OSError:
        return ""

    parts = line.split()
    if len(parts) < 8:
        return ""

    try:
        user, nice, system, idle, iowait, irq, softirq = (
            int(parts[i]) for i in range(1, 8)
        )
    except ValueError:
        return ""

    idle_all = idle + iowait
    total    = user + nice + system + idle_all + irq + softirq
    busy     = total - idle_all

    if _cpu_prev is None:
        _cpu_prev = (busy, total)
        return ""

    prev_busy, prev_total = _cpu_prev
    _cpu_prev = (busy, total)

    diff_total = total - prev_total
    if diff_total <= 0:
        return ""

    usage = (busy - prev_busy) / diff_total * 100.0
    return f"{usage:.0f}%"


def get_CpuTemperatureProgressVar() -> float:
    """
    Map System.CPUTemperature to a progress value from 0 to 100.

    Celsius:    0-110 C
    Fahrenheit: 32-230 F
    """
    raw = _info("System.CPUTemperature").strip()
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
    raw = _info(info_label).strip()

    value = _first_float(raw)
    if value is None:
        return 0.0

    value = max(0, min(value, 100))

    if value >= 99:
        return 100

    return value


def format_queue_level(value: float) -> str:
    """Format a queue level without unnecessary decimal places."""
    if value.is_integer():
        return str(int(value))

    return f"{value:.1f}".rstrip("0").rstrip(".")


def _metadata_unit() -> str:
    """Return the configured L6 metadata unit, including Kodi color markup."""
    unit_color = xbmc.getInfoLabel("Window(10000).Property(TinyPPI.UnitColor)")
    unit_label = xbmc.getInfoLabel("Window(10000).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return ""
    if unit_color:
        return f"[COLOR={unit_color}]{unit_label}[/COLOR]"
    return f" {unit_label}"


def publish_hdr_type(home=None) -> None:
    """Publish the hdrprobe-detected HDR type on Kodi's Home window.

    ``TinyPPI.HdrType`` replaces the ``VideoPlayer.HdrType`` infolabel the skin
    branches on (SDR / HDR10 / Dolby Vision).  It lives on the global Home
    window so both the overlay and the mode-select dialog can read it, and is
    refreshed each polling cycle as background detection completes.
    """
    (home or xbmcgui.Window(10000)).setProperty("TinyPPI.HdrType", get_hdr_format())


def _set_properties(window, values: tuple[tuple[str, str], ...]) -> None:
    """Publish a batch of Kodi window properties."""
    for name, value in values:
        window.setProperty(name, value)


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
    bitrate_value, bitrate_unit = get_VdecBitrateVar()
    fps_info_text, fps_out_text = format_fps()

    l5_offsets = get_DoviLevel5OffsetsVar()
    l5_offsets_icon_visible = (
        "true"
        if l5_offsets and not is_status_label(l5_offsets)
        else "false"
    )

    l6_rpu_mdl          = _with_unit(get_DoviLevel6RpuMdlVar(), unit)
    l6_rpu_max_cll_fall = _with_unit(get_DoviLevel6RpuMaxCllFallVar(), unit)

    _set_properties(
        window,
        (
            ("VideoDecoderVar", get_VideoDecoderVar()),
            ("VideoDecoderExtVar", get_VideoDecoderExtVar()),
            ("VideoPixelFormatVar", get_VideoPixelFormatVar()),
            ("DisplayModeVar", get_DisplayModeVar()),
            ("VideoResolutionVar", get_VideoResolutionVar()),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoLiveBitrateVar", get_VideoLiveBitrateVar()),
            ("VideoCodecVar", get_VideoCodecVar()),
            ("VideoBitDepthVar", get_VideoBitDepthVar()),
            ("HdmiHdrStatusVar", get_HdmiHdrStatusVar()),
            ("DoviProfileVar", get_DoviProfileVar()),
            ("DoviFelVar", get_DoviFelVar()),
            ("DoviTunnelVar", get_DoviTunnelVar()),
            ("DoviCmVersionVar", get_DoviCmVersionVar()),
            ("DoviLevel5OffsetsVar", l5_offsets),
            ("DoviLevel5OffsetsIconVisible", l5_offsets_icon_visible),
            ("DoviLevel6RpuMdlVar", l6_rpu_mdl),
            ("DoviLevel6RpuMaxCllFallVar", l6_rpu_max_cll_fall),
            ("ModeVar", get_ModeVar()),
            ("GamutVar", get_GamutVar()),
            ("VdecBitrate", bitrate_value),
            ("VdecBitrateUnit", bitrate_unit),
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
            ("SubtitleVar", get_SubtitleVar()),
            ("SubtitleCodecVar", get_SubtitleCodecVar()),
            ("SubtitleNameInfoVar", get_SubtitleNameInfoVar()),
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
