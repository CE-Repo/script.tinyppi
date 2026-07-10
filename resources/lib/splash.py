"""
splash.py – Start-up / OSD format-logo overlay for TinyPPI.

When playback of a video begins (``Player.OnAVStart``), the background service
(monitor.py) launches this module through ``RunScript(script.tinyppi,splash)``.
It shows two logos stacked in a corner of the picture – the HDR/video format on
top and the audio format below it – for the current stream.  Two independent
triggers, each toggled from the add-on settings, decide when they are visible:

* ``splash_enabled``         – show them for the first ``splash_duration``
                               seconds after playback starts.
* ``splash_show_on_osd``     – show them whenever the video OSD is open.
* ``splash_show_on_tinyppi`` – show them while the TinyPPI info overlay is open.

The logos are added as ``ControlImage`` controls directly to Kodi's fullscreen
video window (id 12005) and toggled through a visibility condition bound to a
Home-window property (see ``_fade_in`` / ``_fade_out``).  A modeless dialog
would sit on top of the dialog stack and swallow remote input, which prevents
the video OSD from opening; drawing straight onto the video window leaves all
playback controls fully usable while the logos are visible.

The controller re-resolves the logos every poll, so switching the audio track
mid-playback rebuilds the images and the audio logo follows the change.
"""

import os
import time

import xbmc
import xbmcaddon
import xbmcgui

from maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP
from theme import apply_theme
from utils import PROP_DIALOG_MODE, PROP_RUNNING, info

_ADDON      = xbmcaddon.Addon()
_MEDIA_PATH = os.path.join(
    _ADDON.getAddonInfo("path"), "resources", "skins", "Default", "media"
)

# Kodi window ids / Home-window guard property.
WINDOW_FULLSCREEN_VIDEO = 12005
_HOME_WINDOW_ID         = 10000

# Re-entry guard so overlapping playback starts cannot stack two controllers; it
# lives on the Home window because each RunScript call is a separate process.
PROP_SPLASH_ACTIVE = "TinyPPI.SplashActive"

# ControlImage aspect-ratio modes: keep (letterboxed / centred within the box)
# for the logos, stretch (fill the box) for the background panel pieces.
_ASPECT_KEEP    = 2
_ASPECT_STRETCH = 0

# Background panel: a rounded rectangle assembled as a 9-slice from a solid
# 1x1 fill and four pre-rendered rounded-corner masks, all tinted to the same
# ARGB colour so the corners stay crisp at any size.  A faint divider separates
# the two stacked logos, mirroring the reference look.
_BG_TEXTURE     = os.path.join("common", "dot-1x1.png")
_DIVIDER_COLOR  = "59FFFFFF"
_CORNER_TEXTURES = {
    "tl": os.path.join("splash", "corner-tl.png"),
    "tr": os.path.join("splash", "corner-tr.png"),
    "bl": os.path.join("splash", "corner-bl.png"),
    "br": os.path.join("splash", "corner-br.png"),
}

# Fallback ARGB colours used only when the themed Home-window properties have
# not been published yet (they normally come from apply_theme / the settings).
_BG_COLOR   = "FA15181A"  # Charcoal panel (matches the overlay background)
_LOGO_COLOR = "FFEDEDED"  # near-white (leaves white logos unchanged)

# Home-window properties published by theme.apply_theme for the splash colours.
_PROP_BG_COLOR      = "TinyPPI.SplashBackgroundColor"
_PROP_VIDEO_COLOR   = "TinyPPI.SplashVideoColor"
_PROP_AUDIO_COLOR   = "TinyPPI.SplashAudioColor"
_PROP_DIVIDER_COLOR = "TinyPPI.SplashDividerColor"

# Controller poll interval (seconds); fast enough to track OSD open/close and
# audio-track changes.
_POLL_INTERVAL = 0.25

# Fade in/out so the logos appear and disappear softly instead of popping.
# Kodi only plays "Visible" / "Hidden" animations on runtime-added controls
# when a *visibility condition* changes its value — imperative setVisible()
# flips the state without a condition change and the animations never run.
# The controls therefore watch a Home-window property through
# setVisibleCondition(); _fade_in / _fade_out drive the fades by toggling it.
PROP_SPLASH_VISIBLE = "TinyPPI.SplashVisible"
_VISIBLE_CONDITION  = (
    f"String.IsEqual(Window({_HOME_WINDOW_ID}).Property({PROP_SPLASH_VISIBLE}),true)"
)
_FADE_IN_MS       = 350
_FADE_OUT_MS      = 150
_FADE_OUT_SECONDS = (_FADE_OUT_MS + 60) / 1000.0  # wait a touch past the fade
_RENDER_TICK      = 0.05  # one render frame, so Kodi settles a state change
_ANIM_IN  = ("Visible",
             f"effect=fade start=0 end=100 time={_FADE_IN_MS} tween=cubic easing=inout")
_ANIM_OUT = ("Hidden",
             f"effect=fade start=100 end=0 time={_FADE_OUT_MS}")

# Each display mode has its own horizontal / vertical offset settings so the
# logos can sit in a different spot for each trigger.  When several modes are
# active at once the priority is TinyPPI overlay > OSD > start-up window.
_OFFSET_SETTINGS = {
    "start":   ("splash_start_offset_x",   "splash_start_offset_y"),
    "osd":     ("splash_osd_offset_x",     "splash_osd_offset_y"),
    "tinyppi": ("splash_tinyppi_offset_x", "splash_tinyppi_offset_y"),
}

# Each display mode also has its own size multiplier (stored as 80–130 %, default
# 100 %) so the logo block can be scaled independently per trigger.  The value
# multiplies the base layout scale below; the offsets are computed from the
# resulting panel size, so scaling and positioning stay independent.
_SCALE_SETTINGS = {
    "start":   "splash_start_scale",
    "osd":     "splash_osd_scale",
    "tinyppi": "splash_tinyppi_scale",
}

# Base layout scale for the logo block; the per-mode user scale multiplies it, so
# a user value of 1.0 reproduces the original out-of-the-box size.
_BASE_SCALE = 0.95


def _amlogic_hdr_token() -> str:
    """Classify the Amlogic hardware output mode into an ``HDR_LOGO_MAP`` key.

    ``Player.Process(amlogic.eoft_gamut)`` reports the display's actual output
    signalling; its first token is the mode, e.g. ``SDR``, ``HDR10``, ``HDR10+``,
    ``HLG`` or ``DV-Std`` / ``DV-LL`` for Dolby Vision.  Returns the matching map
    key (``''`` for SDR / unknown, so it falls back to the SDR logo).  ``HDR10+``
    is checked before ``HDR10`` because it also contains ``HDR10``.
    """
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
    """Return the logos to stack, top to bottom: HDR/video first, audio below.

    Both logos must be available, otherwise nothing is shown: an empty list is
    returned unless the current stream resolves to a video *and* an audio logo.
    The video (HDR) logo falls back to the SDR logo for an unknown Amlogic output
    mode, so in practice this gates on the audio codec having a logo.
    """
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    audio_logo = AUDIO_LOGO_MAP.get(codec, "")

    video_logo = HDR_LOGO_MAP.get(_amlogic_hdr_token(), HDR_LOGO_MAP[""])

    if not audio_logo or not video_logo:
        return []
    return [video_logo, audio_logo]


def _make_image(rel_path: str, x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Build a keep-aspect, tinted ``ControlImage`` from a media-relative path."""
    full_path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
    return xbmcgui.ControlImage(
        x, y, w, h, full_path, aspectRatio=_ASPECT_KEEP, colorDiffuse=color,
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

    Sizes are fractions of the window's coordinate space (``screen_w`` /
    ``screen_h``) so the placement holds up across skins designed at 720p or
    1080p.  ``offset_x`` / ``offset_y`` (0–100 %) slide the whole block along the
    free horizontal / vertical travel: 0 % keeps a corner inset at the top-left,
    100 % moves it flush into the bottom-right corner.  ``user_scale`` (0.1–1.2)
    resizes the whole block; because the offsets are derived from the resulting
    panel size, scaling and positioning stay independent.  A rounded panel is
    drawn behind the stack (first in the list, so it renders underneath the
    logos); its and the divider's visibility are controlled purely by their
    themed opacity.  ``colors`` supplies the themed ARGB tints keyed by ``bg`` /
    ``video`` / ``audio`` / ``divider``.
    """
    if not logos:
        return []

    # Overall size multiplier for the logo block (panel, logos, gaps, radius):
    # the base layout scale times the user-configured per-mode multiplier.
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

    # Slide the whole panel across the screen.  A corner inset is kept at the
    # 0 % (top / left) end, and a smaller gap is kept from the edge at the 100 %
    # (bottom / right) end so it never sits perfectly flush.  Both anchors carry
    # an extra 5 px so neither extreme sits too close to the edge.
    inset = int(screen_h * 0.0325)
    edge  = 35
    offset_x = min(100, max(0, offset_x))
    offset_y = min(100, max(0, offset_y))
    panel_x = inset + max(0, screen_w - panel_w - inset - edge) * offset_x // 100
    panel_y = inset + max(0, screen_h - panel_h - inset - edge) * offset_y // 100
    block_x = panel_x + pad_x
    top     = panel_y + pad_y

    controls: list[xbmcgui.ControlImage] = []

    # Rounded background panel (drawn first, so it sits behind the logos) plus a
    # divider between the two stacked logos.  Both are always present; hide them
    # by setting their themed opacity to 0.
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
    """Return the coordinate-space size that ``addControl`` uses on *window*.

    ``Window.getWidth()`` / ``getHeight()`` report the window's own coordinate
    system, which is what added controls are positioned in — unlike the global
    ``getScreenWidth`` / ``getScreenHeight`` that can differ from it on some
    skins / render resolutions and would then misplace the 100 % (edge) anchor.
    Falls back to the screen size if the window does not report usable values.
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


def _read_colors(home, addon) -> dict[str, str]:
    """Publish the themed colours and read the splash tints back off *home*."""
    apply_theme(home, addon)
    return {
        "bg":      home.getProperty(_PROP_BG_COLOR) or _BG_COLOR,
        "video":   home.getProperty(_PROP_VIDEO_COLOR) or _LOGO_COLOR,
        "audio":   home.getProperty(_PROP_AUDIO_COLOR) or _LOGO_COLOR,
        "divider": home.getProperty(_PROP_DIVIDER_COLOR) or _DIVIDER_COLOR,
    }


def _mode_scale(addon, mode: str) -> float:
    """Return the configured size multiplier for *mode*, clamped to 0.8–1.3.

    The setting is stored as a whole percentage (80–130, i.e. 80 %–130 %); it is
    divided by 100 to yield the layout multiplier (a 1 % step = 0.01).
    """
    try:
        percent = addon.getSettingInt(_SCALE_SETTINGS[mode])
    except Exception:
        return 1.0
    return min(1.3, max(0.8, percent / 100.0))


def _fade_in(video_window, home, monitor, controls) -> None:
    """Add *controls* to the video window and fade them in.

    The ordering is load-bearing; deviating makes the logos pop or flash:

    1. Force-hide every control *before* adding it (since Kodi 19 the state is
       stored and applied when the control is created).  Freshly added controls
       are otherwise visible until their condition is first evaluated, which
       renders them at full opacity for a few frames — and because the ~11
       panel pieces get their conditions bound one by one, they also wink out
       staggered.  Pre-hiding keeps everything unrendered until the final flip.
    2. Bind the visibility condition with the property cleared and *before*
       arming any animation, so the initial visible→hidden condition edge
       cannot play a "Hidden" fade.
    3. Wait one render tick so Kodi settles the hidden state.
    4. Arm the animations (only possible once the controls belong to a window;
       arming beforehand is silently dropped), then lift the force-hide — the
       condition is still false, so the controls stay invisible.
    5. Wait another tick, then flip the property false→true — the condition
       change plays the "Visible" fade from fully transparent.
    """
    home.clearProperty(PROP_SPLASH_VISIBLE)
    for control in controls:
        control.setVisible(False)
    video_window.addControls(controls)
    for control in controls:
        control.setVisibleCondition(_VISIBLE_CONDITION, False)
    monitor.waitForAbort(_RENDER_TICK)
    for control in controls:
        control.setAnimations([_ANIM_IN, _ANIM_OUT])
    for control in controls:
        control.setVisible(True)
    monitor.waitForAbort(_RENDER_TICK)
    home.setProperty(PROP_SPLASH_VISIBLE, "true")


def _fade_out(video_window, home, monitor, controls) -> None:
    """Fade *controls* out (condition true→false), await it, remove them."""
    home.clearProperty(PROP_SPLASH_VISIBLE)
    monitor.waitForAbort(_FADE_OUT_SECONDS)
    try:
        video_window.removeControls(controls)
    except Exception:
        # The video window may already be gone (playback stopped); the
        # controls are torn down with it, so a failed removal is harmless.
        pass


def open_splash() -> None:
    """Run the logo overlay controller for the lifetime of the current video.

    Each poll picks the active display mode (TinyPPI overlay > OSD > start-up
    window), draws the logos at that mode's own offset, and tears them down when
    no mode is active — rebuilding on mode / offset / format changes until
    playback ends.  Skips silently when all triggers are disabled, when no video
    is playing, or when another controller is running.
    """
    show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(xbmcaddon.Addon())
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
    controls: list[xbmcgui.ControlImage] = []
    state: tuple | None = None  # (logos, offset_x, offset_y, scale, colours) shown
    try:
        started = time.monotonic()
        while not monitor.abortRequested():
            if not player.isPlayingVideo():
                break

            # Read every setting from a *fresh* Addon() each poll.  An Addon
            # instance caches its settings at construction, so the long-lived
            # module-level _ADDON keeps returning the values from when the splash
            # process started (i.e. from playback start).  A new instance reloads
            # the current values, so edits made in the settings apply live without
            # restarting playback.
            addon = xbmcaddon.Addon()
            show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(addon)
            duration = addon.getSettingInt("splash_duration")

            in_fullscreen = xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
            in_start_window = show_on_start and (time.monotonic() - started < duration)

            # End a start-only splash once its window has passed; the OSD and
            # TinyPPI triggers keep the controller alive for the whole film.
            if not show_on_osd and not show_on_tinyppi and not in_start_window:
                break

            # The VS10 mode-select dialog also sets TinyPPI.Running, but codec
            # logos must never appear over it, so DialogMode suppresses them.
            dialog_open  = home.getProperty(PROP_DIALOG_MODE) == "true"
            overlay_open = home.getProperty(PROP_RUNNING) == "true"

            # Pick the active display mode (priority: TinyPPI > OSD > start).
            # Inside the TinyPPI overlay the logos are suppressed unless enabled
            # for it, matching the previous behaviour.
            if dialog_open:
                mode = None
            elif overlay_open:
                mode = "tinyppi" if show_on_tinyppi else None
            elif show_on_osd and xbmc.getCondVisibility("Window.IsVisible(videoosd)"):
                mode = "osd"
            elif in_start_window:
                mode = "start"
            else:
                mode = None

            # The logos live on the fullscreen video window; while the user is in
            # a menu they are torn down and rebuilt again on return.  The build
            # carries the active mode's own offset, scale and colours, so any of
            # those changing (or a mode / audio-track change) simply rebuilds at
            # the new position / size / tint.
            desired = None
            colors = None
            if mode and in_fullscreen:
                logos = _current_logos()
                if logos:
                    colors = _read_colors(home, addon)
                    setting_x, setting_y = _OFFSET_SETTINGS[mode]
                    desired = (
                        tuple(logos),
                        addon.getSettingInt(setting_x),
                        addon.getSettingInt(setting_y),
                        _mode_scale(addon, mode),
                        tuple(sorted(colors.items())),
                    )

            if desired != state:
                if controls:
                    _fade_out(video_window, home, monitor, controls)
                    controls = []
                state = desired
                if desired:
                    controls = _build_controls(
                        list(desired[0]), colors, desired[1], desired[2],
                        screen_w, screen_h, desired[3],
                    )
                    _fade_in(video_window, home, monitor, controls)

            if monitor.waitForAbort(_POLL_INTERVAL):
                break
    finally:
        if controls:
            try:
                video_window.removeControls(controls)
            except Exception:
                # The video window may already be gone (playback stopped); the
                # controls are torn down with it, so a failed removal is harmless.
                pass
        home.clearProperty(PROP_SPLASH_VISIBLE)
        home.clearProperty(PROP_SPLASH_ACTIVE)
