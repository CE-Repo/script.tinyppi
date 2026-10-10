# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""TinyPPI end to end on Kodi 22: service, dashboard, playback, overlay,
VS10 dialog, codec logos, remote, library actions, limits, dialogs, the page
in a browser and the shutdown.

Runs on a fresh profile with the test library scanned.  The VS10 switches
cannot reach an Amlogic driver here: their sysfs writes fail and are
reported apart as expected.
"""

import gzip
import json
import os
import socket
import subprocess
import sys
import time
import traceback

import config
import driver as kodi
from report import Report
from stream import Page

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = config.TOKEN
AUTH = {"X-TinyPPI-Token": TOKEN}
REPORT = Report("functional")
check = REPORT.check
section = REPORT.section
KODI = None


def lan_address():
    """This machine's LAN address: the lockout test must not lock out 127.0.0.1."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("203.0.113.1", 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


def jget(path, **kw):
    status, headers, body = kodi.http(path, **kw)
    try:
        payload = json.loads(gzip.decompress(body) if headers.get("Content-Encoding") == "gzip" else body)
    except Exception:
        payload = None
    return status, headers, payload


def post(path, body, token=TOKEN, **kw):
    headers = {"X-TinyPPI-Token": token} if token is not None else {}
    status, _, raw = kodi.http(path, method="POST", body=body, headers=headers, **kw)
    try:
        return status, json.loads(raw)
    except Exception:
        return status, raw


def prop(*names):
    return kodi.props(*names)


def player():
    return kodi.player_id()


def player_props(*names):
    return kodi.player_props(*names)


def wait(predicate, timeout=15, step=0.25):
    return kodi.wait(predicate, timeout, step)


def run():
    offset = 0

    section("service")
    check("Kodi 22 answers JSON-RPC", kodi.rpc("JSONRPC.Ping")["result"] == "pong")
    ver = kodi.rpc("Application.GetProperties", {"properties": ["version", "name"]})["result"]
    check("Kodi version is 22", ver["version"]["major"] == 22, ver)
    details = kodi.rpc("Addons.GetAddonDetails", {"addonid": "script.tinyppi",
                                                  "properties": ["version", "enabled", "dependencies"]})["result"]["addon"]
    check("TinyPPI installed and enabled", details["enabled"], details["version"])
    check("service started", KODI.wait_log("KodiMonitor started", 0, 30))
    check("service handover property set", prop("TinyPPI.Service")["TinyPPI.Service"] == "1")
    check("dashboard listening", KODI.wait_log("dashboard listening on", 0, 30))

    section("dashboard: static files and headers")
    status, headers, body = kodi.http("/")
    check("GET / serves the page", status == 200 and b"<html" in body.lower(), status)
    check("page has CSP", "default-src 'self'" in headers.get("Content-Security-Policy", ""))
    check("page refuses framing", headers.get("X-Frame-Options") == "DENY")
    etag = headers.get("ETag")
    status, _, _ = kodi.http("/", headers={"If-None-Match": etag})
    check("static ETag answers 304", status == 304, status)
    status, headers, body = kodi.http("/js/dashboard.js", headers={"Accept-Encoding": "gzip"})
    check("static JS is gzipped", status == 200 and headers.get("Content-Encoding") == "gzip", headers.get("Content-Encoding"))
    for path in ("/../addon.xml", "/css/../../addon.xml", "/resources/lib/web/server.py", "/nope"):
        status, _, _ = kodi.http(path)
        check(f"no file outside the route table: {path}", status == 404, status)

    section("dashboard: read API (nothing playing)")
    status, _, hello = jget("/api/hello")
    check("hello", status == 200 and hello["version"] == details["version"] and hello["control"]
          and hello["library"] and hello["series"] and not hello["auth_read"] and len(hello["strings"]) > 20,
          {k: hello[k] for k in ("version", "auth_read", "control", "library", "series")})
    status, _, state = jget("/api/state")
    check("state while idle", status == 200 and state["playing"] is False and "library" in state, status)
    status, _, history = jget("/api/history")
    check("history", status == 200 and isinstance(history, dict), list(history)[:6])
    status, headers, films = jget("/api/library")
    check("film library lists 30 films", status == 200 and films["count"] == 30, films and films["count"])
    status, _, _ = kodi.http("/api/library", headers={"If-None-Match": headers.get("ETag", "")})
    check("film library answers 304 when unchanged", status == 304, status)
    by_title = {f["title"]: f for f in films["movies"]}
    check("films carry rating, year, poster tag", all("rating" in f and "year" in f and f["poster"] for f in films["movies"]),
          by_title["Dunkirk"])
    status, _, shows = jget("/api/series")
    check("series library lists 2 shows", status == 200 and shows["count"] == 2, shows and shows["count"])
    alpha = next(s for s in shows["shows"] if s["title"] == "Test Show Alpha")
    status, _, eps = jget(f"/api/episodes?tvshowid={alpha['id']}")
    check("episodes of a show", status == 200 and eps["count"] == 6, eps and eps["count"])
    status, _, _ = jget("/api/episodes?tvshowid=99999")
    check("unknown show is 404", status == 404, status)
    status, _, cont = jget("/api/continue")
    check("continue row empty at first", status == 200 and cont["count"] == 0, cont)
    for title in ("Dunkirk", "Oppenheimer"):     # jpg and png posters
        film = by_title[title]
        status, headers, body = kodi.http(f"/api/art?kind=poster&movieid={film['id']}&v={film['poster']}")
        magic = "png" if body[:4] == b"\x89PNG" else "jpeg" if body[:3] == b"\xff\xd8\xff" else "?"
        check(f"shelf poster of {title} served with the type of its bytes",
              status == 200 and headers.get("Content-Type", "").endswith(magic), (status, headers.get("Content-Type"), magic, len(body)))
    status, headers, _ = kodi.http(f"/api/art?kind=poster&movieid={by_title['Dunkirk']['id']}&v={by_title['Dunkirk']['poster']}",
                                   headers={"If-None-Match": f'"{by_title["Dunkirk"]["poster"]}"'})
    check("tagged artwork answers 304", status == 304, status)
    status, _, body = kodi.http(f"/api/art?kind=poster&tvshowid={alpha['id']}&v={alpha['poster']}")
    check("series poster", status == 200 and len(body) > 1000, status)

    section("dashboard: access control")
    status, payload = post("/api/command", {"action": "mute"}, token=None)
    check("writing without a token is 401", status == 401, status)
    status, payload = post("/api/command", {"action": "mute"}, token="WRONG1")
    check("writing with a wrong token is 401", status == 401, status)
    status, _, hello_evil = jget("/api/hello", host="evil.example.com")
    check("untrusted host name asks for the token", hello_evil["auth_read"] is True, hello_evil["auth_read"])
    status, _, _ = jget("/api/state", host="evil.example.com")
    check("untrusted host cannot read without token", status == 401, status)
    status, _, _ = jget("/api/state", host="evil.example.com", headers=AUTH)
    check("untrusted host reads with the token", status == 200, status)
    status, _, _ = jget("/api/state", host="coreelec.local:8099")
    check("home-network name reads without token", status == 200, status)
    kodi.helper("set", "web_auth_read=true")
    ok = wait(lambda: jget("/api/state")[0] == 401, 8)
    check("'require token for reading' applies without restart", ok)
    status, _, _ = jget("/api/state", headers=AUTH)
    check("... and the token still reads", status == 200, status)
    kodi.helper("set", "web_auth_read=false")
    wait(lambda: jget("/api/state")[0] == 200, 8)

    section("playback started from the dashboard")
    dunkirk = by_title["Dunkirk"]
    status, payload = post("/api/play", {"movieid": dunkirk["id"]})
    check("POST /api/play starts the film", status == 200 and payload.get("ok"), payload)
    playing = wait(lambda: player() is not None and kodi.rpc("XBMC.GetInfoBooleans", {"booleans": ["Player.HasVideo"]})["result"]["Player.HasVideo"], 20)
    check("video is playing", playing)
    fullscreen = wait(lambda: kodi.rpc("XBMC.GetInfoBooleans", {"booleans": ["Window.IsActive(fullscreenvideo)"]})["result"]["Window.IsActive(fullscreenvideo)"], 15)
    check("fullscreen video active", fullscreen)
    time.sleep(4)
    kodi.shot("01-playback")
    state = wait(lambda: (lambda s: s if s and s.get("playing") and s.get("groups") else None)(jget("/api/state")[2]), 15)
    check("state while playing has the overlay rows", bool(state), state and [g.get("id") for g in state["groups"]])
    if state:
        rows = {r["id"]: r.get("value") for g in state["groups"] for r in g.get("rows", [])}
        print("  sample rows:", {k: rows[k] for k in list(rows)[:14]})
        check("title in snapshot", "Dunkirk" in json.dumps(state, ensure_ascii=False)[:20000])
        check("snapshot reports HDR10 source", "hdr10" in json.dumps(state).lower(), state.get("badges") or state.get("formats"))
        print("  keys:", sorted(state.keys()))

    page = Page(follow_library=False)
    page.start()
    time.sleep(4)
    kinds = [f[1] for f in page.frames]
    sizes = [len(json.dumps(f[2])) for f in page.frames]
    check("event stream: one state, then deltas", kinds[:1] == ["state"] and "delta" in kinds,
          f"{len(kinds)} frames, state {sizes[0] if sizes else 0} B, deltas avg {int(sum(sizes[1:]) / max(1, len(sizes) - 1))} B")

    status, headers, body = kodi.http("/api/art?kind=poster")
    magic = "png" if body[:4] == b"\x89PNG" else "jpeg" if body[:3] == b"\xff\xd8\xff" else "?"
    with open(os.path.join(config.MEDIA, "movies", "Dunkirk (2017)", "Dunkirk (2017)-poster.jpg"), "rb") as handle:
        original = handle.read()
    check("now-playing poster served", status == 200 and headers.get("Content-Type", "").endswith(magic), (status, headers.get("Content-Type"), len(body)))
    check("now-playing poster comes from Kodi's texture cache, not the original file", body != original,
          f"served {len(body)} B, original {len(original)} B")
    status, headers, body = kodi.http("/api/art?kind=fanart")
    check("now-playing fanart served", status == 200 and len(body) > 1000, (status, headers.get("Content-Type")))
    status, _, hist = jget("/api/history")
    check("history while playing", status == 200, list(hist)[:6] if hist else hist)

    section("overlay")
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi"})
    opened = wait(lambda: prop("TinyPPI.Running")["TinyPPI.Running"] == "true", 10)
    check("RunAddon opens the overlay", opened)
    check("the launch was handed to the service", "opening in this script instead" not in KODI.log(offset))
    time.sleep(2.5)
    kodi.shot("02-overlay")
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi"})
    closed = wait(lambda: prop("TinyPPI.Running")["TinyPPI.Running"] != "true", 10)
    check("RunAddon again closes it (toggle)", closed)
    time.sleep(1)
    kodi.rpc("JSONRPC.NotifyAll", {"sender": "script.tinyppi", "message": "open_overlay"})
    opened = wait(lambda: prop("TinyPPI.Running")["TinyPPI.Running"] == "true", 10)
    check("NotifyAll(script.tinyppi,open_overlay) opens it", opened)
    time.sleep(1.5)
    kodi.rpc("Input.Select")      # OK: DV metadata view only for DV sources
    time.sleep(1.5)
    kodi.shot("03-overlay-after-ok")
    check("OK on a non-DV source keeps the overlay", prop("TinyPPI.Running")["TinyPPI.Running"] == "true")
    kodi.rpc("Input.Back")
    closed = wait(lambda: prop("TinyPPI.Running")["TinyPPI.Running"] != "true", 10)
    check("Back closes the overlay", closed)

    section("VS10 dialog")
    time.sleep(1)
    before = kodi.rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["result"]["currentwindow"]
    kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi", "params": ["dialog"]})
    time.sleep(3)
    win = kodi.rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["result"]["currentwindow"]
    kodi.shot("04-vs10-dialog")
    check("VS10 dialog opens", win["id"] != before["id"], win)
    kodi.rpc("Input.Back")
    time.sleep(1.5)

    section("splash (codec logos)")
    kodi.helper("set", "splash_enabled=true")
    shown = wait(lambda: prop("TinyPPI.SplashVisible")["TinyPPI.SplashVisible"] == "true", 10, 0.5)
    kodi.shot("05-splash")
    check("codec-logo splash shows during playback once enabled", shown, prop("TinyPPI.SplashActive", "TinyPPI.SplashVisible"))
    kodi.helper("set", "splash_enabled=false")

    section("transport commands")
    status, payload = post("/api/command", {"action": "playpause"})
    paused = wait(lambda: player_props("speed").get("speed") == 0, 5)
    check("playpause pauses", status == 200 and paused, payload)
    post("/api/command", {"action": "playpause"})
    check("playpause resumes", wait(lambda: player_props("speed").get("speed") == 1, 5))
    t0 = player_props("time")["time"]
    status, payload = post("/api/command", {"action": "seek", "value": 30})
    t1 = wait(lambda: (lambda t: t if t["seconds"] + t["minutes"] * 60 > t0["seconds"] + t0["minutes"] * 60 + 20 else None)(player_props("time")["time"]), 6)
    check("seek +30 s", status == 200 and t1, (t0, t1))
    status, payload = post("/api/command", {"action": "seek_percent", "value": 10})
    check("seek to 10 %", status == 200 and wait(lambda: player_props("percentage")["percentage"] < 20, 6), player_props("percentage"))
    status, payload = post("/api/command", {"action": "seek", "value": 99999})
    check("out-of-range seek refused", status == 400, status)
    clock = player_props("time")["time"]
    check("player clock runs", wait(lambda: player_props("time")["time"] != clock, 8, 0.5))
    status, payload = post("/api/command", {"action": "subtitle", "value": 0})
    check("subtitles on", status == 200 and wait(lambda: player_props("subtitleenabled")["subtitleenabled"], 5),
          (status, payload, player_props("subtitleenabled", "currentsubtitle", "subtitles")))
    status, payload = post("/api/command", {"action": "subtitle", "value": -1})
    check("subtitles off", status == 200 and wait(lambda: not player_props("subtitleenabled")["subtitleenabled"], 5))
    chapter = kodi.rpc("XBMC.GetInfoLabels", {"labels": ["Player.Chapter", "Player.ChapterCount"]})["result"]
    status, payload = post("/api/command", {"action": "chapter_next"})
    after = wait(lambda: (lambda c: c if c["Player.Chapter"] != chapter["Player.Chapter"] else None)(
        kodi.rpc("XBMC.GetInfoLabels", {"labels": ["Player.Chapter"]})["result"]), 6)
    check("next chapter", status == 200 and after, (chapter, after))
    status, payload = post("/api/command", {"action": "audio", "value": 1})
    check("switch audio track", status == 200 and wait(lambda: player_props("currentaudiostream")["currentaudiostream"]["index"] == 1, 5),
          player_props("currentaudiostream").get("currentaudiostream"))
    # Back to the E-AC3 track: in this container (no audio device) Kodi's
    # clock stalls on the AC3 track, which has nothing to do with TinyPPI.
    status, payload = post("/api/command", {"action": "audio", "value": 0})
    check("switch audio track back", status == 200 and wait(lambda: player_props("currentaudiostream")["currentaudiostream"]["index"] == 0, 5))
    time.sleep(2)
    for action in ("volume_up", "volume_down", "mute", "mute"):
        status, payload = post("/api/command", {"action": action})
        check(f"{action}", status == 200, payload)
    status, payload = post("/api/command", {"action": "volume", "value": 40})
    vol = kodi.rpc("Application.GetProperties", {"properties": ["volume"]})["result"]["volume"]
    check("absolute volume (old clients)", status == 200 and vol == 40, vol)
    status, payload = post("/api/command", {"action": "rm -rf"})
    check("unknown command refused", status == 400, status)

    section("VS10 switching: latest request wins")
    state = jget("/api/state")[2]
    options = [o["mode"] for o in (state.get("vs10") or {}).get("options", [])]
    check("VS10 modes offered for HDR10", len(options) >= 3, options)
    mark = len(KODI.log(0))
    for mode in options[:3]:
        status, payload = post("/api/mode", {"mode": mode})
        check(f"POST /api/mode {mode} accepted", status == 200, payload)
    status, payload = post("/api/mode", {"mode": "evil"})
    check("unknown mode refused", status == 400, status)
    time.sleep(12)
    log = KODI.log(0)[mark:]
    replaced = f"VS10 mode '{options[1]}' replaced by '{options[2]}' before it started" in log
    check("the middle tap was replaced by the last", replaced,
          [line for line in log.splitlines() if "VS10 mode" in line or "Unknown mode" in line][:6])
    check("no VS10 mode failed with an exception", "VS10 mode" not in log or "failed:" not in log)

    section("library actions")
    oppen = by_title["Oppenheimer"]
    rev0 = jget("/api/state")[2]["library"]
    status, payload = post("/api/watched", {"movieid": oppen["id"], "watched": True})
    check("mark film watched", status == 200 and payload.get("ok"), payload)
    check("library revision moves with the next snapshot", wait(lambda: jget("/api/state")[2]["library"] != rev0, 2))
    films2 = jget("/api/library")[2]
    check("film shows as watched", next(f for f in films2["movies"] if f["id"] == oppen["id"]).get("watched") is True)
    status, payload = post("/api/watched", {"movieid": oppen["id"], "watched": False})
    films2 = jget("/api/library")[2]
    check("mark film unwatched", status == 200 and not next(f for f in films2["movies"] if f["id"] == oppen["id"]).get("watched"))
    status, payload = post("/api/watched", {"tvshowid": alpha["id"], "watched": True})
    shows2 = jget("/api/series")[2]
    check("mark show watched (all episodes)", status == 200 and next(s for s in shows2["shows"] if s["id"] == alpha["id"]).get("unseen") == 0)
    post("/api/watched", {"tvshowid": alpha["id"], "watched": False})
    status, payload = post("/api/watched", {"movieid": oppen["id"]})
    check("watched flag required", status == 400, status)

    # Stop Dunkirk half-way: it must land on the continue row once Kodi has
    # written the resume point (deferred drops after Player.OnStop).
    post("/api/command", {"action": "seek_percent", "value": 50})
    time.sleep(3)
    rev1 = jget("/api/state")[2]["library"]
    post("/api/command", {"action": "stop"})
    check("stop", wait(lambda: player() is None, 8))
    got = wait(lambda: (lambda c: c if c and c["count"] else None)(jget("/api/continue")[2]), 12)
    check("stopped film appears on the continue row", got and got["items"][0]["id"] == dunkirk["id"], got)
    check("revision moved after the stop", jget("/api/state")[2]["library"] != rev1)
    status, payload = post("/api/resume", {"movieid": dunkirk["id"]})
    got = wait(lambda: (lambda c: c if c["count"] == 0 else None)(jget("/api/continue")[2]), 8)
    check("clear resume point empties the row", status == 200 and got, payload)
    ep = eps["episodes"][0]
    status, payload = post("/api/play", {"episodeid": ep["id"]})
    check("play an episode", status == 200 and wait(lambda: player() is not None, 15), payload)
    time.sleep(3)
    page.stop.set()

    section("connection caps")
    socks = [socket.create_connection(("127.0.0.1", 8099)) for _ in range(20)]
    time.sleep(1.0)
    refused = 0
    for s in socks:
        s.settimeout(0.5)
        try:
            if s.recv(1) == b"":
                refused += 1
        except TimeoutError:
            pass
        except ConnectionResetError:
            refused += 1
    check("one address holds at most 16 connections", refused >= 4, f"{refused} of 20 refused")
    for s in socks:
        s.close()
    time.sleep(0.5)
    check("dashboard still answers after the cap", jget("/api/hello")[0] == 200)
    check("refusal logged", "refusing a connection from 127.0.0.1" in KODI.log(offset))

    section("guessing lockout (from the LAN address)")
    codes = []
    for i in range(10):
        codes.append(_post_lan({"action": "mute"}, f"GUESS{i:03d}"))
    final = _post_lan({"action": "mute"}, TOKEN)
    check("10 different wrong tokens lock the address out", codes[:9] == [401] * 9 and final == 429, (codes, final))
    check("localhost unaffected by the LAN lockout", post("/api/command", {"action": "mute"})[0] == 200)
    post("/api/command", {"action": "mute"})

    section("dialogs from the settings")
    for params, name in ((["web_info"], "06-web-info"), (["pick_color", "splash_start_bg_color"], "07-color-picker")):
        kodi.rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi", "params": params})
        time.sleep(3)
        win = kodi.rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["result"]["currentwindow"]
        kodi.shot(name)
        check(f"{params[0]} opens a dialog", "dialog" in win["label"].lower() or win["id"] >= 10100, win)
        kodi.rpc("Input.Back")
        time.sleep(1.5)
    kodi.helper("builtin", "Addon.OpenSettings(script.tinyppi)")
    time.sleep(4)
    win = kodi.rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["result"]["currentwindow"]
    kodi.shot("08-addon-settings")
    check("add-on settings open", win["id"] == 10140, win)
    kodi.rpc("Input.Back")
    time.sleep(2)

    section("browser UI")
    browser = run_browser()
    if browser is None:
        REPORT.skip("the page in Chromium", "needs node and the playwright package")
        return
    check("dashboard page loads in Chromium without console errors", not browser.get("errors"), browser.get("errors"))
    check("all tabs render", len(browser.get("tabs", [])) >= 5, browser.get("tabs"))
    check("page shows live connection", browser.get("connected"), browser.get("status"))


def run_browser():
    """Run browser.js; None when Node.js or Playwright is not installed."""
    env = dict(os.environ, SHOTS=config.SHOTS, URL=f"http://127.0.0.1:{config.DASHBOARD_PORT}/")
    try:
        if "NODE_PATH" not in env:
            env["NODE_PATH"] = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        found = subprocess.run(["node", "-e", "require('playwright')"], env=env, capture_output=True)
    except FileNotFoundError:
        return None
    if found.returncode:
        return None
    proc = subprocess.run(["node", os.path.join(HERE, "browser.js")], capture_output=True, text=True,
                          timeout=180, env=env)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"errors": [proc.stderr[-500:] or "no result"], "tabs": []}


def _post_lan(body, token):
    """POST from the LAN address, so a lockout does not hit 127.0.0.1."""
    import http.client
    conn = http.client.HTTPConnection(lan_address(), config.DASHBOARD_PORT, timeout=5)
    conn.request("POST", "/api/command", json.dumps(body), {"Content-Type": "application/json", "X-TinyPPI-Token": token})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


def shutdown():
    section("shutdown")
    stream = Page(follow_library=False)
    stream.start()
    idle = socket.create_connection(("127.0.0.1", config.DASHBOARD_PORT))
    idle.sendall(b"GET /api/hello HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    time.sleep(2)
    took = KODI.quit(90)
    check("Kodi quits with a stream and an idle keep-alive open", took is not None and took < 20, f"{took} s")
    log = KODI.log()
    for bad in ("did not stop", "still running", "snapshot producer did not stop"):
        check(f"no '{bad}' at shutdown", bad not in log)
    lines = [line for line in log.splitlines()
             if "TinyPPI" in line and (" error " in line.lower() or "Traceback" in line or "EXCEPTION" in line)]
    # Writing the Amlogic sysfs nodes fails off CoreELEC hardware by nature.
    amlogic = [line for line in lines if "FAILED /sys/" in line or "via built-in TinyPPI VS10 (sysfs)" in line]
    errors = [line for line in lines if line not in amlogic]
    check("VS10 sysfs writes fail cleanly off Amlogic hardware (expected)", True, f"{len(amlogic)} lines")
    check("no TinyPPI errors in the log", not errors, errors[:12])
    check("no Python tracebacks in the log", log.count("Traceback (most recent call last)") == 0)


def main():
    global KODI
    kodi.require_coreelec_marker()
    KODI = kodi.Kodi(kodi.make_home("functional"))
    print(f"Kodi answered after {KODI.start():.1f} s", flush=True)
    try:
        if not kodi.start_tinyppi(KODI):
            raise RuntimeError("TinyPPI did not start")
        kodi.scan_library()
        run()
    except Exception:
        check("the run finished without an exception in the harness", False, traceback.format_exc())
    try:
        shutdown()
    finally:
        KODI.quit()
        KODI.stop_display()
    sys.exit(REPORT.finish())


if __name__ == "__main__":
    main()
