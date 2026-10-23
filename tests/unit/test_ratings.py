# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing title's ratings for the plot card (web/ratings.py)."""

import pytest

import xbmc
from web import ratings
from web.ratings import age_mark, home_country, no_ratings, playing_ratings, rating_list

IMDB = {"default": True, "rating": 8.54, "votes": 612345}
TMDB = {"default": False, "rating": 8.2, "votes": 6120}


class Kodi:
    """Answers JSON-RPC for a video playing from the library; records calls."""

    def __init__(self, item=None, details=None, show=None, players=True):
        self.item = {"id": 12, "type": "movie"} if item is None else item
        self.details = details if details is not None else {}
        self.show = show if show is not None else {}
        self.players = players
        self.calls = []

    def __call__(self, request):
        method, params = request["method"], request.get("params", {})
        self.calls.append((method, params))
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1, "type": "video"}] if self.players else []}
        if method == "Player.GetItem":
            return {"result": {"item": self.item}}
        if method == "VideoLibrary.GetMovieDetails":
            return {"result": {"moviedetails": self.details}}
        if method == "VideoLibrary.GetEpisodeDetails":
            return {"result": {"episodedetails": self.details}}
        if method == "VideoLibrary.GetTVShowDetails":
            return {"result": {"tvshowdetails": self.show}}
        return {"result": "OK"}

    def methods(self):
        return [method for method, _params in self.calls]


def answer(fake):
    xbmc.RPC = fake
    return playing_ratings()


# --- The list ------------------------------------------------------------------

def test_known_sources_come_first_in_their_order_and_the_rest_alphabetically():
    found = rating_list({
        "zeta": {"rating": 6.0}, "Trakt": {"rating": 7.9, "votes": 30},
        "themoviedb": TMDB, "alpha": {"rating": 5.0, "votes": 2}, "imdb": IMDB,
        "tvdb": {"rating": 8.0}, "metacritic": {"rating": 7.7}, "rottentomatoes": {"rating": 9.1},
    })
    assert [entry["source"] for entry in found] == [
        "imdb", "tmdb", "trakt", "tvdb", "metacritic", "rottentomatoes", "alpha", "zeta"]
    assert found[0] == {"source": "imdb", "rating": 8.5, "votes": 612345}
    assert found[1] == {"source": "tmdb", "rating": 8.2, "votes": 6120}


def test_a_source_under_two_names_is_kept_once_as_it_came_first():
    found = rating_list({"tmdb": {"rating": 7.1}, "themoviedb": {"rating": 9.9}})
    assert found == [{"source": "tmdb", "rating": 7.1, "votes": 0}]


@pytest.mark.parametrize(("name", "source"), [
    ("metascore", "metacritic"), ("tomatometer", "rottentomatoes"),
    ("tomatometerallcritics", "rottentomatoes"), ("TheMovieDb", "tmdb"),
])
def test_the_other_names_a_source_goes_by_are_known(name, source):
    assert rating_list({name: {"rating": 8.0}})[0]["source"] == source


@pytest.mark.parametrize("held", [
    None, "8.5", {"rating": 0}, {"rating": -1}, {"rating": 10.5}, {"rating": "x"},
    {"rating": [1]}, {"rating": float("nan")}, {},
])
def test_what_is_no_rating_out_of_ten_is_left_out(held):
    assert rating_list({"imdb": held}) == []


@pytest.mark.parametrize(("votes", "kept"), [
    (12, 12), (0, 0), (-3, 0), (True, 0), ("12", 0), (1.5, 0), (None, 0),
])
def test_only_a_whole_count_of_votes_is_kept(votes, kept):
    assert rating_list({"imdb": {"rating": 7.0, "votes": votes}})[0]["votes"] == kept


def test_names_are_cleaned_cut_short_and_a_nameless_source_is_left_out():
    found = rating_list({"[B]Rotten Tomatoes Critics Consensus[/B]": {"rating": 9.1},
                         "": {"rating": 5.0}, " ": {"rating": 5.0}})
    assert [entry["source"] for entry in found] == ["rotten tomatoes critics"]


def test_a_long_list_is_cut_off():
    found = rating_list({f"source{index:02d}": {"rating": 5.0} for index in range(12)})
    assert len(found) == 8


@pytest.mark.parametrize("value", [None, [], "imdb", 8.5])
def test_a_list_that_is_no_mapping_is_no_list(value):
    assert rating_list(value) == []


# --- The age rating ------------------------------------------------------------------

@pytest.mark.parametrize(("mpaa", "mark"), [
    # German, however it is written.
    ("FSK 12", "fsk12"), ("FSK12", "fsk12"), ("fsk 0", "fsk0"), ("FSK ab 16 freigegeben", "fsk16"),
    ("DE:FSK 18", "fsk18"), ("Germany:6", "fsk6"), ("de: ab 12", "fsk12"), ("Deutschland:16", "fsk16"),
    # American films and television, with and without the scraper's prefix.
    ("Rated PG-13", "mpa_pg13"), ("PG-13", "mpa_pg13"), ("Rated R", "mpa_r"), ("G", "mpa_g"),
    ("Rated NC-17", "mpa_nc17"), ("US:PG", "mpa_pg"), ("MPAA PG", "mpa_pg"), ("TV-MA", "tv_ma"),
    ("Rated TV-14", "tv_14"), ("tv-y7", "tv_y7"), ("USA:TV-PG", "tv_pg"),
    # British.
    ("Rated 15", "bbfc_15"), ("12A", "bbfc_12a"), ("U", "bbfc_u"), ("R18", "bbfc_r18"),
    ("GB:12", "bbfc_12"), ("UK:PG", "bbfc_pg"), ("BBFC 18", "bbfc_18"), ("United Kingdom:15", "bbfc_15"),
    # A level a country's board does not give, a country there are no marks
    # for, and what is no age rating at all.
    ("FSK 14", ""), ("FSK 120", ""), ("US:15", ""), ("GB:PG-13", ""), ("FR:12", ""), ("USK 12", ""),
    ("Rated PG-13 for violence", ""), ("Rated", ""), ("", ""),
])
def test_an_age_rating_is_read_for_its_board_and_level(mpaa, mark):
    assert age_mark(mpaa, home="de") == mark


@pytest.mark.parametrize(("mpaa", "home", "mark"), [
    ("Rated 12", "de", "fsk12"), ("Rated 12", "gb", "bbfc_12"), ("18", "de", "fsk18"),
    ("Rated PG", "us", "mpa_pg"), ("PG", "gb", "bbfc_pg"),
    # Neither of the boards that give it is the home one's.
    ("Rated 12", "us", ""), ("PG", "de", ""), ("12", "", ""),
    # A level only one board gives is that board's whatever the home.
    ("Rated 16", "gb", "fsk16"), ("PG-13", "de", "mpa_pg13"),
])
def test_a_level_more_than_one_board_gives_is_read_as_the_home_one(mpaa, home, mark):
    assert age_mark(mpaa, home) == mark


@pytest.mark.parametrize(("language", "home"), [
    ("de-de", "de"), ("de-AT", "de"), ("de", "de"), ("en-gb", "gb"), ("en", "gb"),
    ("en-US", "us"), ("en_us", "us"), ("en-au", ""), ("fr-fr", ""),
])
def test_the_home_country_is_the_one_kodis_language_points_to(monkeypatch, language, home):
    asked = []
    monkeypatch.setattr(xbmc, "getLanguage", lambda form, region: asked.append((form, region)) or language)
    assert home_country() == home
    assert asked == [(xbmc.ISO_639_1, True)]


# --- What is playing ---------------------------------------------------------------

def test_a_film_brings_every_kind_of_rating():
    fake = Kodi(details={"ratings": {"imdb": IMDB, "themoviedb": TMDB}, "userrating": 9,
                         "mpaa": "[B]FSK 12[/B]", "top250": 27})
    assert answer(fake) == {
        "ratings": [{"source": "imdb", "rating": 8.5, "votes": 612345},
                    {"source": "tmdb", "rating": 8.2, "votes": 6120}],
        "mpaa": "FSK 12", "age": "fsk12", "userrating": 9, "top250": 27,
    }
    assert ("VideoLibrary.GetMovieDetails",
            {"movieid": 12, "properties": ["ratings", "userrating", "mpaa", "top250"]}) in fake.calls


@pytest.mark.parametrize(("userrating", "top250", "kept"), [
    (0, 0, (0, 0)), (11, 251, (0, 0)), (10, 250, (10, 250)), (None, "27", (0, 0)),
])
def test_an_own_rating_runs_to_ten_and_the_top_list_to_250(userrating, top250, kept):
    result = answer(Kodi(details={"userrating": userrating, "top250": top250}))
    assert (result["userrating"], result["top250"]) == kept


def test_an_episode_rates_itself_and_takes_its_age_rating_from_its_show():
    fake = Kodi(item={"id": 7, "type": "episode"},
                details={"ratings": {"tvdb": {"rating": 8.8, "votes": 40}}, "userrating": 7,
                         "tvshowid": 3, "mpaa": "ignored"},
                show={"mpaa": "FSK 16"})
    assert answer(fake) == {"ratings": [{"source": "tvdb", "rating": 8.8, "votes": 40}],
                            "mpaa": "FSK 16", "age": "fsk16", "userrating": 7, "top250": 0}
    assert ("VideoLibrary.GetTVShowDetails", {"tvshowid": 3, "properties": ["mpaa"]}) in fake.calls


def test_an_episode_without_a_show_has_no_age_rating():
    fake = Kodi(item={"id": 7, "type": "episode"}, details={"ratings": {}})
    assert answer(fake) == no_ratings()
    assert "VideoLibrary.GetTVShowDetails" not in fake.methods()


@pytest.mark.parametrize("item", [
    {"type": "unknown", "label": "Film.mkv"}, {"id": 0, "type": "movie"},
    {"id": True, "type": "movie"}, {"id": 4, "type": "channel"},
])
def test_a_file_outside_the_library_has_none_and_says_so(item):
    fake = Kodi(item=item)
    assert answer(fake) == no_ratings()
    assert fake.methods() == ["Player.GetActivePlayers", "Player.GetItem"]


def test_kodi_that_cannot_say_yet_what_plays_is_asked_again_later():
    assert answer(Kodi(players=False)) is None
    assert answer(Kodi(item={})) is None


@pytest.mark.parametrize("result", ["OK", None, {"moviedetails": "x"}, {}])
def test_a_library_answer_of_the_wrong_shape_is_no_ratings(monkeypatch, result):
    answers = {"Player.GetActivePlayers": [{"playerid": 1, "type": "video"}],
               "Player.GetItem": {"item": {"id": 1, "type": "movie"}}}
    monkeypatch.setattr(ratings, "rpc", lambda method, params=None: {"result": answers.get(method, result)})
    monkeypatch.setattr(ratings, "video_player_id", lambda: 1)
    assert playing_ratings() == no_ratings()
