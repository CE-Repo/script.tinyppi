# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Frame-rate formatting (core/helpers.py) and the VS10 dialog's geometry
(ui/dialog_layout.py)."""

import pytest

import xbmcaddon
from core import helpers
from ui import dialog_layout as layout


@pytest.mark.parametrize(("raw", "expected"), [
    ("23.976", "23.976"), ("23.98", "23.976"), ("24", "24"), ("24.0", "24"),
    ("25.0", "25"), ("29.97", "29.97"), ("59.94", "59.94"), ("60.0", "60"),
    ("119.9", "120"), ("47.952", "47.952"), ("12.5", "12.5"),
    (50, "50"), ("", ""), ("x", "x"),
])
def test_normalize_fps_snaps_to_broadcast_rates(raw, expected):
    assert helpers.normalize_fps(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("23.976023", "23.976"), ("23.99", "23.976"), ("24.000", "24"),
    ("29.97003", "29.97"), ("59.94006", "59.94"), ("60", "60"),
    ("25.1", "25.1"), ("12.3456", "12.346"), ("", ""), ("abc", ""),
])
def test_format_fps_trims_and_snaps(raw, expected):
    assert helpers.format_fps(raw) == expected


def test_fps_drop_from_sysfs(monkeypatch):
    monkeypatch.setattr(helpers, "_read_fps_sysfs", lambda: (0x18, 0x16))
    assert helpers.get_fps_drop() == 2
    assert helpers.fps_display_texts("23.976") == ("024 - 002", "22")
    monkeypatch.setattr(helpers, "_read_fps_sysfs", lambda: (10, 20))
    assert helpers.get_fps_drop() == 0


def test_fps_without_sysfs_or_a_rate(monkeypatch):
    monkeypatch.setattr(helpers, "_read_fps_sysfs", lambda: None)
    assert helpers.get_fps_drop() == 0
    assert helpers.fps_display_texts("50") == ("050 - 000", "50")
    monkeypatch.setattr(helpers, "_read_fps_sysfs", pytest.fail)  # never read without a rate
    assert helpers.fps_display_texts("") == ("000 - 000", "0")


def test_fps_sysfs_parsing(monkeypatch, tmp_path):
    node = tmp_path / "fps_info"
    node.write_text("input_fps:0x18 output_fps:0x17 drop_fps:0x1\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda path, *args, **kwargs: real_open(
        node if path == "/sys/class/video/fps_info" else path, *args, **kwargs))
    assert helpers._read_fps_sysfs() == (24, 23)
    node.write_text("garbage")
    assert helpers._read_fps_sysfs() is None


# --- The VS10 dialog's layouts ----------------------------------------------

def test_every_layout_has_a_file_and_a_size():
    assert set(layout.XML_FILES) == set(layout.PANEL_SIZE)


def test_the_selected_layout_and_unknown_values():
    assert layout.dialog_mode() == int(xbmcaddon.DEFAULTS["dialog_mode"])
    xbmcaddon.SETTINGS["dialog_mode"] = str(layout.MODE_BAR)
    assert layout.dialog_mode() == layout.MODE_BAR
    assert layout.xml_file() == "script-tinyppi-dialog-bar.xml"
    assert layout.xml_file(layout.MODE_DIALOG) == "script-tinyppi-dialog.xml"
    xbmcaddon.SETTINGS["dialog_mode"] = "7"            # from a newer version
    assert layout.dialog_mode() == layout.MODE_SINGLE
    xbmcaddon.SETTINGS["dialog_mode"] = "x"
    assert layout.dialog_mode() == layout.MODE_SINGLE


@pytest.mark.parametrize("mode", sorted(layout.PANEL_SIZE))
def test_the_panel_stays_on_screen_at_every_position(mode):
    width, height = layout.PANEL_SIZE[mode]
    margin = layout.SCREEN_MARGIN
    for x in (-20, 0, 33, 50, 100, 150):
        for y in (0, 50, 100):
            xbmcaddon.SETTINGS["dialog_position_x"] = str(x)
            xbmcaddon.SETTINGS["dialog_position_y"] = str(y)
            left, top = layout.panel_position(mode)
            assert margin <= left <= layout.SCREEN_WIDTH - width - margin
            assert margin <= top <= layout.SCREEN_HEIGHT - height - margin


def test_the_default_position_is_centred_at_the_bottom():
    width, height = layout.PANEL_SIZE[layout.MODE_BAR]
    left, top = layout.panel_position(layout.MODE_BAR)
    assert left == (layout.SCREEN_WIDTH - width) // 2
    assert top == layout.SCREEN_HEIGHT - height - layout.SCREEN_MARGIN


def test_across_rounds_half_up():
    assert layout._across(50, 0, 1) == 1
    assert layout._across(0, 10, 20) == 10
    assert layout._across(100, 10, 20) == 20


@pytest.mark.parametrize(("hdr_type", "hdr10plus", "branch"), [
    ("dolbyvision", "", "dv"), ("DolbyVision", "0", "dv"),
    ("dolbyvision", "1", "plain"),          # DV with an ST 2094-40 payload
    ("hdr10", "", "hdr10"), ("hdr10plus", "", "plain"), ("hlg", "", "plain"),
    ("hdr10", "1", "plain"), ("", "", "sdr"), (None, "", "sdr"),
])
def test_the_branch_matches_the_window_conditions(hdr_type, hdr10plus, branch):
    assert layout.branch_for(hdr_type, hdr10plus)["key"] == branch


def test_every_branch_starts_with_the_process_info_button():
    starts = [branch["buttons"][0] for branch in layout.BRANCHES]
    assert [control for control, _label, _mode in starts] == list(layout.PPI_BUTTONS)
    assert all(mode is None for _control, _label, mode in starts)


def test_plain_label_resolves_localize_only():
    assert layout.plain_label(layout.PPI_LABEL) == "[B]#10116[/B]"
    assert layout.plain_label("[B]Dolby Vision[/B]") == "[B]Dolby Vision[/B]"
