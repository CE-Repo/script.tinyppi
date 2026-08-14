"""Dolby Vision debug view: everything the stream's side data carries.

The overlay shows the readings that fit its rows.  This view is the other half
of that: pressing OK on a Dolby Vision source hands over to it, and it lists
every block ``script.module.sidedata`` parsed out of the raw payload -- the
configuration record, the RPU from its header through L11, the static SEIs --
one line each, live, for the frame on screen.  OK hands back to the overlay,
Back closes both (see ui.overlay.open_tinyppi, which switches between the two).

The rows themselves come from info.dvdebug; this module is the window around
them: it fills the list, keeps it current, and gets out of the way again.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from info import dvdebug

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

# The list holding the metadata rows (see script-tinyppi-dv-debug.xml).
_LIST = 6000

# Seconds between refreshes, matching the overlay's own polling interval: the
# per-frame blocks (L1, L5, the trims) move with the picture, so they are worth
# re-reading, but not faster than a viewer can read them.
_REFRESH = 1.0

# Actions arriving within this many seconds of the window opening are ignored,
# so the key press that opened it cannot immediately close it again.
_SETTLE = 0.3


class DVDebugDialog(xbmcgui.WindowXMLDialog):
    """The metadata list.  Closes on OK (back to the overlay), on Back, and on
    its own once playback stops or leaves the fullscreen video window."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        # Row identities currently in the list, so a refresh that only changes
        # values leaves the list itself alone (see _fill).
        self._keys: list = []
        self._closing        = False
        self._refresh_failed = False
        # Read by open_dv_debug() once doModal() returns: True when the viewer
        # asked for the overlay back rather than for the overlay to end.
        self.back_to_overlay = False

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        # Unlike the overlay, whose properties can be published before Kodi
        # builds the window, a list has to be filled through its control -- so
        # the first fill happens here, under the opening fade.
        try:
            self._fill(dvdebug.build_rows())
        except Exception as exc:
            self._log_refresh_failure(exc)
        self.setFocusId(_LIST)
        threading.Thread(target=self._update_loop, daemon=True).start()

    # --- List ---------------------------------------------------------------

    @staticmethod
    def _item(row: tuple[str, str, str]) -> xbmcgui.ListItem:
        """Build the list item for one row; the skin picks its layout from the
        ``kind`` property."""
        kind, name, value = row
        item = xbmcgui.ListItem(name, value)
        item.setProperty("kind", kind)
        return item

    def _fill(self, rows: list) -> None:
        """Put *rows* in the list, rebuilding it only when it has to be.

        The values change every second; the rows they sit in almost never do.
        Rebuilding regardless would throw away where the viewer had scrolled
        to, so a refresh normally just writes the new values into the items
        that are already there.  A structural change -- a stream that starts
        carrying trim passes, an HDR10+ section appearing -- does rebuild, and
        carries the scroll position over so the list does not jump back to the
        top underneath the viewer.
        """
        control = self.getControl(_LIST)
        keys = [(kind, name) for kind, name, _value in rows]

        if keys != self._keys:
            position = control.getSelectedPosition()
            control.reset()
            control.addItems([self._item(row) for row in rows])
            self._keys = keys
            if 0 < position < len(rows):
                control.selectItem(position)
            return

        for index, (_kind, _name, value) in enumerate(rows):
            control.getListItem(index).setLabel2(value)

    # --- Input --------------------------------------------------------------

    def _settled(self) -> bool:
        """False while the opening key press could still be arriving."""
        return time.time() - self._opened_at >= _SETTLE

    def onClick(self, control_id: int) -> None:
        # OK on the focused list.  Kodi delivers the same press to onAction as
        # well, hence the guard in _close.
        if control_id == _LIST and self._settled():
            self._close(back_to_overlay=True)

    def onAction(self, action: xbmcgui.Action) -> None:
        action_id = action.getId()
        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            # The press that opened this view is the one action that must not
            # be acted on; nothing else needs the settling guard.
            if self._settled():
                self._close(back_to_overlay=True)
        elif action_id in (
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_STOP,
        ):
            # Kodi's own handling has already closed the window by now; this
            # records the answer and stops the refresh thread with it.
            self._close(back_to_overlay=False)

    def _close(self, back_to_overlay: bool) -> None:
        """Close once, remembering what the viewer asked for."""
        if self._closing:
            return
        self._closing        = True
        self.back_to_overlay = back_to_overlay
        self._running        = False
        try:
            self.close()
        except Exception:
            pass

    # --- Refresh ------------------------------------------------------------

    def _update_loop(self) -> None:
        """Re-read the side data once a second until the view should close.

        Mirrors the overlay's loop, and for the same reasons: a failed refresh
        costs one stale second rather than the window, and the close runs from
        ``finally`` so an unforeseen failure still puts the view away instead
        of leaving it up and frozen over the film.
        """
        player = xbmc.Player()

        try:
            while self._running and not self._monitor.abortRequested():
                if not player.isPlaying():
                    break
                if not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
                    break

                try:
                    self._fill(dvdebug.build_rows())
                except Exception as exc:
                    self._log_refresh_failure(exc)

                if self._monitor.waitForAbort(_REFRESH):
                    break
        finally:
            # Playback ended under the view: close it for good, not back to an
            # overlay that has nothing left to show either.
            self._close(back_to_overlay=False)

    def _log_refresh_failure(self, exc: Exception) -> None:
        """Log a failed refresh once per view, so a persistent fault leaves a
        trace without writing to the log every second."""
        if self._refresh_failed:
            return
        self._refresh_failed = True
        xbmc.log(
            f"TinyPPI: DV debug refresh failed, continuing with the last "
            f"values: {exc}",
            xbmc.LOGWARNING,
        )


def open_dv_debug() -> bool:
    """Show the debug view; True when OK asked for the overlay back."""
    dialog = DVDebugDialog(
        "script-tinyppi-dv-debug.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    dialog.doModal()
    back_to_overlay = dialog.back_to_overlay
    del dialog
    return back_to_overlay
