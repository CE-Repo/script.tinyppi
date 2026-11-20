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


def layer(fps, seconds, dropped=(), skipped=(), fields=1, decoded_fields=1, jitter=0):
    """Readings a second apart of a decoder and a layer playing *fps*.

    In a second named in *dropped* the layer drops a frame the decoder put
    out; in one named in *skipped* the stream leaves out half its pictures
    (a still scene), which the decoder never puts out.  *jitter* frames
    more are decoded every other second: the queue filling and emptying.
    """
    decoded, shown, readings = 5000, 1000, []
    for second in range(seconds):
        due = math.floor((second + 1) * fps) - math.floor(second * fps)
        if second in skipped:
            due //= 2
        decoded += due * decoded_fields
        shown += (due - (second in dropped)) * fields
        readings.append((decoded + (jitter if second % 2 else 0), shown, fps))
    return readings


def tallied(readings):
    tally = helpers.FrameTally()
    for reading in readings:
        tally.update(*reading)
    return tally


@pytest.mark.parametrize("fps", [23.976, 24.0, 25.0, 29.97, 50.0, 59.94, 60.0])
def test_a_steady_layer_drops_nothing(fps):
    tally = tallied(layer(fps, 7200, jitter=1))
    assert (tally.rate, tally.total) == (0, 0)


def test_pictures_the_stream_leaves_out_are_no_drop():
    # VC-1 in a black scene: half the pictures are repeats never decoded.
    assert tallied(layer(23.976, 600, skipped=set(range(100, 400)))).total == 0
    assert tallied(layer(23.976, 600, skipped=set(range(100, 400)), dropped={200})).total == 1


def test_a_dropped_frame_counts_once_it_holds():
    readings = layer(23.976, 200, dropped={100}, jitter=1)
    tally = tallied(readings[:101])
    assert tally.total == 0                                  # one reading may be the queue
    for reading in readings[101:105]:
        tally.update(*reading)
    assert tally.total == 0                                  # the queue's jitter on top
    tally.update(*readings[105])
    assert (tally.rate, tally.total) == (1, 1)
    for reading in readings[106:]:
        tally.update(*reading)
    assert (tally.rate, tally.total) == (0, 1)


def test_a_steady_drop_shows_as_a_rate():
    tally = tallied(layer(24.0, 30, dropped=set(range(10, 30))))
    assert (tally.rate, tally.total) == (1, 18)              # the last two still unsure


def test_a_fuller_queue_at_the_start_is_no_drop():
    readings = layer(24.0, 60)
    readings[3] = (readings[3][0] + 1, *readings[3][1:])     # the queue's fullest
    assert tallied(readings).total == 0


def test_shown_more_than_decoded_sets_a_new_level():
    # A decoder that counts its frames late, as at the end of a still scene.
    readings = layer(24.0, 60, dropped={40})
    readings[20:] = [(d - 14, n, f) for d, n, f in readings[20:]]
    assert tallied(readings).total == 1


def test_the_pictures_a_frame_are_judged_over_enough_frames():
    tally = helpers.FrameTally()
    tally.update(100, 100, 25.0)
    tally.update(110, 108, 25.0)                             # too few frames to judge
    tally.update(125, 124, 25.0)                             # 25 frames: one picture each
    for second in range(1, 12):
        tally.update(125 + 25 * second, 124 + 25 * second - (second >= 8), 25.0)
    assert tally.total == 1


@pytest.mark.parametrize(("fields", "decoded_fields"), [(2, 1), (1, 2)])
def test_interlaced_video_counts_frames_not_fields(fields, decoded_fields):
    assert tallied(layer(25.0, 60, fields=fields, decoded_fields=decoded_fields)).total == 0
    assert tallied(layer(25.0, 60, dropped={30}, fields=fields,
                         decoded_fields=decoded_fields)).total == 1
    readings = layer(25.0, 60, fields=2)
    readings[30:] = [(d, n - 1, f) for d, n, f in readings[30:]]   # a lone field
    assert tallied(readings).total == 1


def test_a_stretch_starts_over_and_keeps_the_total():
    tally = tallied(layer(24.0, 20, dropped={10}))
    tally.restart()
    assert (tally.rate, tally.total) == (0, 1)
    for reading in layer(24.0, 20, dropped={8}):            # counts from the start again
        tally.update(*reading)
    assert tally.total == 2
    tally.update(0, 10**6, 25.0)                             # another rate: a new stretch
    for second in range(1, 12):
        tally.update(25 * second, 10**6 + 25 * second - (second >= 8), 25.0)
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


def test_the_decoded_count_is_read_from_the_decoders_status(monkeypatch, tmp_path):
    node = tmp_path / "vdec_status"
    node.write_text("vdec channel 0 statistics:\n  device name : amvdec_vc1\n"
                    "    frame dur : 4004\n  frame count : 688\n   drop count : 0\n")
    real_open = open
    monkeypatch.setattr(helpers, "open", lambda path, *args, **kwargs: real_open(
        node if path == helpers.DECODER_STATUS_PATH else path, *args, **kwargs), raising=False)
    assert helpers.read_decoded_count() == 688
    node.write_text("No vdec.\n")                            # nothing decoding
    assert helpers.read_decoded_count() is None


def test_unreadable_layer_files(monkeypatch):
    def missing(path, *_args, **_kwargs):
        raise FileNotFoundError(path)
    monkeypatch.setattr(helpers, "open", missing, raising=False)
    assert helpers.read_toggle_count() is None
    assert helpers.read_decoded_count() is None


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
