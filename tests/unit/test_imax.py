# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""IMAX identification by name (info/imax.py), against the bundled list."""

import os

import pytest

import xbmc
from info import imax


@pytest.fixture(autouse=True)
def bundled_list_only(monkeypatch, tmp_path):
    """Read the bundled list, never a user's copy, and forget past verdicts."""
    bundled = os.path.join(os.path.dirname(imax.__file__), "..", "..", "data",
                           imax._TITLE_FILE)
    monkeypatch.setattr(imax, "_title_files",
                        lambda: (os.path.normpath(bundled), str(tmp_path / "none.txt")))
    monkeypatch.setattr(imax, "_titles", imax._TitleIndex())
    monkeypatch.setattr(imax, "_verdict", imax._Verdict())


@pytest.mark.parametrize("name", [
    "The.Dark.Knight.2008.2160p.UHD.BluRay.x265",
    "Dark Knight, The (2008)",
    "The Wandering Earth 2 2023 1080p",
    "Drachenzaehmen.leicht.gemacht.2025.German.DL.2160p",
    "Drachenzähmen leicht gemacht (2025)",
    "Joker: Folie à Deux 2024",
    "Aquaman 2018 2160p",
    "Some Film 2021 IMAX 2160p",
])
def test_listed_or_tagged_films_are_imax(name):
    assert imax.is_known_imax_title(name)


@pytest.mark.parametrize("name", [
    # A sequel is not its first part: the entry must end the name.
    "Some.Unlisted.Film.2019.2160p",
    # A listed year must match: the 1984 film is not the 2016 remake.
    "Ghostbusters 1984 2160p",
    # The title must end the film part, not merely appear in it.
    "The Dark Knight Behind The Scenes 2008",
])
def test_other_films_are_not(name):
    assert not imax.is_known_imax_title(name)


def test_the_remake_with_its_year_is():
    assert imax.is_known_imax_title("Ghostbusters.2016.1080p")


def test_enhanced_from_the_tag_or_the_list():
    assert imax.is_enhanced_title("Film 2022 IMAX Enhanced 2160p")
    assert imax.is_enhanced_title("Eternals 2021 2160p")
    assert not imax.is_enhanced_title("The Dark Knight 2008")
    assert not imax.is_enhanced_title("Film 2022 IMAX 2160p")


def test_reading_a_list(tmp_path):
    listing = tmp_path / "titles.txt"
    listing.write_text(
        "# comment\n"
        "\n"
        "Film One            # first\n"
        "Film Two 2001 @enhanced\n"
        "Wonder Woman 1984\n",
        encoding="utf-8",
    )
    entries = imax._read_titles(str(listing))
    assert entries["film 1"] == [(None, False)]
    assert entries["film 2"] == [(2001, True)]
    # A trailing year is a condition, even where it reads as part of a title.
    assert entries["wonder woman"] == [(1984, False)]


def test_a_missing_list_is_empty(tmp_path):
    assert imax._read_titles(str(tmp_path / "missing.txt")) == {}


@pytest.mark.parametrize(("path", "names"), [
    ("/films/The Dark Knight (2008)/The.Dark.Knight.2008.mkv",
     ["The.Dark.Knight.2008", "The Dark Knight (2008)"]),
    ("/films/Dunkirk (2017)/BDMV/STREAM/00800.m2ts",
     ["00800", "Dunkirk (2017)"]),
    ("smb://nas/films/Dunkirk/disc.iso/BDMV/PLAYLIST/00800.mpls",
     ["00800", "disc", "Dunkirk"]),
    ("", []),
])
def test_names_from_a_path(path, names):
    assert imax._path_names(path) == names


def test_kodi_titles_count_for_films_but_not_episodes():
    xbmc.INFO.update({"VideoPlayer.Title": "The Dark Knight", "VideoPlayer.Year": "2008"})
    assert "The Dark Knight 2008" in imax._playing_names("plugin://some.addon/play/123")
    xbmc.INFO["VideoPlayer.TVShowTitle"] = "Some Show"
    assert not any("Dark Knight" in name
                   for name in imax._playing_names("plugin://some.addon/play/123"))


def test_nothing_playing_is_not_imax():
    assert imax.playing_path() == ""
    assert not imax.is_known_imax_title()
