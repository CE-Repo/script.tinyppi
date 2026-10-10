# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The real dashboard server, outside Kodi, for the browser test.

Kodi's modules are the test stubs; the library answers from a small fake
video database and the producer hands out one fixed playing snapshot.
Prints ``PORT <n>`` once it listens, then serves until killed.
"""

import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tests", "stubs"), os.path.join(ROOT, "resources", "lib")]

import xbmcaddon  # noqa: E402
from web import library  # noqa: E402
from web import server as web_server  # noqa: E402

TOKEN = "BROWSER1"
xbmcaddon.SETTINGS.update({"web_auth_read": "false", "web_allow_control": "true",
                           "web_library": "true", "web_series": "true"})

FILMS = [
    {"movieid": i, "title": f"Film {i:02d}", "year": 2000 + i, "art": {},
     "playcount": i % 2, "ratings": {"imdb": {"rating": 5 + i / 10}},
     "runtime": 5400 + 60 * i, "resume": {"position": 1800 if i == 3 else 0, "total": 7200},
     "dateadded": f"2026-09-{i:02d} 10:00:00"}
    for i in range(1, 21)
]


def fake_rpc(method: str, params: dict | None = None) -> dict:
    params = params or {}
    if method == "VideoLibrary.GetMovies":
        if "filter" in params:
            return {"result": {"movies": [
                {"movieid": 3, "title": "Film 03", "year": 2003, "art": {},
                 "resume": {"position": 1800, "total": 7200},
                 "lastplayed": "2026-10-01 20:00:00", "runtime": 7200}]}}
        return {"result": {"movies": FILMS}}
    if method == "VideoLibrary.GetTVShows":
        return {"result": {"tvshows": [
            {"tvshowid": i, "title": f"Show {i}", "year": 2010 + i, "episode": 10,
             "watchedepisodes": i, "art": {}, "dateadded": f"2026-08-{i:02d} 10:00:00"}
            for i in range(1, 6)]}}
    if method == "VideoLibrary.GetEpisodes" and "filter" in params:
        return {"result": {"episodes": [
            {"episodeid": 99, "title": "Started", "tvshowid": 2, "showtitle": "Show 2",
             "season": 1, "episode": 3, "resume": {"position": 100, "total": 1000}, "art": {},
             "lastplayed": "2026-10-02 20:00:00"}]}}
    if method == "VideoLibrary.GetEpisodes":
        return {"result": {"episodes": [
            {"episodeid": 100 + n, "title": f"Episode {n}", "season": 1 + n // 6,
             "episode": 1 + n % 6, "playcount": int(n < 3), "runtime": 2700, "art": {}}
            for n in range(10)]}}
    return {"result": "OK"}


SNAPSHOT = {
    "playing": True, "paused": True, "title": "Film", "time": "00:10:00",
    "duration": "02:00:00", "hdr_type": "dolbyvision", "output_type": "dolbyvision",
    "groups": [
        {"id": "video", "title": "Video", "rows": [
            {"id": "video.res", "label": "Resolution", "value": "3840x2160p 23.976FPS", "detail": ""},
            {"id": "video.hdr", "label": "HDR", "value": "Dolby Vision ✔", "detail": ""},
            {"id": "dv.profile", "label": "Profile", "value": "7.6", "detail": ""},
            {"id": "dv.layer", "label": "Layer", "value": "FEL", "detail": ""}]},
        {"id": "audio", "title": "Audio", "rows": [
            {"id": "audio.32238", "label": "Codec", "value": "TrueHD Atmos 7.1", "detail": ""}]}],
    "metrics": {"cpu": 20, "cpu_temp": 50, "fps_in": 24, "l1": {"max": 1000, "avg": 120},
                "frame": {"w": 3840, "h": 2160}},
    "metadata": [{"kind": "row", "name": "L1 max", "value": "1000"}],
    "session": {"seq": 3, "switches": 1, "warnings": 1}, "library": 1, "control": True,
}

HISTORY = {
    "t": [0, 1], "max": [900, 1000], "avg": [100, 120], "now": 1, "step": 1,
    "seq": 3, "switches": 1,
    "events": [
        {"t": 0.5, "pos": "00:00:10", "kind": "fps", "from": 24, "to": 60},
        {"t": 0.8, "pos": "00:00:12", "kind": "audio",
         "from": "#1 · ENG · English", "to": "#2 · GER · Deutsch"},
        {"t": 0.9, "pos": "00:00:13", "kind": "temperature", "value": 77.4}],
}


class Producer:
    seq = 1

    def fresh(self) -> dict:
        return dict(SNAPSHOT, seq=self.seq)

    def history(self) -> dict:
        return HISTORY

    def watch(self) -> int:
        return 0

    def unwatch(self) -> None:
        pass

    def wait_for(self, seen: int, timeout: float) -> dict:
        time.sleep(min(timeout, 0.2))
        self.seq += 1
        return dict(SNAPSHOT, seq=self.seq)


library.rpc = fake_rpc
server = web_server._Server(("127.0.0.1", 0), Producer(), threading.Event(), TOKEN)
server.refresh_settings()
print(f"PORT {server.server_address[1]}", flush=True)
server.serve_forever(poll_interval=0.1)
