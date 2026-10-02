# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 switches requested from the dashboard (web/snapshot.py)."""

import sys
import time
import types

import pytest

from web import snapshot


@pytest.fixture
def switches(monkeypatch):
    """Replace ui.mode_select.set_mode with a slow recorder."""
    applied = []

    def set_mode(mode):
        applied.append(mode)
        time.sleep(0.3)
        if mode == "boom":
            raise ValueError("driver said no")

    module = types.ModuleType("ui.mode_select")
    module.set_mode = set_mode
    monkeypatch.setitem(sys.modules, "ui.mode_select", module)
    monkeypatch.setattr(snapshot, "_switcher", snapshot._ModeSwitcher())
    return applied


def wait_idle(timeout=3.0):
    deadline = time.monotonic() + timeout
    while snapshot._switcher._running and time.monotonic() < deadline:
        time.sleep(0.05)
    return not snapshot._switcher._running


def test_unknown_modes_are_refused(switches):
    assert not snapshot.apply_mode("rm -rf")
    assert not snapshot.apply_mode("")
    assert switches == []


def test_the_last_tap_wins(switches):
    first, second, third = sorted(snapshot._KNOWN_MODES)[:3]
    assert snapshot.apply_mode(first)
    time.sleep(0.05)                     # the first switch is running
    assert snapshot.apply_mode(second)   # replaced before it starts
    assert snapshot.apply_mode(third)
    assert wait_idle()
    assert switches == [first, third]


def test_a_failed_switch_does_not_stop_the_next(switches, monkeypatch):
    monkeypatch.setattr(snapshot, "_KNOWN_MODES", snapshot._KNOWN_MODES | {"boom"})
    mode = sorted(snapshot._KNOWN_MODES - {"boom"})[0]
    snapshot.apply_mode("boom")
    time.sleep(0.05)
    snapshot.apply_mode(mode)
    assert wait_idle()
    assert switches == ["boom", mode]


def test_the_offered_modes_depend_on_the_source():
    assert snapshot._options_for("hdr10plus") == ()
    assert snapshot._options_for("hlg") == ()
    assert snapshot._options_for("dolbyvision", hdr10plus=True) == ()
    assert snapshot._options_for("hdr10", playing=False) == ()
    offered = {source: [mode for mode, _label in snapshot._options_for(source)]
               for source in ("dolbyvision", "hdr10", "")}
    assert offered == {"dolbyvision": ["original_dv", "sdr8"],
                       "hdr10": ["original_hdr", "sdr8", "dv"],
                       "": ["original_sdr", "hdr10", "dv"]}
    assert set().union(*offered.values()) == snapshot._KNOWN_MODES
