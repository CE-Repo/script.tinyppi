# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Rotten Tomatoes' ratings of the playing film from WhatsOn, and its
Certified Fresh and Verified Hot, for every film (``web_whatson_key``
optional).

MDBList has no Rotten Tomatoes rating for some films (The Matrix,
Interstellar) that WhatsOn (whatson-api.onrender.com, a free service for
non-commercial use) has: the Tomatometer and the Popcornmeter.  Where
neither MDBList nor the library has one, WhatsOn's is shown; one they have
stands.  WhatsOn alone says whether Rotten Tomatoes certified either -- the
critics' Certified Fresh, the audience's Verified Hot -- which the rating's
badge then wears, whoever gave the rating.

WhatsOn is always asked: for a film only, by its IMDb id or else its TMDb
one, once MDBList has answered (or will not be asked).  Without a key it
allows 40 questions an hour and 200 a day; the free key a reader may ask its
author for, 200 an hour and 1,000 a day.  A key it does not know is asked
with as no key at all.  A film is asked for once, off the thread
that builds the snapshot, and the answer is kept for half a day, a film
WhatsOn does not know included.  A spent limit waits for as long as WhatsOn
says.
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
# Added to the address for a reader who gave a key.
_KEYED = "&api_key={key}"
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
# is kept by (MDBList's).
_WANTED = {"rottentomatoes": "tomatoes", "popcorn": "popcorn"}

# Ratings out of ten by name, as web.ratings.rating_list reads them.
Scores = dict[str, Json]
# What a film is asked for by: the key ("" for none), "imdb" or "tmdb", and the id.
_Wanted = tuple[str, str, str]


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
    """Return the Rotten Tomatoes ratings in one of WhatsOn's answers, each
    with whether Rotten Tomatoes certified it.

    A side certified without a rating is kept for the certificate alone
    (``rating`` None): the rating may come from MDBList.
    """
    tomatoes = _film(answer, provider, ident).get("rotten_tomatoes")
    if not isinstance(tomatoes, dict):
        return {}
    found: Scores = {}
    for name, side in (("tomatoes", "critics"), ("popcorn", "users")):
        rating = _percent(tomatoes.get(f"{side}_rating"))
        certified = tomatoes.get(f"{side}_certified") is True
        if rating is not None or certified:
            found[name] = {"rating": rating, "votes": _count(tomatoes.get(f"{side}_rating_count")),
                           "certified": certified}
    return found


def _told(found: Scores) -> str:
    """Return what WhatsOn brought, for the log: "tomatoes (certified), popcorn"."""
    return ", ".join(name + (" (certified)" if entry["certified"] else "")
                     for name, entry in found.items()) or "nothing"


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


def fetch(provider: str, ident: str, key: str = "") -> tuple[Scores, float]:
    """Return a film's Rotten Tomatoes ratings and how long to keep them,
    asked with *key* where there is one.

    Raises _Spent while the limit is spent.  A film WhatsOn does not know
    has none for half a day, and one it could not be reached for none until
    it is asked again.
    """
    url = _URL.format(provider=provider, ident=quote(ident, safe=""))
    if key:
        url += _KEYED.format(key=quote(key, safe=""))
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
    _log(f"WhatsOn rated {provider} {ident}: {_told(found)}", xbmc.LOGINFO)
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
        # Until when the limit of each key ("" for none) is spent.
        self._spent: dict[str, float] = {}

    def scores(self, ids: Mapping[str, str], key: str = "") -> Scores | None:
        """Return WhatsOn's ratings for the film *ids* name, or None while
        there are none to show; asks for them with *key* the first time.

        A key given while the limit without one is spent is asked with at
        once.
        """
        if not ids:
            return None
        provider = "imdb" if "imdb" in ids else "tmdb"
        wanted = (key, provider, ids[provider])
        now = self._clock()
        with self._lock:
            kept = self._kept.get(wanted)
            if kept and now < kept[0]:
                return kept[1] or None
            if wanted in self._asking or now < self._spent.get(key, 0.0):
                return None
            self._asking.add(wanted)
        self._start(lambda: self._ask(wanted))
        return None

    def asking(self, ids: Mapping[str, str], key: str = "") -> bool:
        """Return whether WhatsOn is being asked for the film *ids* name."""
        if not ids:
            return False
        provider = "imdb" if "imdb" in ids else "tmdb"
        with self._lock:
            return (key, provider, ids[provider]) in self._asking

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
            key, provider, ident = wanted
            return fetch(provider, ident, key)
        except _Spent as spent:
            _log(f"WhatsOn's limit is spent; asking again in {int(spent.wait // 60)} min",
                 xbmc.LOGWARNING)
            with self._lock:
                self._spent[wanted[0]] = self._clock() + spent.wait
            return {}, 0.0


_LOOKUP = Lookup()


def api_key() -> str:
    """Return the WhatsOn API key the reader gave, or "" for none.

    It costs a look at the settings, so the caller reads it once a static
    interval (see ``SnapshotBuilder._rating_settings``).
    """
    try:
        return settings.addon().getSetting("web_whatson_key").strip()
    except RuntimeError:
        # The add-on is being updated; WhatsOn is asked without one meanwhile.
        return ""


def asking(ids: Mapping[str, str], key: str = "", lookup: Lookup = _LOOKUP) -> bool:
    """Return whether WhatsOn's answer for the film *ids* name is on its way."""
    return lookup.asking(ids, key)


def with_whatson(ratings: Ratings, lookup: Lookup = _LOOKUP, key: str = "") -> Ratings:
    """Return *ratings* with the Rotten Tomatoes ratings they lack from
    WhatsOn, where it has any, and each of the two marked certified where
    WhatsOn says Rotten Tomatoes certified it; the ones already there stand.

    WhatsOn is asked with *key* where there is one.
    """
    found = lookup.scores(ratings["ids"], key)
    if not found:
        return ratings
    held: Scores = {entry["source"]: {"rating": entry["rating"], "votes": entry["votes"]}
                    for entry in ratings["ratings"]}
    for source, name in _WANTED.items():
        if source not in held and found.get(name, {}).get("rating") is not None:
            held[source] = found[name]
    merged = ratings.copy()
    merged["ratings"] = rating_list(held)
    certified = {source for source, name in _WANTED.items()
                 if found.get(name, {}).get("certified")}
    for entry in merged["ratings"]:
        if entry["source"] in certified:
            entry["certified"] = True
    return merged
