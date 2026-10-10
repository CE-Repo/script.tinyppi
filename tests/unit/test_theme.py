# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Publishing the colour settings, the colour picker and the old storage forms (ui/theme.py)."""

import json
import types

import pytest

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from ui import theme

FOREST = "FF81C784"     # convert_yes_color's default, so a fallback is not mistaken for index 0


def home():
    return xbmcgui.Window(10000)


def use(**values):
    xbmcaddon.SETTINGS.update({key: str(value) for key, value in values.items()})


def hex_value(rgb):
    return f"[COLOR=FF{rgb}]●[/COLOR] #{rgb}"


@pytest.fixture
def legacy_file(tmp_path, monkeypatch):
    """Where the pre-picker HEX colours were kept (not written yet)."""
    monkeypatch.setattr(xbmcvfs, "HOME", str(tmp_path))
    path = tmp_path / "profile" / "addon_data" / "script.tinyppi" / "custom_colors.json"
    path.parent.mkdir(parents=True)
    return path


@pytest.fixture
def picker(monkeypatch):
    """Kodi's colour picker and keyboard; set *answer*, *typed* and *confirmed* first."""
    record = types.SimpleNamespace(answer="", typed="", confirmed=True, shown=[], keyboards=[])

    def colorpicker(_dialog, heading, selected, colorlist):
        record.shown.append({"heading": heading, "selected": selected,
                             "tiles": [(tile.label, tile.label2) for tile in colorlist]})
        return record.answer

    class Keyboard:
        def __init__(self, default="", heading="", hidden=False):
            record.keyboards.append((default, heading))

        def doModal(self, autoclose=0):
            pass

        def isConfirmed(self):
            return record.confirmed

        def getText(self):
            return record.typed

    monkeypatch.setattr(xbmcgui.Dialog, "colorpicker", colorpicker)
    monkeypatch.setattr(xbmc, "Keyboard", Keyboard)
    return record


def notifications():
    return [args for kind, args, _kwargs in xbmcgui.DIALOGS if kind == "notification"]


# --- Publishing --------------------------------------------------------------------

@pytest.mark.parametrize(("stored", "label"), [
    (None, "cd/m²"), ("0", "cd/m²"), ("1", "nits"), ("2", ""),
    ("7", "cd/m²"), ("x", "cd/m²"), ("", "cd/m²"),          # unreadable: the first label
    ("-1", "cd/m²"),                                        # not the last one
])
def test_the_unit_label_follows_the_setting(stored, label):
    if stored is not None:
        use(unit_type=stored)
    theme.apply_theme(home())
    assert home().getProperty("TinyPPI.UnitLabel") == label


@pytest.mark.parametrize(("setting_id", "prop", "opacity", "alpha"), [
    ("background_color", "TinyPPI.BackgroundColor", "abc", "FA"),   # its own default, 98 %
    ("line_color", "TinyPPI.LineColor", "", "26"),                  # 15 %
    ("title_color", "TinyPPI.TitleColor", "half", "FF"),            # 100 %
    ("title_color", "TinyPPI.TitleColor", "150", "FF"),             # clamped
    ("title_color", "TinyPPI.TitleColor", "-5", "00"),
])
def test_an_unreadable_opacity_falls_back_to_the_elements_default(setting_id, prop, opacity, alpha):
    use(**{theme._opacity_setting(setting_id): opacity})
    theme.apply_theme(home())
    spec = theme._COLOR_SETTINGS[setting_id]
    assert home().getProperty(prop) == alpha + spec.palette[spec.default][2:]


def test_unsaved_values_win_over_the_stored_ones():
    use(title_color=hex_value("111111"), title_opacity="100")
    theme.apply_theme(home(), xbmcaddon.Addon(),
                      overrides={"title_color": hex_value("ABCDEF"), "title_opacity": 50})
    assert home().getProperty("TinyPPI.TitleColor") == "80ABCDEF"


@pytest.mark.parametrize("stored", [
    "garbage",
    "9999",                                                  # past the old palette
    "[COLOR=FF123456]●[/COLOR] #12345G",                     # not a HEX code, unknown swatch
    "[COLOR=12345678]●[/COLOR] Somewhere 3",
    "999",                                                   # old HEX marker, no file
    "²", "٣",                                                # no ASCII digits ("²" breaks int())
])
def test_an_unreadable_colour_gives_the_settings_default(legacy_file, stored):
    use(convert_yes_color=stored)
    theme.apply_theme(home())
    assert home().getProperty("TinyPPI.ConvertYesColor") == FOREST


@pytest.mark.parametrize(("content", "colour"), [
    ({"convert_yes_color": "FF123456"}, "FF123456"),
    ({"convert_yes_color": " ff12ab56 "}, "FF12AB56"),
    ({"convert_yes_color": "FF1234"}, FOREST),                # not eight digits
    ({"title_color": "FF123456"}, FOREST),                    # another setting's entry
    (["FF123456"], FOREST),                                   # not a mapping
    ("{broken", FOREST),
])
def test_the_old_hex_marker_reads_the_custom_colours_file(legacy_file, content, colour):
    legacy_file.write_text(content if isinstance(content, str) else json.dumps(content))
    use(convert_yes_color="999")
    theme.apply_theme(home())
    assert home().getProperty("TinyPPI.ConvertYesColor") == colour


def test_the_custom_colours_file_is_not_read_without_the_old_marker(legacy_file, monkeypatch):
    monkeypatch.setattr(theme, "_load_legacy_custom", pytest.fail)
    use(convert_yes_color=hex_value("123456"))
    theme.apply_theme(home())
    assert home().getProperty("TinyPPI.ConvertYesColor") == "FF123456"


# --- Migrating the old forms ---------------------------------------------------------

def test_old_hex_values_are_rewritten_and_the_file_removed(legacy_file, monkeypatch):
    legacy_file.write_text(json.dumps({"title_color": "FF123456", "fel_color": "FFABCDEF"}))
    loads = []
    real = theme._load_legacy_custom
    monkeypatch.setattr(theme, "_load_legacy_custom", lambda: loads.append(1) or real())
    use(title_color="999", fel_color="999", mel_color="999")
    assert theme.migrate_legacy_colors() == 3
    assert xbmcaddon.SETTINGS["title_color"] == hex_value("123456")
    assert xbmcaddon.SETTINGS["fel_color"] == hex_value("ABCDEF")
    mel = theme._COLOR_SETTINGS["mel_color"]
    assert xbmcaddon.SETTINGS["mel_color"] == theme._encode(mel, mel.default)  # no entry: the default
    assert loads == [1]                                     # read once for all three
    assert not legacy_file.exists()
    assert theme.migrate_legacy_colors() == 0


# --- The colour picker ----------------------------------------------------------------

def test_an_unknown_setting_opens_no_picker(picker):
    theme.pick_color("no_such_color", "32040")
    assert picker.shown == [] and xbmcaddon.SETTINGS == {}


@pytest.mark.parametrize("heading_id", ["Title", "²"])    # "²" passes str.isdigit()
def test_a_heading_that_is_no_string_id_is_left_empty(picker, heading_id):
    theme.pick_color("title_color", heading_id)
    [shown] = picker.shown
    assert shown["heading"] == ""


@pytest.mark.parametrize("answer", ["", "FF0000FF"])        # cancelled, a tile not offered
def test_cancelling_or_an_unknown_tile_changes_nothing(picker, answer):
    picker.answer = answer
    theme.pick_color("title_color", "32040")
    assert picker.shown[0]["heading"] == "#32040"
    assert "title_color" not in xbmcaddon.SETTINGS
    assert home().getProperty("TinyPPI.TitleColor") == ""


def test_a_hex_colour_shows_on_the_first_tile_and_is_selected(picker):
    use(title_color=hex_value("12AB56"))
    theme.pick_color("title_color")
    [shown] = picker.shown
    assert shown["tiles"][0] == ("#32204", "ff12ab56")
    assert shown["selected"] == "ff12ab56"


def test_an_old_hex_colour_from_the_file_shows_on_the_first_tile(picker, legacy_file):
    legacy_file.write_text(json.dumps({"title_color": "FF12AB56"}))
    use(title_color="999")
    theme.pick_color("title_color")
    assert picker.shown[0]["tiles"][0] == ("#32204", "ff12ab56")


@pytest.mark.parametrize(("stored", "prefill"), [
    (None, "EDEDED"),                                       # a palette colour: its HEX code
    (hex_value("12AB56"), "12AB56"),
])
def test_the_hex_tile_asks_for_a_code_and_stores_it(picker, stored, prefill):
    if stored:
        use(title_color=stored)
    picker.answer = "ff12ab56" if stored else theme._HEX_TILE_EMPTY
    picker.typed = "  #a1b2c3 "
    theme.pick_color("title_color", "32040")
    assert picker.keyboards == [(prefill, "#32205")]
    assert xbmcaddon.SETTINGS["title_color"] == hex_value("A1B2C3")
    assert notifications() == [("TinyPPI", "#32207", xbmcgui.NOTIFICATION_INFO, 3000)]
    assert home().getProperty("TinyPPI.TitleColor") == "FFA1B2C3"


def test_a_cancelled_hex_prompt_keeps_the_colour(picker):
    use(title_color=hex_value("12AB56"))
    picker.answer, picker.confirmed = "ff12ab56", False
    theme.pick_color("title_color")
    assert xbmcaddon.SETTINGS["title_color"] == hex_value("12AB56")
    assert notifications() == []


@pytest.mark.parametrize("typed", ["12345", "GGGGGG", "#1234567", ""])
def test_an_invalid_hex_code_gives_the_default_with_a_warning(picker, typed):
    use(convert_yes_color=hex_value("12AB56"))
    picker.answer, picker.typed = "ff12ab56", typed
    theme.pick_color("convert_yes_color")
    spec = theme._COLOR_SETTINGS["convert_yes_color"]
    assert xbmcaddon.SETTINGS["convert_yes_color"] == theme._encode(spec, spec.default)
    assert notifications() == [("TinyPPI", "#32206", xbmcgui.NOTIFICATION_ERROR, 4000)]
    assert home().getProperty("TinyPPI.ConvertYesColor") == FOREST


def test_a_failed_republish_does_not_undo_the_choice(picker, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("window gone")

    monkeypatch.setattr(theme, "apply_theme", broken)
    spec = theme._COLOR_SETTINGS["title_color"]
    picker.answer = spec.swatches[3]
    theme.pick_color("title_color")
    assert xbmcaddon.SETTINGS["title_color"] == theme._encode(spec, 3)
