# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The composer's rows of the Dolby Vision metadata view (info/dvcomposer.py)."""

import pytest

from info import dvcomposer, dvformat
from info.dvformat import COLUMNS, EMPTY, HEADINGS, SPACE

# 2 ** 22: half of one unit with the usual denominator of 23.
HALF = 4194304


def rpu(curves=None, nlq=None, denom=23, **mapping):
    """Return an RPU whose composer data holds *curves*, *nlq* and *mapping*."""
    data = dict(mapping)
    if curves is not None:
        data["curves"] = curves
    if nlq is not None:
        data["nlq"] = nlq
    return {"header": {"coefficient_log2_denom": denom}, "data_mapping": data}


@pytest.mark.parametrize(("int_part", "frac_part", "denom", "text"), [
    (1, HALF, 23, "1.5"),
    (-1, HALF, 23, "-0.5"),
    (0, 1, 0, "1"),
    # A missing fraction counts as zero.
    (2, None, 23, "2"),
    (2, True, 23, "2"),
    # Without the integer half or a usable denominator there is no value.
    (None, HALF, 23, EMPTY),
    (True, HALF, 23, EMPTY),
    (1, HALF, None, EMPTY),
    (1, HALF, True, EMPTY),
    (1, HALF, "23", EMPTY),
    (1, HALF, -1, EMPTY),
])
def test_a_coefficient_joins_its_halves_like_the_decoder(int_part, frac_part, denom, text):
    assert dvcomposer._coefficient(int_part, frac_part, denom) == text


def test_the_composer_scalars():
    pairs = dict(dvcomposer.composer_pairs(rpu(
        vdr_rpu_id=0, mapping_color_space=0, mapping_chroma_format_idc=0,
        num_x_partitions=1, num_y_partitions=1, nlq_method_idc=0, nlq_num_pivots=2,
        nlq_pred_pivot_value=[0, 1023])))
    assert pairs["VDR RPU ID"] == "0"
    assert pairs["Partitions (x | y)"] == "1 | 1"
    assert pairs["NLQ pivot values"] == "0 | 1023"
    assert set(dict(dvcomposer.composer_pairs(None)).values()) == {EMPTY}


def test_without_composer_data_there_are_no_curves_or_nlq():
    for missing in (None, {}, {"data_mapping": None}, rpu(curves=[])):
        assert dvcomposer.curve_entries(missing, 0) == []
        assert dvcomposer.nlq_entries(missing) == []
    # Only the Y curve is present: Cb and Cr have nothing to show.
    single = rpu(curves=[{"mapping_idc": 0}])
    assert dvcomposer.curve_entries(single, 1) == []
    assert dvcomposer.curve_entries(rpu(curves=[{}]), 0) == []


def test_a_curve_without_coefficients_shows_only_its_shape():
    entries = dvcomposer.curve_entries(
        rpu(curves=[None, {"mapping_idc": 7, "num_pivots": 2, "pivots": [0, 1023]}]), 1)
    assert entries == [
        ("Shape", "7"),
        ("Pivots", "2"),
        ("Pivot codewords", "0 | 1023"),
    ]


def test_a_wide_polynomial_continues_in_a_second_table():
    curve = {"mapping_idc": 0, "polynomial": {
        "poly_order": [4, 1, 1],
        "linear_interp_flag": [True],
        "poly_coef_int": [[0, 1, 2, 3, 4], [1]],
        "poly_coef": [[0, HALF, 0, 0, HALF]],
    }}
    entries = dvcomposer.curve_entries(rpu(curves=[curve]), 0)
    assert entries[0] == ("Shape", "Polynomial")
    table = entries[entries.index((SPACE, "space.curve.0", "")) + 1:]
    assert table == [
        (HEADINGS, "Segment", ["Order", "Linear interp", "c0", "c1", "c2", "c3"]),
        (COLUMNS, "Segment 1", ["4", dvformat.flag(True), "0", "1.5", "2", "3"]),
        # Fractions missing for this segment: the integer halves stand alone.
        (COLUMNS, "Segment 2", ["1", "", "1", "", "", ""]),
        (COLUMNS, "Segment 3", ["1", "", "", "", "", ""]),
        (SPACE, "space.Segment.6", ""),
        # Only the first segment has a fifth coefficient.
        (HEADINGS, "Segment", ["c4"]),
        (COLUMNS, "Segment 1", ["4.5"]),
    ]


def test_an_mmr_curve_lists_segments_then_coefficients_by_order():
    curve = {"mapping_idc": 1, "mmr": {
        "mmr_order": [2],
        "mmr_constant_int": [0],
        "mmr_constant": [HALF],
        "mmr_coef_int": [[[1, 2, 3], [4, 5]]],
        "mmr_coef": [[[0, HALF]]],
    }}
    entries = dvcomposer.curve_entries(rpu(curves=[curve]), 0)
    assert entries[0] == ("Shape", "MMR")
    table = entries[entries.index((SPACE, "space.curve.0", "")) + 1:]
    assert table == [
        (HEADINGS, "Segment", ["Order", "Constant"]),
        (COLUMNS, "Segment 1", ["2", "0.5"]),
        (SPACE, "space.mmr", ""),
        (HEADINGS, "Term", ["1", "2", "3"]),
        (COLUMNS, "Order 1", ["1", "2.5", "3"]),
        # Short rows are padded to the heading width.
        (COLUMNS, "Order 2", ["4", "5", ""]),
    ]


def test_mmr_coefficients_name_the_segment_when_there_are_several():
    mmr = {
        "mmr_order": [1, 1],
        "mmr_constant_int": [0],
        "mmr_coef_int": [[[1]], [[2]]],
    }
    entries = dvcomposer._mmr_entries(mmr, 23)
    assert (COLUMNS, "Segment 2", ["1", ""]) in entries
    assert [row[1] for row in entries if row[0] == COLUMNS][-2:] == [
        "Segment 1 · order 1", "Segment 2 · order 1"]


def test_mmr_tables_stand_alone_without_a_space():
    # Coefficients only: the segment table is empty, so no space before them.
    coefficients = dvcomposer._mmr_entries({"mmr_coef_int": [[[1, 2]]]}, 23)
    assert coefficients == [
        (HEADINGS, "Term", ["1", "2"]),
        (COLUMNS, "Order 1", ["1", "2"]),
    ]
    # Segments only: no coefficient table to separate.
    segments = dvcomposer._mmr_entries({"mmr_order": [2]}, 23)
    assert segments == [
        (HEADINGS, "Segment", ["Order", "Constant"]),
        (COLUMNS, "Segment 1", ["2", ""]),
    ]
    assert dvcomposer._mmr_entries(None, 23) == []


def test_the_nlq_table_has_one_column_per_component():
    nlq = {
        "nlq_offset": [0, 512, 512],
        "vdr_in_max_int": [1, 1, 1],
        "vdr_in_max": [0, HALF],
        "linear_deadzone_slope_int": [],
        "linear_deadzone_threshold_int": [0],
        "linear_deadzone_threshold": [HALF],
    }
    assert dvcomposer.nlq_entries(rpu(nlq=nlq)) == [
        (HEADINGS, "Component", ["Y", "Cb", "Cr"]),
        (COLUMNS, "Offset", ["0", "512", "512"]),
        (COLUMNS, "VDR in max", ["1", "1.5", "1"]),
        # The empty deadzone slope row is dropped.
        (COLUMNS, "Deadzone threshold", ["0.5", "", ""]),
    ]


def test_nlq_coefficients_need_the_headers_denominator():
    nlq = {"vdr_in_max_int": [1, 1, 1]}
    assert dvcomposer.nlq_entries(rpu(nlq=nlq, denom=None)) == []
