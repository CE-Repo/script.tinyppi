# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What a details page leads on to from TMDb: a film's series, the library's
titles TMDb recommends, and a show's state (web/tmdb.py, web/library/)."""

import pytest

from web import library, tmdb
from web.library import details as details_module


@pytest.fixture(autouse=True)
def empty_cache():
    tmdb._CACHE.clear()
    yield
    tmdb._CACHE.clear()


@pytest.fixture
def shelves(monkeypatch):
    """The library's films and shows, read from rows set per test."""
    held = {"movies": [], "tvshows": []}

    def rpc(method, params=None):
        key = {"VideoLibrary.GetMovies": "movies", "VideoLibrary.GetTVShows": "tvshows"}.get(method)
        return {"result": {key: held[key]}} if key else {"result": "OK"}

    monkeypatch.setattr(library.common, "rpc", rpc)
    monkeypatch.setattr(library.cache, "lists", library.new_cache())
    return held


# --- The library by TMDb id ----------------------------------------------------

@pytest.mark.parametrize(("row", "expected"), [
    ({"uniqueid": {"tmdb": "949"}}, 949), ({"uniqueid": {"tmdb": 949}}, 949),
    ({"uniqueid": {"tmdb": "0"}}, None), ({"uniqueid": {"tmdb": "tt1"}}, None),
    ({"uniqueid": {"imdb": "tt1"}}, None), ({"uniqueid": "949"}, None), ({}, None),
    ({"uniqueid": {"tmdb": "12345678901"}}, None),
])
def test_the_tmdb_id_kodi_filed_a_title_under(row, expected):
    assert library.common.tmdb_id(row) == expected


def test_films_and_shows_are_found_by_their_tmdb_ids(shelves):
    shelves["movies"] = [
        {"movieid": 1, "title": "Dune", "year": 2021, "uniqueid": {"tmdb": "438631"}},
        {"movieid": 2, "title": "Dune again", "uniqueid": {"tmdb": "438631"}},
        {"movieid": 3, "title": "Unscraped"},
        {"movieid": 4, "title": "", "uniqueid": {"tmdb": "5"}},
    ]
    shelves["tvshows"] = [{"tvshowid": 7, "title": "Severance", "uniqueid": {"tmdb": "95396"}},
                          {"tvshowid": 8, "title": "Local"}]
    films = library.films.by_tmdb()
    # The first of two copies of one film is the one led to.
    assert list(films) == [438631] and films[438631]["id"] == 1
    assert {ident: show["id"] for ident, show in library.series.by_tmdb().items()} == {95396: 7}
    # Not part of what the clients are sent.
    assert "tmdb" not in library.movies() and "tmdb" not in library.shows()


def test_an_unreadable_library_finds_nothing(monkeypatch):
    monkeypatch.setattr(library.common, "rpc", lambda *args: {"error": {"code": -32100}})
    monkeypatch.setattr(library.cache, "lists", library.new_cache())
    assert library.films.by_tmdb() == {} and library.series.by_tmdb() == {}


# --- What TMDb is asked --------------------------------------------------------

@pytest.mark.parametrize(("kodi", "expected"), [
    ("de-de", "de-DE"), ("pt_br", "pt-BR"), ("fr", "fr"), ("English", "en"), ("", "en"),
])
def test_the_series_is_asked_for_in_kodis_language(monkeypatch, kodi, expected):
    monkeypatch.setattr(tmdb.xbmc, "getLanguage", lambda *args: kodi)
    assert tmdb._language() == expected


def test_a_film_in_a_series_is_asked_for_the_series_too(monkeypatch):
    monkeypatch.setattr(tmdb.xbmc, "getLanguage", lambda *args: "de-de")
    film = {"id": 1, "belongs_to_collection": {"id": 10, "name": "Dune"}}
    answers = {"movie/1?append_to_response=credits,release_dates,recommendations": film,
               "collection/10?language=de-DE": {"name": "Dune Filmreihe", "parts": []}}
    paths = []
    monkeypatch.setattr(tmdb, "_get", lambda path, *args: paths.append(path) or answers.get(path, {}))
    found = tmdb.lookup("movie", {"uniqueid": {"tmdb": "1"}}, "key")
    assert found == {**film, "collection": {"name": "Dune Filmreihe", "parts": []}}
    # The cached answer itself is left as it came.
    assert "collection" not in film
    # A series TMDb has nothing for leaves the film as it is.
    del answers["collection/10?language=de-DE"]
    assert tmdb.lookup("movie", {"uniqueid": {"tmdb": "1"}}, "key") is film
    for held in [None, "Dune", {"id": "x"}, {}]:
        answers["movie/1?append_to_response=credits,release_dates,recommendations"] = \
            {"id": 1, "belongs_to_collection": held}
        paths.clear()
        tmdb.lookup("movie", {"uniqueid": {"tmdb": "1"}}, "key")
        assert len(paths) == 1


# --- What TMDb's answers say ---------------------------------------------------

def test_a_series_in_release_order_with_the_undated_last():
    answer = {"id": 2, "collection": {"name": " Dune Collection ", "parts": [
        {"id": 3, "title": "Dune: Part Three", "poster_path": "/c.jpg"},
        {"id": 2, "title": "Dune: Part Two", "release_date": "2024-02-27",
         "poster_path": "//elsewhere/b.jpg"},
        {"id": 1, "title": "Dune", "release_date": "2021-09-15", "poster_path": "/a.jpg"},
        {"id": 0, "title": "No id"}, {"id": 4, "title": " "}, {"id": 5, "title": "Bad date",
                                                               "release_date": "soon"}, "junk"]}}
    name, parts = tmdb.collection(answer)
    assert name == "Dune Collection"
    assert parts == [
        {"id": 1, "title": "Dune", "current": False, "date": "2021-09-15",
         "poster": "https://image.tmdb.org/t/p/w342/a.jpg"},
        {"id": 2, "title": "Dune: Part Two", "current": True, "date": "2024-02-27"},
        {"id": 3, "title": "Dune: Part Three", "current": False,
         "poster": "https://image.tmdb.org/t/p/w342/c.jpg"},
        {"id": 5, "title": "Bad date", "current": False}]
    assert tmdb.collection({}) == ("", [])
    assert tmdb.collection({"collection": "Dune"}) == ("", [])
    assert tmdb.collection({"collection": {"parts": "none"}}) == ("", [])


def test_recommendations_best_first():
    answer = {"recommendations": {"results": [{"id": 5}, {"id": "x"}, "junk", {"id": 3}]}}
    assert tmdb.recommended(answer) == [5, 3]
    for held in [{}, {"recommendations": []}, {"recommendations": {"results": {}}}]:
        assert tmdb.recommended(held) == []


def test_a_shows_state():
    answer = {
        "status": "Returning Series", "networks": [{"name": " Apple TV+ "}, {"name": ""}, {}],
        "number_of_seasons": 2, "number_of_episodes": 19,
        "next_episode_to_air": {"season_number": 3, "episode_number": 1,
                                "air_date": "2027-01-16", "name": " Hello, Ms. Cobel "},
        "last_episode_to_air": {"season_number": 2, "episode_number": 10, "air_date": "nope"},
    }
    assert tmdb.show_state(answer) == {
        "status": "returning", "networks": ["Apple TV+"], "seasons": 2, "episodes": 19,
        "next": {"season": 3, "episode": 1, "date": "2027-01-16", "title": "Hello, Ms. Cobel"},
        "last": {"season": 2, "episode": 10}}
    for status, code in [("Ended", "ended"), ("Canceled", "canceled"), ("Cancelled", "canceled"),
                         ("In Production", "production"), ("Planned", "planned"),
                         ("Pilot", "pilot")]:
        assert tmdb.show_state({"status": status}) == {"status": code}
    assert tmdb.show_state({"status": "Rumoured", "networks": [{"name": ""}],
                            "number_of_seasons": 0, "next_episode_to_air": None}) == {}


@pytest.mark.parametrize("airing", [
    "S01E01", {}, {"season_number": 1}, {"episode_number": 1},
    {"season_number": -1, "episode_number": 1}, {"season_number": 1, "episode_number": 0},
    {"season_number": True, "episode_number": 1},
])
def test_an_episode_without_its_numbers_is_no_airing(airing):
    assert tmdb._airing(airing) == {}


def test_specials_air_too():
    assert tmdb._airing({"season_number": 0, "episode_number": 2}) == {"season": 0, "episode": 2}


# --- On the details page -------------------------------------------------------

def test_a_films_series_leads_to_the_library_first(shelves, monkeypatch):
    shelves["movies"] = [
        {"movieid": 11, "title": "Dune (Kodi)", "year": 2021, "art": {"poster": "/p.jpg"},
         "uniqueid": {"tmdb": "1"}},
        {"movieid": 12, "title": "Dune: Part Two", "uniqueid": {"tmdb": "2"}}]
    monkeypatch.setattr(tmdb, "api_key", lambda: "key")
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {"id": 2, "collection": {
        "name": "Dune [B]Collection[/B]", "parts": [
            {"id": 1, "title": "Dune", "release_date": "2021-09-15"},
            {"id": 2, "title": "Dune: Part Two", "release_date": "2024-02-27"},
            {"id": 3, "title": "Dune: [I]Part Three[/I]", "release_date": "2026-12-16",
             "poster_path": "/c.jpg"},
            {"id": 4, "title": "Dune Messiah"}]}})
    found = {"id": 12}
    details_module._from_tmdb(found, {}, "movie")
    parts = found["collection"]["parts"]
    assert found["collection"]["name"] == "Dune Collection"
    # Kodi's own: its title, year and poster, the way to its own page.
    assert parts[0] == {"kind": "movie", "tmdb": 1, "id": 11, "title": "Dune (Kodi)",
                        "year": 2021, "poster": library.common.tag("/p.jpg")}
    assert parts[1] == {"kind": "movie", "tmdb": 2, "id": 12, "title": "Dune: Part Two",
                        "current": True}
    # The others as TMDb has them, its poster through the artwork route.
    tag = parts[2].pop("portrait")
    assert details_module.portrait_path(tag) == "https://image.tmdb.org/t/p/w342/c.jpg"
    assert parts[2] == {"kind": "movie", "tmdb": 3, "title": "Dune: Part Three", "year": 2026}
    assert parts[3] == {"kind": "movie", "tmdb": 4, "title": "Dune Messiah"}


@pytest.mark.parametrize("held", [
    {"name": "Alone", "parts": [{"id": 2, "title": "Only one"}]},
    {"name": "", "parts": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]},
])
def test_no_series_of_one_film_or_without_a_name(shelves, monkeypatch, held):
    monkeypatch.setattr(tmdb, "api_key", lambda: "key")
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {"id": 2, "collection": held})
    found = {"id": 12}
    details_module._from_tmdb(found, {}, "movie")
    assert "collection" not in found


def test_recommendations_are_the_librarys_own(shelves, monkeypatch):
    shelves["movies"] = [
        {"movieid": index, "title": f"Film {index}", "uniqueid": {"tmdb": str(100 + index)}}
        for index in range(1, 30)]
    monkeypatch.setattr(tmdb, "api_key", lambda: "key")
    monkeypatch.setattr(details_module, "_RECOMMENDED", 3)
    # Not in the library (999), the film itself (101), a repeat (102) left out.
    picks = [999, 101, 102, 102, 103, 104, 105]
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {
        "recommendations": {"results": [{"id": ident} for ident in picks]}})
    found = {"id": 1}
    details_module._from_tmdb(found, {}, "movie")
    assert [(pick["id"], pick["tmdb"], pick["kind"]) for pick in found["recommended"]] == [
        (2, 102, "movie"), (3, 103, "movie"), (4, 104, "movie")]
    picks[:] = [999]
    found = {"id": 1}
    details_module._from_tmdb(found, {}, "movie")
    assert "recommended" not in found


def test_a_shows_state_and_recommendations(shelves, monkeypatch):
    shelves["tvshows"] = [{"tvshowid": 8, "title": "Andor", "year": 2022,
                           "uniqueid": {"tmdb": "83867"}}]
    monkeypatch.setattr(tmdb, "api_key", lambda: "key")
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {
        "status": "Ended", "networks": [{"name": "Disney+"}, {"name": "[B][/B]"}],
        "number_of_seasons": 2, "number_of_episodes": 24,
        "last_episode_to_air": {"season_number": 2, "episode_number": 12,
                                "air_date": "2025-05-13", "name": "[I][/I]"},
        "next_episode_to_air": {"season_number": 3, "episode_number": 1, "name": "Next"},
        "recommendations": {"results": [{"id": 83867}]}})
    found = {"id": 7}
    details_module._from_tmdb(found, {}, "tvshow")
    assert found == {
        "id": 7, "status": "ended", "networks": ["Disney+"], "tmdb_seasons": 2, "tmdb_episodes": 24,
        "last_episode": {"season": 2, "episode": 12, "date": "2025-05-13"},
        "next_episode": {"season": 3, "episode": 1, "title": "Next"},
        "recommended": [{"kind": "tvshow", "tmdb": 83867, "id": 8, "title": "Andor",
                         "year": 2022}]}
    # TMDb saying nothing of the show adds nothing.
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {})
    found = {"id": 7}
    details_module._from_tmdb(found, {}, "tvshow")
    assert found == {"id": 7}


def test_an_episode_has_no_state_series_or_recommendations(monkeypatch):
    monkeypatch.setattr(tmdb, "api_key", lambda: "key")
    monkeypatch.setattr(tmdb, "lookup", lambda *args: {
        "status": "Ended", "recommendations": {"results": [{"id": 1}]},
        "collection": {"name": "X", "parts": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]}})
    found = {"id": 7}
    details_module._from_tmdb(found, {}, "episode")
    assert found == {"id": 7}
