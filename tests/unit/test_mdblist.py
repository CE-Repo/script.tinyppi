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
from web.mdblist import Chart, Lookup, fetch, fetch_chart, places_of, scores_of, with_mdblist
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


def test_a_value_without_its_score_is_read_on_its_sources_scale():
    answer = {"ratings": [
        {"source": "letterboxd", "value": 4.1, "score": None},
        {"source": "myanimelist", "value": 8.6, "score": None},
        {"source": "popcorn", "value": 91, "score": None},
        # A source whose scale is not known is not guessed at.
        {"source": "newcomer", "value": 7, "score": None},
    ]}
    assert scores_of(answer) == {
        "letterboxd": {"rating": 8.2, "votes": None},
        "myanimelist": {"rating": 8.6, "votes": None},
        "popcorn": {"rating": 9.1, "votes": None},
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
    library = held(ratings=[{"source": "tmdb", "rating": 8.1, "votes": 3}], top250=27)
    assert with_mdblist(library, Answers(None)) == library


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


def test_a_key_given_is_asked_with_and_the_settings_are_not_read(monkeypatch):
    def unread():
        raise AssertionError("the settings were read")

    monkeypatch.setattr(mdblist.settings, "addon", unread)
    answers = Answers(None)
    with_mdblist(held(ids={"imdb": "tt1"}), answers, key="GIVEN")
    with_mdblist(held(ids={"imdb": "tt1"}), answers, key="")
    assert answers.asked == [("GIVEN", {"imdb": "tt1"}), ("", {"imdb": "tt1"})]


# --- The IMDb Top 250 ------------------------------------------------------------------

# MDBList's list, as it answers (cut short): in the chart's order, its rank a
# thousand times the place.
CHART = [
    {"id": 278, "rank": 1000, "title": "The Shawshank Redemption", "imdb_id": "tt0111161",
     "mediatype": "movie", "release_year": 1994},
    {"id": 238, "rank": 2000, "title": "The Godfather", "imdb_id": "tt0068646",
     "mediatype": "movie", "release_year": 1972},
    {"id": 155, "rank": 3000, "title": "The Dark Knight", "imdb_id": "tt0468569",
     "mediatype": "movie", "release_year": 2008},
]


def test_the_chart_gives_each_film_its_place():
    assert places_of(CHART) == {"tt0111161": 1, "tt0068646": 2, "tt0468569": 3}


def test_an_entry_of_another_shape_keeps_its_place():
    answer = [CHART[0], None, {"imdb_id": "nm0000123"}, {"imdb_id": 5}, CHART[2], CHART[0]]
    assert places_of(answer) == {"tt0111161": 1, "tt0468569": 5}


def test_only_the_first_250_are_the_chart():
    answer = [{"imdb_id": f"tt{place:07d}"} for place in range(1, 260)]
    places = places_of(answer)
    assert len(places) == 250 and places["tt0000250"] == 250


@pytest.mark.parametrize("answer", [{}, "chart", None, []])
def test_an_answer_of_another_shape_is_no_chart(answer):
    assert places_of(answer) == {}


def test_the_chart_is_asked_for_without_a_key(monkeypatch):
    asked = []
    monkeypatch.setattr(mdblist, "_json", lambda url: asked.append(url) or CHART)
    places, keep = fetch_chart()
    assert asked == ["https://mdblist.com/lists/snoak/imdb-top-250-movies/json"]
    assert places["tt0468569"] == 3 and keep == mdblist._KEPT


@pytest.mark.parametrize("failure", [
    refusal(403), refusal(500), urllib.error.URLError("no route"), TimeoutError(),
    ValueError("not JSON"), http.client.IncompleteRead(b""),
])
def test_a_chart_that_cannot_be_had_is_asked_for_again_soon(monkeypatch, failure):
    def fail(url):
        raise failure
    monkeypatch.setattr(mdblist, "_json", fail)
    assert fetch_chart() == ({}, mdblist._AGAIN)
    assert any("IMDb Top 250 could not be had" in line for _level, line in xbmc.LOG)


def test_an_empty_chart_is_asked_for_again_soon(monkeypatch):
    monkeypatch.setattr(mdblist, "_json", lambda url: [])
    assert fetch_chart() == ({}, mdblist._AGAIN)


@pytest.fixture
def chart(monkeypatch):
    """A chart that asks only when told to, on a clock the test moves."""
    clock, started, asked = Clock(), [], []
    answers = {"found": ({"tt0816692": 17}, mdblist._KEPT)}

    def fake_fetch():
        asked.append(1)
        found = answers["found"]
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(mdblist, "fetch_chart", fake_fetch)
    found = Chart(start=started.append, clock=clock)

    def run():
        while started:
            started.pop(0)()

    return found, clock, started, asked, answers, run


def test_the_chart_is_asked_for_once_and_kept_for_half_a_day(chart):
    found, clock, started, asked, _answers, run = chart
    # Not in yet: the library's place stands.
    assert found.place("tt0816692") is None
    assert found.place("tt0816692") is None
    assert len(started) == 1
    run()
    assert found.place("tt0816692") == 17
    # One that is not in it has no place.
    assert found.place("tt0000001") == 0
    assert started == [] and len(asked) == 1
    clock.now += mdblist._KEPT + 1
    # Asked for again, the old one standing meanwhile.
    assert found.place("tt0816692") == 17
    run()
    assert len(asked) == 2


def test_a_chart_that_could_not_be_had_leaves_the_last_one(chart):
    found, clock, started, asked, answers, run = chart
    found.place("tt0816692")
    run()
    clock.now += mdblist._KEPT + 1
    answers["found"] = ({}, mdblist._AGAIN)
    found.place("tt0816692")
    run()
    assert found.place("tt0816692") == 17
    assert started == []
    clock.now += mdblist._AGAIN + 1
    found.place("tt0816692")
    assert len(started) == 1


def test_a_chart_whose_asking_fails_of_itself_is_asked_for_again_soon(chart):
    found, clock, started, _asked, answers, run = chart
    answers["found"] = RuntimeError("a fault")
    found.place("tt1")
    with pytest.raises(RuntimeError):
        run()
    assert found.place("tt1") is None and started == []
    clock.now += mdblist._AGAIN + 1
    found.place("tt1")
    assert len(started) == 1


class Places:
    def __init__(self, place):
        self.found = place
        self.asked = []

    def place(self, imdb):
        self.asked.append(imdb)
        return self.found


def test_the_charts_place_lies_over_the_librarys():
    library = held(top250=27, ids={"imdb": "tt0816692", "tmdb": "157336"})
    places = Places(17)
    merged = with_mdblist(library, Answers(None), places)
    assert merged["top250"] == 17 and places.asked == ["tt0816692"]
    assert library["top250"] == 27
    # A film the chart does not hold is in no Top 250, whatever the library says.
    assert with_mdblist(library, Answers(None), Places(0))["top250"] == 0


def test_until_the_chart_is_in_the_librarys_place_stands():
    library = held(top250=27, ids={"imdb": "tt0816692"})
    assert with_mdblist(library, Answers(None), Places(None))["top250"] == 27


def test_a_title_without_an_imdb_id_is_not_looked_up():
    places = Places(17)
    episode = held(top250=0)
    assert with_mdblist(episode, Answers(None), places)["top250"] == 0
    assert with_mdblist(held(ids={"tmdb": "1"}), Answers(None), places)["top250"] == 0
    assert places.asked == []


def test_the_charts_place_stands_beside_mdblists_ratings():
    xbmcaddon.SETTINGS["web_mdblist_key"] = "KEY"
    merged = with_mdblist(held(ids={"imdb": "tt0073195"}), Answers(scores_of(JAWS)), Places(5))
    assert merged["top250"] == 5 and merged["ratings"][0]["source"] == "imdb"
