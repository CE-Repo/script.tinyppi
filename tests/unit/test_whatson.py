# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Rotten Tomatoes' ratings of a film from WhatsOn (web/whatson.py)."""

import http.client
import json
import threading
import urllib.error

import pytest

import xbmc
import xbmcaddon
from web import whatson
from web.ratings import no_ratings
from web.whatson import Lookup, allowed, fetch, missing, scores_of, with_whatson

# WhatsOn's answer for The Matrix (cut short).
MATRIX = {"page": 1, "total_pages": 1, "total_results": 1, "results": [{
    "id": 603, "item_type": "movie", "title": "The Matrix",
    "imdb": {"id": "tt0133093", "users_rating": 8.7, "users_rating_count": 2255431},
    "tmdb": {"id": 603, "users_rating": 8.25},
    "rotten_tomatoes": {"id": "matrix", "users_rating": 85, "users_rating_count": 167410,
                        "critics_rating": 83, "critics_rating_count": 209,
                        "users_certified": False, "critics_certified": True},
}]}


def refusal(code, headers=None):
    return urllib.error.HTTPError("https://whatson-api.onrender.com/", code, "no",
                                  headers or {}, None)


# --- An answer -----------------------------------------------------------------

def test_an_answer_gives_the_tomatometer_and_the_popcornmeter_out_of_ten():
    assert scores_of(MATRIX, "imdb", "tt0133093") == {
        "tomatoes": {"rating": 8.3, "votes": 209},
        "popcorn": {"rating": 8.5, "votes": 167410},
    }


def test_of_several_films_the_one_the_id_is_its_own_is_taken():
    other = {"item_type": "movie", "imdb": {"id": "tt1"},
             "rotten_tomatoes": {"critics_rating": 10, "users_rating": 20}}
    show = {"item_type": "tvshow", "tmdb": {"id": 603},
            "rotten_tomatoes": {"critics_rating": 30}}
    answer = {"results": [show, other, MATRIX["results"][0]]}
    assert scores_of(answer, "tmdb", "603")["tomatoes"]["rating"] == 8.3
    # None is: the first film is.
    assert scores_of(answer, "imdb", "tt2")["tomatoes"]["rating"] == 1.0


def test_a_side_without_a_rating_is_left_out():
    answer = {"results": [{"item_type": "movie", "rotten_tomatoes": {
        "critics_rating": None, "users_rating": 91, "users_rating_count": True}}]}
    assert scores_of(answer, "imdb", "tt1") == {"popcorn": {"rating": 9.1, "votes": None}}


@pytest.mark.parametrize("answer", [
    {}, {"results": "none"}, {"results": [None, "film"]},
    {"results": [{"item_type": "tvshow", "rotten_tomatoes": {"critics_rating": 80}}]},
    {"results": [{"item_type": "movie"}]},
    {"results": [{"item_type": "movie", "rotten_tomatoes": "fresh"}]},
    {"results": [{"item_type": "movie", "rotten_tomatoes": {
        "critics_rating": "83", "users_rating": True}}]},
    {"results": [{"item_type": "movie", "rotten_tomatoes": {
        "critics_rating": 0, "users_rating": 101}}]},
    {"results": [{"item_type": "movie", "rotten_tomatoes": {
        "critics_rating": float("nan"), "users_rating": float("inf")}}]},
])
def test_an_answer_of_another_shape_has_no_ratings(answer):
    assert scores_of(answer, "imdb", "tt1") == {}


# --- Asking ----------------------------------------------------------------------

def test_a_film_is_asked_for_by_its_id_and_logged(monkeypatch):
    asked = []
    monkeypatch.setattr(whatson, "_answer", lambda url: asked.append(url) or MATRIX)
    found, keep = fetch("imdb", "tt0133093")
    assert asked == ["https://whatson-api.onrender.com/?imdbId=tt0133093&item_type=movie"]
    assert set(found) == {"tomatoes", "popcorn"} and keep == whatson._KEPT
    assert (xbmc.LOGINFO, "TinyPPI [web]: WhatsOn rated imdb tt0133093: tomatoes, popcorn") \
        in xbmc.LOG
    monkeypatch.setattr(whatson, "_answer", lambda url: asked.append(url) or {})
    assert fetch("tmdb", "a b") == ({}, whatson._KEPT)
    assert asked[-1] == "https://whatson-api.onrender.com/?tmdbId=a%20b&item_type=movie"
    assert any(line.endswith("WhatsOn rated tmdb a b: nothing") for _level, line in xbmc.LOG)


@pytest.mark.parametrize(("headers", "wait"), [
    ({"Retry-After": "120"}, 120.0), ({}, 3600.0), ({"Retry-After": "soon"}, 3600.0),
    ({"Retry-After": "5"}, 60.0), ({"Retry-After": "999999"}, 86400.0),
])
def test_a_spent_limit_says_how_long_it_lasts(monkeypatch, headers, wait):
    def spent(url):
        raise refusal(429, headers)
    monkeypatch.setattr(whatson, "_answer", spent)
    with pytest.raises(whatson._Spent) as raised:
        fetch("imdb", "tt1")
    assert raised.value.wait == wait


@pytest.mark.parametrize(("failure", "keep"), [
    # A film WhatsOn does not know stays unknown for as long as an answer.
    (refusal(404), whatson._KEPT),
    (refusal(503), whatson._AGAIN),
    (urllib.error.URLError("no route"), whatson._AGAIN),
    (TimeoutError(), whatson._AGAIN),
    (ValueError("not JSON"), whatson._AGAIN),
    (http.client.IncompleteRead(b""), whatson._AGAIN),
])
def test_a_film_it_cannot_answer_for_has_no_ratings(monkeypatch, failure, keep):
    def fail(url):
        raise failure
    monkeypatch.setattr(whatson, "_answer", fail)
    assert fetch("imdb", "tt1") == ({}, keep)
    assert any("WhatsOn" in line and "tt1" in line for _level, line in xbmc.LOG)


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
    (json.dumps(MATRIX).encode(), MATRIX), (b"[1, 2]", {}),
])
def test_the_answer_is_read_as_json(monkeypatch, body, answer):
    seen = {}
    response = Response(body)

    def urlopen(request, timeout):
        seen.update(url=request.full_url, timeout=timeout, accept=request.get_header("Accept"),
                    agent=request.get_header("User-agent"))
        return response

    monkeypatch.setattr(whatson.urllib.request, "urlopen", urlopen)
    assert whatson._answer("https://whatson-api.onrender.com/x") == answer
    assert seen == {"url": "https://whatson-api.onrender.com/x", "timeout": whatson._TIMEOUT,
                    "accept": "application/json", "agent": "script.tinyppi (Kodi add-on)"}
    assert response.asked == whatson._BIGGEST


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
    answers = {"found": ({"tomatoes": {"rating": 8.3, "votes": 209}}, whatson._KEPT)}

    def fake_fetch(provider, ident):
        asked.append((provider, ident))
        found = answers["found"]
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(whatson, "fetch", fake_fetch)
    found = Lookup(start=started.append, clock=clock)

    def run():
        while started:
            started.pop(0)()

    return found, clock, started, asked, answers, run


def test_a_film_is_asked_for_once_and_its_answer_kept(lookup):
    found, clock, started, asked, _answers, run = lookup
    ids = {"imdb": "tt1", "tmdb": "2"}
    assert found.scores(ids) is None
    assert found.scores(ids) is None
    assert len(started) == 1
    run()
    assert asked == [("imdb", "tt1")]
    assert found.scores(ids) == {"tomatoes": {"rating": 8.3, "votes": 209}}
    clock.now += whatson._KEPT + 1
    assert found.scores(ids) is None
    run()
    assert len(asked) == 2


def test_a_film_without_an_imdb_id_is_asked_for_by_its_tmdb_one(lookup):
    found, _clock, _started, asked, _answers, run = lookup
    found.scores({"tmdb": "578"})
    run()
    assert asked == [("tmdb", "578")]


def test_a_title_without_ids_asks_nothing(lookup):
    found, _clock, started, _asked, _answers, _run = lookup
    assert found.scores({}) is None
    assert started == []


def test_a_film_with_no_ratings_there_is_not_asked_for_again_soon(lookup):
    found, clock, started, _asked, answers, run = lookup
    answers["found"] = ({}, whatson._AGAIN)
    found.scores({"imdb": "tt1"})
    run()
    assert found.scores({"imdb": "tt1"}) is None
    assert started == []
    clock.now += whatson._AGAIN + 1
    found.scores({"imdb": "tt1"})
    assert len(started) == 1


def test_a_spent_limit_waits_as_long_as_whatson_says(lookup):
    found, clock, started, _asked, answers, run = lookup
    answers["found"] = whatson._Spent(120.0)
    found.scores({"imdb": "tt1"})
    run()
    assert any("WhatsOn's limit is spent; asking again in 2 min" in line
               for _level, line in xbmc.LOG)
    assert found.scores({"imdb": "tt3"}) is None
    assert started == []
    clock.now += 121
    found.scores({"imdb": "tt1"})
    assert len(started) == 1


def test_a_film_whose_asking_fails_of_itself_can_be_asked_for_again(lookup):
    found, _clock, started, _asked, answers, run = lookup
    answers["found"] = RuntimeError("a fault")
    found.scores({"imdb": "tt1"})
    with pytest.raises(RuntimeError):
        run()
    found.scores({"imdb": "tt1"})
    assert len(started) == 1


def test_only_so_many_films_are_kept(lookup, monkeypatch):
    found, _clock, _started, _asked, _answers, run = lookup
    monkeypatch.setattr(whatson, "_LIMIT", 2)
    for ident in ("tt1", "tt2", "tt3"):
        found.scores({"imdb": ident})
        run()
    assert [wanted[1] for wanted in found._kept] == ["tt2", "tt3"]


def test_the_asking_runs_on_a_thread_of_its_own():
    done = threading.Event()
    whatson._in_background(done.set)
    assert done.wait(5)


# --- Only what is missing --------------------------------------------------------------

class Answers:
    def __init__(self, found):
        self.found = found
        self.asked = []

    def scores(self, ids):
        self.asked.append(ids)
        return self.found


def held(*sources, **extra):
    ratings = no_ratings()
    ratings["ratings"] = [{"source": source, "rating": 7.0, "votes": 1} for source in sources]
    ratings["ids"] = {"imdb": "tt0133093"}
    ratings.update(extra)
    return ratings


def test_a_film_with_both_is_not_asked_for():
    answers = Answers(scores_of(MATRIX, "imdb", "tt0133093"))
    ratings = held("imdb", "rottentomatoes", "popcorn")
    assert not missing(ratings)
    assert with_whatson(ratings, answers) is ratings
    assert answers.asked == []


def test_what_is_missing_is_filled_in_and_what_is_there_stands():
    answers = Answers(scores_of(MATRIX, "imdb", "tt0133093"))
    ratings = held("imdb", "metacritic", "rottentomatoes", "filmstarts")
    assert missing(ratings)
    merged = with_whatson(ratings, answers)
    assert answers.asked == [{"imdb": "tt0133093"}]
    assert [(entry["source"], entry["rating"]) for entry in merged["ratings"]] == [
        ("imdb", 7.0), ("metacritic", 7.0), ("rottentomatoes", 7.0), ("popcorn", 8.5),
        ("filmstarts", 7.0)]
    assert merged["ids"] == ratings["ids"] and len(ratings["ratings"]) == 4


def test_both_are_filled_in_where_neither_is_there():
    merged = with_whatson(held("imdb"), Answers(scores_of(MATRIX, "imdb", "tt0133093")))
    assert [entry["source"] for entry in merged["ratings"]] == [
        "imdb", "rottentomatoes", "popcorn"]
    assert merged["ratings"][1] == {"source": "rottentomatoes", "rating": 8.3, "votes": 209}


def test_without_an_answer_the_ratings_stand():
    ratings = held("imdb")
    assert with_whatson(ratings, Answers(None)) is ratings


def test_whatson_is_asked_unless_the_reader_says_not_to(monkeypatch):
    assert allowed() is True
    xbmcaddon.SETTINGS["web_whatson"] = "false"
    assert allowed() is False
    xbmcaddon.SETTINGS["web_whatson"] = "true"

    def updating():
        raise RuntimeError("being updated")

    monkeypatch.setattr(whatson.settings, "addon", updating)
    assert allowed() is False
