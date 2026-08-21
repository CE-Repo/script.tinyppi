"""The dashboard's HTTP server: a snapshot producer plus a small read-mostly
API served off the add-on's own port.

One producer thread builds a snapshot on a fixed cadence and every connected
browser is pushed the same one over Server-Sent Events, so five open tabs cost
what one costs -- the alternative, polling per request, would run the whole
side-data pass once per client per tick.

Routes are a fixed table, never a path resolved against the filesystem, and
everything that changes the player's state needs the token.  The server is off
until it is switched on in the add-on settings.
"""

import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import xbmc
import xbmcaddon
import xbmcvfs

from core.maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP, IMAX_LOGO_MAP
from web.snapshot import SnapshotBuilder, apply_command, apply_mode, art_path

_ADDON_ID = "script.tinyppi"

# How often the producer rebuilds the snapshot.  Five a second is well inside
# what a browser can paint and keeps the L1 luminance chart moving with the
# picture; the overlay's own 100ms cadence would only spend it on the wire.
_PRODUCE_INTERVAL = 0.2

# Seconds between heartbeat comments on an idle stream.  Without them a
# connection dropped by a router in between looks alive until the next change.
_HEARTBEAT_INTERVAL = 15.0

# Concurrent event streams.  Each holds a thread for as long as its tab is
# open, so the cap is what stops a forgotten phone from accumulating them.
_MAX_STREAMS = 6

# Longest request body accepted (only the two POSTs have one, and both are
# tiny).
_MAX_BODY = 4096

# The artwork kinds the page may ask for, and how big one may be before it is
# treated as something other than a poster.
_ART_KINDS = ("poster", "fanart")
_MAX_ART   = 8 * 1024 * 1024

# Artwork comes from wherever the library points, so its type is read off the
# name; anything unrecognised is sent as the JPEG that a poster almost always
# is, and the browser corrects itself from the bytes.
_ART_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}
_ART_FALLBACK_TYPE = "image/jpeg"

# Ambiguity-free alphabet: a token is read off a TV and typed on a phone.
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_LENGTH   = 8

_MIN_PORT, _MAX_PORT = 1024, 65535
_DEFAULT_PORT = 8099

# The page's own chrome, keyed the way its script names them.  Sent with
# /api/hello so the dashboard speaks whatever language Kodi is set to, the
# same as the row labels that travel with each snapshot.  Four of them are
# the overlay's own strings rather than new ones, so the two always agree on
# what a reading is called.
_UI_STRINGS = {
    "connected":     32448,
    "connecting":    32449,
    "offline":       32450,
    "idle_title":    32451,
    "idle_text":     32452,
    "peak":          32453,
    "average":       32454,
    "aspect":        32024,   # Aspect ratio
    "fps":           32140,   # FPS
    "chart":         32455,
    "active_area":   32030,   # L5 Active Area
    "vs10":          32467,
    "metadata":      32393,   # Dolby Vision metadata view
    "metadata_section": 32289,  # Metadata
    "no_metadata":      32470,
    "no_metadata_text": 32471,
    # The VS10 output the picture leaves on, not the audio row's sink,
    # which keeps #32055: one string cannot be translated for both.
    "output":        32057,   # Output (picture)
    "copy":          32456,
    "copied":        32457,
    "token_title":   32459,
    "token_text":    32460,
    "save":          32461,
    "cancel":        32462,
    "token_bad":     32463,
    "switching":     32464,
    "switched":      32465,
    "switch_failed": 32466,
    # The summary figures, history chart and transport row.
    "drops":         32476,
    "switches":      32478,
    "events":        32479,
    "events_empty":  32480,
    "range_1m":      32481,
    "range_10m":     32482,
    "range_all":     32483,
    "audio_track":   32484,
    "subtitles":     32485,
    "off":           32486,
    "volume":        32487,
    "mute":          32488,
    "playpause":     32489,
    "stop":          32490,
    "ev_mode":       32491,
    "ev_cache":      32492,
    "ev_drops":      32493,
    "controls":      32494,
    "metrics":       32495,
    # The theme button and the menu behind a long press on it.
    "theme_dark":      32496,
    "theme_adaptive":  32497,
    "theme_midnight":  32498,
    "theme_switch":    32499,
    "theme_menu":      32500,
    "tint_label":      32501,
    "tint_subtle":     32502,
    "tint_standard":   32503,
    "tint_strong":     32504,
}


def ui_strings(addon=None) -> dict[str, str]:
    """The page's chrome, localized through Kodi's own string table."""
    addon = addon or _addon()
    strings = {key: addon.getLocalizedString(string_id)
               for key, string_id in _UI_STRINGS.items()}
    # Yes and No are Kodi core strings, not entries in this add-on's table.
    # Asking Addon.getLocalizedString for 106/107 returns an empty string and
    # would erase the report values when the hello response reaches the page.
    strings["yes"] = xbmc.getLocalizedString(107) or "Yes"
    strings["no"] = xbmc.getLocalizedString(106) or "No"
    return strings


def _log(message: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"{_ADDON_ID} --> web: {message}", level=level)


# --- Settings --------------------------------------------------------------

def _addon() -> xbmcaddon.Addon:
    """A fresh Addon, so a setting changed while the service runs is seen."""
    return xbmcaddon.Addon()


def ensure_token(addon=None) -> str:
    """The dashboard's access token, generating one the first time it is
    needed so a freshly enabled server is never left unprotected."""
    addon = addon or _addon()
    token = (addon.getSetting("web_token") or "").strip()
    if not token:
        token = generate_token(addon)
    return token


def generate_token(addon=None) -> str:
    """Mint and store a new token, invalidating whatever was handed out
    before."""
    addon = addon or _addon()
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))
    addon.setSetting("web_token", token)
    return token


def configured_port(addon=None) -> int:
    """The configured port, falling back to the default for anything outside
    the range a non-root process may bind."""
    addon = addon or _addon()
    try:
        port = int(addon.getSetting("web_port") or _DEFAULT_PORT)
    except ValueError:
        return _DEFAULT_PORT
    return port if _MIN_PORT <= port <= _MAX_PORT else _DEFAULT_PORT


def local_address(port: int | None = None) -> str:
    """The URL to reach the dashboard on, as far as this box can tell.

    The route lookup opens no connection -- a UDP socket sends nothing on
    ``connect`` -- so it answers on a box with no internet just as well.
    """
    port = port or configured_port()
    host = ""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("203.0.113.1", 9))  # TEST-NET-3, never routed
            host = probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        host = ""
    if not host:
        host = xbmc.getInfoLabel("Network.IPAddress") or "<box-ip>"
    return f"http://{host}:{port}/"


# --- Static files ----------------------------------------------------------

def _web_root() -> str:
    return os.path.join(_addon().getAddonInfo("path"), "resources", "web")


def _addon_root() -> str:
    return _addon().getAddonInfo("path")


# Route -> (absolute path, content type).  Built once per server so a request
# can never name a file of its own: an unknown route is a 404, not a lookup.
def _static_routes() -> dict[str, tuple[str, str]]:
    web = _web_root()
    root = _addon_root()
    html = "text/html; charset=utf-8"
    return {
        "/":                      (os.path.join(web, "index.html"), html),
        "/index.html":            (os.path.join(web, "index.html"), html),
        # The Dolby Vision metadata list, opened in a window of its own from
        # the dashboard.  Both spellings answer, so a bookmark of either works.
        "/metadata":              (os.path.join(web, "metadata.html"), html),
        "/metadata.html":         (os.path.join(web, "metadata.html"), html),
        "/css/base.css":          (os.path.join(web, "css", "base.css"), "text/css; charset=utf-8"),
        "/css/live-panels.css":   (os.path.join(web, "css", "live-panels.css"), "text/css; charset=utf-8"),
        "/css/dashboard.css":     (os.path.join(web, "css", "dashboard.css"), "text/css; charset=utf-8"),
        "/css/metadata.css":      (os.path.join(web, "css", "metadata.css"), "text/css; charset=utf-8"),
        "/css/theme.css":         (os.path.join(web, "css", "theme.css"), "text/css; charset=utf-8"),
        "/js/core.js":            (os.path.join(web, "js", "core.js"), "text/javascript; charset=utf-8"),
        "/js/theme.js":           (os.path.join(web, "js", "theme.js"), "text/javascript; charset=utf-8"),
        "/js/cover-tint.js":      (os.path.join(web, "js", "cover-tint.js"), "text/javascript; charset=utf-8"),
        "/js/live-panels.js":     (os.path.join(web, "js", "live-panels.js"), "text/javascript; charset=utf-8"),
        "/js/dashboard.js":       (os.path.join(web, "js", "dashboard.js"), "text/javascript; charset=utf-8"),
        "/js/metadata.js":        (os.path.join(web, "js", "metadata.js"), "text/javascript; charset=utf-8"),
        "/icons/chevron-down.svg": (os.path.join(web, "icons", "chevron-down.svg"), "image/svg+xml"),
        "/icons/download.svg":    (os.path.join(web, "icons", "download.svg"), "image/svg+xml"),
        "/icons/key.svg":         (os.path.join(web, "icons", "key.svg"), "image/svg+xml"),
        "/icons/play.svg":        (os.path.join(web, "icons", "play.svg"), "image/svg+xml"),
        "/icons/pause.svg":       (os.path.join(web, "icons", "pause.svg"), "image/svg+xml"),
        "/icons/stop.svg":        (os.path.join(web, "icons", "stop.svg"), "image/svg+xml"),
        "/icons/volume.svg":      (os.path.join(web, "icons", "volume.svg"), "image/svg+xml"),
        "/icons/volume-muted.svg": (os.path.join(web, "icons", "volume-muted.svg"), "image/svg+xml"),
        "/icons/yes.svg":         (os.path.join(web, "icons", "yes.svg"), "image/svg+xml"),
        "/icons/no.svg":          (os.path.join(web, "icons", "no.svg"), "image/svg+xml"),
        "/icons/theme-dark.svg":  (os.path.join(web, "icons", "theme-dark.svg"), "image/svg+xml"),
        "/icons/theme-adaptive.svg": (os.path.join(web, "icons", "theme-adaptive.svg"), "image/svg+xml"),
        "/icons/theme-midnight.svg": (os.path.join(web, "icons", "theme-midnight.svg"), "image/svg+xml"),
        "/manifest.webmanifest":  (os.path.join(web, "manifest.webmanifest"), "application/manifest+json"),
        "/icon.jpg":              (os.path.join(root, "icon.jpg"), "image/jpeg"),
        "/fanart.jpg":            (os.path.join(root, "fanart.jpg"), "image/jpeg"),
        **_media_routes(root),
    }


def _media_routes(root: str) -> dict[str, tuple[str, str]]:
    """The skin graphics the dashboard draws, as routes under ``/media/``.

    Built from the very maps the overlay picks its logos out of, so a format
    wears the same face on the TV and on the phone.  Naming them here keeps the
    route table what it was: an allowlist of files the add-on itself would
    draw, never a path that came in with a request.  A logo that is not
    installed -- the IMAX ones ship separately -- is simply not a route.
    """
    media = os.path.join(root, "resources", "skins", "Default", "media")
    names = set(HDR_LOGO_MAP.values())
    names |= set(AUDIO_LOGO_MAP.values())
    names |= set(IMAX_LOGO_MAP.values())

    routes = {}
    for name in sorted(names):
        path = os.path.join(media, name.replace("/", os.sep))
        if name and os.path.exists(path):
            routes[f"/media/{name}"] = (path, "image/png")
    return routes


# --- Artwork ---------------------------------------------------------------

def _unwrap_image_url(path: str) -> str:
    """The real file behind a Kodi ``image://`` address.

    Kodi wraps art in a texture URL -- ``image://`` plus the source, percent
    encoded, plus a trailing slash.  The wrapper is a name for its own texture
    cache and not something the file system knows, so it is unwrapped back to
    the path or URL the library actually points at.
    """
    if not path.startswith("image://"):
        return path
    inner = unquote(path[len("image://"):])
    return inner[:-1] if inner.endswith("/") else inner


def _art_type(path: str) -> str:
    return _ART_TYPES.get(os.path.splitext(path)[1].lower(), _ART_FALLBACK_TYPE)


def _read_art(path: str) -> bytes | None:
    """Read an artwork file through Kodi's own VFS, or None.

    Kodi's VFS rather than ``open``: art lives wherever the library put it,
    which is as often a share or a URL as it is a local file, and only Kodi
    knows how to reach all three.
    """
    handle = None
    try:
        handle = xbmcvfs.File(path)
        data = bytes(handle.readBytes(_MAX_ART))
    except Exception:
        return None
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
    return data or None


# --- The server ------------------------------------------------------------

class _Producer(threading.Thread):
    """Builds the snapshot on a fixed cadence and wakes the streams waiting
    on it."""

    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__(name="TinyPPI-web-producer", daemon=True)
        self._stop      = stop_event
        self._builder   = SnapshotBuilder()
        self._condition = threading.Condition()
        self._snapshot: dict = {"seq": 0, "playing": False, "groups": [], "metrics": {}}
        self._failed    = False

    def wake(self) -> None:
        """Release every waiting stream at once, used on shutdown."""
        with self._condition:
            self._condition.notify_all()

    @property
    def snapshot(self) -> dict:
        with self._condition:
            return self._snapshot

    def history(self) -> dict:
        """The playing title's chart samples and events.

        Reached straight from the request thread: the session keeps a lock of
        its own, which is cheaper than holding up the producer for a list that
        is only asked for when a page opens or an event lands.
        """
        return self._builder.session.history()

    def wait_for(self, seen: int, timeout: float) -> dict | None:
        """Block until a snapshot newer than ``seen`` exists, or the timeout
        runs out (then None, and the caller sends a heartbeat)."""
        with self._condition:
            if self._snapshot.get("seq", 0) > seen:
                return self._snapshot
            self._condition.wait(timeout)
            snapshot = self._snapshot
        return snapshot if snapshot.get("seq", 0) > seen else None

    def run(self) -> None:
        monitor = xbmc.Monitor()
        while not self._stop.is_set() and not monitor.abortRequested():
            try:
                addon = _addon()
                snapshot = self._builder.build(
                    addon,
                    allow_filename=addon.getSetting("filename") == "true",
                    metadata=addon.getSetting("web_metadata") == "true",
                    control=addon.getSetting("web_allow_control") == "true",
                )
                with self._condition:
                    self._snapshot = snapshot
                    self._condition.notify_all()
            except Exception as exc:  # never let one bad pass end the stream
                self._log_failure(exc)
            if monitor.waitForAbort(_PRODUCE_INTERVAL):
                break
        with self._condition:
            self._condition.notify_all()

    def _log_failure(self, exc: Exception) -> None:
        """Log a failed pass once, so a persistent fault leaves one line in
        the log rather than five a second."""
        if self._failed:
            return
        self._failed = True
        _log(f"snapshot failed, continuing with the last one: {exc}",
             xbmc.LOGWARNING)


class _Handler(BaseHTTPRequestHandler):
    """The route table.  ``server`` carries the producer, the token and the
    static-file map."""

    protocol_version = "HTTP/1.1"
    server_version   = "TinyPPI"
    sys_version      = ""

    # -- plumbing --

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - base API
        _log(fmt % args, xbmc.LOGDEBUG)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              extra: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The dashboard is the live state of a player; nothing here may be
        # replayed from a cache.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    # -- auth --

    def _presented_token(self) -> str:
        header = self.headers.get("X-TinyPPI-Token", "")
        if header:
            return header.strip()
        query = parse_qs(urlparse(self.path).query)
        return (query.get("token") or [""])[0].strip()

    def _authorised(self) -> bool:
        expected = self.server.token
        presented = self._presented_token()
        # compare_digest over equal-length ASCII; a wrong length is a
        # mismatch either way.
        return len(presented) == len(expected) and secrets.compare_digest(
            presented, expected
        )

    # -- routing --

    def do_GET(self) -> None:  # noqa: N802 - base API
        route = urlparse(self.path).path
        if route in self.server.static_routes:
            self._serve_static(route)
            return
        if route in ("/api/state", "/api/stream", "/api/history", "/api/art"):
            if self.server.auth_read and not self._authorised():
                self._send_error_json(HTTPStatus.UNAUTHORIZED, "token required")
                return
            if route == "/api/state":
                self._send_json(self._state_payload())
            elif route == "/api/history":
                # The chart's whole past and the event list, asked for on
                # connect and again whenever the snapshot's event count moves.
                self._send_json(self.server.producer.history())
            elif route == "/api/art":
                self._serve_art()
            else:
                self._serve_stream()
            return
        if route == "/api/hello":
            # Deliberately unauthenticated: it carries no player state, only
            # what the page needs to know before it can ask for any.
            addon = _addon()
            self._send_json({
                "name":        "TinyPPI",
                "version":     addon.getAddonInfo("version"),
                "auth_read":   self.server.auth_read,
                "control":     self.server.allow_control,
                "interval_ms": int(_PRODUCE_INTERVAL * 1000),
                "strings":     ui_strings(addon),
            })
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")

    def do_POST(self) -> None:  # noqa: N802 - base API
        # The body is read first, whatever the request turns out to be: on a
        # kept-alive HTTP/1.1 connection an unread body is parsed as the next
        # request line, so a rejected POST would corrupt the one after it.
        payload = self._read_json_body()
        if payload is None:
            return

        route = urlparse(self.path).path
        if route not in ("/api/mode", "/api/command"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")
            return
        if not self.server.allow_control:
            self._send_error_json(HTTPStatus.FORBIDDEN, "control disabled")
            return
        # Writing always needs the token, whatever reading is set to.
        if not self._authorised():
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "token required")
            return

        if route == "/api/mode":
            mode = str(payload.get("mode", "")).strip()
            if not apply_mode(mode):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "unknown mode")
                return
            _log(f"VS10 mode '{mode}' requested from {self.client_address[0]}")
            self._send_json({"ok": True, "mode": mode})
            return

        action = str(payload.get("action", "")).strip()
        if not apply_command(action, payload.get("value")):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "command failed")
            return
        # A seek or a volume nudge arrives by the dozen while a finger is on
        # the slider; only the ones that change what the player is doing are
        # worth a line at the level a normal log keeps.
        _log(f"'{action}' requested from {self.client_address[0]}",
             xbmc.LOGDEBUG if action in ("seek", "seek_percent", "volume")
             else xbmc.LOGINFO)
        self._send_json({"ok": True, "action": action})

    def _read_json_body(self) -> dict | None:
        """The request body as a dict, or None once an error has been sent."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "bad body length")
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "bad JSON")
            return None
        if not isinstance(payload, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "bad JSON")
            return None
        return payload

    # -- responses --

    def _state_payload(self) -> dict:
        payload = dict(self.server.producer.snapshot)
        payload["control"] = self.server.allow_control
        return payload

    def _serve_art(self) -> None:
        """Send the poster or the fanart of what is playing."""
        query = parse_qs(urlparse(self.path).query)
        kind = (query.get("kind") or [""])[0]
        if kind not in _ART_KINDS:
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such artwork")
            return
        found = self.server.artwork(kind)
        if found is None:
            # Not every film has a poster, and a library-less file has none at
            # all; the page hides the frame rather than showing a broken one.
            self._send_error_json(HTTPStatus.NOT_FOUND, "no artwork")
            return
        body, content_type = found
        self._send(HTTPStatus.OK, body, content_type)

    def _serve_static(self, route: str) -> None:
        path, content_type = self.server.static_routes[route]
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "missing file")
            return
        self._send(HTTPStatus.OK, body, content_type)

    def _serve_stream(self) -> None:
        """Push snapshots as Server-Sent Events until the client leaves or the
        service shuts down."""
        if not self.server.claim_stream():
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, "too many streams")
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            # Nothing between here and the browser may buffer a stream whose
            # point is that it arrives as it happens.
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._stream_loop()
        except (OSError, ValueError):
            pass  # the client went away; nothing to report
        finally:
            self.server.release_stream()

    def _stream_loop(self) -> None:
        producer = self.server.producer
        stop     = self.server.stop_event
        seen     = -1
        last_beat = time.monotonic()
        # A write to a client that has gone quiet must not hold the thread for
        # good; the timeout turns it into the OSError the caller treats as a
        # closed connection.
        self.connection.settimeout(_HEARTBEAT_INTERVAL * 2)

        while not stop.is_set():
            snapshot = producer.wait_for(seen, _HEARTBEAT_INTERVAL)
            if stop.is_set():
                break
            now = time.monotonic()
            if snapshot is None:
                if now - last_beat >= _HEARTBEAT_INTERVAL:
                    last_beat = now
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                continue
            seen = snapshot.get("seq", 0)
            last_beat = now
            payload = dict(snapshot)
            payload["control"] = self.server.allow_control
            data = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"event: state\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

        self.wfile.write(b"event: bye\ndata: {}\n\n")
        self.wfile.flush()


class _Server(ThreadingHTTPServer):
    """Threading HTTP server carrying the dashboard's shared state."""

    daemon_threads      = True
    allow_reuse_address = True

    def __init__(self, address, producer: _Producer, stop_event: threading.Event,
                 token: str) -> None:
        super().__init__(address, _Handler)
        self.producer      = producer
        self.stop_event    = stop_event
        self.token         = token
        self.static_routes = _static_routes()
        self.auth_read     = False
        self.allow_control = True
        self._streams      = 0
        self._stream_lock  = threading.Lock()
        # One picture per kind, kept between requests: every open tab asks for
        # the same poster, and it can be a megabyte off a share.
        self._art: dict[str, tuple[str, bytes, str]] = {}
        self._art_lock = threading.Lock()

    def refresh_settings(self, addon=None) -> None:
        """Re-read the settings a request consults, so toggling one applies
        without restarting the server."""
        addon = addon or _addon()
        self.auth_read     = addon.getSetting("web_auth_read") == "true"
        self.allow_control = addon.getSetting("web_allow_control") == "true"

    def artwork(self, kind: str) -> tuple[bytes, str] | None:
        """The artwork bytes and type for ``kind``, or None when there is none.

        Read once per picture rather than once per request: the film only
        changes with the film.  The read happens outside the lock, so a poster
        coming off a slow share holds nothing else up -- two requests racing
        for the same new picture read it twice and agree on the answer.
        """
        path = art_path(kind)
        if not path:
            return None

        with self._art_lock:
            cached = self._art.get(kind)
            if cached is not None and cached[0] == path:
                return cached[1], cached[2]

        source = _unwrap_image_url(path)
        data = _read_art(source)
        if data is None and source != path:
            data = _read_art(path)   # an address only Kodi's VFS understands
        if data is None:
            return None

        content_type = _art_type(source)
        with self._art_lock:
            self._art[kind] = (path, data, content_type)
        return data, content_type

    def claim_stream(self) -> bool:
        with self._stream_lock:
            if self._streams >= _MAX_STREAMS:
                return False
            self._streams += 1
            return True

    def release_stream(self) -> None:
        with self._stream_lock:
            self._streams = max(0, self._streams - 1)

    def handle_error(self, request, client_address) -> None:
        """A client that hangs up mid-response is routine and stays at debug;
        anything else is a real fault and is logged with its traceback, since
        a swallowed one here would show up only as a dead connection."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            _log(f"connection from {client_address[0]} ended early", xbmc.LOGDEBUG)
            return
        _log(f"request from {client_address[0]} failed:\n"
             f"{traceback.format_exc()}", xbmc.LOGERROR)


class WebDashboard:
    """Owns the server's lifecycle: start it, restart it when its settings
    change, stop it when Kodi shuts down."""

    def __init__(self) -> None:
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._producer: _Producer | None = None
        self._stop: threading.Event | None = None
        self._port  = 0
        self._token = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    def apply_settings(self) -> None:
        """Bring the server in line with the settings: start, stop, or restart
        it on a port or token change, and pick up the rest in place."""
        addon   = _addon()
        enabled = addon.getSetting("web_enabled") == "true"

        if not enabled:
            self.stop()
            return

        port  = configured_port(addon)
        token = ensure_token(addon)

        if self.running and (port != self._port or token != self._token):
            _log("port or token changed, restarting")
            self.stop()

        if not self.running:
            self.start(port, token)
        elif self._server is not None:
            self._server.refresh_settings(addon)

    def start(self, port: int, token: str) -> None:
        if self.running:
            return
        self._stop     = threading.Event()
        self._producer = _Producer(self._stop)
        try:
            server = _Server(("0.0.0.0", port), self._producer, self._stop, token)
        except OSError as exc:
            _log(f"cannot bind port {port}: {exc}", xbmc.LOGERROR)
            self._stop = None
            self._producer = None
            return

        server.refresh_settings()
        self._server = server
        self._port   = port
        self._token  = token
        self._producer.start()
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="TinyPPI-web-server",
            daemon=True,
        )
        self._thread.start()
        _log(f"dashboard listening on {local_address(port)}")

    def stop(self) -> None:
        if not self.running:
            return
        _log("stopping dashboard")
        # Signalled first: the event streams check it between snapshots, so
        # they unwind on their own instead of holding the shutdown.
        if self._stop is not None:
            self._stop.set()
        if self._producer is not None:
            self._producer.wake()
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread   = None
        self._producer = None
        self._stop     = None
        self._port     = 0
        self._token    = ""
