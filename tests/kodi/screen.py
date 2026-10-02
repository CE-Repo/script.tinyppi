# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Measure screenshots: where a colour is, how much of it, how two differ.

Needs Pillow.  The tests paint the panels in signal colours on a gray
picture, so a panel is the bounding box of its colour.
"""

from PIL import Image, ImageChops

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)
MAGENTA, YELLOW, CYAN = (255, 0, 255), (255, 255, 0), (0, 255, 255)


def hexcolor(rgb):
    """The value the colour picker stores for a HEX colour."""
    code = "".join(f"{c:02X}" for c in rgb)
    return f"[COLOR=FF{code}]●[/COLOR] #{code}"


def _mask(path, rgb, tolerance):
    image = Image.open(path).convert("RGB")
    bands = [channel.point(lambda v, t=target: 255 if abs(v - t) <= tolerance else 0)
             for channel, target in zip(image.split(), rgb, strict=True)]
    return ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])


def pixels(path, rgb, tolerance=45):
    return _mask(path, rgb, tolerance).histogram()[255]


def bbox(path, rgb, tolerance=45, min_pixels=400):
    mask = _mask(path, rgb, tolerance)
    return mask.getbbox() if mask.histogram()[255] >= min_pixels else None


def bluish_bbox(path, margin=50, min_pixels=400):
    """Box of blue-dominant pixels; survives the dark gradient of an OSD."""
    red, green, blue = Image.open(path).convert("RGB").split()
    mask = ImageChops.subtract(blue, ImageChops.lighter(red, green)).point(lambda v: 255 if v > margin else 0)
    return mask.getbbox() if mask.histogram()[255] >= min_pixels else None


def size(box):
    return (box[2] - box[0], box[3] - box[1]) if box else None


def difference(path_a, path_b, box):
    """Mean grey-level difference of two screenshots inside *box*."""
    a = Image.open(path_a).convert("L").crop(box)
    b = Image.open(path_b).convert("L").crop(box)
    histogram = ImageChops.difference(a, b).histogram()
    return sum(level * count for level, count in enumerate(histogram)) / max(1, a.width * a.height)
