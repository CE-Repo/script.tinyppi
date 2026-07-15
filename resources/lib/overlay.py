"""Core logic for the TinyPPI overlay dialog and its entry points.

Imported by main.py, which sets up sys.path first.
"""

import os
import threading
import time

import fonts
import properties
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from theme import apply_theme
from utils import (
    PROP_ACTIVE,
    PROP_DIALOG_MODE,
    PROP_RUNNING,
    clear_overlay_state,
    set_window_properties,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_dialog_lock = False

# Raise to True to allow launching on non-CoreELEC platforms (e.g. for testing).
_ALLOW_NON_COREELEC = False

# Runtime nudge: pixels moved per arrow-key press, and the direction each key
# shifts the overlay by.  Deliberately not persisted – the nudge lives on the
# dialog instance, so the next launch starts from the configured offsets again.
_NUDGE_STEP = 10

# Outermost edges of the overlay content inside group 5000 (see the skin XML);
# the nudge is clamped so these stay on screen.
_CONTENT_LEFT      = 35
_CONTENT_TOP       = 340
_CONTENT_BOTTOM    = 1045
_CONTENT_RIGHT_SDR = 1292
_CONTENT_RIGHT_HDR = 1885

_NUDGE_ACTIONS = {
    xbmcgui.ACTION_MOVE_LEFT:  (-_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_RIGHT: (_NUDGE_STEP, 0),
    xbmcgui.ACTION_MOVE_UP:    (0, -_NUDGE_STEP),
    xbmcgui.ACTION_MOVE_DOWN:  (0, _NUDGE_STEP),
}


def _is_coreelec() -> bool:
    """Return True when running on a CoreELEC installation."""
    if os.path.isdir("/etc/coreelec"):
        return True
    try:
        with open("/etc/os-release") as f:
            return any("coreelec" in line.lower() for line in f)
    except OSError:
        return False


def _notify_error(message_id: int) -> None:
    """Show a Kodi error notification using a localised string ID."""
    xbmcgui.Dialog().notification(
        "TinyPPI",
        _ADDON.getLocalizedString(message_id),
        xbmcgui.NOTIFICATION_ERROR,
        4000,
    )


def _set_overlay_state(home, dialog_mode: bool = False) -> None:
    """Publish the Home-window properties that mark TinyPPI as open."""
    set_window_properties(
        home,
        (
            (PROP_RUNNING, "true"),
            (PROP_ACTIVE, "true"),
        ),
    )

    if dialog_mode:
        home.setProperty(PROP_DIALOG_MODE, "true")
    else:
        home.clearProperty(PROP_DIALOG_MODE)


def _preflight(home, player, toggle_log: str) -> bool:
    """Run the environment and playback guards shared by both entry points.

    Returns True when the overlay may open, else shows an error notification
    (or triggers the toggle-close) and returns False.
    """
    if not _ALLOW_NON_COREELEC:
        if not _is_coreelec():
            _notify_error(32016)
            return False

        build_version = xbmc.getInfoLabel("System.BuildVersion")
        try:
            major_version = int(build_version.split(".")[0])
        except (ValueError, IndexError):
            _notify_error(32017)
            return False

        if major_version < 22:
            _notify_error(32016)
            return False

    skin_path = xbmcvfs.translatePath("special://skin/")
    if os.path.exists(os.path.join(skin_path, "720p")):
        _notify_error(32012)
        xbmc.log("TinyPPI: 720p skin detected – unsupported", xbmc.LOGWARNING)
        return False

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return False

    if not player.isPlaying():
        return False

    if home.getProperty(PROP_RUNNING) == "true":
        xbmc.log(toggle_log, xbmc.LOGINFO)
        xbmc.executebuiltin("Action(Back)")
        return False

    return not _dialog_lock


def _elements_visible() -> str:
    """Return the "1"/"0" flag for the header title, header icon and separator
    lines: they follow the background and hide only when it is fully transparent."""
    return "0" if _ADDON.getSettingInt("background_opacity") == 0 else "1"


def _release_overlay(home) -> None:
    """Clear overlay state immediately, then briefly hold the re-entry lock."""
    global _dialog_lock
    _dialog_lock = True
    clear_overlay_state(home)
    try:
        xbmc.Monitor().waitForAbort(0.2)
    finally:
        _dialog_lock = False


# ---------------------------------------------------------------------------
# Overlay dialog
# ---------------------------------------------------------------------------

class TinyPPIDialog(xbmcgui.WindowXMLDialog):
    """Overlay showing live player info during fullscreen playback; auto-closes
    when playback stops or the user leaves the fullscreen video window."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        self._offset    = None
        self._auto_hide = 0
        self._nudge     = (0, 0)

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        # Auto-hide timeout in seconds (0 = off). Applies to the TinyPPI
        # overlay only, not the VS10 selection dialog.
        self._auto_hide = _ADDON.getSettingInt("auto_hide")

        # Publish properties first so the HDR type is known before the initial
        # position is applied (matters when reopening with a cached result).
        properties.update_properties(self)
        self._apply_position_offset()
        self._start_update_loop()

    def _base_offset(self) -> tuple:
        """Return the (x, y) offset configured in the settings.

        From the bottom-left origin, the horizontal offset moves content right,
        the vertical offset moves it up; 100 % is the max on-screen travel
        (30.9 % / 28.1 % of the screen).  The horizontal offset applies to SDR
        only (HDR stays left-aligned).
        """
        max_x = 0.309
        max_y = 0.281
        offset_x = round(1920 * max_x * _ADDON.getSettingInt("offset_x") / 100)
        offset_y = -round(1080 * max_y * _ADDON.getSettingInt("offset_y") / 100)
        if self._is_hdr():
            offset_x = 0
        return offset_x, offset_y

    def _is_hdr(self) -> bool:
        return bool(xbmcgui.Window(10000).getProperty("TinyPPI.HdrType"))

    def _apply_position_offset(self) -> None:
        """Move group 5000 to the configured offset plus the current nudge.

        The nudge is clamped here rather than where it is applied, so that a
        later HDR switch (which widens the content) pulls an already nudged
        overlay back on screen.  Clamping the nudge instead of the resulting
        position keeps the first press in the opposite direction effective.
        Re-applied each cycle since the HDR type is detected asynchronously, and
        cached so the unchanged case is skipped.
        """
        base_x, base_y = self._base_offset()
        nudge_x, nudge_y = self._nudge
        right = _CONTENT_RIGHT_HDR if self._is_hdr() else _CONTENT_RIGHT_SDR

        nudge_x = min(max(nudge_x, -_CONTENT_LEFT - base_x), 1920 - right - base_x)
        nudge_y = min(max(nudge_y, -_CONTENT_TOP - base_y), 1080 - _CONTENT_BOTTOM - base_y)
        self._nudge = (nudge_x, nudge_y)

        offset = (base_x + nudge_x, base_y + nudge_y)
        if offset == self._offset:
            return
        self._offset = offset
        self.getControl(5000).setPosition(*offset)

    def _move(self, dx: int, dy: int) -> None:
        """Shift the overlay by one step; reverts on the next launch."""
        nudge_x, nudge_y = self._nudge
        self._nudge = (nudge_x + dx, nudge_y + dy)
        self._apply_position_offset()

    def onClick(self, control_id: int) -> None:
        self.close_dialog()

    def onAction(self, action: xbmcgui.Action) -> None:
        if time.time() - self._opened_at < 0.3:
            return
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close_dialog()
            return
        step = _NUDGE_ACTIONS.get(action_id)
        if step:
            self._move(*step)

    def _start_update_loop(self) -> None:
        t = threading.Thread(target=self._update_loop, daemon=True)
        t.start()

    def _update_loop(self) -> None:
        player = xbmc.Player()

        while self._running and not self._monitor.abortRequested():
            if not player.isPlaying():
                break
            if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
                break
            if self._auto_hide and time.time() - self._opened_at >= self._auto_hide:
                break

            properties.update_properties(self)
            self._apply_position_offset()

            if self._monitor.waitForAbort(1):
                break

        self.close_dialog()

    def close_dialog(self) -> None:
        self._running = False
        xbmcgui.Window(10000).clearProperty(PROP_ACTIVE)
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def open_tinyppi() -> None:
    """Validate the environment and open the overlay window.

    Skips silently on non-CoreELEC (unless ``_ALLOW_NON_COREELEC``), Kodi < 22,
    a 720p skin, no fullscreen video, or nothing playing; toggle-closes when the
    overlay is already open.
    """
    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    if not _preflight(home, player, "TinyPPI: Toggle close"):
        return

    elements_visible = _elements_visible()
    _set_overlay_state(home)
    set_window_properties(
        home,
        (
            ("TinyPPI.Filename", _ADDON.getSetting("filename")),
            (
                "TinyPPI.ShowL5Icon",
                "0" if _ADDON.getSetting("show_l5_icon") == "false" else "1",
            ),
            ("TinyPPI.ShowLine", elements_visible),
            ("TinyPPI.ShowHeaderTitle", elements_visible),
            ("TinyPPI.ShowHeaderIcon", elements_visible),
        ),
    )
    apply_theme(home, _ADDON)

    try:
        dialog = TinyPPIDialog(
            "script-tinyppi-main.xml",
            _ADDON_PATH,
            "Default",
            "1080i",
        )
        dialog.doModal()
        del dialog
    finally:
        _release_overlay(home)


def open_dialog_mode() -> None:
    """Open the VS10-mode selection dialog."""
    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    if not _preflight(home, player, "TinyPPI: Toggle close (dialog mode)"):
        return

    elements_visible = _elements_visible()
    _set_overlay_state(home, dialog_mode=True)
    set_window_properties(
        home,
        (
            ("TinyPPI.ShowLine", elements_visible),
            ("TinyPPI.ShowHeaderTitle", elements_visible),
            ("TinyPPI.ShowHeaderIcon", elements_visible),
        ),
    )
    apply_theme(home, _ADDON)

    try:
        from mode_select import open_dialog
        open_dialog()
    finally:
        _release_overlay(home)
