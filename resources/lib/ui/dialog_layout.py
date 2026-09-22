# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Geometry and choices of the VS10 dialog's layouts.

One dialog, three ways of drawing it: the panel the add-on has always had,
the compact bar and the single button. Which window file each is drawn from,
how large its panel is and therefore how far it may be moved all live here,
so the skin generator in ``tools/gen_dialog_skins.py`` and the dialog itself
work from one description rather than from two that drift apart.

Imported by the generator outside Kodi as well, so everything Kodi supplies
is optional here.
"""

try:  # pragma: no cover - absent when the skin generator runs this
    import xbmc
    import xbmcaddon
except ImportError:
    xbmc = None
    xbmcaddon = None

# The layouts, and the window file each is drawn from.
MODE_STANDARD = 0
MODE_COMPACT = 1
MODE_SINGLE = 2

XML_FILES = {
    MODE_STANDARD: "script-tinyppi-dialog.xml",
    MODE_COMPACT: "script-tinyppi-dialog-compact.xml",
    MODE_SINGLE: "script-tinyppi-dialog-single.xml",
}

# The panel of each mode, as the window files draw it.
PANEL_SIZE = {
    MODE_STANDARD: (471, 546),
    MODE_COMPACT: (1365, 200),
    MODE_SINGLE: (700, 216),
}

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
# The margin every mode keeps to the screen edge.
SCREEN_MARGIN = 50

# The group the window files wrap their panel in, which the dialog moves, and
# the property it holds off drawing itself on until that move has happened.
GROUP_PANEL = 2
PROP_PLACED = "TinyPPI.DialogPlaced"

# The single button layout's one button, which stands for whichever choice
# its step is on.
SINGLE_BUTTON = 1500

# Kodi's left and right. Every other layout moves focus from button to button
# with them; the single button layout has only the one, so they step it.
ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2

# What the stream is, as the skin branches on it. The first is the one that
# has no VS10 modes to offer at all - HDR10+ and HLG, and a Dolby Vision
# grade with an ST 2094-40 payload beside its RPU, which the driver does not
# take the VS10 modes for either. The other three exclude it, so exactly one
# branch is ever on screen: a layout that laid two of them out at once would
# put two panels in the same place.
_HOME = "Window(10000).Property"
_PLAIN_CONDITION = (
    "String.IsEqual(%s(TinyPPI.HdrType),hdr10plus)"
    " | String.Contains(%s(TinyPPI.HdrType),hlg)"
    " | String.IsEqual(%s(TinyPPI.Hdr10PlusPresent),1)" % (_HOME, _HOME, _HOME)
)
_HAS_VS10_CONDITION = (
    "!String.IsEqual(%s(TinyPPI.HdrType),hdr10plus)"
    " + !String.Contains(%s(TinyPPI.HdrType),hlg)"
    " + !String.IsEqual(%s(TinyPPI.Hdr10PlusPresent),1)" % (_HOME, _HOME, _HOME)
)

# The Player Process Info button, which every branch opens with. It is a
# control of its own per branch rather than one shared between them: the
# layouts put it in a different place depending on how many choices follow
# it, and a control can only be in one place.
PPI_LABEL = "[B][CAPITALIZE]$LOCALIZE[10116][/CAPITALIZE][/B]"
PPI_BUTTONS = (1001, 1101, 1201, 1301)

# Every branch, in the order the buttons are laid out: the Player Process
# Info button first, then the VS10 modes. Each is its control id, its name
# and what ui.mode_select runs for it - None for the Player Process Info
# button, which opens the overlay instead.
BRANCHES = (
    {
        "key": "sdr",
        "visible": "String.IsEmpty(%s(TinyPPI.HdrType)) + %s"
                   % (_HOME, _HAS_VS10_CONDITION),
        "buttons": (
            (1001, PPI_LABEL, None),
            (1002, "[B]Original[/B]", "original_sdr"),
            (1003, "[B]SDR → HDR10[/B]", "hdr10"),
            (1004, "[B]SDR → Dolby Vision[/B]", "dv"),
        ),
    },
    {
        "key": "hdr10",
        "visible": "String.IsEqual(%s(TinyPPI.HdrType),hdr10) + %s"
                   % (_HOME, _HAS_VS10_CONDITION),
        "buttons": (
            (1101, PPI_LABEL, None),
            (1005, "[B]HDR10 (Original)[/B]", "original_hdr"),
            (1006, "[B]HDR10 → SDR[/B]", "sdr8"),
            (1008, "[B]HDR10 → Dolby Vision[/B]", "dv"),
        ),
    },
    {
        "key": "dv",
        "visible": "String.Contains(%s(TinyPPI.HdrType),dolby) + %s"
                   % (_HOME, _HAS_VS10_CONDITION),
        "buttons": (
            (1201, PPI_LABEL, None),
            (1012, "[B]Dolby Vision (Original)[/B]", "original_dv"),
            (1013, "[B]Dolby Vision → SDR[/B]", "sdr8"),
        ),
    },
    {
        "key": "plain",
        "visible": _PLAIN_CONDITION,
        "buttons": (
            (1301, PPI_LABEL, None),
        ),
    },
)


def _setting_int(name, default):
    if xbmcaddon is None:
        return default
    try:
        return int(xbmcaddon.Addon().getSettingInt(name))
    except (TypeError, ValueError, RuntimeError):
        return default


def dialog_mode():
    """The selected layout, falling back to the compact bar - the default.

    An unknown value means a settings file from a newer version than this
    code, so it is treated as the default rather than breaking the dialog.
    """
    mode = _setting_int("dialog_mode", MODE_COMPACT)
    return mode if mode in XML_FILES else MODE_COMPACT


def xml_file(mode=None):
    """The window file matching a layout."""
    return XML_FILES[dialog_mode() if mode is None else mode]


def _across(value, low, high):
    """``value`` percent of the way from ``low`` to ``high``, rounded up at .5.

    Rounded half up rather than to even so the middle of a panel with an odd
    number of pixels left over lands where the hand written layout puts it.
    """
    return low + int((high - low) * max(0, min(100, value)) / 100.0 + 0.5)


def left_range(mode):
    """How far a movable panel may travel sideways, margin to margin."""
    width = PANEL_SIZE[mode][0]
    return SCREEN_MARGIN, SCREEN_WIDTH - width - SCREEN_MARGIN


def top_range(mode):
    """How far a panel may travel up and down, margin to margin."""
    height = PANEL_SIZE[mode][1]
    return SCREEN_MARGIN, SCREEN_HEIGHT - height - SCREEN_MARGIN


def panel_position(mode):
    """Where the panel goes, from the two position settings.

    Vertically 0% is a margin below the top edge and 100% rests it on the
    bottom one; horizontally 0% and 100% are the left and right margins. The
    defaults - 50% across and 100% down - rest the panel on the bottom
    margin, in the middle of the screen.
    """
    ceiling, floor = top_range(mode)
    leftmost, rightmost = left_range(mode)
    return (_across(_setting_int("dialog_position_x", 50),
                    leftmost, rightmost),
            _across(_setting_int("dialog_position_y", 100), ceiling, floor))


def branch_for(hdr_type, hdr10plus_present):
    """The branch the dialog is showing, from the two published properties.

    Mirrors the conditions the window files branch on, so the single button
    layout - which has no branch of its own to read and steps through the
    choices from here - offers exactly what the others draw.
    """
    hdr_type = (hdr_type or "").lower()
    if (hdr_type == "hdr10plus" or "hlg" in hdr_type
            or hdr10plus_present == "1"):
        key = "plain"
    elif "dolby" in hdr_type:
        key = "dv"
    elif hdr_type == "hdr10":
        key = "hdr10"
    else:
        key = "sdr"
    for branch in BRANCHES:
        if branch["key"] == key:
            return branch
    return BRANCHES[0]


def plain_label(markup):
    """A button's label with everything the skin resolves already resolved.

    Bold and the rest of Kodi's text markup survive being set from code; a
    ``$LOCALIZE`` does not - a window file is parsed for those and a label set
    at runtime is not - so it is looked up here. Kodi gives the name already
    written the way it wants to be read, and it goes on the button that way:
    the capitalising the other layouts ask for belongs to a row of names
    where one alone would read as an odd one out.
    """
    if "$LOCALIZE[10116]" in markup:
        localized = (xbmc.getLocalizedString(10116) if xbmc is not None
                     else "Player process info")
        markup = markup.replace("[CAPITALIZE]", "").replace("[/CAPITALIZE]", "")
        markup = markup.replace("$LOCALIZE[10116]", localized)
    return markup
