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

_LIB_PATH = os.path.dirname(__file__)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from dvinfo import reset_playback_cache
from theme import apply_theme

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON_ID = "script.tinyppi"
_HOME_WINDOW_ID = 10000

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


def _notification_media_type(data: str) -> str:
    """Extract the media type field from a Kodi JSON notification payload."""
    payload = json.loads(data)
    if not isinstance(payload, dict):
        return ""

    item = payload.get("item") or {}
    if isinstance(item, dict):
        return item.get("type", "") or payload.get("type", "")
    return payload.get("type", "")


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class KodiMonitor(xbmc.Monitor):
    """
    Listens for Kodi notifications.

    Currently logs all received notifications at DEBUG level.  Extend
    ``onNotification`` to react to specific player or library events.
    """

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if method == "Player.OnStop":
            reset_playback_cache()
            _log("Dolby Vision playback cache cleared")

        if method == "Player.OnAVStart":
            self._maybe_show_splash()

        try:
            mediatype = _notification_media_type(data)
            _log(f"sender={sender}  method={method}  type={mediatype!r}")
        except Exception as exc:
            _log(f"Exception in KodiMonitor.onNotification: {exc}", xbmc.LOGERROR)

    def onSettingsChanged(self) -> None:
        """(Re)launch the splash when the add-on settings change.

        A splash controller that is already running re-reads every setting from a
        fresh ``Addon()`` each poll, so it picks up edits live on its own (its
        re-entry guard makes this call a no-op then).  This launch covers the
        other case: when all triggers were off at playback start no controller
        exists, so enabling one here starts it without restarting playback.
        """
        self._maybe_show_splash()

    def _maybe_show_splash(self) -> None:
        """Fire the start-up format-logo splash when enabled for this video.

        Runs the splash in its own script interpreter so the modal-free window
        and its close timer live outside the notification thread.  Cheap guards
        run here first; the splash script re-checks everything before showing.
        """
        try:
            addon = xbmcaddon.Addon()
            if not (addon.getSettingBool("splash_enabled")
                    or addon.getSettingBool("splash_show_on_osd")
                    or addon.getSettingBool("splash_show_on_tinyppi")):
                return
            if not xbmc.getCondVisibility("Player.HasVideo"):
                return
            xbmc.executebuiltin(f"RunScript({_ADDON_ID},splash)")
        except Exception as exc:
            _log(f"Exception starting splash: {exc}", xbmc.LOGERROR)


# ---------------------------------------------------------------------------
# Entry point  (called by Kodi via the xbmc.service extension point)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    addon   = xbmcaddon.Addon()
    win     = xbmcgui.Window(_HOME_WINDOW_ID)
    monitor = KodiMonitor()

    reset_playback_cache()

    # Publish the theme properties (including the per-color "Custom" swatches)
    # at startup so the settings dialog can preview custom HEX colors even when
    # the overlay has not been opened yet this session.
    try:
        apply_theme(win, addon)
    except Exception as exc:  # pragma: no cover - never block the service
        xbmc.log(f"TinyPPI: apply_theme at startup failed: {exc}", xbmc.LOGWARNING)

    xbmc.log("TinyPPI: KodiMonitor started", xbmc.LOGINFO)

    # Block until Kodi shuts down; notifications arrive on their own thread.
    monitor.waitForAbort()

    del monitor
