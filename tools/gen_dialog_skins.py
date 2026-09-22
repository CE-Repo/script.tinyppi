#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Write the VS10 dialog's layout window files.

Two of the three layouts draw the same four branches - what the stream is
decides which choices there are - in a different arrangement, so they are
generated from one description rather than kept in step by hand. The third,
the panel the add-on has always opened with, is written by hand and left
alone here.

The choices themselves, and how large each layout's panel is, come from
``resources/lib/ui/dialog_layout.py``, which the dialog reads too.

Run from the repository root:

    python3 tools/gen_dialog_skins.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from ui import dialog_layout as layout  # noqa: E402

SKIN = os.path.join(ROOT, "resources", "skins", "Default", "1080i")

HOME = "$INFO[Window(10000).Property(TinyPPI.%s)]"
SHOW = "String.IsEqual(Window(10000).Property(TinyPPI.%s),1)"
PLACED = "String.IsEqual(Window(10000).Property(%s),1)" % layout.PROP_PLACED

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated file - do not edit by hand; see tools/gen_dialog_skins.py.
     %s -->
"""


def indent(text, depth):
    pad = " " * depth
    return "".join(pad + line + "\n" for line in text.strip("\n").split("\n"))


def image(left, top, width, height, texture, colour, border=None,
          visible=None, aspect=None):
    body = ["<control type=\"image\">",
            "    <left>%d</left>" % left,
            "    <top>%d</top>" % top,
            "    <width>%d</width>" % width,
            "    <height>%d</height>" % height]
    if aspect:
        body.append("    <aspectratio>%s</aspectratio>" % aspect)
    if visible:
        body.append("    <visible>%s</visible>" % visible)
    attrs = "colordiffuse=\"%s\"" % colour
    if border is not None:
        attrs += " border=\"%d\"" % border
    body.append("    <texture %s>%s</texture>" % (attrs, texture))
    body.append("</control>")
    return "\n".join(body)


def label(left, top, width, height, text, colour, font="font23_narrow",
          align="center", visible=None, control_id=None):
    opening = ("<control type=\"label\" id=\"%d\">" % control_id
               if control_id else "<control type=\"label\">")
    body = [opening,
            "    <left>%d</left>" % left,
            "    <top>%d</top>" % top,
            "    <width>%d</width>" % width,
            "    <height>%d</height>" % height,
            "    <font>%s</font>" % font,
            "    <textcolor>%s</textcolor>" % colour,
            "    <align>%s</align>" % align,
            "    <aligny>center</aligny>"]
    if visible:
        body.append("    <visible>%s</visible>" % visible)
    body.append("    <label>%s</label>" % text)
    body.append("</control>")
    return "\n".join(body)


def button(control_id, left, top, width, height, text, nav):
    """One choice: the same button the hand written panel draws."""
    body = ["<control type=\"button\" id=\"%d\">" % control_id,
            "    <left>%d</left>" % left,
            "    <top>%d</top>" % top,
            "    <width>%d</width>" % width,
            "    <height>%d</height>" % height,
            "    <label>%s</label>" % text,
            "    <align>center</align>",
            "    <font>font23_narrow</font>"]
    for key in ("onup", "ondown", "onleft", "onright"):
        if key in nav:
            body.append("    <%s>%d</%s>" % (key, nav[key], key))
    body.extend([
        "    <textcolor>%s</textcolor>" % (HOME % "DialogTextColor"),
        "    <selectedcolor>%s</selectedcolor>" % (HOME % "DialogTextColor"),
        "    <focusedcolor>%s</focusedcolor>" % (HOME % "DialogFocusTextColor"),
        "    <texturenofocus colordiffuse=\"00FFFFFF\" border=\"40\">"
        "common/button-white.png</texturenofocus>",
        "    <texturefocus colordiffuse=\"%s\" border=\"40\">"
        "common/button-white.png</texturefocus>" % (HOME % "DialogFocusColor"),
    ])
    body.append("</control>")
    return "\n".join(body)


def panel(width, height):
    """The rounded rectangle a generated layout rests its choices on."""
    return image(0, 0, width, height, "common/button-white.png",
                 HOME % "DialogBackgroundColor", border=40)


def header(width, title_left, title_top, icon_size, icon_top, font):
    """The "VS10" heading and its icon, each hidden by its own setting."""
    icon_left = width - title_left - icon_size
    return "\n".join([
        label(title_left, title_top, width - 2 * title_left, 44, "[B]VS10[/B]",
              HOME % "DialogHeaderColor", font=font, align="left",
              visible=SHOW % "ShowHeaderTitle"),
        image(icon_left, icon_top, icon_size, icon_size, "icons/vs10.png",
              HOME % "DialogHeaderIconColor",
              visible=SHOW % "ShowHeaderIcon", aspect="keep"),
    ])


def rule(left, top, width):
    return image(left, top, width, 1, "common/dot-1x1.png",
                 HOME % "DialogLineColor", visible=SHOW % "ShowLine")


def ring_nav(index, count):
    """Left and right, and up and down, walk the choices round in a ring."""
    if count == 1:
        return {"onleft": None, "onright": None}
    return {"previous": (index - 1) % count, "next": (index + 1) % count}


def stacked_branches(place, keys):
    """Every branch's choices, each group hidden unless its stream is playing.

    ``place`` is handed the branch's buttons and returns the controls for
    them; ``keys`` names which pair of directions walks the ring, so the
    stacked layouts step with up and down and the bars with left and right.
    """
    out = []
    for branch in layout.BRANCHES:
        buttons = branch["buttons"]
        controls = place(buttons, keys)
        out.append("\n".join([
            "<control type=\"group\">",
            "    <visible>%s</visible>" % branch["visible"],
            indent(controls, 4).rstrip("\n"),
            "</control>",
        ]))
    return "\n".join(out)


def nav_for(buttons, index, keys):
    """Which button each of the two active directions leads to."""
    count = len(buttons)
    nav = {}
    if count > 1:
        nav[keys[0]] = buttons[(index - 1) % count][0]
        nav[keys[1]] = buttons[(index + 1) % count][0]
    else:
        nav[keys[0]] = buttons[0][0]
        nav[keys[1]] = buttons[0][0]
    # The other two directions lead back to the button itself, so a press
    # across the grain leaves focus where it is instead of dropping it.
    other = ("onup", "ondown") if keys[0] == "onleft" else ("onleft", "onright")
    nav[other[0]] = buttons[index][0]
    nav[other[1]] = buttons[index][0]
    return nav


def window(title, default_control, width, height, left, top, body,
           entry, exit_):
    """The window every layout shares: the dim, the moved group, the panel."""
    dim = image(0, 0, 1920, 1080, "common/dot-1x1.png",
                HOME % "DialogGlobalBackgroundColor", visible=PLACED)
    return (HEADER % title) + "\n".join([
        "<window type=\"dialog\">",
        "    <defaultcontrol always=\"true\">%d</defaultcontrol>" % default_control,
        "    <onload>Dialog.Close(fullscreenvideo,true)</onload>",
        "    <onload>Dialog.Close(videoosd,true)</onload>",
        "    <onload>Dialog.Close(seekbar,true)</onload>",
        "    <onload>Dialog.Close(1159,true)</onload>",
        "    <animation effect=\"fade\" start=\"0\" end=\"100\" time=\"200\""
        " tween=\"cubic\" easing=\"inout\">WindowOpen</animation>",
        "    <animation effect=\"fade\" end=\"0\" start=\"100\" time=\"150\">"
        "WindowClose</animation>",
        "    <controls>",
        indent(dim, 8).rstrip("\n"),
        "",
        "        <!-- Moved into place by ui.mode_select before anything is",
        "             drawn: the window file can only name one position, and",
        "             the panel would otherwise show at that one for a frame",
        "             and then jump to the one the settings ask for. The",
        "             group that is moved carries the closing animation,",
        "             because a control held back by a condition does not play",
        "             itself out again when the window closes. -->",
        "        <control type=\"group\" id=\"%d\">" % layout.GROUP_PANEL,
        "            <left>%d</left>" % left,
        "            <top>%d</top>" % top,
        "            <width>%d</width>" % width,
        "            <height>%d</height>" % height,
        indent(exit_, 12).rstrip("\n"),
        "            <control type=\"group\">",
        "                <left>0</left>",
        "                <top>0</top>",
        "                <width>%d</width>" % width,
        "                <height>%d</height>" % height,
        "                <visible>%s</visible>" % PLACED,
        indent(entry, 16).rstrip("\n"),
        indent(body, 16).rstrip("\n"),
        "            </control>",
        "        </control>",
        "    </controls>",
        "</window>",
        "",
    ])


SLIDE_IN = """
<animation effect="fade" start="0" end="100" time="200">Visible</animation>
<animation effect="fade" start="100" end="0" time="150">Hidden</animation>
"""


def slide(dx, dy):
    return SLIDE_IN + (
        "<animation effect=\"slide\" start=\"%d,%d\" end=\"0,0\" time=\"200\""
        " tween=\"quadratic\" easing=\"out\">Visible</animation>\n" % (dx, dy))


def slide_out(dx, dy):
    return (
        "<animation effect=\"slide\" start=\"0,0\" end=\"%d,%d\" time=\"200\""
        " tween=\"quadratic\" easing=\"in\">WindowClose</animation>\n"
        "<animation effect=\"fade\" start=\"100\" end=\"0\" time=\"150\">"
        "WindowClose</animation>" % (dx, dy))


# -- the bars ---------------------------------------------------------------

def bar(mode, title, margin, gap, header_font, title_top, icon_size,
        rule_top, button_top, button_height, second_rule_top, single_width):
    """The bar: the choices in a row.

    Each branch fills the row with the choices it has rather than leaving the
    gaps a branch with more would want: three names over four buttons' worth
    of room is what cut "Dolby Vision (Original)" short. The panel stays one
    size whatever is playing, so the position settings still mean one thing.
    """
    width, height = layout.PANEL_SIZE[mode]
    inner = width - 2 * margin

    def place(buttons, keys):
        count = len(buttons)
        if count == 1:
            lefts = [margin + (inner - single_width) // 2]
            size = single_width
        else:
            size = (inner - (count - 1) * gap) // count
            lefts = [margin + index * (size + gap) for index in range(count)]
        return "\n".join(
            button(control_id, lefts[index], button_top, size,
                   button_height, text, nav_for(buttons, index, keys))
            for index, (control_id, text, _action) in enumerate(buttons))

    body = "\n".join([
        panel(width, height),
        header(width, margin, title_top, icon_size,
               title_top + (44 - icon_size) // 2, header_font),
        rule(margin, rule_top, inner),
        rule(margin, second_rule_top, inner),
        stacked_branches(place, ("onleft", "onright")),
    ])
    left, top = layout.panel_position(mode)
    return window(title, layout.BRANCHES[0]["buttons"][0][0], width, height,
                  left, top, body, slide(0, 120), slide_out(0, 240))


# -- the single button ------------------------------------------------------

def single(title):
    mode = layout.MODE_SINGLE
    width, height = layout.PANEL_SIZE[mode]
    margin = 30
    inner = width - 2 * margin
    nav = {key: layout.SINGLE_BUTTON
           for key in ("onup", "ondown", "onleft", "onright")}
    # What left and right do. Not buttons: there is nowhere for focus to go
    # but the one button there is, which is also why they take the colour the
    # button is drawn in rather than the one its name is written in - the
    # three read as one piece that way.
    arrows = [image(left, 122, 32, 32, "dialog/" + name,
                    HOME % "DialogFocusColor", aspect="keep")
              for name, left in (("arrow-left.png", margin + 4),
                                 ("arrow-right.png", width - margin - 36))]
    body = "\n".join([
        panel(width, height),
        header(width, margin, 18, 36, 22, "font32"),
        rule(margin, 80, inner),
    ] + arrows + [
        button(layout.SINGLE_BUTTON, 90, 98, width - 180, 80, "", nav),
        rule(margin, 196, inner),
    ])
    left, top = layout.panel_position(mode)
    return window(title, layout.SINGLE_BUTTON, width, height, left, top,
                  body, slide(0, 120), slide_out(0, 240))


def main():
    files = {
        layout.MODE_BAR: bar(
            layout.MODE_BAR,
            "The bar: the choices in a row rather than stacked, in a panel"
            " low enough to leave most of the picture showing.",
            margin=24, gap=18, header_font="font23_narrow",
            title_top=14, icon_size=30, rule_top=62, button_top=78,
            button_height=80, second_rule_top=176, single_width=500),
        layout.MODE_SINGLE: single(
            "The single button: one button, and left or right steps it to the"
            " next choice rather than moving to another button."),
    }
    for mode, text in files.items():
        path = os.path.join(SKIN, layout.XML_FILES[mode])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("wrote", path)


if __name__ == "__main__":
    main()
