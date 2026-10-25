# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""One library title's details (web/library/details.py)."""

import pytest

from web import library, ratings
from web.library import details as details_module


@pytest.fixture
def answers(monkeypatch):
    """Answer the details queries from a dict by method; record the params.

    MDBList and WhatsOn have no key, and so are not asked.
    """
    held = {"answers": {}, "calls": []}

    def rpc(method, params=None):
        held["calls"].append((method, params))
        return held["answers"].get(method, {"result": "OK"})

    monkeypatch.setattr(library.common, "rpc", rpc)
    monkeypatch.setattr(ratings, "rpc", rpc)
    monkeypatch.setattr(details_module.mdblist, "api_key", lambda: "")
    monkeypatch.setattr(details_module.whatson, "api_key", lambda: "")
    return held


def test_a_films_details(answers):
    answers["answers"]["VideoLibrary.GetMovieDetails"] = {"result": {"moviedetails": {
        "title": "Heat", "plot": "One[CR]Two", "art": {"poster": "/p.jpg", "fanart": "/f.jpg"}, "tagline": "A [B]Los Angeles[/B] crime saga",
        "genre": ["Crime", "Drama"], "director": ["Michael Mann"], "writer": [],
        "studio": ["Warner"], "country": ["USA"], "mpaa": "Rated R", "year": 1995,
        "runtime": 10200, "userrating": 0, "top250": 120, "premiered": "1995-12-15",
        "ratings": {"imdb": {"rating": 8.3, "votes": 700000}},
        "cast": [{"name": "Robert De Niro", "role": "Neil", "order": 1},
                 {"name": "Al Pacino", "role": "Vincent", "order": 0},
                 {"name": "", "role": "Nobody", "order": 2}, "junk"],
        "streamdetails": {"video": [{"hdrtype": "dolbyvision", "hdrdetail": "7FEL", "width": 3840}],
                          "audio": [{"codec": "dtshd_ma"}]},
    }}}
    found = library.title_details("movie", "4")
    assert answers["calls"][0][1]["movieid"] == 4
    assert "art" in answers["calls"][0][1]["properties"]
    assert found == {
        "kind": "movie", "id": 4, "title": "Heat", "watched": False, "resume": 0,
        "ratings": [{"source": "imdb", "rating": 8.3, "votes": 700000}],
        "plot": "One\nTwo", "tagline": "A Los Angeles crime saga", "premiered": "1995-12-15",
        "mpaa": "Rated R", "age": "mpa_r", "age_level": "R", "year": 1995,
        "duration": 10200, "top250": 120, "genres": ["Crime", "Drama"],
        "directors": ["Michael Mann"], "studios": ["Warner"], "countries": ["USA"],
        "cast": [{"name": "Al Pacino", "role": "Vincent"},
                 {"name": "Robert De Niro", "role": "Neil"}],
        "cast_more": False,
        "poster": library.common.tag("/p.jpg"), "fanart": library.common.tag("/f.jpg"), "video": "dv", "dv_profile": "7 FEL", "resolution": "2160p",
        "audio": "dtshd_ma"}


def test_an_episodes_details_name_its_show(answers):
    answers["answers"]["VideoLibrary.GetEpisodeDetails"] = {"result": {"episodedetails": {
        "title": "Pilot", "showtitle": "Show", "tvshowid": 7, "season": 1, "episode": 1,
        "firstaired": "2008-01-20", "userrating": 9, "art": {"thumb": "/t.jpg"},
        "cast": [{"name": f"Actor {n}", "order": n} for n in range(25)],
    }}}
    found = library.title_details("episode", 70)
    assert (found["show"], found["tvshowid"], found["season"], found["episode"]) == ("Show", 7, 1, 1)
    assert found["premiered"] == "2008-01-20" and found["userrating"] == 9
    assert len(found["cast"]) == 25 and found["cast_more"] is False
    assert found["cast"][0] == {"name": "Actor 0", "role": ""}
    assert "plot" not in found and "mpaa" not in found and "video" not in found
    assert found["thumb"] == library.common.tag("/t.jpg") and "poster" not in found


def test_a_series_details(answers):
    answers["answers"]["VideoLibrary.GetTVShowDetails"] = {"result": {"tvshowdetails": {
        "label": "Show", "season": 5, "cast": "junk", "streamdetails": {"audio": [{"codec": "ac3"}]},
    }}}
    found = library.title_details("tvshow", 7)
    assert found == {"kind": "tvshow", "id": 7, "title": "Show", "ratings": [], "season": 5,
                     "audio": "ac3", "watched": False, "resume": 0}


@pytest.mark.parametrize(("kind", "item", "answer"), [
    ("song", 1, {}),
    ("movie", "abc", {}),
    ("movie", 0, {}),
    ("movie", 5, {"error": {"code": -32602}}),
    ("movie", 5, {"result": {"moviedetails": "junk"}}),
])
def test_no_details_for_an_unknown_title(answers, kind, item, answer):
    answers["answers"]["VideoLibrary.GetMovieDetails"] = answer
    assert library.title_details(kind, item) is None


def test_an_episode_wears_its_shows_age_rating_and_awards(answers, monkeypatch):
    answers["answers"]["VideoLibrary.GetEpisodeDetails"] = {"result": {"episodedetails": {
        "title": "Pilot", "tvshowid": 7}}}
    answers["answers"]["VideoLibrary.GetTVShowDetails"] = {"result": {"tvshowdetails": {
        "mpaa": "TV-MA", "uniqueid": {"tvdb": "81189"}}}}
    held = []
    monkeypatch.setattr(ratings, "awards_of", lambda kind, ids: held.append((kind, ids)) or [
        {"award": "emmy", "won": ["Drama"], "nominated": 2}])
    found = library.title_details("episode", 70)
    assert (found["mpaa"], found["age"], found["age_level"]) == ("TV-MA", "tv_ma", "MA")
    assert found["awards"] == [{"award": "emmy", "won": ["Drama"], "nominated": 2}]
    assert held == [("tv", {"tvdb": "81189"})]
    assert answers["calls"][1] == ("VideoLibrary.GetTVShowDetails",
                                   {"tvshowid": 7, "properties": ["mpaa", "uniqueid"]})


class Rated:
    """MDBList and WhatsOn as the details see them: each asked for a few
    looks, then answering."""

    def __init__(self, monkeypatch, mdblist_looks=0, whatson_looks=0):
        self.looks = {"mdblist": mdblist_looks, "whatson": whatson_looks}
        self.slept = []
        self.now = 0.0
        self.keys = []
        module = details_module
        monkeypatch.setattr(module.mdblist, "api_key", lambda: "m-key")
        monkeypatch.setattr(module.whatson, "api_key", lambda: "w-key")
        monkeypatch.setattr(module.mdblist, "with_mdblist", self.with_mdblist)
        monkeypatch.setattr(module.mdblist, "asking", self.mdblist_asking)
        monkeypatch.setattr(module.whatson, "with_whatson", self.with_whatson)
        monkeypatch.setattr(module.whatson, "asking", self.whatson_asking)
        monkeypatch.setattr(module, "_sleep", self.sleep)
        monkeypatch.setattr(module, "_clock", lambda: self.now)

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def _asking(self, name):
        if self.looks[name] > 0:
            self.looks[name] -= 1
            return True
        return False

    def mdblist_asking(self, key, ids):
        self.keys.append(("mdblist", key, dict(ids)))
        return self._asking("mdblist")

    def whatson_asking(self, ids, key):
        self.keys.append(("whatson", key, dict(ids)))
        return self._asking("whatson")

    def with_mdblist(self, given, key=None):
        if self.looks["mdblist"]:
            return given
        merged = given.copy()
        merged["ratings"] = [{"source": "metacritic", "rating": 7.6, "votes": 0}] + given["ratings"]
        merged["top250"] = 115
        return merged

    def with_whatson(self, given, key=""):
        if self.looks["whatson"]:
            return given
        merged = given.copy()
        merged["ratings"] = given["ratings"] + [
            {"source": "rottentomatoes", "rating": 8.8, "votes": 0, "certified": True}]
        return merged


HEAT = {"result": {"moviedetails": {
    "title": "Heat", "ratings": {"imdb": {"rating": 8.3, "votes": 700000}}, "userrating": 8,
    "uniqueid": {"imdb": "tt0113277", "tmdb": "949"}}}}


def test_a_films_ratings_are_the_now_playing_cards(answers, monkeypatch):
    answers["answers"]["VideoLibrary.GetMovieDetails"] = HEAT
    rated = Rated(monkeypatch, mdblist_looks=2, whatson_looks=1)
    found = library.title_details("movie", 4)
    assert "uniqueid" in answers["calls"][0][1]["properties"]
    assert [entry["source"] for entry in found["ratings"]] == ["metacritic", "imdb", "rottentomatoes"]
    assert found["ratings"][2]["certified"] is True
    assert (found["userrating"], found["top250"]) == (8, 115)
    # MDBList first, WhatsOn once it has answered, each with its own key.
    assert rated.slept == [0.2, 0.2, 0.2]
    assert rated.keys[0] == ("mdblist", "m-key", {"imdb": "tt0113277", "tmdb": "949"})
    assert ("whatson", "w-key", {"imdb": "tt0113277", "tmdb": "949"}) in rated.keys


def test_a_slow_answer_is_waited_on_for_a_moment_only(answers, monkeypatch):
    answers["answers"]["VideoLibrary.GetMovieDetails"] = HEAT
    rated = Rated(monkeypatch, mdblist_looks=1000)
    found = library.title_details("movie", 4)
    assert found["ratings"] == [{"source": "imdb", "rating": 8.3, "votes": 700000}]
    assert sum(rated.slept) == pytest.approx(details_module._RATINGS_WAIT)
    assert not any(name == "whatson" for name, _key, _ids in rated.keys)


def test_a_show_is_not_asked_for_by_its_ids(answers, monkeypatch):
    answers["answers"]["VideoLibrary.GetTVShowDetails"] = {"result": {"tvshowdetails": {
        "title": "Dark", "uniqueid": {"imdb": "tt5753856", "tvdb": "334824"}}}}
    rated = Rated(monkeypatch)
    library.title_details("tvshow", 7)
    assert rated.keys[0] == ("mdblist", "m-key", {})


@pytest.mark.parametrize(("kind", "values", "watched", "resume"), [
    ("movie", {"playcount": 2, "resume": {"position": 600, "total": 3600}}, True, 600),
    ("episode", {"playcount": 0}, False, 0),
    ("tvshow", {"episode": 5, "watchedepisodes": 5}, True, 0),
    ("tvshow", {"episode": 5, "watchedepisodes": 3}, False, 0),
    ("tvshow", {"episode": 0, "watchedepisodes": 0}, False, 0),
])
def test_details_carry_the_state_for_their_actions(answers, kind, values, watched, resume):
    method, _, key, _ = details_module._KINDS[kind]
    answers["answers"][method] = {"result": {key: {"title": "A title", **values}}}
    found = library.title_details(kind, 1)
    assert found["watched"] is watched
    assert found["resume"] == resume
