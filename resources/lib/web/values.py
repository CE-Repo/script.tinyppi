# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Text helpers shared by the snapshot, the player state and the library."""

import re
from typing import Any

from info.dvinfo import is_status_label

# A value straight from a request (query or JSON body): any type, or None.
# The function receiving it validates and converts it.
Unchecked = Any

# A JSON object from Kodi (a JSON-RPC answer, or one of its rows): whatever
# Kodi sent, read with ``get`` and checked where a value is used.
Json = dict[str, Any]


def library_id(value: Unchecked) -> int:
    """Return *value* as a library id (a positive integer), or 0.

    JSON true/false and fractions are refused rather than read as 1 or cut
    down to the id below; a query string's digits are accepted.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, float):
        if not value.is_integer():
            return 0
        value = int(value)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Kodi text markup (e.g. the themed FEL/MEL tag) is stripped rather than
# turned into HTML, which would mean building HTML from file names.
_MARKUP_RE = re.compile(r"\[/?(?:COLOR|B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|CR)[^\]]*\]",
                        re.IGNORECASE)


# The overlay's "l" separator (see properties._DISPLAY_SEPARATOR) is turned
# back into a pipe for the browser.
_SEPARATOR_RE = re.compile(r" l ")


def clean_value(value: str) -> str:
    """Return *value* without markup and with pipe separators."""
    if not value:
        return value
    return _SEPARATOR_RE.sub(" | ", _MARKUP_RE.sub("", value)).strip()


# Kodi writes a line break into a library text as [CR].
_LINE_BREAK_RE = re.compile(r"\[CR\]", re.IGNORECASE)


def plain_text(value: str) -> str:
    """Return a library text (a tagline, a plot) without markup.

    Its line breaks are kept; the overlay's separator is not looked for, as
    a plot is prose and " l " in it is a word.
    """
    if not value:
        return value
    return _MARKUP_RE.sub("", _LINE_BREAK_RE.sub("\n", value)).strip()


# Kodi joins the directors and studios of a list InfoLabel with its item
# separator (" / ", unless advancedsettings.xml sets another, which is then
# read as one name) and the cast one name a line.
_ITEM_RE = re.compile(r" / |\n")
# A name is a line of a card, not a paragraph; a longer one is cut off.
_NAME_LIMIT = 80


def name_list(value: str, limit: int | None = None) -> tuple[list[str], bool]:
    """Return the first *limit* names a list InfoLabel holds (all of them
    for None), in Kodi's order -- the cast by billing -- each once, and
    whether it holds more."""
    names: list[str] = []
    for item in _ITEM_RE.split(plain_text(value)):
        name = item.strip()[:_NAME_LIMIT].rstrip()
        if name and name not in names:
            if len(names) == limit:
                return names, True
            names.append(name)
    return names, False


def numbers(value: str) -> list[float]:
    """Return every number in a composite reading."""
    if not value or is_status_label(value):
        return []
    return [float(match) for match in _NUMBER_RE.findall(value)]
