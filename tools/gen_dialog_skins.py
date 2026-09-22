#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Write the VS10 dialog's layout window files.

Six of the seven layouts draw the same four branches - what the stream is
decides which choices there are - in a different arrangement, so they are
generated from one description rather than kept in step by hand. The
seventh, the panel the add-on has always opened with, is written by hand and
left alone here.

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
          align="center", visible=None, control_id=None, zoom=None):
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
    if zoom:
        body.append("    <animation effect=\"zoom\" start=\"100\" end=\"%d\" "
                    "center=\"auto\" time=\"0\" condition=\"true\">"
                    "Conditional</animation>" % zoom)
    body.append("    <label>%s</label>" % text)
    body.append("</control>")
    return "\n".join(body)


def button(control_id, left, top, width, height, text, nav, blank=False):
    """One choice.

    ``blank`` draws no textures of its own: the wheel paints the segment
    under the button instead, and a button drawing its own rounded rectangle
    on top of a wedge would show as a rectangle in a ring.
    """
    body = ["<control type=\"button\" id=\"%d\">" % control_id,
            "    <left>%d</left>" % left,
            "    <top>%d</top>" % top,
            "    <width>%d</width>" % width,
            "    <height>%d</height>" % height,
            "    <label>%s</label>" % ("" if blank else text),
            "    <align>center</align>",
            "    <aligny>center</aligny>",
            "    <font>font23_narrow</font>"]
    for key in ("onup", "ondown", "onleft", "onright"):
        if key in nav:
            body.append("    <%s>%d</%s>" % (key, nav[key], key))
    if blank:
        body.append("    <texturefocus></texturefocus>")
        body.append("    <texturenofocus></texturenofocus>")
    else:
        body.extend([
            "    <textcolor>%s</textcolor>" % (HOME % "DescriptionColor"),
            "    <selectedcolor>%s</selectedcolor>" % (HOME % "DescriptionColor"),
            "    <focusedcolor>%s</focusedcolor>"
            % (HOME % "DialogFocusTextColor"),
            "    <texturenofocus colordiffuse=\"00FFFFFF\" border=\"40\">"
            "common/button-white.png</texturenofocus>",
            "    <texturefocus colordiffuse=\"%s\" border=\"40\">"
            "common/button-white.png</texturefocus>" % (HOME % "DialogFocusColor"),
        ])
    body.append("</control>")
    return "\n".join(body)


def panel(width, height):
    """The rounded rectangle every layout but the wheel rests its choices on."""
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


def spread(count, slots, start, size, gap):
    """Where ``count`` items go in the room kept for ``slots`` of them.

    The layouts reserve the same space whatever the stream is, so that the
    panel is one size and the position settings mean one thing; a branch with
    fewer choices than the widest one spreads them over that space rather than
    bunching them at one end.
    """
    room = slots * size + (slots - 1) * gap
    if count <= 1:
        return [start + (room - size) // 2]
    step = (room - size) / float(count - 1)
    return [start + int(index * step + 0.5) for index in range(count)]


def ring_nav(index, count):
    """Left and right, and up and down, walk the choices round in a ring."""
    if count == 1:
        return {"onleft": None, "onright": None}
    return {"previous": (index - 1) % count, "next": (index + 1) % count}


def stacked_branches(size, place, keys):
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

def bar(mode, title, margin, gap, slots, header_font, title_top, icon_size,
        rule_top, button_top, button_height, second_rule_top, single_width):
    """The wide bar and the compact one: the choices in a row."""
    width, height = layout.PANEL_SIZE[mode]
    inner = width - 2 * margin
    size = (inner - (slots - 1) * gap) // slots

    def place(buttons, keys):
        count = len(buttons)
        if count == 1:
            lefts = [margin + (inner - single_width) // 2]
            widths = [single_width]
        else:
            lefts = spread(count, slots, margin, size, gap)
            widths = [size] * count
        return "\n".join(
            button(control_id, lefts[index], button_top, widths[index],
                   button_height, text, nav_for(buttons, index, keys))
            for index, (control_id, text, _short, _action) in enumerate(buttons))

    body = "\n".join([
        panel(width, height),
        header(width, margin, title_top, icon_size,
               title_top + (44 - icon_size) // 2, header_font),
        rule(margin, rule_top, inner),
        rule(margin, second_rule_top, inner),
        stacked_branches(None, place, ("onleft", "onright")),
    ])
    left, top = layout.panel_position(mode)
    return window(title, layout.BRANCHES[0]["buttons"][0][0], width, height,
                  left, top, body, slide(0, 120), slide_out(0, 240))


# -- the sidebars -----------------------------------------------------------

def sidebar(mode, title):
    width, height = layout.PANEL_SIZE[mode]
    margin, gap, slots = 24, 12, 4
    button_width = width - 2 * margin
    button_height = 70
    area_top = 90

    def place(buttons, keys):
        tops = spread(len(buttons), slots, area_top, button_height, gap)
        return "\n".join(
            button(control_id, margin, tops[index], button_width,
                   button_height, text, nav_for(buttons, index, keys))
            for index, (control_id, text, _short, _action) in enumerate(buttons))

    body = "\n".join([
        panel(width, height),
        header(width, margin, 20, 32, 24, "font32"),
        rule(margin, 74, button_width),
        rule(margin, 424, button_width),
        stacked_branches(None, place, ("onup", "ondown")),
    ])
    travel = -(width + layout.SCREEN_MARGIN)
    if mode == layout.MODE_SIDEBAR_RIGHT:
        travel = -travel
    left, top = layout.panel_position(mode)
    return window(title, layout.BRANCHES[0]["buttons"][0][0], width, height,
                  left, top, body, slide(travel, 0), slide_out(travel, 0))


# -- the wheel --------------------------------------------------------------

WHEEL_RING_INSET = 6
WHEEL_RING_SIZE = 548
WHEEL_LABEL_RADIUS = 188
WHEEL_LABEL_WIDTH = 160
WHEEL_HIT_WIDTH = 150
WHEEL_HIT_HEIGHT = 120


def wheel_nav(buttons, index):
    """Which segment each direction leads to on the ring.

    A wheel of four has a segment in each direction, so the direction pad
    points straight at them: up is the segment at the top whichever one the
    remote is on. Three or one has no such answer, so there the directions
    walk the ring instead, as they do on the bars.
    """
    count = len(buttons)
    if count == 4:
        return {"onup": buttons[0][0], "onright": buttons[1][0],
                "ondown": buttons[2][0], "onleft": buttons[3][0]}
    previous = buttons[(index - 1) % count][0]
    following = buttons[(index + 1) % count][0]
    return {"onup": previous, "onleft": previous,
            "ondown": following, "onright": following}


def wheel_point(index, count, size):
    """The middle of a segment's outer band, where its name goes."""
    centre = size / 2.0
    angle = math.radians(index * 360.0 / count)
    return (centre + WHEEL_LABEL_RADIUS * math.sin(angle),
            centre - WHEEL_LABEL_RADIUS * math.cos(angle))


def wheel(title):
    mode = layout.MODE_WHEEL
    width, height = layout.PANEL_SIZE[mode]
    inset = WHEEL_RING_INSET
    hub_top = height // 2 - 44

    def place(buttons, keys):
        count = len(buttons)
        out = []
        for index, (control_id, _text, text, _action) in enumerate(buttons):
            segment = "dialog/wheel%d-segment%d.png" % (count, index + 1)
            out.append(image(inset, inset, WHEEL_RING_SIZE, WHEEL_RING_SIZE,
                             segment, HOME % "DialogLineColor",
                             visible="!Control.HasFocus(%d)" % control_id,
                             aspect="keep"))
            out.append(image(inset, inset, WHEEL_RING_SIZE, WHEEL_RING_SIZE,
                             segment, HOME % "DialogFocusColor",
                             visible="Control.HasFocus(%d)" % control_id,
                             aspect="keep"))
        for index, (control_id, _text, text, _action) in enumerate(buttons):
            x, y = wheel_point(index, count, width)
            left = int(x - WHEEL_LABEL_WIDTH / 2.0)
            top = int(y - 15)
            # A wedge wants smaller writing than the bars do, and the skin the
            # window is drawn with supplies the fonts, so the name is zoomed
            # rather than set in a font of a size this file cannot count on.
            out.append(label(left, top, WHEEL_LABEL_WIDTH, 30, text,
                             HOME % "DescriptionColor",
                             visible="!Control.HasFocus(%d)" % control_id,
                             zoom=84))
            out.append(label(left, top, WHEEL_LABEL_WIDTH, 30, text,
                             HOME % "DialogFocusTextColor",
                             visible="Control.HasFocus(%d)" % control_id,
                             zoom=84))
            out.append(button(control_id,
                              int(x - WHEEL_HIT_WIDTH / 2.0),
                              int(y - WHEEL_HIT_HEIGHT / 2.0),
                              WHEEL_HIT_WIDTH, WHEEL_HIT_HEIGHT, text,
                              wheel_nav(buttons, index), blank=True))
        return "\n".join(out)

    body = "\n".join([
        image(0, 0, width, height, "dialog/wheel-disc.png",
              HOME % "DialogBackgroundColor", aspect="keep"),
        # The directions are worked out from the ring itself, so the pair
        # the bars are handed is not used here.
        stacked_branches(None, place, ("onleft", "onright")),
        # The hub: a circle has no corner to hang a heading off, and the
        # middle of a wheel is where the eye lands anyway.
        image(width // 2 - 20, hub_top, 40, 40, "icons/vs10.png",
              HOME % "DialogHeaderIconColor",
              visible=SHOW % "ShowHeaderIcon", aspect="keep"),
        label(width // 2 - 100, hub_top + 50, 200, 44, "[B]VS10[/B]",
              HOME % "DialogHeaderColor", font="font32",
              visible=SHOW % "ShowHeaderTitle"),
    ])
    zoom_in = SLIDE_IN + (
        "<animation effect=\"zoom\" start=\"60\" end=\"100\" center=\"%d,%d\""
        " time=\"200\" tween=\"quadratic\" easing=\"out\">Visible</animation>\n"
        % (width // 2, height // 2))
    zoom_out = (
        "<animation effect=\"zoom\" start=\"100\" end=\"60\" center=\"%d,%d\""
        " time=\"150\" tween=\"quadratic\" easing=\"in\">WindowClose</animation>\n"
        "<animation effect=\"fade\" start=\"100\" end=\"0\" time=\"150\">"
        "WindowClose</animation>" % (width // 2, height // 2))
    left, top = layout.panel_position(mode)
    return window(title, layout.BRANCHES[0]["buttons"][0][0], width, height,
                  left, top, body, zoom_in, zoom_out)


# -- the single button ------------------------------------------------------

def single(title):
    mode = layout.MODE_SINGLE
    width, height = layout.PANEL_SIZE[mode]
    margin = 30
    inner = width - 2 * margin
    nav = {key: layout.SINGLE_BUTTON
           for key in ("onup", "ondown", "onleft", "onright")}
    body = "\n".join([
        panel(width, height),
        header(width, margin, 18, 36, 22, "font32"),
        rule(margin, 80, inner),
        # What left and right do. Not buttons: there is nowhere for focus to
        # go but the one button there is.
        image(margin + 4, 122, 32, 32, "dialog/arrow-left.png",
              HOME % "DescriptionColor", aspect="keep"),
        image(width - margin - 36, 122, 32, 32, "dialog/arrow-right.png",
              HOME % "DescriptionColor", aspect="keep"),
        button(layout.SINGLE_BUTTON, 90, 98, width - 180, 80, "", nav),
        rule(margin, 196, inner),
        # Which choice of how many the button is on, written by the dialog:
        # one button gives no other sign of how far round the ring it is.
        label(margin, 200, inner, 28, "", HOME % "DescriptionColor",
              control_id=layout.SINGLE_STEP_LABEL),
    ])
    left, top = layout.panel_position(mode)
    return window(title, layout.SINGLE_BUTTON, width, height, left, top,
                  body, slide(0, 120), slide_out(0, 240))


def main():
    files = {
        layout.MODE_FULL: bar(
            layout.MODE_FULL,
            "The wide bar: the choices in a row across the screen.",
            margin=30, gap=25, slots=4, header_font="font32", title_top=18,
            icon_size=36, rule_top=80, button_top=100, button_height=80,
            second_rule_top=198, single_width=600),
        layout.MODE_COMPACT: bar(
            layout.MODE_COMPACT,
            "The compact bar: the wide one at about three quarters the size,"
            " and free to be moved sideways.",
            margin=24, gap=18, slots=4, header_font="font23_narrow",
            title_top=12, icon_size=28, rule_top=56, button_top=72,
            button_height=60, second_rule_top=150, single_width=500),
        layout.MODE_SIDEBAR_LEFT: sidebar(
            layout.MODE_SIDEBAR_LEFT,
            "The left sidebar: the choices stacked against the left edge."),
        layout.MODE_SIDEBAR_RIGHT: sidebar(
            layout.MODE_SIDEBAR_RIGHT,
            "The right sidebar: the left one against the other edge."),
        layout.MODE_WHEEL: wheel(
            "The wheel: the choices in the segments of a ring, the way a"
            " game's weapon wheel arranges its own."),
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
