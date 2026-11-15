# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""How many awards a title won and was nominated for in all, from OMDb, for
a reader who gave the add-on an API key (``web_omdb_key``).

The big four stand on the plot card as shields, from a list the add-on
carries (see web.awards).  OMDb (omdbapi.com) has IMDb's count of every
award there is as one sentence -- "Won 2 Oscars. 45 wins & 80 nominations
total" -- of which the two totals are read and shown as a line under the
shields.

Asked only by the details view, when one title is opened (see
web.library.details), never for a list: a free key answers 1,000 times a
day.  A title is asked for by its IMDb id, an episode by its show's, and
the answer is kept for a day; a title OMDb could not be reached for is asked
again before long.  A key OMDb refuses, or whose day is spent -- it answers
401 to both -- rests for an hour.
"""

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlencode

import xbmc
from core import settings
from core.log import channel
from web.payloads import AwardsTotal
from web.ratings import IMDB_ID

_log = channel("web")

_URL = "https://www.omdbapi.com/?"
_AGENT = "script.tinyppi (Kodi add-on)"
# The details view waits on it, so not for long.
_TIMEOUT = 4.0
# A title's answer is a few kilobytes.
_BIGGEST = 256 * 1024
# How long an answer is kept, a title OMDb does not know included, how long
# one it could not be reached for waits, and how long a refused key rests.
_KEPT = 24 * 3600.0
_AGAIN = 5 * 60.0
_RESTS = 3600.0
# The titles kept at once; the oldest goes first.
_LIMIT = 256
# The totals in OMDb's sentence: "45 wins", "1 win", "80 nominations", of
# four figures at most: no title has more.  What
# stands before them ("Won 2 Oscars.", "Nominated for 1 BAFTA Award.") is of
# the big awards, counted among the totals already.
_WINS = re.compile(r"\b(\d{1,4}) wins?\b")
_NOMINATIONS = re.compile(r"\b(\d{1,4}) nominations?\b")

_CACHE: OrderedDict[tuple[str, str], tuple[float, AwardsTotal | None]] = OrderedDict()
# When each key OMDb refused is tried again.
_RESTING: dict[str, float] = {}
_LOCK = Lock()
_clock = time.monotonic


class _Refused(Exception):
    """OMDb refused the key, or its day's limit is spent."""


def api_key() -> str:
    """Return the OMDb API key the reader gave, or ""."""
    try:
        return settings.addon().getSetting("web_omdb_key").strip()
    except RuntimeError:
        # The add-on is being updated; the shields will do.
        return ""


def totals_of(answer: object) -> AwardsTotal | None:
    """Return the totals in one of OMDb's answers, or None where it names
    none ("N/A", a title it does not know, junk)."""
    said = answer.get("Awards") if isinstance(answer, dict) else None
    if not isinstance(said, str):
        return None
    won, nominated = (int(found.group(1)) if found else 0
                      for found in (_WINS.search(said), _NOMINATIONS.search(said)))
    if not won and not nominated:
        return None
    return {"won": won, "nominated": nominated}


def fetch(key: str, imdb: str) -> tuple[AwardsTotal | None, float]:
    """Return a title's totals and how long to keep them.

    Raises _Refused for a key OMDb will not take or whose day is spent.  A
    title it does not know has none for a day, and one it could not be
    reached for none until it is asked again.
    """
    request = urllib.request.Request(_URL + urlencode({"i": imdb, "apikey": key}),
                                     headers={"Accept": "application/json",
                                              "User-Agent": _AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            answer = json.loads(response.read(_BIGGEST))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise _Refused from None
        _log(f"OMDb answered {error.code} for {imdb}", xbmc.LOGWARNING)
        return None, _AGAIN
    except (OSError, ValueError, http.client.HTTPException) as error:
        _log(f"OMDb could not be asked for {imdb}: {type(error).__name__}", xbmc.LOGWARNING)
        return None, _AGAIN
    return totals_of(answer), _KEPT


def awards_total(key: str, imdb: str) -> AwardsTotal | None:
    """Return how many awards the title *imdb* names won and was nominated
    for in all, or None: without a key or an IMDb id, for a title OMDb has
    none for, and while it cannot be asked."""
    if not key or not IMDB_ID.fullmatch(imdb):
        return None
    wanted = (key, imdb)
    with _LOCK:
        now = _clock()
        kept = _CACHE.get(wanted)
        if kept is not None and now < kept[0]:
            return kept[1]
        if now < _RESTING.get(key, 0.0):
            return None
    try:
        found, keep = fetch(key, imdb)
    except _Refused:
        _log("OMDb refused the API key, or its daily limit is spent; asking again in an hour",
             xbmc.LOGWARNING)
        with _LOCK:
            _RESTING.clear()
            _RESTING[key] = _clock() + _RESTS
        return None
    with _LOCK:
        _CACHE.pop(wanted, None)
        _CACHE[wanted] = (_clock() + keep, found)
        while len(_CACHE) > _LIMIT:
            _CACHE.popitem(last=False)
    return found
