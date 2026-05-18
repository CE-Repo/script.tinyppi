import os, sys
import xbmc
import time
import json


# -----------------------------
# Logging Helper
# -----------------------------

ADDON_ID = "script.tinyppi"
FORCE_DEBUG_LOG = False

def log_msg(msg, loglevel=xbmc.LOGDEBUG):
    ''' log message to kodi logfile '''
    if loglevel == xbmc.LOGDEBUG and FORCE_DEBUG_LOG:
        loglevel = xbmc.LOGINFO

    xbmc.log("%s --> %s" % (ADDON_ID, msg), level=loglevel)


# -----------------------------
# Kodi Monitor
# -----------------------------

class KodiMonitor(xbmc.Monitor):

    def __init__(self, **kwargs):
        xbmc.Monitor.__init__(self)
        self.win = kwargs.get("win")
        self.addon = kwargs.get("addon")

    def onNotification(self, sender, method, data):
        ''' builtin function for the xbmc.Monitor class '''
        try:
            log_msg("Kodi_Monitor: sender %s - method: %s  - data: %s" % (sender, method, data))
            data = json.loads(data)
            mediatype = ""
            if data and isinstance(data, dict):
                if data.get("item"):
                    mediatype = data["item"].get("type", "")
                elif data.get("type"):
                    mediatype = data["type"]

        except Exception as exc:
            log_msg("Exception in KodiMonitor: %s" % exc, xbmc.LOGERROR)



# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    import xbmcaddon
    import xbmcgui

    addon = xbmcaddon.Addon()
    win = xbmcgui.Window(10000)

    monitor = KodiMonitor(win=win, addon=addon)

    xbmc.log("KodiMonitor started", xbmc.LOGINFO)

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break

    del monitor