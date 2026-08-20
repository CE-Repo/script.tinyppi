"""Compute and publish Window properties for TinyPPI.

Call ``publish_scene_properties(window)`` on every polling tick and
``update_static_properties(window)`` on the slower one, and
``publish_properties(window)`` ahead of a window Kodi has not built yet.
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
    is_effective_dv,
    parse_offsets,
    picture_aspect_ratio,
    set_changed_properties,
)
from info.audioinfo import (
    get_active_audio_bit_depth,
    get_active_audio_sample_rate,
)
from info.imax import is_enhanced_title, is_known_imax_title
from info.mediasource import get_MediaSourceVar
from info.dvinfo import (
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
    get_l1_nits,
    get_l1_pq,
    get_l5_offsets,
    get_l6_rpu_max_cll_fall,
    get_output_mode,
    get_rpu_mdl,
    get_rpu_mdl_from_source,
    get_structure,
    is_status_label,
)

# Channel graphics ship pre-scaled to the exact box the skin draws them in
# (see script-tinyppi-main.xml), so Kodi never resamples them: SDR and
# HDR10 / HDR10+ / HLG share the 495x298 box, DV uses the smaller 400x241 panel.
_CHANNEL_DIR_DEFAULT = "channels/495x298"
_CHANNEL_DIR_DV      = "channels/400x241"


def _channel_dir() -> str:
    """Return the folder holding the display-sized graphics for the current
    output type: the DV panel is smaller than the SDR / HDR box."""
    return _CHANNEL_DIR_DV if is_effective_dv() else _CHANNEL_DIR_DEFAULT


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
# The RPU places the active area to the pixel, but the ratio that falls out of
# it still lands a hair off a familiar number — enough to show a 2.39 film as
# 2.40 without snapping.  Anything further out than the tolerance is shown as
# calculated rather than forced onto a familiar number.
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

    Kodi's ``videodar`` describes the coded frame, so a title letterboxed inside
    it reads as 1.78 even while the picture on screen is 2.39; scaling the coded
    ratio by the RPU's active-area offsets gives the ratio actually being
    watched.  Falls back to Kodi's own value when the bars are unknown, or when
    they're a ``0 | 0 | 0 | 0`` that isn't backed by anything: outside Dolby
    Vision ``l5_offsets`` is only ever dvinfo's placeholder, never a real
    reading, so it carries no more information than Kodi's own ratio.  On a
    Dolby Vision stream the same value is computed anyway, since there the RPU
    is the confirmation and all-zero means a genuine no crop.  ``is_dv`` lets a
    caller pass in already-read state; left out, it is read here.
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
    """Return ``IMAX Enhanced`` / ``IMAX`` for a film recognised as IMAX
    material, or ``''`` otherwise.

    Recognised from its filename (an ``IMAX`` / ``IMAX Enhanced`` release
    name), or failing that from an entry in ``imax_titles.txt`` (bundled plus
    the user's own copy) -- see info.imax.  Shown for the whole runtime: the
    badge names the film, not the framing of whatever is on screen this second.
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

    Only a full enhancement layer raises the depth, to the 12-bit the base
    layer and FEL reconstruct to; dvinfo reports that one case.  Every other
    HDR format -- MEL, single-layer Dolby Vision, HDR10, HDR10+, HLG -- is
    10-bit, and SDR is 8-bit.
    """
    value = get_bit_depth()
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


# Between the value and its unit (``1000 l 400 cd/m²``).
_UNIT_GAP = " "


# What separates the numbers of a multi-part metadata value on screen: a
# lowercase L, not the pipe the values carry internally.  Purely a matter of
# how font23_narrow draws the two.  Swapped here, at the point of publishing,
# so the values themselves stay pipe-joined and parse_offsets() keeps working
# on them (the aspect-ratio row is computed from the same L5 string).
_DISPLAY_SEPARATOR = "l"


def _separated(value: str) -> str:
    """Return a metadata value with its pipes swapped for the display
    separator.  Status labels carry none, so they pass through untouched."""
    return value.replace("|", _DISPLAY_SEPARATOR)


def _with_unit(value: str, unit: str) -> str:
    """Append ``unit`` to a metadata value, but not to status labels.

    The ``0 | 0`` placeholder still gets the unit (``0 | 0  cd/m²``); the
    ``N/A`` label is left unchanged.
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


def get_GamutVar() -> str:
    """Return the second token of ``amlogic.eoft_gamut`` (the gamut field)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    return parts[1] if len(parts) > 1 else ""


def _output_mode_from_videoplayer() -> str:
    """Classify Kodi's ``VideoPlayer.HDRType`` InfoLabel into an output-mode
    label (``SDR`` / ``HDR10`` / ``HLG`` / ``HDR10+`` / ``Dolby Vision``).

    Reads Kodi's own source-side HDR detection, so a stream that carries no
    side-data payload still names its format.  An empty ``VideoPlayer.HDRType``
    means no HDR signalling, i.e. ``SDR``.
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

    Prefers the depth read from the source bitstream itself for the active
    track (see audioinfo.py).  While detection runs or finds nothing, known
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

    Prefers the rate read from the source bitstream: Kodi reports
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


# The PQ row carries raw code words rather than a brightness, so its unit is
# fixed at the depth of the code space (0-4095) instead of following the
# cd/m² / nits choice.
_PQ_UNIT = "12-bit"


def _metadata_units() -> tuple[str, str]:
    """Return the (brightness, PQ) metadata units, including Kodi color markup.

    One setting governs both: ``unit_type`` set to hidden empties the brightness
    label, and the PQ unit goes with it, so the metadata rows either all wear a
    unit or none of them do.
    """
    unit_color = info("Window(10000).Property(TinyPPI.UnitColor)")
    unit_label = info("Window(10000).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return "", ""
    if unit_color:
        return (
            f"[COLOR={unit_color}]{unit_label}[/COLOR]",
            f"[COLOR={unit_color}]{_PQ_UNIT}[/COLOR]",
        )
    return unit_label, _PQ_UNIT


def _channel_setting_for(hdr_type: str) -> str:
    """Return the channel setting that governs an ``EffectiveHdrType`` token.

    Mirrors the branches the skin draws: DV has its own panel, HDR10 / HDR10+ /
    HLG share one layout, and an empty type means SDR.
    """
    low = hdr_type.lower()
    if "dolby" in low:
        return "channels_dv"
    if not low:
        return "channels_sdr"
    return "channels_hdr"


def publish_channel_visibility(home=None, published=None) -> None:
    """Publish ``TinyPPI.ShowChannelIcon`` for the current output type.

    Re-read every poll rather than once at open: the HDR type is detected
    asynchronously, so a stream that turns out to be DV must switch to the DV
    setting while the overlay is up.  A fresh ``Addon()`` avoids its cached
    settings, so toggling one applies without reopening.

    ``published`` tracks the polling loop's window; pass it from there to
    skip the write when the setting hasn't changed.  Left unset, every call
    writes unconditionally.
    """
    home = home or xbmcgui.Window(10000)
    setting = _channel_setting_for(home.getProperty("TinyPPI.EffectiveHdrType"))
    enabled = xbmcaddon.Addon().getSetting(setting) == "true"
    if published is None:
        published = {}
    set_changed_properties(
        home,
        published,
        (
            ("TinyPPI.ShowChannelIcon", "1" if enabled else "0"),
        ),
    )


def _effective_hdr_type(hdr_type: str) -> str:
    """Return the HDR type the overlay layout follows for a source ``hdr_type``.

    Normally the source itself; the two VS10 conversions that leave the source's
    panels describing a signal the display never receives can each be made to
    follow the output instead:

    * to SDR (``keep_area_on_sdr`` off), where no HDR panel applies at all, so
      the overlay drops to its SDR box;
    * DV to HDR10 (``keep_dv_area_on_hdr10`` off), where the HDR
      static-metadata panel takes over from the Dolby Vision one.

    Both settings default to keeping the source's area, so the layout only
    changes for someone who asked for it.  A fresh ``Addon()`` avoids the cached
    settings, so a toggle applies without reopening the overlay.

    The output side is the mode field of ``amlogic.eoft_gamut``, the same signal
    the skin's ``-> SDR`` / ``-> HDR10`` conversion rows branch on.  Anything
    else -- a passed-through source, an unreadable field (no playback, a kernel
    that does not expose it) -- keeps the source type, so a missing value never
    collapses the layout on its own.
    """
    mode = get_ModeVar().upper()
    addon = xbmcaddon.Addon()
    if mode.startswith("SDR"):
        return hdr_type if addon.getSetting("keep_area_on_sdr") == "true" else ""
    if mode.startswith("HDR") and "dolby" in hdr_type.lower():
        if addon.getSetting("keep_dv_area_on_hdr10") != "true":
            return "hdr10"
    return hdr_type


def _hdr10_panel_stands_in_for_dv() -> bool:
    """Return whether the HDR static-metadata panel is drawn for a DV source.

    True only in the DV -> HDR10 case with ``keep_dv_area_on_hdr10`` off, where
    the Dolby Vision panels are off screen and the HDR panel is left holding
    rows a profile 5 stream has no static SEI for.  Reads the properties
    ``publish_hdr_type`` refreshed at the top of this pass.
    """
    home = xbmcgui.Window(10000)
    return (
        "dolby" in home.getProperty("TinyPPI.HdrType").lower()
        and home.getProperty("TinyPPI.EffectiveHdrType") == "hdr10"
    )


def publish_hdr_type(home=None, published=None) -> None:
    """Publish the detected source HDR type as ``TinyPPI.HdrType`` on the Home
    window, plus the type the overlay layout follows as
    ``TinyPPI.EffectiveHdrType``.

    HDR10+ is published as ``hdr10plus`` because Kodi's boolean parser treats
    ``+`` as AND; it still contains ``hdr10`` so ``String.Contains`` branches match.

    The two differ once VS10 converts (see ``_effective_hdr_type``): the source
    stays HDR / DV -- the mode-select dialog and the ``Converting`` row need it
    to name what is being converted -- while the overlay follows the output.

    ``published`` tracks the polling loop's window; pass it from there to
    skip a write when neither value has changed.  Left unset, every call
    writes unconditionally.
    """
    hdr_type = get_hdr_format()
    if hdr_type == "hdr10+":
        hdr_type = "hdr10plus"
    home = home or xbmcgui.Window(10000)
    if published is None:
        published = {}
    set_changed_properties(
        home,
        published,
        (
            ("TinyPPI.HdrType", hdr_type),
            ("TinyPPI.EffectiveHdrType", _effective_hdr_type(hdr_type)),
        ),
    )


def _set_progress(window, published: dict, values: tuple[tuple[int, float], ...]) -> None:
    """Publish a batch of progress-control percentages, skipping the ones
    ``published`` already recorded at the same value."""
    for control_id, value in values:
        key = f"__progress_{control_id}"
        if published.get(key) != value:
            window.getControl(control_id).setPercent(value)
            published[key] = value


def update_static_properties(window, published=None) -> None:
    """Compute the properties that settle at most once a title and refresh
    the CPU-temperature progress control.

    Call from the polling loop's slow cadence; ``publish_scene_properties``
    covers the Dolby Vision / HDR10 readings that need the fast one instead.
    ``_set_progress`` addresses a control by id, which only resolves once
    Kodi has loaded the window's XML -- before that, and only before that,
    use ``publish_properties``.

    ``published`` tracks the polling loop's window across ticks, so an idle
    tick costs no ``setProperty``/``setPercent`` calls; pass the loop's own
    dict to get that.  Left unset, every call writes unconditionally.
    """
    if published is None:
        published = {}
    publish_static_properties(window, published)
    _set_progress(
        window,
        published,
        (
            (9100, get_CpuTemperatureProgressVar()),
        ),
    )


def publish_scene_properties(window, published=None) -> None:
    """Publish the Dolby Vision / HDR10 readings that can move every scene:
    the RPU's active-area offsets and L1 frame luminance come from the frame
    on screen, not the title, so the aspect ratio and brightness rows can
    change mid-playback (an IMAX Enhanced expansion, a brightness shift at a
    scene cut) the way the rest of the overlay does not.  Also carries the
    DV version and profile number, which don't move but are highlighted
    alongside the rest by overlay.py and so need the same cadence.

    ``published`` tracks the state of ``window``; pass the poll loop's own
    dict to skip rewriting values that haven't changed.  Left unset, every
    call writes unconditionally.
    """
    if published is None:
        published = {}
    unit, pq_unit = _metadata_units()

    # The active-area offsets the RPU declares for the frame on screen, and
    # everything that follows from them: the icon beside the row, and the aspect
    # ratio of the picture inside the bars (which Kodi's own ``videodar`` cannot
    # give, since it describes the coded frame).
    l5_offsets          = get_l5_offsets()
    l5_icon_visible     = (
        "true" if l5_offsets and not is_status_label(l5_offsets) else "false"
    )
    # Level 1 frame luminance: nits carry the brightness unit, the raw PQ codes
    # carry the depth of their code space.
    l1_fll              = _with_unit(_separated(get_l1_nits()), unit)
    l1_pq               = _with_unit(_separated(get_l1_pq()), pq_unit)
    # The RPU's mastering display: the source range when the stream carries it,
    # else L6.  The flag travels with it so the panel can label both RPU rows
    # after whichever block was read.
    rpu_mdl             = _with_unit(_separated(get_rpu_mdl()), unit)
    rpu_mdl_from_source = get_rpu_mdl_from_source()
    l6_rpu_max_cll_fall = _with_unit(_separated(get_l6_rpu_max_cll_fall()), unit)
    # Only while the HDR panel stands in for the Dolby Vision one may the static
    # rows borrow L6; the DV panel itself prints both as separate rows.  Reads
    # the Home-window properties publish_static_properties last wrote, which
    # may be up to a static-poll tick stale -- the type they describe settles
    # at most once a title, so that is not a real staleness risk.
    l6_fallback         = _hdr10_panel_stands_in_for_dv()
    hdr10_mdl           = _with_unit(_separated(get_hdr10_mdl(l6_fallback)), unit)
    hdr10_max_cll_fall  = _with_unit(
        _separated(get_hdr10_max_cll_fall(l6_fallback)), unit
    )

    set_changed_properties(
        window,
        published,
        (
            ("AspectRatioVar", get_AspectRatioVar(l5_offsets)),
            ("DoviLevel5OffsetsVar", _separated(l5_offsets)),
            ("DoviLevel5OffsetsIconVisible", l5_icon_visible),
            ("DoviCmVersionVar", get_cm_version()),
            ("DoviStructureVar", get_structure()),
            ("DoviLevel1FllVar", l1_fll),
            ("DoviLevel1PqVar", l1_pq),
            ("DoviRpuMdlVar", rpu_mdl),
            ("DoviRpuMdlFromSourceVar", rpu_mdl_from_source),
            ("DoviLevel6RpuMaxCllFallVar", l6_rpu_max_cll_fall),
            ("Hdr10MdlVar", hdr10_mdl),
            ("Hdr10MaxCllFallVar", hdr10_max_cll_fall),
            # Format facts, not scene-variant, but overlay.py's
            # _DV_VALUE_PROPERTIES highlights both, and a highlight is only as
            # current as the reading behind it: on the slow cadence a profile
            # or version that did change would go unlit for up to a second
            # after the fact, which is the one moment it is worth seeing.
            ("DoviVersionVar", get_dv_version()),
            ("DoviProfileNumberVar", get_dv_profile()),
        ),
    )


def publish_static_properties(window, published=None) -> None:
    """Publish the properties that settle at most once a title: video and
    audio format facts, the Dolby Vision / HDR10 presence flags, and CPU
    load.  ``publish_scene_properties`` covers the readings that can move
    every scene instead, plus the DV version and profile number, which are
    also format facts but need the fast cadence anyway because overlay.py
    highlights them when they change.

    Sets properties and nothing else, so it is safe on a window Kodi has not
    built yet.  That is the point: called just before ``doModal()``, the values
    are already in place when the window is first drawn, instead of arriving
    with ``onInit()`` -- which Kodi dispatches to the script thread while the
    window is on screen and fading in, leaving the rows empty until it lands.

    ``published`` tracks the state of ``window``; pass the poll loop's own
    dict to skip rewriting values that haven't changed.  Left unset, every
    call writes unconditionally, which is what the pre-``doModal()`` caller
    above needs on a window nothing has been published to yet.
    """
    if published is None:
        published = {}
    publish_hdr_type(published=published)
    # Depends on the type just published, and gates the channel graphics below.
    publish_channel_visibility(published=published)

    fps_info_text, fps_out_text = fps_display_texts(
        clean(info("Player.Process(videofps)"))
    )

    # Output-mode line from the stream's side data; fall back to a plain label
    # from Kodi's ``VideoPlayer.HDRType`` when it would show N/A.
    output_mode = get_output_mode()
    if is_status_label(output_mode):
        output_mode = _output_mode_from_videoplayer() or output_mode

    set_changed_properties(
        window,
        published,
        (
            ("VideoDecoderVar", get_VideoDecoderVar()),
            ("VideoDecoderLongVar", get_VideoDecoderLongVar()),
            ("VideoPixelFormatVar", get_VideoPixelFormatVar()),
            ("DisplayModeVar", get_DisplayModeVar()),
            ("VideoResolutionVar", get_VideoResolutionVar()),
            ("ImaxVar", get_ImaxVar()),
            ("VideoBitrateMBVar", get_VideoBitrateMBVar()),
            ("VideoLiveBitrateVar", get_VideoLiveBitrateVar()),
            ("VideoCodecVar", get_VideoCodecVar()),
            ("VideoDecoderNameVar", get_VideoDecoderNameVar()),
            ("VideoBitDepthVar", get_VideoBitDepthVar()),
            ("DoviProfileVar", output_mode),
            ("MediaSourceVar", get_MediaSourceVar()),
            ("DoviTunnelVar", get_DoviTunnelVar()),
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


def publish_properties(window, published=None) -> None:
    """Publish every player property to ``window`` in one pass: a thin
    wrapper combining ``publish_scene_properties`` and
    ``publish_static_properties``, called once before ``doModal()`` so the
    first frame's values are already in place before Kodi draws the window.
    The polling loop calls the two halves separately afterward, each at its
    own cadence.

    ``published`` tracks the state of ``window``, same as in the two halves
    this wraps.
    """
    if published is None:
        published = {}
    publish_scene_properties(window, published)
    publish_static_properties(window, published)
