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


@pytest.fixture
def driver(monkeypatch):
    """An Amlogic box playing a film: hands out the readings queued for it."""
    readings: list[tuple[int, int] | None] = []
    monkeypatch.setattr(fpsdrop, "read_fps_sysfs", lambda: readings.pop(0))
    CLOCK[0], SEEKED[0] = 100.0, 0.0
    monkeypatch.setattr(fpsdrop.time, "monotonic", lambda: CLOCK[0])
    # The play time moves with the clock, unless a seek moves it.
    monkeypatch.setattr(fpsdrop, "_play_time", lambda: CLOCK[0] - 90.0 + SEEKED[0])
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO["Player.FilenameAndPath"] = "/films/a.mkv"
    return readings


def tick(watch, seconds=1):
    """Run passes a second apart that read nothing."""
    for _second in range(seconds):
        watch._sample()
        CLOCK[0] += fpsdrop.SAMPLE_INTERVAL


def sample(watch, readings, *queued):
    """Run a pass a second for each reading."""
    for reading in queued:
        readings.append(reading)
        watch._sample()
        CLOCK[0] += fpsdrop.SAMPLE_INTERVAL


def watching():
    """A watch past the wait at the title's start."""
    watch = FpsDropWatch()
    watch._sample()
    CLOCK[0] += fpsdrop.SETTLE_SECONDS
    return watch


def published():
    return xbmcgui.Window(10000).getProperty(PROP_FPS_DROP)


def test_drops_are_counted_a_second_late(driver):
    watch = watching()
    sample(watch, driver, (24, 24), (24, 23), (24, 25), (24, 21))
    assert published() == "0|0"                              # out of step, no drop
    sample(watch, driver, (24, 24))                          # (24, 21) counted now
    assert published() == "1|3" and fps_drop_reading() == (1, 3)
    assert "TinyPPI [fps]: in 24, out 21" in [line for _level, line in xbmc.LOG]


def test_nothing_is_counted_while_a_title_starts(driver):
    watch = FpsDropWatch()
    for _second in range(3):
        tick(watch)                                          # the driver is not read
        assert published() == "0|0"
    assert driver == []
    sample(watch, driver, (24, 20), (24, 24))
    assert published() == "4|4"


def test_another_title_starts_over(driver):
    watch = watching()
    sample(watch, driver, (24, 20), (24, 24))
    assert published() == "4|4"
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    tick(watch)                                              # its own start wait
    assert published() == "0|0" and driver == []
    CLOCK[0] += fpsdrop.SETTLE_SECONDS
    sample(watch, driver, (24, 24), (24, 24))
    assert published() == "0|0"


def test_a_paused_player_keeps_the_count_and_settles_after(driver):
    watch = watching()
    sample(watch, driver, (24, 20), (24, 24))
    xbmc.CONDITIONS[fpsdrop._HOLDING] = True                 # paused, buffering, spooling
    tick(watch, 30)                                          # the driver is not read
    assert published() == "4|4" and driver == []
    xbmc.CONDITIONS[fpsdrop._HOLDING] = False                # no Player.OnResume seen
    for _second in range(3):
        tick(watch)
        assert published() == "0|4"
    assert driver == []
    sample(watch, driver, (24, 24), (24, 24))
    assert published() == "0|4"


def test_a_late_seek_announcement_drops_the_reading_held_back(driver):
    watch = watching()
    sample(watch, driver, (24, 24), (24, 10))                # the seek's first second
    assert published() == "0|0"
    watch.settle()                                           # Player.OnSeek, late
    for _second in range(3):
        tick(watch)                                          # the driver is not read
        assert published() == "0|0"
    sample(watch, driver, (24, 24), (24, 24))
    assert published() == "0|0"                              # (24, 10) never counted
    sample(watch, driver, (24, 21), (24, 24))
    assert published() == "1|3"


def test_a_jump_of_the_play_time_is_a_seek(driver):
    watch = watching()
    sample(watch, driver, (24, 24), (24, 10))
    SEEKED[0] += 120                                         # before Kodi announces it
    tick(watch)
    assert published() == "0|0" and driver == []
    assert "TinyPPI [fps]: play time jumped by 121.0 s: a seek" in [
        line for _level, line in xbmc.LOG]
    tick(watch, 2)
    sample(watch, driver, (24, 24), (24, 24))
    assert published() == "0|0"                              # (24, 10) never counted
    SEEKED[0] += fpsdrop.JUMP_TOLERANCE                      # within the tolerance
    sample(watch, driver, (24, 20), (24, 24))
    assert published() == "2|4"                              # 4 lost over 3 s


def test_a_seek_under_way_starts_the_wait_too(driver):
    watch = watching()
    sample(watch, driver, (24, 24))
    xbmc.CONDITIONS["Player.Seeking"] = True
    tick(watch)
    xbmc.CONDITIONS["Player.Seeking"] = False
    tick(watch, 2)                                           # still settling
    assert published() == "0|0" and driver == []
    sample(watch, driver, (24, 20), (24, 24))
    assert published() == "4|4"


def test_without_a_play_time_the_counters_still_count(driver, monkeypatch):
    monkeypatch.setattr(fpsdrop, "_play_time", lambda: None)
    watch = watching()
    sample(watch, driver, (24, 20), (24, 24))
    assert published() == "4|4"


def test_the_play_time_comes_from_the_player(monkeypatch):
    assert fpsdrop._play_time() is None                      # nothing playing
    monkeypatch.setattr(xbmc.Player, "getTime", lambda self: 12.5)
    assert fpsdrop._play_time() == 12.5


def test_without_a_video_or_the_counters_nothing_is_published(driver):
    watch = watching()
    sample(watch, driver, (24, 20), (24, 24))
    xbmc.CONDITIONS["Player.HasVideo"] = False
    tick(watch)
    assert published() == "" and fps_drop_reading() is None
    xbmc.CONDITIONS["Player.HasVideo"] = True
    tick(watch)                                              # the start wait
    CLOCK[0] += fpsdrop.SETTLE_SECONDS
    sample(watch, driver, None)                              # not an Amlogic box
    assert published() == ""
    sample(watch, driver, (24, 24))
    assert published() == "0|0"                              # counted afresh


def test_the_property_is_written_only_when_it_changes(driver, monkeypatch):
    writes = []
    real = xbmcgui.Window.setProperty
    monkeypatch.setattr(xbmcgui.Window, "setProperty",
                        lambda self, key, value: (writes.append(value), real(self, key, value)))
    watch = watching()
    sample(watch, driver, (24, 24), (24, 24), (24, 24))
    assert writes == ["0|0"]


def test_the_thread_clears_a_stale_count_and_stops(driver, monkeypatch):
    xbmcgui.Window(10000).setProperty(PROP_FPS_DROP, "3|99")   # an earlier session
    monkeypatch.setattr(fpsdrop, "SAMPLE_INTERVAL", 0.001)
    watch = FpsDropWatch()
    seen = []
    samples = watch._sample

    def stop_after_four():
        seen.append(published())
        driver[:] = [(24, 22)]
        samples()
        CLOCK[0] += fpsdrop.SETTLE_SECONDS
        if len(seen) == 4:
            watch.stop()
    monkeypatch.setattr(watch, "_sample", stop_after_four)
    watch.start()
    watch.join(5)
    assert not watch.is_alive()
    # The start wait, a reading held back, then counted.
    assert seen == ["", "0|0", "0|0", "2|2"]
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
