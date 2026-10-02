# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Codec-logo splash for playback start, the video OSD and the overlay.

The service runs this on its own thread on ``Player.OnAVStart`` (or via
``RunScript(script.tinyppi,splash)``).  It stacks the video and audio format
logos in a panel; per mode, ``splash_<mode>_order`` swaps them and
``splash_<mode>_show_video`` / ``_show_audio`` hide either.  Modes:
``splash_enabled`` (first ``splash_duration`` seconds), ``splash_show_on_osd``
and ``splash_show_on_tinyppi``.

The logos are ``ControlImage`` controls added to the fullscreen video window
(12005), shown and hidden by visibility conditions (see ``_fade_in`` /
``_fade_out``); unlike a modeless dialog this keeps playback controls usable.
Logos are re-resolved every poll, so audio track changes show live.
"""

import os
import time
from typing import NamedTuple

import xbmc
import xbmcgui
from core import settings
from core.constants import HOME_WINDOW_ID
from core.log import channel
from core.images import display_texture
from core.maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP, IMAX_LOGO_MAP
from core.utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_RUNNING, info
from info.dvinfo import get_dv_el_type_raw, get_hdr_format
from info.imax import imax_logo, is_known_imax_title
from ui.theme import apply_theme

_MEDIA_PATH = os.path.join(
    settings.addon().getAddonInfo("path"), "resources", "skins", "Default", "media"
)

_log = channel("splash")

# Kodi window id of the fullscreen video window.
WINDOW_FULLSCREEN_VIDEO = 12005

# Re-entry guard against stacked controllers; a Home property because a
# RunScript call runs in another interpreter than the service's thread.
PROP_SPLASH_ACTIVE = "TinyPPI.SplashActive"

# ControlImage aspect-ratio modes: keep for the logos, stretch for the panel.
_ASPECT_KEEP    = 2
_ASPECT_STRETCH = 0

# Background panel: 9-slice rounded rectangle from a 1x1 fill and four corner
# masks, tinted with one ARGB colour.
_BG_TEXTURE     = os.path.join("common", "dot-1x1.png")
_DIVIDER_COLOR  = "59FFFFFF"
# Conversion badge in the panel's top-right corner (see _is_converting).
_DOT_TEXTURE       = os.path.join("common", "dot-circle.png")
_CONVERT_DOT_COLOR = "FF81C784"  # palette Forest
# DV layer pill on the panel's bottom (or top) edge (see _dv_layer_token).
_PILL_TEXTURE = os.path.join("common", "pill.png")
_CORNER_TEXTURES = {
    "tl": os.path.join("splash", "corner-tl.png"),
    "tr": os.path.join("splash", "corner-tr.png"),
    "bl": os.path.join("splash", "corner-bl.png"),
    "br": os.path.join("splash", "corner-br.png"),
}

# Fallback colours until theme.apply_theme has published the themed ones.
_BG_COLOR   = "FA15181A"  # Charcoal panel (matches the overlay background)
_LOGO_COLOR = "FFEDEDED"  # near-white (leaves white logos unchanged)

# Home properties of the splash colours (from theme.apply_theme), separate
# per context (start / osd / tinyppi).
_MODE_PROP_PREFIX = {
    "start":   "TinyPPI.SplashStart",
    "osd":     "TinyPPI.SplashOsd",
    "tinyppi": "TinyPPI.SplashTinyppi",
}
_COLOR_PROP_SUFFIX = {
    "bg":          "BgColor",
    "video":       "VideoColor",
    "audio":       "AudioColor",
    "divider":     "DividerColor",
    "convert_dot": "ConvertDotColor",
    "fel":         "FelColor",
    "mel":         "MelColor",
    "other":       "DvColor",
}

# Controller poll interval (seconds).
_POLL_INTERVAL = 0.25

# Re-read interval of the source format once known (seconds).
_FORMAT_INTERVAL = 1.0

# At playback start the display is often still switching, so an HDR or DV
# film briefly reads as SDR output.  Nothing is drawn until the output has
# been stable for _SETTLE_SECONDS; HDR/DV shown as SDR output gets up to
# _SETTLE_SDR_LIMIT to change before it is believed.
_SETTLE_SECONDS   = 1.0
_SETTLE_SDR_LIMIT = 3.0


class _ModeState(NamedTuple):
    """Everything one mode's controls are built from.

    Compared with the previous poll's value; any change rebuilds the mode's
    controls (hence ``colors`` as a sorted tuple).
    """

    logos: tuple
    offset_x: int
    offset_y: int
    scale: float
    colors: tuple
    condition: str
    layer_token: str
    pill_at_top: bool


class _ModeSettings(NamedTuple):
    """One mode's settings, read once per settings change."""

    show_video: bool
    show_audio: bool
    audio_first: bool
    offset_x: int
    offset_y: int
    scale: float
    pill_at_top: bool


class _Settings(NamedTuple):
    """All settings the controller uses.

    Read in one go when ``core.settings`` returns a new handle (i.e. after a
    change), not on every poll.
    """

    show_on_start: bool
    show_on_osd: bool
    show_on_tinyppi: bool
    duration: int
    modes: dict


# Kodi plays Visible/Hidden animations on runtime-added controls only when a
# visibility condition changes (not on setVisible()), so the controls watch a
# global and a per-mode Home property.  OSD and overlay conditions can then
# start the fades at once.
PROP_SPLASH_VISIBLE = "TinyPPI.SplashVisible"
_VISIBLE_CONDITION  = (
    f"String.IsEqual(Window({HOME_WINDOW_ID}).Property({PROP_SPLASH_VISIBLE}),true)"
)
# Token of the current controller run, part of every control's condition, so
# controls a run had to leave behind stay hidden (see open_splash's cleanup).
PROP_SPLASH_RUN = "TinyPPI.SplashRun"
_MODE_VISIBLE_PROPS = {
    "start":   "TinyPPI.SplashStartVisible",
    "osd":     "TinyPPI.SplashOsdVisible",
    "tinyppi": "TinyPPI.SplashTinyPPIVisible",
}
_FADE_IN_MS       = 350
_FADE_OUT_MS      = 150
_FADE_OUT_SECONDS = (_FADE_OUT_MS + 60) / 1000.0  # slightly past the fade
_RENDER_TICK      = 0.05  # one render frame for Kodi to apply a change
_ANIM_IN  = ("Visible",
             f"effect=fade start=0 end=100 time={_FADE_IN_MS} tween=cubic easing=inout")
_ANIM_OUT = ("Hidden",
             f"effect=fade start=100 end=0 time={_FADE_OUT_MS}")

# "true" while a conversion is active (see _is_converting); part of the
# badge's condition, so it toggles without a rebuild.
PROP_CONVERTING = "TinyPPI.SplashConverting"


def _is_converting(hdr_type: str, gamut: str) -> bool:
    """Return whether the output *gamut* shows a conversion.

    Mirrors the check-circle condition in script-tinyppi-main.xml: non-DV
    source output as DV, HDR/DV output as SDR, or SDR/DV output as HDR10.
    *hdr_type* comes from the side data, so this works without the overlay.
    """
    gamut = gamut.upper()
    parts = gamut.split()
    mode = parts[0] if parts else ""

    non_dv_source     = hdr_type in ("hdr10", "hlg", "hdr10+", "")
    hdr_or_dv_source  = hdr_type in ("hdr10", "hlg", "hdr10+") or "dolby" in hdr_type
    sdr_or_dv_source  = hdr_type in ("", "hdr10+") or "dolby" in hdr_type

    if non_dv_source and "DV" in gamut:
        return True
    if hdr_or_dv_source and "SDR" in gamut:
        return True
    return bool(sdr_or_dv_source and mode == "HDR10")


# Fallback DV pill colours per layer (FEL forest, MEL tangerine, other white).
_LAYER_COLOR_FALLBACK = {
    "fel":   "FF81C784",  # palette Forest
    "mel":   "FFFFB74D",  # palette Tangerine
    "other": _LOGO_COLOR,  # palette White
}


def _dv_layer_token(hdr_token: str, hdr_type: str, el_type: str) -> str:
    """Return the DV pill token for the output: fel, mel, other or ''.

    Based on the actual output (*hdr_token*): '' when it is not DV, 'other'
    for non-DV sources converted to DV and other profiles, else the source's
    enhancement layer (*el_type*).
    """
    if hdr_token != "dolbyvision":
        return ""
    if "dolby" not in hdr_type:
        return "other"
    el_type = el_type.upper()
    if el_type == "FEL":
        return "fel"
    if el_type == "MEL":
        return "mel"
    return "other"


# Per-mode offset settings (x, y).
_OFFSET_SETTINGS = {
    "start":   ("splash_start_offset_x",   "splash_start_offset_y"),
    "osd":     ("splash_osd_offset_x",     "splash_osd_offset_y"),
    "tinyppi": ("splash_tinyppi_offset_x", "splash_tinyppi_offset_y"),
}

# Per-mode size setting (80-130 %, default 100 %), times _BASE_SCALE.
_SCALE_SETTINGS = {
    "start":   "splash_start_scale",
    "osd":     "splash_osd_scale",
    "tinyppi": "splash_tinyppi_scale",
}

# Per-mode logo selection and order (default: both, video on top).
_SHOW_VIDEO_SETTINGS = {
    "start":   "splash_start_show_video",
    "osd":     "splash_osd_show_video",
    "tinyppi": "splash_tinyppi_show_video",
}
_SHOW_AUDIO_SETTINGS = {
    "start":   "splash_start_show_audio",
    "osd":     "splash_osd_show_audio",
    "tinyppi": "splash_tinyppi_show_audio",
}
_ORDER_SETTINGS = {
    "start":   "splash_start_order",
    "osd":     "splash_osd_order",
    "tinyppi": "splash_tinyppi_order",
}
# splash_<mode>_order: 0 keeps video on top, 1 puts audio on top.
_ORDER_AUDIO_FIRST = 1

# Per-mode edge of the DV layer pill.
_PILL_POSITION_SETTINGS = {
    "start":   "splash_start_pill_position",
    "osd":     "splash_osd_pill_position",
    "tinyppi": "splash_tinyppi_pill_position",
}
# splash_<mode>_pill_position: 0 bottom edge, 1 top edge.
_PILL_TOP = 1

# Base scale of the logo block (at a user scale of 100 %).
_BASE_SCALE = 0.95


def _amlogic_hdr_token(gamut: str) -> str:
    """Map the Amlogic output mode to an ``HDR_LOGO_MAP`` key ('' for SDR)."""
    parts = gamut.split()
    mode = parts[0].upper() if parts else ""
    if "DV" in mode or "DOLBY" in mode:
        return "dolbyvision"
    if "HDR10+" in mode or "HDR10PLUS" in mode or "PLUS" in mode:
        return "hdr10+"
    if "HLG" in mode:
        return "hlg"
    if "HDR" in mode:
        return "hdr10"
    return ""


def _current_logos(hdr_token: str) -> tuple[str, str]:
    """Return the ``(video, audio)`` logos for the current output.

    The video logo is always set (SDR fallback); the audio logo is '' for a
    codec without one.  ``_mode_logos`` decides what a mode shows.
    """
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    audio_logo = AUDIO_LOGO_MAP.get(codec, "")

    video_logo = HDR_LOGO_MAP.get(hdr_token, HDR_LOGO_MAP[""])
    # IMAX films get the combined logo of the output format.  The map lookup
    # comes first, so only candidate formats pay for the title match.
    if hdr_token in IMAX_LOGO_MAP and is_known_imax_title():
        video_logo = imax_logo(hdr_token) or video_logo

    return video_logo, audio_logo


def _has_audio(player: xbmc.Player) -> bool:
    """Return whether the video has an audio track.

    Asks the player as well: the codec is also empty before Kodi has named
    it.
    """
    if info("VideoPlayer.AudioCodec").strip():
        return True
    try:
        return bool(player.getAvailableAudioStreams())
    except RuntimeError:
        # Playback ended; the loop notices.  True keeps the stack unchanged.
        return True


def _mode_logos(
    mode_settings: _ModeSettings, logos: tuple[str, str],
    has_audio: bool = True,
) -> tuple[tuple[str, str], ...]:
    """Return a mode's stack as ``(logo, colour key)`` pairs, top first.

    Applies the mode's show and order settings.  With both logos enabled the
    stack is all or nothing (an audio codec without a logo shows nothing),
    except for videos without audio (*has_audio* False), which show the
    video logo alone.
    """
    video_logo, audio_logo = logos
    show_video = mode_settings.show_video
    show_audio = mode_settings.show_audio and has_audio
    if show_video and show_audio and not (video_logo and audio_logo):
        return ()

    stack = []
    if show_video and video_logo:
        stack.append((video_logo, "video"))
    if show_audio and audio_logo:
        stack.append((audio_logo, "audio"))
    if mode_settings.audio_first:
        stack.reverse()
    return tuple(stack)


def _make_image(rel_path: str, x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Build a tinted, aspect-keeping image from a media-relative path."""
    full_path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
    texture = display_texture(full_path, w, h)
    return xbmcgui.ControlImage(
        x, y, w, h, texture, aspectRatio=_ASPECT_KEEP, colorDiffuse=color,
    )


def _make_dot(cx: int, cy: int, diameter: int, color: str) -> xbmcgui.ControlImage:
    """Build a filled circle centred on (*cx*, *cy*)."""
    return _make_image(
        _DOT_TEXTURE,
        cx - diameter // 2, cy - diameter // 2, diameter, diameter, color,
    )


def _solid(x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Return a solid-colour rectangle from the 1x1 texture."""
    texture = os.path.join(_MEDIA_PATH, _BG_TEXTURE)
    return xbmcgui.ControlImage(
        x, y, max(1, w), max(1, h), texture,
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )


def _panel_controls(
    x: int, y: int, w: int, h: int, radius: int, color: str
) -> list[xbmcgui.ControlImage]:
    """Build a rounded rectangle from a centre, four edges and four corners."""
    c = max(1, min(radius, w // 2, h // 2))
    corner = lambda key, cx, cy: xbmcgui.ControlImage(  # noqa: E731
        cx, cy, c, c, os.path.join(_MEDIA_PATH, _CORNER_TEXTURES[key]),
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )
    return [
        _solid(x + c, y + c, w - 2 * c, h - 2 * c, color),  # centre
        _solid(x + c, y, w - 2 * c, c, color),              # top edge
        _solid(x + c, y + h - c, w - 2 * c, c, color),      # bottom edge
        _solid(x, y + c, c, h - 2 * c, color),              # left edge
        _solid(x + w - c, y + c, c, h - 2 * c, color),      # right edge
        corner("tl", x, y),
        corner("tr", x + w - c, y),
        corner("bl", x, y + h - c),
        corner("br", x + w - c, y + h - c),
    ]


def _build_controls(
    logos: list[tuple[str, str]], colors: dict[str, str],
    offset_x: int, offset_y: int, screen_w: int, screen_h: int,
    user_scale: float = 1.0, layer_token: str = "", pill_at_top: bool = False,
) -> tuple[list[xbmcgui.ControlImage], xbmcgui.ControlImage | None]:
    """Lay out the logos as a vertical stack on a rounded panel.

    *logos* are ``(logo, colour key)`` pairs, top first; a single logo has
    no divider.  Sizes are fractions of the window's coordinate space.
    *offset_x* / *offset_y* (0-100 %) move the panel from the top-left inset
    to the bottom-right; *user_scale* resizes it.  *colors* holds the tints
    by key; *layer_token* picks the DV pill colour ('' for no pill), and
    *pill_at_top* moves the pill to the top edge.

    Returns ``(controls, dot)``; *dot* is the conversion badge (also in
    *controls*) for its own condition, None when there are no logos.
    """
    if not logos:
        return [], None

    # Base scale times the mode's own scale.
    scale = _BASE_SCALE * user_scale

    box_w    = int(screen_w * 0.09 * scale)
    box_h    = int(screen_h * 0.055 * scale)
    v_gap    = int(screen_h * 0.02 * scale)
    pad_x    = int(screen_w * 0.012 * scale)
    pad_y    = int(screen_h * 0.02 * scale)
    radius   = int(screen_h * 0.02 * scale)

    count   = len(logos)
    stack_h = count * box_h + (count - 1) * v_gap
    panel_w = box_w + 2 * pad_x
    panel_h = stack_h + 2 * pad_y

    # Position: an inset at 0 %, a smaller gap at 100 %, never flush.
    inset = int(screen_h * 0.0325)
    edge  = 35
    offset_x = min(100, max(0, offset_x))
    offset_y = min(100, max(0, offset_y))
    panel_x = inset + max(0, screen_w - panel_w - inset - edge) * offset_x // 100
    panel_y = inset + max(0, screen_h - panel_h - inset - edge) * offset_y // 100
    block_x = panel_x + pad_x
    top     = panel_y + pad_y

    controls: list[xbmcgui.ControlImage] = []

    # Panel and divider; always present, hidden by their themed opacity.
    controls.extend(_panel_controls(
        block_x - pad_x, top - pad_y,
        box_w + 2 * pad_x, panel_h,
        radius, colors["bg"],
    ))
    if count == 2:
        div_h = max(1, int(screen_h * 0.0025 * scale))
        div_y = top + box_h + v_gap // 2 - div_h // 2
        controls.append(_solid(block_x, div_y, box_w, div_h, colors["divider"]))

    # Logos top to bottom, each tinted by its kind (follows the order).
    for index, (logo, kind) in enumerate(logos):
        y = top + index * (box_h + v_gap)
        controls.append(_make_image(logo, block_x, y, box_w, box_h, colors[kind]))

    # Conversion badge in the top-right corner (condition set by the caller).
    dot_d   = max(1, int(box_h * 0.20))
    dot_pad = max(1, int(box_h * 0.20))
    dot_cx  = panel_x + panel_w - dot_pad - dot_d // 2
    dot_cy  = panel_y + dot_pad + dot_d // 2
    dot = _make_dot(dot_cx, dot_cy, dot_d, colors["convert_dot"])
    controls.append(dot)

    # DV layer pill, centred on the bottom or top edge; none for non-DV.
    if layer_token in ("fel", "mel", "other"):
        pill_w      = max(1, int(box_w * 0.30))
        pill_h      = max(1, int(box_h * 0.15))
        pill_margin = max(1, int(box_h * 0.10))
        pill_x = panel_x + (panel_w - pill_w) // 2
        pill_y = (
            panel_y + pill_margin if pill_at_top
            else panel_y + panel_h - pill_margin - pill_h
        )
        controls.append(
            _make_image(_PILL_TEXTURE, pill_x, pill_y, pill_w, pill_h, colors[layer_token])
        )

    return controls, dot


def _window_dims(window) -> tuple[int, int]:
    """Return the coordinate space ``addControl`` uses on *window*.

    The window's own size, which may differ from the screen size; falls
    back to the screen size when the window reports none.
    """
    try:
        width, height = window.getWidth(), window.getHeight()
    except Exception:
        width = height = 0
    if width >= 640 and height >= 480:
        return width, height
    return xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()


def _read_settings(addon) -> _Settings:
    """Read all controller settings (see ``_Settings``)."""
    modes = {}
    for mode in _MODE_PROP_PREFIX:
        setting_x, setting_y = _OFFSET_SETTINGS[mode]
        modes[mode] = _ModeSettings(
            show_video=addon.getSettingBool(_SHOW_VIDEO_SETTINGS[mode]),
            show_audio=addon.getSettingBool(_SHOW_AUDIO_SETTINGS[mode]),
            audio_first=(
                addon.getSettingInt(_ORDER_SETTINGS[mode]) == _ORDER_AUDIO_FIRST
            ),
            offset_x=addon.getSettingInt(setting_x),
            offset_y=addon.getSettingInt(setting_y),
            scale=_mode_scale(addon, mode),
            pill_at_top=(
                addon.getSettingInt(_PILL_POSITION_SETTINGS[mode]) == _PILL_TOP
            ),
        )
    return _Settings(
        show_on_start=addon.getSettingBool("splash_enabled"),
        show_on_osd=addon.getSettingBool("splash_show_on_osd"),
        show_on_tinyppi=addon.getSettingBool("splash_show_on_tinyppi"),
        duration=addon.getSettingInt("splash_duration"),
        modes=modes,
    )


def _mode_colors(home, mode: str) -> dict[str, str]:
    """Return *mode*'s tints from the Home properties, with fallbacks.

    Call after ``apply_theme``.
    """
    prefix = _MODE_PROP_PREFIX[mode]
    fallback = {
        "bg":          _BG_COLOR,
        "video":       _LOGO_COLOR,
        "audio":       _LOGO_COLOR,
        "divider":     _DIVIDER_COLOR,
        "convert_dot": _CONVERT_DOT_COLOR,
        **_LAYER_COLOR_FALLBACK,
    }
    return {
        key: home.getProperty(prefix + _COLOR_PROP_SUFFIX[key]) or fallback[key]
        for key in _COLOR_PROP_SUFFIX
    }


def _mode_scale(addon, mode: str) -> float:
    """Return *mode*'s size multiplier, clamped to 0.8-1.3."""
    try:
        percent = addon.getSettingInt(_SCALE_SETTINGS[mode])
    except Exception:
        return 1.0
    return min(1.3, max(0.8, percent / 100.0))


def _home_prop_condition(prop: str, expected: bool = True) -> str:
    """Return a condition testing Home property *prop* for true (or not)."""
    condition = f"String.IsEqual(Window({HOME_WINDOW_ID}).Property({prop}),true)"
    return condition if expected else f"!{condition}"


def _visible_condition(mode: str, suppress_start_for_osd: bool = False,
                       run: str = "") -> str:
    """Return the visibility condition of *mode*'s controls.

    Tied to the controller *run* (see ``PROP_SPLASH_RUN``).
    """
    parts = [
        _VISIBLE_CONDITION,
        _home_prop_condition(_MODE_VISIBLE_PROPS[mode]),
    ]
    if run:
        parts.append(
            f"String.IsEqual(Window({HOME_WINDOW_ID}).Property({PROP_SPLASH_RUN}),{run})"
        )
    if mode == "start":
        parts.extend((
            _home_prop_condition(PROP_RUNNING, False),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
        if suppress_start_for_osd:
            parts.append("!Window.IsVisible(videoosd)")
    elif mode == "osd":
        parts.extend((
            "Window.IsVisible(videoosd)",
            _home_prop_condition(PROP_RUNNING, False),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
    elif mode == "tinyppi":
        parts.extend((
            _home_prop_condition(PROP_ACTIVE),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
    return " + ".join(parts)


def _clear_mode_visibility(home, mode: str | None = None) -> None:
    """Clear *mode*'s visibility property, or all of them."""
    props = (_MODE_VISIBLE_PROPS[mode],) if mode else _MODE_VISIBLE_PROPS.values()
    for prop in props:
        home.clearProperty(prop)


def _fade_in(
    video_window, home, monitor, mode: str, controls, condition: str,
    dot=None,
) -> None:
    """Add *controls* to the video window and fade them in.

    All controls get *condition*; the badge *dot* also requires
    ``PROP_CONVERTING``.  The order matters (otherwise the logos pop or
    flash): hide, add, bind conditions, wait a render tick, arm animations
    and unhide, then set the property that plays the fade.
    """
    dot_condition = condition + " + " + _home_prop_condition(PROP_CONVERTING)
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    for control in controls:
        control.setVisible(False)
    video_window.addControls(controls)
    for control in controls:
        control.setVisibleCondition(
            dot_condition if control is dot else condition, False
        )
    monitor.waitForAbort(_RENDER_TICK)
    for control in controls:
        control.setAnimations([_ANIM_IN, _ANIM_OUT])
    for control in controls:
        control.setVisible(True)
    monitor.waitForAbort(_RENDER_TICK)
    home.setProperty(PROP_SPLASH_VISIBLE, "true")
    home.setProperty(_MODE_VISIBLE_PROPS[mode], "true")


def _remove_controls(video_window, controls) -> None:
    """Remove *controls* from the video window, ignoring failures."""
    try:
        video_window.removeControls(controls)
    except Exception:
        # The window may already be gone.
        pass


def _fade_out(video_window, home, monitor, mode: str, controls) -> None:
    """Fade *controls* out, wait, and remove them.

    Not removed while Kodi stops the service: removal waits on the GUI
    thread, which no longer answers then (see open_splash's cleanup).
    """
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    if monitor.waitForAbort(_FADE_OUT_SECONDS):
        return
    _remove_controls(video_window, controls)


def _safe_addon():
    """Return the current settings handle, or None while unavailable.

    During an add-on update ``Addon()`` may raise ``RuntimeError`` or load
    without settings (``TypeError`` on read), so one read verifies it.
    """
    try:
        addon = settings.addon()
        addon.getSettingBool("splash_enabled")
        return addon
    except (RuntimeError, TypeError):
        return None


def open_splash() -> None:
    """Run the splash controller for the current video.

    Each poll prepares the enabled modes; Kodi's visibility conditions start
    the fades.  Controls are rebuilt on offset, scale, colour or format
    changes.  Returns at once when all modes are off, no video plays, or
    another controller runs.
    """
    addon = _safe_addon()
    if addon is None:
        return
    config = _read_settings(addon)
    if not (config.show_on_start or config.show_on_osd or config.show_on_tinyppi):
        return

    player = xbmc.Player()
    if not player.isPlayingVideo():
        return

    home = xbmcgui.Window(HOME_WINDOW_ID)
    if home.getProperty(PROP_SPLASH_ACTIVE) == "true":
        return

    gamut = info("Player.Process(amlogic.eoft_gamut)")
    logos = _current_logos(_amlogic_hdr_token(gamut))
    has_audio = _has_audio(player)
    enabled_modes = [
        mode for mode, on in (
            ("start", config.show_on_start), ("osd", config.show_on_osd),
            ("tinyppi", config.show_on_tinyppi),
        ) if on
    ]
    if not any(_mode_logos(config.modes[mode], logos, has_audio)
               for mode in enabled_modes):
        return

    video_window = xbmcgui.Window(WINDOW_FULLSCREEN_VIDEO)
    screen_w, screen_h = _window_dims(video_window)
    monitor = xbmc.Monitor()

    home.setProperty(PROP_SPLASH_ACTIVE, "true")
    run = f"{os.getpid()}-{time.monotonic_ns()}"
    home.setProperty(PROP_SPLASH_RUN, run)
    home.clearProperty(PROP_SPLASH_VISIBLE)
    _clear_mode_visibility(home)
    controls_by_mode: dict[str, list[xbmcgui.ControlImage]] = {}
    states: dict[str, _ModeState] = {}
    # Handle ``config`` came from, and whether the theme was published since.
    read_from = addon
    themed = False
    colors_by_mode: dict[str, dict[str, str]] = {}
    # Source format and layer, the output they were read for, the next
    # re-read, and the published badge state.
    hdr_type = el_type = ""
    format_gamut = None
    format_due = 0.0
    converting = None
    # When the logos were first drawn (start of the start window); None
    # while the output settles.
    started = None
    waiting_since = time.monotonic()
    settle_gamut = None
    settle_since = waiting_since
    try:
        while not monitor.abortRequested():
            if not player.isPlayingVideo():
                break

            # A new handle means changed settings; None during an update.
            addon = _safe_addon()
            if addon is None:
                break
            if addon is not read_from:
                read_from = addon
                config = _read_settings(addon)
                themed = False
            show_on_start = config.show_on_start
            show_on_osd = config.show_on_osd
            show_on_tinyppi = config.show_on_tinyppi
            duration = config.duration

            now = time.monotonic()
            in_fullscreen = xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
            in_start_window = show_on_start and (
                started is None or now - started < duration)

            # Read once for badge, pill and logos.
            gamut = info("Player.Process(amlogic.eoft_gamut)")
            hdr_token = _amlogic_hdr_token(gamut)
            # Reading the format parses side data, so it is re-read once a
            # second, when the output changes, or every poll until known.  The
            # audio-track check (player lock) uses the same schedule.
            if not hdr_type or gamut != format_gamut or now >= format_due:
                hdr_type = get_hdr_format()
                el_type = get_dv_el_type_raw() if "dolby" in hdr_type else ""
                has_audio = _has_audio(player)
                format_gamut = gamut
                format_due = now + _FORMAT_INTERVAL

            # Updated every poll; the badge's condition follows it.
            now_converting = "true" if _is_converting(hdr_type, gamut) else "false"
            if now_converting != converting:
                converting = now_converting
                home.setProperty(PROP_CONVERTING, converting)

            if started is None:
                # Wait for the output to settle before drawing.
                if gamut != settle_gamut:
                    settle_gamut, settle_since = gamut, now
                switching = bool(hdr_type) and not hdr_token
                if (now - settle_since < _SETTLE_SECONDS
                        or (switching and now - waiting_since < _SETTLE_SDR_LIMIT)):
                    if monitor.waitForAbort(_POLL_INTERVAL):
                        break
                    continue
                started = now
                _log(f"output settled after {now - waiting_since:.1f}s at "
                     f"{gamut!r}, source {hdr_type or 'sdr'!r}")

            desired_states: dict[str, _ModeState] = {}
            if in_fullscreen:
                logos = _current_logos(hdr_token)
                modes = []
                if show_on_start and in_start_window:
                    modes.append("start")
                if show_on_osd:
                    modes.append("osd")
                if show_on_tinyppi:
                    modes.append("tinyppi")

                if modes:
                    # Publish the theme once per settings change, then read
                    # each context's tints back.
                    if not themed:
                        apply_theme(home, addon)
                        colors_by_mode = {
                            mode: _mode_colors(home, mode)
                            for mode in _MODE_PROP_PREFIX
                        }
                        themed = True
                    layer_token = _dv_layer_token(hdr_token, hdr_type, el_type)
                    for mode in modes:
                        # A mode without logos draws nothing this poll.
                        mode_settings = config.modes[mode]
                        mode_logos = _mode_logos(mode_settings, logos, has_audio)
                        if not mode_logos:
                            continue
                        colors = colors_by_mode[mode]
                        desired_states[mode] = _ModeState(
                            logos=mode_logos,
                            offset_x=mode_settings.offset_x,
                            offset_y=mode_settings.offset_y,
                            scale=mode_settings.scale,
                            colors=tuple(sorted(colors.items())),
                            condition=_visible_condition(mode, show_on_osd, run),
                            layer_token=layer_token,
                            pill_at_top=mode_settings.pill_at_top,
                        )

            remove_modes = [
                mode for mode in tuple(controls_by_mode)
                if mode not in desired_states
            ]
            if remove_modes:
                for mode in remove_modes:
                    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
                if monitor.waitForAbort(_FADE_OUT_SECONDS):
                    break
                for mode in remove_modes:
                    _remove_controls(video_window, controls_by_mode[mode])
                    controls_by_mode.pop(mode, None)
                    states.pop(mode, None)

            for mode, desired in desired_states.items():
                # Adding controls waits on the GUI thread, so nothing is
                # drawn while Kodi stops the service.
                if monitor.abortRequested():
                    break
                if states.get(mode) == desired:
                    continue
                if mode in controls_by_mode:
                    _log(f"{mode} redrawn for output {gamut!r}, source "
                         f"{hdr_type or 'sdr'!r}")
                    _fade_out(video_window, home, monitor, mode, controls_by_mode[mode])
                    if monitor.abortRequested():
                        break
                controls, dot = _build_controls(
                    list(desired.logos), colors_by_mode[mode],
                    desired.offset_x, desired.offset_y,
                    screen_w, screen_h, desired.scale, desired.layer_token,
                    desired.pill_at_top,
                )
                controls_by_mode[mode] = controls
                states[mode] = desired
                _fade_in(
                    video_window, home, monitor, mode, controls,
                    desired.condition, dot,
                )

            if not show_on_osd and not show_on_tinyppi and not in_start_window and not states:
                break

            wait_time = _POLL_INTERVAL
            if show_on_start and in_start_window:
                remaining = duration - (time.monotonic() - started)
                if remaining > 0:
                    wait_time = min(wait_time, remaining)

            if monitor.waitForAbort(wait_time):
                break
    except TypeError:
        # Settings vanished mid-poll (add-on update); clean up and leave.
        pass
    finally:
        # Properties first: they hide the logos and free the guard without
        # waiting on the GUI thread.  Removing controls waits on it, and while
        # Kodi stops the service (update, add-on disabled) that wait ends in
        # SystemExit, which used to leave the guard set until a restart.  On
        # abort the controls stay, hidden for good by the run token.
        home.clearProperty(PROP_SPLASH_VISIBLE)
        _clear_mode_visibility(home)
        home.clearProperty(PROP_CONVERTING)
        home.clearProperty(PROP_SPLASH_RUN)
        home.clearProperty(PROP_SPLASH_ACTIVE)
        if not monitor.abortRequested():
            for controls in controls_by_mode.values():
                _remove_controls(video_window, controls)
