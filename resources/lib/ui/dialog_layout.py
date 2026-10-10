# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Geometry and choices of the VS10 dialog's three layouts.

Single button, bar and panel.  Window files, panel sizes and movement ranges
live here so ``tools/gen_dialog_skins.py`` and the dialog share one
description.  The generator imports this outside Kodi, so Kodi modules are
optional.
"""

from core.constants import HOME_WINDOW_ID

try:  # pragma: no cover - absent when the skin generator runs this
    import xbmc
    from core import settings
except ImportError:
    xbmc = None
    settings = None  # type: ignore[assignment]

# Layout ids and their window files.  The numbers are stored in settings and
# must keep their meaning; the settings list orders them independently.
MODE_DIALOG = 0
MODE_BAR = 1
MODE_SINGLE = 2

XML_FILES = {
    MODE_DIALOG: "script-tinyppi-dialog.xml",
    MODE_BAR: "script-tinyppi-dialog-bar.xml",
    MODE_SINGLE: "script-tinyppi-dialog-single.xml",
}

# Panel size per layout, as drawn by the window files.
PANEL_SIZE = {
    MODE_DIALOG: (471, 546),
    MODE_BAR: (1702, 206),
    MODE_SINGLE: (700, 216),
}

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
# Margin every layout keeps to the screen edge.
SCREEN_MARGIN = 50

# The panel group the dialog moves, and the property that keeps it hidden
# until it has been placed.
GROUP_PANEL = 2
PROP_PLACED = "TinyPPI.DialogPlaced"

# The single-button layout's button; it shows the current choice.
SINGLE_BUTTON = 1500

# Kodi's left and right actions; they step the single-button layout.
ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2

# Skin conditions per stream type.  The plain branch has no VS10 modes
# (HDR10+, HLG, and DV with an ST 2094-40 payload); the others exclude it,
# so exactly one branch is ever visible.
_HOME = f"Window({HOME_WINDOW_ID}).Property"
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

# The Player Process Info button that starts every branch; one control per
# branch, since its position depends on the number of choices.
PPI_LABEL = "[B][CAPITALIZE]$LOCALIZE[10116][/CAPITALIZE][/B]"
PPI_BUTTONS = (1001, 1101, 1201, 1301)

# Every branch with its buttons in layout order: (control id, label, mode
# for ui.mode_select).  The mode is None for the Player Process Info button,
# which opens the overlay.
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


def _setting_int(name: str, default: int) -> int:
    if settings is None:
        return default
    try:
        return int(settings.addon().getSettingInt(name))
    except (TypeError, ValueError, RuntimeError):
        return default


def dialog_mode() -> int:
    """Return the selected layout, or the single button (the default).

    Unknown values (from a newer version) fall back to the default.
    """
    mode = _setting_int("dialog_mode", MODE_SINGLE)
    return mode if mode in XML_FILES else MODE_SINGLE


def xml_file(mode: int | None = None) -> str:
    """Return the window file for *mode* (default: the selected layout)."""
    return XML_FILES[dialog_mode() if mode is None else mode]


def _across(value: int, low: int, high: int) -> int:
    """Return *value* percent of the way from *low* to *high*.

    Rounded half up (not to even) so a centred panel lands where the
    hand-written layout puts it.
    """
    return low + int((high - low) * max(0, min(100, value)) / 100.0 + 0.5)


def left_range(mode: int) -> tuple[int, int]:
    """Return the horizontal range of the panel's left edge."""
    width = PANEL_SIZE[mode][0]
    return SCREEN_MARGIN, SCREEN_WIDTH - width - SCREEN_MARGIN


def top_range(mode: int) -> tuple[int, int]:
    """Return the vertical range of the panel's top edge."""
    height = PANEL_SIZE[mode][1]
    return SCREEN_MARGIN, SCREEN_HEIGHT - height - SCREEN_MARGIN


def panel_position(mode: int) -> tuple[int, int]:
    """Return the panel position from the two position settings.

    0% and 100% are the margins on each axis; the defaults (50% across,
    100% down) centre the panel at the bottom.
    """
    ceiling, floor = top_range(mode)
    leftmost, rightmost = left_range(mode)
    return (_across(_setting_int("dialog_position_x", 50),
                    leftmost, rightmost),
            _across(_setting_int("dialog_position_y", 100), ceiling, floor))


def branch_for(hdr_type: str | None, hdr10plus_present: str) -> dict:
    """Return the branch for the published HDR type and HDR10+ flag.

    Mirrors the window files' conditions, so the single-button layout
    (which steps through the choices from here) offers the same options.
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


def plain_label(markup: str) -> str:
    """Return *markup* with ``$LOCALIZE`` resolved, for a label set in code.

    Text markup survives ``setLabel``, but ``$LOCALIZE`` is only resolved in
    window files.  The capitalisation used in the button rows is dropped,
    since a single button reads better with Kodi's own spelling.
    """
    if "$LOCALIZE[10116]" in markup:
        localized = (xbmc.getLocalizedString(10116) if xbmc is not None
                     else "Player process info")
        markup = markup.replace("[CAPITALIZE]", "").replace("[/CAPITALIZE]", "")
        markup = markup.replace("$LOCALIZE[10116]", localized)
    return markup
