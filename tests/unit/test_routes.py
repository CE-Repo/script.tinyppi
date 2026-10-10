# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What the dashboard's write and library routes accept (web/routes.py)."""

import json
import socket
import urllib.error
import urllib.request

import pytest

from dashboard_server import DIRECT, TOKEN, request
from web import library, routes


@pytest.fixture
def calls(monkeypatch):
    """Record what the routes hand on; the library and player are faked."""
    seen = []

    def recorder(name, result=True):
        def record(*args, **kwargs):
            seen.append((name, args))
            return result
        return record

    monkeypatch.setattr(routes, "apply_command", lambda action, value=None: (
        seen.append(("command", (action, value))) or action == "pause"))
    monkeypatch.setattr(routes, "apply_mode", lambda mode: (
        seen.append(("mode", (mode,))) or mode == "dv"))
    for name in ("play", "play_episode", "set_watched", "clear_resume"):
        monkeypatch.setattr(library, name, recorder(name))
    return seen


def post(srv, path, body, token=TOKEN):
    status, _headers, raw = request(srv, path, "POST", body, token=token)
    return status, json.loads(raw or b"{}")


def raw_post(srv, path, body, length=None):
    """Send a POST with exactly these bytes (and Content-Length)."""
    port = srv.server_address[1]
    head = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nX-TinyPPI-Token: {TOKEN}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body) if length is None else length}\r\nConnection: close\r\n\r\n")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(head.encode() + body)
        answer = b""
        while chunk := sock.recv(65536):
            answer += chunk
    return int(answer.split(b" ", 2)[1])


# --- Bodies -------------------------------------------------------------------

@pytest.mark.parametrize(("body", "length"), [
    (b"{not json", None),
    (b"[1, 2]", None),
    (b'"text"', None),
    (b"{}", "-1"),
    (b"{}", "lots"),
    (b"x" * 5000, None),            # over the 4 KiB limit
])
def test_bad_bodies_are_refused(dashboard, calls, body, length):
    assert raw_post(dashboard, "/api/command", body, length) == 400
    assert calls == []


def test_an_empty_body_is_an_empty_object(dashboard, calls):
    assert raw_post(dashboard, "/api/command", b"") == 400      # no action named
    assert calls == [("command", ("", None))]


def test_unknown_write_routes(dashboard, calls):
    assert post(dashboard, "/api/shutdown", {})[0] == 404
    assert post(dashboard, "/api/state", {})[0] == 404
    assert calls == []


def test_control_off_refuses_every_write(dashboard, calls):
    dashboard.allow_control = False
    for path in ("/api/command", "/api/mode", "/api/play", "/api/watched", "/api/resume"):
        assert post(dashboard, path, {"action": "pause", "movieid": 1})[0] == 403
    assert calls == []


def test_writing_never_happens_without_the_token(dashboard, calls):
    for path in ("/api/command", "/api/play", "/api/watched"):
        assert post(dashboard, path, {"action": "pause", "movieid": 1}, token=None)[0] == 401
    assert calls == []


# --- Commands and modes -------------------------------------------------------

def test_commands(dashboard, calls):
    assert post(dashboard, "/api/command", {"action": " pause ", "value": 5}) == (
        200, {"ok": True, "action": "pause"})
    assert post(dashboard, "/api/command", {"action": "reboot"})[0] == 400
    assert post(dashboard, "/api/command", {"action": ["pause"]})[0] == 400
    assert calls == [("command", ("pause", 5)), ("command", ("reboot", None)),
                     ("command", ("['pause']", None))]


def test_modes(dashboard, calls):
    assert post(dashboard, "/api/mode", {"mode": "dv"}) == (200, {"ok": True, "mode": "dv"})
    assert post(dashboard, "/api/mode", {"mode": "../../etc"})[0] == 400
    assert post(dashboard, "/api/mode", {})[0] == 400


# --- Library writes -----------------------------------------------------------

def test_play_a_film_or_an_episode(dashboard, calls):
    assert post(dashboard, "/api/play", {"movieid": 4})[0] == 200
    assert post(dashboard, "/api/play", {"movieid": 4, "resume": False})[0] == 200
    assert post(dashboard, "/api/play", {"episodeid": 9, "resume": "no"})[0] == 200
    assert calls == [("play", (4, True)), ("play", (4, False)), ("play_episode", (9, True))]


def test_each_shelf_needs_its_setting(dashboard, calls):
    dashboard.offer_library = False
    assert post(dashboard, "/api/play", {"movieid": 4})[0] == 403
    assert post(dashboard, "/api/watched", {"movieid": 4, "watched": True})[0] == 403
    assert post(dashboard, "/api/play", {"episodeid": 9})[0] == 200
    dashboard.offer_series = False
    assert post(dashboard, "/api/play", {"episodeid": 9})[0] == 403
    assert post(dashboard, "/api/watched", {"tvshowid": 2, "watched": False})[0] == 403
    assert post(dashboard, "/api/resume", {"episodeid": 9})[0] == 403
    assert calls == [("play_episode", (9, True))]


@pytest.mark.parametrize("watched", [None, 1, "true", "yes"])
def test_watched_must_be_a_boolean(dashboard, calls, watched):
    assert post(dashboard, "/api/watched", {"movieid": 4, "watched": watched})[0] == 400
    assert calls == []


def test_marking(dashboard, calls):
    assert post(dashboard, "/api/watched", {"tvshowid": 2, "watched": False}) == (
        200, {"ok": True, "tvshowid": 2, "watched": False})
    assert post(dashboard, "/api/watched", {"watched": True})[0] == 400       # no title
    assert post(dashboard, "/api/resume", {"movieid": 4}) == (200, {"ok": True, "movieid": 4})
    assert post(dashboard, "/api/resume", {"tvshowid": 2})[0] == 400        # shows have none
    assert calls == [("set_watched", ("tvshow", 2, False)), ("clear_resume", ("movie", 4))]


def test_a_refused_library_write_is_an_error(dashboard, monkeypatch):
    for name in ("play", "set_watched", "clear_resume"):
        monkeypatch.setattr(library, name, lambda *_args: False)
    assert post(dashboard, "/api/play", {"movieid": True})[0] == 400
    assert post(dashboard, "/api/watched", {"movieid": 4, "watched": True})[0] == 400
    assert post(dashboard, "/api/resume", {"movieid": 4})[0] == 400


# --- Library reads ------------------------------------------------------------

def test_a_broken_library_read_is_503(dashboard, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("database locked")
    for name in ("movies", "shows", "episodes", "continuing"):
        monkeypatch.setattr(library, name, broken)
    for path in ("/api/library", "/api/series", "/api/episodes?tvshowid=2", "/api/continue"):
        assert request(dashboard, path)[0] == 503


def test_listings_carry_their_tag(dashboard, monkeypatch):
    monkeypatch.setattr(library, "movies", lambda: {"tag": "abc", "movies": []})
    status, headers, _ = request(dashboard, "/api/library")
    assert status == 200 and headers["ETag"] == '"abc"'
    port = dashboard.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/library",
                                 headers={"If-None-Match": '"abc"'})
    try:
        DIRECT.open(req, timeout=5)
        code = 200
    except urllib.error.HTTPError as err:
        code = err.code
    assert code == 304


def test_an_unknown_series_is_404(dashboard, monkeypatch):
    monkeypatch.setattr(library, "episodes", lambda show: None)
    assert request(dashboard, "/api/episodes?tvshowid=999")[0] == 404


def test_library_reads_need_control(dashboard):
    dashboard.allow_control = False
    for path in ("/api/library", "/api/series", "/api/episodes?tvshowid=1", "/api/continue"):
        assert request(dashboard, path)[0] == 403


@pytest.mark.parametrize("query", ["kind=x", "kind=", "kind=poster/../../x", ""])
def test_unknown_artwork_kinds(dashboard, query):
    assert request(dashboard, "/api/art?" + query)[0] == 404


def test_art_ids_from_the_query_are_checked(dashboard):
    for query in ("movieid=abc", "movieid=-1", "tvshowid=1e9", "episodeid=%00"):
        assert request(dashboard, "/api/art?kind=poster&" + query)[0] == 404
