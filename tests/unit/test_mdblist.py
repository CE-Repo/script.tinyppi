# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A film's ratings from MDBList (web/mdblist.py)."""

import http.client
import json
import threading
import urllib.error

import pytest

import xbmc
import xbmcaddon
from web import mdblist
from web.mdblist import Lookup, fetch, scores_of, with_mdblist
from web.ratings import no_ratings

# MDBList's answer for Jaws, as its documentation gives it (cut short).
JAWS = {"title": "Jaws", "ratings": [
    {"source": "imdb", "value": 8.1, "score": 81, "votes": 673852},
    {"source": "metacritic", "value": 87, "score": 87, "votes": 21},
    {"source": "metacriticuser", "value": None, "score": None, "votes": None},
    {"source": "trakt", "value": 78, "score": 78, "votes": 14033},
    {"source": "tomatoes", "value": 97, "score": 97, "votes": 102},
    {"source": "tmdb", "value": 76, "score": 76, "votes": 10114},
    {"source": "letterboxd", "value": 8, "score": 80, "votes": 876082},
    {"source": "rogerebert", "value": 4, "score": None, "votes": None},
    {"source": "myanimelist", "value": None, "score": None, "votes": None},
    {"source": "mdblist", "value": None, "score": 86, "votes": None},
]}


def refusal(code, headers=None):
    return urllib.error.HTTPError("https://api.mdblist.com/", code, "no", headers or {}, None)


# --- An answer -----------------------------------------------------------------

def test_an_answer_gives_each_rating_out_of_ten():
    assert scores_of(JAWS) == {
        "imdb": {"rating": 8.1, "votes": 673852},
        "metacritic": {"rating": 8.7, "votes": 21},
        "trakt": {"rating": 7.8, "votes": 14033},
        "tomatoes": {"rating": 9.7, "votes": 102},
        "tmdb": {"rating": 7.6, "votes": 10114},
        "letterboxd": {"rating": 8.0, "votes": 876082},
        # Four stars of four, with no score beside them.
        "rogerebert": {"rating": 10.0, "votes": None},
    }


@pytest.mark.parametrize("answer", [
    {}, {"ratings": "none"}, {"ratings": ["imdb", None]},
    {"ratings": [{"source": "imdb", "score": True}, {"source": "rogerebert", "value": False}]},
    {"ratings": [{"source": "rogerebert", "value": "4"}]},
])
def test_an_answer_of_another_shape_has_no_ratings(answer):
    assert scores_of(answer) == {}


# --- Asking ----------------------------------------------------------------------

def test_a_film_is_asked_for_by_its_id_with_the_key(monkeypatch):
    asked = []
    monkeypatch.setattr(mdblist, "_answer", lambda url: asked.append(url) or JAWS)
    found, keep = fetch("a key&more", "imdb", "tt0073195")
    assert asked == ["https://api.mdblist.com/imdb/movie/tt0073195?apikey=a%20key%26more"]
    assert found["imdb"] == {"rating": 8.1, "votes": 673852}
    assert keep == mdblist._KEPT


def test_a_refused_key_says_so(monkeypatch):
    def refuse(url):
        raise refusal(401)
    monkeypatch.setattr(mdblist, "_answer", refuse)
    with pytest.raises(mdblist._Refused):
        fetch("key", "imdb", "tt1")


@pytest.mark.parametrize(("headers", "wait"), [
    ({"Retry-After": "120"}, 120.0), ({}, 3600.0), ({"Retry-After": "soon"}, 3600.0),
    ({"Retry-After": "5"}, 60.0), ({"Retry-After": "999999"}, 86400.0),
])
def test_a_spent_limit_says_how_long_it_lasts(monkeypatch, headers, wait):
    def spent(url):
        raise refusal(429, headers)
    monkeypatch.setattr(mdblist, "_answer", spent)
    with pytest.raises(mdblist._Spent) as raised:
        fetch("key", "imdb", "tt1")
    assert raised.value.wait == wait


@pytest.mark.parametrize(("failure", "keep"), [
    # A film MDBList does not know stays unknown for as long as an answer.
    (refusal(404), mdblist._KEPT),
    # Anything else is asked again before long: a 403 too, which is what the
    # front MDBList stands behind answers when it does not like a caller.
    (refusal(403), mdblist._AGAIN),
    (refusal(500), mdblist._AGAIN),
    (urllib.error.URLError("no route"), mdblist._AGAIN),
    (TimeoutError(), mdblist._AGAIN),
    (ValueError("not JSON"), mdblist._AGAIN),
    (http.client.IncompleteRead(b""), mdblist._AGAIN),
])
def test_a_film_it_cannot_answer_for_has_no_ratings(monkeypatch, failure, keep):
    def fail(url):
        raise failure
    monkeypatch.setattr(mdblist, "_answer", fail)
    assert fetch("key", "imdb", "tt1") == ({}, keep)


class Response:
    def __init__(self, body):
        self.body = body
        self.asked = None

    def read(self, most):
        self.asked = most
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize(("body", "answer"), [
    (json.dumps(JAWS).encode(), JAWS), (b"[1, 2]", {}),
])
def test_the_answer_is_read_as_json(monkeypatch, body, answer):
    seen = {}
    response = Response(body)

    def urlopen(request, timeout):
        seen.update(url=request.full_url, timeout=timeout, accept=request.get_header("Accept"),
                    agent=request.get_header("User-agent"))
        return response

    monkeypatch.setattr(mdblist.urllib.request, "urlopen", urlopen)
    assert mdblist._answer("https://api.mdblist.com/x") == answer
    # Named as the add-on: MDBList's front turns Python's own name away.
    assert seen == {"url": "https://api.mdblist.com/x", "timeout": mdblist._TIMEOUT,
                    "accept": "application/json", "agent": "script.tinyppi (Kodi add-on)"}
    assert response.asked == mdblist._BIGGEST


# --- The films asked for ---------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def lookup(monkeypatch):
    """A lookup that asks only when told to, on a clock the test moves."""
    clock, started, asked = Clock(), [], []
    answers = {"found": ({"imdb": {"rating": 8.1, "votes": 9}}, mdblist._KEPT)}

    def fake_fetch(key, provider, ident):
        asked.append((key, provider, ident))
        found = answers["found"]
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(mdblist, "fetch", fake_fetch)
    found = Lookup(start=started.append, clock=clock)

    def run():
        while started:
            started.pop(0)()

    return found, clock, started, asked, answers, run


def test_a_film_is_asked_for_once_and_its_answer_kept(lookup):
    found, clock, started, asked, _answers, run = lookup
    ids = {"imdb": "tt1", "tmdb": "2"}
    # Asked for off the snapshot's thread: nothing to show yet, and asked once.
    assert found.scores("key", ids) is None
    assert found.scores("key", ids) is None
    assert len(started) == 1
    run()
    assert asked == [("key", "imdb", "tt1")]
    assert found.scores("key", ids) == {"imdb": {"rating": 8.1, "votes": 9}}
    # Half a day on, it is asked for again.
    clock.now += mdblist._KEPT + 1
    assert found.scores("key", ids) is None
    run()
    assert len(asked) == 2


def test_a_film_without_an_imdb_id_is_asked_for_by_its_tmdb_one(lookup):
    found, _clock, _started, asked, _answers, run = lookup
    found.scores("key", {"tmdb": "578"})
    run()
    assert asked == [("key", "tmdb", "578")]


@pytest.mark.parametrize(("key", "ids"), [("", {"imdb": "tt1"}), ("key", {})])
def test_no_key_or_no_film_asks_nothing(lookup, key, ids):
    found, _clock, started, _asked, _answers, _run = lookup
    assert found.scores(key, ids) is None
    assert started == []


def test_a_film_with_no_ratings_there_is_not_asked_for_again_soon(lookup):
    found, clock, started, asked, answers, run = lookup
    answers["found"] = ({}, mdblist._AGAIN)
    found.scores("key", {"imdb": "tt1"})
    run()
    assert found.scores("key", {"imdb": "tt1"}) is None
    assert started == []
    clock.now += mdblist._AGAIN + 1
    found.scores("key", {"imdb": "tt1"})
    assert len(started) == 1


def test_a_refused_key_is_not_sent_again(lookup):
    found, _clock, started, asked, answers, run = lookup
    answers["found"] = mdblist._Refused()
    found.scores("bad", {"imdb": "tt1"})
    run()
    assert found.scores("bad", {"imdb": "tt2"}) is None
    assert started == []
    assert any("refused the API key" in line for _level, line in xbmc.LOG)
    # A new key is tried.
    found.scores("good", {"imdb": "tt2"})
    assert len(started) == 1


def test_a_spent_limit_waits_for_the_day_to_end(lookup):
    found, clock, started, asked, answers, run = lookup
    answers["found"] = mdblist._Spent(120.0)
    found.scores("key", {"imdb": "tt1"})
    run()
    assert any("daily limit is spent; asking again in 2 min" in line for _level, line in xbmc.LOG)
    assert found.scores("key", {"imdb": "tt3"}) is None
    assert started == []
    clock.now += 121
    found.scores("key", {"imdb": "tt1"})
    assert len(started) == 1


def test_a_film_whose_asking_fails_of_itself_can_be_asked_for_again(lookup):
    found, _clock, started, _asked, answers, run = lookup
    answers["found"] = RuntimeError("a fault")
    found.scores("key", {"imdb": "tt1"})
    with pytest.raises(RuntimeError):
        run()
    found.scores("key", {"imdb": "tt1"})
    assert len(started) == 1


def test_only_so_many_films_are_kept(lookup, monkeypatch):
    found, _clock, _started, _asked, _answers, run = lookup
    monkeypatch.setattr(mdblist, "_LIMIT", 2)
    for ident in ("tt1", "tt2", "tt3"):
        found.scores("key", {"imdb": ident})
        run()
    assert [wanted[2] for wanted in found._kept] == ["tt2", "tt3"]


def test_the_asking_runs_on_a_thread_of_its_own():
    done = threading.Event()
    mdblist._in_background(done.set)
    assert done.wait(5)


# --- Over the library's ----------------------------------------------------------------

class Answers:
    def __init__(self, found):
        self.found = found
        self.asked = []

    def scores(self, key, ids):
        self.asked.append((key, ids))
        return self.found


def held(**extra):
    ratings = no_ratings()
    ratings.update(extra)
    return ratings


def test_mdblists_ratings_come_first_and_the_librarys_stand_beside_them():
    xbmcaddon.SETTINGS["web_mdblist_key"] = "  KEY  "
    answers = Answers(scores_of(JAWS))
    library = held(ratings=[{"source": "tmdb", "rating": 8.1, "votes": 28562},
                            {"source": "rottentomatoes", "rating": 9.0, "votes": 0},
                            {"source": "filmstarts", "rating": 8.0, "votes": 0}],
                   mpaa="FSK 12", ids={"imdb": "tt0073195"})
    merged = with_mdblist(library, answers)
    assert answers.asked == [("KEY", {"imdb": "tt0073195"})]
    assert [(entry["source"], entry["rating"]) for entry in merged["ratings"]] == [
        ("imdb", 8.1), ("tmdb", 7.6), ("trakt", 7.8), ("letterboxd", 8.0), ("metacritic", 8.7),
        ("rottentomatoes", 9.7), ("rogerebert", 10.0), ("filmstarts", 8.0)]
    # The rest is the library's.
    assert merged["mpaa"] == "FSK 12"
    assert library["ratings"][0]["rating"] == 8.1


def test_without_an_answer_the_librarys_ratings_stand():
    library = held(ratings=[{"source": "tmdb", "rating": 8.1, "votes": 3}])
    assert with_mdblist(library, Answers(None)) is library


def test_without_a_key_nothing_is_asked(monkeypatch):
    answers = Answers(None)
    with_mdblist(held(ids={"imdb": "tt1"}), answers)
    assert answers.asked == [("", {"imdb": "tt1"})]

    def updating():
        raise RuntimeError("being updated")

    monkeypatch.setattr(mdblist.settings, "addon", updating)
    xbmcaddon.SETTINGS["web_mdblist_key"] = "KEY"
    with_mdblist(held(), answers)
    assert answers.asked[-1] == ("", {})
