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


def title_card():
    """A lit title in the middle of a black frame."""
    black = bytes((0, 0, 0, 255)) * WIDTH
    line = bytes((0, 0, 0, 255)) * 190 + bytes((40, 160, 255, 255)) * 260 + bytes((0, 0, 0, 255)) * 190
    return bytearray(black * 130 + line * 100 + black * 130)


def black_opening(top=46, black=20):
    """A film's black opening between flat bars, a title in the middle."""
    bar = bytes((16, 16, 16, 255)) * WIDTH
    dark = bytes((black, black, black, 255))
    plain = dark * WIDTH
    titled = dark * 190 + bytes((40, 160, 255, 255)) * 260 + dark * 190
    rows = HEIGHT - 2 * top
    return bytearray(bar * top + plain * (rows // 2 - 20) + titled * 40
                     + plain * (rows - rows // 2 - 20) + bar * top)


def odd_letterbox():
    """A picture of 2.62:1, no film ratio."""
    return frame(58, 58)


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
    """A canary build playing a UHD film."""
    Capture.frames, Capture.requests, Capture.made = [], [], 0
    monkeypatch.setattr(xbmc, "RenderCapture", Capture)
    CLOCK[0] = 100.0
    monkeypatch.setattr(barscan.time, "monotonic", lambda: CLOCK[0])
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO.update({"Player.FilenameAndPath": "/films/a.mkv",
                      "Player.Process(videowidth)": "3840",
                      "Player.Process(videoheight)": "2160",
                      "Player.Process(videodar)": "1.78"})
    return Capture


# The scanner's clock; ``scan`` moves it on by a confirming pause per frame.
CLOCK = [100.0]
STEP  = barscan.CONFIRM_SECONDS


def scan(scanner, *frames):
    Capture.frames.extend(frames)
    for _frame in frames or (None,):
        scanner._scan()
        CLOCK[0] += STEP


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

def test_the_scanner_idles_and_clears_its_bars_without_a_video(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    xbmc.CONDITIONS["Player.HasVideo"] = False
    scan(scanner)
    scan(scanner)
    assert bars() == ""
    assert len(canary.requests) == 2                        # no capture while idle
    assert scanner._capture is None


def test_it_measures_without_any_setting(canary):
    assert "measure_aspect_ratio" not in xbmcaddon.SETTINGS
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    assert bars() == "0 | 0 | 276 | 276"


def test_a_title_card_is_not_taken_for_the_picture(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    scan(scanner, *[title_card()] * 20)                     # five seconds of it
    assert bars() == "0 | 0 | 276 | 276"
    assert not scanner._tracker.pending


def test_a_film_that_opens_on_black_is_measured_from_its_black(canary):
    scanner = BarScanner()
    scan(scanner, *[black_opening()] * 4)                   # under a second
    assert bars() == ""
    scan(scanner, black_opening())
    assert bars() == "0 | 0 | 276 | 276"


def test_a_dark_frame_only_counts_as_a_standard_ratio(canary):
    scanner = BarScanner()
    scan(scanner, *[black_opening(top=58)] * 12)            # 2.62:1
    assert bars() == "" and not scanner._tracker.pending


def test_a_dark_frame_does_not_change_confirmed_bars(canary):
    scanner = BarScanner()
    scan(scanner, FULL, FULL)
    scan(scanner, *[black_opening()] * 12)                  # a vignette, a fade
    assert bars() == "0 | 0 | 0 | 0" and not scanner._tracker.pending


def test_an_odd_ratio_has_to_last(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    scan(scanner, *[odd_letterbox()] * 4)                   # a second of it
    assert bars() == "0 | 0 | 276 | 276"
    scan(scanner, *[odd_letterbox()] * 5)                   # past two seconds
    assert bars() == "0 | 0 | 348 | 348"


def test_a_waiting_measurement_gets_its_frame_as_soon_as_it_counts(canary):
    scanner = BarScanner()
    assert scanner._pause() == barscan.SCAN_INTERVAL
    Capture.frames.append(SCOPE)
    scanner._scan()                                         # unconfirmed
    assert scanner._pause() == barscan.SCAN_INTERVAL        # the hold is longer
    CLOCK[0] += barscan.SCAN_INTERVAL
    assert scanner._pause() == pytest.approx(barscan.CONFIRM_SECONDS - barscan.SCAN_INTERVAL)
    CLOCK[0] += barscan.CONFIRM_SECONDS
    assert scanner._pause() == barscan.CONFIRM_INTERVAL     # overdue: at once
    scan(scanner, SCOPE)                                    # confirmed
    assert bars() == "0 | 0 | 276 | 276"
    assert scanner._pause() == barscan.SCAN_INTERVAL
    scan(scanner, DARK)                                     # proves nothing
    assert scanner._pause() == barscan.SCAN_INTERVAL


def test_the_framing_watch_keeps_its_own_pace(canary, monkeypatch):
    scanner = BarScanner()
    followed = []
    monkeypatch.setattr(scanner._framing, "follow", lambda: followed.append(1))
    for _pass in range(6):                                  # 0.2 s apart
        scanner._follow_framing()
        CLOCK[0] += 0.2
    assert len(followed) == 2                               # at 0 s and 0.6 s


def test_dolby_vision_with_l5_is_measured_too(canary):
    scanner = BarScanner()
    scan(scanner, SCOPE, SCOPE)
    assert properties.get_AspectRatioVar("0 | 0 | 0 | 0", is_dv=True) == "2.39"
    assert properties.get_AspectRatioVar("0 | 0 | 40 | 40", is_dv=True) == "2.39"


# --- Builds without the capture -----------------------------------------------

def test_a_build_that_cannot_capture_is_found_out_once(canary, monkeypatch):
    monkeypatch.undo()                                      # the stub: stock Kodi
    xbmc.CONDITIONS["Player.HasVideo"] = True
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
    monkeypatch.setattr(barscan, "CONFIRM_INTERVAL", 0.001)
    monkeypatch.setattr(barscan, "FOLLOW_INTERVAL", 0.0)
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
        CLOCK[0] += STEP
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
