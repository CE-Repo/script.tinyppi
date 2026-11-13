# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Find the black bars in a captured video frame.

Kodi reports the coded frame, so a letterboxed film reads 1.78:1.  Dolby
Vision declares its bars in the RPU (L5); everything else has to be measured
from the picture.  ``measure`` looks at one frame, ``BarTracker`` decides
what a run of frames proves.

A dark frame cannot tell a black bar from dark picture, so a frame only
counts when both edges of an axis are plainly lit and sit at the same
distance from the frame's border.  Any other frame says nothing and the last
confirmed bars stand.

Free of Kodi imports; ``info.barscan`` feeds it the frames.
"""

# Left, right, top, bottom, in pixels of the frame they were measured in.
Bars = tuple[int, int, int, int]

# The capture is 8-bit BGRA.  Black is 0 in full range and 16 in limited
# range; a channel has to be clearly above both to count as lit.
LIT_ABOVE = 32
_LIT = bytes(1 if value > LIT_ABOVE else 0 for value in range(256))

# Share of a line (row or column), in percent, that has to be lit for it to
# hold picture at all, and for it to be a solid picture edge.  The first
# ignores stray pixels; the second is what a dark scene with one bright
# object, or a subtitle burned into a bar, does not reach.
_SOME_LIT  = 1
_SOLID_LIT = 25

# Matching frames needed before the bars change.
CONFIRM_FRAMES = 2

# The capture: wide enough to tell 2.35:1 from 2.39:1 (four rows apart at
# 360), small enough to read in a few milliseconds.  The height follows the
# video's own ratio so the frame is not distorted.
CAPTURE_WIDTH      = 640
_DEFAULT_HEIGHT    = 360
_MIN_HEIGHT        = 180
_MAX_HEIGHT        = 640


def capture_size(aspect: float) -> tuple[int, int]:
    """Return the capture size for a video of display ratio *aspect*."""
    if aspect <= 0:
        return CAPTURE_WIDTH, _DEFAULT_HEIGHT
    height = round(CAPTURE_WIDTH / aspect / 2) * 2
    return CAPTURE_WIDTH, min(max(height, _MIN_HEIGHT), _MAX_HEIGHT)


def lit_map(image: bytes | bytearray, pixels: int) -> bytes:
    """Return one byte per pixel of a BGRA *image*: 1 where it is lit.

    A pixel is lit when any colour channel is above black.  The channels are
    combined as big integers, so no Python code runs per pixel.
    """
    combined = 0
    for channel in range(3):
        combined |= int.from_bytes(image[channel::4].translate(_LIT), "big")
    return combined.to_bytes(pixels, "big")


def _first(counts: list[int], need: int) -> int | None:
    """Return the index of the first count of at least *need*, or None."""
    return next((index for index, count in enumerate(counts) if count >= need), None)


def _axis_bars(counts: list[int], across: int) -> tuple[int, int] | None:
    """Return the bars before and after the picture along one axis.

    *counts* holds the lit pixels of each line, *across* a line's length.
    None when the frame does not prove them: no solid line, picture outside
    the solid part (a dark scene, a subtitle in the bar), or bars of
    different size (the picture is taken to be centred).
    """
    solid = max(1, across * _SOLID_LIT // 100)
    some  = max(1, across * _SOME_LIT // 100)
    lines = len(counts)
    backwards = counts[::-1]

    solid_before = _first(counts, solid)
    solid_after  = _first(backwards, solid)
    if solid_before is None or solid_after is None:
        return None
    # A solid line is lit, so these two are always found.
    before = _first(counts, some) or 0
    after  = _first(backwards, some) or 0

    blur = max(1, lines // 200)
    if solid_before - before > blur or solid_after - after > blur:
        return None
    if abs(before - after) > max(2, lines // 100):
        return None
    return before, after


def measure(image: bytes | bytearray, width: int, height: int) -> Bars | None:
    """Return the black bars of a *width* x *height* BGRA frame.

    None when the frame does not prove them (see ``_axis_bars``).
    """
    lit = lit_map(image, width * height)

    rows = [lit.count(1, start, start + width)
            for start in range(0, width * height, width)]
    vertical = _axis_bars(rows, width)
    if vertical is None:
        return None

    columns = [lit[column::width].count(1) for column in range(width)]
    horizontal = _axis_bars(columns, height)
    if horizontal is None:
        return None
    return (*horizontal, *vertical)


def _same(first: Bars, second: Bars) -> bool:
    """Return whether two measurements agree to within a pixel per edge."""
    return all(abs(one - other) <= 1 for one, other in zip(first, second, strict=True))


class BarTracker:
    """The bars a run of frames has confirmed.

    A measurement replaces the confirmed bars only after ``CONFIRM_FRAMES``
    frames agree on it; frames that prove nothing in between do not count
    against it.  A measurement within a pixel of the confirmed bars keeps
    them, so the reading does not flicker.
    """

    def __init__(self) -> None:
        self.bars: Bars | None = None
        self._candidate: Bars | None = None
        self._seen = 0

    def reset(self) -> None:
        """Forget everything (a new title)."""
        self.bars = None
        self._candidate = None
        self._seen = 0

    def update(self, measured: Bars | None) -> None:
        """Take in one frame's measurement (None: the frame proved nothing)."""
        if measured is None:
            return
        if self.bars is not None and _same(measured, self.bars):
            self._candidate = None
            self._seen = 0
            return
        if self._candidate is not None and _same(measured, self._candidate):
            self._seen += 1
        else:
            self._candidate = measured
            self._seen = 1
        if self._seen >= CONFIRM_FRAMES:
            self.bars = self._candidate
            self._candidate = None
            self._seen = 0


def scaled(bars: Bars, measured_in: tuple[int, int], target: tuple[int, int]) -> Bars:
    """Return *bars* measured in a frame of one size as pixels of another."""
    from_w, from_h = measured_in
    to_w, to_h = target
    left, right, top, bottom = bars
    return (round(left * to_w / from_w), round(right * to_w / from_w),
            round(top * to_h / from_h), round(bottom * to_h / from_h))


def format_offsets(bars: Bars) -> str:
    """Return *bars* in the RPU's ``L | R | T | B`` notation."""
    return " | ".join(str(bar) for bar in bars)
