"""Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval.
"""

import re

import xbmc
import xbmcgui
from dvinfo import (
    get_audio_bit_depth,
    get_audio_sample_rate,
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
    get_hdr_format,
    get_l5_offsets,
    get_l6_rpu_max_cll_fall,
    get_l6_rpu_mdl,
    get_output_mode,
    get_structure,
    is_fetch_label,
    is_status_label,
)
from helpers import format_fps, fps_display_texts, normalize_fps
from maps import (
    AUDIO_BIT_DEPTH_MAP,
    AUDIO_CODEC_MAP,
    AUDIO_PCM_DEPTH_CODECS,
    CHANNELS_INPUT_MAP,
    CHANNELS_MAP,
    LANGUAGE_MAP,
    LANGUAGE_MAP_SHORT,
    SUBTITLE_CODEC_MAP,
    VIDEO_CODEC_MAP,
)
from utils import clean, cond, info, set_window_properties

_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _first_float(raw: str) -> float | None:
    """Return the first decimal number found in *raw*, or None."""
    match = _DECIMAL_RE.search(raw)
    if not match:
        return None

    try:
        return float(match.group(0).replace(",", "."))
    except (TypeError, ValueError):
        return None


# --- Video properties ------------------------------------------------------

def get_VideoDecoderVar() -> str:
    """Return 'HW' or 'SW' based on the active video decoder type."""
    return "HW" if cond("Player.Process(videohwdecoder)") else "SW"


def get_VideoDecoderLongVar() -> str:
    """Return 'Hardware' or 'Software' for the Decode mode row."""
    return "Hardware" if cond("Player.Process(videohwdecoder)") else "Software"


def get_VideoPixelFormatVar() -> str:
    """Parse ``amlogic.pixformat`` into e.g. ``10-bit (YUV 4:2:0)`` / ``8-bit, RGB``."""
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
    """Parse ``amlogic.displaymode`` into a compact string like ``1080p 23.976Hz``."""
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


def get_VideoCodecVar() -> str:
    """Return the mapped display name for the current video codec."""
    codec = info("VideoPlayer.VideoCodec").lower().strip()
    if not codec:
        return ""
    return VIDEO_CODEC_MAP.get(codec, codec.upper())


def get_VideoDecoderNameVar() -> str:
    """Return the vendor prefix for the active decoder (``AML-`` / ``FF-``).

    ``Player.Process(videodecoder)`` reports e.g. ``am-h264`` / ``ff-hevc``; the
    skin concatenates this prefix with ``VideoCodecVar`` (``AML-H.265``).
    Unknown values are passed through upper-cased.
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

    Uses hdrprobe's detected depth (see dvinfo.py).  The ``Fetching...`` label
    passes through while detection runs; when the depth is unknown, falls back
    to ``10-bit`` for HDR and ``8-bit`` for SDR instead of the ``N/A`` label.
    """
    value = get_bit_depth()
    if is_fetch_label(value):
        return value
    if not value or is_status_label(value):
        return "10-bit" if get_hdr_format() else "8-bit"
    return f"{value}-bit"


# --- HDR / Dolby Vision properties -----------------------------------------

# Cached (pixformat, result) for get_DoviTunnelVar: the sysfs DV mode only
# changes on a VS10 switch, which also changes the pixel format, so keying on
# pixformat avoids re-reading sysfs every cycle.
_dovi_tunnel_cache: tuple[str, str] | None = None


def get_DoviTunnelVar() -> str:
    """Return ``"DV Tunnel"`` when sysfs DV mode is 1 and the output is 8-bit,
    else ``""``.  Cached per Amlogic pixel format."""
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
            # Don't cache a failure; retry next cycle.
            return ""

    _dovi_tunnel_cache = (pixformat, result)
    return result


def _with_unit(value: str, unit: str) -> str:
    """Append ``unit`` to a metadata value, but not to status labels.

    The ``0 | 0`` placeholder still gets the unit (``0 | 0 cd/m²``); the
    ``Fetching...`` label is left unchanged.
    """
    if not value or is_status_label(value):
        return value
    if not unit:
        return value
    return f"{value} {unit}"


# --- Amlogic EOFT / gamut --------------------------------------------------

def get_ModeVar() -> str:
    """Return the first token of ``amlogic.eoft_gamut`` (the mode field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[0] if parts else ""


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


def _output_mode_from_hw() -> str:
    """Classify the ``amlogic.eoft_gamut`` mode token into an output-mode label
    (``SDR`` / ``HDR10`` / ``HLG`` / ``HDR10+`` / ``Dolby Vision``), or ``''``.

    Reads the display's actual output signalling, so it works as the fallback
    when hdrprobe detection could not run.
    """
    mode = get_ModeVar().upper()
    if not mode:
        return ""
    if "DV" in mode or "DOLBY" in mode:
        return "Dolby Vision"
    if "HDR10+" in mode or "HDR10PLUS" in mode or "PLUS" in mode:
        return "HDR10+"
    if "HLG" in mode:
        return "HLG"
    if "HDR" in mode:
        return "HDR10"
    if "SDR" in mode:
        return "SDR"
    return ""


def _media_source_name(output_mode: str) -> str:
    """Collapse an output-mode string to the bare format name for the Media
    source row (dropping the DV / HDR10+ profile suffix).

    Status labels and unrecognised values pass through unchanged.
    """
    if not output_mode or is_status_label(output_mode):
        return output_mode

    low = output_mode.lower()
    if "dolby" in low:
        return "Dolby Vision"
    if "hdr10+" in low:
        return "HDR10+"
    if "hdr10" in low:
        return "HDR10"
    if "hlg" in low:
        return "HLG"
    if "sdr" in low:
        return "SDR"
    return output_mode


# --- Vdec bitrate (Amlogic kernel sysfs) -----------------------------------

def get_VdecBitrateVar() -> tuple[str, str]:
    """Read the hardware decoder bitrate from sysfs as a ``(value, unit)`` tuple,
    e.g. ``('23.45', 'Mb/s')``.  Returns ``('', '')`` when unavailable."""
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


# --- Audio properties ------------------------------------------------------

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


# Kodi audio codec name prefix -> audioprobe codec family (see audioprobe.py).
# ``dts`` covers dts / dtshd_ma / dtshd_ma_x / dts_96_24 / ...; ``dca`` is
# Kodi's alternate name for DTS core.
_AUDIO_PROBE_FAMILY_PREFIXES = (
    ("truehd", "truehd"),
    ("dts", "dts"),
    ("dca", "dts"),
    ("mlp", "mlp"),
    ("flac", "flac"),
)


def _audio_probe_family(codec: str) -> str:
    """Map a Kodi audio codec name to its audioprobe codec family, or ''."""
    for prefix, family in _AUDIO_PROBE_FAMILY_PREFIXES:
        if codec.startswith(prefix):
            return family
    return ""


def get_AudioBitDepthVar() -> str:
    """Return the source audio bit depth for display, e.g. ``24-bit``.

    The depth is read from the source bitstream itself (audioprobe.py): DTS
    carries it in the core header, MLP in the major sync, FLAC in STREAMINFO;
    TrueHD encodes none, so a detected stream reports the universal 24.

    While detection still runs (or found nothing), known bitstream codecs
    fall back to AUDIO_BIT_DEPTH_MAP, because Kodi's own
    ``Player.Process(audiobitspersample)`` reports the sink format — during
    passthrough the packed IEC 61937 byte stream, always ``8``.  Kodi's value
    is only used for lossless/uncompressed codecs Kodi decodes itself
    (AUDIO_PCM_DEPTH_CODECS).  Every other codec — the lossy formats — has no
    PCM bit depth at all and returns ``''``, so the skin shows only the
    sample rate.
    """
    codec = info("VideoPlayer.AudioCodec").lower().strip()

    probed = get_audio_bit_depth(_audio_probe_family(codec))
    if probed:
        return f"{probed}-bit"

    depth = AUDIO_BIT_DEPTH_MAP.get(codec)
    if depth:
        return f"{depth}-bit"

    if codec in AUDIO_PCM_DEPTH_CODECS and not cond("Player.Passthrough"):
        bits = clean(info("Player.Process(audiobitspersample)"))
        if bits:
            return f"{bits}-bit"

    return ""


def get_AudioSampleRateVar() -> str:
    """Return the source audio sample rate for display, e.g. ``96 kHz``.

    A rate probed from the source bitstream takes precedence; the scanner
    only emits one for the DTS family, where Kodi reports the compatibility
    core's rate (48 kHz) even when the extension carries 96/192 kHz (DTS
    96/24, high-rate DTS-HD).  Everywhere else Kodi's own value already is
    the source rate.
    """
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    samplerate = get_audio_sample_rate(_audio_probe_family(codec))
    if not samplerate:
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


# --- Subtitle properties ---------------------------------------------------

def get_SubtitleNameVar() -> str:
    """Return the native language name for the active subtitle language code."""
    code = info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return LANGUAGE_MAP.get(code, "") if code else ""


def get_SubtitleNameShortVar() -> str:
    """Return the native short language name for the active subtitle language code."""
    code = info("VideoPlayer.SubtitlesLanguage").lower().strip()
    return LANGUAGE_MAP_SHORT.get(code, "") if code else ""


def get_SubtitleCodecVar() -> str:
    """Return the mapped display name for the current subtitle codec."""
    codec = info("VideoPlayer.SubtitleCodec").lower().strip()
    return SUBTITLE_CODEC_MAP.get(codec, codec.upper()) if codec else ""


# --- System properties -----------------------------------------------------

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
    """Parse ``System.CpuUsage`` into a pipe-separated per-core string,
    e.g. ``'12 | 08 | 15 | 10'``."""
    raw = info("System.CpuUsage")
    if not raw:
        return ""

    loads = _cpu_core_loads(raw)
    if not loads:
        return raw

    return " | ".join(f"{int(v):02d}" for v in loads)


def get_CpuTopUsageVar() -> str:
    """Return the average CPU usage across all cores, e.g. ``'34%'``, derived
    from ``System.CpuUsage``.  Empty when no per-core values are parseable."""
    loads = _cpu_core_loads(info("System.CpuUsage"))
    if not loads:
        return ""

    return f"{sum(loads) / len(loads):.0f}%"


def get_CpuTemperatureProgressVar() -> float:
    """Map System.CPUTemperature to a 0-100 progress value
    (Celsius 0-110 C, Fahrenheit 32-230 F)."""
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
    """Read a queue level from Kodi.  A full queue may read as 99%, so 99 or
    higher is treated as 100%."""
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
    """Publish the hdrprobe-detected HDR type as ``TinyPPI.HdrType`` on the Home
    window, for the overlay and mode-select dialog to branch on.

    HDR10+ is published as ``hdr10plus`` because Kodi's boolean parser treats
    ``+`` as AND; it still contains ``hdr10`` so ``String.Contains`` branches match.
    """
    hdr_type = get_hdr_format()
    if hdr_type == "hdr10+":
        hdr_type = "hdr10plus"
    (home or xbmcgui.Window(10000)).setProperty("TinyPPI.HdrType", hdr_type)


def _set_progress(window, values: tuple[tuple[int, float], ...]) -> None:
    """Publish a batch of progress-control percentages."""
    for control_id, value in values:
        window.getControl(control_id).setPercent(value)


def update_properties(window) -> None:
    """Compute all player properties and publish them to ``window``.

    Call from ``onInit()`` and from the polling loop.
    """

    publish_hdr_type()

    unit = _metadata_unit()
    video_queue = get_queue_level("Player.Process(videoqueuelevel)")
    video_queue_data = get_queue_level("Player.Process(videoqueuedatalevel)")
    audio_queue = get_queue_level("Player.Process(audioqueuelevel)")
    audio_queue_data = get_queue_level("Player.Process(audioqueuedatalevel)")
    bitrate_value, bitrate_unit = get_VdecBitrateVar()
    fps_info_text, fps_out_text = fps_display_texts()

    # Output-mode line from hdrprobe; fall back to a plain label from the
    # Amlogic hardware mode when it would show N/A (``Fetching...`` is kept).
    output_mode = get_output_mode()
    # Pending flag: the skin uses it to suppress the conversion-arrow suffix
    # while only the ``Fetching...`` placeholder should show.
    output_mode_pending = is_fetch_label(output_mode)
    if is_status_label(output_mode) and not is_fetch_label(output_mode):
        output_mode = _output_mode_from_hw() or output_mode

    l5_offsets = get_l5_offsets()
    l5_offsets_icon_visible = (
        "true"
        if l5_offsets and not is_status_label(l5_offsets)
        else "false"
    )

    l6_rpu_mdl          = _with_unit(get_l6_rpu_mdl(), unit)
    l6_rpu_max_cll_fall = _with_unit(get_l6_rpu_max_cll_fall(), unit)
    hdr10_mdl           = _with_unit(get_hdr10_mdl(), unit)
    hdr10_max_cll_fall  = _with_unit(get_hdr10_max_cll_fall(), unit)

    set_window_properties(
        window,
        (
            ("VideoDecoderVar", get_VideoDecoderVar()),
            ("VideoDecoderLongVar", get_VideoDecoderLongVar()),
            ("VideoPixelFormatVar", get_VideoPixelFormatVar()),
            ("DisplayModeVar", get_DisplayModeVar()),
            ("VideoResolutionVar", get_VideoResolutionVar()),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoCodecVar", get_VideoCodecVar()),
            ("VideoDecoderNameVar", get_VideoDecoderNameVar()),
            ("VideoBitDepthVar", get_VideoBitDepthVar()),
            ("DoviProfileVar", output_mode),
            ("DoviProfileAltVar", output_mode.replace("Dolby Vision Profile", "DV Profile")),
            ("MediaSourceVar", _media_source_name(output_mode)),
            ("DoviProfilePending", "true" if output_mode_pending else "false"),
            ("DoviTunnelVar", get_DoviTunnelVar()),
            ("DoviCmVersionVar", get_cm_version()),
            ("DoviStructureVar", get_structure()),
            ("DoviLevel5OffsetsVar", l5_offsets),
            ("DoviLevel5OffsetsIconVisible", l5_offsets_icon_visible),
            ("DoviLevel6RpuMdlVar", l6_rpu_mdl),
            ("DoviLevel6RpuMaxCllFallVar", l6_rpu_max_cll_fall),
            ("Hdr10MdlVar", hdr10_mdl),
            ("Hdr10MaxCllFallVar", hdr10_max_cll_fall),
            ("DoviVersionVar", get_dv_version()),
            ("DoviProfileNumberVar", get_dv_profile()),
            ("DoviRpuPresentVar", get_dv_rpu_present()),
            ("DoviBlPresentVar", get_dv_bl_present()),
            ("DoviElPresentVar", get_dv_el_present()),
            ("DoviElTypeVar", get_dv_el_type()),
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
            ("AudioBitDepthVar", get_AudioBitDepthVar()),
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
