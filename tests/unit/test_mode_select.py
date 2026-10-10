# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The VS10 mode-selection dialog (ui/mode_select.py)."""

import types

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_HDR10PLUS_PRESENT, PROP_RUNNING
from info import publish
from ui import dialog_layout as layout
from ui import mode_select, overlay

SDR_CHOICES = ["[B]#10116[/B]", "[B]Original[/B]", "[B]SDR → HDR10[/B]", "[B]SDR → Dolby Vision[/B]"]


class Detection:
    """Stands in for info.publish.publish_hdr_type: publishes queued HDR types in turn."""

    def __init__(self):
        self.queue = []
        self.error = None
        self.calls = 0
        self.side_effect = None

    def __call__(self, home):
        self.calls += 1
        if self.error:
            raise self.error
        if self.queue:
            home.setProperty("TinyPPI.HdrType", self.queue.pop(0))
        if self.side_effect:
            self.side_effect()


class Monitor:
    """Stands in for xbmc.Monitor: abort comes after *ticks* waits (at once with *abort*)."""

    def __init__(self, ticks=1, abort=False):
        self.ticks, self.abort = ticks, abort
        self.waits = []

    def abortRequested(self):
        return self.abort

    def waitForAbort(self, timeout=None):
        self.waits.append(timeout)
        return len(self.waits) >= self.ticks


@pytest.fixture
def detection(monkeypatch):
    fake = Detection()
    monkeypatch.setattr(publish, "publish_hdr_type", fake)
    return fake


@pytest.fixture
def threads(monkeypatch):
    """Record the threads the dialog starts instead of running them."""
    started = []

    def thread(target, daemon=False):
        return types.SimpleNamespace(start=lambda: started.append((target, daemon)))

    monkeypatch.setattr(mode_select.threading, "Thread", thread)
    return started


@pytest.fixture
def launch(monkeypatch):
    """Record what open_dialog does; *answer* is what the viewer does in the dialog."""
    record = types.SimpleNamespace(events=[], answer=lambda dialog: None)
    real_init = mode_select.SettingsDialog.__init__

    def init(self, *args, **kwargs):
        record.events.append(("created", args, home().getProperty(layout.PROP_PLACED)))
        real_init(self, *args, **kwargs)

    def do_modal(self):
        record.events.append(("shown",))
        record.answer(self)

    monkeypatch.setattr(mode_select.SettingsDialog, "__init__", init)
    monkeypatch.setattr(mode_select.SettingsDialog, "doModal", do_modal)
    monkeypatch.setattr(mode_select, "delay", lambda ms: record.events.append(("delay", ms)))
    monkeypatch.setattr(mode_select, "set_mode", lambda mode: record.events.append(("set_mode", mode)))
    return record


def home():
    return xbmcgui.Window(10000)


def opened(mode, hdr_type="", monitor=None):
    """Open the dialog in layout *mode* with *hdr_type* published."""
    xbmcaddon.SETTINGS["dialog_mode"] = str(mode)
    home().setProperty("TinyPPI.HdrType", hdr_type)
    dialog = mode_select.SettingsDialog(layout.xml_file(), mode_select._ADDON_PATH, "Default", "1080i")
    dialog.onInit()
    if monitor is not None:
        dialog._monitor = monitor
    return dialog


def focused(dialog):
    return [args[0] for name, args in dialog.calls if name == "setFocusId"]


def single_label(dialog):
    return dialog.getControl(layout.SINGLE_BUTTON).label


def closed(dialog):
    return ("close", ()) in dialog.calls


def logged(level, text):
    return [line for at, line in xbmc.LOG if at == level and text in line]


# --- Opening -------------------------------------------------------------------

@pytest.mark.parametrize("mode", [layout.MODE_DIALOG, layout.MODE_BAR])
@pytest.mark.parametrize(("hdr_type", "hdr10plus", "first"), [
    ("", "", 1001), ("hdr10", "", 1101), ("dolbyvision", "", 1201),
    ("hlg", "", 1301), ("dolbyvision", "1", 1301),
])
def test_the_panel_is_placed_revealed_and_its_branch_focused(detection, threads, mode, hdr_type, hdr10plus, first):
    xbmcaddon.SETTINGS.update(dialog_position_x="0", dialog_position_y="0")
    home().setProperty(PROP_HDR10PLUS_PRESENT, hdr10plus)
    dialog = opened(mode, hdr_type)
    assert dialog.getControl(layout.GROUP_PANEL).position == (layout.SCREEN_MARGIN, layout.SCREEN_MARGIN)
    assert home().getProperty(layout.PROP_PLACED) == "1"
    assert focused(dialog) == [first]
    assert detection.calls == 1                         # refreshed before placing
    assert threads == [(dialog._hdr_type_loop, True)]


def test_the_single_button_shows_the_first_choice_of_its_branch(detection, threads):
    dialog = opened(layout.MODE_SINGLE, "dolbyvision")
    assert focused(dialog) == [layout.SINGLE_BUTTON]
    assert single_label(dialog) == "[B]#10116[/B]"


def test_a_panel_that_cannot_be_moved_is_still_revealed(detection, threads, monkeypatch):
    def broken(_self, control_id):
        raise RuntimeError(f"no control {control_id}")

    monkeypatch.setattr(mode_select.SettingsDialog, "getControl", broken)
    dialog = opened(layout.MODE_BAR)
    assert logged(xbmc.LOGWARNING, "could not place the dialog panel: no control 2")
    assert home().getProperty(layout.PROP_PLACED) == "1"
    assert focused(dialog) == [1001]


def test_a_focus_kodi_refuses_is_only_a_debug_line(detection, threads, monkeypatch):
    def refuse(_self, control_id):
        raise RuntimeError("window gone")

    monkeypatch.setattr(mode_select.SettingsDialog, "setFocusId", refuse)
    opened(layout.MODE_DIALOG, "hdr10")
    assert logged(xbmc.LOGDEBUG, "could not focus dialog button 1101: window gone")
    assert not logged(xbmc.LOGWARNING, "")


def test_a_label_that_cannot_be_set_is_logged_only_while_open(detection, threads, monkeypatch):
    def broken(_self, control_id):
        raise RuntimeError("window gone")

    monkeypatch.setattr(mode_select.SettingsDialog, "getControl", broken)
    dialog = opened(layout.MODE_SINGLE)
    assert len(logged(xbmc.LOGWARNING, "could not set label 1500: window gone")) == 1
    dialog.close()
    dialog.onAction(xbmcgui.Action(layout.ACTION_MOVE_RIGHT))
    assert len(logged(xbmc.LOGWARNING, "could not set label 1500")) == 1


# --- The single button -----------------------------------------------------------

@pytest.mark.parametrize(("moves", "shown"), [
    ([], 0),
    ([layout.ACTION_MOVE_RIGHT], 1),
    ([layout.ACTION_MOVE_RIGHT] * 3, 3),
    ([layout.ACTION_MOVE_RIGHT] * 4, 0),                    # wraps forward
    ([layout.ACTION_MOVE_LEFT], 3),                         # wraps backward
    ([layout.ACTION_MOVE_RIGHT, layout.ACTION_MOVE_RIGHT, layout.ACTION_MOVE_LEFT], 1),
])
def test_left_and_right_step_through_the_choices(detection, threads, moves, shown):
    dialog = opened(layout.MODE_SINGLE)
    for move in moves:
        dialog.onAction(xbmcgui.Action(move))
    assert single_label(dialog) == SDR_CHOICES[shown]
    assert not closed(dialog)


def test_other_keys_leave_the_single_button_as_it_is(detection, threads):
    dialog = opened(layout.MODE_SINGLE)
    dialog.onAction(xbmcgui.Action(layout.ACTION_MOVE_RIGHT))
    before = list(dialog.getControl(layout.SINGLE_BUTTON).calls)
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert dialog.getControl(layout.SINGLE_BUTTON).calls == before
    assert not closed(dialog)


@pytest.mark.parametrize(("moves", "mode"), [
    (1, "original_sdr"), (2, "hdr10"), (3, "dv"), (7, "dv"),
])
def test_the_single_button_applies_its_current_choice(detection, threads, launch, moves, mode):
    xbmcaddon.SETTINGS["dialog_mode"] = str(layout.MODE_SINGLE)

    def answer(dialog):
        dialog.onInit()
        for _ in range(moves):
            dialog.onAction(xbmcgui.Action(layout.ACTION_MOVE_RIGHT))
        dialog.onClick(layout.SINGLE_BUTTON)
        assert closed(dialog)

    launch.answer = answer
    mode_select.open_dialog()
    assert launch.events[-2:] == [("delay", 250), ("set_mode", mode)]


@pytest.mark.parametrize("mode", [layout.MODE_DIALOG, layout.MODE_BAR])
def test_left_and_right_belong_to_kodi_outside_the_single_layout(detection, threads, mode):
    dialog = opened(mode)
    for move in (layout.ACTION_MOVE_LEFT, layout.ACTION_MOVE_RIGHT):
        dialog.onAction(xbmcgui.Action(move))
    assert dialog.getControl(layout.SINGLE_BUTTON).calls == []
    assert focused(dialog) == [1001]                    # Kodi moves the focus, not the dialog
    assert not closed(dialog)


# --- Choosing --------------------------------------------------------------------

@pytest.mark.parametrize("action", [xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_STOP])
@pytest.mark.parametrize("mode", [layout.MODE_SINGLE, layout.MODE_BAR])
def test_back_and_stop_close_without_a_choice(detection, threads, action, mode):
    monitor = Monitor(ticks=3)
    dialog = opened(mode, monitor=monitor)
    dialog.onAction(xbmcgui.Action(action))
    assert closed(dialog) and dialog._pending_mode is None
    # The refresh loop, started with the dialog, ends without another read.
    dialog._hdr_type_loop()
    assert detection.calls == 1 and monitor.waits == []


@pytest.mark.parametrize(("hdr_type", "control_id", "mode"), [
    ("", 1002, "original_sdr"), ("", 1003, "hdr10"), ("", 1004, "dv"),
    ("hdr10", 1005, "original_hdr"), ("hdr10", 1006, "sdr8"), ("hdr10", 1008, "dv"),
    ("dolbyvision", 1012, "original_dv"), ("dolbyvision", 1013, "sdr8"),
])
def test_a_mode_button_closes_and_its_mode_is_applied_once_the_dialog_is_gone(
        detection, threads, launch, hdr_type, control_id, mode):
    xbmcaddon.SETTINGS["dialog_mode"] = str(layout.MODE_DIALOG)
    home().setProperty("TinyPPI.HdrType", hdr_type)

    def answer(dialog):
        dialog.onInit()
        dialog.onClick(control_id)
        assert closed(dialog)
        assert launch.events[-1] == ("shown",)          # nothing applied while it closes

    launch.answer = answer
    mode_select.open_dialog()
    assert launch.events[-2:] == [("delay", 250), ("set_mode", mode)]


@pytest.mark.parametrize(("mode", "control_id"), [
    (layout.MODE_DIALOG, 1001), (layout.MODE_BAR, 1001), (layout.MODE_SINGLE, layout.SINGLE_BUTTON),
])
def test_the_process_info_button_opens_the_overlay(detection, threads, monkeypatch, mode, control_id):
    def state():
        return [home().getProperty(prop) for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE)]

    shown = []
    monkeypatch.setattr(overlay, "open_tinyppi", lambda: shown.append(state()))
    for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE):
        home().setProperty(prop, "true")
    dialog = opened(mode)
    dialog.onClick(control_id)
    assert closed(dialog)
    assert shown == [["", "", ""]]                      # the dialog's state is released first
    assert dialog._pending_mode is None


def test_a_button_without_a_mode_does_nothing(detection, threads):
    dialog = opened(layout.MODE_DIALOG)
    dialog.onClick(4242)
    assert not closed(dialog) and dialog._pending_mode is None


# --- Following the stream -------------------------------------------------------

def test_a_branch_change_while_open_moves_the_focus(detection, threads):
    monitor = Monitor(ticks=3)
    dialog = opened(layout.MODE_DIALOG, monitor=monitor)
    detection.queue = ["dolbyvision", "dolbyvision"]
    dialog._hdr_type_loop()
    assert focused(dialog) == [1001, 1201]              # only refocused on the change
    assert monitor.waits == [0.5, 0.5, 0.5]
    assert detection.calls == 4


def test_a_branch_change_keeps_the_single_button_within_its_choices(detection, threads, monkeypatch):
    shown = []
    monkeypatch.setattr(overlay, "open_tinyppi", lambda: shown.append("overlay"))
    dialog = opened(layout.MODE_SINGLE, monitor=Monitor())
    detection.queue = ["dolbyvision"]
    for _ in range(3):
        dialog.onAction(xbmcgui.Action(layout.ACTION_MOVE_RIGHT))
    assert single_label(dialog) == SDR_CHOICES[3]
    dialog._hdr_type_loop()
    # The DV branch has three choices: step 3 wraps to the first.
    assert single_label(dialog) == "[B]#10116[/B]"
    dialog.onClick(layout.SINGLE_BUTTON)
    assert shown == ["overlay"] and dialog._pending_mode is None and closed(dialog)


def test_the_loop_stops_without_refocusing_once_the_dialog_closes(detection, threads):
    monitor = Monitor(ticks=10)
    dialog = opened(layout.MODE_DIALOG, monitor=monitor)
    detection.queue = ["dolbyvision"]
    detection.side_effect = dialog.close
    dialog._hdr_type_loop()
    assert focused(dialog) == [1001]
    assert monitor.waits == [0.5]
    assert detection.calls == 2


def test_the_loop_ends_at_once_when_kodi_shuts_down(detection, threads):
    monitor = Monitor(abort=True)
    dialog = opened(layout.MODE_DIALOG, monitor=monitor)
    dialog._hdr_type_loop()
    assert detection.calls == 1 and monitor.waits == []


def test_the_loop_does_nothing_before_the_dialog_is_shown(detection):
    dialog = mode_select.SettingsDialog("script-tinyppi-dialog.xml", mode_select._ADDON_PATH)
    dialog._hdr_type_loop()
    assert detection.calls == 0 and dialog.calls == []


def test_a_failing_hdr_read_is_logged_once_per_loop(detection, threads):
    detection.error = RuntimeError("sysfs gone")
    monitor = Monitor(ticks=3)
    dialog = opened(layout.MODE_DIALOG, monitor=monitor)
    assert len(logged(xbmc.LOGWARNING, "HDR type refresh failed: sysfs gone")) == 1
    dialog._hdr_type_loop()
    assert detection.calls == 4 and monitor.waits == [0.5] * 3
    assert len(logged(xbmc.LOGWARNING, "HDR type refresh failed: sysfs gone")) == 2
    assert focused(dialog) == [1001]                    # the branch stays as it was


# --- open_dialog -----------------------------------------------------------------

def test_open_dialog_applies_the_chosen_mode_once_the_dialog_is_gone(launch):
    xbmcaddon.SETTINGS["dialog_mode"] = str(layout.MODE_BAR)
    home().setProperty(layout.PROP_PLACED, "1")         # left over from the last time
    launch.answer = lambda dialog: dialog.onClick(1004)
    mode_select.open_dialog()
    assert launch.events == [
        ("created", ("script-tinyppi-dialog-bar.xml", xbmcaddon.ROOT, "Default", "1080i"), ""),
        ("shown",),
        ("delay", 250),
        ("set_mode", "dv"),
    ]


def test_open_dialog_without_a_choice_applies_nothing(launch):
    launch.answer = lambda dialog: dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    mode_select.open_dialog()
    assert [event[0] for event in launch.events] == ["created", "shown"]
