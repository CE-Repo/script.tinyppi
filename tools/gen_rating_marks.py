#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Draw the marks the plot card's ratings wear that are not the houses' own.

IMDb, TMDB, Trakt, TheTVDB, Letterboxd, Metacritic, Rotten Tomatoes' critics
and its Popcornmeter, MyAnimeList and MDBList wear their own logo files, under
resources/web/ratings/ and converted for the app; this draws none of them.
It draws Metacritic's users' mark, Roger Ebert's, the IMDb Top 250's, the
seal a Rotten Tomatoes rating wears when it is certified (Certified Fresh,
Verified Hot), the plates of the big awards (the Academy Awards, the Golden
Globes, the BAFTAs, the Primetime Emmys) and the age ratings of Germany
(FSK), the United States (the MPA's for films, the TV Parental Guidelines'
for television) and Britain (BBFC).  They are simplified
marks in each house's colours, drawn here, not copies of its own logo files;
they name the source of a rating, which is nominative use (see section 4 of
LICENSE-ASSETS).  An age rating's mark is the left of its shield: the
board's name on the colour of the level, the level itself being written on
the shield's right.  An award's is a drawing of what it hands out, square
like the logos beside it, with what it won written beside it.  The American
boards' are drawn in the colours of the FSK's levels rather than the MPA's
black on white, so a row of them reads the same whichever country rated the
film.

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
import math
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


def ellipse(cx: float, cy: float, rx: float, ry: float, turn: float = 0.0) -> str:
    """Return an ellipse turned by *turn* degrees as path data (two arcs)."""
    angle = math.radians(turn)
    dx, dy = rx * math.cos(angle), rx * math.sin(angle)
    arc = f"A{_number(rx)} {_number(ry)} {_number(turn)} 1 0 "
    return (f"M{_number(cx - dx)} {_number(cy - dy)}{arc}{_number(cx + dx)} {_number(cy + dy)}"
            f"{arc}{_number(cx - dx)} {_number(cy - dy)}Z")


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
        # The seal on the corner of Rotten Tomatoes' mark when it is certified:
        # a tick on its red, ringed in white so it stands off any ground.
        Mark("certified", 12, 12, [
            Shape(circle(6, 6, 6), fill=white),
            Shape(circle(6, 6, 4.8), fill="#FA320A"),
            Shape("M3.6 6.2L5.3 7.9L8.5 4.5", stroke=white, width=1.5),
        ]),
        # Roger Ebert's initials, square like the logos beside it.
        Mark("rogerebert", *square, [
            Shape(rounded(22, 22, 4), fill="#C8102E"),
            Shape(letters.text("RE", 11, 11, 15.2, 0.3), fill=white),
        ]),
    ]
    for age, (colour, ink) in fsk.items():
        found.append(plate_of("fsk" + age, "FSK", colour, ink, letters))
    return found + american(letters) + british(letters) + awards()


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


def awards() -> list[Mark]:
    """Return the marks of the big awards: each a simplified drawing of what
    is handed out, square on a ground of its own like the logos beside it --
    a statuette for the Academy Awards, a ringed globe for the Golden
    Globes, a theatre mask for the BAFTAs and a winged figure holding up an
    atom for the Primetime Emmys."""
    gold, ink, white = "#E2B33C", "#141414", "#FFFFFF"

    def mark(name: str, ground: str, shapes: list[Shape]) -> Mark:
        return Mark(name, 22, 22, [Shape(rounded(22, 22, 4), fill=ground), *shapes])

    def base(colour: str, top: float, width: float) -> Shape:
        left = 11 - width / 2
        return Shape(f"M{_number(left + 0.7)} {_number(top)}H{_number(left + width - 0.7)}"
                     f"A0.7 0.7 0 0 1 {_number(left + width)} {_number(top + 0.7)}V19.4"
                     f"A0.7 0.7 0 0 1 {_number(left + width - 0.7)} 20.1H{_number(left + 0.7)}"
                     f"A0.7 0.7 0 0 1 {_number(left)} 19.4V{_number(top + 0.7)}"
                     f"A0.7 0.7 0 0 1 {_number(left + 0.7)} {_number(top)}Z", fill=colour)

    oscar = mark("award_oscar", gold, [
        Shape(circle(11, 2.9, 1.35), fill=ink),
        Shape("M9.3 4.6H12.7L13.1 5.6L12.2 6.1L12.8 9.9L12.2 15H9.8L9.2 9.9L9.8 6.1L8.9 5.6Z",
              fill=ink),
        Shape("M8.6 15.4H13.4L13.8 16.6H8.2Z", fill=ink),
        base(ink, 17.1, 7.6),
    ])
    globe = mark("award_globe", "#9C6B1E", [
        Shape(circle(11, 8, 5.6), stroke=white, width=1.3),
        Shape(ellipse(11, 8, 2.3, 5.6), stroke=white, width=1.0),
        Shape("M5.4 8H16.6", stroke=white, width=1.0),
        Shape(ellipse(11, 8, 7.4, 2.2, -18), stroke=white, width=1.1),
        Shape("M10.1 13.5H11.9V16.1H10.1Z", fill=white),
        base(white, 16.6, 8.4),
    ])
    bafta = mark("award_bafta", ink, [
        # The mask with its eyes and its mouth cut out: drawn the other way
        # round, so the holes stay holes under the non-zero fill rule.
        Shape("M4.2 3.6C8.6 2.2 13.4 2.2 17.8 3.6C18.4 10.8 15.6 16.6 11 19.4"
              "C6.4 16.6 3.6 10.8 4.2 3.6Z"
              "M7 8.4C7.9 9.4 9.3 9.4 10.2 8.5C9.5 7.3 7.9 7.3 7 8.4Z"
              "M15 8.4C14.1 7.3 12.5 7.3 11.8 8.5C12.7 9.4 14.1 9.4 15 8.4Z"
              "M8.4 13.2C9 15.2 9.9 16.1 11 16.1C12.1 16.1 13 15.2 13.6 13.2"
              "C12 14.4 10 14.4 8.4 13.2Z", fill=gold),
    ])
    emmy = mark("award_emmy", "#3B2A6B", [
        *(Shape(ellipse(11, 3.4, 3.6, 1.3, turn), stroke=gold, width=0.9) for turn in (0, 60, -60)),
        Shape("M10.3 7H11.7L12 15.3H10Z", fill=gold),
        Shape("M10.4 8.4L3.8 5.6L6.2 11.8L10.4 10.6Z", fill=gold),
        Shape("M11.6 8.4L18.2 5.6L15.8 11.8L11.6 10.6Z", fill=gold),
        base(gold, 16, 7.6),
    ])
    return [oscar, globe, bafta, emmy]


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
