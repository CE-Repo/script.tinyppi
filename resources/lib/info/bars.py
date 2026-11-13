# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Find the black bars in a captured video frame.

Kodi reports the coded frame, so a letterboxed film reads 1.78:1.  Dolby
Vision declares its bars in the RPU (L5); everything else has to be measured
from the picture.  ``measure`` looks at one frame, ``BarTracker`` decides
what a run of frames proves.

A dark frame cannot tell a black bar from dark picture, so a frame only
counts when both edges of an axis are plainly lit and sit at the same
distance from the frame's border.  One such axis is enough when the picture
is seen to run on along the other, so a scene with a dark side still shows
its bars.  A title card, a logo or credits on black
look like a small picture; they are told apart by bars on all four sides or
a shape no film has, and the scanner only takes ratios films are made in.
Any such frame says nothing and the last confirmed bars stand.

A title that opens on a minute of black would show nothing for as long.
``measure_dark`` reads such frames: a bar is one flat value, while a film's
black is rarely as black or as even.  It is the weaker proof, so the scanner
only asks it until a title has its first confirmed bars.

A film that changes its framing (IMAX scenes) returns to bars it has shown
before.  Those need less proof: ``shows_again`` takes the earlier bars for
shown when they are black and the picture is lit at one of their edges, so a
scene with a dark top or bottom does not hold the change back.

Free of Kodi imports; ``info.barscan`` feeds it the frames.
"""

import functools

# Left, right, top, bottom, in pixels of the frame they were measured in.
Bars = tuple[int, int, int, int]

# The lit pixels of each row and of each column of a frame.
Lines = tuple[list[int], list[int]]

# The capture is 8-bit BGRA.  Black is 0 in full range and 16 in limited
# range; a channel has to be clearly above both to count as lit.
LIT_ABOVE = 32
_LIT = bytes(1 if value > LIT_ABOVE else 0 for value in range(256))

# For ``measure_dark``: how far the channels of a frame's border lines may
# differ and still be one flat bar, and how far above the bar a channel has
# to be to count as picture.
_FLAT_WITHIN = 1
_ABOVE_BAR   = 2

# Share of a line (row or column), in percent, that has to be lit for it to
# hold picture at all, and for it to be a solid picture edge.  The first
# ignores stray pixels; the second is what a dark scene with one bright
# object, or a subtitle burned into a bar, does not reach.
_SOME_LIT  = 1
_SOLID_LIT = 25

# Share of an axis, in percent, that lit picture has to span for the axis to
# count as free of bars while the other axis has proven ones.
_SPAN_OF_BOXED = 75

# Seconds a measurement has to last before the bars change: three frames at
# the scanner's pace, a little short of two intervals so that a frame a
# moment early still counts.
CONFIRM_SECONDS = 0.09
# For a measurement of a dark frame (``measure_dark``).
DARK_CONFIRM_SECONDS = 1.0

# The picture ratios bars can leave: Academy to Ultra Panavision, with some
# room.  A lit band outside of it (a horizon in a dark scene, a line of
# text) is no picture.
_NARROWEST = 1.15
_WIDEST    = 2.85

# The capture: as small as still tells 2.35:1 from 2.39:1 (three rows apart
# at 270), so it can be read twenty times a second.  The height follows the
# video's own ratio so the frame is not distorted.
CAPTURE_WIDTH      = 480
_DEFAULT_HEIGHT    = 270
_MIN_HEIGHT        = 136
_MAX_HEIGHT        = 480


def capture_size(aspect: float) -> tuple[int, int]:
    """Return the capture size for a video of display ratio *aspect*."""
    if aspect <= 0:
        return CAPTURE_WIDTH, _DEFAULT_HEIGHT
    height = round(CAPTURE_WIDTH / aspect / 2) * 2
    return CAPTURE_WIDTH, min(max(height, _MIN_HEIGHT), _MAX_HEIGHT)


def lit_map(image: bytes | bytearray, pixels: int, above: int = LIT_ABOVE) -> bytes:
    """Return one byte per pixel of a BGRA *image*: 1 where it is lit.

    A pixel is lit when any colour channel is over *above*.  The channels
    are combined as big integers, so no Python code runs per pixel.
    """
    table = _LIT if above == LIT_ABOVE else _lit_table(above)
    combined = 0
    for channel in range(3):
        combined |= int.from_bytes(image[channel::4].translate(table), "big")
    return combined.to_bytes(pixels, "big")


@functools.cache
def _lit_table(above: int) -> bytes:
    """Return the translation table that marks the values over *above*."""
    return bytes(1 if value > above else 0 for value in range(256))


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
    return bars_of(line_counts(image, width, height), width, height)


def line_counts(image: bytes | bytearray, width: int, height: int,
                above: int = LIT_ABOVE) -> Lines:
    """Return the lit pixels of each row and each column of a BGRA frame."""
    lit = lit_map(image, width * height, above)
    rows = [lit.count(1, start, start + width)
            for start in range(0, width * height, width)]
    columns = [lit[column::width].count(1) for column in range(width)]
    return rows, columns


def measure_dark(image: bytes | bytearray, width: int, height: int) -> Bars | None:
    """Return the black bars of a frame too dark for ``measure``.

    The frame's outermost lines, top and bottom or left and right, have to
    be one flat, dark value: the bar.  Whatever is above it counts as
    picture, so the grain or the lifted black of a film's dark scene shows
    where the picture ends.  None when the frame has no such border, when
    its black is as flat as the bars, or when no bars come of it.
    """
    row = width * 4
    last = row - 4
    top_and_bottom = image[:row] + image[-row:]
    borders = (
        # The first and last row, then the first and last column, colours only.
        b"".join(top_and_bottom[channel::4] for channel in range(3)),
        b"".join(image[start + channel::row] for start in (0, last) for channel in range(3)),
    )
    for colours in borders:
        level = _flat_level(colours)
        if level is None:
            continue
        lines = line_counts(image, width, height, level + _ABOVE_BAR)
        found = bars_of(lines, width, height)
        if found is not None and has_bars(found):
            return found
    return None


def _flat_level(colours: bytes) -> int | None:
    """Return the value of *colours* that are one flat black, or None."""
    low, high = min(colours), max(colours)
    if high - low > _FLAT_WITHIN or high > LIT_ABOVE:
        return None
    return high


def bars_of(lines: Lines, width: int, height: int) -> Bars | None:
    """Return the bars the lit pixels of a frame's *lines* prove, or None."""
    rows, columns = lines
    vertical = _axis_bars(rows, width)
    horizontal = _axis_bars(columns, height)

    # One axis is enough when the picture is seen to run on along the other:
    # a scene with a dark side still shows its bars above and below.
    if vertical is None and horizontal is not None:
        vertical = _unbarred(rows, width, boxed=max(horizontal) > _edge_slack(width))
    elif horizontal is None and vertical is not None:
        horizontal = _unbarred(columns, height, boxed=max(vertical) > _edge_slack(height))
    if vertical is None or horizontal is None:
        return None

    found = (*horizontal, *vertical)
    return found if _is_picture(found, width, height) else None


def shows_again(lines: Lines, width: int, height: int, earlier: Bars,
                lit_edge: bool = True) -> bool:
    """Return whether a frame shows the *earlier* bars of its title again.

    Bars the title has shown before need less proof than new ones: they have
    to be black, the picture has to be lit right at one of them (not at
    both, so a dark top or bottom does not matter) and to run on along the
    other axis.  Only for bars on one axis; the full frame proves itself.

    Without *lit_edge* black bars and any picture between them are enough.
    That is for a picture that has been taller (an IMAX scene): once
    nothing shows where the bars were, the title is taken to be back.
    """
    axis = _barred_axis(lines, width, height, earlier)
    if axis is None:
        return False
    barred, across, before, after, other, length = axis

    some = max(1, across * _SOME_LIT // 100)
    first = _first(barred, some)
    last  = _first(barred[::-1], some)
    if first is None or last is None:
        return False
    # Black bars, to within the line the scaler blurs ...
    if first < before - 1 or last < after - 1:
        return False
    if not lit_edge:
        return True
    # ... and picture right at one of them.
    if first > before + 1 and last > after + 1:
        return False
    return _unbarred(other, length, boxed=True) is not None


def _barred_axis(lines: Lines, width: int, height: int, bars: Bars,
                 ) -> tuple[list[int], int, int, int, list[int], int] | None:
    """Return the one axis *bars* lie on, or None when it is not just one.

    As the lines of that axis and their length, the bar before and after
    the picture, and the lines of the other axis and their length.
    """
    rows, columns = lines
    left, right, top, bottom = bars
    letterboxed = max(top, bottom) > _edge_slack(height)
    pillarboxed = max(left, right) > _edge_slack(width)
    if letterboxed and not pillarboxed:
        return rows, width, top, bottom, columns, height
    if pillarboxed and not letterboxed:
        return columns, height, left, right, rows, width
    return None


def _unbarred(counts: list[int], across: int, boxed: bool) -> tuple[int, int] | None:
    """Return ``(0, 0)`` when an axis without proven bars has none, else None.

    That is when lit picture reaches both borders of the frame.  Where the
    other axis has proven bars (*boxed*), most of the way is enough: a film
    has bars on one axis only, so a dark side is picture, not a bar.
    """
    some = max(1, across * _SOME_LIT // 100)
    lines = len(counts)
    before = _first(counts, some)
    after  = _first(counts[::-1], some)
    if before is None or after is None:
        return None
    if before <= 1 and after <= 1:
        return 0, 0
    if boxed and lines - before - after >= lines * _SPAN_OF_BOXED // 100:
        return 0, 0
    return None


def _is_picture(bars: Bars, width: int, height: int) -> bool:
    """Return whether what *bars* leave of the frame can be a film's picture.

    A film is letterboxed or pillarboxed, not both: lit content with black
    on all four sides is a title card, a logo or credits.  With bars on one
    axis the picture has to keep a ratio films are made in.
    """
    letterboxed = max(bars[2:]) > _edge_slack(height)
    pillarboxed = max(bars[:2]) > _edge_slack(width)
    if letterboxed and pillarboxed:
        return False
    if not letterboxed and not pillarboxed:
        return True
    return _NARROWEST <= picture_ratio(bars, (width, height)) <= _WIDEST


def _edge_slack(lines: int) -> int:
    """Return the bar size, in lines, that still counts as no bar."""
    return max(2, lines // 100)


def picture_ratio(bars: Bars, size: tuple[int, int]) -> float:
    """Return the ratio of the picture *bars* leave in a frame of *size*.

    The capture is not distorted (see ``capture_size``), so its pixels are
    square.
    """
    left, right, top, bottom = bars
    width, height = size
    return (width - left - right) / max(1, height - top - bottom)


def crops(bars: Bars, other: Bars) -> bool:
    """Return whether *bars* leave less picture than *other* on no side more."""
    return bars != other and all(bar >= than for bar, than in zip(bars, other, strict=True))


def has_bars(bars: Bars) -> bool:
    """Return whether *bars* crop the frame at all."""
    return max(bars) > 1


def _same(first: Bars, second: Bars) -> bool:
    """Return whether two measurements agree to within a pixel per edge."""
    return all(abs(one - other) <= 1 for one, other in zip(first, second, strict=True))


class BarTracker:
    """The bars a run of frames has confirmed.

    A measurement replaces the confirmed bars only after frames have agreed
    on it for its hold time; frames that prove nothing in between do not
    count against it, a frame that measures something else starts over.  A
    measurement within a pixel of the confirmed bars keeps them, so the
    reading does not flicker.
    """

    def __init__(self) -> None:
        self.bars: Bars | None = None
        # Every framing confirmed for this title, the current one included.
        self.shown: list[Bars] = []
        self._candidate: Bars | None = None
        self._since = 0.0
        self._hold = 0.0

    @property
    def pending(self) -> bool:
        """Return whether a measurement waits for a frame to confirm it."""
        return self._candidate is not None

    def reset(self) -> None:
        """Forget everything (a new title)."""
        self.bars = None
        self.shown = []
        self._candidate = None

    def earlier(self) -> list[Bars]:
        """Return the framings the title has shown other than the current.

        The one it showed last comes first.
        """
        return [bars for bars in reversed(self.shown) if bars != self.bars]

    def update(self, measured: Bars | None, now: float,
               hold: float = CONFIRM_SECONDS) -> None:
        """Take in the measurement of the frame at *now* (seconds).

        None: the frame proved nothing.  *hold* is how long this measurement
        has to last before it counts.
        """
        if measured is None:
            return
        if self.bars is not None and _same(measured, self.bars):
            self._candidate = None
            return
        if self._candidate is None or not _same(measured, self._candidate):
            self._candidate = measured
            self._since = now
            self._hold = hold
            return
        if now - self._since >= self._hold:
            self.bars = self._adopted(self._candidate)
            self._candidate = None

    def _adopted(self, confirmed: Bars) -> Bars:
        """Return *confirmed* as the title showed it before, or note it."""
        for bars in self.shown:
            if _same(bars, confirmed):
                confirmed = bars
                self.shown.remove(bars)
                break
        self.shown.append(confirmed)                # the last shown at the end
        return confirmed


def _centred(before: int, after: int) -> tuple[float, float]:
    """Return the two bars of an axis as equal ones when a line apart.

    The picture is centred (see ``_axis_bars``), so bars that differ by one
    captured line are an edge that falls inside a line: a UHD film's 276
    rows are 34.5 lines of the capture and measure 35 and 34.  Half the sum
    is the bar; scaled it would read 280 and 272.
    """
    if abs(before - after) != 1:
        return before, after
    half = (before + after) / 2
    return half, half


def scaled(bars: Bars, measured_in: tuple[int, int], target: tuple[int, int]) -> Bars:
    """Return *bars* measured in a frame of one size as pixels of another.

    Bars a captured line apart come out equal (see ``_centred``).
    """
    from_w, from_h = measured_in
    to_w, to_h = target
    left, right = _centred(*bars[:2])
    top, bottom = _centred(*bars[2:])
    return (round(left * to_w / from_w), round(right * to_w / from_w),
            round(top * to_h / from_h), round(bottom * to_h / from_h))


def format_offsets(bars: Bars) -> str:
    """Return *bars* in the RPU's ``L | R | T | B`` notation."""
    return " | ".join(str(bar) for bar in bars)
