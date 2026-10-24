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
from web.ratings import IMDB_ID, rating_list
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


# The scale each source's own value is on, for one MDBList sends without
# its score out of 100: Roger Ebert's stars always, the others now and then.
# Rotten Tomatoes' audience has gone by three names in its answers.
_SCALES = {"imdb": 10, "metacriticuser": 10, "myanimelist": 10, "letterboxd": 5,
           "rogerebert": 4, "metacritic": 100, "trakt": 100, "tomatoes": 100,
           "popcorn": 100, "tomatoesaudience": 100, "audience": 100, "tmdb": 100}


def _figure(value: object) -> float | None:
    """Return *value* as a number, where JSON gave one -- MDBList now and
    then sends a figure as text ("73") -- or None ("n/a", null, junk)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        found = float(value)
    else:
        try:
            found = float(str(value).strip()) if isinstance(value, str) else math.nan
        except ValueError:
            return None
    return found if math.isfinite(found) else None


def _source(entry: Json) -> str:
    """Return the name an entry of MDBList's answer gives its source."""
    return str(entry.get("source") or "").strip().lower()


def _out_of_ten(entry: Json) -> float | None:
    """Return one of MDBList's ratings out of ten, or None for none.

    MDBList gives each on its source's own scale and as a score out of 100
    beside it.  Without the score the value is read on its source's scale;
    a source whose scale is not known is left out rather than guessed at.
    """
    score, value = _figure(entry.get("score")), _figure(entry.get("value"))
    if score is not None:
        return score / 10
    scale = _SCALES.get(_source(entry))
    if scale and value is not None:
        return value * 10 / scale
    return None


def scores_of(answer: Json) -> Scores:
    """Return the ratings in one of MDBList's answers, by source.

    Its own score, made of the others, is no rating of its own and is left
    out; a source with no rating for the film comes with nulls.
    """
    found: Scores = {}
    for entry in _entries(answer):
        rating = _out_of_ten(entry)
        if rating is not None:
            found[_source(entry)] = {"rating": rating, "votes": entry.get("votes")}
    return found


def _entries(answer: Json) -> list[Json]:
    """Return the entries of one of MDBList's answers, but its own score."""
    entries = answer.get("ratings")
    return [entry for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict) and _source(entry) != "mdblist"]


def _told(provider: str, ident: str, answer: Json, found: Scores) -> None:
    """Log what MDBList brought for a film, and what of it could not be
    read, so a rating missing from the card can be traced."""
    left = sorted({_source(entry) for entry in _entries(answer)} - set(found))
    _log(f"MDBList rated {provider} {ident}: {', '.join(found) or 'nothing'}"
         + (f"; no rating from {', '.join(left)}" if left else ""), xbmc.LOGINFO)


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
        answer = _answer(url)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise _Refused from None
        if error.code == 429:
            raise _Spent(_retry_after(error)) from None
        # Not a debug line: without it a card short of MDBList's ratings
        # says nothing of why.
        _log(f"MDBList answered {error.code} for {provider} {ident}", xbmc.LOGWARNING)
        return {}, _KEPT if error.code == 404 else _AGAIN
    except (OSError, ValueError, http.client.HTTPException) as error:
        _log(f"MDBList could not be asked for {provider} {ident}: {type(error).__name__}",
             xbmc.LOGWARNING)
        return {}, _AGAIN
    found = scores_of(answer)
    _told(provider, ident, answer, found)
    return found, _KEPT


def places_of(answer: object) -> dict[str, int]:
    """Return the films in the chart, by IMDb id, and the place of each.

    The list comes in the chart's order; an entry of another shape keeps its
    place, so the ones after it keep theirs.
    """
    places: dict[str, int] = {}
    entries = answer if isinstance(answer, list) else []
    for place, entry in enumerate(entries[:250], start=1):
        ident = entry.get("imdb_id") if isinstance(entry, dict) else None
        if isinstance(ident, str) and IMDB_ID.fullmatch(ident):
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


def _wanted(key: str, ids: Mapping[str, str]) -> _Wanted:
    """Return what a film is asked for by: its IMDb id, else its TMDb one."""
    provider = "imdb" if "imdb" in ids else "tmdb"
    return (key, provider, ids[provider])


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
        if not key or not ids:
            return None
        wanted = _wanted(key, ids)
        now = self._clock()
        with self._lock:
            if key in self._refused:
                return None
            kept = self._kept.get(wanted)
            if kept and now < kept[0]:
                return kept[1] or None
            if wanted in self._asking or now < self._spent_until:
                return None
            self._asking.add(wanted)
        self._start(lambda: self._ask(wanted))
        return None

    def asking(self, key: str, ids: Mapping[str, str]) -> bool:
        """Return whether MDBList is being asked for the film *ids* name."""
        if not key or not ids:
            return False
        with self._lock:
            return _wanted(key, ids) in self._asking

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
            with self._lock:
                self._refused.add(key)
            return {}, _KEPT
        except _Spent as spent:
            _log(f"MDBList's daily limit is spent; asking again in {int(spent.wait // 60)} min",
                 xbmc.LOGWARNING)
            with self._lock:
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


def api_key() -> str:
    """Return the MDBList API key the reader gave, or "".

    It costs a look at the settings, so the caller reads it once a static
    interval (see ``SnapshotBuilder._rating_settings``) rather than once a
    snapshot.
    """
    try:
        return settings.addon().getSetting("web_mdblist_key").strip()
    except RuntimeError:
        # The add-on is being updated; the library's ratings will do.
        return ""


def asking(key: str, ids: Mapping[str, str], lookup: Lookup = _LOOKUP) -> bool:
    """Return whether MDBList's answer for the film *ids* name is on its
    way, so what it lacks is not looked for elsewhere before it is in."""
    return lookup.asking(key, ids)


def with_mdblist(ratings: Ratings, lookup: Lookup = _LOOKUP,
                 chart: Chart = _CHART, key: str | None = None) -> Ratings:
    """Return *ratings* with MDBList's for the film, where it has any, and
    its place in the IMDb Top 250 as the chart has it.

    *key* is the API key to ask with; None reads it from the settings.

    MDBList's come first, and the library's own stand beside them for a
    source MDBList has none from.
    """
    merged = ratings.copy()
    imdb = ratings["ids"].get("imdb")
    place = chart.place(imdb) if imdb else None
    if place is not None:
        merged["top250"] = place
    found = lookup.scores(api_key() if key is None else key, ratings["ids"])
    if found:
        held: Scores = dict(found)
        for entry in ratings["ratings"]:
            held.setdefault(entry["source"], {"rating": entry["rating"], "votes": entry["votes"]})
        merged["ratings"] = rating_list(held)
    return merged
