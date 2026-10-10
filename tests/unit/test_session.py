# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing title's history for the dashboard (web/session.py)."""

import pytest

from web import session as session_module
from web.session import SessionLog


class Clock:
    """Stands in for time.monotonic; starts low, as on a box just booted."""

    def __init__(self):
        self.now = 5.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(session_module.time, "monotonic", fake)
    return fake


def observe(log, clock, seconds=0.0, title="Film", source="/films/film.mkv",
            metrics=None, watched=None, position="00:01:00"):
    clock.now += seconds
    log.observe(title, source, metrics or {}, watched or {}, position)


def test_samples_follow_their_own_interval(clock):
    log = SessionLog()
    for _ in range(5):
        observe(log, clock, 0.2, metrics={"l1": {"max": 1000, "avg": 100}})
    observe(log, clock, 1.0, metrics={"l1": {"max": 2000, "avg": 200}})
    history = log.history()
    assert history["max"] == [1000, 2000]
    assert history["avg"] == [100, 200]
    assert history["t"] == sorted(history["t"])
    assert history["step"] == SessionLog.SAMPLE_INTERVAL


def test_samples_keep_the_last_hour(clock, monkeypatch):
    monkeypatch.setattr(SessionLog, "MAX_SAMPLES", 3)
    log = SessionLog()
    for peak in range(5):
        observe(log, clock, 1.0, metrics={"l1": {"max": peak}})
    assert log.history()["max"] == [2, 3, 4]


def test_a_changed_reading_is_an_event_and_a_switch(clock):
    log = SessionLog()
    observe(log, clock, watched={"mode": "dv"})
    assert log.history()["events"] == []       # the first pass only records
    observe(log, clock, 0.1, watched={"mode": "hdr10"}, position="00:02:00")
    events = log.history()["events"]
    assert events == [{"t": 0.1, "pos": "00:02:00", "kind": "mode",
                       "from": "dv", "to": "hdr10"}]
    assert log.summary() == {"seq": 1, "switches": 1, "warnings": 0}


def test_empty_readings_are_ignored(clock):
    log = SessionLog()
    observe(log, clock, watched={"mode": "dv"})
    observe(log, clock, 0.1, watched={"mode": ""})
    observe(log, clock, 0.1, watched={"mode": "dv"})
    assert log.summary()["seq"] == 0


def test_a_track_change_waits_until_settled(clock):
    log = SessionLog()
    track = {"audio": {"id": "1", "label": "English"}}
    observe(log, clock, watched=track)
    observe(log, clock, SessionLog.TRACK_SETTLE, watched=track)   # the first value settles too
    # Index first, label one tick later: one event, dated at the first change.
    observe(log, clock, 0.1, watched={"audio": {"id": "2", "label": "English"}},
            position="00:05:00")
    observe(log, clock, 0.1, watched={"audio": {"id": "2", "label": "German"}})
    assert log.history()["events"] == []
    observe(log, clock, SessionLog.TRACK_SETTLE, watched={"audio": {"id": "2", "label": "German"}})
    [event] = log.history()["events"]
    assert (event["from"], event["to"], event["pos"]) == ("English", "German", "00:05:00")
    assert event["t"] == pytest.approx(SessionLog.TRACK_SETTLE + 0.1)  # the first change


def test_a_track_flicker_is_not_an_event(clock):
    log = SessionLog()
    observe(log, clock, watched={"audio": {"id": "1", "label": "English"}})
    observe(log, clock, SessionLog.TRACK_SETTLE, watched={"audio": {"id": "1", "label": "English"}})
    observe(log, clock, 0.1, watched={"audio": {"id": "2", "label": "German"}})
    observe(log, clock, 0.1, watched={"audio": {"id": "1", "label": "English"}})
    observe(log, clock, 5.0, watched={"audio": {"id": "1", "label": "English"}})
    assert log.summary()["seq"] == 0


def test_warnings_fire_once_per_crossing(clock):
    log = SessionLog()
    for temperature in (70, 80, 85, 70, 90):
        observe(log, clock, 0.1, metrics={"cpu_temp": temperature})
    observe(log, clock, 0.1, metrics={"cpu": 100.0})
    kinds = [event["kind"] for event in log.history()["events"]]
    assert kinds == ["temperature", "temperature", "cpu"]
    assert log.summary() == {"seq": 3, "switches": 0, "warnings": 3}


def test_frame_rate_changes_are_events_but_not_switches(clock):
    log = SessionLog()
    for fps in ("0", "23.976", "24", "x", "50"):
        observe(log, clock, 0.1, metrics={"fps_in": fps})
    [event] = log.history()["events"]
    assert (event["kind"], event["from"], event["to"]) == ("fps", 24, 50)
    assert log.summary()["switches"] == 0


def test_events_keep_the_newest(clock, monkeypatch):
    monkeypatch.setattr(SessionLog, "MAX_EVENTS", 2)
    log = SessionLog()
    for mode in ("a", "b", "c", "d"):
        observe(log, clock, 0.1, watched={"mode": mode})
    assert [event["to"] for event in log.history()["events"]] == ["c", "d"]
    assert log.summary()["switches"] == 3


def test_a_new_title_starts_a_new_session(clock):
    log = SessionLog()
    observe(log, clock, watched={"mode": "dv"})
    observe(log, clock, 0.1, watched={"mode": "hdr10"})
    observe(log, clock, 0.1, title="Other", source="/films/other.mkv")
    assert log.summary() == {"seq": 0, "switches": 0, "warnings": 0}


def test_a_half_empty_reading_keeps_the_title(clock):
    log = SessionLog()
    observe(log, clock, watched={"mode": "dv"})
    observe(log, clock, 0.1, watched={"mode": "hdr10"})
    observe(log, clock, 0.1, title="Film", source="")       # winding down
    observe(log, clock, 0.1, title="", source="/films/film.mkv")
    assert log.summary()["seq"] == 1


def test_a_finished_title_is_kept_for_the_idle_page(clock):
    log = SessionLog()
    observe(log, clock, metrics={"l1": {"max": 500}}, position="01:30:00")
    observe(log, clock, 1.0, metrics={"l1": {"max": 900}})
    assert log.last() == {}                   # still playing
    log.end()
    clock.now += 30
    log.end()                                 # repeated on every idle pass
    last = log.last()
    assert last["title"] == "Film" and last["peak"] == 900 and last["ago"] == 30
    clock.now += SessionLog.RETAIN_SECONDS
    assert log.last() == {}
    log.end()
    assert log.history()["t"] == []


def test_playing_again_after_the_end_starts_afresh(clock):
    log = SessionLog()
    observe(log, clock, watched={"mode": "dv"})
    observe(log, clock, 0.1, watched={"mode": "hdr10"})
    log.end()
    observe(log, clock, 1.0, watched={"mode": "hdr10"})
    assert log.summary()["seq"] == 0
    assert log.last() == {}


def test_ending_nothing_keeps_nothing(clock):
    log = SessionLog()
    log.end()
    log.end()
    assert log.last() == {}
