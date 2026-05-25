import re
import xbmc
import xbmcgui

from constants import (_VIDEO_CODEC_MAP, _SUBTITLE_CODEC_MAP, _AUDIO_CODEC_MAP, _CHANNELS_MAP, _CHANNELS_INPUT_MAP, _LANGUAGE_MAP)

def _cond(condition):
    return xbmc.getCondVisibility(condition)


def _info(label):
    return xbmc.getInfoLabel(label)

    
def _clean(val):
    if val is None:
        return ""
    return str(val).replace(",", "")


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

def get_VideoDecoderVar():
    if _cond("Player.Process(videohwdecoder)"):
        return "HW"
    return "SW"


def get_VideoPixelFormatVar():
    val = _info("Player.Process(amlogic.pixformat)")

    if not val:
        return ""

    val = str(val).strip()

    match = re.search(
        r"(\d+)-bit\s*,\s*(RGB|YUV420|YUV422|YUV444)",
        val,
        re.IGNORECASE
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


def _normalize_fps(fps_value):
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return fps_value

    standards = [
        23.976,
        24.0,
        25.0,
        29.97,
        30.0,
        50.0,
        59.94,
        60.0,
        100.0,
        120.0,
    ]

    closest = min(standards, key=lambda x: abs(x - fps))

    if abs(closest - fps) > 0.5:
        return f"{fps:.3f}".rstrip("0").rstrip(".")

    if closest == 23.976:
        return "23.976"
    if closest == 29.97:
        return "29.97"
    if closest == 59.94:
        return "59.94"

    return str(int(closest)) if closest.is_integer() else str(closest)


def get_DisplayModeVar():
    val = _info("Player.Process(amlogic.displaymode)")
    if not val:
        return ""

    val = str(val).strip()

    compact = re.sub(r"\s+", "", val)

    match = re.match(
        r"(\d+(?:x\d+)?)(p|i)(\d+(?:\.\d+)?)[Hh][Zz]",
        compact,
        re.IGNORECASE,
    )
    if not match:
        return val

    res, scan, raw_fps = match.groups()
    norm_fps = _normalize_fps(raw_fps)

    return f"{res}{scan} {norm_fps}Hz"

    
def _format_fps(fps_value):
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return ""

    targets = [
        (23.976, 0.02),
        (29.97,  0.02),
        (59.94,  0.02),
        (60.0,   0.01),
    ]

    for target, tol in targets:
        if abs(fps - target) <= tol:
            fps = target
            break

    if fps.is_integer():
        return str(int(fps))

    return f"{fps:.3f}".rstrip("0").rstrip(".")


def get_VideoResolutionVar():
    width  = _clean(_info("Player.Process(videowidth)"))
    height = _clean(_info("Player.Process(videoheight)"))
    scan   = _clean(_info("Player.Process(videoscantype)"))
    fps    = _clean(_info("Player.Process(videofps)"))

    if not width or not height:
        return ""

    fps = _format_fps(fps)

    return f"{width}x{height}{scan} {fps}FPS"


def get_VideoBitrateMBVar():
    bitrate = _clean(_info("VideoPlayer.VideoBitrate"))

    try:
        kbps = float(bitrate)
    except (TypeError, ValueError):
        return ""

    mbit = kbps / 1000.0

    value = f"{mbit:.2f}".rstrip("0").rstrip(".")

    return f"{value} Mb/s"

    
def get_AudioBitrateMBVar():
    bitrate = _clean(_info("VideoPlayer.AudioBitrate"))

    try:
        kbps = int(float(bitrate))
    except (TypeError, ValueError):
        return ""

    return f"{kbps:,} Kb/s".replace(",", ".")


def get_HdrTypeVar():
    val = _info("VideoPlayer.HdrType")

    if not val:
        return "SDR"

    val = str(val).lower()

    if "dolbyvision" in val:
        return "Dolby Vision"
    if val == "hdr10plus":
        return "HDR10+"
    if "hdr10" in val:
        return "HDR10"
    if "hlg" in val:
        return "HLG"

    return val.upper()


def get_HdrDetailVar():
    val = _info("VideoPlayer.HdrDetail")

    if not val:
        return ""

    val = str(val).strip()

    if val == "7MEL":
        return "Profile 7 [COLOR orange]MEL[/COLOR]"
    if val == "7FEL":
        return "Profile 7 [COLOR lightgreen]FEL[/COLOR]"

    return f"Profile {val}"


def get_ModeVar():
    val = _info("Player.Process(amlogic.eoft_gamut)")

    if not val:
        return ""

    parts = str(val).split()

    return parts[0] if len(parts) > 0 else ""


def get_ModeConvertVar():
    val = _info("Player.Process(amlogic.eoft_gamut)")

    if not val:
        return ""

    val = str(val).strip().upper()

    if "DV" in val or "dolbyvision" in val:
        result = "-> Dolby Vision Profile 8.1"
        base = "Dolby Vision"
        
    elif "HDR10+" in val or "hdr10plus" in val:
        result = ""
        base = "HDR10+"

    elif "HDR10" in val or "hdr10" in val:
        result = "-> HDR10"
        base = "HDR10"

    elif "SDR" in val or "" in val:
        result = "-> SDR"
        base = "SDR"

    else:
        return ""

    hdr = get_HdrTypeVar()

    if hdr.lower() == base.lower():
        return ""

    return result


def get_GamutVar():
    val = _info("Player.Process(amlogic.eoft_gamut)")

    if not val:
        return ""

    parts = str(val).split()

    return parts[1] if len(parts) > 1 else ""


def get_VideoCodecVar():
    codec = _info("VideoPlayer.VideoCodec")

    if not codec:
        return ""

    codec = str(codec).lower().strip()

    return _VIDEO_CODEC_MAP.get(codec, codec.upper())


def get_HdrCheckVar():
    hdr = _info("VideoPlayer.HdrType")
    gamut = _info("Player.Process(amlogic.eoft_gamut)")

    hdr_l = (hdr or "").lower()
    gamut_l = (gamut or "").lower()

    def is_empty(x):
        return not x or str(x).strip() == ""

    def contains(hay, needle):
        return needle.lower() in hay

    sdr_ok = (not is_empty(hdr)) and contains(gamut_l, "sdr")

    hdr10_ok = (
        (is_empty(hdr) or
         contains(hdr_l, "dolbyvision") or
         contains(hdr_l, "hlg"))
        and contains(gamut_l, "hdr10")
    )

    dv_ok = (
        (is_empty(hdr) or
         contains(hdr_l, "hdr10") or
         contains(hdr_l, "hdr10plus") or
         contains(hdr_l, "hlg"))
        and contains(gamut_l, "dv")
    )

    result = sdr_ok or hdr10_ok or dv_ok

    if xbmc.getSkinDir() == "skin.estuary":
        return "[COLOR lightgreen]■͏[/COLOR]" if result else "[COLOR tomato]■͏[/COLOR]"
    else:
        return "[COLOR lightgreen][/COLOR]" if result else "[COLOR tomato][/COLOR]"


# ---------------------------------------------------------------------------
# Subtitle
# ---------------------------------------------------------------------------


def get_SubtitleNameVar():
    code = _info("VideoPlayer.SubtitlesLanguage")

    if not code:
        return ""

    code = str(code).lower().strip()

    return _LANGUAGE_MAP.get(code, "")


def get_SubtitleCodecVar():
    codec = _info("VideoPlayer.SubtitleCodec")

    if not codec:
        return ""

    codec = str(codec).lower().strip()

    return _SUBTITLE_CODEC_MAP.get(codec, codec.upper())

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def get_AudioCodecVar():
    codec = _info("VideoPlayer.AudioCodec")
    if not codec:
        return xbmc.getLocalizedString(13205)
    return _AUDIO_CODEC_MAP.get(codec, codec)


def get_AudioCodecSpatialVar():
    codec = _info("VideoPlayer.AudioCodec")
    if codec == "dtshd_ma_x_imax":
        return "(IMAX)"
    if codec in ("eac3_ddp_atmos", "truehd_atmos"):
        return "(Atmos)"
    return ""


def get_AudioChannelsVar():
    try:
        ch = int(_info("VideoPlayer.AudioChannels"))
        return _CHANNELS_MAP.get(ch, "")
    except (ValueError, TypeError):
        return ""


def get_AudioSampleRateVar():
    samplerate = _clean(_info("Player.Process(audiosamplerate)"))

    try:
        hz = float(samplerate)
    except (TypeError, ValueError):
        return ""

    khz = hz / 1000.0

    if khz.is_integer():
        return f"{int(khz)} kHz"

    return f"{khz:.1f} kHz"


def get_AudioChannelsInputVar():
    try:
        ch = int(_info("VideoPlayer.AudioChannels"))
        return _CHANNELS_INPUT_MAP.get(ch, xbmc.getLocalizedString(13205))
    except (ValueError, TypeError):
        return xbmc.getLocalizedString(13205)


def get_AudioNameVar():
    code = _info("VideoPlayer.AudioLanguage")

    if not code:
        return ""

    code = str(code).lower().strip()

    return _LANGUAGE_MAP.get(code, "")


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

def get_CpuUsageVar():
    raw = _info("System.CpuUsage")

    if not raw:
        return ""

    matches = re.findall(r"#\d+:\s*([\d.]+)%", raw)

    if not matches:
        return raw

    values = []

    for val in matches:
        try:
            num = int(float(val))
            values.append(f"{num:02d}")
        except ValueError:
            continue

    return " | ".join(values)
    
    
def set_ui_position(window):
    ui_style = xbmcgui.Window(10000).getProperty("TinyPPI.UIStyle")

    if ui_style == "1":
        left, top = 40, 575
    else:
        left, top = 0, 615

    window.getControl(9000).setPosition(left, top)


# ---------------------------------------------------------------------------
# Main update call – use this in your WindowXML class
# ---------------------------------------------------------------------------

def update_properties(window):
    set_ui_position(window)
    
    window.setProperty("VideoDecoderVar",       get_VideoDecoderVar())
    window.setProperty("VideoPixelFormatVar",   get_VideoPixelFormatVar())
    window.setProperty("DisplayModeVar",        get_DisplayModeVar())
    window.setProperty("VideoResolutionVar",    get_VideoResolutionVar())
    window.setProperty("VideoBitrateMBVar",     get_VideoBitrateMBVar())
    window.setProperty("AudioBitrateMBVar",     get_AudioBitrateMBVar())
    window.setProperty("HdrTypeVar",            get_HdrTypeVar())
    window.setProperty("HdrDetailVar",          get_HdrDetailVar())
    window.setProperty("ModeVar",               get_ModeVar())
    window.setProperty("ModeConvertVar",        get_ModeConvertVar())
    window.setProperty("GamutVar",              get_GamutVar())
    window.setProperty("VideoCodecVar",         get_VideoCodecVar())
    window.setProperty("HdrCheckVar",           get_HdrCheckVar())
    window.setProperty("AudioCodecVar",         get_AudioCodecVar())
    window.setProperty("AudioCodecSpatialVar",  get_AudioCodecSpatialVar())
    window.setProperty("AudioChannelsVar",      get_AudioChannelsVar())
    window.setProperty("AudioSampleRateVar",    get_AudioSampleRateVar())
    window.setProperty("AudioChannelsInputVar", get_AudioChannelsInputVar())
    window.setProperty("AudioNameVar",          get_AudioNameVar())
    window.setProperty("SubtitleCodecVar",      get_SubtitleCodecVar())
    window.setProperty("SubtitleNameVar",       get_SubtitleNameVar())
    window.setProperty("CpuUsageVar",           get_CpuUsageVar())
    window.setProperty("CurrentSkin",           xbmc.getSkinDir())
