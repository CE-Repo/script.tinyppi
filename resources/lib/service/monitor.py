"""Background service (xbmc.service): keeps a Kodi monitor alive for the session
so the addon can react to system notifications."""

import json
import os
import sys
import threading

import xbmc
import xbmcaddon
import xbmcgui

_LIB_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from info.dvinfo import prime_playback_detection, reset_playback_cache
from info.properties import prewarm_channel_textures
from ui.theme import apply_theme

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
    """Listens for Kodi notifications; resets the DV cache on stop and, on
    playback start, preloads the metadata detection and fires the splash."""

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if method == "Player.OnStop":
            reset_playback_cache()
            _log("Dolby Vision playback cache cleared")

        if method == "Player.OnAVStart":
            self._prime_detection()
            self._prewarm_channel_textures()
            self._maybe_show_splash()

        try:
            mediatype = _notification_media_type(data)
            _log(f"sender={sender}  method={method}  type={mediatype!r}")
        except Exception as exc:
            _log(f"Exception in KodiMonitor.onNotification: {exc}", xbmc.LOGERROR)

    def onSettingsChanged(self) -> None:
        """(Re)launch the splash when settings change.

        A running controller picks up edits on its own (its guard makes this a
        no-op); this covers the case where all triggers were off at playback
        start, so enabling one here starts it without restarting playback.
        """
        self._maybe_show_splash()

    def _prime_detection(self) -> None:
        """Start hdrprobe / audio detection as soon as a video begins playing.

        Runs the same background scan the overlay would trigger lazily, so the
        Dolby Vision, HDR and audio metadata are already cached and shown
        instantly when the overlay (or dialog mode) is opened — no ``Fetching...``.
        """
        try:
            if not xbmc.getCondVisibility("Player.HasVideo"):
                return
            if prime_playback_detection():
                _log("Preloading playback metadata in background")
        except Exception as exc:
            _log(f"Exception priming detection: {exc}", xbmc.LOGERROR)

    def _prewarm_channel_textures(self) -> None:
        """Scale the channel graphics for this track in the background.

        Scaling is pure Python and takes a moment per graphic, so it runs on its
        own thread: the notification handler returns at once and the work is
        done long before the user can open the overlay.  Cached results make
        every later playback a no-op.
        """
        try:
            if not xbmc.getCondVisibility("Player.HasVideo"):
                return
            threading.Thread(
                target=self._prewarm_worker, name="TinyPPI-prewarm", daemon=True
            ).start()
        except Exception as exc:
            _log(f"Exception starting channel prewarm: {exc}", xbmc.LOGERROR)

    @staticmethod
    def _prewarm_worker() -> None:
        try:
            prewarm_channel_textures()
            _log("Channel textures ready")
        except Exception as exc:
            _log(f"Exception prewarming channel textures: {exc}", xbmc.LOGERROR)

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
    addon   = xbmcaddon.Addon()
    win     = xbmcgui.Window(_HOME_WINDOW_ID)
    monitor = KodiMonitor()

    reset_playback_cache()

    # Publish the theme properties at startup so the settings dialog can preview
    # custom HEX colors before the overlay has been opened this session.
    try:
        apply_theme(win, addon)
    except Exception as exc:  # pragma: no cover - never block the service
        xbmc.log(f"TinyPPI: apply_theme at startup failed: {exc}", xbmc.LOGWARNING)

    xbmc.log("TinyPPI: KodiMonitor started", xbmc.LOGINFO)

    # Block until Kodi shuts down; notifications arrive on their own thread.
    monitor.waitForAbort()

    del monitor
