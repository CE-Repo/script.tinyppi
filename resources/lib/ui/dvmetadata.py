"""Dolby Vision metadata view: everything the stream's side data carries.

The overlay shows the readings that fit its rows.  This view is the other half
of that: pressing OK on a Dolby Vision source hands over to it, and it lists
every block ``script.module.sidedata`` parsed out of the raw payload -- the
configuration record, the RPU from its header through L11, the static SEIs --
one line each, live, for the frame on screen.

Three views deep, and one key each way.  OK goes down -- from the overlay to
the list, and from a section of the list into a window holding that section
alone -- and Back comes up the same way, to the list, to the overlay, and out.
Nothing is ever nested: each window closes before the next one opens, and
open_dv_metadata below drives the list and its sections the way
ui.overlay.open_tinyppi drives the overlay and this.

The rows themselves come from info.dvmetadata; this module is the window around
them: it fills the list, keeps it current, and gets out of the way again.  The
one thing it says of its own accord is which readings just moved -- a refresh
writes those in the highlight color for as long as they keep moving, so a list
this long can be read as a live one.  Which is also why a heading whose block
this frame did not carry reads ``(Cached)``: what is on screen should say
whether it is the frame's own (see _write).
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

# The controls the window is cut down to size by, and the measurements the
# skin lays them out on.  A Kodi skin cannot size a panel from the number of
# rows in it -- coordinates are literals, and the list is not a grouplist that
# grows with its content -- so what the skin holds is the tallest the window
# ever gets, and _resize takes the rest off: a section of four readings should
# be a panel four readings tall, not a screenful of background under them.
#
# The three panel images (left cap, fill, right cap), the rule under the list
# and the two key hints below it, all of which follow the foot of the list.
_PANEL = (6100, 6101, 6102)
_RULE  = 6110
_HINTS = (6120, 6121)

# Where the list starts, how tall one row is, and how much panel there is
# below it -- the rule sits 25 px under its foot, the hint 45, and the panel
# ends 100 px under it.
_LIST_TOP  = 150
_ROW       = 30
_RULE_GAP  = 25
_HINT_GAP  = 45
_PANEL_GAP = 100

# Rows that fit before the panel stops growing, which is the height the skin
# itself is laid out at: 750 px of list.
_MAX_ROWS = 25

# Home window, where ui.theme publishes the colors the skin resolves.
_HOME = 10000

# Set while a single section is on screen rather than the whole list.  The two
# views share one window definition and differ in what the keys do, so this is
# what the skin draws the right key hint from -- and nothing else: the rows
# come through the list either way.
_SECTION_VIEW = "TinyPPI.MetadataSectionView"

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

# A row that fills nothing, which is what the items left over from a longer
# list are painted with: the list only ever grows, so a rebuild with fewer
# rows blanks the surplus in place rather than removing it (see _fill).
_BLANK_ROW = (dvmetadata.SPACE, "", "")

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
    """The metadata list.  Closes on OK into the section the viewer is on, on
    Back to the overlay, and on its own once playback stops or leaves the
    fullscreen video window.

    The arrow keys move between sections rather than between rows: this is a
    list to read a block of at a time, and stepping through sixty rows to
    reach the next heading is not reading.  Each jump puts the whole section
    on screen where it fits -- and OK on one of them opens it on its own, for
    the sections that do not fit at all."""

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
        # The list height the window is currently cut to, so a refresh that
        # leaves the row count alone leaves the geometry alone with it.
        self._list_height   = 0
        self._resize_failed = False
        # The sections the arrow keys move between, and which one the viewer
        # is on -- held by title rather than by number, so a section that
        # comes or goes with the frame does not shift the view out from under
        # them (see _focus_area).
        self._areas: list = []
        self._area_title  = ""
        # Set before doModal(): the section to open on, which is the one the
        # viewer was reading when they went into it, so coming back out of a
        # section lands where they left rather than at the top of the list.
        self.start_section = ""
        # Read by open_dv_metadata() once doModal() returns.  True when the
        # viewer asked for the view that opened this one -- the overlay for
        # the list, the list for a section -- rather than for it to end; and
        # the section OK asked to be opened on its own, if any.
        self.back_to_caller = False
        self.open_section   = ""

    def _rows(self) -> list:
        """The rows to show: all of them.  A section view narrows this."""
        return dvmetadata.build_rows()

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        self._area_title = self.start_section
        # Unlike the overlay, whose properties can be published before Kodi
        # builds the window, a list has to be filled through its control -- so
        # the first fill happens here, under the opening fade.
        try:
            self._fill(self._rows())
        except Exception as exc:
            self._log_refresh_failure(exc)
        self.setFocusId(_LIST)
        threading.Thread(target=self._update_loop, daemon=True).start()

    # --- List ---------------------------------------------------------------

    @staticmethod
    def _write(item: xbmcgui.ListItem, row: tuple, label) -> None:
        """Put a row's value into whichever of the item's fields draws it.

        A heading's value is not a reading but where the block under it came
        from, so it goes into ``state``, which the skin draws after the title
        in brackets -- ``L8 — Trims (Cached)`` for a section standing on a
        block held from an earlier frame, and nothing after the title for one
        the frame itself carried.  Beside the title and not in it: the title is
        what the view finds the viewer's section by (see _area_index), and one
        that changed with the frame would lose them.

        A table row hands its cells over one property at a time, and clears the
        ones it has no cell for -- the item is reused from refresh to refresh,
        so a column that goes away has to be emptied rather than left holding
        what it said last.
        """
        kind, _name, _value = row
        if kind == dvmetadata.SECTION:
            item.setProperty("state", label)
            return
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
    def _paint(cls, item: xbmcgui.ListItem, row: tuple, label) -> None:
        """Make *item* show *row*, with *label* as its value.

        The skin draws every row through the same layout, because that is all
        a Kodi list container offers: its layout conditions are evaluated once
        for the whole list, not per row.  So what tells the kinds apart is
        which of the item's fields carry anything -- each control in the
        layout is fed one of them and draws nothing when it comes back empty.

        A heading puts its title in the ``head`` property, which is the one
        the large font is on, its ``(Cached)`` in ``state`` beside it (see
        _write), and names the texture for the rule under it.  A two-column
        row fills both labels.  A full-width line fills only the second, which
        spans the row.  A table row fills a property per cell, which is what
        puts each in a fixed column.  A blank row fills nothing.

        Every field is written on every call, the unused ones with nothing:
        items outlive the row that was on them -- a rebuild hands an item
        whatever row now falls at its position -- so painting one is as much
        about what it stops saying as about what it says.
        """
        kind, name, _value = row
        heading = kind == dvmetadata.SECTION
        named   = kind in (dvmetadata.ROW, dvmetadata.HEADINGS,
                           dvmetadata.COLUMNS)
        table   = kind in (dvmetadata.HEADINGS, dvmetadata.COLUMNS)
        item.setLabel(name if named else "")
        item.setLabel2(label if kind in (dvmetadata.ROW, dvmetadata.WIDE)
                       else "")
        item.setProperty("head", name if heading else "")
        item.setProperty("state", label if heading else "")
        item.setProperty("rule", _RULE_TEXTURE if heading else "")
        for position in range(dvmetadata.MAX_COLUMNS):
            cell = label[position] if table and position < len(label) else ""
            item.setProperty(f"{_CELL_HEADING}{position}",
                             cell if kind == dvmetadata.HEADINGS else "")
            item.setProperty(f"{_CELL_VALUE}{position}",
                             cell if kind == dvmetadata.COLUMNS else "")

    @classmethod
    def _extend(cls, control: xbmcgui.ControlList, rows: list,
                labels: list) -> int:
        """Append the items a longer list needs, and say how many it had.

        Appending is one message to the GUI thread, which applies it whole, so
        the list is never drawn without its rows -- clearing it first is what
        would be seen (see _fill).  The new items are painted before they are
        handed over rather than after, for the same reason: what the GUI
        thread binds is already the rows it should show, not blanks waiting to
        be filled in.

        The count returned is the one from before the append: those are the
        items still holding an older row, and so the ones the caller has to
        paint.
        """
        held = control.size()
        if len(rows) > held:
            items = []
            for row, label in zip(rows[held:], labels[held:]):
                item = xbmcgui.ListItem("", "")
                cls._paint(item, row, label)
                items.append(item)
            control.addItems(items)
        return held

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
        """Put *rows* in the list, reusing the items already in it.

        The values change every second; the rows they sit in almost never do.
        Rewriting every row regardless would cost more than it buys, so a
        refresh normally just writes the new values into the items that are
        already there.  A structural change -- a stream that starts carrying
        trim passes, a section the frame no longer has any readings for --
        repaints all of them, and puts the viewer back on the section they
        were reading rather than at the top of the list.

        What no refresh does is empty the list first.  Clearing a Kodi list
        and refilling it are two separate messages to the GUI thread, which is
        free to draw the list between them: a block appearing mid-film -- L2
        or L8 arriving with a shot that needed trims -- would blank the whole
        view for a frame or more before the rows came back.  So the list only
        ever grows: items are appended when a rebuild wants more of them, and
        the ones a shorter rebuild leaves over are blanked in place rather
        than removed.  They cost nothing but a little empty room under the
        last section, and the next block to arrive lands in them.

        Either way the values that moved go up in the highlight color, which
        is the whole point of a view that refreshes: with sixty rows on
        screen, a reading that changed is worth nothing if it cannot be told
        from the fifty-nine that did not.  The comparison is by identity, not
        by position, so the rows a rebuild kept are still compared against
        what they said before it.

        Headings are the one thing left out of that.  What a heading carries
        is not a reading but where its block came from, and a section that
        goes in and out of being held would spend half the film lit up as
        though something in it had changed.
        """
        control = self.getControl(_LIST)
        keys   = _identities(rows)
        values = dict(zip(keys, (value for _kind, _name, value in rows)))
        color  = self._changed_color()
        labels = [
            values[key] if row[0] == dvmetadata.SECTION
            else highlight_changes(self._values.get(key), values[key], color)
            for row, key in zip(rows, keys)
        ]

        if keys != self._keys:
            held = self._extend(control, rows, labels)
            for index in range(min(held, len(rows))):
                self._paint(control.getListItem(index), rows[index],
                            labels[index])
            for index in range(len(rows), control.size()):
                self._paint(control.getListItem(index), _BLANK_ROW, "")
            self._keys  = keys
            self._areas = _areas(rows)
            self._resize(len(rows))
            self._focus_area(self._area_index())
        else:
            for index, (row, label) in enumerate(zip(rows, labels)):
                self._write(control.getListItem(index), row, label)

        self._values = values

    # --- Geometry -----------------------------------------------------------

    def _resize(self, shown: int) -> None:
        """Cut the window down to the *shown* rows it has to hold.

        The list keeps every item it has ever been given -- blanking the ones
        a shorter refresh leaves over rather than removing them, which is what
        keeps it from blinking (see _fill) -- so the height comes from the row
        count passed in, not from the size of the control's own list.

        Everything below the list moves with its foot and the panel ends under
        that, so what is drawn is the rows and their frame, with no empty
        panel beneath them.  Nothing grows past what the skin is laid out at:
        the whole list is far longer than the screen, and a section that is
        too has the same page to scroll as before.
        """
        height = max(1, min(shown, _MAX_ROWS)) * _ROW
        if height == self._list_height:
            return
        try:
            foot = _LIST_TOP + height
            for control_id in _PANEL:
                self.getControl(control_id).setHeight(foot + _PANEL_GAP)
            self.getControl(_LIST).setHeight(height)
            self.getControl(_RULE).setPosition(35, foot + _RULE_GAP)
            for control_id in _HINTS:
                self.getControl(control_id).setPosition(35, foot + _HINT_GAP)
        except Exception as exc:
            # A skin without the ids costs the fitted panel, not the readings:
            # the window stays at the height it was laid out at, which is the
            # height it had before any of this.
            if not self._resize_failed:
                self._resize_failed = True
                xbmc.log(
                    f"TinyPPI: DV metadata window cannot be resized to its "
                    f"rows, leaving it at full height: {exc}",
                    xbmc.LOGWARNING,
                )
            return
        self._list_height = height

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

    def _cursor_area(self) -> str:
        """The section the selection is in, by title.

        Read from where the list actually is rather than from the section last
        jumped to: the arrow keys are not the only way to move a Kodi list --
        the scrollbar and a mouse move it too -- and OK should open what the
        viewer is looking at however they got there.
        """
        try:
            position = self.getControl(_LIST).getSelectedPosition()
        except Exception:
            return self._area_title
        for start, title, end in self._areas:
            if start <= position <= end:
                return title
        return self._area_title

    def _open_area(self) -> None:
        """Close, asking for the section under the selection on its own.

        Opened by open_dv_metadata once this window is gone, not from here: a
        modal opened inside a callback nests inside the loop that dispatched
        it, and the overlay hands over to this view the same way for the same
        reason (see ui.overlay._open_dv_metadata).
        """
        title = self._cursor_area()
        if not title:
            return
        self.open_section = title
        self._close(back_to_caller=False)

    def onClick(self, control_id: int) -> None:
        # OK on the focused list.  Kodi delivers the same press to onAction as
        # well, hence the guard in _close.
        if control_id == _LIST and self._settled():
            self._open_area()

    def onAction(self, action: xbmcgui.Action) -> None:
        action_id = action.getId()
        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            # The press that opened this view is the one action that must not
            # be acted on; nothing else needs the settling guard.
            if self._settled():
                self._open_area()
        elif action_id in (xbmcgui.ACTION_PREVIOUS_MENU,
                           xbmcgui.ACTION_NAV_BACK):
            # Kodi's own handling has already closed the window by now; this
            # records the answer and stops the refresh thread with it.
            self._close(back_to_caller=True)
        elif action_id == xbmcgui.ACTION_STOP:
            # Not a step back up: the film is what all of this was about.
            self._close(back_to_caller=False)
        elif action_id in _STEP_ACTIONS:
            # The list has already moved itself a row by the time this runs --
            # Kodi hands the action to the control before the window sees it.
            # Nothing here reads where it ended up, so that does not matter:
            # the step is counted from the section the viewer was on, and the
            # selection is put back on a heading either way.
            self._step_area(_STEP_ACTIONS[action_id])

    def _close(self, back_to_caller: bool) -> None:
        """Close once, remembering what the viewer asked for."""
        if self._closing:
            return
        self._closing       = True
        self.back_to_caller = back_to_caller
        self._running       = False
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
                    self._fill(self._rows())
                except Exception as exc:
                    self._log_refresh_failure(exc)

                if self._monitor.waitForAbort(_REFRESH):
                    break
        finally:
            # Playback ended under the view: close it for good, not back to an
            # overlay that has nothing left to show either.
            self._close(back_to_caller=False)

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


class DVSectionDialog(DVMetadataDialog):
    """One section of the metadata list, on its own.

    The same window and the same refresh, holding one block: what OK opens
    when the list is on a section.  A block worth reading as a whole is worth
    seeing as a whole, and several of them -- the trims with a pass per target
    display, the RPU header, the static SEIs -- are longer than the room the
    list can spare for them among thirteen others.

    Only Back does anything here.  There is nowhere further down to go, so OK
    is left alone rather than made into a second way back: down and up are one
    key each, all the way through (see the module docstring).  The arrow keys
    are the list's own again -- one section is not something to step through a
    section at a time -- so they scroll it by rows.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Set before doModal(): the title of the section to show.
        self.section     = ""
        self._settled_in = False

    def _rows(self) -> list:
        """The rows of this section alone, heading included.

        Sliced out of the whole list each refresh rather than kept, because
        the section is live: a trim pass the frame adds belongs in here too.
        A stream that stops carrying the block entirely leaves the heading, so
        the window says what it is standing on rather than going blank.
        """
        rows = dvmetadata.build_rows()
        for start, title, end in _areas(rows):
            if title == self.section:
                return rows[start:end + 1]
        return [(dvmetadata.SECTION, self.section, "")]

    def _focus_area(self, index: int) -> None:
        """Land on the heading when the window opens, and then keep still.

        The list refocuses its section whenever the rows change under it,
        which is what keeps the viewer's place there.  Here it would take
        their place away: with one section on screen, scrolling within it is
        the only movement there is, and a refresh must not undo it.
        """
        if self._settled_in:
            return
        self._settled_in = True
        super()._focus_area(index)

    def onClick(self, control_id: int) -> None:
        pass

    def onAction(self, action: xbmcgui.Action) -> None:
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self._close(back_to_caller=True)
        elif action_id == xbmcgui.ACTION_STOP:
            self._close(back_to_caller=False)


def _dialog(dialog_class):
    """Build one of the two views on the metadata window."""
    return dialog_class(
        "script-tinyppi-dv-metadata.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )


def _show_section(title: str) -> bool:
    """Show *title* on its own; True when Back asked for the list again.

    The property is what tells the skin which of the two key hints to draw --
    the window is the same one either way, and the keys it answers to are not.
    """
    home = xbmcgui.Window(_HOME)
    home.setProperty(_SECTION_VIEW, "1")
    try:
        dialog = _dialog(DVSectionDialog)
        dialog.section = title
        dialog.doModal()
        back_to_list = dialog.back_to_caller
        del dialog
    finally:
        home.clearProperty(_SECTION_VIEW)
    return back_to_list


def open_dv_metadata() -> bool:
    """Show the metadata view; True when Back asked for the overlay back.

    A loop, because OK opens a section as a window of its own: the list closes
    to let it open, and Back closes it to let the list open again -- on the
    section it was opened from, so a look inside one costs the viewer no place
    in the list.  Playback ending under either of them ends the session
    instead, overlay and all.
    """
    section = ""
    while True:
        dialog = _dialog(DVMetadataDialog)
        dialog.start_section = section
        dialog.doModal()
        section         = dialog.open_section
        back_to_overlay = dialog.back_to_caller
        del dialog

        if not section:
            return back_to_overlay
        if not _show_section(section):
            return False
