"""Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval.
"""

import re

import xbmc
import xbmcaddon
import xbmcgui
from core.helpers import format_fps, fps_display_texts, normalize_fps
from core.maps import (
    AUDIO_BIT_DEPTH_MAP,
    AUDIO_CODEC_MAP,
    AUDIO_PCM_DEPTH_CODECS,
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
from core.utils import (
    clean,
    coded_frame,
    cond,
    info,
    parse_offsets,
    set_window_properties,
)
from info.cropdetect import (
    live_detection_enabled,
    live_detection_pending,
    live_measurement_available,
    resolve_l5_offsets,
)
from info.imax import is_imax_scene
from info.dvinfo import (
    L5_EMPTY,
    L5_PENDING_FRAMES,
    L5_PENDING_STEP,
    get_active_audio_bit_depth,
    get_active_audio_sample_rate,
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
    l5_pending_frame,
)

_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Channel graphics ship pre-scaled to the exact box the skin draws them in
# (see script-tinyppi-main.xml), so Kodi never resamples them: SDR and
# HDR10 / HDR10+ / HLG share the 495x298 box, DV uses the smaller 400x241 panel.
_CHANNEL_DIR_DEFAULT = "channels/495x298"
_CHANNEL_DIR_DV      = "channels/400x241"


def _is_dv() -> bool:
    """Mirror the skin's DV branch, which draws the smaller channel panel."""
    return "dolby" in xbmcgui.Window(10000).getProperty("TinyPPI.HdrType").lower()


def _channel_dir() -> str:
    """Return the folder holding the display-sized graphics for the current
    output type: the DV panel is smaller than the SDR / HDR box."""
    return _CHANNEL_DIR_DV if _is_dv() else _CHANNEL_DIR_DEFAULT


def _channels_shown() -> bool:
    """Return whether the channel graphics are switched on."""
    return xbmcgui.Window(10000).getProperty("TinyPPI.ShowChannelIcon") == "1"



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


# Aspect ratios a computed picture is snapped to when it lands close enough.
# A measured bar is quantised to one grab row — 12 coded lines at 4K, which
# moves a scope ratio by about 0.04 — so without snapping the row would read
# 2.43 for a 2.39 film.  Anything further out than the tolerance is shown as
# calculated rather than forced onto a familiar number.
#
# Note the limit this cannot cross: 2.35 and 2.39 are themselves only 0.04
# apart, so a *measured* bar cannot tell them apart and lands on whichever is
# nearer.  It does not matter in practice, because a DV title carries those
# offsets in its RPU and the exact value is preferred over the measurement;
# only a ratio the RPU does not describe is ever measured.
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


def get_AspectRatioVar(l5_offsets: str) -> str:
    """Return the display aspect ratio of the picture inside the black bars.

    Kodi's ``videodar`` describes the coded frame, so an IMAX title sits on 1.78
    for its whole runtime even while the picture on screen is 2.39.  The bars
    say where the picture actually is — from the RPU where it carries them, from
    the live measurement otherwise — and the coded ratio scaled by them gives
    the ratio being watched.

    Kodi's own value is returned untouched whenever live detection is switched
    off, and whenever the bars are unknown or all zero, so a film without
    letterboxing reads exactly as it did before.
    """
    raw = clean(info("Player.Process(videodar)"))

    # The ratio belongs to the same feature as the offsets it is derived from,
    # so one switch governs both.  Without this the RPU's own offsets would
    # still move the ratio off Kodi's value with the option turned off.
    if not live_detection_enabled():
        return raw

    bars = parse_offsets(l5_offsets)
    coded = coded_frame()
    coded_dar = _first_float(raw)
    if bars is None or coded is None or coded_dar is None or not any(bars):
        return raw

    left, right, top, bottom = bars
    coded_w, coded_h = coded
    picture_w = coded_w - left - right
    picture_h = coded_h - top - bottom
    if picture_w <= 0 or picture_h <= 0:
        return raw

    # Scaling the coded ratio rather than dividing the picture's own dimensions
    # carries any non-square pixel aspect through unchanged.
    ratio = coded_dar * (picture_w / coded_w) * (coded_h / picture_h)
    return _snapped_ar(ratio)


def get_ImaxVar(l5_offsets: str) -> str:
    """Return ``IMAX`` while the picture is opened up past its base framing.

    Requires a settled measurement: without one the offsets are zeros because
    nothing looked, not because the picture fills the frame, and a known IMAX
    title would then wear the badge for its whole runtime.  See info.imax for
    how an IMAX scene is told from an ordinary one.
    """
    if not live_measurement_available():
        return ""
    return "IMAX" if is_imax_scene(l5_offsets) else ""


def get_VideoBitrateMBVar() -> str:
    """Convert the video bitrate from kb/s to Mb/s and return a display string."""
    bitrate = clean(info("VideoPlayer.VideoBitrate"))
    try:
        mbit = float(bitrate) / 1000.0
    except (TypeError, ValueError):
        return ""

    value = f"{mbit:.1f}".rstrip("0").rstrip(".")
    return f"{value} Mb/s"


def get_VideoLiveBitrateVar() -> str:
    """Return video live bitrate with dot instead of comma."""
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


def _output_mode_from_videoplayer() -> str:
    """Classify Kodi's ``VideoPlayer.HDRType`` InfoLabel into an output-mode
    label (``SDR`` / ``HDR10`` / ``HLG`` / ``HDR10+`` / ``Dolby Vision``).

    Reads Kodi's own source-side HDR detection, so it works as the fallback when
    hdrprobe detection could not run.  An empty ``VideoPlayer.HDRType`` means no
    HDR signalling, i.e. ``SDR``.
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


def _channel_layout() -> str:
    """Return the speaker layout for the current track, e.g. ``5.1.2``.

    Empty when the channel count has no graphic (4, 9 and 10 channels).  Atmos
    and DTS:X streams take the height-channel variant: Kodi reports no height
    count, so a 6- or 8-channel track is read as 5.1.2 / 7.1.2.
    """
    try:
        ch = int(info("VideoPlayer.AudioChannels"))
    except (ValueError, TypeError):
        return ""

    layout = ""
    if info("VideoPlayer.AudioCodec") in HEIGHT_CHANNEL_CODECS:
        layout = CHANNELS_ICON_HEIGHT_MAP.get(ch, "")
    return layout or CHANNELS_ICON_MAP.get(ch, "")


def get_ChannelLayerVar() -> str:
    """Return the speaker-layout backdrop drawn behind the active channels,
    sized for the current output type's panel."""
    return f"{_channel_dir()}/layer.png" if _channels_shown() else ""


def get_ChannelIconVar() -> str:
    """Return the speaker-layout graphic for the current channel count, sized
    for the current output type's panel.  Empty when the count has no graphic,
    which also hides the control in the skin.
    """
    if not _channels_shown():
        return ""

    layout = _channel_layout()
    return f"{_channel_dir()}/{layout}.png" if layout else ""


def get_AudioBitDepthVar() -> str:
    """Return the source audio bit depth for display, e.g. ``24-bit``.

    The depth is read from the source bitstream itself by the audioprobe binary,
    for the currently active audio track (see dvinfo.py): DTS carries it in the
    core header, MLP in the major sync, FLAC in STREAMINFO; TrueHD encodes none,
    so a detected stream reports the universal 24.

    While detection still runs (or found nothing), known bitstream codecs
    fall back to AUDIO_BIT_DEPTH_MAP, because Kodi's own
    ``Player.Process(audiobitspersample)`` reports the sink format — during
    passthrough the packed IEC 61937 byte stream, always ``8``.  Kodi's value
    is only used for lossless/uncompressed codecs Kodi decodes itself
    (AUDIO_PCM_DEPTH_CODECS).  Every other codec — the lossy formats — has no
    PCM bit depth at all and returns ``''``, so the skin shows only the
    sample rate.
    """
    probed = get_active_audio_bit_depth()
    if probed:
        return f"{probed}-bit"

    codec = info("VideoPlayer.AudioCodec").lower().strip()
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

    The rate probed from the source bitstream for the active audio track
    (audioprobe binary) takes precedence: Kodi reports the DTS compatibility
    core's rate (48 kHz) even when the extension carries 96/192 kHz (DTS 96/24,
    high-rate DTS-HD).  Everywhere else the probed rate already equals Kodi's
    own value, and Kodi's is the fallback while detection runs.
    """
    samplerate = get_active_audio_sample_rate()
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


def _metadata_unit() -> str:
    """Return the configured L6 metadata unit, including Kodi color markup."""
    unit_color = info("Window(10000).Property(TinyPPI.UnitColor)")
    unit_label = info("Window(10000).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return ""
    if unit_color:
        return f"[COLOR={unit_color}]{unit_label}[/COLOR]"
    return unit_label


def _channel_setting_for(hdr_type: str) -> str:
    """Return the channel setting that governs an ``HdrType`` token.

    Mirrors the branches the skin draws: DV has its own panel, HDR10 / HDR10+ /
    HLG share one layout, and an empty type means SDR.
    """
    low = hdr_type.lower()
    if "dolby" in low:
        return "channels_dv"
    if not low:
        return "channels_sdr"
    return "channels_hdr"


def publish_channel_visibility(home=None) -> None:
    """Publish ``TinyPPI.ShowChannelIcon`` for the current output type.

    Re-read every poll rather than once at open: the HDR type is detected
    asynchronously, so a stream that turns out to be DV must switch to the DV
    setting while the overlay is up.  A fresh ``Addon()`` avoids its cached
    settings, so toggling one applies without reopening.
    """
    home = home or xbmcgui.Window(10000)
    setting = _channel_setting_for(home.getProperty("TinyPPI.HdrType"))
    enabled = xbmcaddon.Addon().getSetting(setting) == "true"
    home.setProperty("TinyPPI.ShowChannelIcon", "1" if enabled else "0")


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


_L5_PROPERTY = "DoviLevel5OffsetsVar"


def tick_l5_placeholder(window) -> None:
    """Advance the L5 placeholder animation, if that is what is on screen.

    A no-op for every real value, so this stays safe to call blindly between
    full updates -- only a frame of the animation is ever overwritten.
    """
    if window.getProperty(_L5_PROPERTY) in L5_PENDING_FRAMES:
        window.setProperty(_L5_PROPERTY, l5_pending_frame())


def wait_poll(monitor, window, seconds: float = 1.0) -> bool:
    """Wait out one polling interval, animating the L5 placeholder meanwhile.

    Returns True when Kodi asked to abort.  The placeholder needs a faster beat
    than the poll to read as an animation; every other property is left on the
    original cadence, since recomputing them all that often would cost far more
    than the one string this touches.
    """
    remaining = seconds
    while remaining > 0:
        step = min(L5_PENDING_STEP, remaining)
        if monitor.waitForAbort(step):
            return True
        remaining -= step
        tick_l5_placeholder(window)
    return False


def update_properties(window) -> None:
    """Compute all player properties and publish them to ``window``.

    Call from ``onInit()`` and from the polling loop.
    """

    publish_hdr_type()
    # Depends on the type just published, and gates the channel graphics below.
    publish_channel_visibility()

    unit = _metadata_unit()
    fps_info_text, fps_out_text = fps_display_texts(
        clean(info("Player.Process(videofps)"))
    )

    # Output-mode line from hdrprobe; fall back to a plain label from Kodi's
    # ``VideoPlayer.HDRType`` when it would show N/A (``Fetching...`` is kept).
    output_mode = get_output_mode()
    # Pending flag: the skin uses it to suppress the conversion-arrow suffix
    # while only the ``Fetching...`` placeholder should show.
    output_mode_pending = is_fetch_label(output_mode)
    if is_status_label(output_mode) and not is_fetch_label(output_mode):
        output_mode = _output_mode_from_videoplayer() or output_mode

    # The RPU offsets are exact, so they stand for as long as the picture still
    # matches them.  Black bars measured off the running picture take over only
    # once it stops matching — a title that changes aspect ratio mid-film — and
    # hand back as soon as the film returns to its base framing.
    l5_offsets_static = get_l5_offsets()
    l5_offsets = resolve_l5_offsets(l5_offsets_static)
    l5_offsets_measured = l5_offsets != l5_offsets_static
    # Only the RPU's "no L5 here" placeholder is stood in for; a settled
    # measurement of zero is an answer, not a wait, and keeps its zeros.
    if l5_offsets == L5_EMPTY and live_detection_pending():
        l5_offsets = l5_pending_frame()
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
            ("AspectRatioVar", get_AspectRatioVar(l5_offsets)),
            ("ImaxVar", get_ImaxVar(l5_offsets)),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoLiveBitrateVar", get_VideoLiveBitrateVar()),
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
            ("DoviLevel5OffsetsLive", "true" if l5_offsets_measured else "false"),
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

    _set_progress(
        window,
        (
            (9100, get_CpuTemperatureProgressVar()),
        ),
    )
