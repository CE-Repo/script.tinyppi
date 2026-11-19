# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The thread that counts the dropped frames during playback (info/fpsdrop.py)."""

import pytest

import xbmc
import xbmcgui
from core.utils import PROP_FPS_DROP, fps_drop_reading
from info import fpsdrop
from info.fpsdrop import FpsDropWatch

# The watch's clock.
CLOCK = [100.0]


@pytest.fixture
def driver(monkeypatch):
    """An Amlogic box playing a film: hands out the readings queued for it."""
    readings: list[tuple[int, int] | None] = []
    monkeypatch.setattr(fpsdrop, "read_fps_sysfs", lambda: readings.pop(0))
    CLOCK[0] = 100.0
    monkeypatch.setattr(fpsdrop.time, "monotonic", lambda: CLOCK[0])
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO["Player.FilenameAndPath"] = "/films/a.mkv"
    return readings


def sample(watch, readings, *queued):
    readings.extend(queued)
    for _reading in queued:
        watch._sample()


def published():
    return xbmcgui.Window(10000).getProperty(PROP_FPS_DROP)


def test_drops_are_published_as_rate_and_total(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 24), (24, 23), (24, 25))
    assert published() == "0|0"                              # out of step, no drop
    sample(watch, driver, (24, 21))
    assert published() == "1|3" and fps_drop_reading() == (1, 3)


def test_another_title_starts_over(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 20))
    assert published() == "4|4"
    xbmc.INFO["Player.FilenameAndPath"] = "/films/b.mkv"
    sample(watch, driver, (24, 24))
    assert published() == "0|0"


def test_a_paused_player_keeps_the_count(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 20))
    xbmc.CONDITIONS["Player.Paused"] = True
    watch._sample()                                          # the driver is not read
    assert published() == "4|4" and driver == []
    xbmc.CONDITIONS["Player.Paused"] = False
    watch._sample()                                          # settling after the pause
    assert published() == "0|4"


def test_nothing_is_counted_while_the_picture_settles_after_a_seek(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 20))
    assert published() == "4|4"
    watch.settle()                                           # Player.OnSeek
    for _second in range(3):
        watch._sample()                                      # the driver is not read
        assert published() == "0|4"
        CLOCK[0] += fpsdrop.SAMPLE_INTERVAL
    assert driver == []
    sample(watch, driver, (24, 24))                          # settled: counted again
    assert published() == "0|4"                              # the window was cleared
    sample(watch, driver, (24, 21))
    assert published() == "2|7"


def test_a_resume_after_a_pause_settles_too(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 20))
    xbmc.CONDITIONS["Player.Paused"] = True
    watch._sample()
    CLOCK[0] += 30                                           # a long pause
    xbmc.CONDITIONS["Player.Paused"] = False                 # no Player.OnResume seen
    for _second in range(3):
        watch._sample()                                      # the driver is not read
        assert published() == "0|4"
        CLOCK[0] += fpsdrop.SAMPLE_INTERVAL
    assert driver == []
    sample(watch, driver, (24, 24))
    assert published() == "0|4"


def test_a_pause_does_not_outlast_the_title(driver):
    watch = FpsDropWatch()
    xbmc.CONDITIONS["Player.Paused"] = True
    watch._sample()
    xbmc.CONDITIONS["Player.HasVideo"] = False               # stopped while paused
    watch._sample()
    xbmc.CONDITIONS.update({"Player.HasVideo": True, "Player.Paused": False})
    sample(watch, driver, (24, 20))                          # the next title counts at once
    assert published() == "4|4"


def test_a_seek_under_way_starts_the_pause_too(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 24))
    xbmc.CONDITIONS["Player.Seeking"] = True
    watch._sample()
    xbmc.CONDITIONS["Player.Seeking"] = False
    CLOCK[0] += fpsdrop.SETTLE_SECONDS - 0.1
    watch._sample()                                          # still settling
    assert published() == "0|0" and driver == []
    CLOCK[0] += 0.1
    sample(watch, driver, (24, 20))
    assert published() == "4|4"


def test_without_a_video_or_the_counters_nothing_is_published(driver):
    watch = FpsDropWatch()
    sample(watch, driver, (24, 20))
    xbmc.CONDITIONS["Player.HasVideo"] = False
    watch._sample()
    assert published() == "" and fps_drop_reading() is None
    xbmc.CONDITIONS["Player.HasVideo"] = True
    sample(watch, driver, None)                              # not an Amlogic box
    assert published() == ""
    sample(watch, driver, (24, 24))
    assert published() == "0|0"                              # counted afresh


def test_the_property_is_written_only_when_it_changes(driver, monkeypatch):
    watch = FpsDropWatch()
    writes = []
    real = xbmcgui.Window.setProperty
    monkeypatch.setattr(xbmcgui.Window, "setProperty",
                        lambda self, key, value: (writes.append(value), real(self, key, value)))
    sample(watch, driver, (24, 24), (24, 24), (24, 24))
    assert writes == ["0|0"]


def test_the_thread_clears_a_stale_count_and_stops(driver, monkeypatch):
    xbmcgui.Window(10000).setProperty(PROP_FPS_DROP, "3|99")   # an earlier session
    monkeypatch.setattr(fpsdrop, "SAMPLE_INTERVAL", 0.001)
    watch = FpsDropWatch()
    seen = []
    samples = watch._sample

    def stop_after_two():
        seen.append(published())
        driver.append((24, 22))
        samples()
        if len(seen) == 2:
            watch.stop()
    monkeypatch.setattr(watch, "_sample", stop_after_two)
    watch.start()
    watch.join(5)
    assert not watch.is_alive()
    assert seen == ["", "2|2"]
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
