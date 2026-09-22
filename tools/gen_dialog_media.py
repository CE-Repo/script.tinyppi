#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Draw the media files the VS10 dialog's layouts need.

The wheel arranges the dialog's choices in the segments of a ring. A skin
cannot turn one texture several ways, so every segment is its own pre-rotated
texture - and the dialog offers three, four or a single choice depending on
what the stream is, so every segment count needs its own set.

The shapes are white and fully opaque; the colour comes from the skin, which
draws each segment twice: once tinted with the line colour for the segments
the remote is not sitting on and once with the focus colour for the one it
is. That is why there is one texture per segment rather than a faint and a
solid copy of it.

Run from the repository root:

    python3 tools/gen_dialog_media.py
"""

import math
import os
import struct
import zlib

MEDIA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "resources", "skins", "Default", "media", "dialog")

# The ring, and the disc it rests on. The ring is inset a little so the disc
# shows as a rim around it rather than ending exactly where the ring does.
DISC_SIZE = 560
RING_SIZE = 548
RING_OUTER = 272.0
RING_INNER = 104.0

# The wedge each segment leaves to its neighbours, in degrees, so the ring
# reads as separate buttons rather than as one band.
SEGMENT_GAP = 2.6

# Samples per pixel per axis along a shape's edge. The inside and the outside
# of a shape are answered without sampling, so this is only paid for the edge.
SUPERSAMPLE = 4


def _png(path, width, height, rows):
    """Write 8-bit RGBA rows (each a bytearray of width * 4) as a PNG."""
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (none)
        raw.extend(row)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(blob)


def _coverage(inside, x, y):
    """How much of the pixel at (x, y) the shape covers, from 0.0 to 1.0.

    The four corners answer for the whole pixel wherever they agree, which is
    every pixel but the ones an edge runs through; only those are sampled.
    """
    corners = (inside(x, y), inside(x + 1.0, y),
               inside(x, y + 1.0), inside(x + 1.0, y + 1.0))
    if all(corners):
        return 1.0
    if not any(corners):
        return 0.0
    hits = 0
    step = 1.0 / SUPERSAMPLE
    for sy in range(SUPERSAMPLE):
        for sx in range(SUPERSAMPLE):
            if inside(x + (sx + 0.5) * step, y + (sy + 0.5) * step):
                hits += 1
    return hits / float(SUPERSAMPLE * SUPERSAMPLE)


def _render(size, inside):
    """Rasterise a white shape with the given inside test, anti-aliased."""
    rows = []
    for y in range(size):
        row = bytearray(size * 4)
        for x in range(size):
            alpha = _coverage(inside, float(x), float(y))
            if alpha <= 0.0:
                continue
            base = x * 4
            row[base] = 255
            row[base + 1] = 255
            row[base + 2] = 255
            row[base + 3] = int(round(alpha * 255.0))
        rows.append(row)
    return rows


def _disc():
    centre = DISC_SIZE / 2.0
    radius = DISC_SIZE / 2.0

    def inside(x, y):
        return math.hypot(x - centre, y - centre) <= radius

    return _render(DISC_SIZE, inside)


def _segment(count, index):
    """One wedge of a ring divided into ``count`` of them.

    Segment 0 is centred on the top of the ring and the rest follow it
    clockwise, which is the order the dialog fills them in. A single-segment
    ring is the whole ring: there is no neighbour to leave a gap to.
    """
    centre = RING_SIZE / 2.0
    span = 360.0 / count
    gap = 0.0 if count == 1 else SEGMENT_GAP
    start = index * span - span / 2.0 + gap / 2.0
    end = index * span + span / 2.0 - gap / 2.0

    def inside(x, y):
        dx = x - centre
        dy = y - centre
        radius = math.hypot(dx, dy)
        if not RING_INNER <= radius <= RING_OUTER:
            return False
        if count == 1:
            return True
        # Clockwise from the top of the ring, which is where segment 0 sits.
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0
        return (angle - start) % 360.0 <= (end - start) % 360.0

    return _render(RING_SIZE, inside)


ARROW_SIZE = 32


def _arrow(pointing_right):
    """A chevron for the single button layout's left and right steps."""
    size = float(ARROW_SIZE)
    # A triangle with a blunt tip, so the shape survives being drawn small.
    tip = 7.0 if pointing_right else size - 7.0
    back = size - 7.0 if pointing_right else 7.0

    def inside(x, y):
        # How far along the arrow the sample is, from the back edge to the tip.
        along = (x - back) / (tip - back)
        if not 0.0 <= along <= 1.0:
            return False
        half = (1.0 - along) * (size / 2.0 - 4.0)
        return abs(y - size / 2.0) <= half

    return _render(ARROW_SIZE, inside)


def main():
    os.makedirs(MEDIA, exist_ok=True)
    path = os.path.join(MEDIA, "wheel-disc.png")
    _png(path, DISC_SIZE, DISC_SIZE, _disc())
    print("wrote", path)
    for count in (1, 3, 4):
        for index in range(count):
            name = "wheel%d-segment%d.png" % (count, index + 1)
            path = os.path.join(MEDIA, name)
            _png(path, RING_SIZE, RING_SIZE, _segment(count, index))
            print("wrote", path)
    for name, pointing_right in (("arrow-left.png", False),
                                 ("arrow-right.png", True)):
        path = os.path.join(MEDIA, name)
        _png(path, ARROW_SIZE, ARROW_SIZE, _arrow(pointing_right))
        print("wrote", path)


if __name__ == "__main__":
    main()
