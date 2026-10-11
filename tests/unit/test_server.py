# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's HTTP server: routes, token checks and connection caps (web/server.py)."""

import json
import select
import socket
import threading
import time
from types import SimpleNamespace

import pytest

import xbmc
import xbmcaddon
from dashboard_server import DIRECT, TOKEN, IdleProducer, request
from web import access
from web import server as web_server


@pytest.fixture(autouse=True)
def no_resolver(monkeypatch):
    """Keep name lookups off the network: the box's own names and the server's name."""
    monkeypatch.setattr(access, "_own_names", lambda: frozenset({"coreelec"}))
    monkeypatch.setattr(socket, "getfqdn", lambda name="": name or "coreelec")


def _wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


def _warnings():
    return [message for level, message in xbmc.LOG if level == xbmc.LOGWARNING]


def test_page_and_static_files(dashboard):
    status, headers, body = request(dashboard, "/")
    assert status == 200 and b"<html" in body.lower()
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    for path in ("/../addon.xml", "/css/../../addon.xml", "/resources/lib/web/server.py", "/nope"):
        assert request(dashboard, path)[0] == 404


def test_hello_and_reading(dashboard):
    status, _, body = request(dashboard, "/api/hello")
    hello = json.loads(body)
    assert status == 200 and hello["auth_read"] is False and hello["version"]
    assert request(dashboard, "/api/state")[0] == 200
    assert request(dashboard, "/api/state", host="evil.example.com")[0] == 401
    assert request(dashboard, "/api/state", host="evil.example.com", token=TOKEN)[0] == 200


def test_reading_from_beyond_the_home_network_needs_the_token(dashboard, monkeypatch):
    seen = []
    monkeypatch.setattr(access, "home_peer", lambda address: seen.append(address) or False)
    assert request(dashboard, "/api/state")[0] == 401
    assert request(dashboard, "/api/state", token=TOKEN)[0] == 200
    assert request(dashboard, "/api/hello")[0] == 200       # what the page needs to ask
    assert seen and set(seen) == {"127.0.0.1"}


def test_writing_needs_the_token(dashboard):
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"})[0] == 401
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"}, token="WRONG")[0] == 401
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"}, token=TOKEN)[0] == 400


def test_ten_wrong_tokens_lock_the_address_out(dashboard):
    codes = [request(dashboard, "/api/mode", "POST", {"mode": "x"}, token=f"GUESS{i}")[0] for i in range(10)]
    assert codes == [401] * 10
    status, headers, _ = request(dashboard, "/api/mode", "POST", {"mode": "x"}, token=TOKEN)
    assert status == 429 and int(headers["Retry-After"]) > 0


def _closed_by_server(sock, timeout=2.0):
    if not select.select([sock], [], [], timeout)[0]:
        return False
    try:
        return sock.recv(1) == b""
    except ConnectionResetError:
        return True


def test_one_address_holds_at_most_16_connections(dashboard):
    port = dashboard.server_address[1]
    sockets = []
    try:
        for count in range(1, 17):
            sockets.append(socket.create_connection(("127.0.0.1", port)))
            # One at a time, so the listen backlog never overflows.
            assert _wait_until(lambda count=count: len(dashboard._connections) == count)
        refused = [socket.create_connection(("127.0.0.1", port)) for _ in range(4)]
        sockets += refused
        assert all(_closed_by_server(sock) for sock in refused)
        # The first 16 stay open, waiting for a request.
        assert select.select(sockets[:16], [], [], 0.05)[0] == []
        assert len(dashboard._connections) == 16
        assert any("refusing a connection" in message for _level, message in xbmc.LOG)
    finally:
        for sock in sockets:
            sock.close()
    assert _wait_until(lambda: not dashboard._connections)
    assert request(dashboard, "/api/hello")[0] == 200


def test_tokens_and_ports():
    addon = xbmcaddon.Addon()
    token = web_server.generate_token(addon)
    assert len(token) == 8 and set(token) <= set(web_server._TOKEN_ALPHABET)
    assert web_server.ensure_token(addon) == token
    for value, port in (("8123", 8123), ("80", 8099), ("70000", 8099), ("x", 8099)):
        addon.setSetting("web_port", value)
        assert web_server.configured_port(addon) == port


def _ipv6_loopback() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _ipv6_loopback(), reason="no IPv6 on this machine")
def test_the_dashboard_answers_over_ipv6_and_ipv4():
    stop = threading.Event()
    srv = web_server._bind(0, IdleProducer(), stop, TOKEN)
    assert isinstance(srv, web_server._DualStackServer)
    srv.refresh_settings()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        port = srv.server_address[1]
        for host in ("127.0.0.1", "[::1]"):
            with DIRECT.open(f"http://{host}:{port}/api/hello", timeout=5) as resp:
                assert resp.status == 200
    finally:
        stop.set()
        srv.shutdown()
        srv.server_close()
        srv.close_connections()
        srv.join_workers(2)


# --- The address shown to the user ------------------------------------------

@pytest.fixture
def probe(monkeypatch):
    """Replace the UDP socket local_address() looks up the route with."""
    record = SimpleNamespace(address=("192.168.1.20", 40000), fail=None, made=[],
                             connected=[], closed=0)

    class Probe:
        def __init__(self, family, kind):
            if record.fail == "socket":
                raise OSError(24, "Too many open files")
            record.made.append((family, kind))

        def connect(self, address):
            record.connected.append(address)
            if record.fail == "connect":
                raise OSError(101, "Network is unreachable")

        def getsockname(self):
            return record.address

        def close(self):
            record.closed += 1

    monkeypatch.setattr(web_server, "socket", SimpleNamespace(
        socket=Probe, AF_INET=socket.AF_INET, SOCK_DGRAM=socket.SOCK_DGRAM))
    return record


def test_the_address_is_where_the_route_to_the_network_leaves_from(probe):
    assert web_server.local_address(8123) == "http://192.168.1.20:8123/"
    assert probe.made == [(socket.AF_INET, socket.SOCK_DGRAM)]
    assert probe.connected == [("203.0.113.1", 9)]
    assert probe.closed == 1


def test_without_a_port_the_configured_one_is_shown(probe):
    xbmcaddon.SETTINGS["web_port"] = "8124"
    assert web_server.local_address() == "http://192.168.1.20:8124/"


@pytest.mark.parametrize(("fail", "address", "kodi_ip", "url"), [
    ("connect", None, "10.0.0.7", "http://10.0.0.7:8099/"),
    ("socket", None, "10.0.0.7", "http://10.0.0.7:8099/"),
    (None, ("", 0), "10.0.0.7", "http://10.0.0.7:8099/"),
    ("connect", None, "", "http://<box-ip>:8099/"),
], ids=["no-route", "no-socket", "no-address", "nothing-known"])
def test_without_a_route_kodis_own_address_is_shown(probe, fail, address, kodi_ip, url):
    probe.fail = fail
    probe.address = address
    xbmc.INFO["Network.IPAddress"] = kodi_ip
    assert web_server.local_address(8099) == url
    # The probe is closed even when its lookup fails.
    assert probe.closed == (0 if fail == "socket" else 1)


# --- Binding -----------------------------------------------------------------

_NO_IPV6 = OSError(97, "Address family not supported by protocol")


@pytest.mark.parametrize(("has_ipv6", "dual_error", "tried", "chosen"), [
    (True, None, [("dual", ("::", 8099))], "dual"),
    (True, _NO_IPV6, [("dual", ("::", 8099)), ("ipv4", ("0.0.0.0", 8099))], "ipv4"),
    (False, None, [("ipv4", ("0.0.0.0", 8099))], "ipv4"),
], ids=["dual-stack", "ipv6-fails", "no-ipv6"])
def test_one_socket_serves_ipv6_and_ipv4_where_it_can(monkeypatch, has_ipv6, dual_error, tried,
                                                      chosen):
    made = []

    def kind(name, error=None):
        def build(address, producer, stop, token):
            made.append((name, address))
            if error is not None:
                raise error
            return SimpleNamespace(name=name, producer=producer, stop=stop, token=token)
        return build

    monkeypatch.setattr(web_server.socket, "has_ipv6", has_ipv6)
    monkeypatch.setattr(web_server, "_DualStackServer", kind("dual", dual_error))
    monkeypatch.setattr(web_server, "_Server", kind("ipv4"))
    producer, stop = IdleProducer(), threading.Event()

    srv = web_server._bind(8099, producer, stop, TOKEN)

    assert made == tried
    assert (srv.name, srv.producer, srv.stop, srv.token) == (chosen, producer, stop, TOKEN)
    expected = [(xbmc.LOGDEBUG, f"TinyPPI [web]: IPv6 unavailable ({_NO_IPV6}), "
                                "listening on IPv4 only")] if dual_error else []
    assert expected == xbmc.LOG


class _RecordingSocket:
    def __init__(self):
        self.calls = []

    def setsockopt(self, level, option, value):
        self.calls.append(("setsockopt", level, option, value))

    def bind(self, address):
        self.calls.append(("bind", address))

    def getsockname(self):
        return ("::", 8099, 0, 0)


def test_the_dual_stack_socket_is_opened_for_ipv4_before_it_binds(monkeypatch):
    monkeypatch.setattr(socket, "getfqdn", lambda name="": "coreelec")
    # Built without __init__: this machine may have no IPv6 to open the socket with.
    srv = web_server._DualStackServer.__new__(web_server._DualStackServer)
    srv.socket = _RecordingSocket()
    srv.server_address = ("::", 8099)

    srv.server_bind()

    assert web_server._DualStackServer.address_family == socket.AF_INET6
    assert srv.socket.calls[0] == ("setsockopt", socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    assert srv.socket.calls[-1] == ("bind", ("::", 8099))
    assert (srv.server_name, srv.server_port) == ("coreelec", 8099)


# --- The server's shared state -----------------------------------------------

@pytest.fixture
def bare():
    """A dashboard server bound to 127.0.0.1 that serves nothing."""
    srv = web_server._Server(("127.0.0.1", 0), IdleProducer(), threading.Event(), TOKEN)
    srv.refresh_settings()
    yield srv
    srv.server_close()


class _Held:
    """An open connection in the server's table."""

    def __init__(self):
        self.how = []

    def shutdown(self, how):
        self.how.append(how)


class _Gone:
    """A connection the client has already torn down."""

    def shutdown(self, how):
        raise OSError(107, "Transport endpoint is not connected")


@pytest.fixture
def clock(monkeypatch):
    fake = SimpleNamespace(now=5000.0)
    monkeypatch.setattr(web_server, "time", SimpleNamespace(monotonic=lambda: fake.now))
    return fake


def test_no_connection_is_taken_once_shutdown_has_begun(dashboard):
    dashboard.stop_event.set()
    assert not dashboard.verify_request(None, ("127.0.0.1", 50000))
    with pytest.raises(OSError):
        request(dashboard, "/api/hello")
    assert dashboard._connections == {}


def test_refused_connections_are_logged_once_a_minute(bare, clock):
    bare._connections.update({_Held(): "10.0.0.9" for _ in range(16)})

    assert not bare.verify_request(None, ("10.0.0.9", 1))
    # The same client seen through the dual-stack socket.
    assert not bare.verify_request(None, ("::ffff:10.0.0.9", 2))
    clock.now += 59
    assert not bare.verify_request(None, ("10.0.0.9", 3))
    assert bare.verify_request(None, ("10.0.0.8", 1))
    assert _warnings() == ["TinyPPI [web]: refusing a connection from 10.0.0.9: "
                           "16 open from it, 16 in all"]

    clock.now += 1
    assert not bare.verify_request(None, ("10.0.0.9", 4))
    assert len(_warnings()) == 2


def test_one_ipv6_network_beyond_the_home_counts_as_one_device(bare):
    bare._connections.update({_Held(): access.client_key(f"2a00:1450:4001:2::{i + 1:x}")
                              for i in range(16)})
    assert not bare.verify_request(None, ("2a00:1450:4001:2::ffff", 1))
    assert bare.verify_request(None, ("2a00:1450:4001:3::1", 1))


def test_at_home_every_ipv6_address_counts_on_its_own(bare):
    bare._connections.update({_Held(): access.client_key("fd00::1") for _ in range(16)})
    assert not bare.verify_request(None, ("fd00::1", 1))
    assert bare.verify_request(None, ("fd00::2", 1))


def test_at_most_48_connections_are_held_in_all(bare):
    bare._connections.update({_Held(): f"10.0.1.{i}" for i in range(47)})
    assert bare.verify_request(None, ("10.0.2.1", 1))
    bare._connections[_Held()] = "10.0.1.47"
    assert not bare.verify_request(None, ("10.0.2.1", 1))
    assert _warnings() == ["TinyPPI [web]: refusing a connection from 10.0.2.1: "
                           "0 open from it, 48 in all"]


def test_hanging_up_reaches_every_connection_even_past_a_dead_one(bare):
    first, last = _Held(), _Held()
    bare._connections.update({first: "10.0.0.1", _Gone(): "10.0.0.2", last: "10.0.0.3"})

    assert bare.close_connections() == 3
    assert bare.close_connections(socket.SHUT_RDWR) == 3

    assert first.how == last.how == [socket.SHUT_RD, socket.SHUT_RDWR]


def test_idle_keep_alive_connections_end_when_hung_up_on(dashboard):
    port = dashboard.server_address[1]
    clients = [socket.create_connection(("127.0.0.1", port)) for _ in range(2)]
    try:
        assert _wait_until(lambda: len(dashboard._workers) == 2)
        # Both threads wait for a request that never comes.
        assert dashboard.join_workers(0) == 2
        assert dashboard.join_workers(0.02) == 2

        assert dashboard.close_connections() == 2

        assert dashboard.join_workers(2) == 0
        assert dashboard._connections == {}
        for client in clients:
            client.settimeout(2)
            assert client.recv(1) == b""
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("error", [BrokenPipeError, ConnectionResetError, TimeoutError])
def test_a_client_leaving_early_is_logged_at_debug(bare, error):
    try:
        raise error("gone")
    except error:
        bare.handle_error(None, ("::ffff:192.168.1.30", 51000))
    assert xbmc.LOG == [(xbmc.LOGDEBUG, "TinyPPI [web]: connection from 192.168.1.30 ended early")]


def test_a_failing_request_is_logged_with_its_traceback(bare):
    try:
        raise ValueError("bad frame")
    except ValueError:
        bare.handle_error(None, ("::ffff:192.168.1.30", 51000))
    [(level, message)] = xbmc.LOG
    assert level == xbmc.LOGERROR
    assert message.startswith("TinyPPI [web]: request from 192.168.1.30 failed:\nTraceback")
    assert message.rstrip().endswith("ValueError: bad frame")


def test_at_most_six_streams_are_open_at_once(bare):
    assert [bare.claim_stream() for _ in range(7)] == [True] * 6 + [False]
    assert bare.streams_full
    bare.release_stream()
    assert not bare.streams_full
    assert bare.claim_stream()
    assert bare.streams_full


def test_extra_stream_releases_do_not_free_extra_slots(bare):
    bare.release_stream()
    bare.release_stream()
    assert not bare.streams_full
    assert [bare.claim_stream() for _ in range(7)] == [True] * 6 + [False]


def test_the_playing_titles_artwork_is_read_once(bare, monkeypatch):
    reads = []

    def picture(path):
        reads.append(path)
        return b"jpeg", "image/jpeg"

    monkeypatch.setattr(web_server.artwork, "art_path", lambda kind: f"/art/{kind}.jpg")
    monkeypatch.setattr(web_server.artwork, "shelf_picture", picture)

    assert bare.artwork("poster") == (b"jpeg", "image/jpeg")
    assert bare.artwork("poster") == (b"jpeg", "image/jpeg")
    assert reads == ["/art/poster.jpg"]


@pytest.fixture
def shelves(monkeypatch):
    """Record the library lookups; every picture's bytes are its path."""
    asked = []

    def lookup(kind):
        def path(item, art):
            asked.append((kind, item, art))
            return f"{kind}{item}-{art}"
        return path

    monkeypatch.setattr(web_server.library, "art_path", lookup("film"))
    monkeypatch.setattr(web_server.library, "show_art_path", lookup("show"))
    monkeypatch.setattr(web_server.library, "episode_art_path", lookup("episode"))
    monkeypatch.setattr(web_server.artwork, "shelf_picture",
                        lambda path: (path.encode(), "image/jpeg"))
    return asked


@pytest.mark.parametrize(("method", "item", "looked_up", "picture"), [
    ("library_artwork", "12", ("film", 12, "poster"), b"film12-poster"),
    ("series_artwork", "7", ("show", "7", "poster"), b"show7-poster"),
    ("episode_artwork", "301", ("episode", "301", "poster"), b"episode301-poster"),
])
def test_shelf_artwork_is_read_for_the_asked_item(bare, shelves, method, item, looked_up,
                                                   picture):
    assert getattr(bare, method)(item, "poster") == (picture, "image/jpeg")
    assert shelves == [looked_up]


@pytest.mark.parametrize(("method", "setting"), [
    ("library_artwork", "web_library"),
    ("library_artwork", "web_allow_control"),
    ("series_artwork", "web_series"),
    ("series_artwork", "web_allow_control"),
    ("episode_artwork", "web_series"),
    ("episode_artwork", "web_allow_control"),
])
def test_shelf_artwork_is_withheld_while_its_shelf_is_off(bare, shelves, method, setting):
    xbmcaddon.SETTINGS[setting] = "false"
    bare.refresh_settings()
    assert getattr(bare, method)("12", "poster") is None
    assert shelves == []


@pytest.mark.parametrize("movie_id", ["abc", None, "1.5"])
def test_a_film_id_that_is_no_number_has_no_artwork(bare, shelves, movie_id):
    assert bare.library_artwork(movie_id, "poster") is None
    assert shelves == []


# --- Starting and stopping ---------------------------------------------------

class _Producer(IdleProducer):
    """Stands in for the snapshot thread and records its lifecycle."""

    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.alive = False
        self.calls = []

    def start(self):
        self.calls.append("start")

    def wake(self):
        self.calls.append("wake")

    def join(self, timeout=None):
        self.calls.append("join")

    def is_alive(self):
        return self.alive


class _QuickServer(web_server._Server):
    """The real server, polling its accept loop faster so stop() returns sooner."""

    def serve_forever(self, poll_interval=0.5):
        super().serve_forever(poll_interval=0.01)


@pytest.fixture
def lifecycle(monkeypatch):
    """A dashboard whose servers listen on 127.0.0.1 beside a fake producer."""
    env = SimpleNamespace(dash=web_server.WebDashboard(), producers=[], ports=[], servers=[])

    def producer(stop_event):
        env.producers.append(_Producer(stop_event))
        return env.producers[-1]

    def bind(port, producer, stop, token):
        env.ports.append(port)
        env.servers.append(_QuickServer(("127.0.0.1", 0), producer, stop, token))
        return env.servers[-1]

    monkeypatch.setattr(web_server, "Producer", producer)
    monkeypatch.setattr(web_server, "_bind", bind)
    monkeypatch.setattr(web_server, "local_address", lambda port: f"http://box:{port}/")
    yield env
    env.dash.stop()


def test_enabling_the_dashboard_starts_it_with_a_new_token(lifecycle):
    xbmcaddon.SETTINGS.update(web_enabled="true", web_port="8123", web_auth_read="true")

    lifecycle.dash.apply_settings()

    srv = lifecycle.dash._server
    token = xbmcaddon.SETTINGS["web_token"]
    assert lifecycle.dash.running
    assert len(token) == 8 and srv.token == token
    assert lifecycle.ports == [8123]
    assert lifecycle.producers[0].calls == ["start"]
    status, _, body = request(srv, "/api/hello")
    assert status == 200 and json.loads(body)["auth_read"] is True
    assert (xbmc.LOGINFO, "TinyPPI [web]: dashboard listening on http://box:8123/") in xbmc.LOG


def test_disabling_the_dashboard_stops_every_thread(lifecycle):
    xbmcaddon.SETTINGS["web_enabled"] = "true"
    lifecycle.dash.apply_settings()
    srv, thread = lifecycle.dash._server, lifecycle.dash._thread
    producer = lifecycle.producers[0]

    xbmcaddon.SETTINGS["web_enabled"] = "false"
    lifecycle.dash.apply_settings()

    assert not lifecycle.dash.running
    assert not thread.is_alive()
    assert srv.socket.fileno() == -1
    assert srv.stop_event.is_set() and producer.stop_event is srv.stop_event
    assert producer.calls == ["start", "wake", "join"]
    assert (xbmc.LOGINFO, "TinyPPI [web]: stopping dashboard") in xbmc.LOG
    assert _warnings() == []


def test_other_settings_change_the_running_server_in_place(lifecycle):
    xbmcaddon.SETTINGS.update(web_enabled="true", web_token=TOKEN)
    lifecycle.dash.apply_settings()
    srv = lifecycle.dash._server
    assert (srv.auth_read, srv.allow_control, srv.offer_library, srv.offer_series) == (
        False, True, True, True)

    xbmcaddon.SETTINGS.update(web_auth_read="true", web_allow_control="false",
                              web_library="false", web_series="false")
    lifecycle.dash.apply_settings()

    assert lifecycle.dash._server is srv
    assert (srv.auth_read, srv.allow_control, srv.offer_library, srv.offer_series) == (
        True, False, False, False)
    assert lifecycle.ports == [8099] and len(lifecycle.producers) == 1


@pytest.mark.parametrize(("key", "value"), [("web_port", "8124"), ("web_token", "NEWTOKEN")])
def test_a_new_port_or_token_restarts_the_server(lifecycle, key, value):
    xbmcaddon.SETTINGS.update(web_enabled="true", web_port="8123", web_token=TOKEN)
    lifecycle.dash.apply_settings()
    first = lifecycle.dash._server

    xbmcaddon.SETTINGS[key] = value
    lifecycle.dash.apply_settings()

    second = lifecycle.dash._server
    assert second is not first and first.socket.fileno() == -1
    assert lifecycle.ports == [8123, int(xbmcaddon.SETTINGS["web_port"])]
    assert second.token == xbmcaddon.SETTINGS["web_token"]
    assert (xbmc.LOGINFO, "TinyPPI [web]: port or token changed, restarting") in xbmc.LOG
    assert [p.calls for p in lifecycle.producers] == [["start", "wake", "join"], ["start"]]


def test_a_second_start_keeps_the_running_server(lifecycle):
    lifecycle.dash.start(8123, TOKEN)
    srv = lifecycle.dash._server

    lifecycle.dash.start(8124, "OTHERTOK")

    assert lifecycle.dash._server is srv and srv.token == TOKEN
    assert lifecycle.ports == [8123]


def test_after_the_final_stop_nothing_starts_again(lifecycle):
    lifecycle.dash.start(8123, TOKEN)
    lifecycle.dash.stop(final=True)
    xbmcaddon.SETTINGS["web_enabled"] = "true"

    lifecycle.dash.apply_settings()
    lifecycle.dash.start(8123, TOKEN)

    assert not lifecycle.dash.running
    assert lifecycle.ports == [8123] and len(lifecycle.producers) == 1


def test_a_port_in_use_leaves_the_dashboard_stopped(lifecycle, monkeypatch):
    def busy(port, producer, stop, token):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(web_server, "_bind", busy)

    lifecycle.dash.start(8099, TOKEN)
    lifecycle.dash.stop()

    assert not lifecycle.dash.running
    assert lifecycle.producers[0].calls == []
    # Nothing ran, so stopping has nothing to log.
    assert xbmc.LOG == [(xbmc.LOGERROR,
                         "TinyPPI [web]: cannot bind port 8099: [Errno 98] Address already in use")]


def _raise(exc):
    raise exc


@pytest.mark.parametrize("failing", ["producer", "server thread"])
def test_a_thread_that_cannot_start_leaves_the_dashboard_stopped(lifecycle, monkeypatch,
                                                                  failing):
    refusals = [RuntimeError("can't start new thread")]     # only the first start fails

    if failing == "producer":
        real_start = _Producer.start
        monkeypatch.setattr(_Producer, "start", lambda producer: (
            real_start(producer) if not refusals else _raise(refusals.pop())))
    else:
        # The producer is running when the server thread fails.
        monkeypatch.setattr(_Producer, "is_alive", lambda producer: True)
        real_start = threading.Thread.start
        monkeypatch.setattr(threading.Thread, "start", lambda thread: (
            _raise(refusals.pop()) if refusals and thread.name == "TinyPPI-web-server"
            else real_start(thread)))

    lifecycle.dash.start(8099, TOKEN)

    srv, producer = lifecycle.servers[0], lifecycle.producers[0]
    assert not lifecycle.dash.running and lifecycle.dash._thread is None
    assert lifecycle.dash._producer is None and lifecycle.dash._stop is None
    assert srv.socket.fileno() == -1
    assert producer.stop_event.is_set()
    assert producer.calls == (["wake"] if failing == "producer" else ["start", "wake", "join"])
    assert xbmc.LOG == [(xbmc.LOGERROR,
                         "TinyPPI [web]: cannot start the dashboard: can't start new thread")]

    # Nothing is left for stop(), and the next start works.
    lifecycle.dash.stop()
    lifecycle.dash.start(8099, TOKEN)
    assert lifecycle.dash.running
    assert request(lifecycle.dash._server, "/api/hello")[0] == 200


def test_settings_are_never_pushed_to_a_missing_server(lifecycle, monkeypatch):
    # apply_settings() checks running before it holds the server; a server
    # gone in between is skipped, not refreshed.
    monkeypatch.setattr(web_server.WebDashboard, "running", property(lambda self: True))
    xbmcaddon.SETTINGS.update(web_enabled="true", web_token=TOKEN)

    lifecycle.dash.apply_settings()

    assert lifecycle.dash._server is None and lifecycle.ports == []


class _FakeServer:
    """A server whose shutdown steps are recorded and can fail."""

    def __init__(self, fail=(), left=(0,), hangs=False):
        self.calls = []
        self.timeouts = []
        self.fail = set(fail)
        self.left = list(left)
        self.hangs = hangs
        self.released = threading.Event()

    def refresh_settings(self, addon=None):
        pass

    def serve_forever(self, poll_interval):
        self.released.wait(5)

    def _step(self, *call):
        self.calls.append(call)
        if call in self.fail:
            raise RuntimeError(f"{call[0]} broke")

    def shutdown(self):
        if not self.hangs:
            self.released.set()
        self._step("shutdown")

    def server_close(self):
        self._step("server_close")

    def close_connections(self, how=socket.SHUT_RD):
        self._step("close_connections", how)
        return 0

    def join_workers(self, timeout):
        self.calls.append(("join_workers",))
        self.timeouts.append(timeout)
        return self.left.pop(0)


_SHUTDOWN = [("shutdown",), ("server_close",), ("close_connections", socket.SHUT_RD),
             ("join_workers",)]
_CUT_OFF = [("close_connections", socket.SHUT_RDWR), ("join_workers",)]


def _start_on(lifecycle, monkeypatch, fake):
    monkeypatch.setattr(web_server, "_bind", lambda port, producer, stop, token: fake)
    lifecycle.dash.start(8099, TOKEN)
    return lifecycle.dash._thread


@pytest.mark.parametrize(("failing", "warning"), [
    (("shutdown",), "server shutdown failed: shutdown broke"),
    (("server_close",), "server close failed: server_close broke"),
    (("close_connections", socket.SHUT_RD), "closing connections failed: close_connections broke"),
], ids=["shutdown", "close", "hang-up"])
def test_a_failing_shutdown_step_is_logged_and_the_rest_still_run(lifecycle, monkeypatch,
                                                                   failing, warning):
    fake = _FakeServer(fail={failing})
    thread = _start_on(lifecycle, monkeypatch, fake)

    lifecycle.dash.stop()

    assert fake.calls == _SHUTDOWN
    assert _warnings() == [f"TinyPPI [web]: {warning}"]
    assert not thread.is_alive()
    assert lifecycle.producers[0].calls == ["start", "wake", "join"]


@pytest.mark.parametrize(("left", "fail", "warnings"), [
    ((0,), (), []),
    ((2, 0), (), []),
    ((2, 1), (), ["1 request thread(s) still running"]),
    ((3, 0), {("close_connections", socket.SHUT_RDWR)},
     ["closing connections failed: close_connections broke"]),
], ids=["all-done", "cut-off", "still-running", "cut-off-fails"])
def test_request_threads_still_busy_after_the_grace_period_are_cut_off(lifecycle, monkeypatch,
                                                                        left, fail, warnings):
    fake = _FakeServer(fail=fail, left=left)
    _start_on(lifecycle, monkeypatch, fake)

    lifecycle.dash.stop()

    assert fake.calls == _SHUTDOWN + (_CUT_OFF if left[0] else [])
    assert fake.timeouts[0] == web_server._HANGUP_GRACE
    # After cutting off, they get the rest of the one shared deadline.
    assert all(1.0 < timeout <= web_server._JOIN_TIMEOUT for timeout in fake.timeouts[1:])
    assert _warnings() == [f"TinyPPI [web]: {warning}" for warning in warnings]


def test_threads_that_outlast_the_deadline_are_reported(lifecycle, monkeypatch):
    monkeypatch.setattr(web_server, "_JOIN_TIMEOUT", 0.02)
    fake = _FakeServer(hangs=True)
    thread = _start_on(lifecycle, monkeypatch, fake)
    lifecycle.producers[0].alive = True
    try:
        lifecycle.dash.stop()
    finally:
        fake.released.set()
        thread.join(2)

    assert not lifecycle.dash.running
    assert _warnings() == ["TinyPPI [web]: web server thread did not stop",
                           "TinyPPI [web]: snapshot producer did not stop"]
    assert fake.timeouts == [0.0]


@pytest.mark.parametrize("part", ["server", "producer"])
def test_stop_tears_down_whichever_parts_exist(part):
    dash = web_server.WebDashboard()
    fake, producer = _FakeServer(), _Producer(threading.Event())
    if part == "server":
        dash._server = fake
    else:
        dash._producer = producer

    dash.stop()

    assert fake.calls == (_SHUTDOWN if part == "server" else [])
    assert producer.calls == ([] if part == "server" else ["wake", "join"])
    assert not dash.running and dash._producer is None
    assert (xbmc.LOGINFO, "TinyPPI [web]: stopping dashboard") in xbmc.LOG


def test_every_server_has_its_own_read_session():
    # A new token restarts the server, which ends the sessions bought with
    # the old one.
    sessions = set()
    for _ in range(2):
        srv = web_server._Server(("127.0.0.1", 0), IdleProducer(), threading.Event(), TOKEN)
        sessions.add(srv.session)
        srv.server_close()
    assert len(sessions) == 2 and all(len(session) >= 40 for session in sessions)
