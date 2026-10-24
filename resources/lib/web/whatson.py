# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Rotten Tomatoes' ratings of the playing film from WhatsOn, where neither
MDBList nor the library has them (``web_whatson``).

MDBList has no Rotten Tomatoes rating for some films (The Matrix,
Interstellar) that WhatsOn (whatson-api.onrender.com, a free service for
non-commercial use) has: the Tomatometer and the Popcornmeter.  It is asked
without a key, which allows 40 questions an hour and 200 a day, so it is
asked only for what is missing: for a film, by its IMDb id or else its TMDb
one, once MDBList has answered (or will not be asked), and only when one of
the two is not among the ratings to show.

A film is asked for once, off the thread that builds the snapshot, and the
answer is kept for half a day, a film WhatsOn does not know included.  A
spent limit waits for as long as WhatsOn says.
"""

import http.client
import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from urllib.parse import quote

import xbmc
from core import settings
from core.log import channel
from web.payloads import Ratings
from web.ratings import rating_list
from web.values import Json

_log = channel("web")

_URL = "https://whatson-api.onrender.com/?{provider}Id={ident}&item_type=movie"
_AGENT = "script.tinyppi (Kodi add-on)"
# The service sleeps on a free host and takes up to a minute to wake.
_TIMEOUT = 60.0
# A film's answer is a few kilobytes.
_BIGGEST = 512 * 1024

# How long an answer is kept, a film WhatsOn does not know included, how
# long a film it could not be reached for waits, and how long a spent limit
# waits when WhatsOn does not say.
_KEPT = 12 * 3600.0
_AGAIN = 10 * 60.0
_SPENT = 3600.0
# The films kept at once; the oldest goes first.
_LIMIT = 256

# Rotten Tomatoes' two ratings, as web.ratings names them, and the name each
# is kept by (MDBList's).  Either missing has WhatsOn asked.
_WANTED = {"rottentomatoes": "tomatoes", "popcorn": "popcorn"}

# Ratings out of ten by name, as web.ratings.rating_list reads them.
Scores = dict[str, Json]
# What a film is asked for by: "imdb" or "tmdb", and the id.
_Wanted = tuple[str, str]


class _Spent(Exception):
    """The limit is spent; *wait* is how many seconds are left of it."""

    def __init__(self, wait: float) -> None:
        super().__init__(wait)
        self.wait = wait


def _percent(value: object) -> float | None:
    """Return a rating out of 100 as one out of ten, or None for none."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 10 if math.isfinite(value) and 0 < value <= 100 else None


def _count(value: object) -> int | None:
    """Return a vote count, where JSON gave a whole number."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _film(answer: Json, provider: str, ident: str) -> Json:
    """Return the film in one of WhatsOn's answers, or {}.

    An id can match more than one entry; the one the id is the film's own
    is taken, else the first.
    """
    results = answer.get("results")
    films = [entry for entry in (results if isinstance(results, list) else [])
             if isinstance(entry, dict) and entry.get("item_type") == "movie"]
    for film in films:
        held = film.get(provider)
        if isinstance(held, dict) and str(held.get("id")) == ident:
            return film
    return films[0] if films else {}


def scores_of(answer: Json, provider: str, ident: str) -> Scores:
    """Return the Rotten Tomatoes ratings in one of WhatsOn's answers."""
    tomatoes = _film(answer, provider, ident).get("rotten_tomatoes")
    if not isinstance(tomatoes, dict):
        return {}
    found: Scores = {}
    for name, side in (("tomatoes", "critics"), ("popcorn", "users")):
        rating = _percent(tomatoes.get(f"{side}_rating"))
        if rating is not None:
            found[name] = {"rating": rating, "votes": _count(tomatoes.get(f"{side}_rating_count"))}
    return found


def _retry_after(error: urllib.error.HTTPError) -> float:
    """Return how many seconds WhatsOn says the spent limit has left."""
    try:
        wait = float(error.headers.get("Retry-After") or _SPENT)
    except ValueError:
        wait = _SPENT
    return min(max(wait, 60.0), 86400.0)


def _answer(url: str) -> Json:
    """Return WhatsOn's answer at *url* as a JSON object ({} for another)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": _AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        found = json.loads(response.read(_BIGGEST))
    return found if isinstance(found, dict) else {}


def fetch(provider: str, ident: str) -> tuple[Scores, float]:
    """Return a film's Rotten Tomatoes ratings and how long to keep them.

    Raises _Spent while the limit is spent.  A film WhatsOn does not know
    has none for half a day, and one it could not be reached for none until
    it is asked again.
    """
    url = _URL.format(provider=provider, ident=quote(ident, safe=""))
    try:
        answer = _answer(url)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise _Spent(_retry_after(error)) from None
        if error.code == 404:
            _log(f"WhatsOn does not know {provider} {ident}", xbmc.LOGINFO)
            return {}, _KEPT
        _log(f"WhatsOn answered {error.code} for {provider} {ident}", xbmc.LOGWARNING)
        return {}, _AGAIN
    except (OSError, ValueError, http.client.HTTPException) as error:
        _log(f"WhatsOn could not be asked for {provider} {ident}: {type(error).__name__}",
             xbmc.LOGWARNING)
        return {}, _AGAIN
    found = scores_of(answer, provider, ident)
    _log(f"WhatsOn rated {provider} {ident}: {', '.join(found) or 'nothing'}", xbmc.LOGINFO)
    return found, _KEPT


def _in_background(work: Callable[[], None]) -> None:
    """Run *work* on a thread of its own, which does not hold up Kodi's exit."""
    threading.Thread(target=work, name="TinyPPI WhatsOn", daemon=True).start()


class Lookup:
    """WhatsOn's answers for the films asked for, and the asking."""

    def __init__(self, start: Callable[[Callable[[], None]], None] = _in_background,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._start = start
        self._clock = clock
        self._lock = threading.Lock()
        # When each answer goes stale, and the answer.
        self._kept: dict[_Wanted, tuple[float, Scores]] = {}
        self._asking: set[_Wanted] = set()
        self._spent_until = 0.0

    def scores(self, ids: Mapping[str, str]) -> Scores | None:
        """Return WhatsOn's ratings for the film *ids* name, or None while
        there are none to show; asks for them the first time."""
        if not ids:
            return None
        provider = "imdb" if "imdb" in ids else "tmdb"
        wanted = (provider, ids[provider])
        now = self._clock()
        with self._lock:
            kept = self._kept.get(wanted)
            if kept and now < kept[0]:
                return kept[1] or None
            if wanted in self._asking or now < self._spent_until:
                return None
            self._asking.add(wanted)
        self._start(lambda: self._ask(wanted))
        return None

    def _ask(self, wanted: _Wanted) -> None:
        """Ask WhatsOn for one film and keep its answer.

        The film is free to be asked for again however the asking ends, a
        fault of its own included.
        """
        try:
            found, keep = self._answer_for(wanted)
        finally:
            with self._lock:
                self._asking.discard(wanted)
        if keep:
            with self._lock:
                self._kept.pop(wanted, None)
                self._kept[wanted] = (self._clock() + keep, found)
                while len(self._kept) > _LIMIT:
                    self._kept.pop(next(iter(self._kept)))

    def _answer_for(self, wanted: _Wanted) -> tuple[Scores, float]:
        """Return a film's ratings and how long to keep them (0: not at all)."""
        try:
            return fetch(*wanted)
        except _Spent as spent:
            _log(f"WhatsOn's limit is spent; asking again in {int(spent.wait // 60)} min",
                 xbmc.LOGWARNING)
            with self._lock:
                self._spent_until = self._clock() + spent.wait
            return {}, 0.0


_LOOKUP = Lookup()


def allowed() -> bool:
    """Return whether the reader lets WhatsOn be asked.

    It costs a look at the settings, so the caller reads it once a static
    interval (see ``SnapshotBuilder._rating_settings``).
    """
    try:
        return settings.addon().getSettingBool("web_whatson")
    except RuntimeError:
        # The add-on is being updated; what MDBList and the library have will do.
        return False


def missing(ratings: Ratings) -> bool:
    """Return whether Rotten Tomatoes' critics or audience are not among
    *ratings*."""
    shown = {entry["source"] for entry in ratings["ratings"]}
    return any(name not in shown for name in _WANTED)


def with_whatson(ratings: Ratings, lookup: Lookup = _LOOKUP) -> Ratings:
    """Return *ratings* with the Rotten Tomatoes ratings they lack from
    WhatsOn, where it has any; the ones already there stand."""
    if not missing(ratings):
        return ratings
    found = lookup.scores(ratings["ids"])
    if not found:
        return ratings
    held: Scores = {entry["source"]: {"rating": entry["rating"], "votes": entry["votes"]}
                    for entry in ratings["ratings"]}
    for source, name in _WANTED.items():
        if source not in held and name in found:
            held[source] = found[name]
    merged = ratings.copy()
    merged["ratings"] = rating_list(held)
    return merged
