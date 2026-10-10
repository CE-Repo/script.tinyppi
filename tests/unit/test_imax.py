# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""IMAX identification by name (info/imax.py), against the bundled list."""

import os

import pytest

import xbmc
import xbmcvfs
from info import imax

# Kept before the autouse fixture below replaces it.
TITLE_FILES = imax._title_files


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
    # Nothing above the file but disc-layout folders, or no folder at all.
    ("/BDMV/STREAM/00800.m2ts", ["00800"]),
    ("Dunkirk.2017.mkv", ["Dunkirk.2017"]),
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


def test_a_bare_title_without_tags_is_matched_whole():
    assert imax.is_known_imax_title("Dunkirk")
    assert not imax.is_known_imax_title("---")


def test_entries_without_a_title_are_skipped(tmp_path):
    listing = tmp_path / "titles.txt"
    listing.write_text("@enhanced\n--- # nothing but punctuation\nTenet\n", encoding="utf-8")
    assert imax._read_titles(str(listing)) == {"tenet": [(None, False)]}


def test_the_users_list_adds_titles_and_is_reread_when_edited(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled.txt"
    personal = tmp_path / "personal.txt"
    bundled.write_text("Tenet\n", encoding="utf-8")
    personal.write_text("Tenet 2020 @enhanced\n", encoding="utf-8")
    monkeypatch.setattr(imax, "_title_files", lambda: (str(bundled), str(personal)))
    assert imax._title_index() == {"tenet": ((None, False), (2020, True))}
    assert imax.is_enhanced_title("Tenet.2020.2160p")
    assert not imax.is_known_imax_title("My Own Film")

    personal.write_text("Tenet 2020 @enhanced\nMy Own Film\n", encoding="utf-8")
    assert imax.is_known_imax_title("My.Own.Film.2160p")
    counts = [line for _level, line in xbmc.LOG if "titles known" in line]
    assert counts[0].endswith("IMAX: 1 titles known, 1 of them IMAX Enhanced")
    assert counts[-1].endswith("IMAX: 2 titles known, 1 of them IMAX Enhanced")


def play(monkeypatch, path):
    class Player(xbmc.Player):
        def getPlayingFile(self):
            return path
    monkeypatch.setattr(xbmc, "Player", Player)


def test_the_playing_path_is_decoded_up_to_four_layers(monkeypatch):
    play(monkeypatch, "smb://nas/films/Dunkirk%25252525202017.mkv?token=1")
    # Four layers are undone; a fifth is left as Kodi encoded it.
    assert imax.playing_path() == "smb://nas/films/Dunkirk%202017.mkv"
    play(monkeypatch, "smb://nas/films/Dunkirk%2520(2017).mkv")
    assert imax.playing_path() == "smb://nas/films/Dunkirk (2017).mkv"


def test_the_playing_film_is_judged_by_its_names(monkeypatch):
    play(monkeypatch, "/films/Film.2022.IMAX.Enhanced.2160p.mkv")
    assert imax.is_known_imax_title()
    assert imax.is_enhanced_title()


def test_nothing_playing_is_not_enhanced():
    assert not imax.is_enhanced_title()


def test_a_verdict_is_kept_for_the_file(monkeypatch):
    play(monkeypatch, "plugin://some.addon/play/1")
    xbmc.INFO["VideoPlayer.Title"] = "Tenet"
    assert imax.is_known_imax_title()
    # Kodi changes the title while the file plays: a positive answer stands.
    xbmc.INFO["VideoPlayer.Title"] = "Something Else"
    assert imax.is_known_imax_title()
    play(monkeypatch, "plugin://some.addon/play/2")
    assert not imax.is_known_imax_title()


@pytest.mark.parametrize(("token", "logo"), [
    ("dolbyvision", "codecs/Dolby_Vision_IMAX.png"),
    ("hdr10+", "codecs/HDR10Plus_IMAX.png"),
    ("hdr10", "codecs/HDR10_IMAX.png"),
    # No combined logo exists for HLG or SDR.
    ("hlg", ""),
    ("", ""),
])
def test_combined_logos_for_installed_files(monkeypatch, token, logo):
    monkeypatch.setattr(imax, "_logo_installed", {})
    assert imax.imax_logo(token) == logo


def test_a_missing_combined_logo_falls_back_to_none(monkeypatch, tmp_path):
    monkeypatch.setattr(imax, "_logo_installed", {})
    monkeypatch.setattr(imax, "_MEDIA_PATH", str(tmp_path))
    assert imax.imax_logo("hdr10") == ""
    # Checked once: a file appearing later is not noticed.
    (tmp_path / "codecs").mkdir()
    (tmp_path / "codecs" / "HDR10_IMAX.png").write_bytes(b"png")
    assert imax.imax_logo("hdr10") == ""
    assert imax._logo_installed == {"codecs/HDR10_IMAX.png": False}


def test_the_lists_are_the_bundled_one_and_the_users_copy():
    bundled, personal = TITLE_FILES()
    assert os.path.isfile(bundled)
    assert bundled.endswith(os.path.join("resources", "data", imax._TITLE_FILE))
    assert personal == os.path.join(
        xbmcvfs.translatePath("special://profile/addon_data/script.tinyppi/"), imax._TITLE_FILE)
