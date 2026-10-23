#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Draw the marks the plot card's ratings wear.

One mark per rating source the dashboard knows (IMDb, TMDb, Trakt, TVDB,
Metacritic, Rotten Tomatoes), the IMDb Top 250 and the five FSK age ratings.
They are simplified marks in each house's colours, drawn here, not copies of
the houses' own logo files; they name the source of a rating, which is
nominative use (see section 4 of LICENSE-ASSETS).

The lettering is Inter Black turned into outlines, so a mark looks the same
whatever fonts the browser or the phone has -- and an Android vector drawable
cannot hold text at all.  Inter is under the SIL Open Font License 1.1.

Writes the SVGs the dashboard serves to resources/web/ratings/.  With
``--android <res/drawable>`` it also writes the same marks as vector
drawables for the TinyPPI app (``rating_<name>.xml``), so both draw one set.

Development only (``pip install fonttools``).  Run from the repository root:

    python3 tools/gen_rating_marks.py [--android ../tinyppi-mobile/app/src/main/res/drawable]
"""

import argparse
import os
from dataclasses import dataclass, field

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "resources", "web", "ratings")
FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"


@dataclass
class Shape:
    """One filled or stroked outline of a mark."""

    d: str
    fill: str | None = None
    # A horizontal gradient as (offset, colour) stops, in place of a fill.
    gradient: list[tuple[float, str]] = field(default_factory=list)
    stroke: str | None = None
    width: float = 0.0


@dataclass
class Mark:
    name: str
    width: int
    height: int
    shapes: list[Shape]


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def rounded(width: float, height: float, radius: float) -> str:
    """Return a rounded rectangle at the origin as path data."""
    r = radius
    return (f"M{_number(r)} 0H{_number(width - r)}A{_number(r)} {_number(r)} 0 0 1 "
            f"{_number(width)} {_number(r)}V{_number(height - r)}A{_number(r)} {_number(r)} 0 0 1 "
            f"{_number(width - r)} {_number(height)}H{_number(r)}A{_number(r)} {_number(r)} 0 0 1 "
            f"0 {_number(height - r)}V{_number(r)}A{_number(r)} {_number(r)} 0 0 1 {_number(r)} 0Z")


def circle(cx: float, cy: float, r: float) -> str:
    """Return a circle as path data (two arcs, which a vector drawable takes)."""
    return (f"M{_number(cx - r)} {_number(cy)}A{_number(r)} {_number(r)} 0 1 0 "
            f"{_number(cx + r)} {_number(cy)}A{_number(r)} {_number(r)} 0 1 0 "
            f"{_number(cx - r)} {_number(cy)}Z")


class Lettering:
    """Inter Black's outlines, set as a line of path data."""

    def __init__(self, path: str) -> None:
        self.font = TTFont(path)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.em = self.font["head"].unitsPerEm

    def text(self, words: str, size: float, centre: float, baseline: float,
             tracking: float = 0.0) -> str:
        """Return *words* at *size*, centred on *centre*, as path data."""
        names = [self.cmap[ord(char)] for char in words]
        scale = size / self.em
        advances = [self.glyphs[name].width * scale for name in names]
        total = sum(advances) + tracking * (len(names) - 1)
        x = centre - total / 2
        pen = SVGPathPen(self.glyphs, ntos=_number)
        for name, advance in zip(names, advances, strict=True):
            # Font units grow upwards and SVG's downwards.
            self.glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
            x += advance + tracking
        return pen.getCommands()


def marks(letters: Lettering) -> list[Mark]:
    """Return every mark the plot card draws."""
    wide, square = (44, 22), (22, 22)
    black, white = "#000000", "#FFFFFF"

    def plate(colour: str, words: str, ink: str | Shape, size: float, baseline: float = 15.6,
              tracking: float = 0.0) -> Mark:
        shape = (Shape(letters.text(words, size, 22, baseline, tracking), fill=ink)
                 if isinstance(ink, str) else ink)
        return Mark(words, *wide, [Shape(rounded(44, 22, 4), fill=colour), shape])

    tmdb_words = Shape(letters.text("TMDB", 11.5, 22, 15.4, 0.3),
                       gradient=[(0.0, "#90CEA1"), (0.55, "#3CBEC9"), (1.0, "#01B4E4")])
    fsk = {"0": ("#FFFFFF", black), "6": ("#FFD500", black), "12": ("#00A651", white),
           "16": ("#00A0E3", white), "18": ("#E30613", white)}

    found = [
        _named("imdb", plate("#F5C518", "IMDb", black, 12.5, 15.8)),
        _named("tmdb", plate("#0D253F", "TMDB", tmdb_words, 11.5)),
        _named("tvdb", plate("#1E2A33", "TVDB", "#6CD491", 11.5, 15.4, 0.3)),
        _named("top250", plate("#F5C518", "TOP 250", black, 8.4, 14.9, 0.1)),
        Mark("trakt", *square, [
            Shape(circle(11, 11, 11), fill="#ED1C24"),
            Shape(circle(11, 11, 7.2), stroke=white, width=1.6),
            Shape("M7.6 11.2L10 13.6L14.6 8.8", stroke=white, width=1.9),
        ]),
        Mark("metacritic", *square, [
            Shape(circle(11, 11, 11), fill="#FFCC34"),
            Shape(letters.text("m", 13, 11, 15.4), fill=black),
        ]),
        Mark("rottentomatoes", *square, [
            Shape(circle(11, 12.2, 9.6), fill="#FA320A"),
            Shape("M11 4.2C9.4 2.3 7.1 2.2 6 2.8C7.6 3 8.6 3.7 9.3 4.6C7.8 4.4 6.3 4.9 5.4 6"
                  "C7.1 5.6 9 6 11 7.2C13 6 14.9 5.6 16.6 6C15.7 4.9 14.2 4.4 12.7 4.6"
                  "C13.4 3.7 14.4 3 16 2.8C14.9 2.2 12.6 2.3 11 4.2Z", fill="#00912D"),
        ]),
    ]
    for age, (colour, ink) in fsk.items():
        found.append(Mark(f"fsk{age}", *square, [
            Shape(rounded(22, 22, 5), fill=colour),
            Shape(letters.text(age, 12, 11, 15.6), fill=ink),
        ]))
    return found


def _named(name: str, mark: Mark) -> Mark:
    mark.name = name
    return mark


def svg(mark: Mark) -> str:
    """Return *mark* as an SVG file."""
    defs, body = [], []
    for index, shape in enumerate(mark.shapes):
        if shape.gradient:
            stops = "".join(f'<stop offset="{_number(at)}" stop-color="{colour}"/>'
                            for at, colour in shape.gradient)
            defs.append(f'<linearGradient id="g{index}" x1="0" x2="1">{stops}</linearGradient>')
            paint = f'fill="url(#g{index})"'
        elif shape.stroke:
            paint = (f'fill="none" stroke="{shape.stroke}" stroke-width="{_number(shape.width)}" '
                     'stroke-linecap="round" stroke-linejoin="round"')
        else:
            paint = f'fill="{shape.fill}"'
        body.append(f'<path d="{shape.d}" {paint}/>')
    inner = (f"<defs>{''.join(defs)}</defs>" if defs else "") + "".join(body)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {mark.width} {mark.height}" '
            f'width="{mark.width}" height="{mark.height}">{inner}</svg>\n')


def vector(mark: Mark) -> str:
    """Return *mark* as an Android vector drawable."""
    paths = []
    for shape in mark.shapes:
        if shape.gradient:
            items = "\n".join(f'                    <item android:offset="{_number(at)}" '
                              f'android:color="{colour}" />' for at, colour in shape.gradient)
            paths.append(
                f'    <path android:pathData="{shape.d}">\n'
                '        <aapt:attr name="android:fillColor">\n'
                '            <gradient android:type="linear" android:startX="0" '
                f'android:startY="0" android:endX="{mark.width}" android:endY="0">\n'
                f"{items}\n"
                "            </gradient>\n"
                "        </aapt:attr>\n"
                "    </path>")
        elif shape.stroke:
            paths.append(
                f'    <path android:pathData="{shape.d}" android:strokeColor="{shape.stroke}" '
                f'android:strokeWidth="{_number(shape.width)}" android:strokeLineCap="round" '
                'android:strokeLineJoin="round" />')
        else:
            paths.append(f'    <path android:pathData="{shape.d}" '
                         f'android:fillColor="{shape.fill}" />')
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<!-- Drawn by tools/gen_rating_marks.py in script.tinyppi; edit it there. -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    xmlns:aapt="http://schemas.android.com/aapt"\n'
        f'    android:width="{mark.width}dp"\n'
        f'    android:height="{mark.height}dp"\n'
        f'    android:viewportWidth="{mark.width}"\n'
        f'    android:viewportHeight="{mark.height}">\n'
        + "\n".join(paths) + "\n</vector>\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--android", help="the app's res/drawable folder, to write it too")
    args = parser.parse_args()
    letters = Lettering(FONT)
    os.makedirs(OUT, exist_ok=True)
    for mark in marks(letters):
        with open(os.path.join(OUT, f"{mark.name}.svg"), "w", encoding="utf-8") as handle:
            handle.write(svg(mark))
        if args.android:
            with open(os.path.join(args.android, f"rating_{mark.name}.xml"), "w",
                      encoding="utf-8") as handle:
                handle.write(vector(mark))


if __name__ == "__main__":
    main()
