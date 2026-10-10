# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's library cache (web/library.py)."""

import threading
import time

import pytest

from web import library


class FakeLibrary:
    """Answer the JSON-RPC calls of web/library.py; GetMovies can be held."""

    def __init__(self):
        self.title = "Old"
        self.movie_reads = 0
        self.release = threading.Event()
        self.release.set()

    def __call__(self, method, params=None):
        params = params or {}
        if method == "VideoLibrary.GetMovies" and "filter" not in params:
            self.movie_reads += 1
            title = self.title
            self.release.wait(5)
            return {"result": {"movies": [
                {"movieid": 1, "title": title, "year": 2017, "art": {"poster": "/films/p.jpg"},
                 "ratings": {"imdb": {"rating": 7.4}}, "resume": {"position": 0, "total": 0}}]}}
        if method == "VideoLibrary.GetTVShows":
            return {"result": {"tvshows": [
                {"tvshowid": 7, "title": "Show", "episode": 2, "watchedepisodes": 1,
                 "art": {"poster": "/tv/show.jpg"}}]}}
        if method == "VideoLibrary.GetEpisodes" and "filter" in params:
            return {"result": {"episodes": [
                {"episodeid": 99, "title": "Started", "tvshowid": 7, "resume": {"position": 100, "total": 1000},
                 "art": {"thumb": "/tv/started.jpg", "tvshow.poster": "/tv/show.jpg"},
                 "lastplayed": "2026-10-01 20:00:00"}]}}
        if method == "VideoLibrary.GetEpisodes":
            return {"result": {"episodes": [
                {"episodeid": 70, "title": "Pilot", "season": 1, "episode": 1, "art": {"thumb": "/tv/pilot.jpg"}}]}}
        if method == "VideoLibrary.GetMovies":
            return {"result": {"movies": []}}
        return {"result": "OK"}


@pytest.fixture
def kodi(monkeypatch):
    fake = FakeLibrary()
    monkeypatch.setattr(library, "rpc", fake)
    monkeypatch.setattr(library, "_cache", library._Cache())
    return fake


def test_concurrent_readers_share_one_query(kodi):
    kodi.release.clear()
    answers = []
    readers = [threading.Thread(target=lambda: answers.append(library.movies())) for _ in range(5)]
    for reader in readers:
        reader.start()
    time.sleep(0.2)
    kodi.release.set()
    for reader in readers:
        reader.join()
    assert kodi.movie_reads == 1
    assert [a["movies"][0]["title"] for a in answers] == ["Old"] * 5


def test_a_read_overtaken_by_a_drop_is_not_kept(kodi):
    kodi.release.clear()
    answers = []
    reader = threading.Thread(target=lambda: answers.append(library.movies()))
    reader.start()
    time.sleep(0.2)
    kodi.title = "New"
    library.invalidate()        # the change lands while the read runs
    kodi.release.set()
    reader.join()
    assert answers[0]["movies"][0]["title"] == "Old"
    assert library.movies()["movies"][0]["title"] == "New"
    assert kodi.movie_reads == 2


def test_lists_are_cached_until_dropped(kodi):
    first = library.movies()
    assert library.movies() is not None and kodi.movie_reads == 1
    revision = library.revision()
    library.invalidate()
    assert library.revision() == revision + 1
    assert library.movies()["tag"] == first["tag"]
    assert kodi.movie_reads == 2


def test_a_burst_of_item_notifications_is_one_drop(kodi, monkeypatch):
    monkeypatch.setattr(library, "_QUIET", 0.3)
    monkeypatch.setattr(library, "_BURST_LIMIT", 1.0)
    start = library.revision()
    for _ in range(5):
        library.changed()
        time.sleep(0.05)
    assert library.revision() == start
    time.sleep(0.35)
    assert library.revision() == start + 1
    assert library.revision() == start + 1


def test_a_long_burst_still_drops_every_burst_limit(kodi, monkeypatch):
    monkeypatch.setattr(library, "_QUIET", 0.3)
    monkeypatch.setattr(library, "_BURST_LIMIT", 1.0)
    start = library.revision()
    began = time.monotonic()
    bumped = None
    while time.monotonic() - began < 1.6:
        library.changed()
        time.sleep(0.1)
        if bumped is None and library.revision() != start:
            bumped = time.monotonic() - began
    assert bumped is not None and 0.9 <= bumped <= 1.25


def test_settle_drops_twice_and_a_drop_covers_a_pending_burst(kodi, monkeypatch):
    monkeypatch.setattr(library, "_SETTLE", (0.1, 0.2))
    start = library.revision()
    library.settle()
    time.sleep(0.15)
    assert library.revision() == start + 1
    time.sleep(0.1)
    assert library.revision() == start + 2
    library.changed()
    library.invalidate()
    after = library.revision()
    time.sleep(2.2)
    assert library.revision() == after


def test_film_fields_and_art(kodi):
    film = library.movies()["movies"][0]
    assert film["title"] == "Old" and film["year"] == 2017
    assert film["rating"] == 7.4 and film["rating_from"] == "imdb"
    assert film["poster"]
    assert library.art_path(1, "poster") == "/films/p.jpg"


def test_episodes_and_their_art(kodi):
    listing = library.episodes(7)
    assert listing["title"] == "Show" and listing["episodes"][0]["id"] == 70
    assert library.episode_art_path(70, "thumb") == "/tv/pilot.jpg"
    assert library.episodes(999) is None
    assert library.episodes("not a number") is None
    assert library.show_art_path(7, "poster") == "/tv/show.jpg"


def test_continue_row_and_art_after_a_drop(kodi):
    row = library.continuing()
    assert [e["id"] for e in row["items"]] == [99]
    assert library.continuing(films=True, series=False)["items"] == []
    library.invalidate()
    # The row is read again to find the picture of an unopened show.
    assert library.episode_art_path(99, "thumb") == "/tv/started.jpg"
    assert library._episode_resume_point(99) == 100


def test_marking_drops_the_lists(kodi):
    revision = library.revision()
    assert library.set_watched("movie", 1, True)
    assert library.revision() == revision + 1
    assert not library.set_watched("movie", "x", True)
    assert not library.set_watched("album", 1, True)


@pytest.mark.parametrize(("value", "wanted"), [
    (5, 5), ("5", 5), (" 7 ", 7), (3.0, 3),
    (True, 0), (False, 0), (2.5, 0), (float("nan"), 0), (float("inf"), 0),
    (0, 0), (-4, 0), ("5.0", 0), ("x", 0), (None, 0), ([], 0), ({}, 0),
])
def test_ids_from_requests(value, wanted):
    from web.values import library_id
    assert library_id(value) == wanted


def test_a_boolean_id_starts_nothing(kodi):
    assert library.play(True) is False
    assert library.play_episode(1.5) is False
    assert library.set_watched("movie", True, True) is False
    assert library.clear_resume("episode", False) is False
