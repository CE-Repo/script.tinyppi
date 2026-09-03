# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Background service (xbmc.service): keeps a Kodi monitor alive for the session
so the addon can react to system notifications."""

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

_LIB_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from ui.theme import apply_theme
from web.server import WebDashboard

_ADDON_ID = "script.tinyppi"
_HOME_WINDOW_ID = 10000


# Set True locally to promote debug messages to INFO in a non-debug Kodi log.
_FORCE_DEBUG_LOG = False


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


class KodiMonitor(xbmc.Monitor):
    """Listens for Kodi notifications; fires the splash on playback start.

    Also owns the web dashboard's lifecycle: it is started and stopped from
    here because this is the one thing that lives for the whole Kodi session.
    """

    def __init__(self, dashboard: WebDashboard | None = None) -> None:
        super().__init__()
        self._dashboard = dashboard

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if method == "Player.OnAVStart":
            self._maybe_show_splash()

        try:
            mediatype = _notification_media_type(data)
            _log(f"sender={sender}  method={method}  type={mediatype!r}")
        except Exception as exc:
            _log(f"Exception in KodiMonitor.onNotification: {exc}", xbmc.LOGERROR)

    def onSettingsChanged(self) -> None:
        """(Re)launch the splash when settings change, and bring the web
        dashboard in line with them.

        A running controller picks up edits on its own (its guard makes this a
        no-op); this covers the case where all triggers were off at playback
        start, so enabling one here starts it without restarting playback.
        """
        self._maybe_show_splash()
        self.apply_dashboard_settings()

    def apply_dashboard_settings(self) -> None:
        """Start, stop or reconfigure the dashboard to match the settings.

        A failure here must not take the monitor with it: the dashboard is an
        extra, and Kodi still needs its notifications handled.
        """
        if self._dashboard is None:
            return
        try:
            self._dashboard.apply_settings()
        except Exception as exc:
            _log(f"Exception applying web dashboard settings: {exc}", xbmc.LOGERROR)

    def _maybe_show_splash(self) -> None:
        """Fire the format-logo splash when enabled for this video.

        Runs in its own script interpreter; cheap guards run here first, the
        splash script re-checks everything before showing.
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


if __name__ == "__main__":
    addon     = xbmcaddon.Addon()
    win       = xbmcgui.Window(_HOME_WINDOW_ID)
    dashboard = WebDashboard()
    monitor   = KodiMonitor(dashboard)

    # Publish the theme properties at startup so the settings dialog can preview
    # custom HEX colors before the overlay has been opened this session.
    try:
        apply_theme(win, addon)
    except Exception as exc:  # pragma: no cover - never block the service
        xbmc.log(f"TinyPPI: apply_theme at startup failed: {exc}", xbmc.LOGWARNING)

    # Off unless the user switched it on; this is what starts it at boot.
    monitor.apply_dashboard_settings()

    xbmc.log("TinyPPI: KodiMonitor started", xbmc.LOGINFO)

    # Block until Kodi shuts down; notifications arrive on their own thread.
    monitor.waitForAbort()

    # Nothing may be left running past this point.  Kodi does not simply let
    # the interpreter go: once this script returns, CPythonInvoker spins with
    # no timeout of its own until every other thread of the interpreter has
    # ended, so a web server still accepting connections -- each one a fresh
    # thread -- is a Kodi that never finishes shutting down.  Being daemons
    # does not help them; Kodi never reaches the teardown that would.
    #
    # It is also on a clock: Kodi allows the script five seconds to stop and
    # then raises SystemExit in it, which is why the shutdown is the first
    # thing done here and why it cannot be allowed to raise.
    try:
        dashboard.stop(final=True)
    except Exception as exc:  # pragma: no cover - never block the shutdown
        xbmc.log(f"TinyPPI: stopping the web dashboard failed: {exc}",
                 xbmc.LOGERROR)

    del monitor
