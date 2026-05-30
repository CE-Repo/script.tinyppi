"""
monitor.py – Lightweight background service for TinyPPI.

Runs as an ``xbmc.service`` (see addon.xml) and keeps a Kodi monitor alive
for the lifetime of the session so that other parts of the addon can react
to system-level notifications.
"""

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON_ID = "script.tinyppi"

# Set to True locally to promote debug messages to INFO level so they appear
# in a standard (non-debug) Kodi log.
_FORCE_DEBUG_LOG = False

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    if level == xbmc.LOGDEBUG and _FORCE_DEBUG_LOG:
        level = xbmc.LOGINFO
    xbmc.log(f"{_ADDON_ID} --> {msg}", level=level)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class KodiMonitor(xbmc.Monitor):
    """
    Listens for Kodi notifications.

    Currently logs all received notifications at DEBUG level.  Extend
    ``onNotification`` to react to specific player or library events.
    """

    def __init__(self, win: xbmcgui.Window, addon: xbmcaddon.Addon) -> None:
        super().__init__()
        self.win   = win
        self.addon = addon

    def onNotification(self, sender: str, method: str, data: str) -> None:
        try:
            payload   = json.loads(data)
            mediatype = ""

            if isinstance(payload, dict):
                item = payload.get("item") or {}
                mediatype = item.get("type", "") or payload.get("type", "")

            _log(f"sender={sender}  method={method}  type={mediatype!r}")

        except Exception as exc:
            _log(f"Exception in KodiMonitor.onNotification: {exc}", xbmc.LOGERROR)


# ---------------------------------------------------------------------------
# Entry point  (called by Kodi via the xbmc.service extension point)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _addon_path = xbmcaddon.Addon().getAddonInfo("path")
    sys.path.insert(0, os.path.join(_addon_path, "resources", "lib"))

    addon   = xbmcaddon.Addon()
    win     = xbmcgui.Window(10000)
    monitor = KodiMonitor(win=win, addon=addon)

    xbmc.log("TinyPPI: KodiMonitor started", xbmc.LOGINFO)

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break

    del monitor
