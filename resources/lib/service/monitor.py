# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Background service (xbmc.service).

Keeps a Kodi monitor alive for the session to react to notifications, opens
views handed over by main.py, runs the splash and owns the web dashboard.
"""

import os
import sys
import threading

import xbmc

_LIB_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from core import images, settings
from core.constants import (
    ADDON_ID,
    OPEN_MESSAGES,
    OPEN_WITHDRAWN,
    PROP_OPEN_ACK,
    PROP_OPEN_REQUEST,
    PROP_SERVICE,
)
from core.log import channel
from core.utils import home_window
from ui import fonts
from ui.theme import apply_theme, migrate_legacy_colors
from web import library
from web.server import WebDashboard

# Notification methods that open a view.  A keymap can send one directly
# (NotifyAll(script.tinyppi,open_overlay)), the fastest way in: no script
# is started.
_OPEN_METHODS = {f"Other.{message}": view
                 for view, message in OPEN_MESSAGES.items()}

# Sent whenever a skin finishes loading (switch, update, or the reload the
# font install triggers).  The only signal that Font.xml may have changed:
# Monitor has no onSkinChanged callback.
_SKIN_LOADED = "GUI.OnSkinLoaded"

# Delay after a skin load before the font check writes to the skin.
_SKIN_SETTLE = 1.0

# Delay before the startup warm-up (font entries, view imports), so it does
# not compete with Kodi's own startup.
_WARMUP_DELAY = 5.0

# Notifications that make the dashboard's cached lists stale.  The lists are
# dropped and re-read on the next request (see web/library.py).  Item
# notifications come in bursts (a scan sends one per item) and are coalesced
# into one drop; the end of a scan or a clean drops the lists at once.
_LIBRARY_ITEM_NOTIFICATIONS = (
    "VideoLibrary.OnUpdate",
    "VideoLibrary.OnRemove",
)
_LIBRARY_DONE_NOTIFICATIONS = (
    "VideoLibrary.OnScanFinished",
    "VideoLibrary.OnCleanFinished",
)

# Playback stop: resume point or play count are about to change.  Kodi
# writes them after this notification and announces only the play count, so
# the library is told to expect a change (see ``library.settle``).
_PLAYBACK_ENDED = "Player.OnStop"


_log = channel("service")


class KodiMonitor(xbmc.Monitor):
    """Handle Kodi notifications and own the web dashboard's lifecycle.

    The monitor is the only object that lives for the whole Kodi session.
    """

    def __init__(self, dashboard: WebDashboard | None = None) -> None:
        super().__init__()
        self._dashboard = dashboard
        # Held while a splash controller runs.
        self._splash_lock = threading.Lock()

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if sender == ADDON_ID and method in _OPEN_METHODS:
            self._open_view(_OPEN_METHODS[method])
            return

        if method == _SKIN_LOADED:
            self._check_fonts()

        if method == "Player.OnAVStart":
            self._maybe_show_splash()

        if method in _LIBRARY_DONE_NOTIFICATIONS:
            library.invalidate()
        elif method in _LIBRARY_ITEM_NOTIFICATIONS:
            library.changed()
        elif method == _PLAYBACK_ENDED:
            library.settle()

        # Every notification arrives here (a library scan sends one per
        # item), so the payload is logged unparsed.
        _log(f"sender={sender}  method={method}  data={data[:200]}")

    def onSettingsChanged(self) -> None:
        """Start the splash if needed and apply the dashboard settings.

        A running splash picks up changes itself; this covers enabling a
        trigger during playback when all were off at start.
        """
        self._maybe_show_splash()
        self.apply_dashboard_settings()

    def apply_dashboard_settings(self) -> None:
        """Start, stop or reconfigure the dashboard to match the settings.

        Failures are logged; they must not take the monitor down.
        """
        if self._dashboard is None:
            return
        try:
            self._dashboard.apply_settings()
        except Exception as exc:
            _log(f"Exception applying web dashboard settings: {exc}", xbmc.LOGERROR)

    def _check_fonts(self) -> None:
        """Register the overlay's font entries in the skin that just loaded.

        Each skin has its own Font.xml, so a switch or update loses the
        entries.  Runs on its own thread: it walks and may write the skin
        folder, and Kodi delivers notifications one at a time.  A no-op when
        the entries exist (as after the reload it triggers itself).
        """
        threading.Thread(target=self._install_fonts, daemon=True).start()

    def _install_fonts(self) -> None:
        """Wait for the skin to settle, then register the font entries."""
        if self.waitForAbort(_SKIN_SETTLE):
            return
        try:
            fonts.ensure_fonts()
        except Exception as exc:
            _log(f"Exception registering the fonts: {exc}", xbmc.LOGERROR)

    def _open_view(self, view: str) -> None:
        """Open the overlay or the VS10 dialog in this process.

        Acknowledges first, since the requesting launch is polling for it.
        The modal view runs on its own thread so it does not block Kodi's
        notification thread.
        """
        home  = home_window()
        token = home.getProperty(PROP_OPEN_REQUEST)
        home.setProperty(PROP_OPEN_ACK, token)

        home.clearProperty(PROP_OPEN_REQUEST)
        if token == OPEN_WITHDRAWN:
            # The launch gave up and opens the view itself.  The request is
            # cleared so the next one (a keymap leaves none) is not read as
            # withdrawn.
            return

        threading.Thread(
            target=self._run_view, args=(view,), daemon=True
        ).start()

    @staticmethod
    def _run_view(view: str) -> None:
        """Run a view's entry point until the viewer closes it.

        The entry points do their own checks (platform, playback, toggle),
        as with main.py.  Failures are logged, not raised.
        """
        try:
            from ui.overlay import open_dialog_mode, open_tinyppi
            if view == "dialog":
                open_dialog_mode()
            else:
                open_tinyppi()
        except Exception as exc:
            _log(f"Exception opening the {view} view: {exc}", xbmc.LOGERROR)

    def _maybe_show_splash(self) -> None:
        """Start the codec-logo splash when enabled for this video.

        Runs on a thread here instead of a new interpreter via ``RunScript``,
        which cost a full import on every playback start and settings change.
        Cheap checks run here; the splash re-checks before showing.
        """
        try:
            addon = settings.addon()
            if not (addon.getSettingBool("splash_enabled")
                    or addon.getSettingBool("splash_show_on_osd")
                    or addon.getSettingBool("splash_show_on_tinyppi")):
                return
            if not xbmc.getCondVisibility("Player.HasVideo"):
                return
        except Exception as exc:
            _log(f"Exception starting splash: {exc}", xbmc.LOGERROR)
            return

        # One controller at a time here; the splash's Home-window guard also
        # stops one started via main.py from stacking.
        if not self._splash_lock.acquire(blocking=False):
            return
        threading.Thread(
            target=self._run_splash, name="TinyPPI-splash", daemon=True,
        ).start()

    def _run_splash(self) -> None:
        """Run the splash controller until its video ends."""
        try:
            from ui.splash import open_splash
            open_splash()
        except Exception as exc:
            _log(f"Exception in the splash: {exc}", xbmc.LOGERROR)
        finally:
            self._splash_lock.release()


def _warm_up(monitor: xbmc.Monitor) -> None:
    """Do the slow first-launch work in the background once per session.

    Registers the font entries (walks and parses the skin's Font.xml),
    imports the view modules (a few hundred KB of Python) and prunes the
    splash texture cache, which also runs after an add-on update.
    """
    if monitor.waitForAbort(_WARMUP_DELAY):
        return

    try:
        # A no-op if the skin-load notification already did this.
        fonts.ensure_fonts()
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"registering the fonts failed: {exc}", xbmc.LOGWARNING)

    # Both views, as the button may open either.  The DV metadata view is the
    # largest and only reached from the overlay, so it loads on first use.
    try:
        import ui.mode_select  # noqa: F401  imported to have it loaded, not used
        import ui.overlay      # noqa: F401
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"pre-loading the views failed: {exc}", xbmc.LOGWARNING)

    # Cached logo textures whose logo has changed or gone (see core.images).
    try:
        media = os.path.join(settings.addon().getAddonInfo("path"),
                             "resources", "skins", "Default", "media")
        removed = images.prune_cache(media)
        if removed:
            _log(f"removed {removed} outdated cached logo texture(s)", xbmc.LOGINFO)
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"tidying the texture cache failed: {exc}", xbmc.LOGWARNING)


if __name__ == "__main__":
    addon     = settings.addon()
    win       = home_window()
    dashboard = WebDashboard()
    monitor   = KodiMonitor(dashboard)

    # Colors from before the color picker are stored as a palette index (or
    # 999 for HEX) and would show as bare numbers.  Rewritten once.
    try:
        moved = migrate_legacy_colors(addon)
        if moved:
            _log(f"carried {moved} color setting(s) over to the color picker",
                 xbmc.LOGINFO)
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"carrying the color settings over failed: {exc}", xbmc.LOGWARNING)

    # Publish the theme so the skin has every color before the first view.
    try:
        apply_theme(win, addon)
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"apply_theme at startup failed: {exc}", xbmc.LOGWARNING)

    # Starts the dashboard at boot if it is enabled.
    monitor.apply_dashboard_settings()

    # Lets main.py hand views over to this process.  Set before the warm-up:
    # the handover works either way and saves early launches the imports.
    win.setProperty(PROP_SERVICE, "1")

    threading.Thread(target=_warm_up, args=(monitor,), daemon=True).start()

    _log("KodiMonitor started", xbmc.LOGINFO)

    # Block until Kodi shuts down; notifications arrive on their own thread.
    monitor.waitForAbort()

    # No handovers during shutdown.
    win.clearProperty(PROP_SERVICE)

    # No thread may outlive this script: after it returns, CPythonInvoker
    # waits without timeout for every interpreter thread, daemons included,
    # so a running web server would stall Kodi's shutdown.  Kodi also raises
    # SystemExit after five seconds, so this comes first and must not raise.
    try:
        dashboard.stop(final=True)
    except Exception as exc:  # pragma: no cover - never block the shutdown
        _log(f"stopping the web dashboard failed: {exc}", xbmc.LOGERROR)

    del monitor
