# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A dashboard page without a browser: follows /api/stream like js/core.js."""

import http.client
import json
import threading
import time

import config


class Page(threading.Thread):
    """Record the frames; on every new library revision re-read the film
    list, as the page does with the films tab open (libraryVersion in
    js/dashboard.js)."""

    def __init__(self, follow_library=True, token=""):
        super().__init__(daemon=True)
        self.follow = follow_library
        self.token = token
        self.frames = []
        self.revisions = []
        self.fetches = 0
        self.stop = threading.Event()
        self.error = None
        self._revision = None

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", config.DASHBOARD_PORT, timeout=30)
        conn.request("GET", path, headers={"X-TinyPPI-Token": self.token} if self.token else {})
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.status

    def run(self):
        try:
            conn = http.client.HTTPConnection("127.0.0.1", config.DASHBOARD_PORT, timeout=30)
            conn.request("GET", "/api/stream" + (f"?token={self.token}" if self.token else ""))
            response = conn.getresponse()
            kind = None
            while not self.stop.is_set():
                line = response.fp.readline()
                if not line:
                    break
                line = line.decode().rstrip("\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    self.frames.append((time.time(), kind, data))
                    revision = data.get("library") if kind == "state" else (data.get("set") or {}).get("library")
                    if revision is not None and revision != self._revision:
                        first = self._revision is None
                        self._revision = revision
                        self.revisions.append(revision)
                        if self.follow and not first:
                            self.fetches += 1
                            self._get("/api/library")
            conn.close()
        except Exception as exc:  # noqa: BLE001 - reported by the caller
            self.error = repr(exc)
