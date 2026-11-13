# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""tools/gen_awards.py against a pretend TheTVDB: what it asks for, and the
file it writes from the answers."""

import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "gen_awards.py")
_SPEC = importlib.util.spec_from_file_location("gen_awards", _PATH)
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)

# TheTVDB as the script sees it: each path's ``data``.
ANSWERS = {
    "/awards": [{"id": 1, "name": "Academy Awards"}, {"id": 2, "name": "Golden Globe Awards"},
                {"id": 3, "name": "BAFTA Awards"}, {"id": 4, "name": "Primetime Emmy Awards"},
                {"id": 5, "name": "César Awards"}],
    "/awards/1/extended": {"categories": [{"id": 11, "name": "Visual Effects"},
                                          {"id": 12, "name": "Best Picture"}, "junk"]},
    "/awards/2/extended": {"categories": [{"id": 21, "name": "Best Score"}]},
    "/awards/3/extended": {},
    "/awards/4/extended": {"categories": [{"id": 41, "name": "Outstanding Drama Series"}]},
    "/awards/categories/11/extended": {"nominees": [
        {"isWinner": True, "year": "2015", "movie": {"id": 100, "name": "Interstellar"}},
        {"isWinner": False, "year": "2015", "movie": {"id": 101, "name": "Guardians"}}]},
    "/awards/categories/12/extended": {"nominees": [
        {"isWinner": False, "year": "2015", "movie": {"id": 100}},
        # A person alone, with no film, is no title's.
        {"isWinner": True, "year": "2015", "name": "Somebody"}]},
    "/awards/categories/21/extended": {"nominees": [
        {"isWinner": False, "year": "2015", "movie": {"id": 100}}]},
    "/awards/categories/41/extended": {"nominees": [
        {"isWinner": True, "year": "2008", "series": {"id": 200}},
        # An episode's nomination is its show's.
        {"isWinner": False, "year": "2009", "episode": {"id": 9, "seriesId": 200}},
        {"isWinner": True, "year": "2009", "series": {"id": 200}}]},
    "/movies/100/extended?short=true": {"remoteIds": [
        {"sourceName": "IMDB", "id": "tt0816692"}, {"sourceName": "TheMovieDB.com", "id": "157336"},
        {"sourceName": "IMDB", "id": "tt0000000"}, {"sourceName": "Wikidata", "id": "Q13417189"}]},
    "/movies/101/extended?short=true": None,
    "/series/200/extended?short=true": {"remoteIds": [{"sourceName": "TheMovieDB.com", "id": "1396"}]},
}


def get(path):
    return ANSWERS[path]


def test_every_nominee_of_the_four_awards_is_collected_by_its_title():
    titles = gen.collect(gen.nominees(get, workers=2))
    assert titles == {
        "movie": {"100": {"oscar": [["Visual Effects (2015)"], 1], "globe": [[], 1]},
                  "101": {"oscar": [[], 1]}},
        "tv": {"200": {"emmy": [["Outstanding Drama Series (2008)", "Outstanding Drama Series (2009)"], 1]}},
    }


def test_the_file_indexes_each_title_by_its_imdb_and_tmdb_ids():
    titles = gen.collect(gen.nominees(get, workers=2))
    data = gen.indexed(titles, lambda kind, tvdb: gen.remote_ids(get, kind, tvdb), workers=2)
    assert data["source"] == gen.SOURCE
    # The first of a source's ids is kept, and a source not asked for left out.
    assert data["movie"]["imdb"] == {"tt0816692": "100"}
    assert data["movie"]["tmdb"] == {"157336": "100"}
    assert list(data["movie"]["titles"]) == ["100", "101"]
    assert data["tv"] == {"titles": titles["tv"], "imdb": {}, "tmdb": {"1396": "200"}}


def test_an_award_missing_from_tvdb_stops_the_run():
    answers = dict(ANSWERS, **{"/awards": [{"id": 1, "name": "Academy Awards"}]})
    with pytest.raises(SystemExit, match="bafta, emmy, globe"):
        list(gen.categories(answers.get))


def test_the_moviedb_helpers_list_is_read_into_the_same_shape():
    helper = {
        "movie": {"157336": {"name": "Interstellar", "tvdb_id": 131079,
                             "awards_won": {"Academy Awards": ["Visual Effects (2015)"]},
                             "awards_nominated": {"Academy Awards": ["Sound Mixing (2015)", "Score (2015)"],
                                                  "Golden Globe Awards": ["Best Score (2015)"],
                                                  "César Awards": ["Best Foreign Film (2015)"]}},
                  # Without a TheTVDB id, or with none of the four, it is left out.
                  "1": {"awards_won": {"Academy Awards": ["Picture (2001)"]}},
                  "2": {"tvdb_id": 7, "awards_won": {"César Awards": ["Best Film (2001)"]}}},
    }
    data = gen.from_helper(helper)
    assert data["source"] == gen.HELPER
    assert data["movie"] == {
        "titles": {"131079": {"oscar": [["Visual Effects (2015)"], 2], "globe": [[], 1]}},
        "imdb": {}, "tmdb": {"157336": "131079"}}
    assert data["tv"] == {"titles": {}, "imdb": {}, "tmdb": {}}


# Wikidata as the script sees it: the rows of each query, picked by what the
# query asks for.
WIKIDATA = {
    "?cat ?fam ?name": [
        {"cat": "Q11", "fam": "Q19020", "name": "Academy Award for Best Visual Effects"},
        {"cat": "Q12", "fam": "Q19020", "name": "Academy Award for Best Actor"},
        {"cat": "Q41", "fam": "Q1044427", "name": "Primetime Emmy Award for Outstanding Drama Series"},
        {"cat": "Q21", "fam": "Q1011547", "name": "Golden Globe Award for Best Original Score"},
        {"cat": "Q31", "fam": "Q732997", "name": "BAFTA Award for Best Film"},
        # A ceremony is part of the award too, and no category.
        {"cat": "Q39", "fam": "Q732997", "name": "79th British Academy Film Awards"}],
    "p:P166": [
        {"item": "Q100", "cat": "Q11", "date": "2015-02-22T00:00:00Z"},
        # Said again without its year, and of an actor for the film.
        {"item": "Q100", "cat": "Q11"},
        {"item": "Q900", "work": "Q100", "cat": "Q12", "date": "2015-02-22T00:00:00Z"},
        # Somebody alone, with no film, is no title's.
        {"item": "Q900", "cat": "Q12", "date": "2001-01-01T00:00:00Z"},
        {"item": "Q200", "cat": "Q41", "date": "2013-01-01T00:00:00Z"},
        # An episode's is its show's; a year before the awards is a slip.
        {"item": "Q201", "cat": "Q41", "date": "0914-01-01T00:00:00Z"}],
    "p:P1411": [
        # What it won is no further nomination; the others are, each once.
        {"item": "Q100", "cat": "Q11", "date": "2015-02-22T00:00:00Z"},
        {"item": "Q100", "cat": "Q21", "date": "2015-01-11T00:00:00Z"},
        {"item": "Q901", "work": "Q100", "cat": "Q21", "date": "2015-01-11T00:00:00Z"},
        {"item": "Q300", "cat": "Q31", "date": "2015-01-01T00:00:00Z"},
        {"item": "Q200", "cat": "Q41", "date": "2014-01-01T00:00:00Z"}],
    "?item ?movie": [
        {"item": "Q100", "movie": "1", "imdb": "tt0816692", "tmdbmovie": "157336",
         "tvdbmovie": "131079"},
        {"item": "Q200", "tv": "1", "imdb": "tt0903747", "tmdbtv": "1396", "tvdbtv": "81189"},
        {"item": "Q201", "show": "Q200"},
        # A film Wikidata holds no TheTVDB id of is held by its item.
        {"item": "Q300", "movie": "1", "imdb": "tt0000300"},
        {"item": "Q900"}, {"item": "Q901"}],
}


def ask(query):
    asked = [rows for marker, rows in WIKIDATA.items() if marker in query]
    assert len(asked) == 1, query
    wanted = {item for item in query.replace("wd:", " ").split() if item.startswith("Q")}
    # Only what the query names is answered: a category's statements, an
    # item's ids.
    named = "fam" if "?fam" in query else "cat" if "?said" in query else "item"
    return [row for row in asked[0] if row[named] in wanted]


def test_wikidatas_awards_are_read_into_the_same_shape():
    data = gen.from_wikidata(ask)
    assert data["source"] == gen.WIKIDATA_SOURCE
    assert data["movie"] == {
        "titles": {"131079": {"oscar": [["Best Actor (2015)", "Best Visual Effects (2015)"], 0],
                              "globe": [[], 1]},
                   "Q300": {"bafta": [[], 1]}},
        "imdb": {"tt0000300": "Q300", "tt0816692": "131079"}, "tmdb": {"157336": "131079"}}
    assert data["tv"] == {
        "titles": {"81189": {"emmy": [["Outstanding Drama Series (2013)"], 1]}},
        "imdb": {"tt0903747": "81189"}, "tmdb": {"1396": "81189"}}


def test_an_award_missing_from_wikidata_stops_the_run():
    with pytest.raises(SystemExit, match="bafta, emmy, globe"):
        gen.from_wikidata(lambda query: WIKIDATA["?cat ?fam ?name"][:2] if "?fam" in query else [])
