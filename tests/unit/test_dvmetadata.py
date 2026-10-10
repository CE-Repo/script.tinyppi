# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The Dolby Vision metadata view's rows (info/dvmetadata.py, dvcomposer.py)."""

from info import dvformat, dvmetadata

TRIM = {"nits": 100, "slope": 2048, "offset": 2048, "power": 2048, "chromaweight": 2048,
        "saturation": 2048, "tonedetail": 2048,
        "ui": {"gain": 0.0, "lift": 0.25}}

FRAME = {
    "flags": [],
    "config": {"profile": 8, "compat_id": 1},
    "rpu": {
        "header": {"coefficient_log2_denom": 23},
        "l1": {"min_pq": 0, "max_pq": 3079, "avg_pq": 1650,
               "min_nits": 0.0001, "max_nits": 1000.4, "avg_nits": 92.0},
        "l2": [TRIM, dict(TRIM, nits=4000)],
        "l5": {"left": 0, "right": 0, "top": 276, "bottom": 276},
        "data_mapping": {
            "vdr_rpu_id": 0, "num_x_partitions": 1, "num_y_partitions": 1,
            "curves": [{"mapping_idc": 0, "num_pivots": 2, "pivots": [0, 1023],
                        "polynomial": {"poly_order": [1], "linear_interp_flag": [False],
                                       "poly_coef_int": [[0, 1]],
                                       "poly_coef": [[0, 4194304]]}}],
        },
    },
}


def sections(rows):
    return [name for kind, name, _value in rows if kind == dvmetadata.SECTION]


def value(rows, name):
    return next(row[2] for row in rows if row[0] != dvmetadata.SECTION and row[1] == name)


def test_scene_rows():
    rows, parsed, origin, carried = dvmetadata.build_scene_rows(FRAME)
    assert sections(rows) == ["L1 — Frame luminance", "L2 — Trims", "L5 — Active area"]
    assert value(rows, "Max (PQ | nits)") == "3079 | 1000"
    assert origin == {} and carried == "config, rpu"
    # Only the listed target displays get a row; raw codes and the UI scale apart.
    trims = [row for row in rows if row[0] == dvmetadata.COLUMNS]
    assert [row[1] for row in trims] == ["100 nits", "100 nits"]
    assert trims[1][2][:2] == ["0.0000", "0.2500"]


def test_static_rows_with_the_composer():
    rows, parsed, origin, carried = dvmetadata.build_scene_rows(FRAME)
    static = dvmetadata.build_static_rows(parsed, origin, carried)
    assert "Composer — Data mapping" in sections(static)
    assert "Composer — Y curve" in sections(static)
    assert value(static, "Shape") == "Polynomial"
    assert value(static, "Pivot codewords") == "0 | 1023"
    segment = next(row for row in static if row[1] == "Segment 1")
    # c1 = 1 + 4194304 / 2**23 = 1.5
    assert segment[2][:2] == ["1", dvformat.flag(False)]
    assert segment[2][3].startswith("1.5")


def test_an_empty_frame_has_no_sections():
    rows, *_rest = dvmetadata.build_scene_rows({})
    assert rows == []


def test_values_are_formatted_or_dropped():
    assert dvformat.num(4.0) == "4" and dvformat.num(None) == dvformat.EMPTY
    assert dvformat.lum(0.0050) == "0.005"
    assert dvformat.joined("1", dvformat.EMPTY, "3") == "1 | 3"
    assert dvformat.joined(dvformat.EMPTY) == dvformat.EMPTY
    assert dvformat.coords((0.708, 0.292)) == "0.7080 | 0.2920"
    assert dvformat.text("  ") == dvformat.EMPTY
