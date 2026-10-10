# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The VS10 dialog's layouts outside Kodi and their fallbacks (ui/dialog_layout.py)."""

import importlib.util
import sys

import pytest

import xbmcaddon
from ui import dialog_layout as layout


@pytest.fixture
def generator_copy(monkeypatch):
    """A fresh copy of the module as tools/gen_dialog_skins.py loads it: without Kodi."""
    monkeypatch.setitem(sys.modules, "xbmc", None)          # import xbmc raises ImportError
    spec = importlib.util.spec_from_file_location("dialog_layout_without_kodi", layout.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_without_kodi_the_settings_are_not_read(generator_copy):
    xbmcaddon.SETTINGS.update(dialog_mode=str(layout.MODE_BAR), dialog_position_x="0",
                              dialog_position_y="0")
    assert generator_copy.xbmc is None and generator_copy.settings is None
    assert generator_copy.dialog_mode() == layout.MODE_SINGLE
    assert generator_copy.xml_file() == "script-tinyppi-dialog-single.xml"
    width, height = layout.PANEL_SIZE[layout.MODE_BAR]
    assert generator_copy.panel_position(layout.MODE_BAR) == (
        (layout.SCREEN_WIDTH - width) // 2, layout.SCREEN_HEIGHT - height - layout.SCREEN_MARGIN)


def test_without_kodi_the_process_info_label_is_spelled_out(generator_copy):
    assert generator_copy.plain_label(layout.PPI_LABEL) == "[B]Player process info[/B]"
    assert layout.plain_label(layout.PPI_LABEL) == "[B]#10116[/B]"


def test_the_skin_generator_and_the_dialog_share_one_description(generator_copy):
    assert generator_copy.BRANCHES == layout.BRANCHES
    assert generator_copy.XML_FILES == layout.XML_FILES
    assert generator_copy.PANEL_SIZE == layout.PANEL_SIZE


def test_a_settings_handle_kodi_refuses_gives_the_defaults(monkeypatch):
    def shutting_down():
        raise RuntimeError("Kodi is shutting down")

    xbmcaddon.SETTINGS.update(dialog_mode=str(layout.MODE_BAR), dialog_position_y="0")
    monkeypatch.setattr(layout.settings, "addon", shutting_down)
    assert layout.dialog_mode() == layout.MODE_SINGLE
    assert layout.panel_position(layout.MODE_SINGLE)[1] == layout.top_range(layout.MODE_SINGLE)[1]


def test_a_branch_missing_from_the_description_falls_back_to_the_first(monkeypatch):
    monkeypatch.setattr(layout, "BRANCHES", tuple(b for b in layout.BRANCHES if b["key"] != "plain"))
    assert layout.branch_for("hlg", "")["key"] == "sdr"
    assert layout.branch_for("dolbyvision", "")["key"] == "dv"
