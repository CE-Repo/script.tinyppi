"""Compute and publish Window properties for TinyPPI.

Call ``update_properties(window)`` once per polling interval.
"""

import re
import time

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
    l5_fallback_required,
    live_detection_enabled,
    live_detection_settling,
    live_measurement_available,
    resolve_l5_offsets,
    stop_live_detection,
)
from info.imax import is_enhanced_title, is_known_imax_title
from info.dvinfo import (
    get_active_audio_bit_depth,
    get_active_audio_sample_rate,
    get_bit_depth,
    get_dv_bl_present,
    get_dv_el_present,
    get_dv_rpu_present,
    get_dv_version,
    get_hdr_format,
    get_output_mode,
    get_structure,
    is_fetch_label,
    is_status_label,
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


# Aspect ratios calculated from Dolby Vision L5 offsets are snapped to a nearby
# standard ratio.  Anything further outside the tolerance is shown exactly as
# calculated.
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
    """Return the Dolby Vision picture ratio described by active offsets.

    Kodi's ``videodar`` describes the coded frame.  Scaling it by the current
    RPU L5 offsets, or by borderprobe's fallback measurement while L5 is
    explicitly all-zero, yields the picture ratio actually being watched and
    follows framing changes during playback.  When offsets are unavailable,
    Kodi's unmodified value is returned.
    """
    raw = clean(info("Player.Process(videodar)"))

    bars = parse_offsets(l5_offsets)
    if bars is None:
        return raw

    ratio = picture_aspect_ratio(l5_offsets)
    return _snapped_ar(ratio) if ratio is not None else raw


def get_ImaxVar() -> str:
    """Return ``IMAX Enhanced`` / ``IMAX`` for a film recognised as IMAX
    material, or ``''`` otherwise.

    Recognised from its filename (an ``IMAX`` / ``IMAX Enhanced`` release
    name), or failing that from an entry in ``imax_titles.txt`` (bundled plus
    the user's own copy) -- see info.imax.  Shown for the whole runtime
    regardless of L5 metadata: the badge names the film, not the framing of
    whatever is on screen this second.
    """
    if not is_known_imax_title():
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
_LIVE_METADATA_STEP = 1 / 3
_L5_EMPTY = "0 | 0 | 0 | 0"
_L5_PENDING_FRAMES = (
    "/ | / | / | /",
    "- | - | - | -",
    "\\ | \\ | \\ | \\",
)


def _l5_pending_frame() -> str:
    """Return the animated placeholder frame due for the live measurement."""
    turn = int(time.monotonic() / _LIVE_METADATA_STEP)
    return _L5_PENDING_FRAMES[turn % len(_L5_PENDING_FRAMES)]


def _dovi_l5_offsets() -> str:
    """Read the four live L5 offsets directly from CoreELEC's InfoLabels."""
    offsets = tuple(
        clean(info(f"Player.Process(video.dovi.l5.{edge}.offset)")).strip()
        for edge in ("left", "right", "top", "bottom")
    )
    return " | ".join(offsets) if all(offsets) else ""


def _l5_derived() -> tuple[tuple[str, str], ...]:
    """Return the effective DV offsets, derived ratio and independent IMAX badge.

    Live RPU L5 is authoritative whenever any of its four values is non-zero.
    borderprobe is allowed only for an explicit all-zero L5 value; missing
    labels do not qualify.  The effective value is published because the skin
    cannot express the measured Python fallback as a ``Player.Process`` label.
    """
    rpu_offsets = _dovi_l5_offsets()
    use_fallback = (
        live_detection_enabled()
        and rpu_offsets == _L5_EMPTY
        and l5_fallback_required()
    )

    if use_fallback:
        offsets = resolve_l5_offsets(rpu_offsets)
        measured = live_measurement_available()
        if not measured and live_detection_settling():
            offsets = _l5_pending_frame()
    else:
        stop_live_detection()
        offsets = rpu_offsets
        measured = False

    icon_visible = "true" if parse_offsets(offsets) is not None else "false"

    return (
        ("AspectRatioVar", get_AspectRatioVar(offsets)),
        ("ImaxVar", get_ImaxVar()),
        ("DoviLevel5OffsetsVar", offsets),
        ("DoviLevel5OffsetsIconVisible", icon_visible),
        ("DoviLevel5OffsetsLive", "true" if measured else "false"),
    )


def wait_poll(monitor, window, seconds: float = 1.0) -> bool:
    """Wait out one polling interval, keeping the DV L5 row current meanwhile.

    Returns True when Kodi asked to abort.

    CoreELEC's L5 InfoLabels and borderprobe's permitted fallback can change
    with the presented frame.  Only the L5-derived set is refreshed here, and
    only when it changed; every other property stays on the original cadence.
    """
    global _l5_published

    remaining = seconds
    while remaining > 0:
        step = min(_LIVE_METADATA_STEP, remaining)
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

    # Keep live L5, its zero-only borderprobe fallback, the derived aspect ratio
    # and the independent IMAX badge on the fast refresh path.
    l5_derived = _l5_derived()

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
            ("DoviStructureVar", get_structure()),
            ("DoviVersionVar", get_dv_version()),
            ("DoviRpuPresentVar", get_dv_rpu_present()),
            ("DoviBlPresentVar", get_dv_bl_present()),
            ("DoviElPresentVar", get_dv_el_present()),
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
