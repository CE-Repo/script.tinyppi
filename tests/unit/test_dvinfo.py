# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dolby Vision and HDR fields from parsed side data (info/dvinfo.py).

The parse itself is script.module.sidedata's; these tests feed its result
shape directly.
"""

import importlib.util
import sys
import types

import pytest

import xbmc
import xbmcgui
from info import dvfields, dvinfo


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
    info = dvfields.build_info(P7_FEL, "dolbyvision", "")
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
    info = dvfields.build_info(frame, "", "8.1")
    # The bitstream says DV although the container does not.
    assert info["hdr_format"] == "dolbyvision"
    assert info["dv_profile"] == "8.1"
    assert info["dv_el_type"] == "8.1"
    assert info["structure"] == "ST-SL"
    assert info["bit_depth"] == ""
    assert (info["dv_rpu_present"], info["dv_bl_present"], info["dv_el_present"]) == \
        ("true", "true", "false")
    # Without a usable HdrDetail the RPU's own guess stands, with no compatibility id.
    assert dvfields.build_info(frame, "", "")["dv_profile"] == "8"


@pytest.mark.parametrize(("label", "frame", "token", "mode"), [
    ("hdr10", parsed(), "hdr10", "HDR10"),
    ("", parsed(mdcv={"max_luminance": 1000, "min_luminance": 0.0001}), "hdr10", "HDR10"),
    ("hdr10", parsed(hdr10plus={"profile": "b"}), "hdr10+", "HDR10+ Profile B"),
    ("hlg", parsed(), "hlg", "HLG"),
    ("", parsed(), "", ""),
])
def test_other_hdr_formats(label, frame, token, mode):
    info = dvfields.build_info(frame, label, "")
    assert info["hdr_format"] == token
    assert info["output_mode"] == mode
    # The DV rows stay empty outside Dolby Vision.
    assert info["dv_profile"] == info["structure"] == info["cm_version"] == ""


def test_hdr10plus_presence_ignores_a_stripped_payload():
    assert dvfields.build_info(parsed(hdr10plus={}), "hdr10", "")["hdr10plus_present"] == ""
    present = parsed(hdr10plus={"profile": "a"})
    assert dvfields.build_info(present, "hdr10", "")["hdr10plus_present"] == "1"
    stripped = parsed(hdr10plus={"profile": "a"}, flags=["hdr10plus-removed"])
    assert dvfields.build_info(stripped, "hdr10", "")["hdr10plus_present"] == ""


def test_a_row_with_a_missing_part_stays_empty():
    frame = parsed(cll={"max_cll": 1000, "max_fall": None})
    assert dvfields.build_info(frame, "hdr10", "")["hdr10_max_cll_fall"] == ""


@pytest.mark.parametrize(("value", "text"), [
    (1000, "1000"), (1000.0, "1000"), (0.5, "0.5"), (True, ""), (None, ""), ("12", ""),
])
def test_numbers(value, text):
    assert dvfields._fmt_num(value) == text


@pytest.mark.parametrize(("value", "text"), [
    (1000.4, "1000"), (0.0050, "0.005"), (0.00012, "0.0001"), (0, "0"), (None, ""),
])
def test_luminances(value, text):
    assert dvfields._fmt_lum(value) == text


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


def test_an_installed_parser_is_asked_for_the_composer_data(monkeypatch):
    calls = []

    def parse_sidedata(raw, include_mapping=False):
        calls.append((raw, include_mapping))
        return parsed(rpu={"profile": 8})
    monkeypatch.setitem(sys.modules, "sidedata",
                        types.SimpleNamespace(parse_sidedata=parse_sidedata))
    # Load a private copy: the shared module keeps its own import result.
    spec = importlib.util.spec_from_file_location("dvinfo_with_parser", dvinfo.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._SIDEDATA_IMPORT_ERROR is None
    assert module._MAPPING_KWARG is True
    assert module._parse("raw", mapping=True)["rpu"] == {"profile": 8}
    assert module._parse("raw")["rpu"] == {"profile": 8}
    assert calls == [("raw", True), ("raw", False)]


@pytest.fixture
def warned(monkeypatch):
    """Forget which problems were already logged."""
    monkeypatch.setattr(dvinfo, "_warned", set())


def warnings():
    return [line for level, line in xbmc.LOG if level == xbmc.LOGWARNING]


def test_a_missing_parser_is_reported_once(monkeypatch, warned):
    monkeypatch.setattr(dvinfo, "_parse_sidedata", None)
    assert dvinfo._parse("{}") == dvinfo._empty_sidedata()
    assert dvinfo._parse("{}") == dvinfo._empty_sidedata()
    assert len(warnings()) == 1
    assert "script.module.sidedata unavailable" in warnings()[0]


def test_an_empty_label_or_an_odd_result_reads_as_no_side_data(monkeypatch):
    calls = []

    def parse_sidedata(raw):
        calls.append(raw)
        return ["not", "a", "dict"]
    monkeypatch.setattr(dvinfo, "_parse_sidedata", parse_sidedata)
    assert dvinfo._parse("") == dvinfo._empty_sidedata()
    assert calls == []
    assert dvinfo._parse("{}") == dvinfo._empty_sidedata()
    assert calls == ["{}"]


def test_a_failure_while_deriving_is_logged_once(monkeypatch, warned):
    monkeypatch.setattr(dvinfo, "_parse_sidedata", lambda raw: parsed(rpu={"profile": 8}))

    def broken(*_args):
        raise KeyError("l1")
    monkeypatch.setattr(dvinfo, "build_info", broken)
    for _ in range(2):
        frame, fields = dvinfo._derive(("{}", "dolbyvision", "", False))
        assert frame["rpu"] == {"profile": 8}
        assert fields == dvfields.empty_info()
    assert len(warnings()) == 1
    assert "could not be interpreted" in warnings()[0]


def test_hdr10plus_named_by_kodi():
    for label in ("HDR10+", "hdr10plus"):
        info = dvfields.build_info(parsed(), label, "")
        assert info["hdr_format"] == "hdr10+"
        assert info["output_mode"] == "HDR10+"


def test_a_record_without_presence_flags_leaves_them_unknown():
    info = dvfields.build_info(parsed(config={"profile": 8, "compat_id": 1}), "", "")
    assert info["dv_profile"] == "8.1"
    assert (info["dv_rpu_present"], info["dv_bl_present"], info["dv_el_present"]) == \
        ("", "", "")


class Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def frames(monkeypatch):
    """Play a video whose side-data label maps to parse results in a dict.

    Returns ``(results, parses, clock)``: set ``results[raw]`` and point the
    side-data label at *raw*; *parses* records each parse as (raw, mapping).
    """
    results: dict = {}
    parses: list = []

    def parse_sidedata(raw, include_mapping=False):
        parses.append((raw, include_mapping))
        return results[raw]
    clock = Clock()
    monkeypatch.setattr(dvinfo, "_parse_sidedata", parse_sidedata)
    monkeypatch.setattr(dvinfo, "_MAPPING_KWARG", True)
    monkeypatch.setattr(dvinfo, "_snapshots", dvinfo._Snapshots())
    monkeypatch.setattr(dvinfo, "time", types.SimpleNamespace(monotonic=clock.monotonic))
    xbmc.CONDITIONS["Player.HasVideo"] = True
    xbmc.INFO["Player.FilenameAndPath"] = "/films/hybrid.mkv"
    return results, parses, clock


def show(raw):
    xbmc.INFO["Player.Process(video.sidedata)"] = raw


def test_a_frame_is_parsed_once_and_held_briefly(frames):
    results, parses, clock = frames
    results["a"] = parsed(rpu={"profile": 8, "l1": {"max_pq": 3079, "min_pq": 0, "avg_pq": 9}})
    show("a")
    assert dvinfo.get_l1_pq() == "0 | 3079 | 9"
    assert dvinfo.get_dv_profile() == "8"
    clock.now += dvinfo._SNAPSHOT_TTL * 2
    # The same payload after the snapshot expired: no new parse.
    assert dvinfo.get_l1_pq() == "0 | 3079 | 9"
    assert parses == [("a", False)]


def test_title_level_fields_carry_across_frames_until_the_title_changes(frames):
    results, parses, clock = frames
    results["full"] = parsed(rpu={"profile": 8, "source": {"max_nits": 4000, "min_nits": 0.005}},
                             hdr10plus={"profile": "B"})
    results["compressed"] = parsed(rpu={"profile": 8, "l6": {"max_lum_nits": 1000,
                                                             "min_lum_nits": 0.0001}})
    show("full")
    assert dvinfo.get_rpu_mdl() == "4000 | 0.005"
    assert dvinfo.get_hdr10plus_present() == "1"

    clock.now += 1
    show("compressed")
    assert dvinfo.get_rpu_mdl() == "4000 | 0.005"
    assert dvinfo.get_rpu_mdl_from_source() == "true"
    assert dvinfo.get_hdr10plus_present() == "1"

    # Another title: a plain DV stream must not read as the hybrid before it.
    clock.now += 1
    show("compressed")
    xbmc.INFO["Player.FilenameAndPath"] = "/films/plain.mkv"
    xbmc.INFO["VideoPlayer.HdrType"] = "dolbyvision"
    assert dvinfo.get_rpu_mdl() == "1000 | 0.0001"
    assert dvinfo.get_rpu_mdl_from_source() == ""
    assert dvinfo.get_hdr10plus_present() == ""
    assert [raw for raw, _mapping in parses] == ["full", "compressed", "compressed"]


def test_the_metadata_view_asks_for_the_composer_data(frames):
    results, parses, clock = frames
    results["a"] = parsed(rpu={"profile": 8})
    show("a")
    assert dvinfo.get_sidedata(mapping=True)["rpu"] == {"profile": 8}
    assert parses == [("a", True)]
    clock.now += dvinfo._MAPPING_TTL + 1
    # The request lapsed: the overlay's own read parses without it.
    assert dvinfo.get_sidedata()["rpu"] == {"profile": 8}
    assert parses == [("a", True), ("a", False)]


def test_no_video_means_no_side_data(frames):
    results, _parses, clock = frames
    results["a"] = parsed(rpu={"profile": 8})
    show("a")
    assert dvinfo.get_sidedata() is not None
    clock.now += 1
    xbmc.CONDITIONS["Player.HasVideo"] = False
    assert dvinfo.get_sidedata() is None
    assert dvinfo.get_bit_depth() == ""


def test_the_getters_read_the_current_frame(frames):
    results, _parses, _clock = frames
    results["fel"] = P7_FEL
    show("fel")
    xbmc.INFO["VideoPlayer.HdrType"] = "dolbyvision"
    assert dvinfo.get_hdr_format() == "dolbyvision"
    assert dvinfo.get_output_mode() == "Dolby Vision Profile 7.6 [COLOR FF81C784]FEL[/COLOR]"
    assert dvinfo.get_dv_el_type() == "[COLOR FF81C784]FEL[/COLOR]"
    assert dvinfo.get_dv_el_type_raw() == "FEL"
    assert (dvinfo.get_cm_version(), dvinfo.get_structure(), dvinfo.get_dv_version()) == \
        ("CMv4.0", "DT-DL", "1.0")
    assert (dvinfo.get_dv_rpu_present(), dvinfo.get_dv_bl_present(),
            dvinfo.get_dv_el_present()) == ("true", "true", "true")
    assert dvinfo.get_bit_depth() == "12"
    assert dvinfo.get_l5_offsets() == "0 | 0 | 276 | 276"
    assert dvinfo.get_l1_nits() == "0.0001 | 1000 | 92"
    assert dvinfo.get_l6_rpu_max_cll_fall() == "1000 | 400"
    # The source range wins over L6 for the mastering display.
    assert dvinfo.get_rpu_mdl() == "4000 | 0.005"
    assert dvinfo.get_hdr10_mdl() == "1000 | 0.005"
    assert dvinfo.get_hdr10_max_cll_fall() == "1000 | 400"


def test_missing_readings_fall_back_to_placeholders_or_na(frames):
    results, _parses, _clock = frames
    # Profile 5 has no static SEIs: only L6 can stand in for them.
    results["p5"] = parsed(rpu={"profile": 5, "l6": {"max_lum_nits": 1000, "min_lum_nits": 0.0001,
                                                     "max_cll": 500, "max_fall": 100}})
    show("p5")
    assert dvinfo.get_l5_offsets() == dvinfo.L5_EMPTY
    assert dvinfo.get_l1_nits() == dvinfo.get_l1_pq() == dvinfo.L1_EMPTY
    assert dvinfo.get_rpu_mdl() == "1000 | 0.0001"
    assert dvinfo.get_rpu_mdl_from_source() == ""
    assert dvinfo.get_hdr10_mdl() == "0 | 0"
    assert dvinfo.get_hdr10_mdl(l6_fallback=True) == "1000 | 0.0001"
    assert dvinfo.get_hdr10_max_cll_fall() == "0 | 0"
    assert dvinfo.get_hdr10_max_cll_fall(l6_fallback=True) == "500 | 100"
    # No enhancement layer: the bit depth reads N/A while the video plays.
    assert dvinfo.get_bit_depth() == dvinfo.na_label()
    assert dvinfo.is_status_label(dvinfo.get_bit_depth())
    assert not dvinfo.is_status_label("12")
