# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The thread that measures the black bars during playback (info/barscan.py)."""

import pytest

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import PROP_MEASURED_BARS, PROP_WIDEST_ASPECT
from info import barscan, properties
from info.barscan import BarScanner

WIDTH, HEIGHT = 640, 360


def frame(top=0, bottom=0, level=200):
    """A 640 x 360 BGRA frame with a lit picture between two bars."""
    black, lit = bytes((0, 0, 0, 255)) * WIDTH, bytes((level, level, level, 255)) * WIDTH
    return bytearray(black * top + lit * (HEIGHT - top - bottom) + black * bottom)


SCOPE, FULL, DARK = frame(46, 46), frame(), frame(level=0)


class Capture:
    """A Kodi that captures the video: hands out the frames queued for it."""

    frames: list[bytearray] = []
    requests: list[tuple[int, int, bool]] = []
    made = 0

    def __init__(self):
        Capture.made += 1

    def getAspectRatio(self):
        return 1.7778

    def capture(self, width, height, composite=False):
        Capture.requests.append((width, height, composite))

    def getImage(self, msecs=0):
        return Capture.frames.pop(0) if Capture.frames else bytearray()


@pytest.fixture
def canary(monkeypatch):
    """A canary build playing a UHD film without L5, the setting on."""
    Capture.frames, Capture.requests, Capture.made = [], [], 0
    monkeypatch.setattr(xbmc, "RenderCapture", Capture)
    monkeypatch.setattr(barscan, "get_l5_offsets", lambda: "0 | 0 | 0 | 0")
    xbmcaddon.SETTINGS["measure_aspect_ratio"] = "true"
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO.update({"Player.FilenameAndPath": "/films/a.mkv",
                      "Player.Process(videowidth)": "3840",
                      "Player.Process(videoheight)": "2160",
                      "Player.Process(videodar)": "1.78"})
    return Capture


def scan(scanner, *frames):
    Capture.frames.extend(frames)
    for _frame in frames or (None,):
        scanner._scan()


def bars():
    return xbmcgui.Window(10000).getProperty(PROP_MEASURED_BARS)


def info_lines():
    return [line for level, line in xbmc.LOG if level >= xbmc.LOGINFO]


# --- Measuring ----------------------------------------------------------------

def test_two_frames_confirm_the_bars_in_coded_pixels(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE)
    assert bars() == ""
    scan(scanner, SCOPE)
    assert bars() == "0 | 0 | 276 | 276"
    assert properties.get_AspectRatioVar("N/A") == "2.39"
    assert canary.requests == [(640, 360, False)] * 2       # the video only
    assert canary.made == 1                                 # one capture, kept


def test_a_dark_scene_keeps_the_confirmed_bars(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE, DARK, DARK, DARK)
    assert bars() == "0 | 0 | 276 | 276"


def test_a_change_of_framing_is_followed(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE, FULL)
    assert bars() == "0 | 0 | 276 | 276"
    scan(scanner, FULL)
    assert bars() == "0 | 0 | 0 | 0"
    assert properties.get_AspectRatioVar("N/A") == "1.78"


def test_nothing_is_published_without_a_coded_frame(canary):
    del xbmc.INFO["Player.Process(videowidth)"]
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    assert bars() == ""


def test_a_paused_film_is_not_captured(canary):
    xbmc.CONDITIONS["Player.Paused"] = True
    scanner = BarScanner()
    scan(scanner)
    assert canary.requests == [] and canary.made == 0


def test_another_title_starts_over(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    scan(scanner, FULL)
    assert bars() == ""                                     # not the last film's bars
    scan(scanner, FULL)
    assert bars() == "0 | 0 | 0 | 0"


# --- When there is nothing to measure -----------------------------------------

@pytest.mark.parametrize("reason", ["setting off", "no video", "L5 declares the bars"])
def test_the_scanner_idles_and_clears_its_bars(canary, monkeypatch, reason):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    if reason == "setting off":
        xbmcaddon.SETTINGS["measure_aspect_ratio"] = "false"
    elif reason == "no video":
        xbmc.CONDITIONS["Player.HasVideo"] = False
    else:
        monkeypatch.setattr(barscan, "get_l5_offsets", lambda: "0 | 0 | 276 | 276")
    scan(scanner)
    scan(scanner)
    assert bars() == ""
    assert len(canary.requests) == 2                        # no capture while idle
    assert scanner._capture is None


def test_the_setting_is_on_by_default(canary):
    del xbmcaddon.SETTINGS["measure_aspect_ratio"]
    scan(BarScanner())
    assert canary.made == 1


# --- Builds without the capture -----------------------------------------------

def test_a_build_that_cannot_capture_is_found_out_once(canary, monkeypatch):
    monkeypatch.undo()                                      # the stub: stock Kodi
    xbmcaddon.SETTINGS["measure_aspect_ratio"] = "true"
    xbmc.CONDITIONS["Player.HasVideo"] = True
    monkeypatch.setattr(barscan, "get_l5_offsets", lambda: "0 | 0 | 0 | 0")
    scanner = BarScanner()
    scanner._scan()
    assert info_lines() == ["TinyPPI [bars]: this Kodi build cannot capture the video; "
                            "the aspect ratio is shown as Kodi reports it"]
    monkeypatch.setattr(xbmc, "RenderCapture", lambda: pytest.fail("captured again"))
    scanner._scan()
    scanner._scan()
    assert len(info_lines()) == 1
    assert bars() == ""
    xbmc.INFO.update({"Player.Process(videowidth)": "1920", "Player.Process(videoheight)": "1080",
                      "Player.Process(videodar)": "1.78"})
    assert properties.get_AspectRatioVar("N/A") == "1.78"   # as before the feature


def test_missing_frames_back_the_scanner_off(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    scan(scanner)
    scan(scanner)
    assert info_lines() == []
    scan(scanner)                                           # the third in a row
    assert info_lines() == ["TinyPPI [bars]: no frames from the video capture; "
                            "trying again every 60 s"]
    assert bars() == "0 | 0 | 276 | 276"                    # the last reading stands
    scan(scanner)
    assert len(canary.requests) == 5                        # waiting, not capturing
    scanner._retry_at = 0.0
    scan(scanner)                                           # still nothing: said once
    assert len(canary.requests) == 6 and len(info_lines()) == 1
    scanner._retry_at = 0.0
    scan(scanner, FULL, FULL)
    assert bars() == "0 | 0 | 0 | 0" and scanner._failures == 0


def test_a_frame_of_the_wrong_size_counts_as_missing(canary):
    scanner = BarScanner()
    scan(scanner, bytearray(16))
    assert scanner._failures == 1 and bars() == ""


# --- The thread ---------------------------------------------------------------

def test_the_thread_clears_stale_bars_and_stops(canary, monkeypatch):
    xbmcgui.Window(10000).setProperty(PROP_MEASURED_BARS, "0 | 0 | 1 | 1")   # an earlier session
    monkeypatch.setattr(barscan, "SCAN_INTERVAL", 0.001)
    scanner = BarScanner()
    followed = []
    monkeypatch.setattr(scanner._framing, "follow", lambda: followed.append(bars()))
    xbmcgui.Window(10000).setProperty(PROP_WIDEST_ASPECT, "2.39")
    seen = []
    scans = scanner._scan

    def stop_after_three():
        seen.append(bars())
        Capture.frames.append(SCOPE)
        scans()
        if len(seen) == 3:
            scanner.stop()
    monkeypatch.setattr(scanner, "_scan", stop_after_three)
    scanner.start()
    scanner.join(5)
    assert not scanner.is_alive()
    assert seen == ["", "", "0 | 0 | 276 | 276"]
    assert followed == ["", "0 | 0 | 276 | 276", "0 | 0 | 276 | 276"]   # after each scan
    assert bars() == ""                                     # nothing left behind
    assert xbmcgui.Window(10000).getProperty(PROP_WIDEST_ASPECT) == ""


def test_a_failing_pass_is_logged_once_and_the_thread_goes_on(monkeypatch):
    monkeypatch.setattr(barscan, "SCAN_INTERVAL", 0.001)
    scanner = BarScanner()
    errors = iter(["add-on being updated", "add-on being updated", "no window"])

    def broken():
        try:
            raise RuntimeError(next(errors))
        except StopIteration:
            scanner.stop()
    monkeypatch.setattr(scanner, "_scan", broken)
    scanner.run()
    assert [line for level, line in xbmc.LOG if level == xbmc.LOGWARNING] == [
        "TinyPPI [bars]: measuring failed: add-on being updated",
        "TinyPPI [bars]: measuring failed: no window",
    ]
