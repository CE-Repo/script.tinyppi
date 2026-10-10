# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Value formatting for the Dolby Vision metadata view (info/dvformat.py)."""

import pytest

from info import dvformat
from info.dvformat import EMPTY


@pytest.mark.parametrize(("value", "text"), [
    ("  P3 D65 ", "P3 D65"), (" ", EMPTY), (None, EMPTY), (0, "0"),
])
def test_text_is_stripped_or_empty(value, text):
    assert dvformat.text(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (4, "4"), (4.0, "4"), (4.25, "4.25"), (True, EMPTY), ("4", EMPTY), (None, EMPTY),
])
def test_numbers_drop_a_redundant_fraction(value, text):
    assert dvformat.num(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (1000.4, "1000"), (0.0050, "0.005"), (-0.25, "-0.25"), (0, "0"),
    (False, EMPTY), (None, EMPTY), (float("inf"), EMPTY), (float("nan"), EMPTY),
])
def test_luminances_keep_decimals_only_below_one_nit(value, text):
    assert dvformat.lum(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (0.25, "0.2500"), (-1, "-1.0000"), (True, EMPTY), ("0.5", EMPTY),
])
def test_scaled_values_have_four_decimals(value, text):
    assert dvformat.scaled(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (12.345, "12.3 %"), (0, "0.0 %"), (True, EMPTY), (None, EMPTY), ("5", EMPTY),
])
def test_percentages_have_one_decimal(value, text):
    assert dvformat.percent(value) == text


def test_flags_read_as_kodis_yes_and_no():
    assert dvformat.flag(True) == "#107"
    assert dvformat.flag(0) == "#106"
    assert dvformat.flag(None) == EMPTY


@pytest.mark.parametrize(("pair", "text"), [
    ((0.708, 0.292), "0.7080 | 0.2920"),
    ([34000, 16000], "34000 | 16000"),
    ((1, 0.5), "1.0000 | 0.5000"),
    ((None, 16000), "16000"),
    ((0.68, None), "0.6800"),                   # a missing half is dropped for floats too
    ((None, 0.32), "0.3200"),
    ((None, None), EMPTY),
    ((1, 2, 3), EMPTY),
    ("12", EMPTY),
    (None, EMPTY),
])
def test_coordinates_are_raw_codes_or_four_decimals(pair, text):
    assert dvformat.coords(pair) == text
