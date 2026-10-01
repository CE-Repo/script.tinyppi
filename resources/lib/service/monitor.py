# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Background service (xbmc.service): keeps a Kodi monitor alive for the session
so the addon can react to system notifications."""

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
from ui.theme import apply_theme
from web import library
from web.server import WebDashboard

# Notification methods that open a view, and the view each one opens.  A
# keymap can send one straight to us -- NotifyAll(script.tinyppi,open_overlay)
# -- which is the fastest way in there is: no script is started at all.
_OPEN_METHODS = {f"Other.{message}": view
                 for view, message in OPEN_MESSAGES.items()}

# What Kodi announces whenever a skin finishes loading: a skin switched by
# hand, a skin updated under a running Kodi, and the reload the font install
# triggers itself.  It is the one signal there is for "the Font.xml the overlay
# relies on may not be the one we checked" -- the Python Monitor has no
# onSkinChanged callback, and there is no announcement for an addon update.
_SKIN_LOADED = "GUI.OnSkinLoaded"

# How long the font check holds off after a skin load, letting Kodi finish
# settling into the new skin before anything is written under it.
_SKIN_SETTLE = 1.0

# How long after startup the warm-up runs.  It registers the overlay's font
# entries in the skin and imports the view modules, so the first launch of the
# session finds both done; held off briefly so none of it lands in the middle
# of Kodi still starting up.
_WARMUP_DELAY = 5.0

# The notifications that mean the film list the dashboard offers is no longer
# what the video database holds.  Kodi says so rather than leaving it to be
# polled, so the held list is simply dropped here and read again by whichever
# phone asks next -- a scan finishing while nobody is looking at a dashboard
# costs nothing at all (see web/library.py).
_LIBRARY_NOTIFICATIONS = (
    "VideoLibrary.OnUpdate",
    "VideoLibrary.OnRemove",
    "VideoLibrary.OnScanFinished",
    "VideoLibrary.OnCleanFinished",
)

# And the one that means it is about to.  A title being switched off in the
# middle moves where the box would resume it from, and one watched to the end
# moves its play count -- both of which every phone in the house is drawing on
# a tile right now.  Kodi writes them after it has said that playback stopped,
# and announces only the play count when it does, so the stop is passed on as
# notice rather than as fact: see ``library.settle``.
_PLAYBACK_ENDED = "Player.OnStop"


_log = channel("service")


class KodiMonitor(xbmc.Monitor):
    """Listens for Kodi notifications; fires the splash on playback start.

    Also owns the web dashboard's lifecycle: it is started and stopped from
    here because this is the one thing that lives for the whole Kodi session.
    """

    def __init__(self, dashboard: WebDashboard | None = None) -> None:
        super().__init__()
        self._dashboard = dashboard
        # Held for as long as a splash controller runs on its thread.
        self._splash_lock = threading.Lock()

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if sender == ADDON_ID and method in _OPEN_METHODS:
            self._open_view(_OPEN_METHODS[method])
            return

        if method == _SKIN_LOADED:
            self._check_fonts()

        if method == "Player.OnAVStart":
            self._maybe_show_splash()

        if method in _LIBRARY_NOTIFICATIONS:
            library.invalidate()
        elif method == _PLAYBACK_ENDED:
            library.settle()

        # Every notification Kodi sends arrives here -- a library scan sends
        # one per item -- so the payload goes into the line as it came rather
        # than parsed for it.
        _log(f"sender={sender}  method={method}  data={data[:200]}")

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

    def _check_fonts(self) -> None:
        """Register the overlay's font entries in the skin that just loaded.

        A skin brings its own Font.xml, so a switch or an update of the one in
        use leaves the entries behind in a file nothing reads any more.  This
        is what puts them back, and it is also what the mark ensure_fonts()
        reads is re-taken by.

        Off the announcement thread: the check walks the skin directory and may
        write to it, and Kodi is handing out its announcements one at a time.
        The check no-ops when the entries are already there, which is what the
        reload it triggers itself comes back to.
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

        Acknowledging is the first thing done, and it is done here rather than
        in the thread below: the launch that asked is sitting in a poll loop
        waiting for it, and every millisecond of that is a millisecond of the
        delay this whole path exists to remove.  The view itself goes to a
        thread of its own because it is modal -- run here it would block Kodi's
        announcement thread for as long as the overlay stayed up.
        """
        home  = home_window()
        token = home.getProperty(PROP_OPEN_REQUEST)
        home.setProperty(PROP_OPEN_ACK, token)

        home.clearProperty(PROP_OPEN_REQUEST)
        if token == OPEN_WITHDRAWN:
            # The launch stopped waiting and is opening the view itself.  The
            # request is dropped along with it, so the next one -- a keymap
            # that notifies us directly leaves none of its own -- is not read
            # as withdrawn too.
            return

        threading.Thread(
            target=self._run_view, args=(view,), daemon=True
        ).start()

    @staticmethod
    def _run_view(view: str) -> None:
        """Run a view's entry point, which returns when the viewer closes it.

        The entry points carry every guard themselves -- the platform checks,
        "is something playing", and the toggle-close when TinyPPI is already
        up -- so this hands over to them exactly as main.py does, and a failure
        in one of them must not take the service with it.
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
        """Fire the format-logo splash when enabled for this video.

        Runs on a thread of this process rather than in a script interpreter
        of its own: ``RunScript`` started a whole interpreter and imported the
        splash into it on every playback start and on every settings change
        while something played, only for most of them to find a controller
        already running and leave.  Cheap guards run here first; the splash
        re-checks everything before showing.
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

        # One controller at a time in here; the splash's own Home-window guard
        # still keeps one started through main.py from stacking on this one.
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
    """Get the work a launch used to pay for out of the way, off to one side.

    Registering the font entries means walking the skin directory for its
    Font.xml and parsing it, and the view modules are a few hundred
    kilobytes of Python to import.  Both used to happen inside the launch the
    viewer was waiting on; done here they happen once, while nobody is
    waiting, and every launch of the session finds them done.

    The splash's texture cache is tidied here too, which is also the first
    thing that runs after an add-on update restarts the service.
    """
    if monitor.waitForAbort(_WARMUP_DELAY):
        return

    try:
        # The skin-load announcement may already have covered this while Kodi
        # was starting; ensure_fonts() is what makes that a no-op.
        fonts.ensure_fonts()
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"registering the fonts failed: {exc}", xbmc.LOGWARNING)

    # Both views, since either one can be what the button is set to open.  The
    # Dolby Vision metadata view is left out on purpose: it is off out of the
    # box and is the largest of them, so it stays loaded on first use.
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

    # Publish the theme properties at startup so the settings dialog can preview
    # custom HEX colors before the overlay has been opened this session.
    try:
        apply_theme(win, addon)
    except Exception as exc:  # pragma: no cover - never block the service
        _log(f"apply_theme at startup failed: {exc}", xbmc.LOGWARNING)

    # Off unless the user switched it on; this is what starts it at boot.
    monitor.apply_dashboard_settings()

    # Tells main.py it may hand a view over here rather than opening it in a
    # script interpreter of its own.  Set before the warm-up rather than after
    # it: the handover works either way, and a launch in the first few seconds
    # of a session then still skips the import pass.
    win.setProperty(PROP_SERVICE, "1")

    threading.Thread(target=_warm_up, args=(monitor,), daemon=True).start()

    _log("KodiMonitor started", xbmc.LOGINFO)

    # Block until Kodi shuts down; notifications arrive on their own thread.
    monitor.waitForAbort()

    # Nothing may be handed over once this is on its way out.
    win.clearProperty(PROP_SERVICE)

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
        _log(f"stopping the web dashboard failed: {exc}", xbmc.LOGERROR)

    del monitor
