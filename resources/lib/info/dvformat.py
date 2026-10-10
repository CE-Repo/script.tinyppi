# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Row kinds and value formatting for the Dolby Vision metadata view.

Shared by ``info.dvmetadata`` and ``info.dvcomposer``; ui.dvmetadata reads
the row kinds through ``info.dvmetadata``.
"""

import xbmc

# Row kinds for ui.dvmetadata: a heading, a name / value pair, a full-width
# line, and an empty row.  Kodi lists scroll by a uniform item size, so the
# space above a heading is an empty row rather than a taller layout.
SECTION = "section"
ROW     = "row"
WIDE    = "wide"
SPACE   = "space"

# Table rows: column headings and readings, with cells as a list.  A
# proportional font cannot be padded into columns, so the skin draws each
# cell in a fixed slot.
HEADINGS = "headings"
COLUMNS  = "columns"

# Cells per table row: the 1195 px list holds a 235 px name column and six
# 160 px cells.  Wider levels (L8 has eight controls) continue in a second
# table below.
MAX_COLUMNS = 6

# Cells per row on the compact grid, used for nine-column tables such as the
# HDR10+ distribution.
MAX_COMPACT_COLUMNS = 9

# Internal marker for "no reading"; _section drops rows holding it.
EMPTY = "—"

# Origin of a section's block.  Only CACHED is shown, next to the heading of
# a section held from an earlier frame (see _HeldBlocks).
LIVE   = "Live"
CACHED = "Cached"

# Separator in composite values ("2081 | 1000").
_JOIN = " | "


def text(value: object) -> str:
    """Return *value* as a stripped string, or EMPTY."""
    if value is None:
        return EMPTY
    stripped = str(value).strip()
    return stripped or EMPTY


def num(value: object) -> str:
    """Format a number without a redundant ``.0``, or EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def lum(value: object) -> str:
    """Format a luminance in nits, like dvinfo (see ``info.dvinfo._fmt_lum``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if value and abs(value) < 1.0:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def scaled(value: object) -> str:
    """Format a 0..1 or -1..1 value (UI trims, knee point), or EMPTY.

    EMPTY is also how a disabled trim control reads.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.4f}"


def percent(value: object) -> str:
    """Format a percentage to one decimal, or EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f} %"


def flag(value: object) -> str:
    """Format a flag as Kodi's localized Yes / No, or EMPTY."""
    if value is None:
        return EMPTY
    return xbmc.getLocalizedString(107 if value else 106)


def joined(*values: str) -> str:
    """Join the present parts of a composite value, or return EMPTY."""
    present = [value for value in values if value != EMPTY]
    return _JOIN.join(present) if present else EMPTY


def coords(pair: object) -> str:
    """Format a CIE ``(x, y)`` pair of raw codes or floats."""
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        return EMPTY
    x, y = pair
    if isinstance(x, float) or isinstance(y, float):
        return joined(f"{x:.4f}", f"{y:.4f}")
    return joined(num(x), num(y))
