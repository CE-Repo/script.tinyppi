# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's HTTP server: routes, token checks and connection caps."""

import json
import socket
import threading
import time

import pytest

import xbmc
from dashboard_server import DIRECT, TOKEN, IdleProducer, request
from web import server as web_server


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


def test_writing_needs_the_token(dashboard):
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"})[0] == 401
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"}, token="WRONG")[0] == 401
    assert request(dashboard, "/api/mode", "POST", {"mode": "nope"}, token=TOKEN)[0] == 400


def test_ten_wrong_tokens_lock_the_address_out(dashboard):
    codes = [request(dashboard, "/api/mode", "POST", {"mode": "x"}, token=f"GUESS{i}")[0] for i in range(10)]
    assert codes == [401] * 10
    status, headers, _ = request(dashboard, "/api/mode", "POST", {"mode": "x"}, token=TOKEN)
    assert status == 429 and int(headers["Retry-After"]) > 0


def test_one_address_holds_at_most_16_connections(dashboard):
    port = dashboard.server_address[1]
    sockets = [socket.create_connection(("127.0.0.1", port)) for _ in range(20)]
    try:
        time.sleep(0.5)
        assert len(dashboard._connections) == 16
        refused = 0
        for sock in sockets:
            sock.settimeout(0.3)
            try:
                if sock.recv(1) == b"":
                    refused += 1
            except TimeoutError:
                pass
            except ConnectionResetError:
                refused += 1
        assert refused == 4
        assert any("refusing a connection" in message for _level, message in xbmc.LOG)
    finally:
        for sock in sockets:
            sock.close()
    time.sleep(0.3)
    assert request(dashboard, "/api/hello")[0] == 200


def test_tokens_and_ports():
    import xbmcaddon
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
