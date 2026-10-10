# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 switches requested from the dashboard (web/vs10.py)."""

import sys
import threading
import types

import pytest

import xbmc
from web import vs10


class Driver:
    """Stands in for core.vs10.set_mode: each switch holds until released."""

    def __init__(self):
        self.applied = []
        self.busy = threading.Event()        # a switch is under way
        self.release = threading.Event()     # lets the switches finish

    def set_mode(self, mode):
        self.applied.append(mode)
        self.busy.set()
        assert self.release.wait(2)
        if mode == "boom":
            raise ValueError("driver said no")


@pytest.fixture
def driver(monkeypatch):
    """A fresh switcher whose worker threads are recorded and joined."""
    fake = Driver()
    module = types.ModuleType("core.vs10")
    module.set_mode = fake.set_mode
    monkeypatch.setitem(sys.modules, "core.vs10", module)
    monkeypatch.setattr(vs10, "_switcher", vs10._ModeSwitcher())

    started = []

    class Thread(threading.Thread):
        def start(self):
            started.append(self)
            super().start()

    monkeypatch.setattr(vs10, "threading", types.SimpleNamespace(Lock=threading.Lock,
                                                                 Thread=Thread))
    fake.threads = started
    yield fake
    fake.release.set()
    for thread in started:
        thread.join(2)


def finish(driver):
    """Let every switch finish and wait for the worker to end."""
    driver.release.set()
    for thread in driver.threads:
        thread.join(2)
        assert not thread.is_alive()


def test_unknown_modes_are_refused(driver):
    assert not vs10.apply_mode("rm -rf")
    assert not vs10.apply_mode("")
    assert driver.applied == [] and driver.threads == []


def test_the_last_tap_wins(driver):
    first, second, third = sorted(vs10._KNOWN_MODES)[:3]
    assert vs10.apply_mode(first)
    assert driver.busy.wait(2)           # the first switch is running
    assert vs10.apply_mode(second)       # replaced before it starts
    assert vs10.apply_mode(third)
    finish(driver)
    assert driver.applied == [first, third]
    assert len(driver.threads) == 1      # one worker applied both
    assert (xbmc.LOGDEBUG, f"TinyPPI [web]: VS10 mode '{second}' replaced by '{third}' "
            "before it started") in xbmc.LOG


def test_a_failed_switch_does_not_stop_the_next(driver, monkeypatch):
    monkeypatch.setattr(vs10, "_KNOWN_MODES", vs10._KNOWN_MODES | {"boom"})
    mode = sorted(vs10._KNOWN_MODES - {"boom"})[0]
    assert vs10.apply_mode("boom")
    assert driver.busy.wait(2)
    assert vs10.apply_mode(mode)
    finish(driver)
    assert driver.applied == ["boom", mode]
    assert (xbmc.LOGERROR, "TinyPPI [web]: VS10 mode 'boom' failed: driver said no") in xbmc.LOG


def test_a_new_request_after_the_worker_ended_starts_a_new_one(driver):
    driver.release.set()
    assert vs10.apply_mode("dv")
    finish(driver)
    assert vs10.apply_mode("sdr8")
    finish(driver)
    assert driver.applied == ["dv", "sdr8"] and len(driver.threads) == 2


def test_the_offered_modes_depend_on_the_source():
    assert vs10._options_for("hdr10plus") == ()
    assert vs10._options_for("hlg") == ()
    assert vs10._options_for("dolbyvision", hdr10plus=True) == ()
    assert vs10._options_for("hdr10", playing=False) == ()
    offered = {source: [mode for mode, _label in vs10._options_for(source)]
               for source in ("dolbyvision", "hdr10", "")}
    assert offered == {"dolbyvision": ["original_dv", "sdr8"],
                       "hdr10": ["original_hdr", "sdr8", "dv"],
                       "": ["original_sdr", "hdr10", "dv"]}
    assert set().union(*offered.values()) == vs10._KNOWN_MODES


def test_a_switch_that_cannot_start_is_logged_and_forgotten(driver, monkeypatch):
    class NoThreads:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(vs10.threading, "Thread", NoThreads)
    assert vs10.apply_mode("dv")        # accepted, though it could not start
    assert (vs10._switcher._running, vs10._switcher._wanted) == (False, None)
    assert any(level == xbmc.LOGERROR and "VS10 mode 'dv' could not be started" in line
               for level, line in xbmc.LOG)
    assert driver.applied == []


def test_no_switch_starts_while_kodi_shuts_down(driver, monkeypatch):
    monkeypatch.setattr(xbmc.Monitor, "abortRequested", lambda self: True)
    assert vs10.apply_mode("dv")
    finish(driver)
    assert driver.applied == []
    assert (vs10._switcher._running, vs10._switcher._wanted) == (False, None)


def test_the_state_lists_the_buttons_and_the_current_output():
    xbmc.INFO["Player.Process(amlogic.eoft_gamut)"] = " HDR10 , BT2020"
    assert vs10.vs10_state("hdr10") == {
        "options": [{"mode": "original_hdr", "label": "HDR10 (Original)"},
                    {"mode": "sdr8", "label": "HDR10 → SDR"},
                    {"mode": "dv", "label": "HDR10 → Dolby Vision"}],
        "output": "HDR10",
    }
    assert vs10.vs10_state("hdr10", playing=False)["options"] == []
