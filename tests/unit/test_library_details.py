# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""One library title's details (web/library/details.py)."""

import pytest

from web import library


@pytest.fixture
def answers(monkeypatch):
    """Answer the details queries from a dict by method; record the params."""
    held = {"answers": {}, "calls": []}

    def rpc(method, params=None):
        held["calls"].append((method, params))
        return held["answers"].get(method, {"result": "OK"})

    monkeypatch.setattr(library.common, "rpc", rpc)
    return held


def test_a_films_details(answers):
    answers["answers"]["VideoLibrary.GetMovieDetails"] = {"result": {"moviedetails": {
        "title": "Heat", "plot": "One[CR]Two", "tagline": "A [B]Los Angeles[/B] crime saga",
        "genre": ["Crime", "Drama"], "director": ["Michael Mann"], "writer": [],
        "studio": ["Warner"], "country": ["USA"], "mpaa": "Rated R", "year": 1995,
        "runtime": 10200, "userrating": 0, "top250": 120, "premiered": "1995-12-15",
        "ratings": {"imdb": {"rating": 8.3, "votes": 700000}},
        "cast": [{"name": "Robert De Niro", "role": "Neil", "order": 1},
                 {"name": "Al Pacino", "role": "Vincent", "order": 0},
                 {"name": "", "role": "Nobody", "order": 2}, "junk"],
        "streamdetails": {"video": [{"hdrtype": "hdr10", "width": 3840}],
                          "audio": [{"codec": "dtshd_ma"}]},
    }}}
    found = library.title_details("movie", "4")
    assert answers["calls"][0][1]["movieid"] == 4
    assert found == {
        "kind": "movie", "id": 4, "title": "Heat",
        "ratings": [{"source": "imdb", "rating": 8.3, "votes": 700000}],
        "plot": "One\nTwo", "tagline": "A Los Angeles crime saga", "premiered": "1995-12-15",
        "mpaa": "Rated R", "age": "mpa_r", "age_level": "R", "year": 1995,
        "duration": 10200, "top250": 120, "genres": ["Crime", "Drama"],
        "directors": ["Michael Mann"], "studios": ["Warner"], "countries": ["USA"],
        "cast": [{"name": "Al Pacino", "role": "Vincent"},
                 {"name": "Robert De Niro", "role": "Neil"}],
        "cast_more": False, "video": "hdr10", "resolution": "2160p", "audio": "dtshd_ma"}


def test_an_episodes_details_name_its_show(answers):
    answers["answers"]["VideoLibrary.GetEpisodeDetails"] = {"result": {"episodedetails": {
        "title": "Pilot", "showtitle": "Show", "tvshowid": 7, "season": 1, "episode": 1,
        "firstaired": "2008-01-20", "userrating": 9,
        "cast": [{"name": f"Actor {n}", "order": n} for n in range(25)],
    }}}
    found = library.title_details("episode", 70)
    assert (found["show"], found["tvshowid"], found["season"], found["episode"]) == ("Show", 7, 1, 1)
    assert found["premiered"] == "2008-01-20" and found["userrating"] == 9
    assert len(found["cast"]) == 20 and found["cast_more"] is True
    assert found["cast"][0] == {"name": "Actor 0", "role": ""}
    assert "plot" not in found and "mpaa" not in found and "video" not in found


def test_a_series_details(answers):
    answers["answers"]["VideoLibrary.GetTVShowDetails"] = {"result": {"tvshowdetails": {
        "label": "Show", "season": 5, "cast": "junk", "streamdetails": {"audio": [{"codec": "ac3"}]},
    }}}
    found = library.title_details("tvshow", 7)
    assert found == {"kind": "tvshow", "id": 7, "title": "Show", "ratings": [], "season": 5,
                     "audio": "ac3"}


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
