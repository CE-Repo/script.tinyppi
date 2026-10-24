# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import json

import pytest

from web import awards
from web.awards import awards_of


@pytest.fixture
def table(monkeypatch, tmp_path):
    """Awards read from a file of the test's own; the real one's cache is
    left as it was."""
    path = tmp_path / "awards.json"

    def write(content):
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        awards._table.cache_clear()

    monkeypatch.setattr(awards, "_FILE", str(path))
    yield write
    awards._table.cache_clear()


def test_the_shipped_list_holds_interstellar():
    assert awards_of("movie", "157336") == [
        {"award": "oscar", "won": ["Visual Effects (2015)"], "nominated": 4},
        {"award": "globe", "won": [], "nominated": 1}]


def test_awards_come_in_the_order_they_are_shown(table):
    table({"movie": {"1": {"emmy": [[], 1], "bafta": [["Film (2001)"], 0],
                           "oscar": [["Picture (2001)"], 2], "globe": [[], 3]}}})
    assert [award["award"] for award in awards_of("movie", "1")] == ["oscar", "globe", "bafta", "emmy"]


@pytest.mark.parametrize(("kind", "tmdb"), [("movie", "2"), ("tv", "1"), ("movie", ""), ("film", "1")])
def test_a_title_the_list_does_not_hold_has_none(table, kind, tmdb):
    table({"movie": {"1": {"oscar": [["Picture (2001)"], 0]}}})
    assert awards_of(kind, tmdb) == []


@pytest.mark.parametrize("held", [
    "oscar", [], [["Picture"]], ["Picture", 2],
    # Nothing won and nothing more, a count that is none among them.
    [[], 0], [[None, ""], -1], [[], "2"], [[], True],
])
def test_an_award_of_the_wrong_shape_is_left_out(table, held):
    table({"movie": {"1": {"oscar": held, "globe": [[], 1]}}})
    assert awards_of("movie", "1") == [{"award": "globe", "won": [], "nominated": 1}]


def test_what_it_won_is_cut_to_a_tooltip(table):
    table({"movie": {"1": {"oscar": [["x" * 100, 7, "Score (2001)"] + ["y"] * 30, -2]}}})
    (award,) = awards_of("movie", "1")
    assert award["won"][0] == "x" * 80
    assert award["won"][1] == "Score (2001)"
    assert len(award["won"]) == 20
    assert award["nominated"] == 0


@pytest.mark.parametrize("content", ["not json", "[1, 2]", {"movie": ["1"]}, {"movie": {"1": "oscar"}}])
def test_a_list_that_cannot_be_read_is_no_awards(table, content):
    table(content)
    assert awards_of("movie", "1") == []


def test_a_missing_list_is_no_awards(monkeypatch, tmp_path):
    monkeypatch.setattr(awards, "_FILE", str(tmp_path / "gone.json"))
    awards._table.cache_clear()
    try:
        assert awards_of("movie", "157336") == []
    finally:
        awards._table.cache_clear()
