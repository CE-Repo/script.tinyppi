# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The thread that counts the dropped frames during playback (info/fpsdrop.py)."""

import pytest

import xbmc
import xbmcgui
from core.utils import PROP_FPS_DROP, fps_drop_reading
from info import fpsdrop
from info.fpsdrop import FpsDropWatch

# The watch's clock, and how far a seek has moved the play time from it.
CLOCK = [100.0]
SEEKED = [0.0]


class Layer:
    """The video layer playing a 24 fps film: one picture a frame, less the
    frames it skipped, a time stamp 3750 ticks a frame."""

    skipped = 0
    readings = 0
    present = True

    @classmethod
    def read(cls):
        if not cls.present:
            return "the time stamp on screen"
        cls.readings += 1
        shown = round((CLOCK[0] - 100.0) * 24)
        return (shown + cls.skipped) * 3750, 1000 + shown


@pytest.fixture
def driver(monkeypatch):
    """An Amlogic box playing a 24 fps film."""
    Layer.skipped, Layer.readings, Layer.present = 0, 0, True
    monkeypatch.setattr(fpsdrop, "_read_layer", Layer.read)
    CLOCK[0], SEEKED[0] = 100.0, 0.0
    monkeypatch.setattr(fpsdrop.time, "monotonic", lambda: CLOCK[0])
    # The play time moves with the clock, unless a seek moves it.
    monkeypatch.setattr(fpsdrop, "_play_time", lambda: CLOCK[0] - 90.0 + SEEKED[0])
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO.update({"Player.FilenameAndPath": "/films/a.mkv",
                      "Player.Process(videofps)": "24.000"})
    return Layer


def tick(watch, seconds=1):
    """Run passes a second apart."""
    for _second in range(seconds):
        watch._sample()
        CLOCK[0] += fpsdrop.SAMPLE_INTERVAL


def watching():
    """A watch past the wait at the title's start."""
    watch = FpsDropWatch()
    watch._sample()
    CLOCK[0] += fpsdrop.SETTLE_SECONDS
    return watch


def counting():
    """A watch whose readings count: past the wait, the reading held back
    and the first reading of the stretch."""
    watch = watching()
    tick(watch, 2)
    return watch


def published():
    return xbmcgui.Window(10000).getProperty(PROP_FPS_DROP)


def test_skipped_frames_are_published_as_rate_and_total(driver):
    watch = counting()
    tick(watch, 10)
    assert published() == "0|0"
    driver.skipped = 3
    tick(watch)                                              # read and held back
    assert published() == "0|0"
    tick(watch)
    assert published() == "1|3" and fps_drop_reading() == (1, 3)
    assert "TinyPPI [fps]: 3 frame(s) dropped near 26 s" in [line for _level, line in xbmc.LOG]
    tick(watch, 10)
    assert published() == "0|3"


def test_nothing_is_counted_while_a_title_starts(driver):
    watch = FpsDropWatch()
    for _second in range(3):
        tick(watch)                                          # the layer is not read
        assert published() == "0|0"
    assert driver.readings == 0
    tick(watch)
    assert driver.readings == 1


def test_another_title_starts_over(driver):
    watch = counting()
    driver.skipped = 2
    tick(watch, 2)
    assert published() == "1|2"
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    tick(watch)                                              # its own start wait
    assert published() == "0|0"


def test_a_paused_player_keeps_the_count_and_settles_after(driver):
    watch = counting()
    driver.skipped = 2
    tick(watch, 2)
    read = driver.readings
    xbmc.CONDITIONS[fpsdrop._HOLDING] = True                 # paused, buffering, spooling
    tick(watch, 30)
    assert published() == "1|2" and driver.readings == read
    xbmc.CONDITIONS[fpsdrop._HOLDING] = False                # no Player.OnResume seen
    for _second in range(3):
        tick(watch)
        assert published() == "0|2"
    assert driver.readings == read
    driver.skipped = 30                                      # skipped while settling
    tick(watch, 20)
    assert published() == "0|2"                              # never counted


def test_a_late_seek_announcement_drops_the_reading_held_back(driver):
    watch = counting()
    driver.skipped = 10                                      # the seek's first second
    tick(watch)                                              # read and held back
    watch.settle()                                           # Player.OnSeek, late
    tick(watch, 20)
    assert published() == "0|0"                              # never counted
    driver.skipped = 11
    tick(watch, 2)
    assert published() == "1|1"                              # counting again


def test_a_jump_of_the_play_time_is_a_seek(driver):
    watch = counting()
    driver.skipped = 10
    tick(watch)                                              # read and held back
    SEEKED[0] += 120                                         # before Kodi announces it
    read = driver.readings
    tick(watch)
    assert published() == "0|0" and driver.readings == read
    assert "TinyPPI [fps]: play time jumped by 121.0 s: a seek" in [
        line for _level, line in xbmc.LOG]
    tick(watch, 20)
    assert published() == "0|0"                              # the 10 never counted
    SEEKED[0] += fpsdrop.JUMP_TOLERANCE                      # within the tolerance
    driver.skipped = 11
    tick(watch, 2)
    assert published() == "1|1"


def test_a_seek_under_way_starts_the_wait_too(driver):
    watch = counting()
    xbmc.CONDITIONS["Player.Seeking"] = True
    tick(watch)
    xbmc.CONDITIONS["Player.Seeking"] = False
    read = driver.readings
    tick(watch, 2)                                           # still settling
    assert published() == "0|0" and driver.readings == read
    tick(watch)
    assert driver.readings == read + 1


def test_a_missing_reading_is_skipped_until_it_keeps_missing(driver):
    watch = counting()
    driver.skipped = 1
    tick(watch, 2)
    assert published() == "1|1"
    driver.present = False                                   # no frame queued
    tick(watch, fpsdrop.MISSES_ALLOWED - 1)
    assert published() == "1|1"                              # the row stays
    driver.present = True
    driver.skipped = 2
    tick(watch, 2)
    assert fps_drop_reading()[1] == 2                        # counted across the gap
    assert not [line for _level, line in xbmc.LOG if "no reading" in line]


@pytest.mark.parametrize("missing", ["play time", "frame rate", "layer"])
def test_without_readings_the_row_empties(driver, monkeypatch, missing):
    watch = counting()
    assert published() == "0|0"
    if missing == "play time":
        monkeypatch.setattr(fpsdrop, "_play_time", lambda: None)
    elif missing == "frame rate":
        xbmc.INFO["Player.Process(videofps)"] = ""
    else:
        driver.present = False                               # not an Amlogic box
    tick(watch, fpsdrop.MISSES_ALLOWED + 2)
    assert published() == "" and fps_drop_reading() is None
    notes = [line for _level, line in xbmc.LOG if "no reading" in line]
    what = {"play time": "the play time", "frame rate": "the frame rate",
            "layer": "the time stamp on screen"}[missing]
    assert notes == [f"TinyPPI [fps]: no reading in 3 passes in a row: {what} is missing"]


def test_without_a_video_nothing_is_published(driver):
    watch = counting()
    xbmc.CONDITIONS["Player.HasVideo"] = False
    tick(watch)
    assert published() == ""
    xbmc.CONDITIONS["Player.HasVideo"] = True
    tick(watch)                                              # the start wait
    assert published() == "0|0"


def test_the_property_is_written_only_when_it_changes(driver, monkeypatch):
    writes = []
    real = xbmcgui.Window.setProperty
    monkeypatch.setattr(xbmcgui.Window, "setProperty",
                        lambda self, key, value: (writes.append(value), real(self, key, value)))
    watch = watching()
    tick(watch, 10)
    assert writes == ["0|0"]


def test_the_play_time_and_the_frame_rate_come_from_kodi(monkeypatch):
    assert fpsdrop._play_time() is None                      # nothing playing
    monkeypatch.setattr(xbmc.Player, "getTime", lambda self: 12.5)
    assert fpsdrop._play_time() == 12.5
    xbmc.INFO["Player.Process(videofps)"] = "23.976"
    assert fpsdrop._video_fps() == 23.976
    for label in ("", "0.000", "n/a"):
        xbmc.INFO["Player.Process(videofps)"] = label
        assert fpsdrop._video_fps() is None


@pytest.fixture
def layer_files(monkeypatch):
    """The layer's picture count and time stamp as successive reads find them."""
    counts: list[int | None] = []
    stamps: list[int | None] = []
    pauses: list[float] = []
    monkeypatch.setattr(fpsdrop, "read_toggle_count", lambda: counts.pop(0))
    monkeypatch.setattr(fpsdrop, "read_video_pts", lambda: stamps.pop(0))
    monkeypatch.setattr(fpsdrop.time, "sleep", pauses.append)
    return counts, stamps, pauses


def test_the_count_and_the_time_stamp_belong_to_one_picture(layer_files):
    counts, stamps, pauses = layer_files
    counts.extend([500, 500])
    stamps.append(90_000)
    assert fpsdrop._read_layer() == (90_000, 500)
    assert pauses == []
    # A picture changed between the reads: read again.
    counts.extend([500, 501, 501, 501])
    stamps.extend([90_000, 93_750])
    assert fpsdrop._read_layer() == (93_750, 501)
    assert counts == [] and stamps == [] and pauses == [fpsdrop.LAYER_RETRY]


def test_the_time_stamp_is_looked_for_until_a_frame_waits(layer_files):
    counts, stamps, pauses = layer_files
    counts.extend([500, 500, 501, 501])
    stamps.extend([None, None, 97_500])                       # an empty queue, twice
    assert fpsdrop._read_layer() == (97_500, 501)
    assert len(pauses) == 2


def test_what_is_missing_when_there_is_no_layer_reading(layer_files):
    counts, stamps, pauses = layer_files
    counts.extend([500] * fpsdrop.LAYER_TRIES)
    stamps.extend([None] * fpsdrop.LAYER_TRIES)              # never a frame queued
    assert fpsdrop._read_layer() == "the time stamp on screen"
    assert len(pauses) == fpsdrop.LAYER_TRIES
    counts[:] = list(range(500, 500 + 2 * fpsdrop.LAYER_TRIES))
    stamps[:] = [1] * fpsdrop.LAYER_TRIES                    # a change every try
    assert fpsdrop._read_layer() == "a steady picture count"
    counts[:], stamps[:] = [None], []
    assert fpsdrop._read_layer() == "the picture count"
    counts[:], stamps[:] = [500, None], [1]
    assert fpsdrop._read_layer() == "the picture count"


def test_the_thread_clears_a_stale_count_and_stops(driver, monkeypatch):
    xbmcgui.Window(10000).setProperty(PROP_FPS_DROP, "3|99")   # an earlier session
    monkeypatch.setattr(fpsdrop, "SAMPLE_INTERVAL", 0.001)
    watch = FpsDropWatch()
    seen = []
    samples = watch._sample

    def stop_after_three():
        seen.append(published())
        samples()
        CLOCK[0] += fpsdrop.SETTLE_SECONDS
        if len(seen) == 3:
            watch.stop()
    monkeypatch.setattr(watch, "_sample", stop_after_three)
    watch.start()
    watch.join(5)
    assert not watch.is_alive()
    assert seen == ["", "0|0", "0|0"]                       # the start wait, then a reading
    assert driver.readings == 2
    assert published() == ""                                 # cleared on the way out


def test_a_failing_pass_is_logged_once_and_the_thread_goes_on(monkeypatch):
    monkeypatch.setattr(fpsdrop, "SAMPLE_INTERVAL", 0.001)
    watch = FpsDropWatch()
    passes = []

    def fail():
        passes.append(1)
        if len(passes) == 3:
            watch.stop()
        raise RuntimeError("no player")
    monkeypatch.setattr(watch, "_sample", fail)
    watch.run()
    assert len(passes) == 3
    assert [line for _level, line in xbmc.LOG if "dropped frames" in line] == [
        "TinyPPI [fps]: counting the dropped frames failed: no player"]
