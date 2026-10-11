# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The library's JSON-RPC queries, rows and writes (web/library/)."""

import re

import pytest

import xbmc
from web import library


class Kodi:
    """Answer the library's JSON-RPC calls from ``answers``; record every call.

    Answers are keyed by method, with " (in progress)" appended for the
    filtered reads of the "continue" row.  An answer may be a callable taking
    the params.  Anything unset answers "OK" (no rows for the readers).
    """

    def __init__(self):
        self.calls = []
        self.answers = {}

    def __call__(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        key = method + (" (in progress)" if "filter" in params else "")
        answer = self.answers.get(key, {"result": "OK"})
        return answer(params) if callable(answer) else answer

    def sent(self, method):
        return [params for name, params in self.calls if name == method]

    def rows(self, method, key, rows):
        self.answers[method] = {"result": {key: rows}}


@pytest.fixture
def kodi(monkeypatch):
    fake = Kodi()
    monkeypatch.setattr(library.common, "rpc", fake)
    monkeypatch.setattr(library.cache, "lists", library.new_cache())
    return fake


def logged():
    return [line for _level, line in xbmc.LOG if line.startswith("TinyPPI [library]: ")]


def info_lines():
    return [line for level, line in xbmc.LOG
            if level == xbmc.LOGINFO and line.startswith("TinyPPI [library]: ")]


def film(kodi, **fields):
    """Return the one film read from a row with *fields*."""
    kodi.rows("VideoLibrary.GetMovies", "movies", [{"movieid": 1, "title": "Film", **fields}])
    [entry] = library.movies()["movies"]
    return entry


# --- Failed and empty reads ----------------------------------------------------

def test_a_failed_film_read_is_an_empty_list(kodi):
    kodi.answers["VideoLibrary.GetMovies"] = {"error": {"code": -32100}}
    assert library.movies() == {"movies": [], "count": 0, "tag": "none"}
    assert library.art_path(1, "poster") == ""
    assert any("VideoLibrary.GetMovies failed" in line for line in logged())


def test_a_failed_series_read_is_an_empty_list(kodi):
    kodi.answers["VideoLibrary.GetTVShows"] = {"error": {"code": -32100}}
    assert library.shows() == {"shows": [], "count": 0, "tag": "none"}
    assert library.show_art_path(7, "poster") == ""
    assert library.episodes(7) is None
    assert any("VideoLibrary.GetTVShows failed" in line for line in logged())


def test_a_failed_episode_read_is_an_empty_list(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [{"tvshowid": 7, "title": "Show"}])
    kodi.answers["VideoLibrary.GetEpisodes"] = {"error": {"code": -32100}}
    assert library.episodes(7) == {"tvshowid": 7, "title": "Show", "episodes": [],
                                   "count": 0, "tag": "none"}
    assert any("VideoLibrary.GetEpisodes failed for 7" in line for line in logged())


def test_answers_without_rows_are_empty_lists(kodi):
    # The fake answers "OK" to everything: a result that is no mapping.
    assert library.movies()["movies"] == []
    assert library.shows()["shows"] == []
    assert library.continuing()["items"] == []
    assert library.movies()["tag"] == "0-00000000"


def test_failed_continue_reads_are_logged_and_give_an_empty_row(kodi):
    kodi.answers["VideoLibrary.GetMovies (in progress)"] = {"error": {"code": 1}}
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"error": {"code": 2}}
    assert library.continuing() == {"items": [], "count": 0, "tag": "11-0-00000000"}
    lines = logged()
    assert any("GetMovies (in progress) failed" in line for line in lines)
    assert any("GetEpisodes (in progress) failed" in line for line in lines)


# --- Films -----------------------------------------------------------------------

def test_film_rows_without_an_id_or_title_are_left_out(kodi):
    kodi.rows("VideoLibrary.GetMovies", "movies", [
        "junk",
        {"movieid": "1", "title": "Id as text"},
        {"movieid": 2, "title": ""},
        {"movieid": 3, "label": "[B]Label only[/B]", "art": "not a mapping"},
        {"movieid": 4, "title": "Full", "art": {"poster": "  ", "thumb": " /t.jpg ",
                                                "fanart": "/f.jpg"}},
    ])
    listing = library.movies()
    assert [entry["id"] for entry in listing["movies"]] == [3, 4]
    assert listing["count"] == 2 and listing["tag"].startswith("2-")
    assert listing["movies"][0] == {"id": 3, "title": "Label only", "poster": ""}
    assert library.art_path(4, "poster") == "/t.jpg"
    assert library.art_path("4", "fanart") == "/f.jpg"
    assert library.art_path(3, "poster") == ""
    assert library.art_path(99, "poster") == ""
    assert kodi.sent("VideoLibrary.GetMovies") == [{
        "properties": ["title", "year", "art", "runtime", "playcount", "resume", "ratings",
                       "dateadded"],
        "sort": {"method": "sorttitle", "order": "ascending", "ignorearticle": True}}]
    assert "2 films read from the video database" in info_lines()[-1]


def test_a_full_film_row(kodi):
    entry = film(kodi, year=1999, runtime=7200, playcount=2,
                 resume={"position": 600, "total": 7200},
                 ratings={"imdb": {"rating": 8.04}}, dateadded="2020-01-02 03:04:05")
    assert {key: value for key, value in entry.items() if key != "poster"} == {
        "id": 1, "title": "Film", "year": 1999, "duration": 7200, "watched": True,
        "resume": 600, "rating": 8.0, "rating_from": "imdb", "added": "2020-01-02 03:04:05"}


@pytest.mark.parametrize("fields", [
    {"year": 0}, {"year": "1999"}, {"runtime": 0}, {"runtime": "90"},
    {"playcount": 0}, {"playcount": "1"},
])
def test_film_fields_out_of_range_are_left_out(kodi, fields):
    assert set(film(kodi, **fields)) == {"id", "title", "poster"}


@pytest.mark.parametrize(("resume", "wanted"), [
    (None, None), ("600", None),
    ({"position": 29, "total": 100}, None),
    ({"position": 30, "total": 100}, 30),
    ({"position": 100, "total": 100}, None),
    ({"position": 50, "total": 0}, None),
    ({"position": "abc", "total": 100}, None),
    ({"position": [1], "total": 100}, None),
    ({"position": "45.7", "total": "100"}, 45),
    # JSON-RPC answers may carry NaN and Infinity (json.loads reads them).
    ({"position": float("nan"), "total": 100}, None),
    ({"position": float("inf"), "total": float("nan")}, None),
    ({"position": 60, "total": float("nan")}, None),
    ({"position": 60, "total": float("inf")}, None),
])
def test_a_resume_point_counts_from_30_seconds_before_the_end(kodi, resume, wanted):
    assert film(kodi, resume=resume).get("resume") == wanted


def test_a_resume_point_that_is_no_number_spoils_no_list(kodi):
    broken = {"position": float("nan"), "total": 100}
    kodi.rows("VideoLibrary.GetMovies", "movies", [
        {"movieid": 1, "title": "A", "resume": broken}, {"movieid": 2, "title": "B"}])
    assert [entry["id"] for entry in library.movies()["movies"]] == [1, 2]
    kodi.rows("VideoLibrary.GetEpisodes", "episodes", [{"episodeid": 3, "resume": broken}])
    assert library.set_watched("tvshow", 9, True) is True
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 3, "title": "Ep", "resume": broken}]}}
    assert library.continuing()["items"] == []


@pytest.mark.parametrize(("ratings", "wanted"), [
    (None, None),
    ([7.0], None),
    ({"imdb": "7.0"}, None),
    ({"imdb": {"rating": "bad"}}, None),
    ({"imdb": {"rating": [7]}}, None),
    ({"imdb": {"rating": 0}}, None),
    ({"imdb": {"rating": 11}, "themoviedb": {"rating": 6.66}}, (6.7, "tmdb")),
    ({"imdb": {"rating": "x"}, "tmdb": {"rating": "8"}}, (8.0, "tmdb")),
    ({"tmdb": {"rating": 5}, "imdb": {"rating": 7.25}}, (7.2, "imdb")),
])
def test_the_best_valid_rating_is_shown(kodi, ratings, wanted):
    entry = film(kodi, ratings=ratings)
    got = (entry["rating"], entry["rating_from"]) if "rating" in entry else None
    assert got == wanted


@pytest.mark.parametrize(("value", "wanted"), [
    (None, None), (20200102, None), ("   ", None), ("0000-00-00 00:00:00", None),
    (" 2024-05-01 10:00:00 ", "2024-05-01 10:00:00"),
])
def test_the_date_added_is_kept_as_sortable_text(kodi, value, wanted):
    assert film(kodi, dateadded=value).get("added") == wanted


def test_the_tag_stays_while_the_list_is_unchanged(kodi):
    kodi.rows("VideoLibrary.GetMovies", "movies", [{"movieid": 1, "title": "A"}])
    first = library.movies()["tag"]
    library.invalidate()
    assert library.movies()["tag"] == first
    assert len(kodi.sent("VideoLibrary.GetMovies")) == 2


def test_the_tag_follows_the_list(kodi):
    first = library.movies()["tag"]
    for fields in ({"movieid": 1, "title": "A"},
                   {"movieid": 1, "title": "A", "resume": {"position": 60, "total": 99}},
                   {"movieid": 1, "title": "A", "art": {"poster": "/p.jpg"}}):
        kodi.rows("VideoLibrary.GetMovies", "movies", [fields])
        library.invalidate()
        tag = library.movies()["tag"]
        assert tag != first
        first = tag


@pytest.mark.parametrize(("method", "key", "row", "edits", "read"), [
    ("VideoLibrary.GetMovies", "movies", {"movieid": 1, "title": "A"},
     [{"year": 2001}, {"ratings": {"imdb": {"rating": 7}}},
      {"ratings": {"tmdb": {"rating": 7}}}, {"runtime": 60}, {"playcount": 1},
      {"dateadded": "2025-01-01 00:00:00"}],
     lambda: library.movies()["tag"]),
    ("VideoLibrary.GetTVShows", "tvshows", {"tvshowid": 7, "title": "S"},
     [{"year": 2001}, {"ratings": {"imdb": {"rating": 7}}},
      {"ratings": {"tmdb": {"rating": 7}}}, {"episode": 4, "watchedepisodes": 1},
      {"art": {"fanart": "/f.jpg"}}],
     lambda: library.shows()["tag"]),
])
def test_the_list_tag_follows_every_field_sent(kodi, method, key, row, edits, read):
    # The tag is the ETag: a field it leaves out never reaches a held list.
    kodi.rows(method, key, [row])
    seen = {read()}
    for edit in edits:
        kodi.rows(method, key, [{**row, **edit}])
        library.invalidate()
        seen.add(read())
    assert len(seen) == len(edits) + 1


def test_the_episode_tag_follows_every_field_sent(kodi):
    shows = [{"tvshowid": 7, "title": "Show"}]
    row = {"episodeid": 71, "title": "Pilot"}
    edits = [{"season": 1}, {"season": 2}, {"episode": 1}, {"runtime": 60},
             {"playcount": 1}, {"resume": {"position": 60, "total": 600}}]
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", shows)
    kodi.rows("VideoLibrary.GetEpisodes", "episodes", [row])
    seen = {library.episodes(7)["tag"]}
    for edit in edits:
        kodi.rows("VideoLibrary.GetEpisodes", "episodes", [{**row, **edit}])
        library.invalidate()
        seen.add(library.episodes(7)["tag"])
    # The show's title is sent with its episodes.
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [{"tvshowid": 7, "title": "Renamed"}])
    library.invalidate()
    seen.add(library.episodes(7)["tag"])
    assert len(seen) == len(edits) + 2


def test_the_continue_tag_follows_every_field_sent(kodi):
    film_row = {"movieid": 1, "title": "A", "resume": {"position": 60, "total": 600}}
    film_edits = [{"runtime": 700}, {"year": 2001}, {"ratings": {"imdb": {"rating": 7}}},
                  {"ratings": {"tmdb": {"rating": 7}}}]
    episode_row = {"episodeid": 3, "title": "Ep", "resume": {"position": 60, "total": 600}}
    episode_edits = [{"showtitle": "Show"}, {"tvshowid": 7}, {"season": 1}, {"episode": 2},
                     {"art": {"thumb": "/still.jpg"}}]
    seen = {library.continuing()["tag"]}
    for edit in film_edits:
        kodi.answers["VideoLibrary.GetMovies (in progress)"] = {
            "result": {"movies": [{**film_row, **edit}]}}
        library.invalidate()
        seen.add(library.continuing()["tag"])
    kodi.answers["VideoLibrary.GetMovies (in progress)"] = {"result": {"movies": []}}
    for edit in episode_edits:
        kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {
            "result": {"episodes": [{**episode_row, **edit}]}}
        library.invalidate()
        seen.add(library.continuing()["tag"])
    assert len(seen) == len(film_edits) + len(episode_edits) + 1


def test_poster_tags_change_with_the_path_only(kodi):
    kodi.rows("VideoLibrary.GetMovies", "movies", [
        {"movieid": 1, "title": "A", "art": {"poster": "/p.jpg"}},
        {"movieid": 2, "title": "B", "art": {"poster": "/p.jpg"}},
        {"movieid": 3, "title": "C", "art": {"poster": "/q.jpg"}},
    ])
    tags = [entry["poster"] for entry in library.movies()["movies"]]
    assert tags[0] == tags[1] != tags[2]
    assert all(re.fullmatch(r"[0-9a-f]{8}", tag) for tag in tags)


# --- Starting a film -------------------------------------------------------------

@pytest.fixture
def films(kodi):
    kodi.rows("VideoLibrary.GetMovies", "movies", [
        {"movieid": 1, "title": "Started", "resume": {"position": 300, "total": 6000}},
        {"movieid": 2, "title": "Fresh"},
    ])
    return kodi


@pytest.mark.parametrize(("movie_id", "resume", "options"), [
    (1, True, {"resume": True}),
    (1, False, {"resume": False}),
    (2, True, None),
    (2, False, {"resume": False}),
    ("3", True, None),
])
def test_playing_a_film_says_whether_to_resume(films, movie_id, resume, options):
    revision = library.revision()
    assert library.play(movie_id, resume=resume) is True
    wanted = {"item": {"movieid": int(movie_id)}}
    if options:
        wanted["options"] = options
    assert films.sent("Player.Open") == [wanted]
    assert library.revision() == revision + 1
    assert f"film {int(movie_id)} started from the dashboard" in info_lines()[-1]


def test_a_refused_film_keeps_the_lists(films):
    films.answers["Player.Open"] = {"error": {"code": -32602}}
    revision = library.revision()
    assert library.play(1) is False
    assert library.revision() == revision
    assert not any("started from the dashboard" in line for line in logged())


# --- Series ----------------------------------------------------------------------

def test_series_rows_without_an_id_or_title_are_left_out(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [
        None,
        {"tvshowid": 7.0, "title": "Float id"},
        {"tvshowid": 8, "title": None, "label": ""},
        {"tvshowid": 9, "label": "Bare"},
    ])
    assert library.shows()["shows"] == [{"id": 9, "title": "Bare", "poster": "", "fanart": ""}]
    assert "1 series read from the video database" in info_lines()[-1]


def test_a_full_series_row(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [
        {"tvshowid": 7, "title": "Show", "year": 2008, "episode": 10, "watchedepisodes": 4,
         "art": {"poster": "/tv/p.jpg", "fanart": "/tv/f.jpg"},
         "ratings": {"themoviedb": {"rating": 9.1}}, "dateadded": "2025-01-01 00:00:00"}])
    listing = library.shows()
    [show] = listing["shows"]
    assert show["fanart"] and show["poster"] and show["fanart"] != show["poster"]
    assert {key: value for key, value in show.items() if key not in ("poster", "fanart")} == {
        "id": 7, "title": "Show", "year": 2008, "episodes": 10, "unseen": 6,
        "rating": 9.1, "rating_from": "tmdb", "added": "2025-01-01 00:00:00"}
    assert listing["count"] == 1
    assert library.show_art_path(7, "fanart") == "/tv/f.jpg"
    assert library.show_art_path("x", "poster") == ""


@pytest.mark.parametrize(("fields", "wanted"), [
    ({"episode": 10, "watchedepisodes": 10}, {"episodes": 10, "unseen": 0, "watched": True}),
    ({"episode": 10, "watchedepisodes": 12}, {"episodes": 10, "unseen": 0, "watched": True}),
    ({"episode": 10, "watchedepisodes": None}, {"episodes": 10}),
    ({"episode": 0, "watchedepisodes": 0}, {}),
    ({"episode": "10", "watchedepisodes": 2}, {}),
    ({"year": -1}, {}),
])
def test_series_episode_counts(kodi, fields, wanted):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [{"tvshowid": 7, "title": "S", **fields}])
    [show] = library.shows()["shows"]
    assert {key: value for key, value in show.items()
            if key not in ("id", "title", "poster", "fanart")} == wanted


# --- Episodes --------------------------------------------------------------------

@pytest.fixture
def show(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [{"tvshowid": 6, "title": "Other"},
                                                     {"tvshowid": 7, "title": "Show"}])
    kodi.rows("VideoLibrary.GetEpisodes", "episodes", [
        "junk",
        {"episodeid": "70", "title": "Id as text"},
        {"episodeid": 71, "title": "Pilot", "season": 1, "episode": 1, "runtime": 2700,
         "playcount": 1, "resume": {"position": 120, "total": 2700},
         "art": {"season.poster": "/tv/s1.jpg", "tvshow.poster": "/tv/p.jpg"}},
        {"episodeid": 72, "season": -1, "episode": "2", "runtime": 0, "playcount": 0},
    ])
    return kodi


def test_episode_rows(show):
    listing = library.episodes(7)
    assert listing["tvshowid"] == 7 and listing["title"] == "Show" and listing["count"] == 2
    pilot, untitled = listing["episodes"]
    assert pilot["thumb"]
    assert {key: value for key, value in pilot.items() if key != "thumb"} == {
        "id": 71, "title": "Pilot", "season": 1, "episode": 1, "duration": 2700,
        "watched": True, "resume": 120}
    # No invented title, and no season or number out of range.
    assert untitled == {"id": 72, "title": "", "thumb": ""}
    assert listing["tag"].startswith("7-2-")
    assert show.sent("VideoLibrary.GetEpisodes") == [{
        "tvshowid": 7,
        "properties": ["title", "season", "episode", "art", "runtime", "playcount", "resume"],
        "sort": {"method": "episode", "order": "ascending"}}]
    assert library.episode_art_path(71, "thumb") == "/tv/s1.jpg"
    assert library.episode_art_path(72, "thumb") == ""
    assert any("2 episodes read for series 7" in line for line in logged())


def test_an_opened_series_is_read_once(show):
    first = library.episodes(7)
    assert library.episodes("7") == first
    assert len(show.sent("VideoLibrary.GetEpisodes")) == 1


def test_an_unknown_episode_has_no_picture(show):
    library.episodes(7)
    assert library.episode_art_path(0, "thumb") == ""
    # Known to nothing, and the "continue" row is already read.
    library.continuing()
    calls = len(show.calls)
    assert library.episode_art_path(555, "thumb") == ""
    assert len(show.calls) == calls


# --- Starting an episode ---------------------------------------------------------

@pytest.mark.parametrize(("episode_id", "resume", "options"), [
    (71, True, {"resume": True}),
    (71, False, {"resume": False}),
    (72, True, None),
])
def test_playing_an_episode_of_an_opened_series(show, episode_id, resume, options):
    library.episodes(7)
    revision = library.revision()
    assert library.play_episode(episode_id, resume=resume) is True
    wanted = {"item": {"episodeid": episode_id}}
    if options:
        wanted["options"] = options
    assert show.sent("Player.Open") == [wanted]
    assert library.revision() == revision + 1
    assert f"episode {episode_id} started from the dashboard" in info_lines()[-1]
    assert show.sent("VideoLibrary.GetEpisodeDetails") == []


def test_a_refused_episode_keeps_the_lists(show):
    show.answers["Player.Open"] = {"result": None}
    library.episodes(7)
    revision = library.revision()
    assert library.play_episode(71) is False
    assert library.revision() == revision
    assert library.play_episode(0) is False


def test_an_episode_on_the_continue_row_resumes_from_there(kodi):
    kodi.answers["VideoLibrary.GetMovies (in progress)"] = {"result": {"movies": [
        {"movieid": 5, "title": "Film", "resume": {"position": 50, "total": 500}}]}}
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 5, "title": "Ep", "resume": {"position": 90, "total": 900}},
        {"episodeid": 6, "title": "Ep 2", "resume": {"position": 40, "total": 900}}]}}
    library.continuing()
    assert library.play_episode(6)
    assert kodi.sent("Player.Open")[-1] == {"item": {"episodeid": 6}, "options": {"resume": True}}
    library.continuing()
    # Episode 5 shares its id with a film on the row; a film's point is not used.
    assert library.series._episode_resume_point(5) == 90
    assert library.series._episode_resume_point(8) == 0
    assert kodi.sent("VideoLibrary.GetEpisodeDetails") == []


def test_an_episode_of_an_unopened_series_is_found_past_the_opened_ones(show):
    show.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 99, "title": "Elsewhere", "resume": {"position": 90, "total": 900}}]}}
    library.episodes(7)
    library.continuing()
    assert library.series._episode_resume_point(99) == 90
    assert show.sent("VideoLibrary.GetEpisodeDetails") == []


@pytest.mark.parametrize(("answer", "options"), [
    ({"result": {"episodedetails": {"resume": {"position": 400, "total": 1200}}}},
     {"resume": True}),
    ({"result": {"episodedetails": {"resume": {"position": 10, "total": 1200}}}}, None),
    ({"result": {"episodedetails": None}}, None),
    ({"result": "OK"}, None),
    ({"error": {"code": -32602}}, None),
])
def test_after_a_drop_the_resume_point_is_asked_from_kodi(kodi, answer, options):
    kodi.answers["VideoLibrary.GetEpisodeDetails"] = answer
    assert library.play_episode(12) is True
    assert kodi.sent("VideoLibrary.GetEpisodeDetails") == [
        {"episodeid": 12, "properties": ["resume"]}]
    wanted = {"item": {"episodeid": 12}}
    if options:
        wanted["options"] = options
    assert kodi.sent("Player.Open") == [wanted]


def test_a_series_still_being_read_is_skipped_for_the_resume_point(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [{"tvshowid": 7, "title": "Show"}])
    kodi.answers["VideoLibrary.GetEpisodeDetails"] = {"result": {"episodedetails": {
        "resume": {"position": 77, "total": 700}}}}
    asked = []

    def episodes_in_flight(_params):
        # Asked while the episode list is read: its slot holds nothing yet.
        asked.append(library.series._episode_resume_point(70))
        return {"result": {"episodes": [{"episodeid": 70, "title": "Pilot"}]}}

    kodi.answers["VideoLibrary.GetEpisodes"] = episodes_in_flight
    library.episodes(7)
    assert asked == [77]


def test_an_episode_still_is_found_again_after_a_drop(kodi):
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 99, "title": "Started", "resume": {"position": 90, "total": 900},
         "art": {"thumb": "/tv/started.jpg"}}]}}
    library.continuing()
    library.invalidate()
    # The drop forgot the still; the "continue" row is read again to find it.
    assert library.episode_art_path(99, "thumb") == "/tv/started.jpg"
    assert len(kodi.sent("VideoLibrary.GetEpisodes")) == 2


@pytest.mark.parametrize(("call", "wanted"), [
    (lambda: library.play(0), False),
    (lambda: library.play("x"), False),
    (lambda: library.play_episode(None), False),
    (lambda: library.episodes("x"), None),
    (lambda: library.set_watched("movie", -1, True), False),
    (lambda: library.set_watched("tvshow", "x", True), False),
    (lambda: library.set_watched("album", 3, True), False),
    (lambda: library.episode_art_path("x", "thumb"), ""),
])
def test_bad_ids_and_kinds_ask_kodi_nothing(kodi, call, wanted):
    revision = library.revision()
    got = call()
    assert got == wanted and type(got) is type(wanted)
    assert kodi.calls == []
    assert library.revision() == revision


# --- Seen and unseen -------------------------------------------------------------

def test_marking_a_film_watched_sets_a_play_count_and_clears_the_resume_point(kodi):
    revision = library.revision()
    assert library.set_watched("movie", 3, True) is True
    [params] = kodi.sent("VideoLibrary.SetMovieDetails")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", params.pop("lastplayed"))
    assert params == {"movieid": 3, "playcount": 1, "resume": {"position": 0, "total": 0}}
    assert library.revision() == revision + 1
    assert "movie 3 marked seen from the dashboard" in info_lines()[-1]


def test_marking_an_episode_unwatched_keeps_its_resume_point(kodi):
    assert library.set_watched("episode", "4", False) is True
    assert kodi.sent("VideoLibrary.SetEpisodeDetails") == [{"episodeid": 4, "playcount": 0}]
    assert "episode 4 marked unseen from the dashboard" in info_lines()[-1]


def test_a_refused_mark_still_drops_the_lists_but_logs_nothing(kodi):
    kodi.answers["VideoLibrary.SetMovieDetails"] = {"error": {"code": -32602}}
    revision = library.revision()
    assert library.set_watched("movie", 3, True) is False
    assert library.revision() == revision + 1
    assert info_lines() == []


@pytest.fixture
def series_episodes(kodi):
    kodi.rows("VideoLibrary.GetEpisodes", "episodes", [
        "junk",
        {"episodeid": None, "playcount": 0},
        {"episodeid": 1, "playcount": 0},
        {"episodeid": 2, "playcount": 1},
        {"episodeid": 3, "playcount": 1, "resume": {"position": 300, "total": 1000}},
        {"episodeid": 4, "playcount": "1"},
    ])
    return kodi


@pytest.mark.parametrize(("watched", "written"), [
    # Watched episodes with a resume point are written again to clear it.
    (True, [1, 3, 4]),
    (False, [2, 3]),
])
def test_marking_a_series_writes_only_the_episodes_that_change(series_episodes, watched,
                                                               written):
    assert library.set_watched("tvshow", 9, watched) is True
    assert series_episodes.sent("VideoLibrary.GetEpisodes") == [
        {"tvshowid": 9, "properties": ["playcount", "resume"]}]
    sent = series_episodes.sent("VideoLibrary.SetEpisodeDetails")
    assert [params["episodeid"] for params in sent] == written
    assert all(params["playcount"] == int(watched) for params in sent)
    assert f"tvshow 9 marked {'seen' if watched else 'unseen'}" in info_lines()[-1]


def test_one_refused_episode_fails_the_series_mark(series_episodes):
    series_episodes.answers["VideoLibrary.SetEpisodeDetails"] = (
        lambda params: {"result": "OK" if params["episodeid"] != 1 else None})
    assert library.set_watched("tvshow", 9, True) is False
    # The others are still written.
    assert len(series_episodes.sent("VideoLibrary.SetEpisodeDetails")) == 3


def test_a_series_whose_episodes_cannot_be_read_is_not_marked(kodi):
    kodi.answers["VideoLibrary.GetEpisodes"] = {"error": {"code": -32602}}
    revision = library.revision()
    assert library.set_watched("tvshow", 9, True) is False
    assert kodi.sent("VideoLibrary.SetEpisodeDetails") == []
    assert library.revision() == revision + 1
    assert any("VideoLibrary.GetEpisodes failed for 9" in line for line in logged())


def test_marking_a_series_without_episodes_succeeds(kodi):
    assert library.set_watched("tvshow", 9, False) is True
    assert kodi.sent("VideoLibrary.SetEpisodeDetails") == []


@pytest.mark.parametrize(("kind", "method", "key"), [
    ("movie", "VideoLibrary.SetMovieDetails", "movieid"),
    ("episode", "VideoLibrary.SetEpisodeDetails", "episodeid"),
])
def test_clearing_a_resume_point_keeps_the_play_count(kodi, kind, method, key):
    revision = library.revision()
    assert library.clear_resume(kind, 5) is True
    assert kodi.sent(method) == [{key: 5, "resume": {"position": 0, "total": 0}}]
    assert library.revision() == revision + 1
    assert f"{kind} 5: resume point cleared from the dashboard" in info_lines()[-1]


def test_a_refused_resume_clear_is_reported(kodi):
    kodi.answers["VideoLibrary.SetMovieDetails"] = {"error": {"code": -32602}}
    revision = library.revision()
    assert library.clear_resume("movie", 5) is False
    assert library.revision() == revision + 1
    assert info_lines() == []


@pytest.mark.parametrize(("kind", "item_id"), [("tvshow", 5), ("album", 5), ("movie", "x")])
def test_clearing_a_resume_point_of_anything_else_does_nothing(kodi, kind, item_id):
    revision = library.revision()
    assert library.clear_resume(kind, item_id) is False
    assert kodi.calls == []
    assert library.revision() == revision


# --- Continue watching -----------------------------------------------------------

def test_continue_films(kodi):
    kodi.answers["VideoLibrary.GetMovies (in progress)"] = {"result": {"movies": [
        "junk",
        {"movieid": 1, "title": "", "resume": {"position": 60, "total": 600}},
        {"movieid": 2, "title": "Not started", "resume": {"position": 0, "total": 600}},
        {"movieid": "5", "title": "Id as text", "resume": {"position": 60, "total": 600}},
        {"movieid": 3, "title": "Film", "year": 2001, "runtime": 5400,
         "resume": {"position": 60, "total": 6000}, "lastplayed": " 2026-01-01 10:00:00 ",
         "art": {"poster": "/p.jpg"}, "ratings": {"imdb": {"rating": 6.5}}},
        {"movieid": 4, "title": "Bare", "year": 0, "resume": {"position": 60, "total": "900.5"},
         "lastplayed": "   "},
    ]}}
    row = library.continuing()
    assert kodi.sent("VideoLibrary.GetMovies") == [{
        "properties": ["title", "year", "art", "runtime", "resume", "lastplayed", "ratings"],
        "filter": {"field": "inprogress", "operator": "true", "value": ""},
        "sort": {"method": "lastplayed", "order": "descending"},
        "limits": {"start": 0, "end": 30}}]
    assert kodi.sent("VideoLibrary.GetEpisodes")[0]["filter"] == {
        "field": "inprogress", "operator": "true", "value": ""}
    full, bare = row["items"]
    assert full["poster"]
    assert {key: value for key, value in full.items() if key != "poster"} == {
        "kind": "movie", "id": 3, "resume": 60, "title": "Film", "duration": 5400,
        "lastplayed": "2026-01-01 10:00:00", "year": 2001, "rating": 6.5, "rating_from": "imdb"}
    # Without a runtime the length comes from the resume point.
    assert bare == {"kind": "movie", "id": 4, "resume": 60, "title": "Bare", "duration": 900,
                    "poster": ""}
    assert row["count"] == 2 and row["tag"].startswith("11-2-")


def test_continue_episodes_carry_their_show_and_its_rating(kodi):
    kodi.rows("VideoLibrary.GetTVShows", "tvshows", [
        {"tvshowid": 7, "title": "Show", "ratings": {"imdb": {"rating": 8.5}}},
        {"tvshowid": 8, "title": "Unrated"}])
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 70, "title": "Pilot", "showtitle": "Show", "tvshowid": 7, "season": 1,
         "episode": 2, "resume": {"position": 100, "total": 1000},
         "lastplayed": "2026-01-03 00:00:00",
         "art": {"thumb": "/tv/still.jpg", "tvshow.poster": "/tv/p.jpg"}},
        {"episodeid": 80, "title": "Other", "showtitle": "", "tvshowid": 8, "season": -1,
         "episode": None, "resume": {"position": 100, "total": 1000},
         "lastplayed": "2026-01-02 00:00:00"},
        {"episodeid": 90, "title": "", "tvshowid": 0, "resume": {"position": 100, "total": 1000},
         "lastplayed": "2026-01-01 00:00:00"},
        {"episodeid": 91, "title": "Unstarted", "resume": None},
    ]}}
    first, second, third = library.continuing()["items"]
    assert first["poster"] and first["thumb"]
    assert {key: value for key, value in first.items() if key not in ("poster", "thumb")} == {
        "kind": "episode", "id": 70, "resume": 100, "title": "Pilot", "duration": 1000,
        "lastplayed": "2026-01-03 00:00:00", "show": "Show", "tvshowid": 7, "rating": 8.5,
        "rating_from": "imdb", "season": 1, "episode": 2}
    assert "show" not in second and "rating" not in second and "season" not in second
    assert second["tvshowid"] == 8 and "episode" not in second
    assert third["id"] == 90 and "tvshowid" not in third
    # The show list is read once for all episodes.
    assert len(kodi.sent("VideoLibrary.GetTVShows")) == 1
    assert library.episode_art_path(70, "thumb") == "/tv/still.jpg"
    assert library.episode_art_path(70, "poster") == "/tv/p.jpg"


def test_the_continue_row_is_most_recent_first_and_capped(kodi, monkeypatch):
    monkeypatch.setattr(library.progress, "_CONTINUE_LIMIT", 3)
    kodi.answers["VideoLibrary.GetMovies (in progress)"] = {"result": {"movies": [
        {"movieid": 1, "title": "Old film", "resume": {"position": 60, "total": 600},
         "lastplayed": "2026-01-01 00:00:00"},
        {"movieid": 2, "title": "New film", "resume": {"position": 60, "total": 600},
         "lastplayed": "2026-01-04 00:00:00"}]}}
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 3, "title": "Ep", "resume": {"position": 60, "total": 600},
         "lastplayed": "2026-01-03 00:00:00"},
        {"episodeid": 4, "title": "Never dated", "resume": {"position": 60, "total": 600}}]}}
    row = library.continuing()
    assert [(entry["kind"], entry["id"]) for entry in row["items"]] == [
        ("movie", 2), ("episode", 3), ("movie", 1)]
    assert library.continuing(films=False)["items"] == [row["items"][1]]
    assert library.continuing(films=False)["tag"].startswith("01-3-")
    assert any("3 titles in progress read" in line for line in logged())


@pytest.mark.parametrize("total", [float("nan"), float("inf")])
def test_a_resume_total_that_is_no_number_is_no_resume_point(kodi, total):
    # Like a total of 0: no length, so nothing to continue.
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 3, "title": "Ep", "resume": {"position": 60, "total": total}},
        {"episodeid": 4, "title": "Ep", "resume": {"position": 60, "total": 600}}]}}
    assert [entry["id"] for entry in library.continuing()["items"]] == [4]


def test_a_broken_series_read_leaves_continue_episodes_unrated(kodi):
    def broken(_params):
        raise RuntimeError("database locked")

    kodi.answers["VideoLibrary.GetTVShows"] = broken
    kodi.answers["VideoLibrary.GetEpisodes (in progress)"] = {"result": {"episodes": [
        {"episodeid": 3, "title": "Ep", "tvshowid": 7, "resume": {"position": 60, "total": 600}},
        {"episodeid": 4, "title": "Ep", "tvshowid": 7, "resume": {"position": 60, "total": 600}}]}}
    items = library.continuing()["items"]
    assert [entry["id"] for entry in items] == [3, 4]
    assert all("rating" not in entry and entry["tvshowid"] == 7 for entry in items)
    # Asked once only: the failure still counts as an answer.
    assert len(kodi.sent("VideoLibrary.GetTVShows")) == 1
    assert any("reading the series for their ratings failed: database locked" in line
               for line in logged())
