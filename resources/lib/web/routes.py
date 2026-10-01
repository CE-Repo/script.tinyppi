# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's routes: one request handler, its dispatch tables and the
event stream.

Routes are a fixed table, never a path resolved against the filesystem, and
everything that changes the player's state needs the token.
"""

import gzip
import json
import math
import re
import secrets
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import xbmc

from core import settings
from core.log import channel
from web import access, artwork, library
from web.delta import snapshot_delta
from web.producer import PRODUCE_INTERVAL, Producer
from web.snapshot import apply_command, apply_mode
from web.static import MIN_COMPRESS, STATIC_CACHE
from web.strings import ui_strings

# Seconds between heartbeat comments on an idle stream.  Without them a
# connection dropped by a router in between looks alive until the next change.
_HEARTBEAT_INTERVAL = 15.0

# How long a socket may hold a request thread.
#
# Kodi does not care that these threads are daemons: when the service script
# returns, CPythonInvoker spins -- with no timeout of its own -- until every
# other thread of the interpreter is gone.  So a thread parked on a socket is
# a Kodi that will not shut down, and every wait here has to end on its own.
#
# _REQUEST_TIMEOUT bounds a kept-alive connection that has gone quiet between
# requests; _STREAM_WRITE_TIMEOUT bounds a write into a stream whose reader
# stopped reading.  Both are well inside the five seconds Kodi allows a script
# to stop in (PYTHON_SCRIPT_TIMEOUT).
_REQUEST_TIMEOUT      = 15.0
_STREAM_WRITE_TIMEOUT = 4.0

# Longest request body accepted (only the two POSTs have one, and both are
# tiny).
_MAX_BODY = 4096

# The token in a request line.  It travels in the query string of everything a
# browser cannot put a header on -- the stream, the pictures (see withToken in
# js/core.js) -- and a request line logged as it came would put it in Kodi's
# debug log, which is the file people post to a forum when something goes
# wrong.
_TOKEN_IN_QUERY = re.compile(r"(token=)[^&\s\"']*", re.IGNORECASE)

# Headers every answer carries.  The page is never to be framed by another one:
# it holds the token and its buttons stop films, which is exactly what a page
# laid invisibly over somebody else's site would be after (clickjacking).  And
# none of its addresses -- the stream and the pictures carry the token in
# theirs -- is passed on anywhere as a referrer.
_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)

# What the page itself may load and run: its own files and its own API, and
# nothing else -- no script written into the page, no inline style, no other
# origin.  Nothing is loaded from the internet in the first place (see the
# README), so this costs the page nothing and leaves a script that somehow got
# into a title or a file name with nowhere to run.
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


class Handler(BaseHTTPRequestHandler):
    """The route table.  ``server`` carries the producer, the token and the
    static-file map."""

    protocol_version = "HTTP/1.1"
    server_version   = "TinyPPI"
    sys_version      = ""
    # Applied to the socket before the first request line is read, so a
    # connection that is opened and then says nothing cannot hold a thread --
    # and with it Kodi's shutdown -- for good.
    timeout          = _REQUEST_TIMEOUT

    # -- plumbing --

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - base API
        _log(_TOKEN_IN_QUERY.sub(r"\1***", fmt % args), xbmc.LOGDEBUG)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              extra: tuple[tuple[str, str], ...] = (),
              cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The default is the live state of a player, which may never be
        # replayed from a cache.  The page itself is another matter, and says
        # so (see _serve_static and _serve_art).
        self.send_header("Cache-Control", cache)
        for name, value in _SECURITY_HEADERS + extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_unchanged(self, etag: str, cache: str) -> None:
        """Answer a conditional request with an empty 304."""
        self.send_response(HTTPStatus.NOT_MODIFIED)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache)
        self.end_headers()

    def _holds(self, etag: str) -> bool:
        """Whether the request already carries this exact version."""
        offered = self.headers.get("If-None-Match", "")
        return bool(etag) and etag in [
            part.strip().removeprefix("W/") for part in offered.split(",")
        ]

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK,
                   etag: str = "", cache: str = "no-store",
                   extra: tuple[tuple[str, str], ...] = ()) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if etag:
            extra += (("ETag", etag),)
        # The chart's history is the one answer here big enough to be worth
        # compressing -- an hour of samples is five arrays of 3600 numbers --
        # and it is asked for whenever a page opens or an event lands.
        if (len(body) >= MIN_COMPRESS
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            body = gzip.compress(body, 6)
            extra += (("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding"))
        self._send(status, body, "application/json; charset=utf-8", extra,
                   cache=cache)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    # -- auth --

    def _presented_token(self) -> str:
        header = self.headers.get("X-TinyPPI-Token", "")
        if header:
            return header.strip()
        query = parse_qs(urlparse(self.path).query)
        return (query.get("token") or [""])[0].strip()

    def _token_holder(self) -> bool:
        """Whether the request carries the token.  When it does not, it has
        been answered: a 401, so the page asks for the token -- or a 429 for an
        address that has been guessing it (see ``access.Guesses``), which is
        not even looked at until its lock-out is over.
        """
        address = self.client_address[0]
        wait = self.server.guesses.locked_for(address)
        if wait:
            self._send_json({"error": "too many wrong tokens",
                             "retry_ms": int(wait * 1000)},
                            HTTPStatus.TOO_MANY_REQUESTS,
                            extra=(("Retry-After", str(math.ceil(wait))),))
            return False

        presented = self._presented_token()
        # Compared as bytes: compare_digest refuses a str with anything but
        # ASCII in it, and a header can carry anything at all.  A wrong length
        # is a mismatch either way.
        expected = self.server.token.encode("utf-8")
        offered  = presented.encode("utf-8", "replace")
        if len(offered) == len(expected) and secrets.compare_digest(offered, expected):
            return True
        self.server.guesses.wrong(address, presented)
        self._send_error_json(HTTPStatus.UNAUTHORIZED, "token required")
        return False

    def _token_to_read(self) -> bool:
        """Whether reading needs the token on this request.

        Always when the setting says so.  Otherwise only when the request came
        in under a host name no home network would use -- which is what a web
        page reading the box through somebody's browser has to send (see
        ``access.trusted_host``).
        """
        return (self.server.auth_read
                or not access.trusted_host(self.headers.get("Host", "")))

    # -- routing --

    def do_GET(self) -> None:  # noqa: N802 - base API
        route = urlparse(self.path).path
        if route in self.server.static_routes:
            self._serve_static(route)
            return
        reader = _READERS.get(route)
        if reader is not None:
            if self._token_to_read() and not self._token_holder():
                return
            reader(self)
            return
        if route == "/api/hello":
            self._serve_hello()
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")

    def do_POST(self) -> None:  # noqa: N802 - base API
        # The body is read first, whatever the request turns out to be: on a
        # kept-alive HTTP/1.1 connection an unread body is parsed as the next
        # request line, so a rejected POST would corrupt the one after it.
        payload = self._read_json_body()
        if payload is None:
            return

        writer = _WRITERS.get(urlparse(self.path).path)
        if writer is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such route")
            return
        if not self.server.allow_control:
            self._send_error_json(HTTPStatus.FORBIDDEN, "control disabled")
            return
        # Writing always needs the token, whatever reading is set to.
        if not self._token_holder():
            return
        writer(self, payload)

    def _serve_hello(self) -> None:
        """What the page needs to know before it can ask for anything else.

        Deliberately unauthenticated: it carries no player state, only the
        version, the settings that decide which cards the page draws, and its
        chrome in Kodi's language.
        """
        addon = settings.addon()
        self._send_json({
            "name":        "TinyPPI",
            "version":     addon.getAddonInfo("version"),
            # Read off this request rather than the setting alone, so a page
            # reached under a name that needs the token asks for it at once.
            "auth_read":   self._token_to_read(),
            "control":     self.server.allow_control,
            # Whether the idle page has a film library to offer.  Both
            # halves have to be there: reading the library is this
            # setting, and starting one of them is the control setting.
            "library":     self.server.offer_library and self.server.allow_control,
            # And whether it has a series library, which is its own
            # setting: the two shelves are offered separately, so a box can
            # have the one and not the other.
            "series":      self.server.offer_series and self.server.allow_control,
            "interval_ms": int(PRODUCE_INTERVAL * 1000),
            "strings":     ui_strings(addon),
        })

    def _serve_state(self) -> None:
        """The snapshot as it is now, for a page outside any stream."""
        self._send_json(self._state_payload())

    def _serve_history(self) -> None:
        """The chart's whole past and the event list, asked for on connect and
        again whenever the snapshot's event count moves."""
        self._send_json(self.server.producer.history())

    def _set_mode(self, payload: dict) -> None:
        """Switch the VS10 output mode."""
        mode = str(payload.get("mode", "")).strip()
        if not apply_mode(mode):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "unknown mode")
            return
        _log(f"VS10 mode '{mode}' requested from {self.client_address[0]}")
        self._send_json({"ok": True, "mode": mode})

    def _run_command(self, payload: dict) -> None:
        """Carry out one transport command: play/pause, a seek, the volume."""
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
        payload = dict(self.server.producer.fresh())
        payload["control"] = self.server.allow_control
        # Whether a stream would be turned away right now.  A browser whose
        # EventSource was refused cannot read why -- the failure reaches it as
        # a bare error -- so it asks here, and this is what tells a full server
        # apart from one that has gone away (see connect() in js/core.js).
        payload["streams_full"] = self.server.streams_full
        return payload

    def _serve_library(self) -> None:
        """Send the films the video database holds."""
        if not (self.server.offer_library and self.server.allow_control):
            # Off in the settings, or a box that will not be told what to play:
            # either way there is no card, and saying so is better than
            # answering with a list nothing can be done with.
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

    def _start_film(self, payload: dict) -> None:
        """Put a film, or one episode of a series, on the television.

        One route for both because it is one act: something in the library is
        being started.  Which of the two it is, is which id the body carries --
        a series itself is never named here, because a series is not a thing
        that can be played.
        """
        # False asks for the title from the beginning, past any point the
        # library holds to resume it from; anything else resumes as before.
        resume = payload.get("resume") is not False
        episode_id = payload.get("episodeid")
        if episode_id is not None:
            if not self.server.offer_series:
                self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
                return
            if not library.play_episode(episode_id, resume):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "playback failed")
                return
            _log(f"episode {episode_id} started from {self.client_address[0]}")
            self._send_json({"ok": True, "episodeid": episode_id})
            return

        if not self.server.offer_library:
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        movie_id = payload.get("movieid")
        if not library.play(movie_id, resume):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "playback failed")
            return
        _log(f"film {movie_id} started from {self.client_address[0]}")
        # Nothing is pushed from here: the producer rebuilds five times a
        # second and the page learns the film is on from the next snapshot,
        # the same way it learns about one started from the remote control.
        self._send_json({"ok": True, "movieid": movie_id})

    def _mark_watched(self, payload: dict) -> None:
        """Mark a film, a series or one episode of one as seen or unseen.

        Which of the three it is, is which id the body carries, the same as
        ``/api/play``; ``watched`` says which way.  Behind the same settings as
        the shelf the title came off: a box that offers no series has handed
        out no series to be marked.
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

    def _clear_resume(self, payload: dict) -> None:
        """Forget where a film or one episode got to, leaving it unwatched or
        watched as it was.  A series has no resume point of its own."""
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
        """Send the series the video database holds."""
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
        """Send the episodes of one series.

        Asked for only when somebody opens that series, which is why it is a
        route of its own rather than part of the shelf: a house with ninety
        series in it would otherwise be sending every episode of all of them to
        draw a wall of ninety posters.
        """
        if not (self.server.offer_series and self.server.allow_control):
            self._send_error_json(HTTPStatus.FORBIDDEN, "library disabled")
            return
        show = (parse_qs(urlparse(self.path).query).get("tvshowid") or [""])[0]
        try:
            payload = library.episodes(show)
        except Exception as exc:
            _log(f"reading the video database failed: {exc}", xbmc.LOGWARNING)
            self._send_error_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                  "library unavailable")
            return
        if payload is None:
            # A series that is not on the shelf the page was drawn from: the
            # library moved under it, and the page reads the shelf again.
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such series")
            return
        self._send_listing(payload)

    def _serve_continue(self) -> None:
        """Send the films and episodes left half-watched, newest first.

        Whichever halves the box offers: a film is on the row only where the
        film shelf is, and an episode only where the series shelf is, because
        a press on one starts it and starting it needs that shelf's setting.
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

    def _send_listing(self, payload: dict) -> None:
        """Send one of the library's lists, under its own tag.

        A validator rather than the whole list every time: the tag changes only
        when the library does, so a phone that opens the page twice in an
        evening is answered the second time with an empty 304.  Which matters
        here more than anywhere else on this server, because these are the
        answers whose size grows with somebody's collection.
        """
        etag = f'"{payload["tag"]}"'
        if self._holds(etag):
            self._send_unchanged(etag, STATIC_CACHE)
            return
        self._send_json(payload, etag=etag, cache=STATIC_CACHE)

    def _serve_art(self) -> None:
        """Send the poster or the fanart of what is playing, or of one of the
        films, series or episodes the library cards offer."""
        query = parse_qs(urlparse(self.path).query)
        kind = (query.get("kind") or [""])[0]
        if kind not in artwork.KINDS:
            self._send_error_json(HTTPStatus.NOT_FOUND, "no such artwork")
            return
        # Which of the three shelves the picture is off, if it is off one at
        # all: a request naming none of them is asking for what is playing.
        film    = (query.get("movieid") or [""])[0]
        show    = (query.get("tvshowid") or [""])[0]
        episode = (query.get("episodeid") or [""])[0]
        # The page hangs the picture's own tag on the address, so an answer
        # can be kept for as long as the browser likes: the next film asks a
        # different address rather than the same one twice.
        tag  = (query.get("v") or [""])[0]
        etag = f'"{tag}"' if tag else ""
        cache = artwork.CACHE if tag else "no-store"
        if etag and self._holds(etag):
            self._send_unchanged(etag, cache)
            return

        if film:
            found = self.server.library_artwork(film, kind)
        elif show:
            found = self.server.series_artwork(show, kind)
        elif episode:
            found = self.server.episode_artwork(episode, kind)
        else:
            found = self.server.artwork(kind)
        if found is None:
            # Not every film has a poster, and a library-less file has none at
            # all; the page hides the frame rather than showing a broken one.
            self._send_error_json(HTTPStatus.NOT_FOUND, "no artwork")
            return
        body, content_type = found
        self._send(HTTPStatus.OK, body, content_type,
                   (("ETag", etag),) if etag else (), cache=cache)

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
        extra = (("ETag", etag), ("Vary", "Accept-Encoding"))
        if content_type.startswith("text/html"):
            extra += (("Content-Security-Policy", _PAGE_POLICY),)
        if packed is not None and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = packed
            extra += (("Content-Encoding", "gzip"),)
        self._send(HTTPStatus.OK, body, content_type, extra, cache=STATIC_CACHE)

    def _serve_stream(self) -> None:
        """Push snapshots as Server-Sent Events until the client leaves or the
        service shuts down."""
        if self.server.stop_event.is_set():
            # Shutting down: a stream opened now would be one more thread for
            # Kodi to wait on, and the page is told not to come straight back
            # for another (see the bye handler in js/core.js).
            self._send_json({"error": "shutting down", "retry_ms": 20000},
                            HTTPStatus.SERVICE_UNAVAILABLE)
            self.close_connection = True
            return
        if not self.server.claim_stream():
            # A slot frees the moment a forgotten tab is closed or its phone
            # locks (see the visibility handling in js/core.js), so the page is
            # told to come back in a second rather than backing off.
            self._send_json({"error": "too many streams"},
                            HTTPStatus.SERVICE_UNAVAILABLE)
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
        # The last payload this connection was sent, which every delta after
        # it is measured against.  Per connection rather than per server: two
        # browsers can be at different points, and a page that has just
        # connected must be sent the whole thing whatever the others hold.
        sent: dict | None = None
        last_beat = time.monotonic()
        # A write to a client that has gone quiet must not hold the thread for
        # good; the timeout turns it into the OSError the caller treats as a
        # closed connection.  It is deliberately shorter than the heartbeat:
        # what is being bounded is the write, not the wait between them, and a
        # thread still writing when Kodi stops is a Kodi that hangs.
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
            payload = dict(snapshot)
            payload["control"] = self.server.allow_control
            if sent is None:
                kind, frame = "state", payload
            else:
                kind, frame = "delta", snapshot_delta(sent, payload)
            sent = payload
            data = json.dumps(frame, ensure_ascii=False)
            self.wfile.write(f"event: {kind}\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

        # A parting frame so the page can say it is offline rather than
        # showing a dead connection.  It carries how long to stay away: the
        # server is going down with Kodi, and a reconnect landing in the
        # middle of that is a fresh thread for Kodi to wait on.
        self.wfile.write(b'event: bye\ndata: {"retry_ms": 20000}\n\n')
        self.wfile.flush()


# The routes that read the player or the library, and what answers each.  Open
# to anyone while reading needs no token, and to a token holder always.
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

# The routes that change something, and what carries each out.  Each takes the
# request's JSON body, and every one of them needs the token and the control
# setting.
_WRITERS = {
    "/api/mode":    Handler._set_mode,
    "/api/command": Handler._run_command,
    "/api/play":    Handler._start_film,
    "/api/watched": Handler._mark_watched,
    "/api/resume":  Handler._clear_resume,
}
