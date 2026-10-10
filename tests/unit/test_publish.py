# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The overlay's readings written as window properties (info/publish.py)."""

import pytest

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from info import dvinfo, publish

# A profile 8 frame as dvinfo derives it from the side data.
DV_FRAME = {
    "hdr_format": "dolbyvision",
    "output_mode": "Dolby Vision Profile 8.1",
    "cm_version": "CMv4.0",
    "structure": "ST-SL",
    "l5_offsets": "0 | 0 | 140 | 140",
    "l1_nits": "0.01 | 1000 | 92",
    "l1_pq": "62 | 3079 | 1650",
    "l6_mdl": "1000 | 0.005",
    "l6_max_cll_fall": "1000 | 400",
    "dv_version": "1.0",
    "dv_profile": "8.1",
    "dv_rpu_present": "true",
    "dv_bl_present": "true",
    "dv_el_present": "false",
}


class Sink:
    """A property target that records every write."""

    def __init__(self):
        self.values = {}
        self.writes = []

    def setProperty(self, name, value):
        self.values[name] = value
        self.writes.append(name)

    def getProperty(self, name):
        return self.values.get(name, "")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))


@pytest.fixture
def frame(monkeypatch):
    """Serve dvinfo's fields from a dict the test can change."""
    fields = dict(DV_FRAME)
    monkeypatch.setattr(dvinfo, "_snapshot", lambda: (fields, True))
    xbmc.CONDITIONS["Player.HasVideo"] = True
    return fields


def units(label="", color=""):
    xbmc.INFO["Window(10000).Property(TinyPPI.UnitLabel)"] = label
    xbmc.INFO["Window(10000).Property(TinyPPI.UnitColor)"] = color


# --- Scene readings -----------------------------------------------------------

@pytest.mark.parametrize("label, color, nits, pq", [
    ("nits", "FF00FF00", "[COLOR=FF00FF00]nits[/COLOR]", "[COLOR=FF00FF00]12-bit[/COLOR]"),
    ("cd/m²", "", "cd/m²", "12-bit"),
])
def test_metadata_rows_carry_the_unit(frame, label, color, nits, pq):
    units(label, color)
    sink = Sink()
    publish.publish_scene_properties(sink)
    assert sink.values["DoviLevel1FllVar"] == f"0.01 l 1000 l 92 {nits}"
    assert sink.values["DoviLevel1PqVar"] == f"62 l 3079 l 1650 {pq}"
    assert sink.values["DoviLevel6RpuMaxCllFallVar"] == f"1000 l 400 {nits}"


def test_hidden_units_leave_the_values_bare(frame):
    units(label="", color="FF00FF00")
    sink = Sink()
    publish.publish_scene_properties(sink)
    assert sink.values["DoviLevel1FllVar"] == "0.01 l 1000 l 92"
    assert sink.values["DoviLevel1PqVar"] == "62 l 3079 l 1650"


def test_scene_readings_of_a_dv_frame(frame):
    xbmc.INFO.update({"Player.Process(videowidth)": "1920",
                      "Player.Process(videoheight)": "1080",
                      "Player.Process(videodar)": "1.78"})
    sink = Sink()
    publish.publish_scene_properties(sink)
    assert sink.values["AspectRatioVar"] == "2.39"
    assert sink.values["DoviLevel5OffsetsVar"] == "0 l 0 l 140 l 140"
    assert sink.values["DoviLevel5OffsetsIconVisible"] == "true"
    assert sink.values["DoviRpuMdlVar"] == "1000 l 0.005"
    assert sink.values["DoviRpuMdlFromSourceVar"] == ""
    assert (sink.values["DoviVersionVar"], sink.values["DoviProfileNumberVar"]) == ("1.0", "8.1")
    # The DV panel shows L6 and the static SEIs separately: none here.
    assert sink.values["Hdr10MdlVar"] == "0 l 0"


def test_the_hdr10_panel_borrows_l6_while_it_replaces_the_dv_one(frame):
    home = xbmcgui.Window(10000)
    home.setProperty("TinyPPI.HdrType", "dolbyvision")
    home.setProperty("TinyPPI.EffectiveHdrType", "hdr10")
    sink = Sink()
    publish.publish_scene_properties(sink)
    assert sink.values["Hdr10MdlVar"] == "1000 l 0.005"
    assert sink.values["Hdr10MaxCllFallVar"] == "1000 l 400"


def test_the_offsets_icon_hides_for_a_status_label(frame):
    frame["l5_offsets"] = dvinfo.na_label()
    sink = Sink()
    publish.publish_scene_properties(sink)
    assert sink.values["DoviLevel5OffsetsIconVisible"] == "false"


def test_an_idle_scene_tick_writes_nothing(frame):
    sink, published = Sink(), {}
    publish.publish_scene_properties(sink, published)
    first = len(sink.writes)
    publish.publish_scene_properties(sink, published)
    assert first == 14 and len(sink.writes) == first
    frame["l1_nits"] = "0.01 | 600 | 50"
    publish.publish_scene_properties(sink, published)
    assert sink.writes[first:] == ["DoviLevel1FllVar"]


# --- HDR type -----------------------------------------------------------------

def test_hdr10_plus_is_published_without_the_plus(frame, monkeypatch):
    frame["hdr_format"] = "hdr10+"
    frame["hdr10plus_present"] = "1"
    monkeypatch.setattr(publish, "get_ModeVar", lambda: "")
    publish.publish_hdr_type()
    home = xbmcgui.Window(10000)
    assert home.getProperty("TinyPPI.HdrType") == "hdr10plus"
    assert home.getProperty("TinyPPI.EffectiveHdrType") == "hdr10plus"
    assert home.getProperty("TinyPPI.Hdr10PlusPresent") == "1"


@pytest.mark.parametrize("source, mode, keep, effective", [
    ("hdr10", "SDR BT709", "false", ""),             # VS10 to SDR uses the SDR box
    ("hdr10", "SDR BT709", "true", "hdr10"),
    ("dolbyvision", "HDR10 BT2020", "false", "hdr10"),
    ("dolbyvision", "HDR10 BT2020", "true", "dolbyvision"),
    ("dolbyvision", "DV-STD", "false", "dolbyvision"),
])
def test_the_layout_type_follows_a_vs10_conversion(frame, source, mode, keep, effective):
    frame["hdr_format"] = source
    xbmc.INFO["Player.Process(amlogic.eoft_gamut)"] = mode
    xbmcaddon.SETTINGS.update({"keep_area_on_sdr": keep, "keep_dv_area_on_hdr10": keep})
    home, published = Sink(), {}
    publish.publish_hdr_type(home, published)
    assert home.values["TinyPPI.HdrType"] == source
    assert home.values["TinyPPI.EffectiveHdrType"] == effective
    assert published["TinyPPI.EffectiveHdrType"] == effective


@pytest.mark.parametrize("hdr_type, setting", [
    ("dolbyvision", "channels_dv"), ("hlg", "channels_hdr"), ("", "channels_sdr"),
])
def test_channel_graphics_follow_their_output_setting(hdr_type, setting):
    xbmcaddon.SETTINGS[setting] = "true"
    home, published = Sink(), {}
    home.setProperty("TinyPPI.EffectiveHdrType", hdr_type)
    publish.publish_channel_visibility(home, published)
    publish.publish_channel_visibility(home, published)
    assert home.values["TinyPPI.ShowChannelIcon"] == "1"
    assert home.writes.count("TinyPPI.ShowChannelIcon") == 1
    xbmcaddon.SETTINGS[setting] = "false"
    publish.publish_channel_visibility()             # the Home window, no record
    assert xbmcgui.Window(10000).getProperty("TinyPPI.ShowChannelIcon") == "0"


# --- Static readings ----------------------------------------------------------

def test_the_output_mode_comes_from_the_side_data(frame):
    sink = Sink()
    publish.publish_static_properties(sink)
    assert sink.values["DoviProfileVar"] == "Dolby Vision Profile 8.1"
    assert sink.values["DoviRpuPresentVar"] == "true"
    assert sink.values["DoviElPresentVar"] == "false"
    assert xbmcgui.Window(10000).getProperty("TinyPPI.HdrType") == "dolbyvision"


def test_without_side_data_the_output_mode_is_kodis(frame):
    frame.clear()
    xbmc.INFO["VideoPlayer.HDRType"] = "hlg"
    sink = Sink()
    publish.publish_static_properties(sink)
    assert sink.values["DoviProfileVar"] == "HLG"


def test_the_cpu_temperature_bar_is_set_once_per_value(frame):
    xbmc.INFO["System.CPUTemperature"] = "55 °C"
    xbmc.INFO["VideoPlayer.VideoCodec"] = "hevc"
    window, published = xbmcgui.Window(13000), {}
    publish.update_static_properties(window, published)
    publish.update_static_properties(window, published)
    bar = window.getControl(9100)
    assert bar.calls == [("setPercent", (50.0,))]
    assert window.getProperty("DoviProfileVar") == "Dolby Vision Profile 8.1"
    assert window.getProperty("VideoCodecVar") == "H.265"

    xbmc.INFO["System.CPUTemperature"] = "66 °C"
    publish.update_static_properties(window)        # no record: always writes
    assert bar.percent == pytest.approx(60.0) and len(bar.calls) == 2


# --- Everything at once -------------------------------------------------------

def test_publish_properties_fills_both_halves(frame):
    sink, published = Sink(), {}
    publish.publish_properties(sink, published)
    assert sink.values["DoviLevel1FllVar"].startswith("0.01 l 1000 l 92")
    assert sink.values["DoviProfileVar"] == "Dolby Vision Profile 8.1"
    writes = len(sink.writes)
    publish.publish_properties(sink, published)
    assert len(sink.writes) == writes

    other = Sink()
    publish.publish_properties(other)
    assert other.values == sink.values
