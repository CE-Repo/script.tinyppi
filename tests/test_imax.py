# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

import pytest

from info import imax


@pytest.fixture(autouse=True)
def fresh_index(monkeypatch):
    monkeypatch.setattr(imax, "_titles", None)
    monkeypatch.setattr(imax, "_titles_stamp", None)
    monkeypatch.setattr(imax, "_cache", None)


@pytest.mark.parametrize("name, expected", [
    ("The.Dark.Knight.2008.2160p.UHD.BluRay.x265", (True, False)),
    ("Dark Knight, The (2008)", (True, False)),
    ("Eternals.2021.2160p.DSNP.WEB-DL", (True, True)),
    ("Ghostbusters.2016.2160p", (True, False)),
    ("Ghostbusters.1984.2160p", (False, False)),     # the entry is the remake
    ("Some.Unlisted.Film.2020.2160p", (False, False)),
    ("Random.Film.IMAX.Enhanced.2160p", (True, True)),
])
def test_classify(name, expected):
    assert imax._classify((name,)) == expected


def test_a_sequel_is_matched_by_its_own_entry_only():
    # "Aquaman" is listed, and so is the sequel; the sequel's name must not be
    # read as the first film plus words.
    assert imax._tokens("Aquaman.and.the.Lost.Kingdom") == [
        "aquaman", "and", "the", "lost", "kingdom"]
    assert imax._classify(("Aquaman.and.the.Lost.Kingdom.2023.2160p",)) == (
        True, False)


def test_umlauts_and_numerals_are_normalised():
    assert imax._tokens("Drachenzähmen leicht gemacht II") == \
        imax._tokens("Drachenzaehmen.Leicht.Gemacht.2")
