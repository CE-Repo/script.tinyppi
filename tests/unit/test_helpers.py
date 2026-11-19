# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Frame-rate formatting (core/helpers.py) and the VS10 dialog's geometry
(ui/dialog_layout.py)."""

import math

import pytest

import xbmcaddon
import xbmcgui
from core import helpers
from core.utils import PROP_FPS_DROP
from ui import dialog_layout as layout


@pytest.mark.parametrize(("raw", "expected"), [
    ("23.976", "23.976"), ("23.98", "23.976"), ("24", "24"), ("24.0", "24"),
    ("25.0", "25"), ("29.97", "29.97"), ("59.94", "59.94"), ("60.0", "60"),
    ("119.9", "120"), ("47.952", "47.952"), ("12.5", "12.5"),
    (50, "50"), ("", ""), ("x", "x"), ("nan", "nan"), ("inf", "inf"),
])
def test_normalize_fps_snaps_to_broadcast_rates(raw, expected):
    assert helpers.normalize_fps(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("23.976023", "23.976"), ("23.99", "23.976"), ("24.000", "24"),
    ("29.97003", "29.97"), ("59.94006", "59.94"), ("60", "60"),
    ("25.1", "25.1"), ("12.3456", "12.346"), ("", ""), ("abc", ""),
    ("inf", ""), ("-inf", ""), ("1e400", ""), ("nan", ""),     # not a rate
])
def test_format_fps_trims_and_snaps(raw, expected):
    assert helpers.format_fps(raw) == expected


def layer(fps, seconds, dropped=(), stalled=(), fields=1, start=0):
    """The readings of a video layer playing *fps*, one a second.

    In a second named in *dropped* a frame of the film is skipped; in one
    named in *stalled* a picture stays on screen a turn longer.
    """
    film, shown, readings = 0, 1000, []
    for second in range(seconds):
        due = math.floor((second + 1) * fps) - math.floor(second * fps)
        if second in dropped:
            film, shown = film + due + 1, shown + due * fields
        elif second in stalled:
            film, shown = film + due - 1, shown + (due - 1) * fields
        else:
            film, shown = film + due, shown + due * fields
        pts = (start + round(film * 90_000 / fps)) % (1 << 32)
        readings.append((pts, shown, fps))
    return readings


def tallied(readings):
    tally = helpers.FrameTally()
    for reading in readings:
        tally.update(*reading)
    return tally


@pytest.mark.parametrize("fps", [23.976, 24.0, 25.0, 29.97, 50.0, 59.94, 60.0])
def test_a_steady_layer_drops_nothing(fps):
    tally = tallied(layer(fps, 7200))
    assert (tally.rate, tally.total) == (0, 0)


def test_a_skipped_frame_counts_at_once():
    readings = layer(23.976, 200, dropped={100})
    tally = tallied(readings[:100])
    assert tally.total == 0
    tally.update(*readings[100])
    assert (tally.rate, tally.total) == (1, 1)
    for reading in readings[101:]:
        tally.update(*reading)
    assert (tally.rate, tally.total) == (0, 1)


def test_a_picture_left_on_screen_longer_is_no_drop():
    assert tallied(layer(23.976, 600, stalled={10, 200, 400})).total == 0
    assert tallied(layer(23.976, 600, stalled={10}, dropped={11})).total == 1


def test_a_steady_drop_shows_as_a_rate():
    tally = tallied(layer(24.0, 20, dropped=set(range(10, 20))))
    assert (tally.rate, tally.total) == (1, 10)


def test_interlaced_video_shows_two_pictures_a_frame():
    assert tallied(layer(25.0, 60, fields=2)).total == 0
    assert tallied(layer(25.0, 60, dropped={30}, fields=2)).total == 1
    tally = tallied(layer(25.0, 10, fields=2))
    pts, shown, fps = layer(25.0, 10, fields=2)[-1]
    tally.update(pts + 3600, shown + 1, fps)                # a frame on, one field of it
    assert tally.total == 1


def test_the_time_stamp_wraps():
    assert tallied(layer(23.976, 60, start=(1 << 32) - 500_000)).total == 0


def test_a_jump_in_the_stream_is_a_new_starting_point():
    readings = layer(24.0, 40, dropped={30})
    pts, shown, fps = readings[10]
    readings[10] = ((pts + 90_000 * 600) % (1 << 32), shown, fps)       # ten minutes on
    readings[11:] = [((p + 90_000 * 600) % (1 << 32), n, f) for p, n, f in readings[11:]]
    readings[20] = (readings[20][0] - 90_000 * 60, *readings[20][1:])    # a minute back
    readings[21:] = [(p - 90_000 * 60, n, f) for p, n, f in readings[21:]]
    assert tallied(readings).total == 1


def test_a_stretch_starts_over_and_keeps_the_total():
    tally = tallied(layer(24.0, 20, dropped={10}))
    tally.restart()
    assert (tally.rate, tally.total) == (0, 1)
    for reading in layer(24.0, 20, dropped={5}):            # a count from 1000 again
        tally.update(*reading)
    assert tally.total == 2
    tally.update(0, 10**6, 25.0)                             # another rate: a new stretch
    tally.update(0, 10**6, 25.0)                             # nothing shown: no step known
    tally.update(3600 * 25, 10**6 + 24, 25.0)
    assert tally.total == 3
    tally.reset()
    assert (tally.rate, tally.total) == (0, 0)


def test_the_fps_row_reads_the_published_drops(monkeypatch):
    home = xbmcgui.Window(10000)
    home.setProperty(PROP_FPS_DROP, "2|37")
    assert helpers.fps_display_texts("23.976") == ("024 - 002", "22", "37")
    home.setProperty(PROP_FPS_DROP, "0|0")
    assert helpers.fps_display_texts("24") == ("024 - 000", "24", "0")
    home.setProperty(PROP_FPS_DROP, "30|1")                 # never below 0
    assert helpers.fps_display_texts("24") == ("024 - 030", "0", "1")


@pytest.mark.parametrize("published", ["", "2", "x|1", "1|x", "-1|3"])
def test_the_fps_row_without_counted_drops(published):
    xbmcgui.Window(10000).setProperty(PROP_FPS_DROP, published)
    assert helpers.fps_display_texts("50") == ("050 - 000", "50", "")


def test_the_fps_row_without_a_rate(monkeypatch):
    xbmcgui.Window(10000).setProperty(PROP_FPS_DROP, "2|5")
    monkeypatch.setattr(helpers, "fps_drop_reading", pytest.fail)  # never read without a rate
    assert helpers.fps_display_texts("") == ("000 - 000", "0", "")
    for raw in ("nan", "inf", "-inf", "1e400"):                 # no finite rate
        assert helpers.fps_display_texts(raw) == ("000 - 000", "0", "")


def test_the_toggle_count_is_read_from_the_drivers_settings(monkeypatch, tmp_path):
    node = tmp_path / "video"
    # As the driver lists its settings: the node's name, no path before it.
    node.write_text("[NODE]video:[rw/1/52/1]\n video.new_frame_count=12\n"
                    " video.toggle_count=4321\n video.show_first_frame_nosync=1\n")
    real_open = open
    monkeypatch.setattr(helpers, "open", lambda path, *args, **kwargs: real_open(
        node if path == helpers.TOGGLE_COUNT_PATH else path, *args, **kwargs), raising=False)
    assert helpers.read_toggle_count() == 4321
    node.write_text(" media.video.toggle_count=99\n")         # with its full path
    assert helpers.read_toggle_count() == 99
    node.write_text(" video.new_frame_count=12\n")            # a driver without it
    assert helpers.read_toggle_count() is None


def test_the_time_stamp_on_screen_is_read_from_the_layers_state(monkeypatch, tmp_path):
    node = tmp_path / "vframe_states"
    node.write_text("amvideo vframe states\nvframe_pool_size=16\nvf index=3\n"
                    "vf->pts=118794960\ncur vpts=118791180\nvf type=8\n")
    real_open = open
    monkeypatch.setattr(helpers, "open", lambda path, *args, **kwargs: real_open(
        node if path == helpers.VIDEO_STATES_PATH else path, *args, **kwargs), raising=False)
    assert helpers.read_video_pts() == 118791180
    node.write_text("cur vpts=-2000\n")                       # past 2^31, printed signed
    assert helpers.read_video_pts() == -2000
    node.write_text("amvideo vframe states\nvframe_pool_size=16\n")   # no frame queued
    assert helpers.read_video_pts() is None


def test_unreadable_layer_files(monkeypatch):
    def missing(path, *_args, **_kwargs):
        raise FileNotFoundError(path)
    monkeypatch.setattr(helpers, "open", missing, raising=False)
    assert helpers.read_toggle_count() is None
    assert helpers.read_video_pts() is None


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
