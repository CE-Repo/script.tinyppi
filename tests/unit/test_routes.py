# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's request handler, routes and event stream (web/routes.py)."""

import gzip
import io
import json
import socket
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

import xbmc
from dashboard_server import DIRECT, TOKEN, IdleProducer, request, serve
from web import artwork, library, routes


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
    assert calls == [("mode", ("dv",)), ("mode", ("../../etc",)), ("mode", ("",))]


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


def test_a_failed_episode_start_is_an_error(dashboard, monkeypatch):
    monkeypatch.setattr(library, "play_episode", lambda *_args: False)
    assert post(dashboard, "/api/play", {"episodeid": 9}) == (400, {"error": "playback failed"})


@pytest.mark.parametrize(("path", "reader", "expected_args"), [
    ("/api/series", "shows", ()),
    ("/api/episodes?tvshowid=7", "episodes", ("7",)),
    ("/api/continue", "continuing", ()),
])
def test_library_listings_are_sent_with_their_tag(dashboard, monkeypatch, path, reader,
                                                  expected_args):
    asked = []

    def listing(*args, **kwargs):
        asked.append((args, kwargs))
        return {"tag": "t1", "items": [1, 2]}

    monkeypatch.setattr(library, reader, listing)
    status, headers, raw = request(dashboard, path)
    assert status == 200 and headers["ETag"] == '"t1"'
    assert json.loads(raw) == {"tag": "t1", "items": [1, 2]}
    assert asked[0][0] == expected_args


def test_continue_lists_only_the_enabled_shelves(dashboard, monkeypatch):
    asked = []
    monkeypatch.setattr(library, "continuing",
                        lambda **kwargs: asked.append(kwargs) or {"tag": "c", "items": []})
    dashboard.offer_library = False
    assert request(dashboard, "/api/continue")[0] == 200
    dashboard.offer_series = False
    assert request(dashboard, "/api/continue")[0] == 403
    assert asked == [{"films": False, "series": True}]


# --- Plain reads ----------------------------------------------------------------

def get(srv, path, headers=None):
    """GET *path* with extra headers; returns status, headers and raw body."""
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with DIRECT.open(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


class HistoryProducer(IdleProducer):
    def __init__(self, history):
        self._history = history

    def history(self):
        return self._history


def test_hello_offers_the_shelves_only_with_control(dashboard):
    hello = json.loads(request(dashboard, "/api/hello")[2])
    assert (hello["control"], hello["library"], hello["series"]) == (True, True, True)
    assert hello["name"] == "TinyPPI" and hello["interval_ms"] > 0 and hello["strings"]
    dashboard.allow_control = False
    hello = json.loads(request(dashboard, "/api/hello")[2])
    assert (hello["control"], hello["library"], hello["series"]) == (False, False, False)


def test_state_tells_whether_control_is_on_and_streams_are_full(dashboard):
    while dashboard.claim_stream():
        pass
    dashboard.allow_control = False
    status, _, raw = request(dashboard, "/api/state")
    assert status == 200
    assert json.loads(raw) == {"seq": 1, "playing": False, "groups": [], "metrics": {},
                               "library": 0, "control": False, "streams_full": True}


def test_the_token_is_masked_in_the_access_log(dashboard):
    assert request(dashboard, f"/api/state?token={TOKEN}&x=1")[0] == 200
    lines = [line for _level, line in xbmc.LOG if "GET /api/state" in line]
    assert lines and all("token=***&x=1" in line and TOKEN not in line for line in lines)


@pytest.mark.parametrize(("action", "level"), [
    ("pause", xbmc.LOGINFO), ("seek", xbmc.LOGDEBUG), ("volume", xbmc.LOGDEBUG),
])
def test_bursty_commands_are_logged_at_debug(dashboard, monkeypatch, action, level):
    monkeypatch.setattr(routes, "apply_command", lambda action, value=None: True)
    assert post(dashboard, "/api/command", {"action": action})[0] == 200
    assert (level, f"TinyPPI [web]: '{action}' requested from 127.0.0.1") in xbmc.LOG


def test_unknown_read_routes_are_404(dashboard):
    status, _, raw = request(dashboard, "/api/nothing")
    assert status == 404 and json.loads(raw) == {"error": "no such route"}


def test_reading_needs_the_token_when_the_setting_says_so(dashboard):
    dashboard.auth_read = True
    assert request(dashboard, "/api/state")[0] == 401
    assert request(dashboard, "/api/state", token=TOKEN)[0] == 200
    assert json.loads(request(dashboard, "/api/hello")[2])["auth_read"] is True


def test_a_token_in_the_address_does_not_count(dashboard):
    dashboard.auth_read = True
    assert request(dashboard, f"/api/state?token={TOKEN}")[0] == 401


def session_cookie(dashboard, token=TOKEN):
    status, headers, raw = request(dashboard, "/api/session", "POST", {}, token=token)
    return status, headers.get("Set-Cookie", ""), raw


def test_the_token_buys_a_read_session_cookie(dashboard):
    status, cookie, raw = session_cookie(dashboard)
    assert status == 200 and json.loads(raw) == {"ok": True}
    value, *attributes = [part.strip() for part in cookie.split(";")]
    assert value == f"tinyppi_session={dashboard.session}"
    assert attributes == ["Path=/api/", "HttpOnly", "SameSite=Strict"]


@pytest.mark.parametrize("token", [None, "WRONG"])
def test_no_session_without_the_token(dashboard, token):
    status, cookie, _raw = session_cookie(dashboard, token)
    assert status == 401 and cookie == ""


def test_a_session_needs_no_control(dashboard):
    dashboard.allow_control = False
    assert session_cookie(dashboard)[0] == 200


def test_the_session_reads_where_reading_needs_the_token(dashboard):
    dashboard.auth_read = True
    held = f"kodi=1; other=\"x; tinyppi_session={dashboard.session}"
    # Other services' cookies on the same host, one of them malformed.
    assert request(dashboard, "/api/state", cookie=held)[0] == 200


def test_a_session_reads_even_from_a_locked_out_address(dashboard, monkeypatch):
    # It cannot be guessed, so it is no guess to lock out.
    dashboard.auth_read = True
    monkeypatch.setattr(dashboard.guesses, "locked_for", lambda address: 2.5)
    assert request(dashboard, "/api/state", cookie=f"tinyppi_session={dashboard.session}")[0] == 200
    assert request(dashboard, "/api/state", token=TOKEN)[0] == 429


@pytest.mark.parametrize("cookie", [
    "tinyppi_session=forged", "tinyppi_session=", "tinyppi_session", "other=1",
    "tinyppi_session=\u00e9\u00e9",
])
def test_a_foreign_session_reads_nothing_and_is_no_guess(dashboard, cookie):
    dashboard.auth_read = True
    assert request(dashboard, "/api/state", cookie=cookie)[0] == 401
    assert dashboard.guesses._wrong == {}


def test_a_session_does_not_write(dashboard, calls):
    status, _headers, _raw = request(dashboard, "/api/command", "POST", {"action": "pause"},
                                     cookie=f"tinyppi_session={dashboard.session}")
    assert status == 401 and calls == []


def test_a_locked_out_address_is_told_when_to_retry(dashboard, monkeypatch, calls):
    monkeypatch.setattr(dashboard.guesses, "locked_for", lambda address: 2.5)
    status, headers, raw = request(dashboard, "/api/command", "POST", {"action": "pause"},
                                   token=TOKEN)
    assert status == 429 and headers["Retry-After"] == "3"
    assert json.loads(raw) == {"error": "too many wrong tokens", "retry_ms": 2500}
    assert calls == []


def test_history_is_gzipped_when_large_and_accepted():
    history = {"t": list(range(400)), "events": []}
    srv, close = serve(HistoryProducer(history))
    try:
        status, headers, raw = get(srv, "/api/history", {"Accept-Encoding": "gzip"})
        assert status == 200 and headers["Content-Encoding"] == "gzip"
        assert headers["Vary"] == "Accept-Encoding"
        assert json.loads(gzip.decompress(raw)) == history
        status, headers, raw = get(srv, "/api/history")
        assert "Content-Encoding" not in headers and json.loads(raw) == history
    finally:
        close()


def test_small_json_is_never_gzipped(dashboard):
    status, headers, raw = get(dashboard, "/api/history", {"Accept-Encoding": "gzip"})
    assert status == 200 and "Content-Encoding" not in headers
    assert json.loads(raw) == {"t": [], "events": []}


# --- Artwork --------------------------------------------------------------------

@pytest.fixture
def art(dashboard, monkeypatch):
    """Record which artwork source each request asks; every one has a JPEG."""
    asked = []

    def source(name):
        def look_up(*args):
            asked.append((name, args))
            return (b"\xff\xd8\xff-" + name.encode(), "image/jpeg")
        return look_up

    for name in ("artwork", "library_artwork", "series_artwork", "episode_artwork"):
        monkeypatch.setattr(dashboard, name, source(name))
    return asked


@pytest.mark.parametrize(("query", "source", "args"), [
    ("kind=fanart", "artwork", ("fanart",)),
    ("kind=poster&movieid=4", "library_artwork", ("4", "poster")),
    ("kind=poster&tvshowid=2", "series_artwork", ("2", "poster")),
    ("kind=thumb&episodeid=9", "episode_artwork", ("9", "thumb")),
])
def test_artwork_comes_from_the_named_item(dashboard, art, query, source, args):
    status, headers, body = request(dashboard, "/api/art?" + query)
    assert status == 200 and body == b"\xff\xd8\xff-" + source.encode()
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["Cache-Control"] == "no-store" and "ETag" not in headers
    assert art == [(source, args)]


def test_tagged_artwork_is_immutable_and_revalidates_empty(dashboard, art):
    status, headers, _ = get(dashboard, "/api/art?kind=poster&v=abc")
    assert status == 200 and headers["ETag"] == '"abc"'
    assert headers["Cache-Control"] == artwork.CACHE
    status, headers, body = get(dashboard, "/api/art?kind=poster&v=abc",
                                {"If-None-Match": 'W/"old", W/"abc"'})
    assert status == 304 and body == b"" and headers["ETag"] == '"abc"'
    assert art == [("artwork", ("poster",))]          # the 304 read nothing


@pytest.mark.parametrize("tag", [
    "x%0d%0aSet-Cookie:%20evil=1",                    # header injection
    'ab"cd',
    "ABCDEF12",                                       # tags are lowercase hex
    "a" * 17,                                         # longer than any tag
])
def test_foreign_artwork_tags_are_ignored(dashboard, art, tag):
    status, headers, _ = get(dashboard, "/api/art?kind=poster&v=" + tag)
    assert status == 200 and "ETag" not in headers and "Set-Cookie" not in headers
    assert headers["Cache-Control"] == "no-store"
    assert art == [("artwork", ("poster",))]


def test_missing_artwork_is_404(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "artwork", lambda kind: None)
    status, _, raw = request(dashboard, "/api/art?kind=poster")
    assert status == 404 and json.loads(raw) == {"error": "no artwork"}


# --- Static files ---------------------------------------------------------------

@pytest.fixture
def files(dashboard, tmp_path):
    """Serve a page, a big style sheet and a missing file from tmp_path."""
    page = tmp_path / "index.html"
    page.write_text("<html>hi</html>")
    sheet = tmp_path / "big.css"
    sheet.write_text("body { color: red; }\n" * 100)
    dashboard.static_routes = {
        "/": (str(page), "text/html; charset=utf-8"),
        "/big.css": (str(sheet), "text/css; charset=utf-8"),
        "/gone.css": (str(tmp_path / "gone.css"), "text/css; charset=utf-8"),
    }
    return sheet


def test_the_page_carries_its_content_policy(dashboard, files):
    status, headers, body = get(dashboard, "/", {"Accept-Encoding": "gzip"})
    assert status == 200 and body == b"<html>hi</html>"   # too small to pack
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "Content-Encoding" not in headers


def test_static_files_are_packed_for_gzip_clients(dashboard, files):
    status, headers, body = get(dashboard, "/big.css", {"Accept-Encoding": "gzip, br"})
    assert status == 200 and headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(body) == files.read_bytes()
    assert "Content-Security-Policy" not in headers
    assert headers["Cache-Control"] == "no-cache" and headers["Vary"] == "Accept-Encoding"
    status, headers, body = get(dashboard, "/big.css")
    assert status == 200 and body == files.read_bytes() and "Content-Encoding" not in headers


def test_an_unchanged_static_file_is_304(dashboard, files):
    etag = get(dashboard, "/big.css")[1]["ETag"]
    status, headers, body = get(dashboard, "/big.css", {"If-None-Match": etag})
    assert status == 304 and body == b"" and headers["ETag"] == etag


def test_a_routed_file_that_is_gone_is_404(dashboard, files):
    status, _, raw = get(dashboard, "/gone.css")
    assert status == 404 and json.loads(raw) == {"error": "missing file"}


# --- Event stream ---------------------------------------------------------------

class ScriptedProducer(IdleProducer):
    """Hands out the scripted snapshots, then stops the server.

    A step is a snapshot or None (the wait timed out); a callable step runs
    first (e.g. to move the clock) and returns the step.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.stop = None
        self.waits = []
        self.watching = 0

    def watch(self):
        self.watching += 1
        return 0

    def unwatch(self):
        self.watching -= 1

    def wait_for(self, seen, timeout):
        self.waits.append((seen, timeout))
        if not self.steps:
            self.stop.set()
            return None
        step = self.steps.pop(0)
        return step() if callable(step) else step


def frames(raw):
    """Split an event stream into (event, data) pairs and comment lines."""
    parsed = []
    for block in raw.decode().split("\n\n"):
        if block.startswith(":"):
            parsed.append(block)
        elif block:
            event, data = block.split("\n")
            parsed.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return parsed


def test_the_stream_sends_a_state_then_deltas_then_bye():
    first = {"seq": 1, "playing": True, "title": "Film"}
    second = {"seq": 2, "playing": True, "title": "Film", "time": "00:01"}
    producer = ScriptedProducer([first, second])
    srv, close = serve(producer)
    producer.stop = srv.stop_event
    srv.allow_control = False
    try:
        status, headers, raw = request(srv, "/api/stream")
    finally:
        close()
    assert status == 200
    assert headers["Content-Type"] == "text/event-stream; charset=utf-8"
    assert headers["X-Accel-Buffering"] == "no" and headers["Connection"] == "close"
    assert frames(raw) == [
        ("state", {**first, "control": False}),
        ("delta", {"seq": 2, "set": {"time": "00:01"}}),
        ("bye", {"retry_ms": 20000}),
    ]
    # Each wait is past the last snapshot sent, bounded by the heartbeat.
    assert producer.waits == [(0, 15.0), (1, 15.0), (2, 15.0)]
    assert producer.watching == 0 and srv._streams == 0     # unwatched, slot freed


class FakeServer:
    """The parts of _Server a stream uses."""

    def __init__(self, producer, slots=1):
        self.producer = producer
        self.stop_event = threading.Event()
        self.allow_control = True
        self.slots = slots
        self.claimed = self.released = 0

    def claim_stream(self):
        if self.claimed - self.released >= self.slots:
            return False
        self.claimed += 1
        return True

    def release_stream(self):
        self.released += 1


class Connection:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class Output(io.BytesIO):
    """The response body; can fail or stop the server on a write."""

    def __init__(self, fail=None, on_flush=None):
        super().__init__()
        self.fail, self.on_flush = fail, on_flush

    def write(self, data):
        if self.fail is not None:
            raise self.fail
        return super().write(data)

    def flush(self):
        if self.on_flush is not None:
            self.on_flush()


def stream_handler(server, output=None):
    """A Handler for GET /api/stream on an in-memory connection."""
    handler = routes.Handler.__new__(routes.Handler)
    handler.server = server
    handler.wfile = output or Output()
    handler.connection = Connection()
    handler.client_address = ("127.0.0.1", 50000)
    handler.headers = {}
    handler.path = "/api/stream"
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET /api/stream HTTP/1.1"
    handler.close_connection = False
    return handler


def split_response(raw):
    head, body = raw.split(b"\r\n\r\n", 1)
    return int(head.split(b" ", 2)[1]), body


@pytest.fixture
def clock(monkeypatch):
    """The stream's clock, moved by the scripted steps."""
    now = [100.0]
    monkeypatch.setattr(routes, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_an_idle_stream_pings_once_per_heartbeat_interval(clock):
    def later(seconds, snapshot=None):
        def step():
            clock[0] += seconds
            return snapshot
        return step

    producer = ScriptedProducer([later(5), later(10), later(14), later(1, {"seq": 3}), later(15)])
    server = FakeServer(producer)
    producer.stop = server.stop_event
    handler = stream_handler(server)
    handler._stream_frames(producer, 0)
    assert frames(handler.wfile.getvalue()) == [
        ": ping",                                       # 15 s after the start
        ("state", {"seq": 3, "control": True}),        # 29 s: a frame, no ping needed
        ": ping",                                       # 15 s after that frame
        ("bye", {"retry_ms": 20000}),
    ]
    assert handler.connection.timeouts == [routes._STREAM_WRITE_TIMEOUT]


def test_a_snapshot_arriving_at_shutdown_is_not_sent():
    server = FakeServer(None)
    producer = ScriptedProducer([lambda: server.stop_event.set() or {"seq": 1}])
    handler = stream_handler(server)
    handler._stream_frames(producer, 0)
    assert frames(handler.wfile.getvalue()) == [("bye", {"retry_ms": 20000})]


def test_a_stop_while_writing_ends_the_stream_after_the_frame():
    server = FakeServer(None)
    producer = ScriptedProducer([{"seq": 1}, {"seq": 2}])
    output = Output(on_flush=server.stop_event.set)
    handler = stream_handler(server, output)
    handler._stream_frames(producer, 0)
    assert frames(output.getvalue()) == [("state", {"seq": 1, "control": True}),
                                         ("bye", {"retry_ms": 20000})]
    assert len(producer.waits) == 1


def test_no_stream_starts_while_shutting_down():
    server = FakeServer(ScriptedProducer([]))
    server.stop_event.set()
    handler = stream_handler(server)
    handler._serve_stream()
    status, body = split_response(handler.wfile.getvalue())
    assert status == 503 and json.loads(body) == {"error": "shutting down", "retry_ms": 20000}
    assert handler.close_connection is True
    assert server.claimed == 0 and server.producer.watching == 0


def test_a_stream_over_the_limit_is_refused():
    server = FakeServer(ScriptedProducer([]), slots=0)
    handler = stream_handler(server)
    handler._serve_stream()
    status, body = split_response(handler.wfile.getvalue())
    assert status == 503 and json.loads(body) == {"error": "too many streams"}
    assert server.released == 0 and server.producer.waits == []


@pytest.mark.parametrize("error", [BrokenPipeError("gone"), ValueError("closed file")])
def test_a_client_leaving_frees_its_stream_slot(error):
    producer = ScriptedProducer([{"seq": 1}])
    server = FakeServer(producer)
    handler = stream_handler(server, Output(fail=error))
    handler._serve_stream()                 # the error does not escape
    assert (server.claimed, server.released) == (1, 1)
    assert producer.watching == 0           # unwatched despite the failure
    assert handler.close_connection is True
