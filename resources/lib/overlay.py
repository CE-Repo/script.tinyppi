"""
overlay.py – Core logic for the TinyPPI overlay dialog and its entry points.

Imported by the root launcher (main.py).  Do not add sys.path manipulation
here — that is handled by main.py before this module is imported.
"""

import os
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

import fonts       # runs install_fonts() on import
import properties

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_PROP_RUNNING = "TinyPPI.Running"
_PROP_ACTIVE  = "TinyPPI.Active"

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
        home.clearProperty(_PROP_RUNNING)
        home.clearProperty(_PROP_ACTIVE)

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
    - A 720p skin is active.
    - Fullscreen video is not currently active.
    - No media is playing.
    - The overlay is already open (acts as a toggle-close instead).
    """
    global _dialog_lock

    home   = xbmcgui.Window(10000)
    player = xbmc.Player()

    # ── CoreELEC / version checks ──────────────────────────────────────

    if not _ALLOW_NON_COREELEC:
        if not _is_coreelec():
            _notify_error(32016)
            return

        build_version = xbmc.getInfoLabel("System.BuildVersion")
        try:
            major_version = int(build_version.split(".")[0])
        except (ValueError, IndexError):
            _notify_error(32017)
            return

        if major_version < 22:
            _notify_error(32016)
            return

    # ── 720p skin guard ────────────────────────────────────────────────

    skin_path   = xbmcvfs.translatePath("special://skin/")
    is_720_skin = os.path.exists(os.path.join(skin_path, "720p"))

    if is_720_skin:
        _notify_error(32012)
        xbmc.log("TinyPPI: 720p skin detected – unsupported", xbmc.LOGWARNING)
        return

    # ── State guards ───────────────────────────────────────────────────

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return

    if not player.isPlaying():
        return

    if home.getProperty(_PROP_RUNNING) == "true":
        xbmc.log("TinyPPI: Toggle close", xbmc.LOGINFO)
        xbmc.executebuiltin("Action(Back)")
        return

    if _dialog_lock:
        return

    # ── Set window properties and open ─────────────────────────────────

    home.setProperty(_PROP_RUNNING, "true")
    home.setProperty(_PROP_ACTIVE,  "true")
    home.setProperty("TinyPPI.UIStyle",          _ADDON.getSetting("ui_style"))
    home.setProperty("TinyPPI.Filename",         _ADDON.getSetting("filename"))
    home.setProperty("TinyPPI.BackgroundToggle",
                     "1" if _ADDON.getSetting("background_toggle") == "true" else "0")

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
        _dialog_lock = True
        xbmc.Monitor().waitForAbort(0.2)
        _dialog_lock = False

        home.clearProperty(_PROP_RUNNING)
        home.clearProperty(_PROP_ACTIVE)


def open_dialog_mode() -> None:
    """Open the VS10-mode selection dialog."""
    from mode_select import open_dialog
    open_dialog()
