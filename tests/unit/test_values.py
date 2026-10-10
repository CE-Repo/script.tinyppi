# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Text and id helpers shared by the dashboard (web/values.py)."""

import pytest

from info.dvinfo import na_label
from web.values import clean_value, library_id, numbers


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
    ("1000 / 0.005 nits", [1000.0, 0.005]),
    ("-3 dB, 12", [-3.0, 12.0]),
    ("no digits", []),
    ("", []),
])
def test_numbers_are_read_from_composite_readings(value, expected):
    assert numbers(value) == expected


def test_the_not_available_label_has_no_numbers():
    assert numbers(na_label()) == []
