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
    """The video layer: shows 24 frames a second, less the ones dropped."""

    dropped = 0
    readings = 0
    present = True

    @classmethod
    def catch(cls):
        if not cls.present:
            return None
        cls.readings += 1
        return CLOCK[0], 1000 + round((CLOCK[0] - 100.0) * 24) - cls.dropped


@pytest.fixture
def driver(monkeypatch):
    """An Amlogic box playing a 24 fps film."""
    Layer.dropped, Layer.readings, Layer.present = 0, 0, True
    monkeypatch.setattr(fpsdrop, "_catch_frame", Layer.catch)
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
    and the readings that set where the difference sits."""
    watch = watching()
    tick(watch, 5)
    return watch


def published():
    return xbmcgui.Window(10000).getProperty(PROP_FPS_DROP)


def test_dropped_frames_are_published_as_rate_and_total(driver):
    watch = counting()
    tick(watch, 10)
    assert published() == "0|0"
    driver.dropped = 3
    tick(watch, 2)                                           # held back, then one reading
    assert published() == "0|0"
    tick(watch)                                              # a second reading shows it
    assert published() == "1|3" and fps_drop_reading() == (1, 3)
    assert "TinyPPI [fps]: 3 frame(s) dropped near 30 s" in [line for _level, line in xbmc.LOG]
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
    driver.dropped = 2
    tick(watch, 3)
    assert published() == "1|2"
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    tick(watch)                                              # its own start wait
    assert published() == "0|0"


def test_a_paused_player_keeps_the_count_and_settles_after(driver):
    watch = counting()
    driver.dropped = 2
    tick(watch, 3)
    read = driver.readings
    xbmc.CONDITIONS[fpsdrop._HOLDING] = True                 # paused, buffering, spooling
    tick(watch, 30)
    assert published() == "1|2" and driver.readings == read
    xbmc.CONDITIONS[fpsdrop._HOLDING] = False                # no Player.OnResume seen
    for _second in range(3):
        tick(watch)
        assert published() == "0|2"
    assert driver.readings == read
    driver.dropped = 30                                      # lost while settling
    tick(watch, 20)
    assert published() == "0|2"                              # never counted


def test_a_late_seek_announcement_drops_the_reading_held_back(driver):
    watch = counting()
    driver.dropped = 10                                      # the seek's first second
    tick(watch)                                              # read and held back
    watch.settle()                                           # Player.OnSeek, late
    tick(watch, 20)
    assert published() == "0|0"                              # never counted
    driver.dropped = 11
    tick(watch, 3)
    assert published() == "1|1"                              # counting again


def test_a_jump_of_the_play_time_is_a_seek(driver):
    watch = counting()
    driver.dropped = 10
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
    driver.dropped = 11
    tick(watch, 3)
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


@pytest.mark.parametrize("missing", ["play time", "frame rate", "frame count"])
def test_without_a_reading_nothing_is_published(driver, monkeypatch, missing):
    watch = counting()
    assert published() == "0|0"
    if missing == "play time":
        monkeypatch.setattr(fpsdrop, "_play_time", lambda: None)
    elif missing == "frame rate":
        xbmc.INFO["Player.Process(videofps)"] = ""
    else:
        driver.present = False                               # not an Amlogic box
    tick(watch, 3)
    assert published() == "" and fps_drop_reading() is None
    notes = [line for _level, line in xbmc.LOG if "no reading" in line]
    assert len(notes) == 1                                   # once, not every pass


def test_a_reading_after_none_is_noted_again_when_it_goes(driver):
    watch = counting()
    driver.present = False
    tick(watch)
    driver.present = True
    tick(watch)
    driver.present = False
    tick(watch)
    assert len([line for _level, line in xbmc.LOG if "no reading" in line]) == 2


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
def layer_file(monkeypatch):
    """The layer's count as successive reads find it, on a clock that only
    the waits move."""
    counts: list[int | None] = []
    clock = [50.0]
    monkeypatch.setattr(fpsdrop, "read_toggle_count", lambda: counts.pop(0))
    monkeypatch.setattr(fpsdrop.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fpsdrop.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return counts, clock


def test_a_reading_is_taken_as_the_next_picture_appears(layer_file):
    counts, clock = layer_file
    counts.extend([500, 500, 500, 501])
    assert fpsdrop._catch_frame() == (pytest.approx(50.003), 501)
    assert counts == []


def test_no_reading_without_a_new_picture_or_a_count(layer_file):
    counts, clock = layer_file
    counts.extend([500] * 300)
    assert fpsdrop._catch_frame() is None                    # the picture stands still
    assert clock[0] == pytest.approx(50.0 + fpsdrop.FRAME_WAIT, abs=fpsdrop.FRAME_POLL)
    counts[:] = [None]
    assert fpsdrop._catch_frame() is None                    # no count at all
    counts[:] = [500, None]
    assert fpsdrop._catch_frame() is None                    # gone while waiting


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
