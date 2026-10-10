# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dolby Vision metadata view: everything the stream's side data carries.

OK on the overlay of a DV source opens a live list of every block
``script.module.sidedata`` parsed (configuration record, RPU header to L255,
static SEIs).  OK on a section opens it alone; Back goes up one level each
time.  Windows never nest: each closes before the next opens, driven by
``open_dv_metadata`` (and ``ui.overlay.open_tinyppi`` above it).

The rows come from info.dvmetadata.  This module fills and refreshes the
list, highlights changed readings for the highlight duration, and marks
sections held from earlier frames as ``(Cached)`` (see _paint).
"""

import contextlib
import threading
import time
from typing import Any, TypeVar

import xbmc
import xbmcgui
from core import settings
from core.log import log
from core.utils import (
    ChangeHighlighter,
    highlight_hold,
    home_window,
    join_refresh_thread,
    log_refresh_failure,
)
from info import dvmetadata

# The add-on folder (via the shared settings handle, see core.settings).
_ADDON_PATH = settings.addon().getAddonInfo("path")

# The metadata list control (see script-tinyppi-dv-metadata.xml).
_LIST = 6000

# Controls resized to fit the rows.  A skin cannot size a panel by its row
# count, so the skin defines the tallest window and _resize shrinks it.
# Panel images (left cap, fill, right cap), the rule under the list and the
# two key hints all follow the list's foot.
_PANEL = (6100, 6101, 6102)
_RULE  = 6110
_HINTS = (6120, 6121)

# List top, row height, and the rule, hint and panel-end gaps below the list.
_LIST_TOP  = 150
_ROW       = 30
_RULE_GAP  = 25
_HINT_GAP  = 45
_PANEL_GAP = 100

# Maximum visible rows (750 px of list, the skin's layout height).
_MAX_ROWS = 25

# Set while a single section is shown; the skin uses it for the key hint.
_SECTION_VIEW = "TinyPPI.MetadataSectionView"

# Highlight color for changed readings (published by ui.theme).
_CHANGED_COLOR = "TinyPPI.MetadataChangedColor"

# Setting for the highlight duration in ms (independent of _REFRESH).
_CHANGED_HOLD = "metadata_changed_duration"

# Fallback when the color is not published (apply_theme never ran).
_CHANGED_FALLBACK = "FF82B1FF"  # Blue, the setting's default

# Texture of the rule under a heading; set per item, since all rows share
# one layout.
_RULE_TEXTURE = "common/dot-1x1.png"

# Property prefixes for table cells (one fixed skin slot per index);
# headings and readings are separate so they can be coloured differently.
_CELL_HEADING = "h"
_CELL_VALUE   = "c"

# The same for the compact nine-cell grid (e.g. the HDR10+ distribution).
_COMPACT_CELL_HEADING = "ch"
_COMPACT_CELL_VALUE   = "cc"

# Refresh interval, as in the overlay; _fill skips ticks where nothing
# changed.
_REFRESH = 0.1

# Fallback interval for rebuilding the static rows; changes are normally
# caught at once by dvmetadata.static_signature (see _merged_rows).
_STATIC_ROWS_INTERVAL = 1.0

# Actions this soon after opening are ignored, so the opening key press
# cannot act on the new window.
_SETTLE = 0.3

# Up/down and page up/down move by section, not by row or page.  Looked up
# by name: not every Kodi build has the paging actions.
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
    """Return a stable key per row: (kind, name, repeat index).

    Names repeat (MaxCLL is under L6 and the static SEIs).  The key keeps a
    row's highlight history across rebuilds, e.g. when sections come and go.
    """
    seen: dict = {}
    keys = []
    for kind, name, _value in rows:
        repeat = seen.get((kind, name), 0)
        seen[(kind, name)] = repeat + 1
        keys.append((kind, name, repeat))
    return keys


def _areas(rows: list) -> list:
    """Return the sections as ``(heading row, title, last row)``.

    The blank row before a heading belongs to neither section.
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
    """The metadata list.

    OK opens the current section alone, Back returns to the overlay, and the
    view closes when playback stops or fullscreen video is left.  The arrow
    keys jump between sections and show as much of each as fits.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._running   = False
        self._monitor   = xbmc.Monitor()
        self._opened_at = 0.0
        # Row identities in the list; the highlighter tracks values by
        # identity (see _identities).
        self._keys: list = []
        self._highlighter = ChangeHighlighter(highlight_hold(_CHANGED_HOLD))
        # Labels (or cell lists) shown last tick, so _fill can skip idle
        # ticks.
        self._last_labels: list = []
        # True during _fill's list swap (see _cursor_area).
        self._swapping: bool = False
        # Cached static rows, their signature and the next fallback rebuild
        # (owned by _merged_rows).
        self._static_rows: list = []
        self._static_signature: tuple | None = None
        self._next_static_rows = 0.0
        self._thread: threading.Thread | None = None
        self._closing        = False
        self._refresh_failed = False
        self._color_missing  = False
        # Current list height, so unchanged row counts skip the resize.
        self._list_height   = 0
        self._resize_failed = False
        # Sections and the current one, by title, so sections coming and
        # going do not move the viewer (see _focus_area).
        self._areas: list = []
        self._area_title  = ""
        # Set before doModal(): the section to start on, so returning from a
        # section keeps the viewer's place.
        self.start_section = ""
        # Read by open_dv_metadata() after doModal(): whether Back asked for
        # the previous view, and the section OK asked to open.
        self.back_to_caller = False
        self.open_section   = ""

    def _merged_rows(self) -> list:
        """Return this tick's scene rows joined with the cached static rows.

        The static rows are rebuilt when ``dvmetadata.static_signature``
        changes or after ``_STATIC_ROWS_INTERVAL``.  Deadline and signature
        advance before the rebuild, so a failure retries after an interval
        rather than every tick.
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
        """Return the rows to show (all; DVSectionDialog narrows this)."""
        return self._merged_rows()

    def onInit(self) -> None:
        self._running   = True
        self._opened_at = time.time()
        self._area_title = self.start_section
        # A list can only be filled through its control, so the first fill
        # happens here, during the opening fade.
        try:
            self._fill(self._rows())
        except Exception as exc:
            self._log_refresh_failure(exc)
        self.setFocusId(_LIST)
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def join_update_loop(self) -> None:
        """Wait for the refresh thread to stop (called after doModal())."""
        join_refresh_thread(self._thread)

    # --- List --------------------------------------------------------------

    @staticmethod
    def _paint(item: xbmcgui.ListItem, row: tuple, label: str | list[str]) -> None:
        """Make *item* show *row* with *label* as its value.

        All rows share one layout (Kodi evaluates list layout conditions once
        per list), so the row kind is expressed by which fields are filled:
        headings use ``head``, ``state`` and ``rule``; two-column rows both
        labels; full-width lines only label2; table rows one property per
        cell; blank rows nothing.  Every field is written, unused ones empty.
        """
        kind, name, _value = row
        heading = kind == dvmetadata.SECTION
        named   = kind in (dvmetadata.ROW, dvmetadata.HEADINGS,
                           dvmetadata.COLUMNS)
        table   = kind in (dvmetadata.HEADINGS, dvmetadata.COLUMNS)
        compact = table and len(label) == dvmetadata.MAX_COMPACT_COLUMNS
        # Right-align narrow tables in the fixed slots, so the list has one
        # right edge.  All rows of a table have the heading's width (see
        # dvcomposer._grid and dvmetadata._table), so readings stay under their
        # headings.  Full-width and compact tables are not shifted.
        offset  = (max(0, dvmetadata.MAX_COLUMNS - len(label))
                   if table and not compact else 0)
        item.setLabel(name if named else "")
        item.setLabel2(label if kind in (dvmetadata.ROW, dvmetadata.WIDE)
                       else "")
        item.setProperty("head", name if heading else "")
        item.setProperty("state", label if heading else "")
        item.setProperty("rule", _RULE_TEXTURE if heading else "")
        for position in range(dvmetadata.MAX_COLUMNS):
            at   = position - offset
            cell = (label[at]
                    if table and not compact and 0 <= at < len(label) else "")
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
        """Return the published highlight color, or the default (logged once)."""
        color = home_window().getProperty(_CHANGED_COLOR)
        if color:
            return color
        if not self._color_missing:
            self._color_missing = True
            log(
                f"{_CHANGED_COLOR} is not published, highlighting "
                f"changed values in {_CHANGED_FALLBACK} instead",
                xbmc.LOGWARNING,
            )
        return _CHANGED_FALLBACK

    def _fill(self, rows: list) -> None:
        """Replace the list with *rows* when anything changed; else do nothing.

        Measured on device: in-place ``setLabel``/``setProperty`` calls from
        a background thread wait for a once-per-frame GUI lock (one row
        47-250 ms, 72 rows 829 ms), while one ``addItems()`` with fresh
        offscreen items took 4.8 ms.  So a changed tick builds new items and
        calls ``reset()`` and ``addItems()`` back to back, with nothing in
        between (the viewport is read from InfoLabels beforehand, since
        ``getSelectedPosition()`` also costs ~34 ms).  Whether Kodi can draw
        an empty list between the two calls is still to be verified on
        device.

        ``addItems()`` always selects item 0.  To restore the viewport after
        a value-only change, the last row of the old page is selected first,
        then the current row (Kodi does not scroll for a visible row).  The
        page start is ``(CurrentItem - 1) - Position``; if unreadable, the
        selection is left alone.  A structural change returns the viewer to
        their section instead.

        Changed values are highlighted for the highlight duration, compared
        by row identity.  Headings are never highlighted: their value is the
        Cached marker, not a reading.  A highlight ending counts as a change.
        """
        keys  = _identities(rows)
        color = self._changed_color()
        now   = time.monotonic()
        self._highlighter.retain(keys)
        labels = [
            value if kind == dvmetadata.SECTION
            else self._highlighter.mark(key, value, color, now)
            for (kind, _name, value), key in zip(rows, keys, strict=True)
        ]

        if keys == self._keys and labels == self._last_labels:
            return

        items = []
        for row, label in zip(rows, labels, strict=True):
            item = xbmcgui.ListItem("", "", offscreen=True)
            self._paint(item, row, label)
            items.append(item)

        control = self.getControl(_LIST)
        self._swapping = True
        try:
            try:
                slot    = int(xbmc.getInfoLabel(f"Container({_LIST}).Position"))
                current = int(xbmc.getInfoLabel(f"Container({_LIST}).CurrentItem")) - 1
            except ValueError:  # empty labels while the list is still empty
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

    # --- Geometry ----------------------------------------------------------

    def _resize(self, shown: int) -> None:
        """Shrink the window to fit *shown* rows (at most ``_MAX_ROWS``).

        The rule, hints and panel follow the list's foot.
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
            # Without these ids the window keeps its full skin height.
            if not self._resize_failed:
                self._resize_failed = True
                log(
                    f"DV metadata window cannot be resized to its "
                    f"rows, leaving it at full height: {exc}",
                    xbmc.LOGWARNING,
                )
            return
        self._list_height = height

    # --- Sections ----------------------------------------------------------

    def _area_index(self) -> int:
        """Return the index of the current section, found by title.

        Sections come and go with the frame, so the title keeps the viewer
        on the same section; if it disappears, index 0 is used.
        """
        for index, (_start, title, _end) in enumerate(self._areas):
            if title == self._area_title:
                return index
        return 0

    def _focus_area(self, index: int) -> None:
        """Select section *index*, showing as much of it as fits.

        Selecting its last row and then its heading shows the whole section
        when it fits, otherwise its heading at the top.
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

    # --- Input -------------------------------------------------------------

    def _settled(self) -> bool:
        """Return False while the opening key press may still arrive."""
        return time.time() - self._opened_at >= _SETTLE

    def _cursor_area(self) -> str:
        """Return the title of the section under the selection.

        Read from the list itself, since the scrollbar or a mouse can move
        it too.  During a list swap the last known section is used.
        """
        if self._swapping:
            return self._area_title
        try:
            position = self.getControl(_LIST).getSelectedPosition()
        except Exception:  # window closing: the control is gone
            return self._area_title
        for start, title, end in self._areas:
            if start <= position <= end:
                return title
        return self._area_title

    def _open_area(self) -> None:
        """Close and request the section under the selection.

        ``open_dv_metadata`` opens it after this window has closed (see
        ``ui.overlay._open_dv_metadata`` for why).
        """
        title = self._cursor_area()
        if not title:
            return
        self.open_section = title
        self._close(back_to_caller=False)

    def onClick(self, control_id: int) -> None:
        # OK on the list; Kodi also sends it to onAction (see _close's guard).
        if control_id == _LIST and self._settled():
            self._open_area()

    def onAction(self, action: xbmcgui.Action) -> None:
        action_id = action.getId()
        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            # Ignore the press that opened this view.
            if self._settled():
                self._open_area()
        elif action_id in (xbmcgui.ACTION_PREVIOUS_MENU,
                           xbmcgui.ACTION_NAV_BACK):
            # Kodi has already closed the window; record the answer.
            self._close(back_to_caller=True)
        elif action_id == xbmcgui.ACTION_STOP:
            # Stop ends the session instead of going back.
            self._close(back_to_caller=False)
        elif action_id in _STEP_ACTIONS:
            # The list has already moved a row; the step counts from the
            # current section and lands on a heading anyway.
            self._step_area(_STEP_ACTIONS[action_id])

    def _close(self, back_to_caller: bool) -> None:
        """Close once and record whether Back asked for the previous view."""
        if self._closing:
            return
        self._closing       = True
        self.back_to_caller = back_to_caller
        self._running       = False
        with contextlib.suppress(Exception):
            self.close()

    # --- Refresh -----------------------------------------------------------

    def _update_loop(self) -> None:
        """Refresh every ``_REFRESH`` seconds until the view should close.

        Like the overlay's loop: failures cost one tick, and ``finally``
        always closes the view.
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
            # Playback ended: end the session, not back to the overlay.
            self._close(back_to_caller=False)

    def _log_refresh_failure(self, exc: Exception) -> None:
        """Log a failed refresh once per view."""
        if self._refresh_failed:
            return
        self._refresh_failed = True
        log_refresh_failure("DV metadata", exc)


class DVSectionDialog(DVMetadataDialog):
    """One section of the metadata list on its own.

    Same window and refresh, for sections too long for the list (trims, RPU
    header, static SEIs).  Only Back and Stop act; OK does nothing, and the
    arrow keys scroll by rows.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Set before doModal(): the section title to show.
        self.section     = ""
        self._settled_in = False

    def _rows(self) -> list:
        """Return this section's rows, heading included.

        Sliced from ``_merged_rows`` on every refresh, so the section stays
        live.  When the block disappears only the heading remains.
        """
        rows = self._merged_rows()
        for start, title, end in _areas(rows):
            if title == self.section:
                return rows[start:end + 1]
        return [(dvmetadata.SECTION, self.section, "")]

    def _focus_area(self, index: int) -> None:
        """Select the heading once on open, then never move the selection.

        Refocusing on refresh would undo the viewer's scrolling.
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


_Dialog = TypeVar("_Dialog", bound=xbmcgui.WindowXMLDialog)


def _dialog(dialog_class: type[_Dialog]) -> _Dialog:

    """Create a *dialog_class* window from the metadata skin file."""
    return dialog_class(
        "script-tinyppi-dv-metadata.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )


def _show_section(title: str) -> bool:
    """Show section *title* alone; return True when Back asked for the list.

    ``_SECTION_VIEW`` tells the skin which key hint to show.
    """
    home = home_window()
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
    """Show the metadata view; return True when Back asked for the overlay.

    Loops between the list and single sections, reopening the list on the
    section the viewer came from.  When playback ends, the session ends.
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
