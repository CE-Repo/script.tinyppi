# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The Dolby Vision metadata list and section windows (ui/dvmetadata.py)."""

import importlib
import os
import xml.etree.ElementTree as ET

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from info import dvmetadata
from ui import dvmetadata as view

LIST = 6000
FALLBACK = "FF82B1FF"
COLOR_PROPERTY = "TinyPPI.MetadataChangedColor"
SECTION_VIEW = "TinyPPI.MetadataSectionView"
FULLSCREEN = "Window.IsActive(fullscreenvideo)"


def section(title, state=""):
    return (dvmetadata.SECTION, title, state)


def row(name, value):
    return (dvmetadata.ROW, name, value)


def blank(name="space"):
    return (dvmetadata.SPACE, name, "")


# Three sections; the blank row before L5 belongs to neither.
ROWS = [
    section("L1"), row("Max", "1000"), row("Min", "0"),
    blank(),
    section("L5"), row("Top", "276"),
    section("RPU"), row("Profile", "8"),
]


class Clock:
    """Replaces the view's ``time`` module: wall and monotonic time move together."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


class Feed:
    """Stands in for info.dvmetadata's live row builders."""

    def __init__(self):
        self.scene = []
        self.static = []
        self.parsed = {}
        self.static_builds = 0
        self.static_error = None

    def scene_rows(self):
        return list(self.scene), self.parsed, {}, "rpu"

    def static_rows(self, parsed, origin, carried):
        self.static_builds += 1
        if self.static_error:
            raise self.static_error
        return list(self.static)


class Player:
    def __init__(self, playing=True):
        self.playing = playing

    def isPlaying(self):
        return self.playing


class Monitor:
    """Counts refresh waits; *on_wait* decides whether each wait reports an abort."""

    def __init__(self, aborted=False, on_wait=lambda waits: True):
        self.aborted = aborted
        self.on_wait = on_wait
        self.waits = []

    def abortRequested(self):
        return self.aborted

    def waitForAbort(self, timeout=None):
        self.waits.append(timeout)
        return self.on_wait(self.waits)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(view, "time", fake)
    return fake


@pytest.fixture
def feed(monkeypatch):
    fake = Feed()
    monkeypatch.setattr(dvmetadata, "build_scene_rows", fake.scene_rows)
    monkeypatch.setattr(dvmetadata, "build_static_rows", fake.static_rows)
    return fake


def listed(dialog):
    return dialog.getControl(LIST)


def calls(control, name=None):
    return [(call, args) for call, args in control.calls if name in (None, call)]


def selections(control):
    return [args[0] for _call, args in calls(control, "selectItem")]


def values(dialog):
    return [item.getLabel2() for item in listed(dialog).items]


def warnings():
    return [message for level, message in xbmc.LOG if level == xbmc.LOGWARNING]


def settled(dialog, clock):
    dialog._opened_at = clock.now - 1


# --- Rows and sections -------------------------------------------------------

@pytest.mark.parametrize(("rows", "keys"), [
    ([], []),
    ([row("MaxCLL", "1"), section("S"), row("MaxCLL", "2"), row("MaxCLL", "3")],
     [("row", "MaxCLL", 0), ("section", "S", 0), ("row", "MaxCLL", 1), ("row", "MaxCLL", 2)]),
    ([section("A"), section("A")], [("section", "A", 0), ("section", "A", 1)]),
])
def test_repeated_names_get_their_own_identity(rows, keys):
    assert view._identities(rows) == keys


@pytest.mark.parametrize(("rows", "areas"), [
    ([], []),
    ([row("Loose", "1")], []),
    (ROWS, [(0, "L1", 2), (4, "L5", 5), (6, "RPU", 7)]),
    ([section("A"), blank(), blank(), section("B"), blank()], [(0, "A", 0), (3, "B", 3)]),
])
def test_sections_end_before_the_blank_rows(rows, areas):
    assert view._areas(rows) == areas


# --- Painting a row ----------------------------------------------------------

def cells(item, prefix, count):
    return [item.getProperty(f"{prefix}{index}") for index in range(count)]


def painted(row_, label):
    item = xbmcgui.ListItem()
    view.DVMetadataDialog._paint(item, row_, label)
    return item


def test_a_heading_fills_head_state_and_rule_only():
    item = painted(section("L1", "Cached"), "Cached")
    assert (item.getLabel(), item.getLabel2()) == ("", "")
    assert item.getProperty("head") == "L1"
    assert item.getProperty("state") == "Cached"
    assert item.getProperty("rule") == "common/dot-1x1.png"
    assert set(cells(item, "h", 6) + cells(item, "c", 6)) == {""}
    assert set(cells(item, "ch", 9) + cells(item, "cc", 9)) == {""}


@pytest.mark.parametrize(("row_", "label", "labels"), [
    (row("Max", "1000"), "1000", ("Max", "1000")),
    ((dvmetadata.WIDE, "note", "a full-width line"), "a full-width line",
     ("", "a full-width line")),
    (blank(), "", ("", "")),
])
def test_plain_rows_fill_only_their_labels(row_, label, labels):
    item = painted(row_, label)
    assert (item.getLabel(), item.getLabel2()) == labels
    assert [item.getProperty(key) for key in ("head", "state", "rule")] == ["", "", ""]
    assert set(cells(item, "h", 6) + cells(item, "c", 6)) == {""}
    assert set(cells(item, "ch", 9) + cells(item, "cc", 9)) == {""}


@pytest.mark.parametrize(("kind", "prefix", "other"), [
    (dvmetadata.HEADINGS, "h", "c"),
    (dvmetadata.COLUMNS, "c", "h"),
])
@pytest.mark.parametrize(("label", "slots"), [
    (["a", "b", "c"], ["", "", "", "a", "b", "c"]),           # right-aligned
    (list("abcdef"), list("abcdef")),
    (list("abcdefg"), list("abcdef")),                         # wider than the slots
])
def test_table_cells_are_right_aligned_in_the_fixed_slots(kind, prefix, other, label, slots):
    item = painted((kind, "100 nits", label), label)
    assert item.getLabel() == "100 nits" and item.getLabel2() == ""
    assert cells(item, prefix, 6) == slots
    assert set(cells(item, other, 6)) == {""}
    assert set(cells(item, "ch", 9) + cells(item, "cc", 9)) == {""}


@pytest.mark.parametrize(("kind", "prefix", "other"), [
    (dvmetadata.HEADINGS, "ch", "cc"),
    (dvmetadata.COLUMNS, "cc", "ch"),
])
def test_a_nine_cell_table_uses_the_compact_grid(kind, prefix, other):
    label = [str(index) for index in range(9)]
    item = painted((kind, "maxRGB", label), label)
    assert item.getLabel() == "maxRGB"
    assert cells(item, prefix, 9) == label
    assert set(cells(item, other, 9)) == {""}
    assert set(cells(item, "h", 6) + cells(item, "c", 6)) == {""}


# --- Filling the list --------------------------------------------------------

def test_the_first_fill_lists_every_row_and_fits_the_window():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    control = listed(dialog)
    assert [item.getProperty("head") or item.getLabel() for item in control.items] == [
        "L1", "Max", "Min", "", "L5", "Top", "RPU", "Profile"]
    assert values(dialog) == ["", "1000", "0", "", "", "276", "", "8"]
    assert [call for call, _args in control.calls[:2]] == ["reset", "addItems"]
    assert calls(control, "setHeight") == [("setHeight", (8 * 30,))]
    # The whole first section is shown, its heading selected.
    assert selections(control) == [2, 0]


def test_an_unchanged_tick_leaves_the_list_alone():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    listed(dialog).calls.clear()
    dialog._fill(list(ROWS))
    assert listed(dialog).calls == []


LONG = [section("A")] + [row(f"r{index}", "0") for index in range(29)]


@pytest.mark.parametrize(("position", "current", "selected"), [
    ("2", "13", [29, 12]),      # page 10-34, clamped to the last row
    ("0", "2", [25, 1]),        # page 1-25, the selection at its top
    ("5", "3", [24, 2]),        # a slot past the selection reads as the list top
])
def test_a_value_change_keeps_the_viewport(position, current, selected):
    dialog = view.DVMetadataDialog()
    dialog._fill(LONG)
    control = listed(dialog)
    control.calls.clear()
    xbmc.INFO["Container(6000).Position"] = position
    xbmc.INFO["Container(6000).CurrentItem"] = current
    changed = list(LONG)
    changed[5] = row("r4", "1")
    dialog._fill(changed)
    assert [call for call, _args in control.calls] == [
        "reset", "addItems", "selectItem", "selectItem"]
    # The last row of the old page first, then the row itself.
    assert selections(control) == selected
    assert calls(control, "setHeight") == []


@pytest.mark.parametrize(("position", "current"), [
    ("", ""),           # unreadable while the list is empty
    ("0", "0"),         # nothing selected
    ("0", "99"),        # beyond the new list
])
def test_a_value_change_leaves_an_unknown_selection_alone(position, current):
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    control = listed(dialog)
    control.calls.clear()
    xbmc.INFO["Container(6000).Position"] = position
    xbmc.INFO["Container(6000).CurrentItem"] = current
    changed = list(ROWS)
    changed[1] = row("Max", "4000")
    dialog._fill(changed)
    assert [call for call, _args in control.calls] == ["reset", "addItems"]


def test_a_new_layout_returns_the_viewer_to_their_section():
    dialog = view.DVMetadataDialog()
    dialog.start_section = "L5"
    dialog._area_title = "L5"
    dialog._fill(ROWS)
    control = listed(dialog)
    assert selections(control) == [5, 4]
    # L1 goes away: L5 moves up and is still the one selected.
    control.calls.clear()
    dialog._fill(ROWS[4:])
    assert selections(control) == [1, 0]
    assert calls(control, "setHeight") == [("setHeight", (4 * 30,))]
    # L5 goes away too: the first section is selected.
    control.calls.clear()
    dialog._fill(ROWS[6:])
    assert selections(control) == [1, 0]
    assert dialog._area_title == "RPU"


def test_a_selection_read_during_the_swap_keeps_the_last_section():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    dialog._area_title = "RPU"
    control = listed(dialog)
    seen = []
    plain_reset = control.reset

    def reset():
        plain_reset()
        # Kodi's GUI thread may ask now; the emptied list points at row 0 (L1).
        seen.append(dialog._cursor_area())

    control.reset = reset
    changed = list(ROWS)
    changed[1] = row("Max", "4000")
    dialog._fill(changed)
    assert seen == ["RPU"]


# --- Highlighting changed readings ---------------------------------------------

def test_a_changed_reading_is_highlighted_in_the_published_color():
    xbmcgui.Window(10000).setProperty(COLOR_PROPERTY, "FFFF0000")
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    changed = list(ROWS)
    changed[1] = row("Max", "4000")
    dialog._fill(changed)
    assert values(dialog)[1:3] == ["[COLOR=FFFF0000]4000[/COLOR]", "0"]
    assert warnings() == []


def test_a_changed_table_cell_is_highlighted_alone():
    xbmcgui.Window(10000).setProperty(COLOR_PROPERTY, "FFFF0000")
    dialog = view.DVMetadataDialog()
    table = [section("L2", ""), (dvmetadata.COLUMNS, "1000 nits", ["2048", "2048"])]
    dialog._fill(table)
    dialog._fill([table[0], (dvmetadata.COLUMNS, "1000 nits", ["2048", "1900"])])
    assert cells(listed(dialog).items[1], "c", 6)[-2:] == ["2048", "[COLOR=FFFF0000]1900[/COLOR]"]


def test_without_a_published_color_the_default_is_used_and_logged_once():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    for value in ("2000", "3000"):
        changed = list(ROWS)
        changed[1] = row("Max", value)
        dialog._fill(changed)
    assert values(dialog)[1] == f"[COLOR={FALLBACK}]3000[/COLOR]"
    assert len(warnings()) == 1
    assert "TinyPPI.MetadataChangedColor is not published" in warnings()[0]
    assert FALLBACK in warnings()[0]


def test_headings_are_never_highlighted():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    cached = [section("L1", "Cached")] + ROWS[1:]
    dialog._fill(cached)
    assert listed(dialog).items[0].getProperty("state") == "Cached"


def test_the_end_of_a_highlight_redraws_the_list(clock):
    xbmcaddon.SETTINGS["metadata_changed_duration"] = "500"
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    changed = list(ROWS)
    changed[5] = row("Top", "140")
    dialog._fill(changed)
    control = listed(dialog)
    assert values(dialog)[5] == f"[COLOR={FALLBACK}]140[/COLOR]"
    control.calls.clear()
    clock.now += 0.4
    dialog._fill(changed)
    assert control.calls == []
    clock.now += 0.2
    dialog._fill(changed)
    assert values(dialog)[5] == "140"
    assert [call for call, _args in control.calls][:2] == ["reset", "addItems"]


def test_a_row_that_went_away_comes_back_without_a_highlight():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    dialog._fill([row for row in ROWS if row[1] != "Top"])
    changed = list(ROWS)
    changed[5] = row("Top", "140")
    dialog._fill(changed)
    assert values(dialog)[5] == "140"


# --- Window geometry ------------------------------------------------------------

@pytest.mark.parametrize(("shown", "height"), [(0, 30), (1, 30), (8, 240), (25, 750), (40, 750)])
def test_the_window_shrinks_to_its_rows(shown, height):
    dialog = view.DVMetadataDialog()
    dialog._resize(shown)
    foot = 150 + height
    for panel in (6100, 6101, 6102):
        assert dialog.getControl(panel).height == foot + 100
    assert listed(dialog).height == height
    assert dialog.getControl(6110).position == (35, foot + 25)
    assert dialog.getControl(6120).position == (35, foot + 45)
    assert dialog.getControl(6121).position == (35, foot + 45)


def test_an_unchanged_height_is_not_resized_again():
    dialog = view.DVMetadataDialog()
    dialog._resize(8)
    listed(dialog).calls.clear()
    dialog._resize(8)
    assert listed(dialog).calls == []
    dialog._resize(9)
    assert calls(listed(dialog), "setHeight") == [("setHeight", (270,))]


def test_a_window_without_its_panel_stays_at_full_height_and_says_so_once(monkeypatch):
    dialog = view.DVMetadataDialog()
    plain = dialog.getControl

    def get_control(control_id):
        if control_id == 6100:
            raise RuntimeError("Non-Existent Control 6100")
        return plain(control_id)

    monkeypatch.setattr(dialog, "getControl", get_control)
    dialog._resize(8)
    dialog._resize(8)
    assert listed(dialog).height is None
    assert len(warnings()) == 1
    assert "cannot be resized" in warnings()[0]
    assert "Non-Existent Control 6100" in warnings()[0]


def test_the_controls_the_view_drives_are_in_its_skin_file():
    path = os.path.join(xbmcaddon.ROOT, "resources", "skins", "Default", "1080i",
                        "script-tinyppi-dv-metadata.xml")
    ids = {int(control.get("id")) for control in ET.parse(path).iter("control")
           if control.get("id")}
    assert {LIST, *view._PANEL, view._RULE, *view._HINTS} <= ids


# --- Moving between sections ---------------------------------------------------

@pytest.fixture
def listing():
    dialog = view.DVMetadataDialog()
    dialog._fill(ROWS)
    listed(dialog).calls.clear()
    return dialog


@pytest.mark.parametrize(("start", "action", "landed", "selected"), [
    ("L1", xbmcgui.ACTION_MOVE_DOWN, "L5", [5, 4]),
    ("L5", xbmcgui.ACTION_MOVE_DOWN, "RPU", [7, 6]),
    ("RPU", xbmcgui.ACTION_MOVE_DOWN, "RPU", [7, 6]),
    ("RPU", xbmcgui.ACTION_MOVE_UP, "L5", [5, 4]),
    ("L1", xbmcgui.ACTION_MOVE_UP, "L1", [2, 0]),
    ("gone", xbmcgui.ACTION_MOVE_DOWN, "L5", [5, 4]),     # unknown section counts as the first
])
def test_up_and_down_jump_between_sections(listing, start, action, landed, selected):
    listing._area_title = start
    listing.onAction(xbmcgui.Action(action))
    assert listing._area_title == landed
    assert selections(listed(listing)) == selected


@pytest.fixture
def paging():
    """The view as loaded by a Kodi build that has the page up/down actions."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(xbmcgui, "ACTION_PAGE_UP", 5, raising=False)
        patch.setattr(xbmcgui, "ACTION_PAGE_DOWN", 6, raising=False)
        importlib.reload(view)
        yield view
    importlib.reload(view)


@pytest.mark.parametrize(("start", "action", "landed"), [
    ("L1", 6, "L5"),
    ("RPU", 5, "L5"),
])
def test_page_up_and_down_jump_between_sections_where_kodi_has_them(paging, start, action,
                                                                    landed):
    dialog = paging.DVMetadataDialog()
    dialog._fill(ROWS)
    dialog._area_title = start
    dialog.onAction(xbmcgui.Action(action))
    assert dialog._area_title == landed


def test_without_paging_actions_only_the_arrows_jump():
    assert set(view._STEP_ACTIONS) == {xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN}


def test_nothing_is_selected_without_sections():
    dialog = view.DVMetadataDialog()
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))
    assert listed(dialog).calls == []


@pytest.mark.parametrize(("position", "title"), [(0, "L1"), (2, "L1"), (5, "L5"), (7, "RPU")])
def test_ok_opens_the_section_under_the_selection(listing, clock, position, title):
    settled(listing, clock)
    listed(listing).selected = position
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert listing.open_section == title
    assert listing.back_to_caller is False
    assert ("close", ()) in listing.calls


def test_ok_on_the_blank_row_opens_the_current_section(listing, clock):
    settled(listing, clock)
    listing._area_title = "L5"
    listed(listing).selected = 3
    listing.onClick(LIST)
    assert listing.open_section == "L5"


def test_ok_while_the_list_is_gone_opens_the_last_section(listing, clock, monkeypatch):
    settled(listing, clock)
    listing._area_title = "RPU"

    def gone(control_id):
        raise RuntimeError("window closing")

    monkeypatch.setattr(listing, "getControl", gone)
    listing.onClick(LIST)
    assert listing.open_section == "RPU"


def test_ok_without_a_section_does_nothing(clock):
    dialog = view.DVMetadataDialog()
    settled(dialog, clock)
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert dialog.open_section == ""
    assert ("close", ()) not in dialog.calls


def test_the_press_that_opened_the_view_is_ignored(listing, clock):
    listing._opened_at = clock.now - 0.2
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    listing.onClick(LIST)
    assert listing.open_section == ""
    clock.now += 0.1
    listing.onClick(LIST)
    assert listing.open_section == "L1"


def test_a_click_elsewhere_than_the_list_does_nothing(listing, clock):
    settled(listing, clock)
    listing.onClick(6001)
    assert listing.open_section == ""
    assert listing.calls == []


@pytest.mark.parametrize(("action", "back"), [
    (xbmcgui.ACTION_PREVIOUS_MENU, True),
    (xbmcgui.ACTION_NAV_BACK, True),
    (xbmcgui.ACTION_STOP, False),
])
def test_back_returns_to_the_overlay_and_stop_ends_the_session(listing, action, back):
    listing.onAction(xbmcgui.Action(action))
    assert listing.back_to_caller is back
    assert listing.open_section == ""
    assert listing.calls.count(("close", ())) == 1


def test_other_keys_are_left_to_kodi(listing):
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert listing.calls == [] and listed(listing).calls == []
    assert listing.back_to_caller is False


def test_the_window_closes_only_once(listing):
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_STOP))
    assert listing.back_to_caller is True
    assert listing.calls.count(("close", ())) == 1


def test_a_failing_close_still_records_the_answer(listing, monkeypatch):
    def close():
        raise RuntimeError("already closed")

    monkeypatch.setattr(listing, "close", close)
    listing.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert listing.back_to_caller is True


# --- Static rows ----------------------------------------------------------------

def test_scene_and_static_rows_are_joined_by_a_blank_row(feed):
    feed.scene = [section("L1"), row("Max", "1000")]
    feed.static = [section("RPU"), row("Profile", "8")]
    assert view.DVMetadataDialog()._rows() == [
        section("L1"), row("Max", "1000"), blank("space.RPU"),
        section("RPU"), row("Profile", "8")]


def test_a_frame_without_metadata_says_so(feed):
    assert view.DVMetadataDialog()._rows() == [section("No metadata in this frame")]


def test_static_rows_are_rebuilt_on_a_change_or_after_an_interval(feed, clock):
    feed.parsed = {"config": {"profile": 8}}
    feed.static = [section("Configuration record"), row("Profile", "8")]
    dialog = view.DVMetadataDialog()
    dialog._rows()
    clock.now += 0.5
    dialog._rows()
    assert feed.static_builds == 1
    feed.parsed = {"config": {"profile": 7}}
    feed.static = [section("Configuration record"), row("Profile", "7")]
    assert dialog._rows()[-1] == row("Profile", "7")
    assert feed.static_builds == 2
    clock.now += 0.9
    dialog._rows()
    assert feed.static_builds == 2
    clock.now += 0.1
    dialog._rows()
    assert feed.static_builds == 3


def test_a_failed_static_rebuild_waits_for_the_interval(feed, clock):
    feed.scene = [section("L1"), row("Max", "1000")]
    feed.static_error = RuntimeError("bad block")
    dialog = view.DVMetadataDialog()
    with pytest.raises(RuntimeError):
        dialog._rows()
    feed.static_error = None
    feed.static = [section("RPU")]
    assert dialog._rows() == feed.scene
    assert feed.static_builds == 1
    clock.now += 1.0
    assert dialog._rows()[-1] == section("RPU")


# --- Opening and refreshing -----------------------------------------------------

def test_opening_fills_the_list_on_the_start_section_and_focuses_it(feed):
    feed.scene = ROWS
    dialog = view.DVMetadataDialog()
    dialog.start_section = "RPU"
    dialog.onInit()
    dialog.join_update_loop()
    assert ("setFocusId", (LIST,)) in dialog.calls
    assert len(listed(dialog).items) == len(ROWS)
    assert selections(listed(dialog)) == [7, 6]
    # Nothing is playing in the stubs, so the refresh loop ends the session.
    assert dialog.calls[-1] == ("close", ())
    assert dialog.back_to_caller is False


def test_a_failed_first_fill_is_logged_and_the_view_still_opens(monkeypatch):
    def broken():
        raise RuntimeError("no side data")

    monkeypatch.setattr(dvmetadata, "build_scene_rows", broken)
    dialog = view.DVMetadataDialog()
    dialog.onInit()
    dialog.join_update_loop()
    assert ("setFocusId", (LIST,)) in dialog.calls
    assert warnings() == [
        "TinyPPI: DV metadata refresh failed, continuing with the last values: no side data"]


def watching(dialog, monkeypatch, player, monitor):
    monkeypatch.setattr(xbmc, "Player", lambda: player)
    dialog._monitor = monitor
    dialog._running = True


def test_the_list_refreshes_while_the_video_plays(feed, monkeypatch):
    xbmc.CONDITIONS[FULLSCREEN] = True
    feed.scene = [section("L1"), row("Max", "1000")]

    def tick(waits):
        feed.scene = [section("L1"), row("Max", str(1000 + len(waits)))]
        return len(waits) == 3

    dialog = view.DVMetadataDialog()
    monitor = Monitor(on_wait=tick)
    watching(dialog, monkeypatch, Player(), monitor)
    dialog._update_loop()
    assert monitor.waits == [0.1, 0.1, 0.1]
    assert values(dialog)[1] == f"[COLOR={FALLBACK}]1002[/COLOR]"
    assert dialog.calls == [("close", ())]
    assert dialog.back_to_caller is False


@pytest.mark.parametrize(("playing", "fullscreen", "aborted", "running"), [
    (False, True, False, True),     # playback stopped
    (True, False, False, True),     # fullscreen video left
    (True, True, True, True),       # Kodi shutting down
    (True, True, False, False),     # view already closing
])
def test_the_view_closes_when_it_should_not_refresh(
        feed, monkeypatch, playing, fullscreen, aborted, running):
    xbmc.CONDITIONS[FULLSCREEN] = fullscreen
    feed.scene = ROWS
    dialog = view.DVMetadataDialog()
    monitor = Monitor(aborted=aborted)
    watching(dialog, monkeypatch, Player(playing), monitor)
    dialog._running = running
    dialog._update_loop()
    assert listed(dialog).items == []
    assert monitor.waits == []
    assert dialog.calls == [("close", ())]
    assert dialog.back_to_caller is False


def test_playback_ending_mid_view_ends_the_session(feed, monkeypatch):
    xbmc.CONDITIONS[FULLSCREEN] = True
    feed.scene = ROWS
    player = Player()

    def stop(waits):
        player.playing = False
        return False

    dialog = view.DVMetadataDialog()
    monitor = Monitor(on_wait=stop)
    watching(dialog, monkeypatch, player, monitor)
    dialog._update_loop()
    assert monitor.waits == [0.1]
    assert len(listed(dialog).items) == len(ROWS)
    assert dialog.calls == [("close", ())]


def test_a_failing_refresh_is_logged_once_and_the_loop_goes_on(monkeypatch):
    xbmc.CONDITIONS[FULLSCREEN] = True

    def broken():
        raise RuntimeError("parser crashed")

    monkeypatch.setattr(dvmetadata, "build_scene_rows", broken)
    dialog = view.DVMetadataDialog()
    monitor = Monitor(on_wait=lambda waits: len(waits) == 3)
    watching(dialog, monkeypatch, Player(), monitor)
    dialog._update_loop()
    assert len(monitor.waits) == 3
    assert warnings() == [
        "TinyPPI: DV metadata refresh failed, continuing with the last values: parser crashed"]
    assert dialog.calls == [("close", ())]


# --- A single section -----------------------------------------------------------

@pytest.mark.parametrize(("title", "rows"), [
    ("L1", ROWS[:3]),
    ("L5", ROWS[4:6]),
    ("RPU", ROWS[6:]),
    ("L8", [section("L8")]),     # the block went away
])
def test_a_section_view_shows_its_section_only(feed, title, rows):
    feed.scene = ROWS
    dialog = view.DVSectionDialog()
    dialog.section = title
    assert dialog._rows() == rows


def test_a_section_view_selects_its_heading_once(feed):
    feed.scene = ROWS
    dialog = view.DVSectionDialog()
    dialog.section = "L1"
    dialog._fill(dialog._rows())
    control = listed(dialog)
    assert selections(control) == [2, 0]
    control.calls.clear()
    feed.scene = [section("L1"), row("Max", "1000"), row("Min", "0"), row("Avg", "92")]
    dialog._fill(dialog._rows())
    assert len(control.items) == 4
    assert calls(control, "setHeight") == [("setHeight", (120,))]
    assert selections(control) == []


@pytest.mark.parametrize("action", [
    xbmcgui.ACTION_SELECT_ITEM, xbmcgui.ACTION_MOVE_DOWN, xbmcgui.ACTION_MOVE_UP,
])
def test_ok_and_the_arrows_leave_a_section_view_to_kodi(action, clock):
    dialog = view.DVSectionDialog()
    dialog._fill(ROWS)
    settled(dialog, clock)
    listed(dialog).calls.clear()
    dialog.onAction(xbmcgui.Action(action))
    dialog.onClick(LIST)
    assert dialog.calls == [] and listed(dialog).calls == []
    assert dialog.open_section == ""


@pytest.mark.parametrize(("action", "back"), [
    (xbmcgui.ACTION_PREVIOUS_MENU, True),
    (xbmcgui.ACTION_NAV_BACK, True),
    (xbmcgui.ACTION_STOP, False),
])
def test_back_leaves_a_section_for_the_list_and_stop_ends_the_session(action, back):
    dialog = view.DVSectionDialog()
    dialog.onAction(xbmcgui.Action(action))
    assert dialog.back_to_caller is back
    assert dialog.calls == [("close", ())]


# --- The session ------------------------------------------------------------------

def test_the_windows_are_built_from_the_metadata_skin_file():
    class Recorder(xbmcgui.WindowXMLDialog):
        def __init__(self, *args):
            super().__init__(*args)
            self.args = args

    assert view._dialog(Recorder).args == (
        "script-tinyppi-dv-metadata.xml", xbmcaddon.ROOT, "Default", "1080i")
    assert isinstance(view._dialog(view.DVSectionDialog), view.DVSectionDialog)


@pytest.fixture
def viewer(monkeypatch):
    """Plays the viewer: each window shown runs the next scripted answer."""
    shown = []
    answers = []

    def do_modal(dialog):
        home = xbmcgui.Window(10000)
        if isinstance(dialog, view.DVSectionDialog):
            shown.append(("section", dialog.section, home.getProperty(SECTION_VIEW)))
        else:
            shown.append(("list", dialog.start_section, home.getProperty(SECTION_VIEW)))
        answers.pop(0)(dialog)

    monkeypatch.setattr(view.DVMetadataDialog, "doModal", do_modal)
    return shown, answers


def back(dialog):
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))


def stop(dialog):
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_STOP))


def opens(title):
    def answer(dialog):
        dialog.open_section = title
        dialog._close(back_to_caller=False)
    return answer


@pytest.mark.parametrize(("answers", "shown", "result"), [
    ([back], [("list", "", "")], True),
    ([stop], [("list", "", "")], False),
    ([opens("L2"), back, back],
     [("list", "", ""), ("section", "L2", "1"), ("list", "L2", "")], True),
    ([opens("L2"), back, opens("RPU"), back, stop],
     [("list", "", ""), ("section", "L2", "1"), ("list", "L2", ""),
      ("section", "RPU", "1"), ("list", "RPU", "")], False),
    ([opens("L2"), stop], [("list", "", ""), ("section", "L2", "1")], False),
])
def test_the_session_moves_between_the_list_and_its_sections(viewer, answers, shown, result):
    seen, script = viewer
    script.extend(answers)
    assert view.open_dv_metadata() is result
    assert seen == shown
    assert xbmcgui.Window(10000).getProperty(SECTION_VIEW) == ""


def test_the_section_hint_is_cleared_when_a_section_fails(viewer):
    _seen, script = viewer

    def crash(dialog):
        raise RuntimeError("skin error")

    script.append(crash)
    with pytest.raises(RuntimeError):
        view._show_section("L2")
    assert xbmcgui.Window(10000).getProperty(SECTION_VIEW) == ""
