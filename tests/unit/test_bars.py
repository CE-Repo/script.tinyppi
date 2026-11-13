# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Black bars measured from a captured frame (info/bars.py)."""

import pytest

from info import bars
from info.bars import BarTracker, measure

SIZE = 100          # frames are 100 x 100, so pixels read as percent


def picture(left=0, right=0, top=0, bottom=0, level=200, black=0):
    """A BGRA frame with a lit picture inside the given bars, as rows of levels."""
    rows = []
    for y in range(SIZE):
        inside_y = top <= y < SIZE - bottom
        rows.append([level if inside_y and left <= x < SIZE - right else black
                     for x in range(SIZE)])
    return rows


def image(rows):
    """The BGRA bytes of *rows* (grey levels, opaque)."""
    return bytearray(b"".join(bytes((v, v, v, 255)) for row in rows for v in row))


def measured(rows):
    return measure(image(rows), SIZE, SIZE)


# --- The capture size ---------------------------------------------------------

@pytest.mark.parametrize(("aspect", "size"), [
    (0.0, (640, 360)),                      # unknown: 16:9
    (1.7778, (640, 360)),
    (2.39, (640, 268)),                     # an encode cropped to the picture
    (1.3333, (640, 480)),
    (0.5, (640, 640)),                      # held to a sane height
    (10.0, (640, 180)),
])
def test_the_capture_follows_the_videos_ratio(aspect, size):
    assert bars.capture_size(aspect) == size


# --- One frame ----------------------------------------------------------------

def test_any_colour_channel_lights_a_pixel_and_alpha_none():
    pixels = bytes((0, 0, 0, 255)) + bytes((0, 0, 90, 255)) + bytes((0, 90, 0, 0)) \
        + bytes((90, 0, 0, 255)) + bytes((32, 32, 32, 255))
    assert bars.lit_map(pixels, 5) == bytes((0, 1, 1, 1, 0))


@pytest.mark.parametrize(("box", "found"), [
    ({}, (0, 0, 0, 0)),                                     # the picture fills the frame
    ({"top": 12, "bottom": 12}, (0, 0, 12, 12)),            # letterbox
    ({"left": 12, "right": 12}, (12, 12, 0, 0)),            # pillarbox
    ({"left": 5, "right": 5, "top": 20, "bottom": 20}, (5, 5, 20, 20)),
    ({"top": 12, "bottom": 13}, (0, 0, 12, 13)),            # a row off centre is centred
])
def test_the_bars_of_a_bright_frame(box, found):
    assert measured(picture(**box)) == found


def test_limited_range_black_is_black():
    assert measured(picture(top=12, bottom=12, black=16)) == (0, 0, 12, 12)
    assert measured(picture(top=12, bottom=12, black=24)) == (0, 0, 12, 12)


def test_a_black_frame_proves_nothing():
    assert measured(picture(level=0)) is None


def test_a_dark_scene_with_a_bright_object_proves_nothing():
    rows = picture(level=0)
    for y in range(40, 60):
        rows[y][45:55] = [200] * 10                         # no solid line anywhere
    assert measured(rows) is None


def test_a_dim_picture_edge_proves_nothing():
    rows = picture(top=12, bottom=12)
    for y in range(12, 30):
        rows[y] = [0] * SIZE                                # the top of the picture is dark
        rows[y][50:60] = [200] * 10
    assert measured(rows) is None


def test_a_subtitle_in_the_bar_proves_nothing():
    rows = picture(top=12, bottom=12)
    rows[94][40:55] = [255] * 15                            # burned into the bottom bar
    assert measured(rows) is None


def test_bars_of_different_size_prove_nothing():
    assert measured(picture(top=12, bottom=20)) is None
    assert measured(picture(left=5, right=20)) is None


def test_a_dark_side_of_the_picture_proves_nothing():
    rows = picture()
    for y in range(SIZE):
        if not 40 <= y < 50:
            rows[y][:20] = [0] * 20                         # lit on the left in ten rows only
    assert measured(rows) is None


def test_a_soft_edge_counts_from_its_first_lit_row():
    rows = picture(top=12, bottom=12)
    rows[11][45:55] = [200] * 10                            # the scaler's blur
    rows[88][45:55] = [200] * 10
    assert measured(rows) == (0, 0, 11, 11)


# --- A run of frames ----------------------------------------------------------

SCOPE = (0, 0, 46, 46)
FULL  = (0, 0, 0, 0)


def test_bars_stand_once_two_frames_agree():
    tracker = BarTracker()
    tracker.update(SCOPE)
    assert tracker.bars is None
    tracker.update(SCOPE)
    assert tracker.bars == SCOPE


def test_frames_that_prove_nothing_change_nothing():
    tracker = BarTracker()
    tracker.update(None)
    assert tracker.bars is None
    tracker.update(SCOPE)
    tracker.update(None)                                    # does not count against it
    tracker.update((0, 0, 47, 45))                          # the same to within a pixel
    assert tracker.bars == SCOPE
    tracker.update(None)
    assert tracker.bars == SCOPE


def test_a_pixel_of_jitter_keeps_the_confirmed_bars():
    tracker = BarTracker()
    tracker.update(SCOPE)
    tracker.update(SCOPE)
    tracker.update((0, 0, 47, 46))
    tracker.update((0, 0, 47, 46))
    assert tracker.bars == SCOPE


def test_a_change_of_framing_needs_two_frames_too():
    tracker = BarTracker()
    tracker.update(SCOPE)
    tracker.update(SCOPE)
    tracker.update(FULL)                                    # the picture opens up
    assert tracker.bars == SCOPE
    tracker.update(FULL)
    assert tracker.bars == FULL


def test_a_single_stray_measurement_is_dropped():
    tracker = BarTracker()
    tracker.update(SCOPE)
    tracker.update(SCOPE)
    tracker.update(FULL)
    tracker.update(SCOPE)                                   # back: the candidate is gone
    tracker.update(FULL)
    assert tracker.bars == SCOPE
    tracker.update((0, 0, 20, 20))                          # another candidate takes over
    tracker.update((0, 0, 20, 20))
    assert tracker.bars == (0, 0, 20, 20)


def test_a_reset_forgets_bars_and_candidate():
    tracker = BarTracker()
    tracker.update(SCOPE)
    tracker.update(SCOPE)
    tracker.update(FULL)
    tracker.reset()
    assert tracker.bars is None
    tracker.update(FULL)
    assert tracker.bars is None


# --- Into coded pixels --------------------------------------------------------

def test_bars_scale_to_the_coded_frame():
    assert bars.scaled((0, 0, 46, 46), (640, 360), (3840, 2160)) == (0, 0, 276, 276)
    assert bars.scaled((80, 80, 0, 0), (640, 360), (1920, 1080)) == (240, 240, 0, 0)


def test_bars_are_written_like_l5_offsets():
    assert bars.format_offsets((0, 0, 276, 276)) == "0 | 0 | 276 | 276"
