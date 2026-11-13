# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The widest framing of the playing title (info/framing.py)."""

import pytest

import xbmc
import xbmcgui
from core.utils import PROP_WIDEST_ASPECT
from info import framing
from info.framing import ODD_SETTLE_PASSES, SETTLE_PASSES, FramingWatch, WidestRatio


def lasting(ratios, ratio, passes=SETTLE_PASSES):
    for _pass in range(passes):
        ratios.note(ratio)


# --- The widest ratio ---------------------------------------------------------

def test_a_ratio_counts_once_it_has_lasted():
    ratios = WidestRatio()
    lasting(ratios, 2.39, SETTLE_PASSES - 1)
    assert ratios.widest is None
    ratios.note(2.39)
    assert ratios.widest == 2.39


def test_only_a_wider_ratio_replaces_it():
    ratios = WidestRatio()
    lasting(ratios, 1.78)                                   # the film opens in IMAX
    assert ratios.widest == 1.78
    lasting(ratios, 2.39)
    assert ratios.widest == 2.39
    lasting(ratios, 1.78)                                   # an IMAX scene
    assert ratios.widest == 2.39


def test_a_stray_reading_does_not_count():
    ratios = WidestRatio()
    lasting(ratios, 2.39)
    lasting(ratios, 2.76, SETTLE_PASSES - 1)                # a fade, a studio logo
    ratios.note(2.39)
    assert ratios.widest == 2.39


def test_an_odd_ratio_has_to_last_longer():
    ratios = WidestRatio()
    lasting(ratios, 2.39)
    lasting(ratios, 2.47, ODD_SETTLE_PASSES - 1)            # no film ratio
    assert ratios.widest == 2.39
    ratios.note(2.47)
    assert ratios.widest == 2.47                            # a film framed like that


def test_an_unknown_ratio_is_never_the_widest():
    ratios = WidestRatio()
    lasting(ratios, None, SETTLE_PASSES + 2)
    assert ratios.widest is None


def test_a_reset_forgets_the_title():
    ratios = WidestRatio()
    lasting(ratios, 2.39)
    ratios.reset()
    assert ratios.widest is None
    lasting(ratios, 2.39, SETTLE_PASSES - 1)
    assert ratios.widest is None


# --- Following playback -------------------------------------------------------

@pytest.fixture
def film(monkeypatch):
    """A letterboxed film playing; the L5 offsets are set by the test."""
    offsets = {"l5": "0 | 0 | 138 | 138"}
    monkeypatch.setattr(framing, "get_l5_offsets", lambda: offsets["l5"])
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO.update({"Player.FilenameAndPath": "/films/a.mkv",
                      "Player.Process(videowidth)": "1920",
                      "Player.Process(videoheight)": "1080",
                      "Player.Process(videodar)": "1.78"})
    return offsets


def follow(watch, passes=SETTLE_PASSES):
    for _pass in range(passes):
        watch.follow()


def widest():
    return xbmcgui.Window(10000).getProperty(PROP_WIDEST_ASPECT)


def test_the_widest_ratio_is_published_once_it_has_lasted(film):
    watch = FramingWatch()
    follow(watch, SETTLE_PASSES - 1)
    assert widest() == ""
    watch.follow()
    assert widest() == "2.39"
    film["l5"] = "0 | 0 | 0 | 0"                            # an IMAX scene
    follow(watch)
    assert widest() == "2.39"


def test_another_title_starts_over(film):
    watch = FramingWatch()
    follow(watch)
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    watch.follow()
    assert widest() == ""


def test_the_end_of_playback_withdraws_it(film):
    xbmcgui.Window(10000).setProperty(PROP_WIDEST_ASPECT, "1.85")   # an earlier session
    watch = FramingWatch()
    xbmc.CONDITIONS["Player.HasVideo"] = False
    watch.follow()
    assert widest() == ""
    xbmc.CONDITIONS["Player.HasVideo"] = True
    follow(watch)
    assert widest() == "2.39"
    watch.clear()
    assert widest() == ""
