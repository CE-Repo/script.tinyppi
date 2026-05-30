"""
properties.py – Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval from your
``WindowXMLDialog`` subclass.
"""

import re

import xbmc

from maps import (
    _AUDIO_CODEC_MAP,
    _CHANNELS_INPUT_MAP,
    _CHANNELS_MAP,
    _LANGUAGE_MAP,
    _SUBTITLE_CODEC_MAP,
    _VIDEO_CODEC_MAP,
)
from utils import _cond, _info, _clean
from helpers import (
    _normalize_fps,
    _format_fps,
    _read_hdr_status,
    _read_last_dovi_log_line,
    format_fps,
    get_fps_data,
    set_ui_position,
)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Previous /proc/stat snapshot for delta-based CPU usage calculation.
_cpu_prev: tuple[int, int] | None = None

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


def get_VideoCodecVar() -> str:
    """Return the mapped display name for the current video codec."""
    codec = _info("VideoPlayer.VideoCodec").lower().strip()
    if not codec:
        return ""
    return _VIDEO_CODEC_MAP.get(codec, codec.upper())


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
    Return a Dolby Vision profile string such as
    ``Dolby Vision Profile 7 [COLOR lightgreen]FEL[/COLOR]``.

    Returns an empty string when DV is not active or no matching log line
    can be found.
    """
    if "dolby" not in _read_hdr_status():
        return ""

    text = _read_last_dovi_log_line()
    if not text:
        return ""

    prof = re.search(r"profile\s*(\d+)", text)
    if not prof:
        return ""

    profile_num = prof.group(1)
    if profile_num in ("0", "8"):
        profile_num = "8.1"

    if "minimum enhancement layer" in text:
        return f"Dolby Vision Profile {profile_num} [COLOR orange]MEL[/COLOR]"
    if "full enhancement layer" in text:
        return f"Dolby Vision Profile {profile_num} [COLOR lightgreen]FEL[/COLOR]"
    return f"Dolby Vision Profile {profile_num}"


def get_DoviFelVar() -> str:
    """Return ``'FEL'`` when a full-enhancement-layer DV stream is active, else ``''``."""
    if "dolby" not in _read_hdr_status():
        return ""
    text = _read_last_dovi_log_line()
    return "FEL" if "full enhancement layer" in text else ""


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

def get_AudioBitrateMBVar() -> str:
    """Convert the audio bitrate from kb/s to Kb/s and return a display string."""
    bitrate = _clean(_info("VideoPlayer.AudioBitrate"))
    try:
        kbps = int(float(bitrate))
    except (TypeError, ValueError):
        return ""
    return f"{kbps:,} Kb/s".replace(",", ".")


def get_AudioCodecVar() -> str:
    """Return the mapped display name for the current audio codec."""
    codec = _info("VideoPlayer.AudioCodec")
    if not codec:
        return xbmc.getLocalizedString(13205)
    return _AUDIO_CODEC_MAP.get(codec, codec)


def get_AudioCodecSpatialVar() -> str:
    """Return the spatial-audio suffix: ``'(Atmos)'``, ``'(IMAX)'``, or ``''``."""
    codec = _info("VideoPlayer.AudioCodec")
    if codec == "dtshd_ma_x_imax":
        return "(IMAX)"
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


# ---------------------------------------------------------------------------
# Subtitle properties
# ---------------------------------------------------------------------------

def get_SubtitleNameVar() -> str:
    """Return the native language name for the active subtitle language code."""
    code = _info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return _LANGUAGE_MAP.get(code, "") if code else ""


def get_SubtitleCodecVar() -> str:
    """Return the mapped display name for the current subtitle codec."""
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
        user, nice, system, idle, iowait, irq, softirq = (int(parts[i]) for i in range(1, 8))
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
    set_ui_position(window)

    bitrate_value, bitrate_unit = get_VdecBitrateVar()
    fps_info_text, fps_out_text = format_fps()

    window.setProperty("VideoDecoderVar",       get_VideoDecoderVar())
    window.setProperty("VideoDecoderExtVar",    get_VideoDecoderExtVar())
    window.setProperty("VideoPixelFormatVar",   get_VideoPixelFormatVar())
    window.setProperty("DisplayModeVar",        get_DisplayModeVar())
    window.setProperty("VideoResolutionVar",    get_VideoResolutionVar())
    window.setProperty("VideoBitrateMBVar",     get_VideoBitrateMBVar())
    window.setProperty("VideoCodecVar",         get_VideoCodecVar())
    window.setProperty("HdmiHdrStatusVar",      get_HdmiHdrStatusVar())
    window.setProperty("DoviProfileVar",        get_DoviProfileVar())
    window.setProperty("DoviFelVar",            get_DoviFelVar())
    window.setProperty("ModeVar",               get_ModeVar())
    window.setProperty("GamutVar",              get_GamutVar())
    window.setProperty("VdecBitrate",           bitrate_value)
    window.setProperty("VdecBitrateUnit",       bitrate_unit)
    window.setProperty("FpsInfoVar",            fps_info_text)
    window.setProperty("FpsDropVar",            fps_out_text)
    window.setProperty("AudioBitrateMBVar",     get_AudioBitrateMBVar())
    window.setProperty("AudioCodecVar",         get_AudioCodecVar())
    window.setProperty("AudioCodecSpatialVar",  get_AudioCodecSpatialVar())
    window.setProperty("AudioChannelsVar",      get_AudioChannelsVar())
    window.setProperty("AudioChannelsInputVar", get_AudioChannelsInputVar())
    window.setProperty("AudioSampleRateVar",    get_AudioSampleRateVar())
    window.setProperty("AudioNameVar",          get_AudioNameVar())
    window.setProperty("SubtitleCodecVar",      get_SubtitleCodecVar())
    window.setProperty("SubtitleNameVar",       get_SubtitleNameVar())
    window.setProperty("CpuUsageVar",           get_CpuUsageVar())
    window.setProperty("CpuTopUsageVar",        get_CpuTopUsageVar())
    window.setProperty("CurrentSkin",           xbmc.getSkinDir())
