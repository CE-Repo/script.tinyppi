"""Dolby Vision metadata view: everything the stream's side data carries.

The overlay shows the readings that fit its rows.  This view is the other half
of that: pressing OK on a Dolby Vision source hands over to it, and it lists
every block ``script.module.sidedata`` parsed out of the raw payload -- the
configuration record, the RPU from its header through L255, the static SEIs --
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
writes those in the highlight color, and leaves them in it for the highlight
duration afterwards, so a list this long can be read as a live one.  Which is
also why a heading whose block this frame did not carry reads ``(Cached)``:
what is on screen should say whether it is the frame's own (see _paint).
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from core.utils import (
    ChangeHighlighter,
    highlight_hold,
    join_refresh_thread,
    log_refresh_failure,
)
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

# A reading that moved is written in this color, so the eye finds what is live
# among rows that mostly stand still -- the trims and the frame luminance move
# with the picture, the title-level blocks do not.  Its own setting (Metadata
# -> Changed values), published by ui.theme like every other color.
_CHANGED_COLOR = "TinyPPI.MetadataChangedColor"

# How long it stays written that way, in milliseconds (Metadata -> Changed
# values -> Highlight duration).  A separate matter from _REFRESH below: the
# rows are re-read ten times a second either way, and a change that lasted
# only the tick that found it would be a tenth of a second on screen.
_CHANGED_HOLD = "metadata_changed_duration"

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

# The same two property families for a table that uses the skin's compact
# nine-cell grid.  Kept separate from h / c so L2 and L8 stay on their wider
# six-cell grid while HDR10+'s short distribution readings sit nine abreast.
_COMPACT_CELL_HEADING = "ch"
_COMPACT_CELL_VALUE   = "cc"

# Seconds between refreshes, matching the overlay's own polling interval: the
# per-frame blocks (L1, L5, the trims) move with the picture, so a slower tick
# here would fall behind the same scene cuts the overlay already tracks.  The
# guard in _fill (self._keys and self._last_labels) is what keeps a tick this
# fast from touching the list on the ticks nothing in it changed.
_REFRESH = 0.1

# Seconds between fallback re-renders of dvmetadata.build_static_rows's half
# of the list, matching the overlay's own static cadence: those sections
# settle before the film was ever played, so re-deriving them on every
# _REFRESH tick would recompute nine formatting passes a second for rows that
# changed maybe once.  The rare change they do have is caught the tick it
# lands by dvmetadata.static_signature, so this timer only covers what the
# signature cannot see.  See _merged_rows.
_STATIC_ROWS_INTERVAL = 1.0

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
        # Row identities currently in the list, and the value each identity
        # was last filled with, which is what a refresh highlights against --
        # held by the highlighter, together with how long each change of them
        # stays lit.  Keyed by identity rather than by position so a rebuild
        # does not lose it (see _identities).
        self._keys: list = []
        self._highlighter = ChangeHighlighter(highlight_hold(_CHANGED_HOLD))
        # The label (or, for a table row, cell list) each row actually
        # showed last tick, compared whole against a fresh tick's labels so
        # an idle tick can return before it builds anything -- see _fill.
        self._last_labels: list = []
        # True from just before _fill's reset()/addItems() swap until the
        # post-swap selection handling is done -- see _cursor_area.
        self._swapping: bool = False
        # The static half of the row list (see dvmetadata.build_static_rows),
        # the signature of what it was rendered from, and when its fallback
        # re-render is next due -- re-rendered the tick its blocks change and
        # on _STATIC_ROWS_INTERVAL otherwise, rather than on every tick.
        # _merged_rows() owns all three.
        self._static_rows: list = []
        self._static_signature = None
        self._next_static_rows = 0.0
        self._thread         = None
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

    def _merged_rows(self) -> list:
        """The scene rows fresh from this tick, plus the static rows from
        whichever tick last re-rendered them.

        dvmetadata.build_scene_rows already does the live side-data read and
        the DM-compression hold-fill every call; build_static_rows only
        needs the parse result and origin map that call produced, not a
        fresh read of its own, so re-rendering it is cheap to skip on the
        ticks it is not due.  It re-renders the tick its own blocks actually
        change (dvmetadata.static_signature) and on _STATIC_ROWS_INTERVAL
        otherwise, so a scene cut that also moves the static half is not
        left waiting on the fallback timer to catch up.  join_rows decides
        the blank row between the two halves against THIS tick's scene_rows
        every time, not against whichever tick last rebuilt
        self._static_rows, so a stale cache cannot leave the joined list
        wrongly shaped even while its readings are still stale.

        The deadline and signature both advance before the call, not after,
        the same reason overlay.py's update_static_properties does it in
        that order: a failure below still counts this as tried, so it
        retries in another _STATIC_ROWS_INTERVAL rather than every tick
        until it succeeds.
        """
        scene_rows, parsed, origin, carried = dvmetadata.build_scene_rows()
        signature = dvmetadata.static_signature(parsed, origin, carried)
        now = time.time()
        if signature != self._static_signature or now >= self._next_static_rows:
            self._next_static_rows = now + _STATIC_ROWS_INTERVAL
            self._static_signature = signature
            self._static_rows = dvmetadata.build_static_rows(parsed, origin, carried)
        rows = dvmetadata.join_rows(scene_rows, self._static_rows)
        if not rows:
            rows = [(dvmetadata.SECTION, "No metadata in this frame", "")]
        return rows

    def _rows(self) -> list:
        """The rows to show: all of them.  A section view narrows this."""
        return self._merged_rows()

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
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def join_update_loop(self) -> None:
        """Wait for the refresh thread to actually stop.

        Called after doModal(), so the hand-over to the next view waits for
        the loop instead of racing it.
        """
        join_refresh_thread(self._thread)

    # --- List ---------------------------------------------------------------

    @classmethod
    def _paint(cls, item: xbmcgui.ListItem, row: tuple, label) -> None:
        """Make *item* show *row*, with *label* as its value.

        The skin draws every row through the same layout, because that is all
        a Kodi list container offers: its layout conditions are evaluated once
        for the whole list, not per row.  So what tells the kinds apart is
        which of the item's fields carry anything -- each control in the
        layout is fed one of them and draws nothing when it comes back empty.

        A heading puts its title in the ``head`` property, which is the one
        the large font is on, its ``(Cached)`` in ``state`` beside it, and
        names the texture for the rule under it.  A two-column row fills
        both labels.  A full-width line fills only the second, which spans
        the row.  A table row fills a property per cell, which is what puts
        each in a fixed column.  A blank row fills nothing.

        Every field is written on every call, the unused ones with nothing:
        the item is always a fresh one _fill just built for this one row, so
        there is no earlier row's field left over to worry about -- but one
        painter that always writes the whole shape is simpler than one that
        has to know what an item said last, and it costs nothing extra on an
        item that started out blank anyway.
        """
        kind, name, _value = row
        heading = kind == dvmetadata.SECTION
        named   = kind in (dvmetadata.ROW, dvmetadata.HEADINGS,
                           dvmetadata.COLUMNS)
        table   = kind in (dvmetadata.HEADINGS, dvmetadata.COLUMNS)
        compact = table and len(label) == dvmetadata.MAX_COMPACT_COLUMNS
        item.setLabel(name if named else "")
        item.setLabel2(label if kind in (dvmetadata.ROW, dvmetadata.WIDE)
                       else "")
        item.setProperty("head", name if heading else "")
        item.setProperty("state", label if heading else "")
        item.setProperty("rule", _RULE_TEXTURE if heading else "")
        for position in range(dvmetadata.MAX_COLUMNS):
            cell = (label[position]
                    if table and not compact and position < len(label) else "")
            item.setProperty(f"{_CELL_HEADING}{position}",
                             cell if kind == dvmetadata.HEADINGS else "")
            item.setProperty(f"{_CELL_VALUE}{position}",
                             cell if kind == dvmetadata.COLUMNS else "")
        for position in range(dvmetadata.MAX_COMPACT_COLUMNS):
            cell = label[position] if compact and position < len(label) else ""
            item.setProperty(f"{_COMPACT_CELL_HEADING}{position}",
                             cell if kind == dvmetadata.HEADINGS else "")
            item.setProperty(f"{_COMPACT_CELL_VALUE}{position}",
                             cell if kind == dvmetadata.COLUMNS else "")

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
        """Put *rows* in the list, wholesale, on any tick something in it
        changed; touch nothing at all on a tick that did not.

        On-device measurement is why: Kodi meters every in-place
        ListItem.setLabel*/setProperty call made from a background thread
        through a once-per-frame GUI lock, so a single row write blocked
        47-250ms at 23.976Hz, a 6-row update spanned 85-627ms, and a 72-row
        in-place repaint ran 829ms -- against 4.8ms for the same 72 rows
        through the bind path below.  The one fast path Kodi offers is the
        initial fill, which hands the control a whole item list through one
        addItems() bind message.  So a changed tick takes that path every
        time: a fresh, unattached ListItem is built and painted for every
        row -- offscreen items are unsynchronized by design, so populating
        them off the GUI thread costs nothing here -- and only once that is
        done does the tick touch the list at all: control.reset()
        immediately followed by control.addItems(items), with no work
        between the two so both messages queue for what is meant to be the
        same dispatch pass -- not even a read of the control, now that the
        viewport it will need back comes from two infolabels rather than
        ControlList.getSelectedPosition(), which blocked behind the same
        once-per-frame lock as the writes above, close to a frame on its own
        (about 34ms measured) for a call that used to sit in this exact
        spot.  That is design intent, not a settled fact: this file's
        previous design never reset the list at all, on the reasoning that
        Kodi is free to draw between any two calls however close together
        they are issued, and an empty list mid-swap would flash visibly.
        Whether Kodi can in fact draw between reset() and addItems() is the
        one open question this design carries -- taken deliberately to the
        device for verification rather than settled here, because the per-call
        alternative is the one measured above.  An item already handed to
        the control this way is never reached back into; the next changed
        tick builds a whole new set instead.

        An idle tick -- the row identities and the labels they would show
        are both exactly what the list is already showing -- returns before
        any of that runs, so a still frame between scene cuts costs nothing.
        A highlight running out is not an idle tick: the label it was lit in
        is not the label it goes back to, so the tick a hold ends on rebuilds
        the list the same way the tick it started on did.

        Every addItems() bind ends, inside Kodi itself, in an unconditional
        SelectItem(0) -- the jump to the top of the list is built into the
        engine, not a gap this code leaves open.  A single selectItem(current)
        afterward puts the cursor back on the right row but not the view
        under it: from that zeroed offset, Kodi's own SelectItem places an
        off-page row at the bottom of the viewport (offset = row - page + 1)
        rather than where it sat before, so a row thirty deep into the list
        reappears at its foot, and a frame rendered before a second call
        corrects that shows a snap to the top followed by an animated crawl
        back down.  Landing exactly on the old viewport instead takes two
        selects, the idiom _focus_area already uses to open a section:
        selectItem(first_visible + page - 1) first, page being however many
        rows are on screen at once, which pins the far edge of the old page
        without moving the cursor there, then selectItem(current), which
        lands the cursor on a row already on screen -- the one case
        SelectItem leaves the offset untouched.  first_visible itself comes
        from two infolabels read before reset() touches anything:
        Container(_LIST).Position, the cursor's slot within the viewport,
        and .CurrentItem, its absolute index one-based, give first_visible =
        (CurrentItem - 1) - Position.  Either read coming back empty or
        unparsable leaves the viewport unknown rather than guessed at zero,
        and a value-only refresh under those conditions makes no
        selectItem() call at all, leaving the list wherever the bind's own
        SelectItem(0) put it.

        A structural change -- a stream that starts carrying trim passes, a
        section the frame no longer has any readings for -- puts the viewer
        back on the section they were reading rather than at the top of the
        list, same as before.  A value-only change instead restores the
        exact viewport the control had right before the swap, by the
        two-select recipe above, so a refresh cannot move the viewer even
        though every item under them is a different object than a moment
        ago.

        Either way the values that moved go up in the highlight color, which
        is the whole point of a view that refreshes: with sixty rows on
        screen, a reading that changed is worth nothing if it cannot be told
        from the fifty-nine that did not.  They stay up in it for the
        highlight duration rather than for the one tick that found them (see
        core.utils.ChangeHighlighter), which at this refresh rate is a tenth
        of a second -- a blink the eye is not given time to follow.  The
        comparison is by identity, not by position, so the rows a rebuild
        kept are still compared against what they said before it, and
        ``retain`` drops the history of the rows it did not.

        Headings are the one thing left out of that.  What a heading carries
        is not a reading but where its block came from, and a section that
        goes in and out of being held would spend half the film lit up as
        though something in it had changed.
        """
        keys  = _identities(rows)
        color = self._changed_color()
        now   = time.monotonic()
        self._highlighter.retain(keys)
        labels = [
            value if kind == dvmetadata.SECTION
            else self._highlighter.mark(key, value, color, now)
            for (kind, _name, value), key in zip(rows, keys)
        ]

        if keys == self._keys and labels == self._last_labels:
            return

        items = []
        for row, label in zip(rows, labels):
            item = xbmcgui.ListItem("", "", offscreen=True)
            self._paint(item, row, label)
            items.append(item)

        control = self.getControl(_LIST)
        self._swapping = True
        try:
            try:
                slot    = int(xbmc.getInfoLabel(f"Container({_LIST}).Position"))
                current = int(xbmc.getInfoLabel(f"Container({_LIST}).CurrentItem")) - 1
            except Exception:
                current = -1
            first_visible = max(0, current - slot) if current >= 0 else 0
            control.reset()
            control.addItems(items)

            if keys != self._keys:
                self._keys  = keys
                self._areas = _areas(rows)
                self._resize(len(rows))
                self._focus_area(self._area_index())
            elif 0 <= current < len(items):
                page   = max(1, min(len(items), _MAX_ROWS))
                anchor = min(first_visible + page - 1, len(items) - 1)
                control.selectItem(anchor)
                control.selectItem(current)
        finally:
            self._swapping = False

        self._last_labels = labels

    # --- Geometry -----------------------------------------------------------

    def _resize(self, shown: int) -> None:
        """Cut the window down to the *shown* rows it has to hold.

        Called with the row count _fill rebuilt the list to, from the same
        call that just swapped it in -- there is no reason to ask the
        control what it holds when the caller already knows.

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

        Answers with the section already on screen while self._swapping is
        set: a keypress can land between _fill's reset() and its addItems(),
        and the control would read position 0 out of a list that is
        momentarily empty.
        """
        if self._swapping:
            return self._area_title
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
        """Re-read the side data every _REFRESH seconds until the view should
        close.

        Mirrors the overlay's loop, and for the same reasons: a failed refresh
        costs one stale tick rather than the window, and the close runs from
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
        trace without writing to the log every tick."""
        if self._refresh_failed:
            return
        self._refresh_failed = True
        log_refresh_failure("DV metadata", exc)


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

        Sliced out of the merged list each refresh rather than kept, because
        the section is live: a trim pass the frame adds belongs in here too.
        A stream that stops carrying the block entirely leaves the heading, so
        the window says what it is standing on rather than going blank.
        Slicing from self._merged_rows() rather than a fresh
        dvmetadata.build_rows() call means a section on the static side
        (L9, the RPU header, and the rest -- see dvmetadata.build_static_rows)
        re-renders the tick its own blocks change and on that half's fallback
        cadence otherwise, same as it would be in the full list; only a scene
        section is fresh every tick either way.
        """
        rows = self._merged_rows()
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
        dialog.join_update_loop()
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
        dialog.join_update_loop()
        section         = dialog.open_section
        back_to_overlay = dialog.back_to_caller
        del dialog

        if not section:
            return back_to_overlay
        if not _show_section(section):
            return False
