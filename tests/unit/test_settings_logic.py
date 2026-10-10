# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Settings whose effect needs Dolby Vision or Amlogic hardware.

Their effect cannot be seen on a desktop Kodi, so the code paths that
apply them are checked directly.
"""

import math
from itertools import pairwise

import pytest

import xbmcaddon
import xbmcgui
from core.utils import highlight_hold
from info import publish
from ui import dvmetadata as metadata_view
from ui import overlay, palette, splash, theme
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
    monkeypatch.setattr(publish, "get_ModeVar", lambda: mode)
    use(**{setting: value})
    assert publish._effective_hdr_type(source) == expected


@pytest.mark.parametrize("setting, output", [
    ("channels_dv", "dolbyvision"), ("channels_hdr", "hdr10"), ("channels_hdr", "hlg"), ("channels_sdr", ""),
])
@pytest.mark.parametrize("on", [True, False])
def test_channel_graphic_per_output(setting, output, on):
    use(**{setting: on})
    home = xbmcgui.Window(10000)
    home.setProperty("TinyPPI.EffectiveHdrType", output)
    publish.publish_channel_visibility(home)
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


def _picker_tiles(monkeypatch, setting_id, answer=""):
    shown = {}

    def colorpicker(_dialog, heading, selected, colorlist):
        shown.update(selected=selected, tiles=[(tile.label, tile.label2) for tile in colorlist])
        return answer

    monkeypatch.setattr(xbmcgui.Dialog, "colorpicker", colorpicker)
    theme.pick_color(setting_id, "32040")
    return shown


@pytest.mark.parametrize("setting_id", ["title_color", "background_color", "dialog_focus_text_color"])
def test_picker_shows_the_hex_tile_then_the_default_then_the_palette(monkeypatch, setting_id):
    spec = theme._COLOR_SETTINGS[setting_id]
    shown = _picker_tiles(monkeypatch, setting_id)
    assert shown["tiles"][0] == (f"#{theme._HEX_TILE_LABEL}", theme._HEX_TILE_EMPTY)
    tiles = {swatch: ((f"#{name}" if isinstance(name, int) else name)
                      + (f" #{theme._DEFAULT_LABEL}" if index == spec.default else ""), swatch)
             for index, (name, swatch) in enumerate(zip(spec.names, spec.swatches, strict=True))}
    default = spec.swatches[spec.default]
    assert shown["tiles"][1] == tiles[default]
    assert shown["tiles"][2:] == [tile for swatch, tile in tiles.items() if swatch != default]
    # Only the colours settings start out on keep a translated name.
    translated = {swatch for name, swatch in zip(spec.names, spec.swatches, strict=True) if isinstance(name, int)}
    assert spec.swatches[spec.default] in translated <= set(theme._DEFAULT_NAMES)
    assert shown["selected"] == spec.swatches[spec.default]


def test_colour_names_count_up_per_family():
    families = (("Red", ("FFFF0000", "FFEE0000", "FFCC0000", "FF990000")), ("Black", ("FF000000",)))
    assert [name for name, _colour in palette.named(families, {})] == [
        "Red", "Red 1", "Red 2", "Red 3", "Black"]
    # A fixed name leaves the count without a gap.
    assert [name for name, _colour in palette.named(families, {"FFEE0000": 32212})] == [
        "Red", 32212, "Red 1", "Red 2", "Black"]
    pairs = (("Dark gray", (("FA151515", "FF2A2A2A"), ("FA101010", "FF202020"))),)
    assert [name for name, _pair in palette.named(pairs, {"FF2A2A2A": 32210})] == [32210, "Dark gray"]
    assert len(palette.named(palette.TEXT, {})) == len(palette.named(palette.BACKGROUND, {})) == 250


def test_picking_a_new_colour_stores_and_publishes_it(monkeypatch):
    spec = theme._COLOR_SETTINGS["title_color"]
    _picker_tiles(monkeypatch, "title_color", answer=spec.swatches[200])
    stored = xbmcaddon.SETTINGS["title_color"]
    assert stored == f"[COLOR={spec.swatches[200]}]●[/COLOR] {spec.names[200]}"
    assert theme._decode(spec, stored) == (200, "")
    assert xbmcgui.Window(10000).getProperty("TinyPPI.TitleColor") == spec.palette[200]


@pytest.mark.parametrize("stored", [
    "12",                                                           # palette index
    "[COLOR=FFFFD54F]●[/COLOR] $ADDON[script.tinyppi 32152]",        # name whose string is gone
    "[COLOR=FFFFD54F]●[/COLOR] Amber 9",                            # a name since moved on
])
def test_older_stored_colours_keep_their_colour(stored):
    spec = theme._COLOR_SETTINGS["title_color"]
    amber = spec.swatches.index("FFFFD54F")
    assert theme._decode(spec, stored) == (amber, "")
    use(title_color=stored)
    assert theme.migrate_legacy_colors() == 1
    assert xbmcaddon.SETTINGS["title_color"] == f"[COLOR=FFFFD54F]●[/COLOR] {spec.names[amber]}"
    assert theme.migrate_legacy_colors() == 0


def test_translated_default_names_stay_as_stored_before():
    spec = theme._COLOR_SETTINGS["convert_yes_color"]
    stored = "[COLOR=FF81C784]●[/COLOR] $ADDON[script.tinyppi 32214] $ADDON[script.tinyppi 32203]"
    assert theme._encode(spec, spec.default) == stored
    use(convert_yes_color=stored)
    assert theme.migrate_legacy_colors() == 0


def test_every_tile_can_be_told_apart():
    # The picker hands back the tile's swatch, and a setting stores it.
    for setting_id, spec in theme._COLOR_SETTINGS.items():
        assert len(set(spec.swatches)) == len(spec.swatches) >= 250, setting_id
        assert len(set(spec.names)) == len(spec.names), setting_id


def _depth(argb):
    """Distance in OKLab from white: how far an ARGB colour is from light."""
    def linear(at):
        value = int(argb[at:at + 2], 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = linear(2), linear(4), linear(6)
    long_ = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
    lightness = 0.2104542553 * long_ + 0.7936177850 * medium - 0.0040720468 * short
    a = 1.9779984951 * long_ - 2.4285922050 * medium + 0.4505937099 * short
    b = 0.0259040371 * long_ + 0.7827717662 * medium - 0.8086757660 * short
    return math.hypot(1 - lightness, a, b)


def test_every_family_runs_light_to_dark():
    for family, colours in palette.TEXT:
        steps = [_depth(colour) for colour in colours]
        assert steps == sorted(steps), family
    for family, pairs in palette.BACKGROUND:
        shades = [_depth(shade) for shade, _swatch in pairs]
        assert shades == sorted(shades), family
        # The swatches follow their shades, but for rounding.
        swatches = [_depth(swatch) for _shade, swatch in pairs]
        assert all(after >= before - 0.005 for before, after in pairwise(swatches)), family


def _saturation(argb):
    """OKLCH chroma of an ARGB colour as a share of the most sRGB holds there."""
    def linear(at):
        value = int(argb[at:at + 2], 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = linear(2), linear(4), linear(6)
    lms = [(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3),
           (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3),
           (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)]
    lightness = 0.2104542553 * lms[0] + 0.7936177850 * lms[1] - 0.0040720468 * lms[2]
    a = 1.9779984951 * lms[0] - 2.4285922050 * lms[1] + 0.4505937099 * lms[2]
    b = 0.0259040371 * lms[0] + 0.7827717662 * lms[1] - 0.8086757660 * lms[2]
    chroma, hue = math.hypot(a, b), math.atan2(b, a)

    def fits(c):
        x, y = c * math.cos(hue), c * math.sin(hue)
        l_, m_, s_ = ((lightness + 0.3963377774 * x + 0.2158037573 * y) ** 3,
                      (lightness - 0.1055613458 * x - 0.0638541728 * y) ** 3,
                      (lightness - 0.0894841775 * x - 1.2914855480 * y) ** 3)
        rgb = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
               -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
               -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)
        return all(-1e-6 <= v <= 1 + 1e-6 for v in rgb)

    low, high = 0.0, 0.5
    for _ in range(30):
        low, high = ((low + high) / 2, high) if fits((low + high) / 2) else (low, (low + high) / 2)
    return chroma / max(low, chroma, 1e-9)


GRAYS = ("White", "Gray", "Slate", "Sand", "Dark gray", "Black", "Dark slate", "Dark sand")


def test_neighbours_in_a_family_share_their_saturation():
    # A vivid tone between pale ones reads as darker than it is: yellow,
    # gold, then pale khaki looked light, dark, light again.
    families = [(family, colours) for family, colours in palette.TEXT]
    families += [(family, [swatch for _shade, swatch in pairs]) for family, pairs in palette.BACKGROUND]
    for family, colours in families:
        if family in GRAYS:
            continue
        shares = [_saturation(colour) for colour in colours]
        assert all(abs(after - before) < 0.26 for before, after in pairwise(shares)), family


def test_former_background_swatches_still_read_as_their_shade():
    spec = theme._COLOR_SETTINGS["background_color"]
    assert len(set(spec.palette)) == len(spec.palette)     # no two tiles give one shade
    for number, (swatch, shade) in enumerate(theme._LEGACY_BACKGROUND):
        index, _rgb = theme._decode(spec, f"[COLOR={swatch}]●[/COLOR] $ADDON[script.tinyppi 32132]")
        assert spec.palette[index] == shade
        assert spec.palette[theme._decode(spec, str(number))[0]] == shade
