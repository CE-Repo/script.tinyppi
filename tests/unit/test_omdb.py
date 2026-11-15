# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Every award a title won and was nominated for, counted (web/omdb.py)."""

import http.client
import json
import urllib.error

import pytest

import xbmcaddon
from web import omdb
from web.omdb import api_key, awards_total, fetch, totals_of


class Answer:
    """OMDb's answer to one request, as urlopen hands it out."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, _limit):
        return self.body


@pytest.fixture
def asked(monkeypatch):
    """Answer OMDb's requests from ``found`` (an answer, or an error to
    raise) at a clock the test turns; record the addresses asked."""
    held = {"found": {"Awards": "4 wins & 7 nominations total"}, "urls": [], "now": 100.0}

    def urlopen(request, timeout):
        held["urls"].append(request.full_url)
        held["timeout"] = timeout
        if isinstance(held["found"], Exception):
            raise held["found"]
        return Answer(held["found"])

    monkeypatch.setattr(omdb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(omdb, "_clock", lambda: held["now"])
    omdb._CACHE.clear()
    omdb._RESTING.clear()
    return held


def refusal(code):
    return urllib.error.HTTPError("https://www.omdbapi.com/", code, "no", {}, None)


# --- An answer -----------------------------------------------------------------

@pytest.mark.parametrize(("said", "total"), [
    ("4 wins & 7 nominations total", (4, 7)),
    # The big ones before the totals are counted among them already.
    ("Won 2 Oscars. 45 wins & 80 nominations total", (45, 80)),
    ("Nominated for 1 Oscar. 5 wins & 20 nominations total", (5, 20)),
    ("Won 1 Primetime Emmy. 3 wins total", (3, 0)),
    ("1 win & 1 nomination", (1, 1)),
    ("2 nominations", (0, 2)),
    ("1 win", (1, 0)),
])
def test_the_totals_are_read_from_omdbs_sentence(said, total):
    assert totals_of({"Awards": said}) == {"won": total[0], "nominated": total[1]}


@pytest.mark.parametrize("answer", [
    {"Awards": "N/A"}, {"Awards": ""}, {"Awards": None}, {"Awards": 7},
    {"Awards": "Won 2 Oscars."}, {"Awards": "0 wins & 0 nominations"},
    {"Response": "False", "Error": "Incorrect IMDb ID."}, {}, [], "junk", None,
])
def test_an_answer_without_totals_has_none(answer):
    assert totals_of(answer) is None


def test_a_count_no_title_has_is_not_read():
    assert totals_of({"Awards": "99999 wins"}) is None
    assert totals_of({"Awards": "9999 wins & 1234 nominations"}) == {"won": 9999,
                                                                     "nominated": 1234}


# --- Asking --------------------------------------------------------------------

def test_a_title_is_asked_for_by_its_imdb_id(asked):
    assert fetch("a key&more", "tt0218967") == ({"won": 4, "nominated": 7}, omdb._KEPT)
    assert asked["urls"] == ["https://www.omdbapi.com/?i=tt0218967&apikey=a+key%26more"]
    assert asked["timeout"] == omdb._TIMEOUT


def test_a_title_omdb_does_not_know_has_none_for_a_day(asked):
    asked["found"] = {"Response": "False", "Error": "Incorrect IMDb ID."}
    assert fetch("KEY", "tt1") == (None, omdb._KEPT)


@pytest.mark.parametrize("error", [
    refusal(500), OSError("down"), TimeoutError(), http.client.IncompleteRead(b""),
])
def test_a_title_omdb_cannot_be_reached_for_is_asked_again_before_long(asked, error):
    asked["found"] = error
    assert fetch("KEY", "tt1") == (None, omdb._AGAIN)


def test_an_answer_that_is_no_json_is_none(asked):
    asked["found"] = b"<html>"
    assert fetch("KEY", "tt1") == (None, omdb._AGAIN)


def test_a_refused_key_is_said(asked):
    asked["found"] = refusal(401)
    with pytest.raises(omdb._Refused):
        fetch("KEY", "tt1")


# --- Kept ----------------------------------------------------------------------

def test_an_answer_is_kept_for_a_day(asked):
    assert awards_total("KEY", "tt0218967") == {"won": 4, "nominated": 7}
    asked["now"] += omdb._KEPT - 1
    assert awards_total("KEY", "tt0218967") == {"won": 4, "nominated": 7}
    assert len(asked["urls"]) == 1
    asked["now"] += 1
    asked["found"] = {"Awards": "5 wins & 7 nominations total"}
    assert awards_total("KEY", "tt0218967") == {"won": 5, "nominated": 7}
    assert len(asked["urls"]) == 2


def test_a_title_without_awards_is_not_asked_for_twice(asked):
    asked["found"] = {"Awards": "N/A"}
    assert awards_total("KEY", "tt1") is None
    assert awards_total("KEY", "tt1") is None
    assert len(asked["urls"]) == 1


def test_a_title_that_failed_is_asked_for_again_before_long(asked):
    asked["found"] = OSError("down")
    assert awards_total("KEY", "tt1") is None
    assert awards_total("KEY", "tt1") is None
    assert len(asked["urls"]) == 1
    asked["now"] += omdb._AGAIN
    asked["found"] = {"Awards": "1 win"}
    assert awards_total("KEY", "tt1") == {"won": 1, "nominated": 0}


@pytest.mark.parametrize(("key", "imdb"), [
    ("", "tt0218967"), ("KEY", ""), ("KEY", "0218967"), ("KEY", "tt1&apikey=x"),
])
def test_nothing_is_asked_without_a_key_or_an_imdb_id(asked, key, imdb):
    assert awards_total(key, imdb) is None
    assert asked["urls"] == []


def test_a_refused_key_rests_for_an_hour(asked):
    asked["found"] = refusal(401)
    assert awards_total("KEY", "tt1") is None
    assert awards_total("KEY", "tt2") is None
    assert len(asked["urls"]) == 1
    # Another key is tried at once.
    asked["found"] = {"Awards": "1 win"}
    assert awards_total("OTHER", "tt1") == {"won": 1, "nominated": 0}
    asked["now"] += omdb._RESTS
    assert awards_total("KEY", "tt2") == {"won": 1, "nominated": 0}


def test_only_so_many_titles_are_kept(asked, monkeypatch):
    monkeypatch.setattr(omdb, "_LIMIT", 2)
    for imdb in ("tt1", "tt2", "tt3"):
        awards_total("KEY", imdb)
    assert [wanted[1] for wanted in omdb._CACHE] == ["tt2", "tt3"]


def test_the_key_is_the_readers_and_optional(monkeypatch):
    assert api_key() == ""
    xbmcaddon.SETTINGS["web_omdb_key"] = "  KEY  "
    assert api_key() == "KEY"

    def updating():
        raise RuntimeError("being updated")

    monkeypatch.setattr(omdb.settings, "addon", updating)
    assert api_key() == ""
