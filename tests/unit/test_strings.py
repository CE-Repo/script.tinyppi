# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's UI strings (web/strings.py)."""

import os
import re

import xbmc
import xbmcaddon
from web import strings
from web.strings import ui_strings


def test_every_string_comes_from_the_addons_table():
    texts = ui_strings(xbmcaddon.Addon())
    assert texts["connected"] == "#32274" and texts["runtime_h"] == "#32364"
    assert set(strings._UI_STRINGS) | {"yes", "no"} == set(texts)


def test_yes_no_and_cancel_are_kodis_own_strings():
    texts = ui_strings()
    assert (texts["yes"], texts["no"], texts["cancel"]) == ("#107", "#106", "#222")


def test_missing_core_strings_fall_back_to_english(monkeypatch):
    monkeypatch.setattr(xbmc, "getLocalizedString", lambda string_id: "")
    texts = ui_strings()
    assert (texts["yes"], texts["no"], texts["cancel"]) == ("Yes", "No", "Cancel")


def test_every_string_id_exists_in_the_english_language_file():
    path = os.path.join(xbmcaddon.ROOT, "resources", "language", "resource.language.en_gb",
                        "strings.po")
    with open(path, encoding="utf-8") as handle:
        defined = {int(found) for found in re.findall(r'msgctxt "#(\d+)"', handle.read())}
    assert set(strings._UI_STRINGS.values()) <= defined
