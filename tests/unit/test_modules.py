# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Every module imports outside a player, and the small state holders work."""

import importlib
import os

import pytest

import xbmcgui

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "resources", "lib")
MODULES = sorted(
    os.path.relpath(os.path.join(folder, name), LIB)[:-3].replace(os.sep, ".")
    for folder, _dirs, files in os.walk(LIB)
    for name in files if name.endswith(".py") and name != "__init__.py"
)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_the_memo_holds_one_value_for_the_key_it_was_computed_for():
    from core.memo import KeyedMemo
    memo = KeyedMemo()
    assert memo.get("a") is None
    memo.put("a", "")
    assert memo.get("a") == "" and memo.get("b") is None
    memo.put(("yuv420p", 10), "HDR")
    assert memo.get(("yuv420p", 10)) == "HDR"
    assert memo.get("a") is None                 # one entry: the new key replaced it


def test_display_reset_without_drm_gives_up_once(monkeypatch):
    from core import display
    monkeypatch.setattr(display, "_drm_fds", list)            # no DRM card open
    monkeypatch.setattr(display, "_target", display._Target())   # not left to other tests
    assert display.reset("test") is False
    assert display._target.ids is False and display.reset() is False


def test_imax_titles_and_tags():
    from info import imax
    titles = imax._title_index()
    assert len(titles) > 50 and imax._title_index() is titles
    assert imax.is_known_imax_title("Dunkirk.2017.2160p.UHD.BluRay")
    assert imax.is_known_imax_title("Some.Film.IMAX.2160p")
    assert not imax.is_known_imax_title("Some.Film.2160p")


def test_dv_snapshot_without_video():
    from info import dvfields, dvinfo
    fields, playing = dvinfo._snapshot()
    assert playing is False and set(fields) == set(dvfields.FIELDS)
    assert dvinfo.get_sidedata(mapping=True) is None


def test_dv_metadata_holds_blocks_per_item():
    import xbmc
    from info import dvmetadata
    xbmc.INFO["Player.FilenameAndPath"] = "/films/a.mkv"
    held = dvmetadata._HeldBlocks()
    held.hold({"rpu": {"l1": {"max": 1}}, "config": {"profile": 8}})
    parsed, origin = held.hold({"rpu": {}, "config": None})
    assert parsed["config"] == {"profile": 8} and origin["config"] == dvmetadata.CACHED
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    parsed, origin = held.hold({"rpu": {}, "config": None})
    assert "config" not in origin


def test_a_closed_overlay_holds_off_reentry_while_it_settles(monkeypatch):
    import xbmc
    from core.utils import PROP_ACTIVE, PROP_RUNNING
    from ui import overlay
    held = []
    monkeypatch.setattr(xbmc.Monitor, "waitForAbort",
                        lambda self, timeout=None: held.append(
                            (timeout, overlay._releasing.is_set())) or False)
    home = xbmcgui.Window(10000)
    home.setProperty(PROP_RUNNING, "true")
    home.setProperty(PROP_ACTIVE, "true")
    overlay._release_overlay(home)
    assert held == [(0.2, True)]
    assert home.getProperty(PROP_RUNNING) == home.getProperty(PROP_ACTIVE) == ""
    assert not overlay._releasing.is_set()
