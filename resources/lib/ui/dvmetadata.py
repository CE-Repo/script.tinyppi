"""Dolby Vision metadata view: everything the stream's side data carries.

The overlay shows the readings that fit its rows.  This view is the other half
of that: pressing OK on a Dolby Vision source hands over to it, and it lists
every block ``script.module.sidedata`` parsed out of the raw payload -- the
configuration record, the RPU from its header through L11, the static SEIs --
one line each, live, for the frame on screen.  OK hands back to the overlay,
Back closes both (see ui.overlay.open_tinyppi, which switches between the two).

The rows themselves come from info.dvmetadata; this module is the window around
them: it fills the list, keeps it current, and gets out of the way again.  The
one thing it says of its own accord is which readings just moved -- a refresh
writes those in the highlight color for as long as they keep moving, so a list
this long can be read as a live one.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from core.utils import highlight_changes
from info import dvmetadata

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

# The list holding the metadata rows (see script-tinyppi-dv-metadata.xml).
_LIST = 6000

# Home window, where ui.theme publishes the colors the skin resolves.
_HOME = 10000

# A reading that moved since the last refresh is written in this color for the
# one second it stays changed, so the eye finds what is live among rows that
# mostly stand still -- the trims and the frame luminance move with the
# picture, the title-level blocks do not.  Its own setting (Metadata -> Changed
# values), published by ui.theme like every other color.
_CHANGED_COLOR = "TinyPPI.MetadataChangedColor"

# Used when that property is not published, which means apply_theme never ran.
# The highlighting is the whole point of a view that refreshes, so a missing
# color costs the viewer's choice of color, not the highlighting itself.
_CHANGED_FALLBACK = "FF82B1FF"  # Light blue, the setting's own default

# The rule drawn under a section heading.  Named per row rather than by the
# skin, because the layout is shared: the image control that draws it is on
# every row and takes its texture from the item, so the rows that name none
# draw none.
_RULE_TEXTURE = "common/dot-1x1.png"

# Property name each cell of a table row goes into: the skin has a label per
# column reading one of these, so cell 0 lands in the first fixed slot, cell 1
# in the second, and a cell nobody filled draws nothing.  Headings and
# readings take separate ones so the skin can draw them in separate colors.
_CELL_HEADING = "h"
_CELL_VALUE   = "c"

# Seconds between refreshes, matching the overlay's own polling interval: the
# per-frame blocks (L1, L5, the trims) move with the picture, so they are worth
# re-reading, but not faster than a viewer can read them.
_REFRESH = 1.0

# Actions arriving within this many seconds of the window opening are ignored,
# so the key press that opened it cannot immediately close it again.
_SETTLE = 0.3

# What the arrow keys move by: a section, not a row.  Page up and down step
# the same way rather than by a screenful -- a screenful of a list whose rows
# are only readable in blocks would land the viewer mid-block.  Fetched by
# name because not every Kodi build exposes the paging actions.
_STEP_ACTIONS = {
    action: step
    for action, step in (
        (getattr(xbmcgui, "ACTION_MOVE_UP", None), -1),
        (getattr(xbmcgui, "ACTION_MOVE_DOWN", None), 1),
        (getattr(xbmcgui, "ACTION_PAGE_UP", None), -1),
        (getattr(xbmcgui, "ACTION_PAGE_DOWN", None), 1),
    )
    if action is not None
}


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


def _areas(rows: list) -> list:
    """Where each section starts and ends, as ``(heading row, title, last
    row)``.

    What the viewer moves between: a section is the unit that means something,
    a row of it on its own is a number without its neighbours.  The blank row
    ahead of a heading belongs to neither section, so it is left out of both --
    it is spacing, not something to land on.
    """
    starts = [index for index, (kind, _name, _value) in enumerate(rows)
              if kind == dvmetadata.SECTION]
    areas = []
    for position, start in enumerate(starts):
        end = (starts[position + 1] - 1 if position + 1 < len(starts)
               else len(rows) - 1)
        while end > start and rows[end][0] == dvmetadata.SPACE:
            end -= 1
        areas.append((start, rows[start][1], end))
    return areas


class DVMetadataDialog(xbmcgui.WindowXMLDialog):
    """The metadata list.  Closes on OK (back to the overlay), on Back, and on
    its own once playback stops or leaves the fullscreen video window.

    The arrow keys move between sections rather than between rows: this is a
    list to read a block of at a time, and stepping through sixty rows to
    reach the next heading is not reading.  Each jump puts the whole section
    on screen where it fits."""

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
        # The sections the arrow keys move between, and which one the viewer
        # is on -- held by title rather than by number, so a section that
        # comes or goes with the frame does not shift the view out from under
        # them (see _focus_area).
        self._areas: list = []
        self._area_title  = ""
        # Read by open_dv_metadata() once doModal() returns: True when the viewer
        # asked for the overlay back rather than for the overlay to end.
        self.back_to_overlay = False

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        # Unlike the overlay, whose properties can be published before Kodi
        # builds the window, a list has to be filled through its control -- so
        # the first fill happens here, under the opening fade.
        try:
            self._fill(dvmetadata.build_rows())
        except Exception as exc:
            self._log_refresh_failure(exc)
        self.setFocusId(_LIST)
        threading.Thread(target=self._update_loop, daemon=True).start()

    # --- List ---------------------------------------------------------------

    @staticmethod
    def _write(item: xbmcgui.ListItem, kind: str, label) -> None:
        """Put a row's value into whichever of the item's fields draws it.

        A table row hands its cells over one property at a time, and clears
        the ones it has no cell for: the item is reused from refresh to
        refresh, so a column that goes away has to be emptied rather than left
        holding what it said last.
        """
        if kind not in (dvmetadata.HEADINGS, dvmetadata.COLUMNS):
            item.setLabel2(label)
            return
        prefix = _CELL_HEADING if kind == dvmetadata.HEADINGS else _CELL_VALUE
        for position in range(dvmetadata.MAX_COLUMNS):
            item.setProperty(
                f"{prefix}{position}",
                label[position] if position < len(label) else "",
            )

    @classmethod
    def _item(cls, row: tuple, label) -> xbmcgui.ListItem:
        """Build the list item for one row, showing *label* as its value.

        The skin draws every row through the same layout, because that is all
        a Kodi list container offers: its layout conditions are evaluated once
        for the whole list, not per row.  So what tells the kinds apart is
        which of the item's fields carry anything -- each control in the
        layout is fed one of them and draws nothing when it comes back empty.

        A heading puts its title in the ``head`` property, which is the one
        the large font is on, and names the texture for the rule under it.  A
        two-column row fills both labels.  A full-width line fills only the
        second, which spans the row.  A table row fills a property per cell,
        which is what puts each in a fixed column.  A blank row fills nothing.
        """
        kind, name, _value = row
        named = kind in (dvmetadata.ROW, dvmetadata.HEADINGS, dvmetadata.COLUMNS)
        item = xbmcgui.ListItem(name if named else "", "")
        if kind == dvmetadata.SECTION:
            item.setProperty("head", name)
            item.setProperty("rule", _RULE_TEXTURE)
        elif kind in (dvmetadata.ROW, dvmetadata.WIDE, dvmetadata.HEADINGS,
                      dvmetadata.COLUMNS):
            cls._write(item, kind, label)
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
        for -- does rebuild, and puts the viewer back on the section they were
        reading rather than at the top of the list.

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
        labels = [highlight_changes(self._values.get(key), values[key], color)
                  for key in keys]

        if keys != self._keys:
            control.reset()
            control.addItems([
                self._item(row, label) for row, label in zip(rows, labels)
            ])
            self._keys  = keys
            self._areas = _areas(rows)
            self._focus_area(self._area_index())
        else:
            for index, (row, label) in enumerate(zip(rows, labels)):
                self._write(control.getListItem(index), row[0], label)

        self._values = values

    # --- Sections -----------------------------------------------------------

    def _area_index(self) -> int:
        """Which section the viewer is on, found by its title.

        By title and not by number: sections come and go with the frame -- a
        block the stream stops carrying drops out of the list -- and a viewer
        reading L8 should still be reading L8 afterwards, not whatever has
        taken its place.  A section that goes away entirely leaves them on the
        one that has taken its number, which is the nearest thing to where
        they were.
        """
        for index, (_start, title, _end) in enumerate(self._areas):
            if title == self._area_title:
                return index
        return 0

    def _focus_area(self, index: int) -> None:
        """Move to section *index* and put as much of it on screen as fits.

        The list is asked for the section's last row first and for its heading
        second.  The first call scrolls far enough that the end of the section
        is in view; the second lands the selection on the heading and moves
        the list no further than it has to -- which leaves the whole section
        showing when it fits, and its heading at the top when it does not.
        """
        if not self._areas:
            return
        index = max(0, min(index, len(self._areas) - 1))
        start, title, end = self._areas[index]
        self._area_title = title
        control = self.getControl(_LIST)
        control.selectItem(end)
        control.selectItem(start)

    def _step_area(self, direction: int) -> None:
        """Move one section up or down."""
        self._focus_area(self._area_index() + direction)

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
        elif action_id in _STEP_ACTIONS:
            # The list has already moved itself a row by the time this runs --
            # Kodi hands the action to the control before the window sees it.
            # Nothing here reads where it ended up, so that does not matter:
            # the step is counted from the section the viewer was on, and the
            # selection is put back on a heading either way.
            self._step_area(_STEP_ACTIONS[action_id])

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
                    self._fill(dvmetadata.build_rows())
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
            f"TinyPPI: DV metadata refresh failed, continuing with the last "
            f"values: {exc}",
            xbmc.LOGWARNING,
        )


def open_dv_metadata() -> bool:
    """Show the metadata view; True when OK asked for the overlay back."""
    dialog = DVMetadataDialog(
        "script-tinyppi-dv-metadata.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    dialog.doModal()
    back_to_overlay = dialog.back_to_overlay
    del dialog
    return back_to_overlay
