# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Black bars measured from a captured frame (info/bars.py)."""

import pytest

from info import bars
from info.bars import BarTracker, measure, measure_dark

SIZE  = 100         # frames are 200 x 100, so rows read as percent
WIDTH = 200


def picture(left=0, right=0, top=0, bottom=0, level=200, black=0):
    """A BGRA frame with a lit picture inside the given bars, as rows of levels."""
    rows = []
    for y in range(SIZE):
        inside_y = top <= y < SIZE - bottom
        rows.append([level if inside_y and left <= x < WIDTH - right else black
                     for x in range(WIDTH)])
    return rows


def image(rows):
    """The BGRA bytes of *rows* (grey levels, opaque)."""
    return bytearray(b"".join(bytes((v, v, v, 255)) for row in rows for v in row))


def measured(rows):
    return measure(image(rows), WIDTH, SIZE)


# --- The capture size ---------------------------------------------------------

@pytest.mark.parametrize(("aspect", "size"), [
    (0.0, (480, 270)),                      # unknown: 16:9
    (1.7778, (480, 270)),
    (2.39, (480, 200)),                     # an encode cropped to the picture
    (1.3333, (480, 360)),
    (0.5, (480, 480)),                      # held to a sane height
    (10.0, (480, 136)),
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
        rows[y] = [0] * WIDTH                               # the top of the picture is dark
        rows[y][50:60] = [200] * 10
    assert measured(rows) is None


def test_a_subtitle_in_the_bar_proves_nothing():
    rows = picture(top=12, bottom=12)
    rows[94][40:55] = [255] * 15                            # burned into the bottom bar
    assert measured(rows) is None


def test_bars_of_different_size_prove_nothing():
    assert measured(picture(top=12, bottom=20)) is None
    assert measured(picture(left=5, right=60)) is None


def test_lit_content_with_black_on_all_sides_is_no_picture():
    # A title card, a logo, credits: no film is boxed on both axes.
    assert measured(picture(left=50, right=50, top=30, bottom=30)) is None
    assert measured(picture(left=10, right=10, top=12, bottom=12)) is None
    # A bar of a line or two on the other axis is the scaler's, not a box.
    assert measured(picture(left=2, right=2, top=12, bottom=12)) == (2, 2, 12, 12)


def test_a_band_no_film_is_shaped_like_is_no_picture():
    assert measured(picture(top=20, bottom=20)) is None     # 3.33:1, a line of text
    assert measured(picture(left=60, right=60)) is None     # 0.8:1
    assert measured(picture(top=14, bottom=14)) == (0, 0, 14, 14)   # 2.78:1, still a film


def test_the_ratio_of_the_picture_inside_the_bars():
    assert bars.picture_ratio((0, 0, 46, 46), (640, 360)) == pytest.approx(2.39, abs=0.005)
    assert bars.picture_ratio((80, 80, 0, 0), (640, 360)) == pytest.approx(1.33, abs=0.005)
    assert not bars.has_bars((0, 0, 1, 0)) and bars.has_bars((0, 0, 46, 46))


def dark_on_the_right(rows, top, bottom, lit_until, glint=None):
    """Darken the right of the picture, but for a glint at one column."""
    for y in range(top, SIZE - bottom):
        rows[y][lit_until:] = [0] * (WIDTH - lit_until)
        if glint is not None and 40 <= y < 50:
            rows[y][glint] = 200
    return rows


def test_a_dark_side_of_a_letterboxed_picture_still_shows_its_bars():
    # A cockpit: bright on the left, dark on the right but for a few lights.
    rows = dark_on_the_right(picture(top=12, bottom=12), 12, 12, lit_until=120, glint=170)
    assert measured(rows) == (0, 0, 12, 12)
    rows = dark_on_the_right(picture(top=12, bottom=12), 12, 12, lit_until=120, glint=199)
    assert measured(rows) == (0, 0, 12, 12)


def test_a_picture_lit_on_one_half_only_proves_nothing():
    rows = dark_on_the_right(picture(top=12, bottom=12), 12, 12, lit_until=120)
    assert measured(rows) is None


def test_a_dark_side_of_a_full_frame_needs_light_at_the_border():
    rows = dark_on_the_right(picture(), 0, 0, lit_until=120, glint=199)
    assert measured(rows) == (0, 0, 0, 0)
    rows = dark_on_the_right(picture(), 0, 0, lit_until=120, glint=170)
    assert measured(rows) is None                           # could be anything


def test_an_axis_with_next_to_no_light_is_not_free_of_bars():
    # Each column holds less than the share that counts as picture.
    assert bars._unbarred([1, 0, 1, 0, 1], across=300, boxed=True) is None


def test_a_subtitle_in_the_bar_is_not_taken_for_a_full_frame():
    rows = picture(top=12, bottom=12)
    rows[99][40:55] = [255] * 15                            # at the very border
    assert measured(rows) is None
    rows[3][40:55] = [255] * 15                             # and a logo in the other bar
    assert measured(rows) is None


def test_a_soft_edge_counts_from_its_first_lit_row():
    rows = picture(top=12, bottom=12)
    rows[11][45:55] = [200] * 10                            # the scaler's blur
    rows[88][45:55] = [200] * 10
    assert measured(rows) == (0, 0, 11, 11)


# --- Bars the title has shown before ------------------------------------------

def again(rows, earlier=(0, 0, 12, 12)):
    return bars.shows_again(bars.line_counts(image(rows), WIDTH, SIZE), WIDTH, SIZE, earlier)


def dim_edge(rows, edge_rows):
    """Darken the picture in *edge_rows*."""
    for y in edge_rows:
        rows[y] = [0] * WIDTH
    return rows


def test_earlier_bars_show_again_with_one_lit_edge():
    dark_top = dim_edge(picture(top=12, bottom=12), range(12, 40))
    assert measured(dark_top) is None                       # no proof of new bars
    assert again(dark_top)
    assert again(dim_edge(picture(top=12, bottom=12), range(60, 88)))   # a dark bottom
    assert again(picture(top=12, bottom=12))


def test_earlier_bars_need_an_edge_and_black():
    both_dark = dim_edge(picture(top=12, bottom=12), [*range(12, 40), *range(60, 88)])
    assert not again(both_dark)                             # the picture could be anything
    assert not again(picture(level=0))                      # a black frame
    assert not again(picture())                             # picture in the bars
    assert not again(picture(top=6, bottom=12))
    assert not again(dim_edge(picture(top=12, bottom=12), range(12, 40)), (0, 0, 20, 20))


def test_without_the_lit_edge_black_bars_and_any_picture_are_enough():
    both_dark = dim_edge(picture(top=12, bottom=12), [*range(12, 40), *range(60, 88)])
    lenient = bars.line_counts(image(both_dark), WIDTH, SIZE)
    assert bars.shows_again(lenient, WIDTH, SIZE, (0, 0, 12, 12), lit_edge=False)
    small = bars.line_counts(image(picture(left=60, right=60, top=30, bottom=30)), WIDTH, SIZE)
    assert bars.shows_again(small, WIDTH, SIZE, (0, 0, 12, 12), lit_edge=False)
    for rows in (picture(level=0), picture(), picture(top=6, bottom=12)):
        lines = bars.line_counts(image(rows), WIDTH, SIZE)
        assert not bars.shows_again(lines, WIDTH, SIZE, (0, 0, 12, 12), lit_edge=False)


def test_bars_that_crop_a_taller_picture():
    assert bars.crops((0, 0, 46, 46), (0, 0, 0, 0))
    assert bars.crops((0, 0, 46, 46), (0, 0, 9, 9))
    assert not bars.crops((0, 0, 0, 0), (0, 0, 46, 46))
    assert not bars.crops((0, 0, 46, 46), (0, 0, 46, 46))
    assert not bars.crops((0, 0, 46, 46), (60, 60, 0, 0))


def test_earlier_bars_need_the_picture_to_run_on_along_the_other_axis():
    assert not again(picture(left=60, right=60, top=12, bottom=12))     # a title card


def test_earlier_pillar_bars_show_again_too():
    rows = picture(left=24, right=24)
    for y in range(SIZE):
        rows[y][24:80] = [0] * 56                           # dark on the left
    assert again(rows, (24, 24, 0, 0))
    assert not again(rows, (0, 0, 0, 0))                    # the full frame proves itself
    assert not again(rows, (24, 24, 12, 12))


# --- A dark frame -------------------------------------------------------------

def dark_film(top=12, bottom=12, left=0, right=0, bar=16, black=19):
    """A film's black scene between flat bars, with a bright title in it."""
    rows = picture(left, right, top, bottom, level=black, black=bar)
    for y in range(45, 55):
        rows[y][80:120] = [230] * 40
    return rows


def dark(rows):
    return measure_dark(image(rows), WIDTH, SIZE)


def test_a_films_black_is_told_from_the_bars():
    assert measured(dark_film()) is None                    # too dark for the first look
    assert dark(dark_film()) == (0, 0, 12, 12)
    assert dark(dark_film(bar=0, black=3)) == (0, 0, 12, 12)            # full range
    assert dark(dark_film(top=0, bottom=0, left=24, right=24)) == (24, 24, 0, 0)


def test_grain_is_enough():
    rows = dark_film(black=16)
    for y in range(12, 88):
        rows[y][::3] = [20] * len(rows[y][::3])             # a third of the pixels
        rows[y][-1] = 20
    assert dark(rows) == (0, 0, 12, 12)


def test_black_as_flat_as_the_bars_proves_nothing():
    assert dark(dark_film(black=16)) is None                # only the title is left
    assert dark(dark_film(black=18)) is None                # within the bar's rounding


def test_a_dark_frame_without_a_flat_border_proves_nothing():
    assert dark(dark_film(top=0, bottom=0)) is None         # the picture fills the frame
    rows = dark_film()
    rows[0][30] = 40                                        # something in the bar
    assert dark(rows) is None
    assert dark(dark_film(bar=60, black=70)) is None        # grey is no bar


# --- A run of frames ----------------------------------------------------------

SCOPE = (0, 0, 46, 46)
FULL  = (0, 0, 0, 0)
HOLD  = bars.CONFIRM_SECONDS + 0.01     # clear of float rounding


def confirmed(tracker, measured, at=0.0):
    """Have *measured* last its hold time from *at* on."""
    tracker.update(measured, at)
    tracker.update(measured, at + HOLD)


def test_bars_stand_once_they_lasted():
    tracker = BarTracker()
    tracker.update(SCOPE, 10.0)
    assert tracker.bars is None and tracker.pending
    tracker.update(SCOPE, 10.0 + HOLD / 2)                  # too soon, however many frames
    tracker.update(SCOPE, 10.0 + HOLD / 2)
    assert tracker.bars is None
    tracker.update(SCOPE, 10.0 + HOLD)
    assert tracker.bars == SCOPE and not tracker.pending


def test_a_measurement_can_be_given_a_longer_hold():
    tracker = BarTracker()
    tracker.update(SCOPE, 0.0, hold=bars.DARK_CONFIRM_SECONDS)
    tracker.update(SCOPE, bars.DARK_CONFIRM_SECONDS / 2)
    assert tracker.bars is None
    tracker.update(SCOPE, bars.DARK_CONFIRM_SECONDS)
    assert tracker.bars == SCOPE


def test_frames_that_prove_nothing_change_nothing():
    tracker = BarTracker()
    tracker.update(None, 0.0)
    assert tracker.bars is None
    tracker.update(SCOPE, 1.0)
    tracker.update(None, 1.1)                               # does not count against it
    tracker.update((0, 0, 47, 45), 1.0 + HOLD)              # the same to within a pixel
    assert tracker.bars == SCOPE
    tracker.update(None, 2.0)
    assert tracker.bars == SCOPE


def test_a_pixel_of_jitter_keeps_the_confirmed_bars():
    tracker = BarTracker()
    confirmed(tracker, SCOPE)
    confirmed(tracker, (0, 0, 47, 46), at=1.0)
    assert tracker.bars == SCOPE


def test_a_change_of_framing_has_to_last_too():
    tracker = BarTracker()
    confirmed(tracker, SCOPE)
    tracker.update(FULL, 1.0)                               # the picture opens up
    assert tracker.bars == SCOPE
    tracker.update(FULL, 1.0 + HOLD)
    assert tracker.bars == FULL


def test_a_stray_measurement_is_dropped():
    tracker = BarTracker()
    confirmed(tracker, SCOPE)
    tracker.update(FULL, 1.0)
    tracker.update(SCOPE, 1.1)                              # back: the candidate is gone
    tracker.update(FULL, 1.0 + HOLD)                        # starts over
    assert tracker.bars == SCOPE
    tracker.update((0, 0, 20, 20), 2.0)                     # another candidate takes over
    tracker.update((0, 0, 20, 20), 2.0 + HOLD)
    assert tracker.bars == (0, 0, 20, 20)


def test_the_tracker_remembers_the_framings_of_its_title():
    tracker = BarTracker()
    confirmed(tracker, SCOPE)
    assert tracker.shown == [SCOPE] and tracker.earlier() == []
    confirmed(tracker, FULL, at=1.0)
    assert tracker.earlier() == [SCOPE]
    confirmed(tracker, (0, 0, 47, 46), at=2.0)              # the same to within a pixel
    assert tracker.bars == SCOPE and tracker.shown == [FULL, SCOPE]
    assert tracker.earlier() == [FULL]
    confirmed(tracker, (0, 0, 9, 9), at=3.0)
    assert tracker.earlier() == [SCOPE, FULL]               # the last shown first
    tracker.reset()
    assert tracker.shown == []


def test_a_reset_forgets_bars_and_candidate():
    tracker = BarTracker()
    confirmed(tracker, SCOPE)
    tracker.update(FULL, 1.0)
    tracker.reset()
    assert tracker.bars is None and not tracker.pending
    tracker.update(FULL, 1.0 + HOLD)
    assert tracker.bars is None


# --- Into coded pixels --------------------------------------------------------

def test_bars_scale_to_the_coded_frame():
    assert bars.scaled((0, 0, 46, 46), (640, 360), (3840, 2160)) == (0, 0, 276, 276)
    assert bars.scaled((80, 80, 0, 0), (640, 360), (1920, 1080)) == (240, 240, 0, 0)


def test_bars_are_written_like_l5_offsets():
    assert bars.format_offsets((0, 0, 276, 276)) == "0 | 0 | 276 | 276"
