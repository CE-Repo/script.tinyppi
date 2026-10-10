# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A one-entry memo for readings recomputed on every tick."""

from collections.abc import Hashable
from typing import Any


class KeyedMemo:
    """Remember one value for the key it was computed for.

    For readings asked for several times a second that only change with
    their input (a path, a pixel format): the work runs again only for a new
    key.  Key and value are swapped as one tuple, so a reader on another
    thread never pairs one key with another key's value.
    """

    __slots__ = ("_entry",)

    def __init__(self) -> None:
        self._entry: tuple | None = None

    def get(self, key: Hashable) -> Any:
        """Return the value held for *key*, or None."""
        entry = self._entry
        if entry is not None and entry[0] == key:
            return entry[1]
        return None

    def put(self, key: Hashable, value: Any) -> None:

        """Hold *value* for *key*, replacing the previous entry."""
        self._entry = (key, value)
