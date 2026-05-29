import font_installer
import playerprops
import sys
import threading
import time
import os
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

WINDOW_PROP = "TinyPPI.Running"
SKIN_PROP = "TinyPPI.Active"

DIALOG_LOCK = False
BACKGROUND_TOGGLE = ADDON.getSetting("background_toggle") == "true"
ALLOW_NON_COREELEC = True


class TinyPPIDialog(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running = False
        self.monitor = xbmc.Monitor()
        self._opened_at = 0

    def onInit(self):
        self._running = True
        self._opened_at = time.time()

        playerprops.update_properties(self)
        self._start_update_loop()

    def _start_update_loop(self):
        t = threading.Thread(target=self._update_loop, daemon=True)
        t.start()

    def _update_loop(self):

        player = xbmc.Player()

        while self._running and not self.monitor.abortRequested():

            if not player.isPlaying():
                break

            if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
                break

            playerprops.update_properties(self)

            if self.monitor.waitForAbort(1):
                break

        self.close_dialog()

    def onClick(self, controlId):
        self.close_dialog()

    def onAction(self, action):

        if time.time() - self._opened_at < 0.3:
            return

        action_id = action.getId()

        if action_id in [xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK]:
            self.close_dialog()

    def close_dialog(self):
        self._running = False

        try:
            self.close()
        except:
            pass

    def onClosed(self):
        xbmcgui.Window(10000).clearProperty(WINDOW_PROP)
        xbmcgui.Window(10000).clearProperty(SKIN_PROP)


def _is_coreelec() -> bool:
    if os.path.isdir("/etc/coreelec"):
        return True
    try:
        with open("/etc/os-release") as f:
            return any("coreelec" in line.lower() for line in f)
    except OSError:
        return False


def open_tinyppi():

    global DIALOG_LOCK

    win = xbmcgui.Window(10000)
    player = xbmc.Player()

    skin_path = xbmcvfs.translatePath("special://skin/")
    is_720_skin = os.path.exists(os.path.join(skin_path, "720p"))

    if not ALLOW_NON_COREELEC:

        if not _is_coreelec():

            xbmcgui.Dialog().notification(
                "TinyPPI",
                ADDON.getLocalizedString(32016),
                xbmcgui.NOTIFICATION_ERROR,
                4000
            )

            return

        build_version = xbmc.getInfoLabel("System.BuildVersion")

        try:
            major_version = int(build_version.split(".")[0])
        except:

            xbmcgui.Dialog().notification(
                "TinyPPI",
                ADDON.getLocalizedString(32017),
                xbmcgui.NOTIFICATION_ERROR,
                4000
            )

            return

        if major_version < 22:

            xbmcgui.Dialog().notification(
                "TinyPPI",
                ADDON.getLocalizedString(32016),
                xbmcgui.NOTIFICATION_ERROR,
                4000
            )

            return

    if is_720_skin:

        xbmcgui.Dialog().notification(
            "TinyPPI",
            ADDON.getLocalizedString(32012),
            xbmcgui.NOTIFICATION_ERROR,
            4000
        )

        xbmc.log("TinyPPI: 720p skin detected - unsupported", xbmc.LOGWARNING)
        return

    if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return

    if not player.isPlaying():
        return

    if win.getProperty(WINDOW_PROP) == "true":
        xbmc.log("TinyPPI: Toggle close", xbmc.LOGINFO)

        xbmc.executebuiltin("Action(Back)")
        return

    if DIALOG_LOCK:
        return

    win.setProperty(WINDOW_PROP, "true")
    win.setProperty(SKIN_PROP, "true")
    win.setProperty("TinyPPI.UIStyle", ADDON.getSetting("ui_style"))
    win.setProperty("TinyPPI.BackgroundToggle", "1" if ADDON.getSetting("background_toggle") == "true" else "0")

    try:
        dialog = TinyPPIDialog(
            'script-tinyppi-main.xml',
            ADDON_PATH,
            'Default',
            '1080i'
        )

        dialog.doModal()
        del dialog

    finally:
        DIALOG_LOCK = True
        xbmc.Monitor().waitForAbort(0.2)
        DIALOG_LOCK = False

        win.clearProperty(WINDOW_PROP)
        win.clearProperty(SKIN_PROP)


if __name__ == '__main__':

    args = sys.argv[1:] if len(sys.argv) > 0 else []

    if 'dialog' in args:
        import dialog
        dialog.open_dialog()
    else:
        open_tinyppi()
