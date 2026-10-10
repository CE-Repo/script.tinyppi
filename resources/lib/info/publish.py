# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Publish the overlay's readings as window properties.

Call ``publish_scene_properties`` on every polling tick,
``update_static_properties`` on the slower one, and ``publish_properties``
before a window is shown.  The readings themselves come from
``info.properties``.
"""


import xbmcgui
from core import settings
from core.constants import HOME_WINDOW_ID
from core.helpers import fps_display_texts
from core.protocols import PropertyTarget
from core.utils import (
    PROP_HDR10PLUS_PRESENT,
    clean,
    home_window,
    info,
    read_pass,
    set_changed_properties,
)
from info.dvinfo import (
    get_cm_version,
    get_dv_bl_present,
    get_dv_el_present,
    get_dv_el_type,
    get_dv_profile,
    get_dv_rpu_present,
    get_dv_version,
    get_hdr10_max_cll_fall,
    get_hdr10_mdl,
    get_hdr10plus_present,
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
from info.mediasource import get_MediaSourceVar
from info.properties import (
    get_AspectRatioVar,
    get_AudioBitDepthVar,
    get_AudioBitrateKBVar,
    get_AudioChannelsInputVar,
    get_AudioChannelsVar,
    get_AudioCodecSpatialVar,
    get_AudioCodecVar,
    get_AudioLiveBitrateVar,
    get_AudioNameShortVar,
    get_AudioNameVar,
    get_AudioSampleRateVar,
    get_ChannelIconVar,
    get_ChannelLayerVar,
    get_CpuTemperatureProgressVar,
    get_CpuTopUsageVar,
    get_CpuUsageVar,
    get_DisplayModeVar,
    get_DoviTunnelVar,
    get_GamutVar,
    get_ImaxVar,
    get_ModeVar,
    get_SubtitleCodecVar,
    get_SubtitleNameShortVar,
    get_SubtitleNameVar,
    get_VideoBitDepthVar,
    get_VideoBitrateMBVar,
    get_VideoCodecVar,
    get_VideoDecoderLongVar,
    get_VideoDecoderNameVar,
    get_VideoDecoderVar,
    get_VideoLiveBitrateVar,
    get_VideoPixelFormatVar,
    get_VideoResolutionVar,
    output_mode_from_videoplayer,
    separated,
    with_unit,
)

# The PQ row shows raw 12-bit code words (0-4095), not a brightness, so its
# unit is fixed.
_PQ_UNIT = "12-bit"


def _metadata_units() -> tuple[str, str]:
    """Return the (brightness, PQ) units with Kodi color markup.

    Hiding the unit (``unit_type``) hides both, so either all metadata rows
    show a unit or none do.
    """
    unit_color = info(f"Window({HOME_WINDOW_ID}).Property(TinyPPI.UnitColor)")
    unit_label = info(f"Window({HOME_WINDOW_ID}).Property(TinyPPI.UnitLabel)")

    if not unit_label:
        return "", ""
    if unit_color:
        return (
            f"[COLOR={unit_color}]{unit_label}[/COLOR]",
            f"[COLOR={unit_color}]{_PQ_UNIT}[/COLOR]",
        )
    return unit_label, _PQ_UNIT


def _channel_setting_for(hdr_type: str) -> str:
    """Return the channel setting for an ``EffectiveHdrType`` value.

    Mirrors the skin: DV has its own panel, HDR formats share one, empty is
    SDR.
    """
    low = hdr_type.lower()
    if "dolby" in low:
        return "channels_dv"
    if not low:
        return "channels_sdr"
    return "channels_hdr"


def publish_channel_visibility(home: PropertyTarget | None = None,
                               published: dict | None = None) -> None:
    """Publish ``TinyPPI.ShowChannelIcon`` for the current output type.

    Re-read on every poll: the HDR type is detected asynchronously, and a
    settings change should apply without reopening.

    *published* is the polling loop's record; without it every call writes.
    """
    home = home or home_window()
    setting = _channel_setting_for(home.getProperty("TinyPPI.EffectiveHdrType"))
    enabled = settings.addon().getSetting(setting) == "true"
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
    """Return the HDR type the overlay layout follows for source *hdr_type*.

    Normally the source type.  Two VS10 conversions can follow the output
    instead:

    * to SDR (``keep_area_on_sdr`` off): the SDR box is used;
    * DV to HDR10 (``keep_dv_area_on_hdr10`` off): the HDR static-metadata
      panel replaces the Dolby Vision one.

    Both settings keep the source layout by default.  The output comes from
    the mode field of ``amlogic.eoft_gamut``, like the skin's conversion
    rows; anything else (passthrough, unreadable field) keeps the source
    type.
    """
    mode = get_ModeVar().upper()
    addon = settings.addon()
    if mode.startswith("SDR"):
        return hdr_type if addon.getSetting("keep_area_on_sdr") == "true" else ""
    if (mode.startswith("HDR") and "dolby" in hdr_type.lower()
            and addon.getSetting("keep_dv_area_on_hdr10") != "true"):
        return "hdr10"
    return hdr_type


def _hdr10_panel_stands_in_for_dv() -> bool:
    """Return whether the HDR static-metadata panel is shown for a DV source.

    Only for DV -> HDR10 with ``keep_dv_area_on_hdr10`` off; a profile 5
    stream has no static SEI for those rows.  Reads the properties
    ``publish_hdr_type`` last wrote.
    """
    home = home_window()
    return (
        "dolby" in home.getProperty("TinyPPI.HdrType").lower()
        and home.getProperty("TinyPPI.EffectiveHdrType") == "hdr10"
    )


def publish_hdr_type(home: PropertyTarget | None = None,
                     published: dict | None = None) -> None:
    """Publish the source HDR type and the type the layout follows.

    ``TinyPPI.HdrType`` is the source, ``TinyPPI.EffectiveHdrType`` the
    layout type (they differ during VS10 conversion, see
    ``_effective_hdr_type``).  HDR10+ is published as ``hdr10plus`` because
    Kodi's condition parser reads ``+`` as AND; it still contains ``hdr10``
    for ``String.Contains``.

    ``TinyPPI.Hdr10PlusPresent`` marks a Dolby Vision source with an
    ST 2094-40 payload next to its RPU: a hybrid grade VS10 cannot convert,
    so the dialog and dashboard offer no modes for it.

    *published* is the polling loop's record; without it every call writes.
    """
    hdr_type = get_hdr_format()
    if hdr_type == "hdr10+":
        hdr_type = "hdr10plus"
    home = home or home_window()
    if published is None:
        published = {}
    set_changed_properties(
        home,
        published,
        (
            ("TinyPPI.HdrType", hdr_type),
            ("TinyPPI.EffectiveHdrType", _effective_hdr_type(hdr_type)),
            (PROP_HDR10PLUS_PRESENT, get_hdr10plus_present()),
        ),
    )


def _set_progress(window: xbmcgui.Window, published: dict,
                  values: tuple[tuple[int, float], ...]) -> None:
    """Set progress controls, skipping values *published* already holds."""
    for control_id, value in values:
        key = f"__progress_{control_id}"
        if published.get(key) != value:
            window.getControl(control_id).setPercent(value)
            published[key] = value


def update_static_properties(window: xbmcgui.Window, published: dict | None = None) -> None:
    """Publish the per-title properties and the CPU temperature bar.

    For the polling loop's slow cadence.  The progress control is addressed
    by id, which needs the loaded window; before that use
    ``publish_properties``.

    *published* is the polling loop's record, so an idle tick writes
    nothing; without it every call writes.
    """
    if published is None:
        published = {}
    with read_pass():
        publish_static_properties(window, published)
        _set_progress(
            window,
            published,
            (
                (9100, get_CpuTemperatureProgressVar()),
            ),
        )


def publish_scene_properties(window: PropertyTarget, published: dict | None = None) -> None:
    """Publish the Dolby Vision / HDR10 readings that change per scene.

    Active-area offsets and L1 luminance come from the current frame, so the
    aspect ratio and brightness rows can change during playback.  The DV
    version and profile are included because overlay.py highlights them too.

    *published* is the polling loop's record; without it every call writes.
    """
    if published is None:
        published = {}
    with read_pass():
        _publish_scene_properties(window, published)


def _publish_scene_properties(window: PropertyTarget, published: dict) -> None:
    """Run the scene pass inside the caller's ``read_pass``."""
    unit, pq_unit = _metadata_units()

    # Active-area offsets of the current frame, the row's icon, and the
    # aspect ratio inside the bars.
    l5_offsets          = get_l5_offsets()
    l5_icon_visible     = (
        "true" if l5_offsets and not is_status_label(l5_offsets) else "false"
    )
    # L1 frame luminance in nits and as PQ code words.
    l1_fll              = with_unit(separated(get_l1_nits()), unit)
    l1_pq               = with_unit(separated(get_l1_pq()), pq_unit)
    # The RPU mastering display (source range if present, else L6); the flag
    # lets the panel label the rows after the block that was read.
    rpu_mdl             = with_unit(separated(get_rpu_mdl()), unit)
    rpu_mdl_from_source = get_rpu_mdl_from_source()
    l6_rpu_max_cll_fall = with_unit(separated(get_l6_rpu_max_cll_fall()), unit)
    # The static rows borrow L6 only while the HDR panel replaces the DV one.
    # The properties read may be one slow tick old; the type settles once
    # per title, so that is harmless.
    l6_fallback         = _hdr10_panel_stands_in_for_dv()
    hdr10_mdl           = with_unit(separated(get_hdr10_mdl(l6_fallback)), unit)
    hdr10_max_cll_fall  = with_unit(
        separated(get_hdr10_max_cll_fall(l6_fallback)), unit
    )

    set_changed_properties(
        window,
        published,
        (
            ("AspectRatioVar", get_AspectRatioVar(l5_offsets)),
            ("DoviLevel5OffsetsVar", separated(l5_offsets)),
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
            # Per-title facts, but overlay.py highlights them, and on the
            # slow cadence a change would be lit up to a second late.
            ("DoviVersionVar", get_dv_version()),
            ("DoviProfileNumberVar", get_dv_profile()),
        ),
    )


def publish_static_properties(window: PropertyTarget, published: dict | None = None) -> None:
    """Publish the properties that change at most once per title.

    Video and audio format facts, DV / HDR10 presence flags and CPU load.
    Only sets properties, so it is safe before ``doModal()``: the values are
    then in place on the first frame instead of arriving with ``onInit()``,
    while the window is already fading in.

    *published* is the polling loop's record; without it every call writes,
    which is what the pre-``doModal()`` call needs.
    """
    if published is None:
        published = {}
    with read_pass():
        _publish_static_properties(window, published)


def _publish_static_properties(window: PropertyTarget, published: dict) -> None:
    """Run the static pass inside the caller's ``read_pass``."""
    publish_hdr_type(published=published)
    # Uses the type just published; gates the channel graphics below.
    publish_channel_visibility(published=published)

    fps_info_text, fps_out_text = fps_display_texts(
        clean(info("Player.Process(videofps)"))
    )

    # Output mode from side data, else from ``VideoPlayer.HDRType``.
    output_mode = get_output_mode()
    if is_status_label(output_mode):
        output_mode = output_mode_from_videoplayer() or output_mode

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


def publish_properties(window: PropertyTarget, published: dict | None = None) -> None:

    """Publish all player properties to *window* in one pass.

    Called once before ``doModal()`` so the first frame is complete; the
    polling loop then calls the scene and static halves at their own
    cadence.  *published* works as in those two.
    """
    if published is None:
        published = {}
    # One read pass for both halves, so nothing is read twice.
    with read_pass():
        _publish_scene_properties(window, published)
        _publish_static_properties(window, published)
