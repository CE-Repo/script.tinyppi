# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Text and id helpers shared by the dashboard (web/values.py)."""

import pytest

from info.dvinfo import na_label
from web.values import clean_value, library_id, name_list, numbers, plain_text


@pytest.mark.parametrize(("value", "expected"), [
    (7, 7), ("12", 12), (3.0, 3), ("0", 0), (-4, 0), (0, 0),
    (True, 0), (False, 0), (2.5, 0), ("2.5", 0), ("x", 0), (None, 0), ([1], 0), ({}, 0),
])
def test_library_ids_are_positive_integers_or_zero(value, expected):
    assert library_id(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("", ""),
    (None, None),
    ("[COLOR FFFF0000]FEL[/COLOR]", "FEL"),
    ("[B]Bold[/B] [i]and[/I] [CR]", "Bold and"),
    ("HDR10 l 1000 nits l BT2020", "HDR10 | 1000 nits | BT2020"),
    ("[unknown]kept", "[unknown]kept"),
    ("  padded  ", "padded"),
])
def test_markup_is_stripped_and_separators_become_pipes(value, expected):
    assert clean_value(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("", ""),
    ("[I]Long live the fighters.[/I]", "Long live the fighters."),
    ("First line.[CR]Second line.[cr]", "First line.\nSecond line."),
    ("Paul l Chani l Jessica", "Paul l Chani l Jessica"),
    ("  padded  ", "padded"),
])
def test_library_texts_lose_markup_and_keep_their_line_breaks(value, expected):
    assert plain_text(value) == expected


@pytest.mark.parametrize(("value", "limit", "expected"), [
    ("", 4, ([], False)),
    ("Legendary Pictures / Warner Bros.", 4, (["Legendary Pictures", "Warner Bros."], False)),
    # The cast one name a line, in billing order, cut to its leads -- and
    # said to have more.
    ("Timothée Chalamet\nZendaya\nRebecca Ferguson", 2, (["Timothée Chalamet", "Zendaya"], True)),
    ("Timothée Chalamet\nZendaya", 2, (["Timothée Chalamet", "Zendaya"], False)),
    # Markup stripped, blanks and repeats dropped: a repeat is no more.
    ("[B]Legendary[/B] /  / Warner Bros. / Legendary", 2, (["Legendary", "Warner Bros."], False)),
    # A slash within a name is no separator, and nor is another one Kodi
    # was told to use instead.
    ("AC/DC, Queen", 4, (["AC/DC, Queen"], False)),
    ("x" * 90, 4, (["x" * 80], False)),
])
def test_list_labels_are_split_into_names(value, limit, expected):
    assert name_list(value, limit) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("1000 / 0.005 nits", [1000.0, 0.005]),
    ("-3 dB, 12", [-3.0, 12.0]),
    ("no digits", []),
    ("", []),
])
def test_numbers_are_read_from_composite_readings(value, expected):
    assert numbers(value) == expected


def test_the_not_available_label_has_no_numbers():
    assert numbers(na_label()) == []
