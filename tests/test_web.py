# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import threading
import time
import types

import pytest

from web import server, snapshot


# --- Delta frames --------------------------------------------------------------

def _groups(*values):
    return [{"id": "video", "title": "Video", "rows": [
        {"id": f"r{index}", "label": f"Row {index}", "value": value}
        for index, value in enumerate(values)]}]


def test_delta_sends_only_what_moved():
    previous = {"seq": 1, "title": "A", "clock": "1", "gone": True,
                "groups": _groups("x", "y")}
    current  = {"seq": 2, "title": "A", "clock": "2",
                "groups": _groups("x", "z")}
    assert server._snapshot_delta(previous, current) == {
        "seq": 2,
        "set": {"clock": "2"},
        "del": ["gone"],
        "groups": {"rows": [["r1", "z", None]]},
    }


def test_delta_sends_the_whole_list_when_its_shape_changes():
    previous = {"seq": 1, "groups": _groups("x")}
    current  = {"seq": 2, "groups": _groups("x", "y")}
    assert server._snapshot_delta(previous, current)["groups"] == current["groups"]


def test_metadata_delta_by_index_and_cells():
    previous = [{"kind": "row", "name": "L1", "value": "1"},
                {"kind": "trim", "name": "L2", "cells": [1, 2]}]
    current  = [{"kind": "row", "name": "L1", "value": "1"},
                {"kind": "trim", "name": "L2", "cells": [1, 3]}]
    assert server._metadata_delta(previous, current) == [[1, [1, 3]]]
    current.append({"kind": "row", "name": "L5", "value": "0"})
    assert server._metadata_delta(previous, current) is None


# --- Artwork -------------------------------------------------------------------

@pytest.mark.parametrize("path, logged", [
    ("smb://user:secret@nas/films/poster.jpg", "smb://***@nas/films/poster.jpg"),
    ("davs://me@cloud/a.png", "davs://***@cloud/a.png"),
    ("nfs://nas/films/poster.jpg", "nfs://nas/films/poster.jpg"),
    ("/storage/films/poster.jpg", "/storage/films/poster.jpg"),
])
def test_credentials_are_kept_out_of_the_log(path, logged):
    assert server._redacted(path) == logged


def test_shelf_art_logs_the_original_at_debug_without_credentials(kodi,
                                                                  monkeypatch):
    original = "smb://user:secret@nas/films/poster.jpg"
    monkeypatch.setattr(server, "_read_art",
                        lambda source: None if source.startswith("image://")
                        else b"\xff\xd8\xff rest")
    found = server._Server._shelf_art(None, original)
    assert found == (b"\xff\xd8\xff rest", "image/jpeg")
    [(line, level)] = kodi.logged
    assert "secret" not in line and "smb://***@nas" in line
    assert level == server.xbmc.LOGDEBUG


def test_image_type_reads_the_bytes():
    assert server._image_type(b"\x89PNG\r\n\x1a\n...", "x") == "image/png"
    assert server._image_type(b"GIF89a...", "x") == "image/gif"
    assert server._image_type(b"RIFF\0\0\0\0WEBPVP8", "x") == "image/webp"
    assert server._image_type(b"????", "image/jpeg") == "image/jpeg"


def test_art_sources_try_kodis_cache_first():
    wrapped = "image://smb%3a%2f%2fnas%2fposter.jpg/"
    assert server._art_sources(wrapped) == (wrapped, "smb://nas/poster.jpg")
    assert server._art_sources("/storage/p.jpg") == (
        "image://%2Fstorage%2Fp.jpg/", "/storage/p.jpg")


# --- The producer's failure line ------------------------------------------------

def test_a_failure_is_logged_again_after_a_recovery(kodi):
    producer = types.SimpleNamespace(_failed=False)
    for _ in range(3):
        server._Producer._log_failure(producer, RuntimeError("boom"))
    server._Producer._log_recovery(producer)
    server._Producer._log_recovery(producer)
    server._Producer._log_failure(producer, RuntimeError("again"))
    lines = [line for line, _ in kodi.logged]
    assert len(lines) == 3
    assert "boom" in lines[0] and "recovered" in lines[1] and "again" in lines[2]


# --- Shutdown ------------------------------------------------------------------

class _Stuck:
    """A thread that never finishes: every join waits out its timeout."""

    def __init__(self):
        self.waited = []

    def join(self, timeout=None):
        self.waited.append(timeout)
        time.sleep(timeout)

    def is_alive(self):
        return True

    def wake(self):
        pass


class _StuckServer:
    def shutdown(self):
        pass

    def server_close(self):
        pass

    def join_workers(self, timeout):
        time.sleep(timeout)
        return 1


def test_stop_waits_one_deadline_for_all_threads(monkeypatch):
    monkeypatch.setattr(server, "_JOIN_TIMEOUT", 0.3)
    dashboard = server.WebDashboard()
    dashboard._server   = _StuckServer()
    dashboard._thread   = _Stuck()
    dashboard._producer = _Stuck()
    dashboard._stop     = threading.Event()

    started = time.monotonic()
    dashboard.stop(final=True)
    elapsed = time.monotonic() - started

    # Three waits of their own would have taken 0.9s.
    assert elapsed < 0.55
    assert dashboard._stop is None and not dashboard.running


# --- Commands from the page -----------------------------------------------------

@pytest.fixture
def rpc(monkeypatch):
    calls = []

    def answer(method, params=None):
        calls.append((method, params))
        return {"result": "OK"}

    monkeypatch.setattr(snapshot, "_rpc", answer)
    monkeypatch.setattr(snapshot, "_video_player_id", lambda: 1)
    monkeypatch.setattr(snapshot, "_broadcast_times", lambda: {})
    return calls


@pytest.mark.parametrize("action, value", [
    ("format_disk", None),            # not a command at all
    ("seek", float("nan")),
    ("seek", 99999),                  # past the seek limit
    ("volume", 101),
    ("audio", "first"),
    ("subtitle", -2),
])
def test_bad_commands_never_reach_kodi(rpc, action, value):
    assert not snapshot.apply_command(action, value)
    assert rpc == []


def test_commands_become_the_matching_rpc(rpc):
    assert snapshot.apply_command("seek", "-30")
    assert snapshot.apply_command("subtitle", -1)
    assert snapshot.apply_command("volume_up")
    assert rpc == [
        ("Player.Seek", {"playerid": 1, "value": {"seconds": -30}}),
        ("Player.SetSubtitle", {"playerid": 1, "subtitle": "off"}),
        ("Input.ExecuteAction", {"action": "volumeup"}),
    ]


@pytest.fixture
def switches(monkeypatch):
    import ui.mode_select

    done = []
    finished = threading.Event()

    def set_mode(name):
        done.append(name)
        finished.set()

    monkeypatch.setattr(ui.mode_select, "set_mode", set_mode)
    return done, finished


def test_a_mode_switch_runs_in_the_service(kodi, switches):
    done, finished = switches
    assert snapshot.apply_mode("dv")
    assert finished.wait(2)
    assert done == ["dv"]
    assert not any(command.startswith("RunScript") for command in kodi.builtins)


def test_unknown_modes_are_refused(switches):
    done, finished = switches
    assert not snapshot.apply_mode("hdr10_to_8k")
    assert not finished.wait(0.1)
    assert done == []


def test_no_switch_starts_once_kodi_is_stopping(kodi, switches):
    done, finished = switches
    kodi.abort = True
    assert snapshot.apply_mode("dv")
    assert not finished.wait(0.2)
    assert done == []
