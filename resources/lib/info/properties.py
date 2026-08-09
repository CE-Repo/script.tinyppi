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
    cond,
    first_float,
    info,
    parse_offsets,
    picture_aspect_ratio,
    set_window_properties,
)
from info.cropdetect import (
    live_detection_enabled,
    live_detection_pending,
    live_detection_settling,
    live_measurement_available,
    resolve_l5_offsets,
)
from info.imax import is_enhanced_title, is_imax_scene
from info.dvinfo import (
    L5_EMPTY,
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
# borderprobe measures the coded frame at full resolution, but a bar edge that
# falls inside a coding block can still be read a pixel or two either way —
# enough to nudge a 2.39 film to 2.40 without snapping.  Anything further out
# than the tolerance is shown as calculated rather than forced onto a familiar
# number.
#
# Note the limit this cannot cross: 2.35 and 2.39 are themselves only 0.04
# apart, so a measured bar cannot tell them apart and lands on whichever is
# nearer.  Since the live measurement is preferred over the RPU whenever one
# exists, that applies to DV titles too — their RPU would have named the ratio
# exactly, and a 2.35 title can read as 2.39 while detection is on.
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


def get_AspectRatioVar(
    l5_offsets: str, is_dv: bool | None = None, live_available: bool = False
) -> str:
    """Return the display aspect ratio of the picture inside the black bars.

    Kodi's ``videodar`` describes the coded frame, so an IMAX title sits on 1.78
    for its whole runtime even while the picture on screen is 2.39; scaling the
    coded ratio by the bars (RPU or live measurement, whichever ``l5_offsets``
    carries) gives the ratio actually being watched.  Falls back to Kodi's own
    value when the bars are unknown, or when they're a genuine ``0 | 0 | 0 | 0``
    that isn't backed by anything: outside Dolby Vision, with no live
    measurement landed yet, ``l5_offsets`` is only ever dvinfo's placeholder,
    never a confirmed reading, so it carries no more information than Kodi's
    own ratio.  A confirmed ``0 | 0 | 0 | 0`` is computed anyway, since there it
    is a real answer (no crop) rather than an unset placeholder -- true on a
    Dolby Vision stream (the RPU itself is the confirmation, live measurement
    or not) and on any format once a live measurement has actually landed.
    ``is_dv`` and ``live_available`` let a caller pass in already-read state;
    left out, ``is_dv`` is read here and ``live_available`` defaults to False.
    """
    raw = clean(info("Player.Process(videodar)"))

    bars = parse_offsets(l5_offsets)
    if bars is None:
        return raw

    if not any(bars) and not live_available:
        if is_dv is None:
            is_dv = _is_dv()
        if not is_dv:
            return raw

    ratio = picture_aspect_ratio(l5_offsets)
    return _snapped_ar(ratio) if ratio is not None else raw


def get_ImaxVar(l5_offsets: str, available: bool | None = None) -> str:
    """Return ``IMAX`` while the picture is opened up past its base framing.

    Requires a settled measurement: without one the offsets are zeros because
    nothing looked, not because the picture fills the frame, which would wear
    the badge for the whole runtime.  See info.imax for scene detection.
    ``available`` lets a caller pass in an already-established measurement
    state; left out, it is looked up here.
    """
    if available is None:
        available = live_measurement_available()
    if not available or not is_imax_scene(l5_offsets):
        return ""
    return "IMAX Enhanced" if is_enhanced_title() else "IMAX"


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

    Prefers the depth audioprobe read from the source bitstream itself for the
    active track (see dvinfo.py).  While detection runs or finds nothing, known
    bitstream codecs fall back to AUDIO_BIT_DEPTH_MAP, since Kodi's own
    ``audiobitspersample`` reports the sink format (always ``8`` during
    passthrough).  Kodi's value is used only for codecs it decodes itself
    (AUDIO_PCM_DEPTH_CODECS); lossy codecs have no PCM bit depth and return
    ``''``, so the skin shows only the sample rate.
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

    Prefers the rate audioprobe read from the source bitstream: Kodi reports
    the DTS compatibility core's rate (48 kHz) even when the extension carries
    96/192 kHz.  Falls back to Kodi's own value while detection runs.
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


# The L5-derived set as last written to the overlay window, so wait_poll can
# tell a tick that carries news from one that does not.  Kept in step by
# update_properties, which always writes the set and always records it.
_l5_published: tuple[tuple[str, str], ...] | None = None


def _l5_derived() -> tuple[tuple[str, str], ...]:
    """Return every property that follows from the L5 offsets.

    Kept together because the offsets, aspect ratio and IMAX badge are three
    readings of one measurement, and publishing them separately would let the
    badge disagree with the numbers it's drawn from.  Split out of
    update_properties so wait_poll can refresh just this set between full
    updates.  Cheap enough to call several times a second (a cache read plus
    whatever the sampler last published, no frame decoding); ``enabled`` and
    ``available`` are read once here and passed down rather than re-read by
    every caller below.
    """
    enabled = live_detection_enabled()

    static = get_l5_offsets()
    static_bars = parse_offsets(static)
    # A genuine RPU reading -- anything past all-zero -- is authoritative and
    # ends the question; live measurement exists only to answer it when the
    # RPU itself has nothing (a bare "0 | 0 | 0 | 0", or detection still
    # fetching, which parses to no bars at all).
    has_rpu_area = static_bars is not None and any(static_bars)

    if enabled and not has_rpu_area:
        offsets = resolve_l5_offsets(static)
        # Says the displayed value came from the picture rather than the RPU —
        # not that the two differ, which they usually do not on a fixed-framing
        # title.
        available = live_measurement_available()
        # Show the placeholder while the value on screen is not yet the one
        # that will stand: either nothing is known at all (no RPU offsets,
        # nothing measured), or the measurement that outranks the RPU is still
        # on its way and within its grace period.  A settled measurement of
        # zero is an answer, not a wait, and keeps its zeros.
        if (offsets == L5_EMPTY and live_detection_pending()) or live_detection_settling():
            offsets = l5_pending_frame()
    else:
        # The RPU already has the answer (or the option is off, in which case
        # it's the only answer there is) -- no live measurement is run or shown.
        offsets = static
        available = False
    icon_visible = "true" if offsets and not is_status_label(offsets) else "false"

    return (
        ("AspectRatioVar", get_AspectRatioVar(offsets, live_available=available)),
        ("ImaxVar", get_ImaxVar(offsets, available)),
        ("DoviLevel5OffsetsVar", offsets),
        ("DoviLevel5OffsetsIconVisible", icon_visible),
        ("DoviLevel5OffsetsLive", "true" if available else "false"),
    )


def wait_poll(monitor, window, seconds: float = 1.0) -> bool:
    """Wait out one polling interval, keeping the L5 row current meanwhile.

    Returns True when Kodi asked to abort.

    The placeholder needs a faster beat than the poll to read as an animation,
    and a fresh measurement benefits from the same beat instead of sitting
    unseen for the rest of the second.  Only the L5-derived set is refreshed
    here — every other property stays on the original cadence — and only when
    it actually changed, so a film whose framing never moves triggers no writes
    (``update_properties`` always writes and records the set, so the comparison
    starts from what's really on the window).
    """
    global _l5_published

    remaining = seconds
    while remaining > 0:
        step = min(L5_PENDING_STEP, remaining)
        if monitor.waitForAbort(step):
            return True
        remaining -= step
        derived = _l5_derived()
        if derived != _l5_published:
            set_window_properties(window, derived)
            _l5_published = derived
    return False


def update_properties(window) -> None:
    """Compute all player properties and publish them to ``window``.

    Call from ``onInit()`` and from the polling loop.
    """
    global _l5_published

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

    # Black bars measured off the running picture are what gets shown once a
    # measurement has landed; the RPU's own offsets stand in until then, and
    # again whenever detection is off or has given up.  Computed by
    # _l5_derived() so the poll loop can refresh the same set between updates.

    l5_derived          = _l5_derived()
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
            *l5_derived,
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

    # Recorded after the write above, so wait_poll's comparison starts from what
    # is actually on the window.
    _l5_published = l5_derived

    _set_progress(
        window,
        (
            (9100, get_CpuTemperatureProgressVar()),
        ),
    )
