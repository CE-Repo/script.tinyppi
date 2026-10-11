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

import contextlib
import os
import time
from typing import NamedTuple

import xbmc
import xbmcaddon
import xbmcgui
from core import settings
from core.constants import HOME_WINDOW_ID
from core.log import channel
from core.protocols import PropertyTarget
from core.utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_RUNNING, info
from info.dvinfo import get_dv_el_type_raw, get_hdr_format
from info.properties import output_hdr_token
from ui.splash_logos import (
    current_logos,
    dv_layer_token,
    is_converting,
    video_has_audio,
)
from ui.splash_panel import build_controls, window_dims
from ui.splash_settings import ModeSettings, Settings, read_settings
from ui.theme import apply_theme

_log = channel("splash")

# Kodi window id of the fullscreen video window.
WINDOW_FULLSCREEN_VIDEO = 12005

# Re-entry guard against stacked controllers; a Home property because a
# RunScript call runs in another interpreter than the service's thread.
PROP_SPLASH_ACTIVE = "TinyPPI.SplashActive"

# Fallback colours until theme.apply_theme has published the themed ones.
_BG_COLOR          = "FA15181A"  # Charcoal panel (matches the overlay background)
_LOGO_COLOR        = "FFEDEDED"  # near-white (leaves white logos unchanged)
_DIVIDER_COLOR     = "59FFFFFF"
_CONVERT_DOT_COLOR = "FF81C784"  # palette Forest (the conversion badge)

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

    logos: tuple[tuple[str, str], ...]
    offset_x: int
    offset_y: int
    scale: float
    colors: tuple[tuple[str, str], ...]
    condition: str
    layer_token: str
    pill_at_top: bool


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

# The overlay's window.  The tinyppi logos wait for it to be visible, not
# just for PROP_ACTIVE (set before the dialog is built and filled), so both
# fade in together.
_OVERLAY_WINDOW = "script-tinyppi-main.xml"

# "true" while a conversion is active (see is_converting); part of the
# badge's condition, so it toggles without a rebuild.
PROP_CONVERTING = "TinyPPI.SplashConverting"


# Fallback DV pill colours per layer (FEL forest, MEL tangerine, other white).
_LAYER_COLOR_FALLBACK = {
    "fel":   "FF81C784",  # palette Forest
    "mel":   "FFFFB74D",  # palette Tangerine
    "other": _LOGO_COLOR,  # palette White
}


def _mode_logos(
    mode_settings: ModeSettings, logos: tuple[str, str],
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

    shown = ((video_logo, "video", show_video), (audio_logo, "audio", show_audio))
    stack = [(logo, key) for logo, key, show in shown if show and logo]
    if mode_settings.audio_first:
        stack.reverse()
    return tuple(stack)


def _mode_colors(home: PropertyTarget, mode: str) -> dict[str, str]:
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
            f"Window.IsVisible({_OVERLAY_WINDOW})",
        ))
    return " + ".join(parts)


def _clear_mode_visibility(home: PropertyTarget, mode: str | None = None) -> None:
    """Clear *mode*'s visibility property, or all of them."""
    props = (_MODE_VISIBLE_PROPS[mode],) if mode else _MODE_VISIBLE_PROPS.values()
    for prop in props:
        home.clearProperty(prop)


def _fade_in(
    video_window: xbmcgui.Window, home: PropertyTarget, monitor: xbmc.Monitor,
    mode: str, controls: list[xbmcgui.Control], condition: str,
    dot: xbmcgui.Control | None = None,
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


def _remove_controls(video_window: xbmcgui.Window, controls: list[xbmcgui.Control]) -> None:
    """Remove *controls* from the video window, ignoring failures."""
    # The window may already be gone.
    with contextlib.suppress(RuntimeError):
        video_window.removeControls(controls)


def _fade_out(video_window: xbmcgui.Window, home: PropertyTarget, monitor: xbmc.Monitor,
              mode: str, controls: list[xbmcgui.Control]) -> None:
    """Fade *controls* out, wait, and remove them.

    Not removed while Kodi stops the service: removal waits on the GUI
    thread, which no longer answers then (see open_splash's cleanup).
    """
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    if monitor.waitForAbort(_FADE_OUT_SECONDS):
        return
    _remove_controls(video_window, controls)


def _safe_addon() -> xbmcaddon.Addon | None:
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


def _active_modes(config: Settings, in_start_window: bool = True) -> list[str]:
    """Return the enabled modes in drawing order.

    The start mode counts only while *in_start_window*.
    """
    modes = []
    if config.show_on_start and in_start_window:
        modes.append("start")
    if config.show_on_osd:
        modes.append("osd")
    if config.show_on_tinyppi:
        modes.append("tinyppi")
    return modes


def _anything_to_show(config: Settings, player: xbmc.Player) -> bool:
    """Return whether any enabled mode has logos for the current video."""
    gamut = info("Player.Process(amlogic.eoft_gamut)")
    logos = current_logos(output_hdr_token(gamut))
    has_audio = video_has_audio(player)
    return any(_mode_logos(config.modes[mode], logos, has_audio)
               for mode in _active_modes(config))


class _Controller:
    """One controller run: the polls of ``open_splash`` and their state.

    Each poll prepares the enabled modes and redraws those whose
    ``_ModeState`` changed; ``open_splash`` sets up and cleans up around it.
    """

    def __init__(
        self, addon: xbmcaddon.Addon, config: Settings, player: xbmc.Player,
        home: xbmcgui.Window, video_window: xbmcgui.Window,
        screen: tuple[int, int], monitor: xbmc.Monitor, run: str,
    ) -> None:
        self.player       = player
        self.home         = home
        self.video_window = video_window
        self.screen_w, self.screen_h = screen
        self.monitor      = monitor
        self.run_token    = run
        self.controls_by_mode: dict[str, list[xbmcgui.ControlImage]] = {}
        self.states: dict[str, _ModeState] = {}
        # Handle ``config`` came from, and whether the theme was published since.
        self.addon  = addon
        self.config = config
        self.themed = False
        self.colors_by_mode: dict[str, dict[str, str]] = {}
        # Source format and layer, the output they were read for, the next
        # re-read, and the published badge state.
        self.hdr_type = self.el_type = ""
        self.has_audio = True
        self.format_gamut: str | None = None
        self.format_due = 0.0
        self.converting: str | None = None
        # When the logos were first drawn (start of the start window); None
        # while the output settles.
        self.started: float | None = None
        self.waiting_since = time.monotonic()
        self.settle_gamut: str | None = None
        self.settle_since = self.waiting_since

    def run(self) -> None:
        """Poll until playback, the settings or Kodi end the run."""
        while not self.monitor.abortRequested():
            if not self._poll():
                break

    def _poll(self) -> bool:
        """Run one poll and its wait; return False when the run ends."""
        if not self.player.isPlayingVideo():
            return False
        if not self._refresh_settings():
            return False

        now = time.monotonic()
        in_fullscreen = xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
        in_start_window = self._in_start_window(now)

        # Read once for badge, pill and logos.
        gamut = info("Player.Process(amlogic.eoft_gamut)")
        hdr_token = output_hdr_token(gamut)
        self._refresh_format(gamut, now)
        self._publish_converting(gamut)

        started = self.started
        if started is None:
            started = self._settle(gamut, hdr_token, now)
            if started is None:
                return not self.monitor.waitForAbort(_POLL_INTERVAL)

        desired_states = (
            self._desired_states(hdr_token, in_start_window) if in_fullscreen else {}
        )
        if not self._remove_stale(desired_states):
            return False
        self._draw(desired_states, gamut)

        if self._finished(in_start_window):
            return False
        return not self.monitor.waitForAbort(self._wait_time(in_start_window, started))

    def _in_start_window(self, now: float) -> bool:
        """Return whether the start logos are (still) due."""
        config = self.config
        return config.show_on_start and (
            self.started is None or now - self.started < config.duration)

    def _finished(self, in_start_window: bool) -> bool:
        """Return whether nothing is left to show: no mode, no logos."""
        config = self.config
        return (not config.show_on_osd and not config.show_on_tinyppi
                and not in_start_window and not self.states)

    def _refresh_settings(self) -> bool:
        """Re-read the settings after a change; False while unavailable."""
        # A new handle means changed settings; None during an update.
        addon = _safe_addon()
        if addon is None:
            return False
        if addon is not self.addon:
            self.addon = addon
            self.config = read_settings(addon)
            self.themed = False
        return True

    def _refresh_format(self, gamut: str, now: float) -> None:
        """Re-read the source format, its DV layer and the audio track when due."""
        # Reading the format parses side data, so it is re-read once a
        # second, when the output changes, or every poll until known.  The
        # audio-track check (player lock) uses the same schedule.
        if not self.hdr_type or gamut != self.format_gamut or now >= self.format_due:
            self.hdr_type = get_hdr_format()
            self.el_type = get_dv_el_type_raw() if "dolby" in self.hdr_type else ""
            self.has_audio = video_has_audio(self.player)
            self.format_gamut = gamut
            self.format_due = now + _FORMAT_INTERVAL

    def _publish_converting(self, gamut: str) -> None:
        """Publish the badge state (``PROP_CONVERTING``) when it changed."""
        # Updated every poll; the badge's condition follows it.
        now_converting = "true" if is_converting(self.hdr_type, gamut) else "false"
        if now_converting != self.converting:
            self.converting = now_converting
            self.home.setProperty(PROP_CONVERTING, self.converting)

    def _settle(self, gamut: str, hdr_token: str, now: float) -> float | None:
        """Return the start time once the output has settled, else None."""
        # Wait for the output to settle before drawing.
        if gamut != self.settle_gamut:
            self.settle_gamut, self.settle_since = gamut, now
        switching = bool(self.hdr_type) and not hdr_token
        if (now - self.settle_since < _SETTLE_SECONDS
                or (switching and now - self.waiting_since < _SETTLE_SDR_LIMIT)):
            return None
        self.started = now
        _log(f"output settled after {now - self.waiting_since:.1f}s at "
             f"{gamut!r}, source {self.hdr_type or 'sdr'!r}")
        return now

    def _desired_states(self, hdr_token: str, in_start_window: bool) -> dict[str, _ModeState]:
        """Return the state each mode to show should have this poll."""
        desired_states: dict[str, _ModeState] = {}
        logos = current_logos(hdr_token)
        modes = _active_modes(self.config, in_start_window)
        if not modes:
            return desired_states

        # Publish the theme once per settings change, then read
        # each context's tints back.
        if not self.themed:
            apply_theme(self.home, self.addon)
            self.colors_by_mode = {
                mode: _mode_colors(self.home, mode)
                for mode in _MODE_PROP_PREFIX
            }
            self.themed = True
        layer_token = dv_layer_token(hdr_token, self.hdr_type, self.el_type)
        for mode in modes:
            # A mode without logos draws nothing this poll.
            mode_settings = self.config.modes[mode]
            mode_logos = _mode_logos(mode_settings, logos, self.has_audio)
            if not mode_logos:
                continue
            colors = self.colors_by_mode[mode]
            desired_states[mode] = _ModeState(
                logos=mode_logos,
                offset_x=mode_settings.offset_x,
                offset_y=mode_settings.offset_y,
                scale=mode_settings.scale,
                colors=tuple(sorted(colors.items())),
                condition=_visible_condition(mode, self.config.show_on_osd, self.run_token),
                layer_token=layer_token,
                pill_at_top=mode_settings.pill_at_top,
            )
        return desired_states

    def _remove_stale(self, desired_states: dict[str, _ModeState]) -> bool:
        """Fade out and remove the modes not wanted; False on abort."""
        remove_modes = [
            mode for mode in tuple(self.controls_by_mode)
            if mode not in desired_states
        ]
        if remove_modes:
            for mode in remove_modes:
                self.home.clearProperty(_MODE_VISIBLE_PROPS[mode])
            if self.monitor.waitForAbort(_FADE_OUT_SECONDS):
                return False
            for mode in remove_modes:
                _remove_controls(self.video_window, self.controls_by_mode[mode])
                self.controls_by_mode.pop(mode, None)
                self.states.pop(mode, None)
        return True

    def _draw(self, desired_states: dict[str, _ModeState], gamut: str) -> None:
        """(Re)draw each mode whose desired state changed."""
        monitor = self.monitor
        for mode, desired in desired_states.items():
            # Adding controls waits on the GUI thread, so nothing is
            # drawn while Kodi stops the service.
            if monitor.abortRequested():
                break
            if self.states.get(mode) == desired:
                continue
            if mode in self.controls_by_mode:
                _log(f"{mode} redrawn for output {gamut!r}, source "
                     f"{self.hdr_type or 'sdr'!r}")
                _fade_out(self.video_window, self.home, monitor, mode,
                          self.controls_by_mode[mode])
                if monitor.abortRequested():
                    break
            controls, dot = build_controls(
                list(desired.logos), self.colors_by_mode[mode],
                desired.offset_x, desired.offset_y,
                self.screen_w, self.screen_h, desired.scale, desired.layer_token,
                desired.pill_at_top,
            )
            self.controls_by_mode[mode] = controls
            self.states[mode] = desired
            _fade_in(
                self.video_window, self.home, monitor, mode, controls,
                desired.condition, dot,
            )

    def _wait_time(self, in_start_window: bool, started: float) -> float:
        """Return the poll wait, cut to what is left of the start window."""
        wait_time = _POLL_INTERVAL
        if self.config.show_on_start and in_start_window:
            remaining = self.config.duration - (time.monotonic() - started)
            if remaining > 0:
                wait_time = min(wait_time, remaining)
        return wait_time


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
    config = read_settings(addon)
    if not _active_modes(config):
        return

    player = xbmc.Player()
    if not player.isPlayingVideo():
        return

    home = xbmcgui.Window(HOME_WINDOW_ID)
    if home.getProperty(PROP_SPLASH_ACTIVE) == "true":
        return

    if not _anything_to_show(config, player):
        return

    video_window = xbmcgui.Window(WINDOW_FULLSCREEN_VIDEO)
    screen = window_dims(video_window)
    monitor = xbmc.Monitor()

    home.setProperty(PROP_SPLASH_ACTIVE, "true")
    run = f"{os.getpid()}-{time.monotonic_ns()}"
    home.setProperty(PROP_SPLASH_RUN, run)
    home.clearProperty(PROP_SPLASH_VISIBLE)
    _clear_mode_visibility(home)
    controller = _Controller(addon, config, player, home, video_window, screen, monitor, run)
    try:
        controller.run()
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
            for controls in controller.controls_by_mode.values():
                _remove_controls(video_window, controls)
