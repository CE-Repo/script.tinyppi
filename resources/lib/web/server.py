# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's HTTP server: a snapshot producer plus a small read-mostly
API served off the add-on's own port.

One producer thread builds a snapshot on a fixed cadence and every connected
browser is pushed the same one over Server-Sent Events (see web/producer.py).
The routes are in web/routes.py, the delta frames in web/delta.py, the artwork
in web/artwork.py and the page's own files in web/static.py; this module owns
the server's lifecycle and the settings it is started from.

Routes are a fixed table, never a path resolved against the filesystem, and
everything that changes the player's state needs the token.  The server is off
until it is switched on in the add-on settings.
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

# Concurrent event streams.  Each holds a thread for as long as its tab is
# open, so the cap is what stops a forgotten phone from accumulating them.
_MAX_STREAMS = 6

# How long stop() waits, in all, for the threads it asked to finish.  One
# deadline for the accept loop, the producer and the request threads together:
# a timeout of their own each added up to more than the five seconds Kodi
# allows the whole script.  Past this the add-on has done what it can and
# holding the service script open any longer only makes the shutdown worse.
_JOIN_TIMEOUT = 3.0

# How long, of that, the request threads get to finish an answer or a stream's
# parting frame before their connections are cut off outright.
_HANGUP_GRACE = 0.5

# Ambiguity-free alphabet: a token is read off a TV and typed on a phone.
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_LENGTH   = 8

_MIN_PORT, _MAX_PORT = 1024, 65535
_DEFAULT_PORT = 8099


_log = channel("web", xbmc.LOGINFO)


# --- Settings --------------------------------------------------------------

def _addon() -> xbmcaddon.Addon:
    """The settings in force right now, so a setting changed while the service
    runs is seen (see ``core.settings``)."""
    return settings.addon()


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
        # Who has been presenting wrong tokens, and who is shut out for it.
        self.guesses       = access.Guesses()
        self.auth_read     = False
        self.allow_control = True
        self.offer_library = True
        self.offer_series  = True
        self._streams      = 0
        self._stream_lock  = threading.Lock()
        # Every thread this server has handed a connection to.  Kodi waits on
        # thread states, not on the daemon flag, so these have to be joined
        # before the service script returns rather than left to the
        # interpreter that Kodi never gets round to tearing down.
        self._workers      = set()
        self._worker_lock  = threading.Lock()
        # Every connection a request thread is holding, so stop() can hang up
        # on them instead of waiting out a browser's idle keep-alive.
        self._connections  = set()
        # The playing title's poster and fanart, kept between requests.
        self._art = artwork.PlayingArtwork()

    def verify_request(self, request, client_address) -> bool:
        """Turn away a connection once the shutdown has begun.

        Checked before the request is handed to a thread, so a page that
        reconnects while Kodi is stopping costs a closed socket rather than a
        new thread -- and Kodi's wait for the interpreter's threads can
        actually finish.
        """
        return not self.stop_event.is_set()

    def process_request(self, request, client_address) -> None:
        # Registered here, on the accept loop, rather than in the thread: once
        # shutdown() has returned the set is complete, and close_connections()
        # cannot miss a thread that had not got round to adding itself.
        with self._worker_lock:
            self._connections.add(request)
        super().process_request(request, client_address)

    def shutdown_request(self, request) -> None:
        # Out of the set before the socket is closed, under the lock
        # close_connections() holds, so it never acts on a closed socket.
        with self._worker_lock:
            self._connections.discard(request)
        super().shutdown_request(request)

    def close_connections(self, how: int = socket.SHUT_RD) -> int:
        """Hang up on every connection still open, and report how many.

        A browser keeps its connection open between requests, and the thread
        holding it sits in a read until _REQUEST_TIMEOUT -- three times what
        Kodi allows the whole script to stop in.  Shutting the socket down for
        reading ends that read at once while an answer, or a stream's parting
        frame, still goes out; ``SHUT_RDWR`` also cuts off a write into a
        browser that has stopped reading.
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
        """Wait for the request threads to finish, and report how many are
        still running when the time is up."""
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
        """Re-read the settings a request consults, so toggling one applies
        without restarting the server."""
        addon = addon or _addon()
        self.auth_read     = addon.getSetting("web_auth_read") == "true"
        self.allow_control = addon.getSetting("web_allow_control") == "true"
        self.offer_library = addon.getSetting("web_library") == "true"
        self.offer_series  = addon.getSetting("web_series") == "true"

    def artwork(self, kind: str) -> tuple[bytes, str] | None:
        """The poster or fanart of what is playing, or None (see
        ``artwork.PlayingArtwork``)."""
        return self._art.get(kind)

    def library_artwork(self, movie_id: str, kind: str) -> tuple[bytes, str] | None:
        """The poster of one of the library's films, or None.

        Nothing is held here, unlike the playing title's own artwork: a card
        of a thousand posters is a thousand pictures, and keeping them would
        cost the add-on more memory than everything else it does put together.
        The browser is the one that keeps them, and it keeps them well -- the
        address carries the picture's own tag and is answered with a week and
        an immutable, so each poster crosses the network once (see
        artwork.CACHE).  A card only asks for the posters it is showing anyway:
        the rest are fetched as they are scrolled to.
        """
        if not (self.offer_library and self.allow_control):
            return None
        try:
            path = library.art_path(int(movie_id), kind)
        except (TypeError, ValueError):
            return None
        return artwork.shelf_picture(path)

    def series_artwork(self, show_id: str, kind: str) -> tuple[bytes, str] | None:
        """The poster of one of the series on the shelf, or None."""
        if not (self.offer_series and self.allow_control):
            return None
        return artwork.shelf_picture(library.show_art_path(show_id, kind))

    def episode_artwork(self, episode_id: str, kind: str) -> tuple[bytes, str] | None:
        """The still of one episode, or None.

        Only episodes of a series somebody has opened have a still to hand out:
        the rest have never been read, and an address for one of them cannot
        have reached a browser (see web/library.py).
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
        self._producer: Producer | None = None
        self._stop: threading.Event | None = None
        self._port  = 0
        self._token = ""
        # Kodi saves its settings on the way out, and the settings callback
        # arrives on a thread of its own: without this lock a change landing
        # while the service is stopping could start the server back up behind
        # the shutdown and leave a listening socket nobody owns.
        self._lock  = threading.RLock()
        self._done  = False

    @property
    def running(self) -> bool:
        return self._server is not None

    def apply_settings(self) -> None:
        with self._lock:
            self._apply_settings()

    def _apply_settings(self) -> None:
        """Bring the server in line with the settings: start, stop, or restart
        it on a port or token change, and pick up the rest in place."""
        if self._done:
            # Stopped for good; a late settings callback must not undo that.
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
            # Polled often enough that shutdown() returns promptly: this wait
            # is spent inside the five seconds Kodi gives the script to stop.
            kwargs={"poll_interval": 0.1},
            name="TinyPPI-web-server",
            daemon=True,
        )
        self._thread.start()
        _log(f"dashboard listening on {local_address(port)}")

    def stop(self, final: bool = False) -> None:
        """Close the server down and leave no thread of it running.

        Every step is guarded, and the ones that matter most come first: Kodi
        allows a service script five seconds to stop and then raises
        SystemExit in it, so anything skipped here is skipped for good.  What
        must not be skipped is closing the listening socket -- a socket still
        accepting is a browser reconnecting, and every reconnect is another
        thread for Kodi to wait on before it can finish shutting down -- and
        then the connections already open, whose threads would otherwise wait
        for a browser that has nothing more to ask.
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

            # First, and before anything that can block: the streams read this
            # between snapshots and unwind on their own, and the server reads
            # it in verify_request and stops taking connections.
            if stop is not None:
                stop.set()
            if producer is not None:
                producer.wake()

            if server is not None:
                # shutdown() ends the accept loop; server_close() drops the
                # listening socket.  The close is what stops new threads
                # appearing, so it runs even if the first call goes wrong.
                try:
                    server.shutdown()
                except Exception as exc:
                    _log(f"server shutdown failed: {exc}", xbmc.LOGWARNING)
                finally:
                    try:
                        server.server_close()
                    except Exception as exc:
                        _log(f"server close failed: {exc}", xbmc.LOGWARNING)
                    # With the accept loop gone no connection can be added,
                    # so this reaches every one: the request threads then end
                    # now rather than at their read timeout.
                    try:
                        server.close_connections()
                    except Exception as exc:
                        _log(f"closing connections failed: {exc}",
                             xbmc.LOGWARNING)

            # Then wait for the threads themselves.  Kodi's own wait for them
            # has no timeout, so a thread left running here is a Kodi that
            # never finishes shutting down; ours is bounded because by then
            # there is nothing further the add-on can do about it -- and
            # bounded once, for all three, so the waits cannot add up.
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
                # The connections were shut for reading above; a thread still
                # running a moment later is stuck writing, and is cut off.
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
