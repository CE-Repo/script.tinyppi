# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The add-on's entry point: handing a view to the service and dispatching commands (main.py)."""

import importlib
import os
import runpy
import sys

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from core import vs10
from core.constants import OPEN_WITHDRAWN, PROP_OPEN_ACK, PROP_OPEN_REQUEST, PROP_SERVICE
from ui import overlay, splash, theme, webinfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAIN = os.path.join(ROOT, "main.py")
LIB = os.path.join(ROOT, "resources", "lib")


@pytest.fixture
def main(monkeypatch):
    monkeypatch.syspath_prepend(ROOT)
    module = importlib.import_module("main")
    assert module.__file__ == MAIN
    return module


@pytest.fixture
def opened(monkeypatch):
    """Record every view and command main() can start, instead of starting it."""
    seen = []
    monkeypatch.setattr(overlay, "open_tinyppi", lambda: seen.append("overlay"))
    monkeypatch.setattr(overlay, "open_dialog_mode", lambda: seen.append("dialog"))
    monkeypatch.setattr(splash, "open_splash", lambda: seen.append("splash"))
    monkeypatch.setattr(vs10, "set_mode", lambda mode: seen.append(("run_mode", mode)))
    monkeypatch.setattr(theme, "pick_color", lambda sid, heading: seen.append(("pick_color", sid, heading)))
    monkeypatch.setattr(webinfo, "show_web_info", lambda: seen.append("web_info"))
    monkeypatch.setattr(webinfo, "new_web_token", lambda: seen.append("web_token"))
    return seen


def home():
    return xbmcgui.Window(10000)


class Service:
    """Stands in for the service while the launch sleeps: acknowledges after *after* naps."""

    def __init__(self, after=1):
        self.after = after
        self.naps = []

    def __call__(self, milliseconds):
        self.naps.append(milliseconds)
        if len(self.naps) == self.after:
            home().setProperty(PROP_OPEN_ACK, home().getProperty(PROP_OPEN_REQUEST))


@pytest.fixture
def service(monkeypatch):
    home().setProperty(PROP_SERVICE, "1")
    fake = Service()
    monkeypatch.setattr(xbmc, "sleep", fake)
    return fake


# --- The import path -------------------------------------------------------------

@pytest.mark.parametrize("listed", [False, True])
def test_the_library_folder_is_put_on_the_import_path_once(main, monkeypatch, listed):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != LIB] + ([LIB] if listed else []))
    monkeypatch.delitem(sys.modules, "main")
    importlib.import_module("main")
    assert sys.path.count(LIB) == 1
    # Put in front when missing, left where it was otherwise.
    assert sys.path.index(LIB) == (len(sys.path) - 1 if listed else 0)


@pytest.mark.parametrize(("raw", "args"), [
    ([], []), (["overlay"], ["overlay"]),
    (["run_mode,dv"], ["run_mode", "dv"]),
    (["pick_color,title_color", "32040"], ["pick_color", "title_color", "32040"]),
])
def test_kodis_comma_separated_arguments_are_flattened(main, raw, args):
    assert main._split_args(raw) == args


# --- Handing a view to the service ----------------------------------------------

@pytest.mark.parametrize(("view", "message"), [("overlay", "open_overlay"), ("dialog", "open_dialog")])
def test_a_running_service_that_acknowledges_takes_the_view(main, service, view, message):
    service.after = 3
    assert main._hand_to_service(view) is True
    [builtin] = xbmc.BUILTINS
    assert builtin == f"NotifyAll(script.tinyppi,{message})"
    request = home().getProperty(PROP_OPEN_REQUEST)
    assert request.startswith(f"{view}:{os.getpid()}:")
    assert home().getProperty(PROP_OPEN_ACK) == request
    assert service.naps == [main._ACK_STEP_MS] * 3


def test_an_earlier_acknowledgement_is_cleared_before_the_service_is_asked(main, service, monkeypatch):
    home().setProperty(PROP_OPEN_ACK, "overlay:1:2.000")   # from an earlier launch
    asked = []
    monkeypatch.setattr(xbmc, "executebuiltin", lambda command: asked.append(
        (command, home().getProperty(PROP_OPEN_ACK), home().getProperty(PROP_OPEN_REQUEST))))
    assert main._hand_to_service("overlay") is True
    [(command, ack, request)] = asked
    assert command == "NotifyAll(script.tinyppi,open_overlay)"
    assert ack == "" and request.startswith("overlay:")


def test_a_silent_service_has_the_request_withdrawn(main, service):
    service.after = 0                                   # never answers
    assert main._hand_to_service("overlay") is False
    assert sum(service.naps) == main._ACK_TIMEOUT_MS
    assert home().getProperty(PROP_OPEN_REQUEST) == OPEN_WITHDRAWN
    assert (xbmc.LOGWARNING, "TinyPPI: the service did not answer – opening in this script instead") in xbmc.LOG


@pytest.mark.parametrize(("running", "view"), [("", "overlay"), ("0", "dialog"), ("1", "splash")])
def test_no_handover_without_a_service_or_for_other_views(main, monkeypatch, running, view):
    home().setProperty(PROP_SERVICE, running)
    monkeypatch.setattr(xbmc, "sleep", pytest.fail)
    assert main._hand_to_service(view) is False
    assert xbmc.BUILTINS == []
    assert home().getProperty(PROP_OPEN_REQUEST) == ""


@pytest.mark.parametrize("view", ["overlay", "dialog"])
def test_a_view_the_service_took_is_not_opened_again(main, service, opened, view):
    main._open_view(view)
    assert opened == []


@pytest.mark.parametrize(("view", "local"), [("overlay", "overlay"), ("dialog", "dialog"), ("other", "overlay")])
def test_without_the_service_the_script_opens_the_view_itself(main, opened, view, local):
    main._open_view(view)
    assert opened == [local]


# --- Commands --------------------------------------------------------------------

@pytest.mark.parametrize(("argv", "started"), [
    (["overlay"], ["overlay"]),
    (["dialog"], ["dialog"]),
    (["splash"], ["splash"]),
    (["run_mode,dv"], [("run_mode", "dv")]),
    (["run_mode", "sdr8"], [("run_mode", "sdr8")]),
    (["run_mode"], ["overlay"]),                        # no mode given
    (["pick_color,title_color,32040"], [("pick_color", "title_color", "32040")]),
    (["pick_color,title_color"], [("pick_color", "title_color", "")]),
    (["pick_color"], ["overlay"]),                      # no setting given
    (["web_info"], ["web_info"]),
    (["web_token"], ["web_token"]),
    (["something_new"], ["overlay"]),
])
def test_each_command_starts_its_action(main, opened, monkeypatch, argv, started):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()
    assert opened == started


@pytest.mark.parametrize(("launch_mode", "started"), [("0", "overlay"), ("1", "dialog"), (None, "overlay")])
def test_without_a_command_the_launch_mode_setting_decides(main, opened, monkeypatch, launch_mode, started):
    if launch_mode is not None:
        xbmcaddon.SETTINGS["launch_mode"] = launch_mode
    monkeypatch.setattr(sys, "argv", ["main.py"])
    main.main()
    assert opened == [started]


def test_running_the_script_dispatches_its_arguments(opened, monkeypatch):
    monkeypatch.setattr(sys, "argv", [MAIN, "web_token"])
    runpy.run_path(MAIN, run_name="__main__")
    assert opened == ["web_token"]
