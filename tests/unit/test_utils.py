# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Kodi wrappers, change highlights and picture geometry (core/utils.py)."""

import re
import threading
import types

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from core import utils

COLOR = "FFFFCC00"


def lit(text):
    return f"[COLOR={COLOR}]{text}[/COLOR]"


class Recorder:
    """A property target that records every write."""

    def __init__(self):
        self.writes = []
        self.cleared = []

    def setProperty(self, name, value):
        self.writes.append((name, value))

    def clearProperty(self, name):
        self.cleared.append(name)


# --- Reading Kodi -----------------------------------------------------------

def test_a_read_pass_reads_each_label_and_condition_once():
    xbmc.INFO["Player.Title"] = "first"
    xbmc.CONDITIONS["Player.HasVideo"] = True
    with utils.read_pass():
        assert utils.info("Player.Title") == "first"
        assert utils.cond("Player.HasVideo") is True
        xbmc.INFO["Player.Title"] = "second"
        xbmc.CONDITIONS["Player.HasVideo"] = False
        with utils.read_pass():                      # an inner pass shares the cache
            assert utils.info("Player.Title") == "first"
            assert utils.cond("Player.HasVideo") is True
        assert utils.info("Player.Title") == "first"  # the inner pass kept it
    assert utils.info("Player.Title") == "second"
    assert utils.cond("Player.HasVideo") is False


def test_the_home_window_is_shared_within_a_pass_only():
    with utils.read_pass():
        assert utils.home_window() is utils.home_window()
    assert utils.home_window() is not utils.home_window()


def test_a_label_kodi_does_not_know_reads_empty():
    xbmc.INFO["Player.Process(amlogic.fake)"] = "Player.Process(amlogic.fake)"
    assert utils.info("Player.Process(amlogic.fake)") == ""
    with utils.read_pass():
        assert utils.info("Player.Process(amlogic.fake)") == ""


@pytest.mark.parametrize(("hdr_type", "dv"), [
    ("dolbyvision", True), ("DolbyVision", True), ("hdr10", False), ("", False),
])
def test_the_dv_branch_follows_the_effective_hdr_type(hdr_type, dv):
    xbmcgui.Window(10000).setProperty(utils.PROP_EFFECTIVE_HDR_TYPE, hdr_type)
    assert utils.effective_hdr_type() == hdr_type
    assert utils.is_effective_dv() is dv


@pytest.mark.parametrize(("raw", "expected"), [
    (None, ""), ("1,234,567", "1234567"), (3840, "3840"), ("", ""),
])
def test_clean_strips_thousands_separators(raw, expected):
    assert utils.clean(raw) == expected


# --- Strings ----------------------------------------------------------------

def test_strings_are_read_once_per_language(monkeypatch):
    clock = types.SimpleNamespace(now=100.0)
    language = types.SimpleNamespace(name="English")
    asked = []

    class Addon:
        @staticmethod
        def getLocalizedString(string_id):
            asked.append(string_id)
            return f"{language.name}:{string_id}"

    monkeypatch.setattr(utils, "time", types.SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(utils.settings, "addon", Addon)
    monkeypatch.setattr(xbmc, "getLanguage", lambda *_args: language.name)
    strings = utils._Strings()

    assert strings.get(1) == "English:1"
    assert strings.get(1) == "English:1"
    assert asked == [1]
    language.name = "German"
    clock.now += 0.5                       # not checked again yet
    assert strings.get(1) == "English:1"
    clock.now += 0.5
    assert strings.get(1) == "German:1"
    assert asked == [1, 1]
    clock.now += 5                         # checked, but the same language
    assert strings.get(1) == "German:1"
    assert asked == [1, 1]


def test_localized_answers_from_the_addon(monkeypatch):
    # A fresh cache, so strings another test left in the shared one cannot answer.
    monkeypatch.setattr(utils, "_strings", utils._Strings())
    assert utils.localized(32230) == "#32230"
    assert utils.localized(32231) == "#32231"


# --- Change highlights --------------------------------------------------------

def test_a_change_is_lit_for_the_hold_and_then_plain():
    marker = utils.ChangeHighlighter(hold=1.0)
    assert marker.mark("fps", "24", COLOR, now=0.0) == "24"          # no history yet
    assert marker.mark("fps", "24", COLOR, now=0.1) == "24"
    assert marker.mark("fps", "25", COLOR, now=0.2) == lit("25")
    assert marker.mark("fps", "25", COLOR, now=1.1) == lit("25")
    assert marker.mark("fps", "25", COLOR, now=1.2) == "25"


def test_only_the_changed_reading_of_a_composite_is_lit():
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("l5", "10 | 20 | 30", COLOR, now=0.0)
    assert marker.mark("l5", "10 | 21 | 30", COLOR, now=0.1) == f"10 | {lit('21')} | 30"
    # A second change does not cut the first one short.
    assert marker.mark("l5", "11 | 21 | 30", COLOR, now=0.5) == f"{lit('11')} | {lit('21')} | 30"
    assert marker.mark("l5", "11 | 21 | 30", COLOR, now=1.2) == f"{lit('11')} | 21 | 30"


@pytest.mark.parametrize(("before", "after"), [
    ("10 | 20", "10 | 20 | 30"),       # another number of readings
    (["10", "20"], "10 | 20"),         # a list turned into a string
])
def test_a_reading_that_changes_shape_is_lit_whole(before, after):
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("row", before, COLOR, now=0.0)
    assert marker.mark("row", after, COLOR, now=0.1) == lit(after)


def test_list_readings_are_lit_cell_by_cell():
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("rpu", ["L1", "100", "200"], COLOR, now=0.0)
    assert marker.mark("rpu", ["L1", "101", "200", "new"], COLOR, now=0.1) == [
        "L1", lit("101"), "200", lit("new")]


def test_a_list_after_a_string_is_lit_entirely_and_empty_cells_stay_bare():
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("rpu", "L1", COLOR, now=0.0)
    marker.mark("rpu", "L1  100", COLOR, now=0.1)       # shape change: whole value lit
    assert marker.mark("rpu", ["L2", "", "300"], COLOR, now=0.2) == [lit("L2"), "", lit("300")]


def test_without_a_color_nothing_is_lit_but_the_value_is_recorded():
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("fps", "24", COLOR, now=0.0)
    marker.mark("fps", "25", COLOR, now=0.1)
    assert marker.mark("fps", "26", "", now=0.2) == "26"
    assert marker.mark("fps", "26", COLOR, now=0.3) == "26"     # the lit part was dropped


def test_a_negative_hold_lights_nothing():
    marker = utils.ChangeHighlighter(hold=-5)
    marker.mark("fps", "24", COLOR, now=0.0)
    assert marker.mark("fps", "25", COLOR, now=0.1) == "25"


def test_marking_without_a_time_uses_the_clock(monkeypatch):
    monkeypatch.setattr(utils, "time", types.SimpleNamespace(monotonic=lambda: 50.0))
    marker = utils.ChangeHighlighter(hold=1.0)
    marker.mark("fps", "24", COLOR)
    assert marker.mark("fps", "25", COLOR) == lit("25")
    assert marker.mark("fps", "25", COLOR, now=50.5) == lit("25")
    assert marker.mark("fps", "25", COLOR, now=51.0) == "25"


def test_retain_forgets_rows_that_went_away():
    marker = utils.ChangeHighlighter(hold=1.0)
    for key in ("a", "b"):
        marker.mark(key, "1", COLOR, now=0.0)
        marker.mark(key, "2", COLOR, now=0.1)
    marker.retain(["a"])
    assert marker.mark("a", "3", COLOR, now=0.2) == lit("3")
    assert marker.mark("b", "3", COLOR, now=0.2) == "3"         # no history any more


@pytest.mark.parametrize(("stored", "seconds"), [
    ("1500", 1.5), ("0", utils.DEFAULT_HIGHLIGHT_HOLD), ("-20", utils.DEFAULT_HIGHLIGHT_HOLD),
])
def test_the_highlight_hold_comes_from_milliseconds(stored, seconds):
    xbmcaddon.SETTINGS["output_changed_duration"] = stored
    assert utils.highlight_hold("output_changed_duration") == seconds


def test_an_unreadable_highlight_hold_falls_back_to_the_default(monkeypatch):
    class Addon:
        @staticmethod
        def getSettingInt(_setting_id):
            raise TypeError("not an integer")
    monkeypatch.setattr(utils.settings, "addon", Addon)
    assert utils.highlight_hold("output_changed_duration") == utils.DEFAULT_HIGHLIGHT_HOLD


# --- Picture geometry -------------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [
    ("0 | 0 | 140 | 140", (0, 0, 140, 140)), ("1|2|3|4", (1, 2, 3, 4)),
    ("-1 | 0 | 0 | 0", (-1, 0, 0, 0)),
    ("", None), ("1 | 2 | 3", None), ("a | b | c | d", None), ("Not available", None),
])
def test_offsets_are_four_numbers(value, expected):
    assert utils.parse_offsets(value) == expected


@pytest.mark.parametrize(("width", "height", "expected"), [
    ("3,840", "2,160", (3840, 2160)), ("1920", "1080", (1920, 1080)),
    ("", "1080", None), ("1920", "abc", None), ("0", "1080", None), ("1920", "-1", None),
])
def test_the_coded_frame_from_kodi(width, height, expected):
    xbmc.INFO["Player.Process(videowidth)"] = width
    xbmc.INFO["Player.Process(videoheight)"] = height
    assert utils.coded_frame() == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("1.778", 1.778), ("23,976 fps", 23.976), ("DAR -2.5:1", -2.5), ("16", 16.0),
    ("", None), ("n/a", None),
])
def test_the_first_number_in_a_label(raw, expected):
    assert utils.first_float(raw) == expected


def test_a_match_that_is_no_number_reads_as_none(monkeypatch):
    # The pattern only matches numbers; a looser one must not leak a ValueError.
    monkeypatch.setattr(utils, "_DECIMAL_RE", re.compile(r"\d+(?:[.,]\d+)+"))
    assert utils.first_float("version 1.2.3") is None


@pytest.mark.parametrize(("offsets", "dar", "expected"), [
    ("0 | 0 | 140 | 140", "1.778", 1.778 * 1080 / 800),   # letterboxed scope
    ("240 | 240 | 0 | 0", "1.778", 1.778 * 1440 / 1920),  # pillarboxed 4:3
    ("0 | 0 | 0 | 0", "1.778", 1.778),
    ("960 | 960 | 0 | 0", "1.778", None),                 # the bars leave no picture
    ("0 | 0 | 540 | 540", "1.778", None),
    ("", "1.778", None),
    ("0 | 0 | 140 | 140", "", None),
])
def test_the_picture_ratio_inside_the_bars(offsets, dar, expected):
    xbmc.INFO["Player.Process(videowidth)"] = "1920"
    xbmc.INFO["Player.Process(videoheight)"] = "1080"
    xbmc.INFO["Player.Process(videodar)"] = dar
    result = utils.picture_aspect_ratio(offsets)
    assert result == (pytest.approx(expected) if expected is not None else None)


def test_no_picture_ratio_without_a_coded_frame():
    xbmc.INFO["Player.Process(videodar)"] = "1.778"
    assert utils.picture_aspect_ratio("0 | 0 | 140 | 140") is None


# --- Window properties --------------------------------------------------------

def test_a_batch_of_properties_is_published():
    window = Recorder()
    utils.set_window_properties(window, (("A", "1"), ("B", "2")))
    assert window.writes == [("A", "1"), ("B", "2")]


def test_only_changed_properties_are_written():
    window = Recorder()
    published = {"A": "1", "Other": "x"}
    utils.set_changed_properties(window, published, (("A", "1"), ("B", "2")))
    assert window.writes == [("B", "2")]
    assert published == {"A": "1", "Other": "x", "B": "2"}
    utils.set_changed_properties(window, published, (("A", "3"), ("B", "2")))
    assert window.writes == [("B", "2"), ("A", "3")]


def test_clearing_the_overlay_state():
    window = Recorder()
    utils.clear_overlay_state(window)
    assert window.cleared == [utils.PROP_RUNNING, utils.PROP_ACTIVE, utils.PROP_DIALOG_MODE]


# --- Refresh threads ----------------------------------------------------------

def test_no_refresh_thread_is_nothing_to_wait_for():
    utils.join_refresh_thread(None)
    assert xbmc.LOG == []


def test_a_finished_refresh_thread_is_joined_quietly():
    thread = threading.Thread(target=lambda: None)
    thread.start()
    utils.join_refresh_thread(thread)
    assert not thread.is_alive()
    assert xbmc.LOG == []


def test_a_wedged_refresh_thread_is_handed_over_with_a_warning():
    joined = []
    wedged = types.SimpleNamespace(join=joined.append, is_alive=lambda: True)
    utils.join_refresh_thread(wedged)
    assert joined == [utils._JOIN_TIMEOUT]
    assert xbmc.LOG == [(xbmc.LOGWARNING,
                         "TinyPPI: refresh thread still running after 1.0s, handing over anyway")]


def test_a_refresh_failure_is_logged_as_a_warning():
    utils.log_refresh_failure("overlay", ValueError("bad label"))
    assert xbmc.LOG == [(xbmc.LOGWARNING,
                         "TinyPPI: overlay refresh failed, continuing with the last values: "
                         "bad label")]
