# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 switches requested from the dashboard (web/vs10.py)."""

import sys
import time
import types

import pytest

from web import vs10


@pytest.fixture
def switches(monkeypatch):
    """Replace core.vs10.set_mode with a slow recorder."""
    applied = []

    def set_mode(mode):
        applied.append(mode)
        time.sleep(0.3)
        if mode == "boom":
            raise ValueError("driver said no")

    module = types.ModuleType("core.vs10")
    module.set_mode = set_mode
    monkeypatch.setitem(sys.modules, "core.vs10", module)
    monkeypatch.setattr(vs10, "_switcher", vs10._ModeSwitcher())
    return applied


def wait_idle(timeout=3.0):
    deadline = time.monotonic() + timeout
    while vs10._switcher._running and time.monotonic() < deadline:
        time.sleep(0.05)
    return not vs10._switcher._running


def test_unknown_modes_are_refused(switches):
    assert not vs10.apply_mode("rm -rf")
    assert not vs10.apply_mode("")
    assert switches == []


def test_the_last_tap_wins(switches):
    first, second, third = sorted(vs10._KNOWN_MODES)[:3]
    assert vs10.apply_mode(first)
    time.sleep(0.05)                     # the first switch is running
    assert vs10.apply_mode(second)   # replaced before it starts
    assert vs10.apply_mode(third)
    assert wait_idle()
    assert switches == [first, third]


def test_a_failed_switch_does_not_stop_the_next(switches, monkeypatch):
    monkeypatch.setattr(vs10, "_KNOWN_MODES", vs10._KNOWN_MODES | {"boom"})
    mode = sorted(vs10._KNOWN_MODES - {"boom"})[0]
    vs10.apply_mode("boom")
    time.sleep(0.05)
    vs10.apply_mode(mode)
    assert wait_idle()
    assert switches == ["boom", mode]


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
