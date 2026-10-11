# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's request handler, dispatch tables and event stream.

Routes are a fixed table, never a filesystem lookup; every state change
needs the token.
"""

import gzip
import json
import math
import re
import secrets
import time
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import xbmc
from core import settings
from core.log import channel
from web import access, artwork, library
from web.delta import snapshot_delta
from web.library.entries import Listing
from web.payloads import DeltaFrame, Snapshot
from web.player import apply_command
from web.producer import PRODUCE_INTERVAL, Producer
from web.static import MIN_COMPRESS, STATIC_CACHE
from web.strings import ui_strings
from web.values import Unchecked
from web.vs10 import apply_mode

if TYPE_CHECKING:  # web.server imports this module
    from web.server import _Server

# Heartbeat interval on an idle stream, so dropped connections are noticed.
_HEARTBEAT_INTERVAL = 15.0

# Socket timeouts.  After the service script returns, Kodi waits without
# timeout for every interpreter thread (daemons included), so no wait here
# may be unbounded.
#
# _REQUEST_TIMEOUT bounds an idle keep-alive connection while the server
# runs; it exceeds Kodi's five-second stop limit, so stop() hangs up instead
# of waiting (_Server.close_connections in web/server.py).
# _STREAM_WRITE_TIMEOUT bounds a write to a stream that stopped reading.
_REQUEST_TIMEOUT      = 15.0
_STREAM_WRITE_TIMEOUT = 4.0

# Maximum request body size (POST bodies are tiny).
_MAX_BODY = 4096

# A token in a request line.  The page never puts it there (see the session
# below), and the server no longer reads it from there, but a page from an
# older version or a hand-typed address may; masked before logging, since
# debug logs get posted to forums.
_TOKEN_IN_QUERY = re.compile(r"(token=)[^&\s\"']*", re.IGNORECASE)

# The read session.  What a browser cannot send a header with (the event
# stream, images) carries this cookie instead of the token: the page trades
# the token for it once per connection (POST /api/session, see connect in
# js/core.js).  HttpOnly keeps it from scripts, SameSite=Strict from other
# sites' requests, and it is valid for reading only and for this server's
# lifetime (a new token restarts the server).  No Max-Age: it ends with the
# browser session.
_SESSION_COOKIE = "tinyppi_session"
_SESSION_ATTRIBUTES = "Path=/api/; HttpOnly; SameSite=Strict"

# An artwork tag as the add-on makes them (CRC-32 in hex, see
# snapshot._art_tags and library.common.tag).  It goes into the ETag header, so
# anything else (e.g. an encoded CR/LF that would add headers) is no tag.
_ART_TAG = re.compile(r"[0-9a-f]{1,16}")

# Headers on every response: no framing (clickjacking) and no referrer
# (nothing in a URL should leave the page).
_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)

# Content Security Policy of the page: only its own files and API, no inline
# script or style, no other origin.  Nothing loads from the internet anyway,
# so an injected script (e.g. in a title) has nowhere to run.
_PAGE_POLICY = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))


_log = channel("web", xbmc.LOGINFO)


def _param(query: dict[str, list[str]], name: str) -> str:
    """Return the first value of *name* in a parsed query, or ''."""
    return (query.get(name) or [""])[0]


class Handler(BaseHTTPRequestHandler):
    """The request handler; ``server`` holds the producer, token and files."""

    protocol_version = "HTTP/1.1"
    server_version   = "TinyPPI"
    sys_version      = ""
    # Applied before the first request line, so a silent connection cannot
    # hold a thread forever.
    timeout          = _REQUEST_TIMEOUT

    server: _Server

    # --- Plumbing ----------------------------------------------------------

    @property
    def _peer(self) -> str:
        """The client's address for log lines."""
        return access.plain_address(self.client_address[0])

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003 - base API
        _log(_TOKEN_IN_QUERY.sub(r"\1***", fmt % args), xbmc.LOGDEBUG)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              extra: tuple[tuple[str, str], ...] = (),
              cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Live player state must never be cached; static files and art set
        # their own policy.
        self.send_header("Cache-Control", cache)
        for name, value in _SECURITY_HEADERS + extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_unchanged(self, etag: str, cache: str) -> None:
        """Send an empty 304 for a conditional request."""
        self.send_response(HTTPStatus.NOT_MODIFIED)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache)
        self.end_headers()

    def _holds(self, etag: str) -> bool:
        """Return whether the request's If-None-Match matches *etag*."""
        offered = self.headers.get("If-None-Match", "")
        return bool(etag) and etag in [
            part.strip().removeprefix("W/") for part in offered.split(",")
        ]

    def _send_json(self, payload: Mapping[str, object], status: HTTPStatus = HTTPStatus.OK,
                   etag: str = "", cache: str = "no-store",
                   extra: tuple[tuple[str, str], ...] = ()) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if etag:
            extra += (("ETag", etag),)
        # Large JSON (mainly the chart history) is gzipped.
        if (len(body) >= MIN_COMPRESS
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            body = gzip.compress(body, 6)
            extra += (("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding"))
        self._send(status, body, "application/json; charset=utf-8", extra,
                   cache=cache)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    # --- Auth --------------------------------------------------------------

    def _presented_token(self) -> str:
        """Return the token in the request's header, or ''.

        Only the header counts: a URL ends up in logs and histories.
        """
        return self.headers.get("X-TinyPPI-Token", "").strip()

    def _session_holder(self) -> bool:
        """Return whether the request carries this server's read session.

        Parsed by hand: cookies are per host, not per port, so the header
        may carry those of other services on the box (Kodi's own web
        interface, say), and ``http.cookies`` drops every cookie when one
        of them does not parse.
        """
        expected = self.server.session.encode("ascii")
        for part in self.headers.get("Cookie", "").split(";"):
            name, _sep, value = part.partition("=")
            if name.strip() != _SESSION_COOKIE:
                continue
            offered = value.strip().encode("utf-8", "replace")
            if len(offered) == len(expected) and secrets.compare_digest(offered, expected):
                return True
        return False

    def _token_holder(self, session: bool = False) -> bool:
        """Return whether the request carries the token.

        With *session*, the read session counts as the token (reads only):
        it cannot be guessed, so it is checked before any lockout.  Otherwise
        the request has been answered with 401, or 429 for a locked-out
        address (see ``access.Guesses``).
        """
        if session and self._session_holder():
            return True
        address = access.client_key(self.client_address[0])
        wait = self.server.guesses.locked_for(address)
        if wait:
            self._send_json({"error": "too many wrong tokens",
                             "retry_ms": int(wait * 1000)},
                            HTTPStatus.TOO_MANY_REQUESTS,
                            extra=(("Retry-After", str(math.ceil(wait))),))
            return False

        presented = self._presented_token()
        # Compare bytes: compare_digest rejects non-ASCII str.
        expected = self.server.token.encode("utf-8")
        offered  = presented.encode("utf-8", "replace")
        if len(offered) == len(expected) and secrets.compare_digest(offered, expected):
            return True
        self.server.guesses.wrong(address, presented)
        self._send_error_json(HTTPStatus.UNAUTHORIZED, "token required")
        return False

    def _token_to_read(self) -> bool:
        """Return whether reading needs the token for this request.

        When the setting says so, for a client beyond the home network (see
        ``access.home_peer``), or for an untrusted host name (see
        ``access.trusted_host``).
        """
        return (self.server.auth_read
                or not access.home_peer(self.client_address[0])
                or not access.trusted_host(self.headers.get("Host", "")))

    # --- Routing -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - base API
        route = urlparse(self.path).path
        if route in self.server.static_routes:
            self._serve_static(route)
            return
        reader = _READERS.get(route)
        if reader is not None:
            if self._token_to_read() and not self._token_holder(session=True):
                return
            reader(self)
            return
        if route == "/api/hello":
            self._serve_hello()
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")

    def do_POST(self) -> None:  # noqa: N802 - base API
        # Always read the body first: on a keep-alive connection an unread
        # body would be parsed as the next request.
        payload = self._read_json_body()
        if payload is None:
            return

        route = urlparse(self.path).path
        if route == "/api/session":
            # For reading, so control need not be allowed; the token must.
            if self._token_holder():
                self._start_session()
            return
        writer = _WRITERS.get(route)
        if writer is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")
            return
        if not self.server.allow_control:
            self._send_error_json(HTTPStatus.FORBIDDEN, "control disabled")
            return
        # Writing always needs the token.
        if not self._token_holder():
            return
        writer(self, payload)

    def _serve_hello(self) -> None:
        """Send the page's start-up information.

        Unauthenticated on purpose: no player state, only version, feature
        flags and UI strings.
        """
        addon = settings.addon()
        self._send_json({
            "name":        "TinyPPI",
            "version":     addon.getAddonInfo("version"),
            # Per request, so an untrusted host name asks for the token.
            "auth_read":   self._token_to_read(),
            "control":     self.server.allow_control,
            # The film shelf needs both the library and the control setting.
            "library":     self.server.offer_library and self.server.allow_control,
            # The series shelf has its own setting.
            "series":      self.server.offer_series and self.server.allow_control,
            "interval_ms": int(PRODUCE_INTERVAL * 1000),
            "strings":     ui_strings(addon),
        })

    def _start_session(self) -> None:
        """Hand a token holder the read session cookie."""
        self._send_json({"ok": True}, extra=((
            "Set-Cookie",
            f"{_SESSION_COOKIE}={self.server.session}; {_SESSION_ATTRIBUTES}",
        ),))

    def _serve_state(self) -> None:
        """Send the current snapshot to a page without a stream."""
        self._send_json(self._state_payload())

    def _serve_history(self) -> None:
        """Send the chart history and events (on connect and new events)."""
        self._send_json(self.server.producer.history())

    def _set_mode(self, payload: dict[str, Unchecked]) -> None:
        """Switch the VS10 output mode."""
        mode = str(payload.get("mode", "")).strip()
        if not apply_mode(mode):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "unknown mode")
            return
        _log(f"VS10 mode '{mode}' requested from {self._peer}")
        self._send_json({"ok": True, "mode": mode})

    def _run_command(self, payload: dict[str, Unchecked]) -> None:
        """Run a transport command (play/pause, seek, volume, ...)."""
        action = str(payload.get("action", "")).strip()
        if not apply_command(action, payload.get("value")):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "command failed")
            return
        # Seek and volume arrive in bursts, so they log at debug level.
        _log(f"'{action}' requested from {self._peer}",
             xbmc.LOGDEBUG if action in ("seek", "seek_percent", "volume")
             else xbmc.LOGINFO)
        self._send_json({"ok": True, "action": action})

    def _read_json_body(self) -> dict[str, Unchecked] | None:
        """Return the JSON body as a dict, or None after sending an error."""
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

    # --- Responses ---------------------------------------------------------

    def _state_payload(self) -> Snapshot:
        payload = self.server.producer.fresh().copy()
        payload["control"] = self.server.allow_control
        # Whether a stream would be refused now: an EventSource cannot read
        # the 503, so the page asks here (see connect() in js/core.js).
        payload["streams_full"] = self.server.streams_full
        return payload

    def _serve_library(self) -> None:
        """Send the film library."""
        if not (self.server.offer_library and self.server.allow_control):
            # Disabled, or control is off (nothing could be played).
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        try:
            payload = library.movies()
        except Exception as exc:
            _log(f"reading the video database failed: {exc}", xbmc.LOGWARNING)
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                  "library unavailable")
            return
        self._send_listing(payload)

    def _start_film(self, payload: dict[str, Unchecked]) -> None:
        """Start a film or an episode, depending on the id in *payload*."""
        # resume=False starts from the beginning; anything else resumes.
        resume = payload.get("resume") is not False
        episode_id = payload.get("episodeid")
        if episode_id is not None:
            if not self.server.offer_series:
                self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
                return
            if not library.play_episode(episode_id, resume):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "playback failed")
                return
            _log(f"episode {episode_id} started from {self._peer}")
            self._send_json({"ok": True, "episodeid": episode_id})
            return

        if not self.server.offer_library:
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        movie_id = payload.get("movieid")
        if not library.play(movie_id, resume):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "playback failed")
            return
        _log(f"film {movie_id} started from {self._peer}")
        # The page learns about the playback from the next snapshot.
        self._send_json({"ok": True, "movieid": movie_id})

    def _mark_watched(self, payload: dict[str, Unchecked]) -> None:
        """Mark a film, series or episode as watched or unwatched.

        The id in *payload* selects the kind; each needs its shelf's setting.
        """
        watched = payload.get("watched")
        if not isinstance(watched, bool):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "watched required")
            return
        for key, kind, offered in (
                ("movieid", "movie", self.server.offer_library),
                ("tvshowid", "tvshow", self.server.offer_series),
                ("episodeid", "episode", self.server.offer_series)):
            item_id = payload.get(key)
            if item_id is None:
                continue
            if not offered:
                self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
                return
            if not library.set_watched(kind, item_id, watched):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "update failed")
                return
            self._send_json({"ok": True, key: item_id, "watched": watched})
            return
        self._send_error_json(HTTPStatus.BAD_REQUEST, "no title named")

    def _clear_resume(self, payload: dict[str, Unchecked]) -> None:
        """Clear the resume point of a film or episode."""
        for key, kind, offered in (
                ("movieid", "movie", self.server.offer_library),
                ("episodeid", "episode", self.server.offer_series)):
            item_id = payload.get(key)
            if item_id is None:
                continue
            if not offered:
                self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
                return
            if not library.clear_resume(kind, item_id):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "update failed")
                return
            self._send_json({"ok": True, key: item_id})
            return
        self._send_error_json(HTTPStatus.BAD_REQUEST, "no title named")

    def _serve_series(self) -> None:
        """Send the series library."""
        if not (self.server.offer_series and self.server.allow_control):
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        try:
            payload = library.shows()
        except Exception as exc:
            _log(f"reading the video database failed: {exc}", xbmc.LOGWARNING)
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                  "library unavailable")
            return
        self._send_listing(payload)

    def _serve_episodes(self) -> None:
        """Send the episodes of one series (requested when it is opened)."""
        if not (self.server.offer_series and self.server.allow_control):
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        show = _param(parse_qs(urlparse(self.path).query), "tvshowid")
        try:
            payload = library.episodes(show)
        except Exception as exc:
            _log(f"reading the video database failed: {exc}", xbmc.LOGWARNING)
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                  "library unavailable")
            return
        if payload is None:
            # Unknown series: the library changed; the page reloads the shelf.
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such series")
            return
        self._send_listing(payload)

    def _serve_continue(self) -> None:
        """Send partly watched films and episodes, newest first.

        Each kind only when its shelf is enabled.
        """
        films = self.server.offer_library
        series = self.server.offer_series
        if not ((films or series) and self.server.allow_control):
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        try:
            payload = library.continuing(films=films, series=series)
        except Exception as exc:
            _log(f"reading the video database failed: {exc}", xbmc.LOGWARNING)
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                  "library unavailable")
            return
        self._send_listing(payload)

    def _send_listing(self, payload: Listing) -> None:
        """Send a library list with its tag as ETag (304 when unchanged)."""
        etag = f'"{payload["tag"]}"'
        if self._holds(etag):
            self._send_unchanged(etag, STATIC_CACHE)
            return
        self._send_json(payload, etag=etag, cache=STATIC_CACHE)

    def _serve_art(self) -> None:
        """Send artwork of the playing title or a library item."""
        query = parse_qs(urlparse(self.path).query)
        kind = _param(query, "kind")
        if kind not in artwork.KINDS:
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such artwork")
            return
        # The URL carries the picture's tag, so the answer is immutable.
        tag  = _param(query, "v")
        if not _ART_TAG.fullmatch(tag):
            tag = ""
        etag = f'"{tag}"' if tag else ""
        cache = artwork.CACHE if tag else "no-store"
        if etag and self._holds(etag):
            self._send_unchanged(etag, cache)
            return

        found = self._find_art(query, kind)
        if found is None:
            # No artwork: the page hides the frame.
            self._send_error_json(HTTPStatus.NOT_FOUND, "no artwork")
            return
        body, content_type = found
        self._send(HTTPStatus.OK, body, content_type,
                   (("ETag", etag),) if etag else (), cache=cache)

    def _find_art(self, query: dict[str, list[str]], kind: str) -> tuple[bytes, str] | None:
        """Return the requested picture and its type, or None."""
        # No library id means the playing title.
        lookups = (("movieid", self.server.library_artwork),
                   ("tvshowid", self.server.series_artwork),
                   ("episodeid", self.server.episode_artwork))
        for name, lookup in lookups:
            item = _param(query, name)
            if item:
                return lookup(item, kind)
        return self.server.artwork(kind)

    def _serve_static(self, route: str) -> None:
        path, content_type = self.server.static_routes[route]
        found = self.server.static_files.get(path, content_type)
        if found is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "missing file")
            return
        body, packed, etag = found
        if self._holds(etag):
            self._send_unchanged(etag, STATIC_CACHE)
            return
        extra: tuple[tuple[str, str], ...] = (("ETag", etag), ("Vary", "Accept-Encoding"))
        if content_type.startswith("text/html"):
            extra += (("Content-Security-Policy", _PAGE_POLICY),)
        if packed is not None and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = packed
            extra += (("Content-Encoding", "gzip"),)
        self._send(HTTPStatus.OK, body, content_type, extra, cache=STATIC_CACHE)

    def _serve_stream(self) -> None:
        """Push snapshots as Server-Sent Events until the client leaves or
        the server stops."""
        if self.server.stop_event.is_set():
            # Shutting down: refuse, and tell the page to wait before
            # retrying (see the bye handler in js/core.js).
            self._send_json({"error": "shutting down", "retry_ms": 20000},
                            HTTPStatus.SERVICE_UNAVAILABLE)
            self.close_connection = True
            return
        if not self.server.claim_stream():
            # Slots free up quickly (hidden tabs disconnect, see js/core.js),
            # so the page retries soon.
            self._send_json({"error": "too many streams"},
                            HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            # No proxy buffering.
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._stream_loop()
        except (OSError, ValueError):
            pass  # the client went away
        finally:
            self.server.release_stream()
            self.close_connection = True

    def _stream_loop(self) -> None:
        producer = self.server.producer
        seen = producer.watch()
        try:
            self._stream_frames(producer, seen)
        finally:
            producer.unwatch()

    def _stream_frames(self, producer: Producer, seen: int) -> None:
        stop     = self.server.stop_event
        # Last payload sent on this connection, the base of the next delta.
        sent: Snapshot | None = None
        last_beat = time.monotonic()
        # Bound writes to a client that stopped reading (OSError ends the
        # stream); shorter than the heartbeat interval.
        self.connection.settimeout(_STREAM_WRITE_TIMEOUT)

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
            payload = snapshot.copy()
            payload["control"] = self.server.allow_control
            frame: Snapshot | DeltaFrame
            if sent is None:
                kind, frame = "state", payload
            else:
                kind, frame = "delta", snapshot_delta(sent, payload)
            sent = payload
            data = json.dumps(frame, ensure_ascii=False)
            self.wfile.write(f"event: {kind}\ndata: {data}\n\n".encode())
            self.wfile.flush()

        # Parting frame: the page shows "offline" and waits before
        # reconnecting, so it does not hit a server that is going down.
        self.wfile.write(b'event: bye\ndata: {"retry_ms": 20000}\n\n')
        self.wfile.flush()


# Read routes; they need the token only when reading does.
_READERS = {
    "/api/state":    Handler._serve_state,
    "/api/stream":   Handler._serve_stream,
    "/api/history":  Handler._serve_history,
    "/api/art":      Handler._serve_art,
    "/api/library":  Handler._serve_library,
    "/api/series":   Handler._serve_series,
    "/api/episodes": Handler._serve_episodes,
    "/api/continue": Handler._serve_continue,
}

# Write routes (JSON body); they always need the token and control enabled.
_WRITERS = {
    "/api/mode":    Handler._set_mode,
    "/api/command": Handler._run_command,
    "/api/play":    Handler._start_film,
    "/api/watched": Handler._mark_watched,
    "/api/resume":  Handler._clear_resume,
}
