# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dolby Vision and HDR fields from parsed side data (info/dvinfo.py).

The parse itself is script.module.sidedata's; these tests feed its result
shape directly.
"""

import pytest

import xbmcgui
from info import dvinfo


def parsed(**blocks):
    """Return a parse result with *blocks* filled in."""
    result = dvinfo._empty_sidedata()
    result.update(blocks)
    return result


# A profile 7 FEL frame with every block the overlay reads.
P7_FEL = parsed(
    structure="DT",
    config={"profile": 7, "compat_id": 6, "version_major": 1, "version_minor": 0,
            "rpu_present": True, "bl_present": True, "el_present": True},
    rpu={"header": {"el_type": "fel"}, "cm_version": "4.0",
         "l1": {"min_nits": 0.0001, "max_nits": 1000.4, "avg_nits": 92.0,
                "min_pq": 0, "max_pq": 3079, "avg_pq": 1650.0},
         "l5": {"left": 0, "right": 0, "top": 276, "bottom": 276},
         "l6": {"max_lum_nits": 1000, "min_lum_nits": 0.005, "max_cll": 1000, "max_fall": 400},
         "source": {"max_nits": 4000.0, "min_nits": 0.005}},
    mdcv={"max_luminance": 1000, "min_luminance": 0.0050},
    cll={"max_cll": 1000, "max_fall": 400},
)


def test_a_profile_7_fel_frame():
    info = dvinfo._build_info(P7_FEL, "dolbyvision", "")
    assert info["hdr_format"] == "dolbyvision"
    assert info["output_mode"] == "Dolby Vision Profile 7.6 FEL"
    assert info["dv_profile"] == "7.6"
    assert info["dv_el_type"] == "FEL"
    assert info["structure"] == "DT-DL"
    assert info["dv_version"] == "1.0"
    assert info["cm_version"] == "CMv4.0"
    assert info["bit_depth"] == "12"
    assert (info["dv_rpu_present"], info["dv_bl_present"], info["dv_el_present"]) == \
        ("true", "true", "true")
    assert info["l1_nits"] == "0.0001 | 1000 | 92"
    assert info["l1_pq"] == "0 | 3079 | 1650"
    assert info["l5_offsets"] == "0 | 0 | 276 | 276"
    assert info["l6_mdl"] == "1000 | 0.005"
    assert info["l6_max_cll_fall"] == "1000 | 400"
    assert info["source_mdl"] == "4000 | 0.005"
    assert info["hdr10_mdl"] == "1000 | 0.005"
    assert info["hdr10_max_cll_fall"] == "1000 | 400"


def test_a_profile_8_rpu_without_a_configuration_record():
    frame = parsed(rpu={"header": {}, "profile": 8})
    info = dvinfo._build_info(frame, "", "8.1")
    # The bitstream says DV although the container does not.
    assert info["hdr_format"] == "dolbyvision"
    assert info["dv_profile"] == "8.1"
    assert info["dv_el_type"] == "8.1"
    assert info["structure"] == "ST-SL"
    assert info["bit_depth"] == ""
    assert (info["dv_rpu_present"], info["dv_bl_present"], info["dv_el_present"]) == \
        ("true", "true", "false")
    # Without a usable HdrDetail the RPU's own guess stands, with no compatibility id.
    assert dvinfo._build_info(frame, "", "")["dv_profile"] == "8"


@pytest.mark.parametrize(("label", "frame", "token", "mode"), [
    ("hdr10", parsed(), "hdr10", "HDR10"),
    ("", parsed(mdcv={"max_luminance": 1000, "min_luminance": 0.0001}), "hdr10", "HDR10"),
    ("hdr10", parsed(hdr10plus={"profile": "b"}), "hdr10+", "HDR10+ Profile B"),
    ("hlg", parsed(), "hlg", "HLG"),
    ("", parsed(), "", ""),
])
def test_other_hdr_formats(label, frame, token, mode):
    info = dvinfo._build_info(frame, label, "")
    assert info["hdr_format"] == token
    assert info["output_mode"] == mode
    # The DV rows stay empty outside Dolby Vision.
    assert info["dv_profile"] == info["structure"] == info["cm_version"] == ""


def test_hdr10plus_presence_ignores_a_stripped_payload():
    assert dvinfo._build_info(parsed(hdr10plus={}), "hdr10", "")["hdr10plus_present"] == ""
    present = parsed(hdr10plus={"profile": "a"})
    assert dvinfo._build_info(present, "hdr10", "")["hdr10plus_present"] == "1"
    stripped = parsed(hdr10plus={"profile": "a"}, flags=["hdr10plus-removed"])
    assert dvinfo._build_info(stripped, "hdr10", "")["hdr10plus_present"] == ""


def test_a_row_with_a_missing_part_stays_empty():
    frame = parsed(cll={"max_cll": 1000, "max_fall": None})
    assert dvinfo._build_info(frame, "hdr10", "")["hdr10_max_cll_fall"] == ""


@pytest.mark.parametrize(("value", "text"), [
    (1000, "1000"), (1000.0, "1000"), (0.5, "0.5"), (True, ""), (None, ""), ("12", ""),
])
def test_numbers(value, text):
    assert dvinfo._fmt_num(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (1000.4, "1000"), (0.0050, "0.005"), (0.00012, "0.0001"), (0, "0"), (None, ""),
])
def test_luminances(value, text):
    assert dvinfo._fmt_lum(value) == text


def test_enhancement_layer_tags_take_the_theme_colour():
    assert dvinfo._colourise_el_tag("7.6 FEL") == "7.6 [COLOR FF81C784]FEL[/COLOR]"
    xbmcgui.Window(10000).setProperty("TinyPPI.MelColor", "FF123456")
    assert dvinfo._colourise_el_tag("MEL") == "[COLOR FF123456]MEL[/COLOR]"
    assert dvinfo._colourise_el_tag("8.1") == "8.1"


def test_unparsable_side_data_leaves_the_fields_empty(monkeypatch):
    def broken(*_args, **_kwargs):
        raise ValueError("libdovi panic")
    monkeypatch.setattr(dvinfo, "_parse_sidedata", broken)
    assert dvinfo._parse("{}") == dvinfo._empty_sidedata()
    assert dvinfo._derive(("{}", "dolbyvision", "", False))[1]["output_mode"] == "Dolby Vision"
