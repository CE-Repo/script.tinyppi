# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing film's ratings from MDBList, for a reader who gave the add-on
an API key (``web_mdblist_key``).

MDBList gathers what IMDb, TMDb, Trakt, Letterboxd, Rotten Tomatoes (its
critics and its audience), Metacritic (its critics and its users), Roger
Ebert and MyAnimeList gave a film into one answer.  Where it has a rating the
library has one from too, MDBList's is shown; the library's own stand beside
them.  Without a key, for a film MDBList does not know or cannot be reached
for, the library's ratings are shown alone (see web.ratings) -- and always
for an episode: MDBList rates shows, not episodes.

A film is asked for once, by its IMDb id or else its TMDb one, off the
thread that builds the snapshot: the card shows the library's ratings until
the answer is in, and the answer is kept for half a day.  A key MDBList
refuses is not sent again, and a day's limit spent waits for the day's end.

A film's place in the IMDb Top 250 is read off a public MDBList list that
follows IMDb's chart, key or no key: scrapers seldom fill the library's, and
it goes stale the day after it is scraped.  The list says nothing of what is
playing -- it is the same 250 films for everyone -- and is fetched at most
twice a day.  Until it is in, and for a film without an IMDb id, the
library's place stands.
"""

import http.client
import json
import re
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

_URL = "https://api.mdblist.com/{provider}/movie/{ident}?apikey={key}"
# The IMDb Top 250, in its order; public, and asked for without a key.
_CHART_URL = "https://mdblist.com/lists/snoak/imdb-top-250-movies/json"
# The add-on names itself: the front MDBList stands behind turns away
# Python's own User-Agent (and none at all) with a 403 of its own.
_AGENT = "script.tinyppi (Kodi add-on)"
_TIMEOUT = 10.0
# A film's answer is a few kilobytes, the chart some forty; anything past
# this is neither.
_BIGGEST = 512 * 1024

# How long an answer is kept, a film MDBList does not know included, and how
# long a film it could not be reached for waits before it is asked again.
_KEPT = 12 * 3600.0
_AGAIN = 10 * 60.0
# How long a day's spent limit waits when MDBList does not say.
_SPENT = 3600.0
# The films kept at once; the oldest goes first.
_LIMIT = 256

# Ratings out of ten by name, as web.ratings.rating_list reads them.
Scores = dict[str, Json]
# What a film is asked for by: the key, "imdb" or "tmdb", and the id.
_Wanted = tuple[str, str, str]


class _Refused(Exception):
    """MDBList refused the key."""


class _Spent(Exception):
    """The day's limit is spent; *wait* is how many seconds are left of it."""

    def __init__(self, wait: float) -> None:
        super().__init__(wait)
        self.wait = wait


def _out_of_ten(entry: Json) -> float | None:
    """Return one of MDBList's ratings out of ten, or None for none.

    MDBList gives each on its source's own scale and as a score out of 100
    beside it; Roger Ebert's stars, out of four, come without the score.
    """
    score, value = entry.get("score"), entry.get("value")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return score / 10
    if entry.get("source") == "rogerebert" and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        return value * 2.5
    return None


def scores_of(answer: Json) -> Scores:
    """Return the ratings in one of MDBList's answers, by source.

    Its own score, made of the others, is no rating of its own and is left
    out; a source with no rating for the film comes with nulls.
    """
    found: Scores = {}
    entries = answer.get("ratings")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("source") == "mdblist":
            continue
        rating = _out_of_ten(entry)
        if rating is not None:
            found[str(entry.get("source") or "")] = {"rating": rating, "votes": entry.get("votes")}
    return found


def _retry_after(error: urllib.error.HTTPError) -> float:
    """Return how many seconds MDBList says the spent limit has left."""
    try:
        wait = float(error.headers.get("Retry-After") or _SPENT)
    except ValueError:
        wait = _SPENT
    return min(max(wait, 60.0), 86400.0)


def _json(url: str) -> object:
    """Return MDBList's answer at *url*, read as JSON."""
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": _AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read(_BIGGEST))


def _answer(url: str) -> Json:
    """Return MDBList's answer at *url* as a JSON object ({} for another)."""
    found = _json(url)
    return found if isinstance(found, dict) else {}


def fetch(key: str, provider: str, ident: str) -> tuple[Scores, float]:
    """Return a film's ratings and how long to keep them.

    Raises _Refused for a key MDBList will not take (a 401: a 403 can be
    the front it stands behind, and is tried again) and _Spent while the
    day's limit is spent.  A film it does not know has no ratings for half a
    day, and one it could not be reached for none until it is asked again.
    """
    url = _URL.format(provider=provider, ident=quote(ident, safe=""), key=quote(key, safe=""))
    try:
        return scores_of(_answer(url)), _KEPT
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise _Refused from None
        if error.code == 429:
            raise _Spent(_retry_after(error)) from None
        _log(f"MDBList answered {error.code} for {provider} {ident}")
        return {}, _KEPT if error.code == 404 else _AGAIN
    except (OSError, ValueError, http.client.HTTPException) as error:
        _log(f"MDBList could not be asked for {provider} {ident}: {type(error).__name__}")
        return {}, _AGAIN


# An IMDb id as Kodi and MDBList keep one: "tt" and its digits.
_IMDB_ID = re.compile(r"tt\d+")


def places_of(answer: object) -> dict[str, int]:
    """Return the films in the chart, by IMDb id, and the place of each.

    The list comes in the chart's order; an entry of another shape keeps its
    place, so the ones after it keep theirs.
    """
    places: dict[str, int] = {}
    entries = answer if isinstance(answer, list) else []
    for place, entry in enumerate(entries[:250], start=1):
        ident = entry.get("imdb_id") if isinstance(entry, dict) else None
        if isinstance(ident, str) and _IMDB_ID.fullmatch(ident):
            places.setdefault(ident, place)
    return places


def fetch_chart() -> tuple[dict[str, int], float]:
    """Return the IMDb Top 250 and how long to keep it.

    A chart that could not be had, or came empty, is asked for again before
    long.
    """
    try:
        places = places_of(_json(_CHART_URL))
    except (OSError, ValueError, http.client.HTTPException) as error:
        _log(f"MDBList's IMDb Top 250 could not be had: {type(error).__name__}")
        return {}, _AGAIN
    return places, _KEPT if places else _AGAIN


def _in_background(work: Callable[[], None]) -> None:
    """Run *work* on a thread of its own, which does not hold up Kodi's exit."""
    threading.Thread(target=work, name="TinyPPI MDBList", daemon=True).start()


class Lookup:
    """MDBList's answers for the films asked for, and the asking."""

    def __init__(self, start: Callable[[Callable[[], None]], None] = _in_background,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._start = start
        self._clock = clock
        self._lock = threading.Lock()
        # When each answer goes stale, and the answer.
        self._kept: dict[_Wanted, tuple[float, Scores]] = {}
        self._asking: set[_Wanted] = set()
        self._refused: set[str] = set()
        self._spent_until = 0.0

    def scores(self, key: str, ids: Mapping[str, str]) -> Scores | None:
        """Return MDBList's ratings for the film *ids* name, or None while
        there are none to show; asks for them the first time.
        """
        if not key or key in self._refused or not ids:
            return None
        provider = "imdb" if "imdb" in ids else "tmdb"
        wanted = (key, provider, ids[provider])
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
        """Ask MDBList for one film and keep its answer.

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
        key, provider, ident = wanted
        try:
            return fetch(key, provider, ident)
        except _Refused:
            _log("MDBList refused the API key; the library's ratings are shown",
                 xbmc.LOGWARNING)
            self._refused.add(key)
            return {}, _KEPT
        except _Spent as spent:
            _log(f"MDBList's daily limit is spent; asking again in {int(spent.wait // 60)} min",
                 xbmc.LOGWARNING)
            self._spent_until = self._clock() + spent.wait
            return {}, 0.0


class Chart:
    """The IMDb Top 250, and the asking for it."""

    def __init__(self, start: Callable[[Callable[[], None]], None] = _in_background,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._start = start
        self._clock = clock
        self._lock = threading.Lock()
        self._places: dict[str, int] = {}
        # When it is asked for again; at once, the first time.
        self._until = 0.0
        self._asking = False

    def place(self, imdb: str) -> int | None:
        """Return the film's place in the chart, 0 for none, or None while
        the chart is not in; asks for it when it is due.

        A chart that could not be had again leaves the last one standing.
        """
        with self._lock:
            due = not self._asking and self._clock() >= self._until
            self._asking = self._asking or due
            known = self._places.get(imdb, 0) if self._places else None
        if due:
            self._start(self._ask)
        return known

    def _ask(self) -> None:
        """Ask for the chart and keep it; free to be asked for again however
        the asking ends."""
        try:
            places, keep = fetch_chart()
        finally:
            with self._lock:
                self._asking = False
                self._until = self._clock() + _AGAIN
        with self._lock:
            self._until = self._clock() + keep
            if places:
                self._places = places


_LOOKUP = Lookup()
_CHART = Chart()


def _key() -> str:
    """Return the MDBList API key the reader gave, or ""."""
    try:
        return settings.addon().getSetting("web_mdblist_key").strip()
    except RuntimeError:
        # The add-on is being updated; the library's ratings will do.
        return ""


def with_mdblist(ratings: Ratings, lookup: Lookup = _LOOKUP,
                 chart: Chart = _CHART) -> Ratings:
    """Return *ratings* with MDBList's for the film, where it has any, and
    its place in the IMDb Top 250 as the chart has it.

    MDBList's come first, and the library's own stand beside them for a
    source MDBList has none from.
    """
    merged = ratings.copy()
    imdb = ratings["ids"].get("imdb")
    place = chart.place(imdb) if imdb else None
    if place is not None:
        merged["top250"] = place
    found = lookup.scores(_key(), ratings["ids"])
    if found:
        held: Scores = dict(found)
        for entry in ratings["ratings"]:
            held.setdefault(entry["source"], {"rating": entry["rating"], "votes": entry["votes"]})
        merged["ratings"] = rating_list(held)
    return merged
