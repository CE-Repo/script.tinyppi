"""
overlay.py – Core logic for the TinyPPI overlay dialog and its entry points.

Imported by the root launcher (main.py).  Do not add sys.path manipulation
here — that is handled by main.py before this module is imported.
"""

import os
import re
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

import fonts
import properties
from theme import apply_theme

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_PROP_RUNNING = "TinyPPI.Running"
_PROP_ACTIVE  = "TinyPPI.Active"
_PROP_DIALOG_MODE = "TinyPPI.DialogMode"

# Kodi skin resolution folder names, e.g. "720p", "1080i", "1080p", "480p".
_RES_FOLDER_RE = re.compile(r"^\d{3,4}[ip]$")

_dialog_lock = False

# Raise to True to allow launching on non-CoreELEC platforms (e.g. for testing).
_ALLOW_NON_COREELEC = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _set_home_properties(home, values: tuple[tuple[str, str], ...]) -> None:
    """Publish a batch of properties on Kodi's Home window."""
    for name, value in values:
        home.setProperty(name, value)


def _set_overlay_state(home, dialog_mode: bool = False) -> None:
    """Publish the Home-window properties that mark TinyPPI as open."""
    _set_home_properties(
        home,
        (
            (_PROP_RUNNING, "true"),
            (_PROP_ACTIVE, "true"),
        ),
    )

    if dialog_mode:
        home.setProperty(_PROP_DIALOG_MODE, "true")
    else:
        home.clearProperty(_PROP_DIALOG_MODE)


def _clear_overlay_state(home) -> None:
    """Clear the Home-window properties that describe TinyPPI state."""
    home.clearProperty(_PROP_RUNNING)
    home.clearProperty(_PROP_ACTIVE)
    home.clearProperty(_PROP_DIALOG_MODE)


def _skin_supports_1080(skin_path: str) -> bool:
    """
    Return True only when the active skin is a pure 1080 skin.

    Collects the skin's resolution folders (e.g. ``720p``, ``1080i``, ``1080p``)
    and requires that at least one exists and *all* of them are 1080-based.  A
    multi-resolution skin that also ships a 720p (or other sub-1080) folder is
    treated as unsupported, since Kodi may render it at the lower resolution.
    """
    try:
        entries = os.listdir(skin_path)
    except OSError:
        return False
    resolutions = [
        name for name in entries
        if _RES_FOLDER_RE.match(name) and os.path.isdir(os.path.join(skin_path, name))
    ]
    return bool(resolutions) and all(r.startswith("1080") for r in resolutions)


def _preflight(home, player, toggle_log: str) -> bool:
    """
    Run the environment and playback guards shared by both entry points.

    Returns True when the overlay may open.  Otherwise shows the appropriate
    error notification (or triggers the toggle-close action) and returns False.
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
    if not _skin_supports_1080(skin_path):
        _notify_error(32012)
        xbmc.log("TinyPPI: non-1080 skin detected – unsupported", xbmc.LOGWARNING)
        return False

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return False

    if not player.isPlaying():
        return False

    if home.getProperty(_PROP_RUNNING) == "true":
        xbmc.log(toggle_log, xbmc.LOGINFO)
        xbmc.executebuiltin("Action(Back)")
        return False

    return not _dialog_lock


def _release_overlay(home) -> None:
    """Briefly hold the re-entry lock, then clear the overlay state properties."""
    global _dialog_lock
    _dialog_lock = True
    xbmc.Monitor().waitForAbort(0.2)
    _dialog_lock = False

    _clear_overlay_state(home)


# ---------------------------------------------------------------------------
# Overlay dialog
# ---------------------------------------------------------------------------

class TinyPPIDialog(xbmcgui.WindowXMLDialog):
    """
    Overlay window that displays live player information while a video is
    playing in fullscreen.

    The dialog auto-closes when playback stops or the user navigates away
    from the fullscreen video window.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0

    # ------------------------------------------------------------------
    # Kodi callbacks

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()

        properties.update_properties(self)
        self._start_update_loop()

    def onClick(self, control_id: int) -> None:
        self.close_dialog()

    def onAction(self, action: xbmcgui.Action) -> None:
        if time.time() - self._opened_at < 0.3:
            return
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close_dialog()

    def onClosed(self) -> None:
        home = xbmcgui.Window(10000)
        _clear_overlay_state(home)

    # ------------------------------------------------------------------
    # Update loop

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

            properties.update_properties(self)

            if self._monitor.waitForAbort(1):
                break

        self.close_dialog()

    # ------------------------------------------------------------------
    # Close

    def close_dialog(self) -> None:
        self._running = False
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def open_tinyppi() -> None:
    """
    Validate the environment and open the TinyPPI overlay window.

    Skips silently when:
    - Not running on CoreELEC (unless ``_ALLOW_NON_COREELEC`` is True).
    - Kodi build version is older than 22.
    - The active skin does not support 1080.
    - Fullscreen video is not currently active.
    - No media is playing.
    - The overlay is already open (acts as a toggle-close instead).
    """
    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    if not _preflight(home, player, "TinyPPI: Toggle close"):
        return

    _set_overlay_state(home)
    _set_home_properties(
        home,
        (
            ("TinyPPI.UIStyle", _ADDON.getSetting("ui_style")),
            ("TinyPPI.Filename", _ADDON.getSetting("filename")),
            (
                "TinyPPI.BackgroundToggle",
                "1" if _ADDON.getSetting("background_toggle") == "true" else "0",
            ),
            (
                "TinyPPI.ShowL5Icon",
                "0" if _ADDON.getSetting("show_l5_icon") == "false" else "1",
            ),
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

    _set_overlay_state(home, dialog_mode=True)
    apply_theme(home, _ADDON)

    try:
        from mode_select import open_dialog
        open_dialog()
    finally:
        _release_overlay(home)
