# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Text helpers shared by the snapshot, the player state and the library."""

import re
from typing import Any

from info.dvinfo import is_status_label

# A value straight from a request (query or JSON body): any type, or None.
# The function receiving it validates and converts it.
Unchecked = Any


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


def numbers(value: str) -> list[float]:
    """Return every number in a composite reading."""
    if not value or is_status_label(value):
        return []
    return [float(match) for match in _NUMBER_RE.findall(value)]
