# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A dashboard server on a free port, and requests to it, for the tests."""

import json
import threading
import urllib.error
import urllib.request

from web import server as web_server

TOKEN = "TESTTK23"


class IdleProducer:
    """A producer with nothing playing (no thread)."""

    def fresh(self):
        return {"seq": 1, "playing": False, "groups": [], "metrics": {}, "library": 0}

    def history(self):
        return {"t": [], "events": []}


DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(srv, path, method="GET", body=None, token=None, host=None):
    port = srv.server_address[1]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-TinyPPI-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with DIRECT.open(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def serve(producer=None):
    """Start a dashboard server on a free port; returns it and its stopper."""
    stop = threading.Event()
    srv = web_server._Server(("127.0.0.1", 0), producer or IdleProducer(), stop, TOKEN)
    srv.refresh_settings()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def close():
        stop.set()
        srv.shutdown()
        srv.server_close()
        srv.close_connections()
        srv.join_workers(2)
    return srv, close

