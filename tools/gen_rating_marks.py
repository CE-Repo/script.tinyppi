#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Draw the marks the plot card's ratings wear that are not the houses' own.

IMDb, TMDB, Trakt, TheTVDB, Letterboxd, Metacritic, Rotten Tomatoes' critics
and its Popcornmeter and MyAnimeList wear their own logo files, under
resources/web/ratings/ and converted for the app; this draws none of them.
It draws Metacritic's users' mark, Roger Ebert's, the IMDb Top 250's and the
age ratings of Germany (FSK), the United States (the MPA's for films, the TV
Parental Guidelines' for television) and Britain (BBFC).  They are simplified
marks in each house's colours, drawn here, not copies of its own logo files;
they name the source of a rating, which is nominative use (see section 4 of
LICENSE-ASSETS).  An age rating's mark is the left of its shield: the
board's name on the colour of the level, the level itself being written on
the shield's right.  The American boards' are drawn in the colours of the
FSK's levels rather than the MPA's black on white, so a row of them reads
the same whichever country rated the film.

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

    fsk = {"0": ("#FFFFFF", black), "6": ("#FFD500", black), "12": ("#00A651", white),
           "16": ("#00A0E3", white), "18": ("#E30613", white)}

    found = [
        # The IMDb Top 250's number alone, square like the logos beside it.
        Mark("top250", *square, [
            Shape(rounded(22, 22, 4), fill="#F5C518"),
            Shape(letters.text("250", 9, 11, 14.3, 0.1), fill=black),
        ]),
        # Metacritic's own circle with a reader on it, for its users' score.
        Mark("metacriticuser", *square, [
            Shape(circle(11, 11, 11), fill="#FFCC34"),
            Shape(circle(11, 8.3, 3.1), fill=black),
            Shape("M5.4 17.4C5.4 14.3 7.9 12.4 11 12.4C14.1 12.4 16.6 14.3 16.6 17.4Z", fill=black),
        ]),
        # Roger Ebert's initials, square like the logos beside it.
        Mark("rogerebert", *square, [
            Shape(rounded(22, 22, 4), fill="#C8102E"),
            Shape(letters.text("RE", 11, 11, 15.2, 0.3), fill=white),
        ]),
    ]
    for age, (colour, ink) in fsk.items():
        found.append(plate_of("fsk" + age, "FSK", colour, ink, letters))
    return found + american(letters) + british(letters)


# The colours of the levels, from all ages to adults only, as the FSK has them.
_ALL, _CHILDREN, _TEENS, _ADULTS, _RESTRICTED = (
    ("#00A651", "#FFFFFF"), ("#FFD500", "#000000"), ("#F7941D", "#000000"),
    ("#E30613", "#FFFFFF"), ("#2E3192", "#FFFFFF"))

# How wide the plate of each board's name is drawn, for its name to fit.
_BOARD_WIDTHS = {"FSK": 30, "MPA": 32, "TV": 24, "BBFC": 38}


def plate_of(name: str, board: str, colour: str, ink: str, letters: Lettering) -> Mark:
    """Return the left of an age rating's shield: the board's name on the
    level's colour.

    Square-cornered and full-bleed, as tall as the shield it stands in: the
    shield rounds its corners, and its right half carries the level itself.
    """
    width = _BOARD_WIDTHS[board]
    size = 9.4 if len(board) > 3 else 10.5
    return Mark(name, width, 22, [
        Shape(f"M0 0H{width}V22H0Z", fill=colour),
        Shape(letters.text(board, size, width / 2, 11 + size * 0.36, 0.2), fill=ink),
    ])


def american(letters: Lettering) -> list[Mark]:
    """Return the MPA's film ratings and the TV Parental Guidelines', in the
    FSK's colours rather than the MPA's black on white."""
    films = [plate_of(name, "MPA", *paint, letters) for name, paint in (
        ("mpa_g", _ALL), ("mpa_pg", _CHILDREN), ("mpa_pg13", _TEENS), ("mpa_r", _ADULTS),
        ("mpa_nc17", _RESTRICTED))]
    television = [plate_of(name, "TV", *paint, letters) for name, paint in (
        ("tv_y", _ALL), ("tv_y7", _ALL), ("tv_g", _ALL), ("tv_pg", _CHILDREN),
        ("tv_14", _TEENS), ("tv_ma", _ADULTS))]
    return films + television


def british(letters: Lettering) -> list[Mark]:
    """Return the BBFC's ratings, in its own colours."""
    return [plate_of(name, "BBFC", colour, ink, letters) for name, colour, ink in (
        ("bbfc_u", "#00A651", "#FFFFFF"), ("bbfc_pg", "#FBB800", "#000000"),
        ("bbfc_12a", "#F58220", "#FFFFFF"), ("bbfc_12", "#F58220", "#FFFFFF"),
        ("bbfc_15", "#E5007E", "#FFFFFF"), ("bbfc_18", "#E30613", "#FFFFFF"),
        ("bbfc_r18", "#1D1D6B", "#FFFFFF"))]


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
