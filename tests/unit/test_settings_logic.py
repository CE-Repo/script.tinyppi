# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Settings whose effect needs Dolby Vision or Amlogic hardware.

Their effect cannot be seen on a desktop Kodi, so the code paths that
apply them are checked directly.
"""

import pytest

import xbmcaddon
import xbmcgui
from core.utils import highlight_hold
from info import properties
from ui import dvmetadata as metadata_view
from ui import overlay, splash, theme
from web.snapshot import SnapshotBuilder


def use(**values):
    xbmcaddon.SETTINGS.update({k: "true" if v is True else "false" if v is False else str(v)
                               for k, v in values.items()})


@pytest.mark.parametrize("mode, setting, value, source, expected", [
    ("SDR", "keep_area_on_sdr", True, "hdr10", "hdr10"),
    ("SDR", "keep_area_on_sdr", False, "hdr10", ""),
    ("HDR10 (VS10)", "keep_dv_area_on_hdr10", True, "dolbyvision", "dolbyvision"),
    ("HDR10 (VS10)", "keep_dv_area_on_hdr10", False, "dolbyvision", "hdr10"),
    ("", "keep_dv_area_on_hdr10", False, "dolbyvision", "dolbyvision"),
])
def test_layout_follows_the_output(monkeypatch, mode, setting, value, source, expected):
    monkeypatch.setattr(properties, "get_ModeVar", lambda: mode)
    use(**{setting: value})
    assert properties._effective_hdr_type(source) == expected


@pytest.mark.parametrize("setting, output", [
    ("channels_dv", "dolbyvision"), ("channels_hdr", "hdr10"), ("channels_hdr", "hlg"), ("channels_sdr", ""),
])
@pytest.mark.parametrize("on", [True, False])
def test_channel_graphic_per_output(setting, output, on):
    use(**{setting: on})
    home = xbmcgui.Window(10000)
    home.setProperty("TinyPPI.EffectiveHdrType", output)
    properties.publish_channel_visibility(home)
    assert home.getProperty("TinyPPI.ShowChannelIcon") == ("1" if on else "0")


def test_highlight_durations():
    use(output_changed_duration=2500, metadata_changed_duration=1200)
    assert highlight_hold(overlay._DV_CHANGED_HOLD) == 2.5
    assert highlight_hold(metadata_view._CHANGED_HOLD) == 1.2
    use(output_changed_duration=0)
    assert highlight_hold(overlay._DV_CHANGED_HOLD) == 0.75


def test_dv_metadata_view_switch():
    use(dv_metadata_view=True)
    assert overlay._dv_metadata_enabled() is True
    use(dv_metadata_view=False)
    assert overlay._dv_metadata_enabled() is False


def test_dv_channel_panel_slides_with_offset_x_dv():
    class Panel:
        position = None

        def setPosition(self, x, y):
            self.position = (x, y)

    dialog = overlay.TinyPPIDialog.__new__(overlay.TinyPPIDialog)
    panel = Panel()
    dialog.getControl = lambda control_id: panel
    placed = {}
    for percent in (0, 50, 100):
        dialog._dv_offset_pct = percent
        dialog._dv_channel_offset = None
        dialog._apply_dv_channel_offset()
        placed[percent] = panel.position
    assert placed[100] == (0, 0) and placed[0][0] < placed[50][0] < 0


def test_pill_position(monkeypatch):
    made = []
    monkeypatch.setattr(splash, "_make_image", lambda tex, x, y, w, h, c: made.append((tex, y)) or tex)
    monkeypatch.setattr(splash, "_make_dot", lambda x, y, d, c: "dot")
    colours = dict.fromkeys(("bg", "video", "audio", "divider", "convert_dot", "fel", "mel", "other"), "FFFFFFFF")

    def pill_y(top):
        made.clear()
        splash._build_controls([("a.png", "video"), ("b.png", "audio")], colours, 0, 0, 1920, 1080,
                               layer_token="fel", pill_at_top=top)
        return [y for tex, y in made if tex == splash._PILL_TEXTURE][0]

    assert pill_y(True) < pill_y(False)
    for mode in ("start", "osd", "tinyppi"):
        for value, top in ((0, False), (1, True)):
            use(**{f"splash_{mode}_pill_position": value})
            assert splash._read_settings(xbmcaddon.Addon()).modes[mode].pill_at_top is top


def test_web_metadata_off_sends_no_rows():
    builder = SnapshotBuilder.__new__(SnapshotBuilder)
    builder._meta_static, builder._meta_static_at = ["held"], 1.0
    assert builder._metadata(True, False) == [] and builder._meta_static == []


def test_colours_reach_their_properties():
    home = xbmcgui.Window(10000)
    expected = {}
    for index, (prop, _palette, setting_id) in enumerate(theme._THEME_PROPERTIES):
        rgb = f"{index * 37 % 256:02X}{index * 91 % 256:02X}{index * 53 % 256:02X}"
        opacity = index * 13 % 101
        use(**{setting_id: f"[COLOR=FF{rgb}]●[/COLOR] #{rgb}", theme._opacity_setting(setting_id): opacity})
        expected[prop] = f"{int(opacity * 255 / 100 + 0.5):02X}{rgb}"
    theme.apply_theme(home)
    assert {prop: home.getProperty(prop) for prop in expected} == expected
