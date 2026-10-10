# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Handing out snapshots without a running producer thread (web/producer.py)."""

import threading
import time

import pytest

import xbmc
import xbmcaddon
from web import producer as producer_module
from web.producer import Producer


class Builder:
    """Stands in for SnapshotBuilder: full passes return what the test queues."""

    def __init__(self, *snapshots):
        self.snapshots = list(snapshots)
        self.calls = []

    def build(self, detail=True, **options):
        self.calls.append("full" if detail else "idle")
        self.options = options
        return self.snapshots.pop(0) if detail else None


@pytest.fixture
def idle(monkeypatch):
    """A producer whose thread is never started; passes run in the test's thread."""
    monkeypatch.setattr(producer_module.library, "revision", lambda: 3)
    monkeypatch.setattr(producer_module, "PRODUCE_INTERVAL", 0)
    monkeypatch.setattr(producer_module, "_IDLE_INTERVAL", 0)
    monkeypatch.setattr(producer_module, "_FRESH_TIMEOUT", 0.01)
    producer = Producer(threading.Event())
    producer._builder = Builder()
    return producer


def run_passes(producer, monkeypatch, count):
    """Run the producer loop for *count* passes, then let Kodi abort it."""
    checks = iter([False] * count)
    monkeypatch.setattr(xbmc.Monitor, "abortRequested", lambda self: next(checks, True))
    producer.run()


def test_a_request_during_a_stream_gets_the_held_snapshot(idle, monkeypatch):
    monkeypatch.setattr(producer_module, "_FRESH_TIMEOUT", 5)
    held = idle.snapshot
    idle.watch()
    started = time.monotonic()
    assert idle.fresh() is held
    assert time.monotonic() - started < 1                    # no waiting for a pass
    idle.unwatch()
    run_passes(idle, monkeypatch, 1)
    assert idle._builder.calls == ["idle"]                   # and no extra pass asked for


def test_a_request_without_a_new_snapshot_falls_back_to_the_last(idle):
    started = time.monotonic()
    shot = idle.fresh()
    assert shot == {"seq": 0, "playing": False, "groups": [], "metrics": {}, "library": 0}
    assert time.monotonic() - started < 0.5


def test_a_request_makes_the_next_pass_a_full_one(idle, monkeypatch):
    idle._builder = Builder({"seq": 1, "playing": True})
    idle.fresh()                                              # times out: nothing runs yet
    run_passes(idle, monkeypatch, 2)
    assert idle._builder.calls == ["full", "idle"]            # the request is answered once
    assert idle.snapshot == {"seq": 1, "playing": True, "library": 3}


def test_waiting_ends_on_the_timeout(idle):
    started = time.monotonic()
    assert idle.wait_for(0, 0.01) is None
    assert time.monotonic() - started >= 0.01


def test_a_published_snapshot_wakes_a_waiting_stream(idle):
    idle._builder = Builder({"seq": 5, "playing": True})
    seen = idle.watch()
    got = []
    waiter = threading.Thread(target=lambda: got.append(idle.wait_for(seen, 2)))
    waiter.start()
    idle._publish()
    waiter.join(2)
    assert not waiter.is_alive()
    assert got == [{"seq": 5, "playing": True, "library": 3}]
    assert idle.snapshot["seq"] == 5


def test_a_pass_without_a_snapshot_keeps_the_last_and_the_request(idle, monkeypatch):
    xbmcaddon.SETTINGS["web_allow_control"] = "true"
    idle._builder = Builder(None, {"seq": 2, "playing": True})
    idle.fresh()
    run_passes(idle, monkeypatch, 1)
    assert idle.snapshot["seq"] == 0
    assert idle._builder.options["control"] is True
    run_passes(idle, monkeypatch, 1)                          # still pending: built again
    assert idle._builder.calls == ["full", "full"]
    assert idle.snapshot["seq"] == 2


def test_the_loop_ends_when_kodi_shuts_down(idle, monkeypatch):
    run_passes(idle, monkeypatch, 0)
    assert idle._builder.calls == []
