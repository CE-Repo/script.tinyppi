"""Start-up / OSD format-logo overlay.

On ``Player.OnAVStart`` the service (monitor.py) launches this via
``RunScript(script.tinyppi,splash)``.  It stacks two logos in a corner – the
HDR/video format on top, the audio format below.  Three settings triggers decide
when they show: ``splash_enabled`` (first ``splash_duration`` seconds),
``splash_show_on_osd`` (while the video OSD is open) and ``splash_show_on_tinyppi``
(while the TinyPPI overlay is open).

Logos are added as ``ControlImage`` controls directly onto the fullscreen video
window (12005) and toggled via a visibility condition (see ``_fade_in`` /
``_fade_out``); drawing straight onto the video window keeps playback controls
usable, unlike a modeless dialog.  Logos are re-resolved every poll, so an
audio-track change follows live.
"""

import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from core.images import display_texture
from core.maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP
from core.utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_RUNNING, info
from ui.theme import apply_theme

_ADDON      = xbmcaddon.Addon()
_MEDIA_PATH = os.path.join(
    _ADDON.getAddonInfo("path"), "resources", "skins", "Default", "media"
)

# Kodi window ids / Home-window guard property.
WINDOW_FULLSCREEN_VIDEO = 12005
_HOME_WINDOW_ID         = 10000

# Re-entry guard so overlapping playback starts cannot stack two controllers;
# on the Home window because each RunScript call is a separate process.
PROP_SPLASH_ACTIVE = "TinyPPI.SplashActive"

# ControlImage aspect-ratio modes: keep for the logos, stretch for the panel.
_ASPECT_KEEP    = 2
_ASPECT_STRETCH = 0

# Background panel: a rounded rectangle assembled 9-slice from a 1x1 fill and
# four rounded-corner masks, all tinted the same ARGB colour.
_BG_TEXTURE     = os.path.join("common", "dot-1x1.png")
_DIVIDER_COLOR  = "59FFFFFF"
_CORNER_TEXTURES = {
    "tl": os.path.join("splash", "corner-tl.png"),
    "tr": os.path.join("splash", "corner-tr.png"),
    "bl": os.path.join("splash", "corner-bl.png"),
    "br": os.path.join("splash", "corner-br.png"),
}

# Fallback ARGB colours used only before theme.apply_theme has published the
# themed Home-window properties.
_BG_COLOR   = "FA15181A"  # Charcoal panel (matches the overlay background)
_LOGO_COLOR = "FFEDEDED"  # near-white (leaves white logos unchanged)

# Home-window properties published by theme.apply_theme for the splash colours.
# Each context (start / osd / tinyppi) has its own bg / video / audio / divider
# tint, so a colour change in one context does not touch the others.
_MODE_PROP_PREFIX = {
    "start":   "TinyPPI.SplashStart",
    "osd":     "TinyPPI.SplashOsd",
    "tinyppi": "TinyPPI.SplashTinyppi",
}
_COLOR_PROP_SUFFIX = {
    "bg":      "BgColor",
    "video":   "VideoColor",
    "audio":   "AudioColor",
    "divider": "DividerColor",
}

# Controller poll interval (seconds).
_POLL_INTERVAL = 0.25

# Fade in/out.  Kodi only plays "Visible"/"Hidden" animations on runtime-added
# controls when a *visibility condition* changes value (setVisible() alone does
# not), so the controls watch a global guard plus a per-mode Home-window
# property.  External conditions (VideoOSD / TinyPPI state) can then start the
# fades immediately once the controls have been preloaded.
PROP_SPLASH_VISIBLE = "TinyPPI.SplashVisible"
_VISIBLE_CONDITION  = (
    f"String.IsEqual(Window({_HOME_WINDOW_ID}).Property({PROP_SPLASH_VISIBLE}),true)"
)
_MODE_VISIBLE_PROPS = {
    "start":   "TinyPPI.SplashStartVisible",
    "osd":     "TinyPPI.SplashOsdVisible",
    "tinyppi": "TinyPPI.SplashTinyPPIVisible",
}
_FADE_IN_MS       = 350
_FADE_OUT_MS      = 150
_FADE_OUT_SECONDS = (_FADE_OUT_MS + 60) / 1000.0  # wait a touch past the fade
_RENDER_TICK      = 0.05  # one render frame, so Kodi settles a state change
_ANIM_IN  = ("Visible",
             f"effect=fade start=0 end=100 time={_FADE_IN_MS} tween=cubic easing=inout")
_ANIM_OUT = ("Hidden",
             f"effect=fade start=100 end=0 time={_FADE_OUT_MS}")

# Per-mode horizontal / vertical offset settings (priority when several are
# active: TinyPPI overlay > OSD > start-up window).
_OFFSET_SETTINGS = {
    "start":   ("splash_start_offset_x",   "splash_start_offset_y"),
    "osd":     ("splash_osd_offset_x",     "splash_osd_offset_y"),
    "tinyppi": ("splash_tinyppi_offset_x", "splash_tinyppi_offset_y"),
}

# Per-mode size multiplier (stored 80–130 %, default 100 %); multiplies the base
# layout scale below.
_SCALE_SETTINGS = {
    "start":   "splash_start_scale",
    "osd":     "splash_osd_scale",
    "tinyppi": "splash_tinyppi_scale",
}

# Base layout scale for the logo block; a user scale of 1.0 keeps the original size.
_BASE_SCALE = 0.95

def _amlogic_hdr_token() -> str:
    """Classify the Amlogic output mode (``amlogic.eoft_gamut``) into an
    ``HDR_LOGO_MAP`` key (``''`` for SDR / unknown)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
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


def _current_logos() -> list[str]:
    """Return [video, audio] logos to stack, or [] unless both are available.
    The video logo falls back to SDR, so this effectively gates on the audio codec."""
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    audio_logo = AUDIO_LOGO_MAP.get(codec, "")

    video_logo = HDR_LOGO_MAP.get(_amlogic_hdr_token(), HDR_LOGO_MAP[""])

    if not audio_logo or not video_logo:
        return []
    return [video_logo, audio_logo]


def _translate_path(path: str) -> str:
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


def _log_debug(message: str) -> None:
    try:
        xbmc.log(f"TinyPPI splash: {message}", xbmc.LOGDEBUG)
    except Exception:
        pass


def _make_image(rel_path: str, x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Build a keep-aspect, tinted ``ControlImage`` from a media-relative path."""
    full_path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
    texture = display_texture(full_path, w, h)
    return xbmcgui.ControlImage(
        x, y, w, h, texture, aspectRatio=_ASPECT_KEEP, colorDiffuse=color,
    )


def _solid(x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Return a stretched, solid-colour fill built from the 1x1 texture."""
    texture = os.path.join(_MEDIA_PATH, _BG_TEXTURE)
    return xbmcgui.ControlImage(
        x, y, max(1, w), max(1, h), texture,
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )


def _panel_controls(
    x: int, y: int, w: int, h: int, radius: int, color: str
) -> list[xbmcgui.ControlImage]:
    """Assemble a rounded rectangle from a centre fill, four edges and corners."""
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
    logos: list[str], colors: dict[str, str],
    offset_x: int, offset_y: int, screen_w: int, screen_h: int,
    user_scale: float = 1.0,
) -> list[xbmcgui.ControlImage]:
    """Lay out the logos as a vertical stack, sized to the skin.

    Sizes are fractions of the window's coordinate space so placement holds up
    across 720p / 1080p skins.  ``offset_x`` / ``offset_y`` (0–100 %) slide the
    block from a top-left inset (0 %) to the bottom-right corner (100 %);
    ``user_scale`` resizes it.  A rounded panel is drawn first (behind the
    logos); it and the divider are shown/hidden purely by their themed opacity.
    ``colors`` supplies the ARGB tints keyed by ``bg`` / ``video`` / ``audio`` /
    ``divider``.
    """
    if not logos:
        return []

    # Overall size multiplier: base layout scale times the per-mode user scale.
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

    # Slide the panel across the screen, keeping a corner inset at 0 % and a
    # smaller gap at 100 % so it never sits perfectly flush.
    inset = int(screen_h * 0.0325)
    edge  = 35
    offset_x = min(100, max(0, offset_x))
    offset_y = min(100, max(0, offset_y))
    panel_x = inset + max(0, screen_w - panel_w - inset - edge) * offset_x // 100
    panel_y = inset + max(0, screen_h - panel_h - inset - edge) * offset_y // 100
    block_x = panel_x + pad_x
    top     = panel_y + pad_y

    controls: list[xbmcgui.ControlImage] = []

    # Rounded background panel (behind the logos) plus a divider between them;
    # both are always present and hidden via their themed opacity.
    controls.extend(_panel_controls(
        block_x - pad_x, top - pad_y,
        box_w + 2 * pad_x, panel_h,
        radius, colors["bg"],
    ))
    if count == 2:
        div_h = max(1, int(screen_h * 0.0025 * scale))
        div_y = top + box_h + v_gap // 2 - div_h // 2
        controls.append(_solid(block_x, div_y, box_w, div_h, colors["divider"]))

    # Logos, top to bottom: video (HDR) first, then audio.
    logo_colors = (colors["video"], colors["audio"])
    for index, logo in enumerate(logos):
        y = top + index * (box_h + v_gap)
        controls.append(_make_image(logo, block_x, y, box_w, box_h, logo_colors[index]))
    return controls


def _window_dims(window) -> tuple[int, int]:
    """Return the coordinate-space size ``addControl`` uses on *window*.

    Uses ``Window.getWidth()`` / ``getHeight()`` (the system added controls are
    positioned in), which can differ from the global screen size; falls back to
    the screen size when the window reports no usable values.
    """
    try:
        width, height = window.getWidth(), window.getHeight()
    except Exception:
        width = height = 0
    if width >= 640 and height >= 480:
        return width, height
    return xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()


def _read_triggers(addon) -> tuple[bool, bool, bool]:
    """Return the ``(start, osd, tinyppi)`` trigger toggles from the settings."""
    return (
        addon.getSettingBool("splash_enabled"),
        addon.getSettingBool("splash_show_on_osd"),
        addon.getSettingBool("splash_show_on_tinyppi"),
    )


def _mode_colors(home, mode: str) -> dict[str, str]:
    """Read *mode*'s bg / video / audio / divider tints off *home*.

    Call after ``apply_theme`` has published the themed properties; falls back to
    the pre-theme defaults if a property is somehow missing.
    """
    prefix = _MODE_PROP_PREFIX[mode]
    fallback = {
        "bg":      _BG_COLOR,
        "video":   _LOGO_COLOR,
        "audio":   _LOGO_COLOR,
        "divider": _DIVIDER_COLOR,
    }
    return {
        key: home.getProperty(prefix + _COLOR_PROP_SUFFIX[key]) or fallback[key]
        for key in _COLOR_PROP_SUFFIX
    }


def _mode_scale(addon, mode: str) -> float:
    """Return the size multiplier for *mode* (setting stored as 80–130 %),
    clamped to 0.8–1.3."""
    try:
        percent = addon.getSettingInt(_SCALE_SETTINGS[mode])
    except Exception:
        return 1.0
    return min(1.3, max(0.8, percent / 100.0))


def _home_prop_condition(prop: str, expected: bool = True) -> str:
    """Return a Kodi visibility fragment for a true/false Home property."""
    condition = f"String.IsEqual(Window({_HOME_WINDOW_ID}).Property({prop}),true)"
    return condition if expected else f"!{condition}"


def _visible_condition(mode: str, suppress_start_for_osd: bool = False) -> str:
    """Return the Kodi visibility condition used by controls for *mode*."""
    parts = [
        _VISIBLE_CONDITION,
        _home_prop_condition(_MODE_VISIBLE_PROPS[mode]),
    ]
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
    """Clear one mode visibility property, or all mode properties."""
    props = (_MODE_VISIBLE_PROPS[mode],) if mode else _MODE_VISIBLE_PROPS.values()
    for prop in props:
        home.clearProperty(prop)


def _fade_in(video_window, home, monitor, mode: str, controls, condition: str) -> None:
    """Add *controls* to the video window and fade them in.

    The ordering is load-bearing (deviating makes the logos pop or flash):

    1. Force-hide every control *before* adding it, so freshly added controls
       don't flash at full opacity before their condition is first evaluated.
    2. Bind the visibility condition with the property cleared and before arming
       any animation, so the initial edge cannot play a "Hidden" fade.
    3. Wait one render tick to settle the hidden state.
    4. Arm the animations (only works once the controls belong to a window),
       then lift the force-hide — the condition is still false.
    5. Wait a tick, then flip the property false→true to play the "Visible" fade.
    """
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    for control in controls:
        control.setVisible(False)
    video_window.addControls(controls)
    for control in controls:
        control.setVisibleCondition(condition, False)
    monitor.waitForAbort(_RENDER_TICK)
    for control in controls:
        control.setAnimations([_ANIM_IN, _ANIM_OUT])
    for control in controls:
        control.setVisible(True)
    monitor.waitForAbort(_RENDER_TICK)
    home.setProperty(PROP_SPLASH_VISIBLE, "true")
    home.setProperty(_MODE_VISIBLE_PROPS[mode], "true")


def _remove_controls(video_window, controls) -> None:
    """Remove controls from the video window, ignoring already-closed windows."""
    try:
        video_window.removeControls(controls)
    except Exception:
        # The video window may already be gone; a failed removal is harmless.
        pass


def _fade_out(video_window, home, monitor, mode: str, controls) -> None:
    """Fade *controls* out (condition true→false), await it, remove them."""
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    monitor.waitForAbort(_FADE_OUT_SECONDS)
    _remove_controls(video_window, controls)


def _safe_addon():
    """Return a fresh Addon whose settings can be read, or None.

    Updating the addon during playback briefly deletes and re-registers
    ``script.tinyppi``.  An ``Addon()`` built in that window raises
    ``RuntimeError: Unknown addon id`` — but one built a moment later can be
    handed back with its settings definition not yet loaded, and every read off
    it then raises ``TypeError: Invalid setting type``.  Constructing is
    therefore not proof of a usable object; one read is.  The long-lived splash
    loop must tolerate both and exit quietly instead of crashing (which also
    leaks Kodi classes).
    """
    try:
        addon = xbmcaddon.Addon()
        addon.getSettingBool("splash_enabled")
        return addon
    except (RuntimeError, TypeError):
        return None


def open_splash() -> None:
    """Run the logo overlay controller for the current video's lifetime.

    Each poll prepares the enabled modes (start-up, VideoOSD, TinyPPI overlay)
    and lets Kodi's visibility conditions start the actual fades immediately.
    Rebuilds still happen on offset / scale / colour / format changes.  Skips
    silently when all triggers are off, no video plays, or another controller is
    running.
    """
    addon = _safe_addon()
    if addon is None:
        return
    show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(addon)
    if not show_on_start and not show_on_osd and not show_on_tinyppi:
        return

    player = xbmc.Player()
    if not player.isPlayingVideo():
        return

    home = xbmcgui.Window(_HOME_WINDOW_ID)
    if home.getProperty(PROP_SPLASH_ACTIVE) == "true":
        return

    if not _current_logos():
        return

    video_window = xbmcgui.Window(WINDOW_FULLSCREEN_VIDEO)
    screen_w, screen_h = _window_dims(video_window)
    monitor = xbmc.Monitor()

    home.setProperty(PROP_SPLASH_ACTIVE, "true")
    home.clearProperty(PROP_SPLASH_VISIBLE)
    _clear_mode_visibility(home)
    controls_by_mode: dict[str, list[xbmcgui.ControlImage]] = {}
    states: dict[str, tuple] = {}
    try:
        started = time.monotonic()
        while not monitor.abortRequested():
            if not player.isPlayingVideo():
                break

            # Read settings from a fresh Addon() each poll: an Addon caches its
            # settings at construction, so a new instance is needed to pick up
            # live edits without restarting playback.  While the addon is being
            # updated Kodi unregisters our id, so bail out cleanly if it's gone.
            addon = _safe_addon()
            if addon is None:
                break
            show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(addon)
            duration = addon.getSettingInt("splash_duration")

            now = time.monotonic()
            in_fullscreen = xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
            in_start_window = show_on_start and (now - started < duration)

            desired_states: dict[str, tuple] = {}
            colors_by_mode: dict[str, dict[str, str]] = {}
            if in_fullscreen:
                logos = _current_logos()
                if logos:
                    modes = []
                    if show_on_start and in_start_window:
                        modes.append("start")
                    if show_on_osd:
                        modes.append("osd")
                    if show_on_tinyppi:
                        modes.append("tinyppi")

                    if modes:
                        # Publish every themed colour once, then read each
                        # context's own tints back so they stay independent.
                        apply_theme(home, addon)
                        for mode in modes:
                            colors = _mode_colors(home, mode)
                            colors_by_mode[mode] = colors
                            setting_x, setting_y = _OFFSET_SETTINGS[mode]
                            desired_states[mode] = (
                                tuple(logos),
                                addon.getSettingInt(setting_x),
                                addon.getSettingInt(setting_y),
                                _mode_scale(addon, mode),
                                tuple(sorted(colors.items())),
                                _visible_condition(mode, show_on_osd),
                            )

            remove_modes = [
                mode for mode in tuple(controls_by_mode)
                if mode not in desired_states
            ]
            if remove_modes:
                for mode in remove_modes:
                    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
                monitor.waitForAbort(_FADE_OUT_SECONDS)
                for mode in remove_modes:
                    _remove_controls(video_window, controls_by_mode[mode])
                    controls_by_mode.pop(mode, None)
                    states.pop(mode, None)

            for mode, desired in desired_states.items():
                if states.get(mode) == desired:
                    continue
                if mode in controls_by_mode:
                    _fade_out(video_window, home, monitor, mode, controls_by_mode[mode])
                controls = _build_controls(
                    list(desired[0]), colors_by_mode[mode], desired[1], desired[2],
                    screen_w, screen_h, desired[3],
                )
                controls_by_mode[mode] = controls
                states[mode] = desired
                _fade_in(video_window, home, monitor, mode, controls, desired[5])

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
        # The settings went away mid-poll, between _safe_addon() proving them
        # readable and a later read here.  Same update window, same answer:
        # leave quietly, the finally below still tidies up.
        pass
    finally:
        for controls in controls_by_mode.values():
            _remove_controls(video_window, controls)
        home.clearProperty(PROP_SPLASH_VISIBLE)
        _clear_mode_visibility(home)
        home.clearProperty(PROP_SPLASH_ACTIVE)
