# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Drive a Kodi 22 instance under Xvfb: profiles, JSON-RPC, HTTP, screenshots.

``make_home`` gives each test run a fresh profile copied from the template
(see setup_profiles.py), with TinyPPI installed from the checkout or from a
git ref.
"""

import base64
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import io
import time
import urllib.error
import urllib.request

import config

_AUTH = "Basic " + base64.b64encode(b"kodi:kodi").decode()
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Paths of the add-on folder that are no part of the installed add-on.
_NOT_INSTALLED = ("docs/", "tools/", "tests/", ".git")

TINYPPI_SETTINGS = f"""<settings version="2">
    <setting id="web_enabled">true</setting>
    <setting id="web_token">{config.TOKEN}</setting>
</settings>
"""


# --- Kodi's APIs -----------------------------------------------------------

def rpc(method, params=None, timeout=15):
    """Call Kodi's JSON-RPC over its web server."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(f"http://127.0.0.1:{config.JSONRPC_PORT}/jsonrpc",
                                 json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": _AUTH})
    with _DIRECT.open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def http(path, method="GET", body=None, headers=None, port=config.DASHBOARD_PORT, timeout=10, host=None):
    """Request the dashboard; returns (status, headers, body)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if host:
        req.add_header("Host", host)
    try:
        with _DIRECT.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def helper(*args, wait=8.0):
    """Run the helper add-on inside Kodi and return its JSON answer."""
    try:
        os.remove(config.HELPER_OUT)
    except FileNotFoundError:
        pass
    rpc("Addons.ExecuteAddon", {"addonid": "script.tinyppi.testhelper", "params": list(args), "wait": False})
    deadline = time.time() + wait
    while time.time() < deadline:
        if os.path.exists(config.HELPER_OUT):
            time.sleep(0.1)
            with open(config.HELPER_OUT, encoding="utf-8") as handle:
                return json.load(handle)
        time.sleep(0.1)
    raise TimeoutError(f"the helper did not answer {args}")


def props(*names):
    """Read Home-window properties (in batches, the helper's argv is short)."""
    out = {}
    for start in range(0, len(names), 40):
        out.update(helper("props", *names[start:start + 40])["props"])
    return out


def set_settings(**values):
    """Write TinyPPI settings as the settings dialog would."""
    pairs = [f"{key}={'true' if v is True else 'false' if v is False else v}" for key, v in values.items()]
    for start in range(0, len(pairs), 20):
        helper("set", *pairs[start:start + 20])
    time.sleep(0.6)


def get_settings(*names):
    return helper("get", *names)["settings"]


def builtin(command):
    return helper("builtin", command)


def booleans(*conditions):
    return rpc("XBMC.GetInfoBooleans", {"booleans": list(conditions)})["result"]


def labels(*names):
    return rpc("XBMC.GetInfoLabels", {"labels": list(names)})["result"]


def window():
    return rpc("GUI.GetProperties", {"properties": ["currentwindow"]})["result"]["currentwindow"]


def xmlfile():
    return labels("Window.Property(xmlfile)")["Window.Property(xmlfile)"]


def player_id():
    return next((p["playerid"] for p in rpc("Player.GetActivePlayers")["result"] if p["type"] == "video"), None)


def player_props(*names):
    pid = player_id()
    if pid is None:
        return {}
    return rpc("Player.GetProperties", {"playerid": pid, "properties": list(names)})["result"]


def wait(predicate, timeout=10, step=0.25):
    """Poll *predicate* until it returns something true; None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception:
            pass
        time.sleep(step)
    return None


def play(path, timeout=40):
    """Play *path* and wait for fullscreen video (an audio device that times
    out keeps Kodi's busy dialog up for several seconds)."""
    rpc("Player.Open", {"item": {"file": path}})
    time.sleep(1)
    ok = wait(lambda: all(booleans("Window.IsActive(fullscreenvideo)", "Player.Playing").values()), timeout, 0.5)
    time.sleep(2)
    return bool(ok)


def stop():
    pid = player_id()
    if pid is not None:
        rpc("Player.Stop", {"playerid": pid})
        wait(lambda: not rpc("Player.GetActivePlayers")["result"], 15)
        time.sleep(1)


def shot(name):
    """Screenshot the virtual display into config.SHOTS."""
    os.makedirs(config.SHOTS, exist_ok=True)
    path = os.path.join(config.SHOTS, f"{name}.png")
    subprocess.run(["import", "-display", config.DISPLAY, "-window", "root", path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


# --- Profiles ---------------------------------------------------------------

def _addon_files(src):
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=src,
                            capture_output=True, text=True, check=True).stdout.split("\n")
    return [rel for rel in listed if rel and not rel.startswith(_NOT_INSTALLED)]


def install_tinyppi(home, ref=None):
    """Install TinyPPI into *home* from the checkout, or from git *ref*."""
    dest = os.path.join(home, ".kodi", "addons", "script.tinyppi")
    shutil.rmtree(dest, ignore_errors=True)
    if ref:
        archive = subprocess.run(["git", "archive", "--format=tar", ref], cwd=config.REPO,
                                 capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            members = [m for m in tar.getmembers() if not m.name.startswith(_NOT_INSTALLED)]
            tar.extractall(dest, members=members)
        return
    for rel in _addon_files(config.REPO):
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(config.REPO, rel), target)


def install_helper(home):
    dest = os.path.join(home, ".kodi", "addons", "script.tinyppi.testhelper")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper"), dest)


def make_home(name, ref=None, settings=TINYPPI_SETTINGS):
    """Return a fresh profile *name*: the template plus TinyPPI."""
    if not os.path.isdir(config.TEMPLATE):
        raise SystemExit("no profile template: run setup_profiles.py first")
    home = os.path.join(config.HOMES, name)
    shutil.rmtree(home, ignore_errors=True)
    shutil.copytree(config.TEMPLATE, home, symlinks=True)
    install_tinyppi(home, ref)
    data = os.path.join(home, ".kodi", "userdata", "addon_data", "script.tinyppi")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "settings.xml"), "w", encoding="utf-8") as handle:
        handle.write(settings)
    return home


def video_db(home):
    folder = os.path.join(home, ".kodi", "userdata", "Database")
    return os.path.join(folder, sorted(n for n in os.listdir(folder) if n.startswith("MyVideos"))[-1])


def scan_library(timeout=120):
    """Scan the video sources and wait for the scan to end."""
    rpc("VideoLibrary.Scan", {"showdialogs": False})
    time.sleep(2)
    wait(lambda: not booleans("Library.IsScanningVideo")["Library.IsScanningVideo"], timeout, 0.25)


# --- The process ------------------------------------------------------------

class Kodi:
    """One Kodi process (and its Xvfb display) on profile *home*."""

    def __init__(self, home):
        self.home = home
        self.log_path = os.path.join(home, ".kodi", "temp", "kodi.log")
        self.xvfb = None
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.quit()
        self.stop_display()

    def start(self, timeout=90):
        """Start Kodi; return the seconds until JSON-RPC answers."""
        if self.xvfb is None:
            self.xvfb = subprocess.Popen(["Xvfb", config.DISPLAY, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
        env = dict(os.environ, HOME=self.home, DISPLAY=config.DISPLAY, LIBGL_ALWAYS_SOFTWARE="1",
                   KODI_TEST_ROOT=config.ROOT)
        os.makedirs(config.ROOT, exist_ok=True)
        started = time.time()
        with open(os.path.join(config.ROOT, "kodi-stdout.log"), "a") as out:
            self.proc = subprocess.Popen([config.KODI_BIN, "--windowing=x11", "--standalone"], env=env,
                                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if rpc("JSONRPC.Ping", timeout=2).get("result") == "pong":
                    return time.time() - started
            except Exception:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"Kodi exited with {self.proc.returncode}")
            time.sleep(1)
        raise TimeoutError("Kodi did not answer JSON-RPC")

    def quit(self, timeout=60):
        """Quit Kodi; return the seconds it took, None if it had to be killed."""
        if self.proc is None or self.proc.poll() is not None:
            return 0.0
        started = time.time()
        try:
            rpc("Application.Quit", timeout=5)
        except Exception:
            pass
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
            return None
        return time.time() - started

    def stop_display(self):
        if self.xvfb:
            self.xvfb.terminate()
            self.xvfb.wait()
            self.xvfb = None

    def log(self, since=0):
        with open(self.log_path, encoding="utf-8", errors="replace") as handle:
            return handle.read()[since:]

    def log_size(self):
        return len(self.log())

    def wait_log(self, text, since=0, timeout=20):
        return wait(lambda: text in self.log(since), timeout, 0.3)


def enable(*addon_ids):
    for addon_id in addon_ids:
        rpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})


def set_path_content(home):
    """Give the two media sources their content type (no JSON-RPC for it)."""
    connection = sqlite3.connect(video_db(home))
    for path, content, recursive in ((f"{config.MEDIA}/movies/", "movies", 2147483647),
                                     (f"{config.MEDIA}/tv/", "tvshows", 0)):
        connection.execute("DELETE FROM path WHERE strPath = ?", (path,))
        connection.execute(
            "INSERT INTO path (strPath, strContent, strScraper, scanRecursive, useFolderNames,"
            " strSettings, noUpdate, exclude, allAudio) VALUES (?, ?, 'metadata.local', ?, 0, '', 0, 0, 0)",
            (path, content, recursive))
    connection.commit()
    connection.close()


def start_tinyppi(kodi, timeout=30):
    """Enable TinyPPI (Kodi leaves add-ons copied in disabled) and wait for
    its service and dashboard."""
    enable("script.tinyppi")
    return (kodi.wait_log("KodiMonitor started", 0, timeout)
            and kodi.wait_log("dashboard listening on", 0, timeout))


def require_coreelec_marker():
    """The overlay and the VS10 dialog open on CoreELEC only (see _preflight
    in ui/overlay.py); a desktop Kodi passes with an /etc/coreelec folder."""
    if not os.path.isdir("/etc/coreelec"):
        raise SystemExit("/etc/coreelec is missing: create it on the (throwaway) test machine, "
                         "e.g. 'sudo mkdir /etc/coreelec', so TinyPPI treats Kodi as CoreELEC")
