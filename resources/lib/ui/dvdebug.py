"""Dolby Vision debug view: everything the stream's side data carries.

The overlay shows the readings that fit its rows.  This view is the other half
of that: pressing OK on a Dolby Vision source hands over to it, and it lists
every block ``script.module.sidedata`` parsed out of the raw payload -- the
configuration record, the RPU from its header through L11, the static SEIs --
one line each, live, for the frame on screen.  OK hands back to the overlay,
Back closes both (see ui.overlay.open_tinyppi, which switches between the two).

The rows themselves come from info.dvdebug; this module is the window around
them: it fills the list, keeps it current, and gets out of the way again.  The
one thing it says of its own accord is which readings just moved -- a refresh
writes those in the highlight color for as long as they keep moving, so a list
this long can be read as a live one.
"""

import re
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

# Home window, where ui.theme publishes the colors the skin resolves.
_HOME = 10000

# A reading that moved since the last refresh is written in this color for the
# one second it stays changed, so the eye finds what is live among rows that
# mostly stand still -- the trims and the frame luminance move with the
# picture, the title-level blocks do not.  Its own setting (Debug -> Changed
# values), published by ui.theme like every other color.
_CHANGED_COLOR = "TinyPPI.DebugChangedColor"

# Used when that property is not published, which means apply_theme never ran.
# The highlighting is the whole point of a view that refreshes, so a missing
# color costs the viewer's choice of color, not the highlighting itself.
_CHANGED_FALLBACK = "FF82B1FF"  # Light blue, the setting's own default

# Splits a value into the readings it carries: the wide lines run a whole trim
# pass across one row, separated by runs of spaces, and it is the reading that
# moved that should light up rather than the line it sits on.
_GAP = re.compile(r"(\s{2,})")

# Seconds between refreshes, matching the overlay's own polling interval: the
# per-frame blocks (L1, L5, the trims) move with the picture, so they are worth
# re-reading, but not faster than a viewer can read them.
_REFRESH = 1.0

# Actions arriving within this many seconds of the window opening are ignored,
# so the key press that opened it cannot immediately close it again.
_SETTLE = 0.3


def _identities(rows: list) -> list:
    """Give every row a key that survives a rebuild.

    Its kind and name, plus which repeat of them it is -- names are not unique
    on their own, MaxCLL appearing under both L6 and the static SEIs.  The
    identity is what a value is remembered against, so a row keeps its history
    across a rebuild: a stream whose DM compression alternates drops and
    restores whole sections from one frame to the next, and the readings that
    stayed put through that should not read as new.
    """
    seen: dict = {}
    keys = []
    for kind, name, _value in rows:
        repeat = seen.get((kind, name), 0)
        seen[(kind, name)] = repeat + 1
        keys.append((kind, name, repeat))
    return keys


def _shown(previous, current: str, color: str) -> str:
    """The text to write into a row: its value, with whatever moved in it
    highlighted.  A row that was not on screen before has nothing it could
    have changed from, so it goes up plain."""
    if previous is None or previous == current:
        return current
    return _marked(previous, current, color)


def _marked(previous: str, current: str, color: str) -> str:
    """Return *current* with the readings that differ from *previous* colored.

    A two-column value is one reading and lights up whole.  A wide line is a
    whole trim pass, so it is compared reading by reading and only the ones
    that moved are colored -- a pass where the slope changed should point at
    the slope, not at the eight numbers beside it.  A line that gained or lost
    a reading no longer lines up with the one before it and lights up whole.
    """
    if not color:
        return current
    parts = _GAP.split(current)
    before = _GAP.split(previous)
    if len(parts) != len(before):
        return f"[COLOR={color}]{current}[/COLOR]"
    return "".join(
        part if index % 2 or part == before[index]
        else f"[COLOR={color}]{part}[/COLOR]"
        for index, part in enumerate(parts)
    )


class DVDebugDialog(xbmcgui.WindowXMLDialog):
    """The metadata list.  Closes on OK (back to the overlay), on Back, and on
    its own once playback stops or leaves the fullscreen video window."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        # Row identities currently in the list, so a refresh that only changes
        # values leaves the list itself alone, and the value each identity was
        # last filled with, which is what a refresh highlights against.  Keyed
        # by identity rather than by position so a rebuild does not lose it
        # (see _identities).
        self._keys: list = []
        self._values: dict = {}
        self._closing        = False
        self._refresh_failed = False
        self._color_missing  = False
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
    def _item(row: tuple[str, str, str], label: str) -> xbmcgui.ListItem:
        """Build the list item for one row, showing *label* as its value; the
        skin picks its layout from the ``kind`` property."""
        kind, name, _value = row
        item = xbmcgui.ListItem(name, label)
        item.setProperty("kind", kind)
        return item

    def _changed_color(self) -> str:
        """The highlight color the theme published, or the setting's own
        default when it did not -- and a line in the log saying so, since a
        view that quietly stops highlighting looks like one that has nothing
        to highlight."""
        color = xbmcgui.Window(_HOME).getProperty(_CHANGED_COLOR)
        if color:
            return color
        if not self._color_missing:
            self._color_missing = True
            xbmc.log(
                f"TinyPPI: {_CHANGED_COLOR} is not published, highlighting "
                f"changed values in {_CHANGED_FALLBACK} instead",
                xbmc.LOGWARNING,
            )
        return _CHANGED_FALLBACK

    def _fill(self, rows: list) -> None:
        """Put *rows* in the list, rebuilding it only when it has to be.

        The values change every second; the rows they sit in almost never do.
        Rebuilding regardless would throw away where the viewer had scrolled
        to, so a refresh normally just writes the new values into the items
        that are already there.  A structural change -- a stream that starts
        carrying trim passes, a section the frame no longer has any readings
        for -- does rebuild, and carries the scroll position over so the list
        does not jump back to the top underneath the viewer.

        Either way the values that moved go up in the highlight color, which
        is the whole point of a view that refreshes: with sixty rows on
        screen, a reading that changed is worth nothing if it cannot be told
        from the fifty-nine that did not.  The comparison is by identity, not
        by position, so the rows a rebuild kept are still compared against
        what they said before it.
        """
        control = self.getControl(_LIST)
        keys   = _identities(rows)
        values = dict(zip(keys, (value for _kind, _name, value in rows)))
        color  = self._changed_color()
        labels = [_shown(self._values.get(key), values[key], color)
                  for key in keys]

        if keys != self._keys:
            position = control.getSelectedPosition()
            control.reset()
            control.addItems([
                self._item(row, label) for row, label in zip(rows, labels)
            ])
            self._keys = keys
            if 0 < position < len(rows):
                control.selectItem(position)
        else:
            for index, label in enumerate(labels):
                control.getListItem(index).setLabel2(label)

        self._values = values

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
