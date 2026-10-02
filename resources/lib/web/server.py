# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's HTTP server and its lifecycle.

A producer thread builds snapshots that are pushed to every browser via
Server-Sent Events (web/producer.py).  Routes live in web/routes.py, delta
frames in web/delta.py, artwork in web/artwork.py and the page's files in
web/static.py.  Routes are a fixed table, never a filesystem lookup; every
state change needs the token.  The server is off unless enabled.
"""

import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer

import xbmc
import xbmcaddon

from core import settings
from core.log import channel
from web import access, artwork, library, static
from web.producer import Producer
from web.routes import Handler

# Maximum concurrent event streams (each holds a thread while its tab is
# open).
_MAX_STREAMS = 6

# Maximum open connections, in all and per address.  Each holds a thread,
# for up to _REQUEST_TIMEOUT (web/routes.py) while idle; a browser opens six
# at most per host, so this leaves room for several devices while one cannot
# pile up threads on the box.
_MAX_CONNECTIONS = 48
_MAX_PER_ADDRESS = 16

# Seconds between two log lines about refused connections.
_REFUSAL_LOG_INTERVAL = 60.0

# Total time stop() waits for all threads, as one deadline: separate
# timeouts added up to more than Kodi's five seconds per script.
_JOIN_TIMEOUT = 3.0

# Part of that for request threads to finish an answer or a stream's
# parting frame before their connections are cut off.
_HANGUP_GRACE = 0.5

# Ambiguity-free alphabet: a token is read off a TV and typed on a phone.
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_LENGTH   = 8

_MIN_PORT, _MAX_PORT = 1024, 65535
_DEFAULT_PORT = 8099


_log = channel("web", xbmc.LOGINFO)


# --- Settings --------------------------------------------------------------

def _addon() -> xbmcaddon.Addon:
    """Return the current settings handle (see ``core.settings``)."""
    return settings.addon()


def ensure_token(addon=None) -> str:
    """Return the access token, generating one when none exists yet."""
    addon = addon or _addon()
    token = (addon.getSetting("web_token") or "").strip()
    if not token:
        token = generate_token(addon)
    return token


def generate_token(addon=None) -> str:
    """Generate and store a new token, invalidating the old one."""
    addon = addon or _addon()
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))
    addon.setSetting("web_token", token)
    return token


def configured_port(addon=None) -> int:
    """Return the configured port, or the default outside 1024-65535."""
    addon = addon or _addon()
    try:
        port = int(addon.getSetting("web_port") or _DEFAULT_PORT)
    except ValueError:
        return _DEFAULT_PORT
    return port if _MIN_PORT <= port <= _MAX_PORT else _DEFAULT_PORT


def local_address(port: int | None = None) -> str:
    """Return the dashboard URL as far as this box can tell.

    The UDP route lookup sends nothing, so it works without internet.
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


# --- The server ------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    """Threading HTTP server carrying the dashboard's shared state."""

    daemon_threads      = True
    allow_reuse_address = True

    def __init__(self, address, producer: Producer, stop_event: threading.Event,
                 token: str) -> None:
        super().__init__(address, Handler)
        self.producer      = producer
        self.stop_event    = stop_event
        self.token         = token
        self.static_routes = static.routes()
        self.static_files  = static.StaticFiles()
        # Wrong-token tracking and lockouts.
        self.guesses       = access.Guesses()
        self.auth_read     = False
        self.allow_control = True
        self.offer_library = True
        self.offer_series  = True
        self._streams      = 0
        self._stream_lock  = threading.Lock()
        # Request threads, joined in stop(): Kodi waits for every thread of
        # the interpreter, daemon or not.
        self._workers      = set()
        self._worker_lock  = threading.Lock()
        # Open connections and their addresses, so stop() can hang up on
        # idle keep-alives and verify_request() can cap them.
        self._connections: dict = {}
        self._refusal_logged = 0.0
        # Cached poster and fanart of the playing title.
        self._art = artwork.PlayingArtwork()

    def verify_request(self, request, client_address) -> bool:
        """Refuse connections once shutdown has begun or over the caps.

        Checked before a thread is started, so reconnecting pages cannot
        delay Kodi's shutdown, and one device cannot fill the box with
        threads (see ``_MAX_CONNECTIONS``).
        """
        if self.stop_event.is_set():
            return False
        address = client_address[0]
        with self._worker_lock:
            total = len(self._connections)
            mine = sum(1 for held in self._connections.values()
                       if held == address)
            if total < _MAX_CONNECTIONS and mine < _MAX_PER_ADDRESS:
                return True
            now = time.monotonic()
            quiet = now - self._refusal_logged >= _REFUSAL_LOG_INTERVAL
            if quiet:
                self._refusal_logged = now
        if quiet:
            _log(f"refusing a connection from {address}: {mine} open from it, "
                 f"{total} in all", xbmc.LOGWARNING)
        return False

    def process_request(self, request, client_address) -> None:
        # Registered on the accept loop, so the table is complete once
        # shutdown() has returned.
        with self._worker_lock:
            self._connections[request] = client_address[0]
        super().process_request(request, client_address)

    def shutdown_request(self, request) -> None:
        # Removed under the lock before closing, so close_connections()
        # never touches a closed socket.
        with self._worker_lock:
            self._connections.pop(request, None)
        super().shutdown_request(request)

    def close_connections(self, how: int = socket.SHUT_RD) -> int:
        """Shut down all open connections and return their count.

        An idle keep-alive thread waits in a read for up to
        _REQUEST_TIMEOUT, longer than Kodi allows.  ``SHUT_RD`` ends the read
        while answers and a stream's parting frame still go out;
        ``SHUT_RDWR`` also cuts off a write to a browser that stopped reading.
        """
        with self._worker_lock:
            connections = list(self._connections)
            for connection in connections:
                try:
                    connection.shutdown(how)
                except OSError:
                    pass
        return len(connections)

    def process_request_thread(self, request, client_address) -> None:
        worker = threading.current_thread()
        with self._worker_lock:
            self._workers.add(worker)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._worker_lock:
                self._workers.discard(worker)

    def join_workers(self, timeout: float) -> int:
        """Wait for the request threads; return how many are still running."""
        deadline = time.monotonic() + timeout
        with self._worker_lock:
            workers = list(self._workers)
        for worker in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(remaining)
        return sum(1 for worker in workers if worker.is_alive())

    def refresh_settings(self, addon=None) -> None:
        """Re-read the request-related settings without a restart."""
        addon = addon or _addon()
        self.auth_read     = addon.getSetting("web_auth_read") == "true"
        self.allow_control = addon.getSetting("web_allow_control") == "true"
        self.offer_library = addon.getSetting("web_library") == "true"
        self.offer_series  = addon.getSetting("web_series") == "true"

    def artwork(self, kind: str) -> tuple[bytes, str] | None:
        """Return the playing title's poster or fanart, or None."""
        return self._art.get(kind)

    def library_artwork(self, movie_id: str, kind: str) -> tuple[bytes, str] | None:
        """Return a library film's poster, or None.

        Not cached here (a library has thousands); the browser caches them
        as immutable (see artwork.CACHE) and loads them as they scroll in.
        """
        if not (self.offer_library and self.allow_control):
            return None
        try:
            path = library.art_path(int(movie_id), kind)
        except (TypeError, ValueError):
            return None
        return artwork.shelf_picture(path)

    def series_artwork(self, show_id: str, kind: str) -> tuple[bytes, str] | None:
        """Return a series poster, or None."""
        if not (self.offer_series and self.allow_control):
            return None
        return artwork.shelf_picture(library.show_art_path(show_id, kind))

    def episode_artwork(self, episode_id: str, kind: str) -> tuple[bytes, str] | None:
        """Return an episode still, or None.

        Only episodes of opened series are known (see web/library.py).
        """
        if not (self.offer_series and self.allow_control):
            return None
        return artwork.shelf_picture(library.episode_art_path(episode_id, kind))

    @property
    def streams_full(self) -> bool:
        with self._stream_lock:
            return self._streams >= _MAX_STREAMS

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
        """Log request errors: hang-ups at debug, real faults with traceback."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            _log(f"connection from {client_address[0]} ended early", xbmc.LOGDEBUG)
            return
        _log(f"request from {client_address[0]} failed:\n"
             f"{traceback.format_exc()}", xbmc.LOGERROR)


class WebDashboard:
    """Start, restart and stop the dashboard server."""

    def __init__(self) -> None:
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._producer: Producer | None = None
        self._stop: threading.Event | None = None
        self._port  = 0
        self._token = ""
        # Settings callbacks arrive on another thread (also during shutdown);
        # the lock keeps them from restarting a server being stopped.
        self._lock  = threading.RLock()
        self._done  = False

    @property
    def running(self) -> bool:
        return self._server is not None

    def apply_settings(self) -> None:
        with self._lock:
            self._apply_settings()

    def _apply_settings(self) -> None:
        """Apply the settings: start, stop, restart on port or token change,
        or update the rest in place."""
        if self._done:
            # Stopped for good; ignore late settings callbacks.
            return

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
        if self.running or self._done:
            return
        self._stop     = threading.Event()
        self._producer = Producer(self._stop)
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
            # Short poll, so shutdown() returns quickly.
            kwargs={"poll_interval": 0.1},
            name="TinyPPI-web-server",
            daemon=True,
        )
        self._thread.start()
        _log(f"dashboard listening on {local_address(port)}")

    def stop(self, final: bool = False) -> None:
        """Stop the server and leave no thread running.

        Kodi raises SystemExit five seconds into a script's shutdown, so every
        step is guarded and the important ones come first: close the
        listening socket (reconnects would create new threads), then hang up
        on open connections.
        """
        with self._lock:
            if final:
                self._done = True

            server   = self._server
            thread   = self._thread
            producer = self._producer
            stop     = self._stop

            self._server   = None
            self._thread   = None
            self._producer = None
            self._stop     = None
            self._port     = 0
            self._token    = ""

            if server is None and producer is None:
                return
            _log("stopping dashboard")

            # First: streams and verify_request react to this flag.
            if stop is not None:
                stop.set()
            if producer is not None:
                producer.wake()

            if server is not None:
                # End the accept loop, then always close the listening socket.
                try:
                    server.shutdown()
                except Exception as exc:
                    _log(f"server shutdown failed: {exc}", xbmc.LOGWARNING)
                finally:
                    try:
                        server.server_close()
                    except Exception as exc:
                        _log(f"server close failed: {exc}", xbmc.LOGWARNING)
                    # No new connections now; end the idle reads at once.
                    try:
                        server.close_connections()
                    except Exception as exc:
                        _log(f"closing connections failed: {exc}",
                             xbmc.LOGWARNING)

            # Then wait for the threads, with one shared deadline.
            deadline = time.monotonic() + _JOIN_TIMEOUT

            def remaining() -> float:
                return max(0.0, deadline - time.monotonic())

            if thread is not None:
                thread.join(timeout=remaining())
                if thread.is_alive():
                    _log("web server thread did not stop", xbmc.LOGWARNING)
            if producer is not None:
                producer.join(timeout=remaining())
                if producer.is_alive():
                    _log("snapshot producer did not stop", xbmc.LOGWARNING)
            if server is not None:
                # A thread still running after the grace period is stuck
                # writing; cut its connection off.
                left = server.join_workers(min(remaining(), _HANGUP_GRACE))
                if left:
                    try:
                        server.close_connections(socket.SHUT_RDWR)
                    except Exception as exc:
                        _log(f"closing connections failed: {exc}",
                             xbmc.LOGWARNING)
                    left = server.join_workers(remaining())
                if left:
                    _log(f"{left} request thread(s) still running",
                         xbmc.LOGWARNING)
