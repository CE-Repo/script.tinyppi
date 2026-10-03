# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""resources/settings.xml against the strings, the code and the skin."""

import os
import re
import xml.etree.ElementTree as ET

import pytest

from ui import splash, theme

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TREE = ET.parse(os.path.join(ROOT, "resources", "settings.xml")).getroot()
SETTINGS = list(TREE.iter("setting"))
IDS = [setting.get("id") for setting in SETTINGS]
LANGUAGES = ("en_gb", "de_de", "hu_hu", "ar_sa", "zh_cn")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def strings(language):
    text = read("resources", "language", f"resource.language.{language}", "strings.po")
    pattern = r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"'
    return {int(m.group(1)): (m.group(2), m.group(3)) for m in re.finditer(pattern, text)}


CODE = "\n".join(
    read(os.path.relpath(os.path.join(folder, name), ROOT))
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "resources", "lib"))
    for name in files if name.endswith(".py")
) + read("main.py")
SKINS = "\n".join(
    read(os.path.relpath(os.path.join(folder, name), ROOT))
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "resources", "skins"))
    for name in files if name.endswith(".xml")
)
ACTIONS = [(s.get("id"), d.text) for s in SETTINGS for d in s.iter("data") if d.text]


def test_ids_are_unique():
    assert len(IDS) == len(set(IDS))


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_text_exists(language):
    table = strings(language)
    missing = []
    for element in [*TREE.iter("category"), *TREE.iter("group"), *SETTINGS, *TREE.iter("option")]:
        for attribute in ("label", "help"):
            value = element.get(attribute) or ""
            if not value.isdigit() or int(value) < 30000:
                continue                         # Kodi's own strings
            entry = table.get(int(value))
            if entry is None or not entry[0] or (language != "en_gb" and not entry[1]):
                missing.append(value)
    assert not missing


def test_defaults_fit_type_and_constraints():
    bad = []
    for setting in SETTINGS:
        kind, default = setting.get("type"), setting.findtext("default")
        constraints = setting.find("constraints")
        if kind == "boolean" and default not in ("true", "false"):
            bad.append(setting.get("id"))
        if kind != "integer":
            continue
        options = [o.text for o in constraints.iter("option")] if constraints is not None else []
        if options and default not in options:
            bad.append(setting.get("id"))
        if constraints is not None and constraints.findtext("minimum") is not None:
            low, high = int(constraints.findtext("minimum")), int(constraints.findtext("maximum"))
            if not low <= int(default) <= high:
                bad.append(setting.get("id"))
    assert not bad


def test_dependencies_name_existing_settings():
    assert not [(s.get("id"), c.get("setting")) for s in SETTINGS for c in s.iter("condition")
                if c.get("setting") and c.get("setting") not in IDS]


def test_action_buttons_run_known_commands():
    commands = set(re.findall(r'command == "(\w+)"', read("main.py"))) | {"overlay", "dialog"}
    wrong = []
    for setting_id, data in ACTIONS:
        match = re.match(r"RunScript\(script\.tinyppi,(\w+)(?:,([^,)]*))?", data)
        if not match or match.group(1) not in commands:
            wrong.append(setting_id)
        elif match.group(1) == "pick_color" and match.group(2) != setting_id:
            wrong.append(setting_id)     # a colour button edits its own row
    assert not wrong


@pytest.mark.parametrize("language", LANGUAGES)
def test_default_colours_keep_their_translated_names(language):
    table = strings(language)
    defaults = {spec.swatches[spec.default] for spec in theme._COLOR_SETTINGS.values()}
    assert defaults == set(theme._DEFAULT_NAMES)
    missing = [i for i in theme._DEFAULT_NAMES.values() if i not in table or not table[i][0]
               or (language != "en_gb" and not table[i][1])]
    assert not missing


def test_colour_names_are_unique_in_english():
    english = strings("en_gb")
    for setting_id, spec in theme._COLOR_SETTINGS.items():
        names = [english[name][0] if isinstance(name, int) else name for name in spec.names]
        assert len(set(names)) == len(names), setting_id


def test_colour_defaults_are_what_the_picker_stores():
    colours = [s for s in SETTINGS if s.get("id").endswith("_color")]
    assert len(colours) == len(theme._COLOR_SETTINGS)
    for setting in colours:
        spec = theme._COLOR_SETTINGS[setting.get("id")]
        assert theme._encode(spec, spec.default) == setting.findtext("default")
        assert theme._decode(spec, setting.findtext("default")) == (spec.default, "")


def test_every_colour_has_its_opacity_slider_with_the_code_default():
    defaults = {s.get("id"): s.findtext("default") for s in SETTINGS}
    for colour in theme._COLOR_SETTINGS:
        opacity = theme._opacity_setting(colour)
        assert opacity in defaults
        expected = theme._DEFAULT_OPACITIES.get(colour, theme._DEFAULT_OPACITY)
        assert int(defaults[opacity]) == expected
    sliders = [i for i in IDS if i.endswith("_opacity")]
    assert all(i[:-len("_opacity")] + "_color" in theme._COLOR_SETTINGS for i in sliders)


def test_every_colour_property_is_used():
    suffixes = tuple(splash._COLOR_PROP_SUFFIX.values())
    # Drawn by a skin file, read by the code, or built by the splash from
    # its per-mode prefix and suffix.
    unused = [prop for prop, _palette, _sid in theme._THEME_PROPERTIES
              if prop not in SKINS and prop not in CODE
              and not (prop.startswith("TinyPPI.Splash") and prop.endswith(suffixes))]
    assert not unused


def test_the_code_reads_only_existing_settings():
    named = set(re.findall(r'(?:get|set)Setting(?:Bool|Int|String)?\(\s*"([a-z0-9_]+)"', CODE))
    assert named and not named - set(IDS)


def test_every_setting_is_read_somewhere():
    derived = {theme._opacity_setting(c) for c in theme._COLOR_SETTINGS}
    action_only = {sid for sid, _data in ACTIONS if not sid.endswith("_color")}
    unread = [i for i in IDS if not re.search(r"['\"]" + re.escape(i) + r"['\"]", CODE)
              and i not in derived and i not in action_only]
    assert not unread
