# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The Dolby Vision metadata view's rows (info/dvmetadata.py, dvcomposer.py)."""

import pytest

import xbmc
import xbmcaddon
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


@pytest.fixture
def module_version():
    """Forget the cached parser version before and after the test."""
    dvmetadata._module_version.cache_clear()
    yield
    dvmetadata._module_version.cache_clear()


def test_the_stream_section_names_the_parser_version(module_version):
    xbmc.INFO["VideoPlayer.HdrType"] = "dolbyvision"
    rows = dvmetadata.build_static_rows({"flags": ["converted"]}, {}, "rpu")
    assert value(rows, "HDR type (Kodi)") == "dolbyvision"
    assert value(rows, "Flags") == "converted"
    assert value(rows, "Side data") == "rpu"
    assert value(rows, "Parser module") == xbmcaddon.VERSION


def test_a_missing_parser_module_has_no_version(monkeypatch, module_version):
    class Missing:
        def __init__(self, addon_id):
            raise RuntimeError(f"unknown addon id {addon_id!r}")
    monkeypatch.setattr(xbmcaddon, "Addon", Missing)
    rows = dvmetadata.build_static_rows({"flags": ["converted"]}, {}, dvmetadata.EMPTY)
    assert not any(row[1] == "Parser module" for row in rows)


def test_a_section_drops_blank_rows_at_its_edges():
    rows = [(dvmetadata.SECTION, "Earlier", "")]
    dvmetadata._section(rows, "Title", [
        (dvmetadata.SPACE, "space.top", ""),
        ("Kept", "1"),
        ("Dropped", dvmetadata.EMPTY),
        (dvmetadata.SPACE, "space.middle", ""),
        ("Also kept", "2"),
        (dvmetadata.SPACE, "space.bottom", ""),
    ], dvmetadata.CACHED)
    assert rows[1:] == [
        (dvmetadata.SPACE, "space.Title", ""),
        (dvmetadata.SECTION, "Title", dvmetadata.CACHED),
        (dvmetadata.ROW, "Kept", "1"),
        (dvmetadata.SPACE, "space.middle", ""),
        (dvmetadata.ROW, "Also kept", "2"),
    ]
    dvmetadata._section(rows, "Blank", [(dvmetadata.SPACE, "space.only", "")])
    assert sections(rows) == ["Earlier", "Title"]


def test_colorimetry_matrices_need_all_nine_coefficients():
    rpu = {"colorimetry": {
        "ycc_to_rgb_coef": [9575, 0, 14742, 9575, -1754, -4383, 9575, 17372, 0],
        "rgb_to_lms_coef": [1, 2, 3],
        "ycc_to_rgb_offset": [16777216, 134217728, 134217728],
        "signal_eotf": 65535, "signal_eotf_param0": 0, "signal_eotf_param1": 0,
        "signal_eotf_param2": 0, "signal_bit_depth": 12,
    }}
    rows = dvmetadata.build_static_rows({"rpu": rpu}, {}, "rpu")
    start = rows.index((dvmetadata.SECTION, "Colorimetry (VDR DM)", ""))
    assert rows[start + 1] == (dvmetadata.HEADINGS, "Matrix (raw)",
                               [str(index) for index in range(1, 10)])
    assert rows[start + 2] == (dvmetadata.COLUMNS, "YCC to RGB",
                               ["9575", "0", "14742", "9575", "-1754", "-4383",
                                "9575", "17372", "0"])
    assert rows[start + 3] == (dvmetadata.SPACE, "space.colorimetry", "")
    assert value(rows, "YCC to RGB offset") == "16777216 | 134217728 | 134217728"
    assert value(rows, "EOTF parameters") == "0 | 0 | 0"
    assert not any(row[1] == "RGB to LMS" for row in rows)


def test_colorimetry_without_matrix_values_shows_only_the_signal():
    rpu = {"colorimetry": {"ycc_to_rgb_coef": [None] * 9, "signal_bit_depth": 12}}
    rows = dvmetadata.build_static_rows({"rpu": rpu}, {}, "rpu")
    start = rows.index((dvmetadata.SECTION, "Colorimetry (VDR DM)", ""))
    assert rows[start + 1] == (dvmetadata.ROW, "Signal bit depth", "12")
    assert not any(row[0] == dvmetadata.HEADINGS and row[1] == "Matrix (raw)"
                   for row in rows)


L8_FULL = dict(TRIM, nits=1000, mid_contrast=2048, clip_trim=2048, length=25,
               saturation_vector=[1, 2, 3, 4, 5, 6], hue_vector="not a vector")


def test_l8_trims_continue_past_six_controls_and_add_vector_tables():
    passes = [
        L8_FULL,
        {"nits": 600, "slope": 1800},          # sets nothing beyond the first six
        {"nits": "100", "slope": 1},            # unreadable target: not shown
        {"nits": 4000, "slope": 1},             # not one of the listed targets
    ]
    rows, *_rest = dvmetadata.build_scene_rows({"rpu": {"l8": passes}})
    start = rows.index((dvmetadata.SECTION, "L8 — Trims", ""))
    body = rows[start + 1:]
    assert body[:4] == [
        (dvmetadata.HEADINGS, "Legend (raw)",
         ["Slope", "Offset", "Power", "Chroma", "Saturation", "Detail"]),
        (dvmetadata.COLUMNS, "1000 nits", ["2048"] * 6),
        (dvmetadata.COLUMNS, "600 nits", ["1800", "", "", "", "", ""]),
        (dvmetadata.SPACE, "space.Legend (raw).6", ""),
    ]
    # Only the full pass sets mid contrast and clip trim.
    assert body[4:6] == [
        (dvmetadata.HEADINGS, "Legend (raw)", ["Mid contrast", "Clip trim"]),
        (dvmetadata.COLUMNS, "1000 nits", ["2048", "2048"]),
    ]
    names = [row[1] for row in body if row[0] == dvmetadata.HEADINGS]
    assert names == ["Legend (raw)", "Legend (raw)", "Legend (UI)", "Legend (sat)",
                     "Legend (block)"]
    sat = body.index((dvmetadata.HEADINGS, "Legend (sat)",
                      [f"Field {index}" for index in range(1, 7)]))
    assert body[sat + 1] == (dvmetadata.COLUMNS, "1000 nits", ["1", "2", "3", "4", "5", "6"])
    assert body[-1] == (dvmetadata.COLUMNS, "1000 nits", ["25"])
    assert not any("4000" in str(row[1]) or row[1] == "100 nits" for row in body)


def test_title_level_blocks():
    parsed = {
        "rpu": {
            "l9": {"index": 1, "name": "DCI-P3 D65", "length": 17,
                   "coords": {"red": (0.68, 0.32), "white": (0.3127, 0.329)}},
            "l10": [
                {"nits": 1000, "target_display_index": 3, "primary_name": "BT.2020",
                 "target_max_pq": 3079, "target_min_pq": 62, "length": 21},
                {"nits": 600, "target_min_pq": 0},
                {"nits": 100},
            ],
        },
        "mdcv": {"max_luminance": 1000, "min_luminance": 0.0001,
                 "primaries": {"name": "DCI-P3", "red": (34000, 16000)},
                 "white_point": (15635, 16450)},
        "cll": {"max_cll": 1000, "max_fall": 400},
    }
    rows = dvmetadata.build_static_rows(parsed, {}, "rpu, mdcv, cll")
    assert value(rows, "Red (x | y)") == "0.6800 | 0.3200"
    assert value(rows, "White (x | y)") == "0.3127 | 0.3290"
    assert value(rows, "Block length") == "17"
    assert value(rows, "1000 nits (#3)") == "BT.2020  max PQ 3079  min PQ 62  length 21"
    assert value(rows, "600 nits") == "min PQ 0"
    # A target display without readings gets no row.
    assert not any(row[1] == "100 nits" for row in rows)
    static = rows[rows.index((dvmetadata.SECTION, "Static metadata (MDCV / CLL)", "")):]
    assert value(static, "Primaries") == "DCI-P3"
    assert value(static, "Red (x | y)") == "34000 | 16000"
    assert value(static, "White point (x | y)") == "15635 | 16450"
    assert value(static, "Min luminance") == "0.0001"


def test_hdr10plus_profile_b_with_its_distribution():
    hdr10plus = {
        "profile": "B", "application_version": 1, "num_windows": 1,
        "targeted_system_display_maximum_luminance": 400,
        "maxscl": [1000.2, 900, 0.5], "average_maxrgb": 120.0,
        "fraction_bright_pixels": 1.75,
        "knee_point_x": 0.25, "knee_point_y": 0.5, "bezier_anchors": [102, 205],
        "distribution": [{"percentage": 1, "nits": 0.1}, {"percentage": 99, "nits": 950}],
    }
    rows, _parsed, _origin, carried = dvmetadata.build_scene_rows({"hdr10plus": hdr10plus})
    assert carried == "hdr10plus"
    assert sections(rows) == ["HDR10+ (ST 2094-40)"]
    assert value(rows, "MaxSCL (R | G | B)") == "1000 | 900 | 0.5"
    assert value(rows, "Bright pixels") == "1.8 %"
    assert value(rows, "Knee point (x | y)") == "0.2500 | 0.5000"
    assert value(rows, "Bézier anchors") == "102 205"
    assert rows[-2] == (dvmetadata.HEADINGS, "Distribution",
                        ["1%", "5%", "10%", "25%", "50%", "75%", "90%", "95%", "99%"])
    assert rows[-1] == (dvmetadata.COLUMNS, "maxRGB (nits)",
                        ["0.1", "", "", "", "", "", "", "", "950"])


def test_hdr10plus_profile_a_has_no_knee_point_or_distribution():
    rows, *_rest = dvmetadata.build_scene_rows({"hdr10plus": {"profile": "A", "num_windows": 1}})
    assert value(rows, "Profile") == "A"
    assert not any(row[1] in ("Knee point (x | y)", "Distribution") for row in rows)
    assert rows[-1] == (dvmetadata.ROW, "Windows", "1")


@pytest.fixture
def live(monkeypatch):
    """Feed build_scene_rows live frames, holding blocks from a fresh start."""
    frames = []
    monkeypatch.setattr(dvmetadata, "_held", dvmetadata._HeldBlocks())

    def side_data(mapping=False):
        assert mapping is True
        return frames.pop(0)
    monkeypatch.setattr(dvmetadata, "get_sidedata", side_data)
    xbmc.INFO["Player.FilenameAndPath"] = "/films/one.mkv"
    return frames


def test_live_frames_hold_blocks_they_omit(live):
    l1 = {"min_pq": 0, "max_pq": 3079, "avg_pq": 1650}
    live.extend([
        {"config": {"profile": 8}, "rpu": {"l1": l1, "l2": [TRIM]},
         "hdr10plus": {"profile": "A"}},
        {"rpu": {"l1": dict(l1, max_pq=2000)}},
    ])
    rows, _parsed, origin, carried = dvmetadata.build_scene_rows()
    assert carried == "config, rpu, hdr10plus"
    assert (dvmetadata.SECTION, "L2 — Trims", "") in rows
    assert (dvmetadata.SECTION, "HDR10+ (ST 2094-40)", "") in rows
    assert origin["rpu.l2"] == dvmetadata.LIVE

    rows, parsed, origin, carried = dvmetadata.build_scene_rows()
    assert carried == "rpu"
    # L1 is this frame's own; L2, the record and HDR10+ are held.
    assert (dvmetadata.SECTION, "L1 — Frame luminance", "") in rows
    assert value(rows, "Max (PQ | nits)") == "2000"
    assert (dvmetadata.SECTION, "L2 — Trims", dvmetadata.CACHED) in rows
    assert (dvmetadata.SECTION, "HDR10+ (ST 2094-40)", dvmetadata.CACHED) in rows
    assert parsed["config"] == {"profile": 8}
    assert origin["config"] == dvmetadata.CACHED


def test_a_frame_without_an_rpu_shows_every_held_block_as_cached(live):
    live.extend([{"rpu": {"l1": {"max_pq": 3079}, "l5": {"top": 276}}}, {"flags": []}])
    dvmetadata.build_scene_rows()
    rows, _parsed, origin, carried = dvmetadata.build_scene_rows()
    assert carried == dvmetadata.EMPTY
    assert origin["rpu"] == origin["rpu.l1"] == origin["rpu.l5"] == dvmetadata.CACHED
    assert sections(rows) == ["L1 — Frame luminance", "L5 — Active area"]
    assert all(row[2] == dvmetadata.CACHED for row in rows if row[0] == dvmetadata.SECTION)


def test_a_new_item_forgets_the_held_blocks(live):
    live.extend([{"rpu": {"l1": {"max_pq": 3079}}}, {"flags": []}])
    dvmetadata.build_scene_rows()
    xbmc.INFO["Player.FilenameAndPath"] = "/films/two.mkv"
    rows, parsed, origin, _carried = dvmetadata.build_scene_rows()
    assert rows == [] and origin == {} and parsed.get("rpu") is None


def test_a_live_read_that_did_not_parse_shows_nothing(live):
    live.append(None)
    rows, parsed, origin, carried = dvmetadata.build_scene_rows()
    assert (rows, parsed, origin, carried) == ([], {}, {}, dvmetadata.EMPTY)


def test_scene_and_static_rows_are_joined_with_one_space():
    scene = [(dvmetadata.SECTION, "L1 — Frame luminance", "")]
    static = [(dvmetadata.SECTION, "Source master", "")]
    assert dvmetadata.join_rows(scene, static) == [
        scene[0], (dvmetadata.SPACE, "space.Source master", ""), static[0]]
    assert dvmetadata.join_rows([], static) == static
    assert dvmetadata.join_rows(scene, []) == scene


def test_the_static_signature_follows_title_blocks_not_frame_scalars():
    _rows, parsed, origin, carried = dvmetadata.build_scene_rows(FRAME)
    signature = dvmetadata.static_signature(parsed, origin, carried)
    # Per-frame readings and RPU scalars leave the static rows alone.
    frame = dict(parsed, rpu=dict(parsed["rpu"], l1={"max_pq": 1}, scene_refresh_flag=1))
    assert dvmetadata.static_signature(frame, origin, carried) == signature
    # A new composer block, a held heading or another payload rebuilds them.
    remapped = dict(parsed, rpu=dict(parsed["rpu"], data_mapping={"vdr_rpu_id": 1}))
    assert dvmetadata.static_signature(remapped, origin, carried) != signature
    assert dvmetadata.static_signature(
        parsed, {"rpu.data_mapping": dvmetadata.CACHED}, carried) != signature
    assert dvmetadata.static_signature(parsed, origin, "rpu") != signature
    assert dvmetadata.static_signature({}, {}, dvmetadata.EMPTY) == \
        dvmetadata.static_signature({"rpu": None}, {}, dvmetadata.EMPTY)
