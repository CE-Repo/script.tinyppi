import re
import xbmc


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

    # Amlogic may insert spaces within the Hz value for 3-digit rates
    # (e.g. "1920x1080p 1 00hz" for 100 Hz, "1920x1080p 1 20hz" for 120 Hz).
    # Collapse all internal whitespace so the regex always sees a compact string.
    compact = re.sub(r"\s+", "", val)

    match = re.match(
        r"(\d+(?:x\d+)?)(p|i)(\d+(?:\.\d+)?)[Hh][Zz]",
        compact,
        re.IGNORECASE,
    )
    if not match:
        return val  # return original (with spacing) if format is unrecognised

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

    if "hdr10plus" in val:
        return "HDR10+"
    if "hdr10" in val:
        return "HDR10"
    if "dolby" in val or "dv" in val:
        return "Dolby Vision Profile"
    if "hlg" in val:
        return "HLG"

    return val
    
    
# --- Optional fallback for CoreELEC NO-branch (S905X4/S905X5) + Kodi 22 ---
# On some hardware/branch combos (notably Ugoos AM9 Pro / S905X5 on Piers nightly
# with jellyfin-kodi stream-mode playback), Kodi's `VideoPlayer.HdrDetail` infolabel
# returns an empty string during DV Profile 7 playback even though the kernel-side
# DV pipeline is fully active (verified via /sys/class/amdolby_vision/* and dmesg).
# This helper provides a kernel-state fallback that only confirms FEL when the
# Amlogic kernel actively logs `enable_fel 1` + `enable_mel 1` (which fire together
# for Profile 7 FEL). It does NOT try to distinguish Profile 7 MEL from Profile 8
# because both produce the same both-zero pattern on this branch.

_FEL_CACHE = {"ts": 0, "fel": None}


def _get_fel_from_dmesg():
    """Most-recent enable_fel/enable_mel state from kernel ring buffer.
    Returns True only if both signals are 1 (confirmed Profile 7 FEL).
    Cached 5 seconds to avoid hammering dmesg during the 1s poll loop."""
    import subprocess, time
    now = time.time()
    if now - _FEL_CACHE["ts"] < 5:
        return _FEL_CACHE["fel"]
    try:
        out = subprocess.run(
            ["dmesg"], capture_output=True, text=True, timeout=2
        ).stdout
        fel = mel = None
        for line in reversed(out.splitlines()):
            if "enable_fel " in line and fel is None:
                fel = line.split("enable_fel ")[-1].split()[0] == "1"
            if "enable_mel " in line and mel is None:
                mel = line.split("enable_mel ")[-1].split()[0] == "1"
            if fel is not None and mel is not None:
                break
        confirmed = fel is True and mel is True
        _FEL_CACHE.update({"ts": now, "fel": confirmed})
        return confirmed
    except Exception:
        return None


def get_HdrDetailVar():
    raw = _info("VideoPlayer.HdrDetail")

    # Primary path: Kodi populates HdrDetail (NG-branch / Kodi 21 / direct paths).
    # Format is typically "7FEL" / "7MEL" — color-code the suffix.
    if raw:
        lines = str(raw).splitlines()
        out = []

        for line in lines:
            line = line.strip()

            match = re.match(r"(\d+)(FEL|MEL)", line)
            if match:
                num, typ = match.groups()

                if typ == "FEL":
                    color = "palegreen"
                elif typ == "MEL":
                    color = "orange"
                else:
                    color = "white"

                out.append(f"{num} [COLOR {color}]{typ}[/COLOR]")
            else:
                out.append(line)

        return "\n".join(out)

    # Fallback for NO-branch / Kodi 22 / stream-mode playback where Kodi's
    # HdrDetail label stays empty. Only confirms FEL when kernel signals are
    # unambiguous; stays silent for MEL/Profile 8 since they cannot be reliably
    # distinguished from the kernel state on this branch.
    if "dolby" in str(_info("VideoPlayer.HdrType")).lower():
        if _get_fel_from_dmesg() is True:
            return "7 [COLOR palegreen]FEL[/COLOR]"

    return ""

def get_ModeVar():
    val = _info("Player.Process(amlogic.eoft_gamut)")

    if not val:
        return ""

    parts = str(val).split()

    return parts[0] if len(parts) > 0 else ""


def get_GamutVar():
    val = _info("Player.Process(amlogic.eoft_gamut)")

    if not val:
        return ""

    parts = str(val).split()

    return parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# Subtitle
# ---------------------------------------------------------------------------


def get_SubtitleVar():
    if _cond("String.IsEmpty(VideoPlayer.SubtitlesLanguage)"):
        return _info("VideoPlayer.SubtitlesLangEx")
    lang = _info("VideoPlayer.SubtitlesLanguage")
    return "[UPPERCASE]{}[/UPPERCASE]".format(lang)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

_AUDIO_CODEC_MAP = {
    "aac":              "AAC",
    "aac_latm":         "AAC",
    "aac_lc":           "AAC",
    "he_aac":           "AAC",
    "he_aac_v2":        "AAC",
    "aac_ssr":          "AAC",
    "aac_ltp":          "AAC",
    "ac3":              "Dolby Digital",
    "aif":              "AIFF",
    "aifc":             "AIFF",
    "aiff":             "AIFF",
    "alac":             "ALAC",
    "ape":              "APE",
    "avc":              "AVC",
    "cdda":             "CDDA",
    "dca":              "DTS",
    "dolbydigital":     "Dolby Digital",
    "dtshd":            "DTS-HD",
    "dtshd_ma":         "DTS-HD MA",
    "dtshd_hra":        "DTS-HD HRA",
    "dtshd_ma_x":       "DTS:X MA",
    "dtshd_ma_x_imax":  "DTS:X",
    "eac3":             "Dolby Digital Plus",
    "eac3_ddp_atmos":   "Dolby Digital Plus",
    "flac":             "FLAC",
    "mp1":              "MP1",
    "mp2":              "MP2",
    "mp3":              "MP3",
    "mp3float":         "MP3",
    "ogg":              "OGG",
    "opus":             "OPUS",
    "pcm":              "PCM",
    "pcm_bluray":       "PCM",
    "pcm_s16le":        "PCM",
    "pcm_s24le":        "PCM",
    "truehd":           "Dolby TrueHD",
    "truehd_atmos":     "Dolby TrueHD",
    "vorbis":           "Vorbis",
    "wav":              "WAV",
    "wavpack":          "WAVP",
    "wmapro":           "WMA-PRO",
    "wmav2":            "WMA",
}


_CHANNELS_MAP = {
    1: "1.0", 2: "2.0", 4: "4.0", 5: "5.0",
    6: "5.1", 7: "6.1", 8: "7.1", 10: "9.1",
}


_CHANNELS_INPUT_MAP = {
    1:  "Mono",
    2:  "FL, FR",
    3:  "FL, FR, LFE",
    4:  "FL, FR, BL, BR",
    5:  "FL, FR, LFE, BL, BR",
    6:  "FL, FR, FC, LFE, SL, SR",
    7:  "FL, FR, FC, LFE, BC, SL, SR",
    8:  "FL, FR, FC, LFE, BL, BR, SL, SR",
    9:  "FL, FR, FC, LFE, BL, BR, SL, SR, FWL",
    10: "FL, FR, FC, LFE, BL, BR, SL, SR, FWL, FWR",
}


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


# ---------------------------------------------------------------------------
# Main update call – use this in your WindowXML class
# ---------------------------------------------------------------------------

def update_properties(window):
    """Call this from onInit() and your update loop."""
    window.setProperty("VideoDecoderVar",       get_VideoDecoderVar())
    window.setProperty("VideoPixelFormatVar",   get_VideoPixelFormatVar())
    window.setProperty("DisplayModeVar",        get_DisplayModeVar())
    window.setProperty("VideoResolutionVar",    get_VideoResolutionVar())
    window.setProperty("VideoBitrateMBVar",     get_VideoBitrateMBVar())
    window.setProperty("AudioBitrateMBVar",     get_AudioBitrateMBVar())
    window.setProperty("HdrTypeVar",            get_HdrTypeVar())
    window.setProperty("HdrDetailVar",          get_HdrDetailVar())
    window.setProperty("ModeVar",               get_ModeVar())
    window.setProperty("GamutVar",              get_GamutVar())
    window.setProperty("AudioCodecVar",         get_AudioCodecVar())
    window.setProperty("AudioCodecSpatialVar",  get_AudioCodecSpatialVar())
    window.setProperty("AudioChannelsVar",      get_AudioChannelsVar())
    window.setProperty("AudioSampleRateVar",    get_AudioSampleRateVar())
    window.setProperty("AudioChannelsInputVar", get_AudioChannelsInputVar())
    window.setProperty("SubtitleVar",           get_SubtitleVar())
    window.setProperty("CpuUsageVar",           get_CpuUsageVar())
