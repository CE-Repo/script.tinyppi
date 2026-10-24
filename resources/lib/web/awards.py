# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The big awards the playing title won or was nominated for, for the plot
card: the Academy Awards, the Golden Globes, the BAFTAs and the Primetime
Emmys.

They are read from ``resources/data/awards.json``, by the title's TMDb id --
a film's own, an episode's show's -- which ``tools/gen_awards.py`` writes
from TheMovieDb Helper's list (see there).  No key and no request: a title
the list does not hold has none to show.  The file is read the first time a
title is looked up, and kept.
"""

import json
import os
from functools import cache

from web.payloads import Award

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data",
                     "awards.json")

# The awards in the order the plot card shows them.
_ORDER = ("oscar", "globe", "bafta", "emmy")
# A category is a label in a tooltip, and a title wins a handful at most.
_CATEGORY_LIMIT = 80
_WIN_LIMIT = 20


@cache
def _table() -> dict[str, dict[str, object]]:
    """Return the awards of every title, by kind ("movie", "tv") and TMDb id;
    empty if the file cannot be read."""
    try:
        with open(_FILE, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _count(value: object) -> int:
    """Return *value* if JSON gave it as a whole number above 0, else 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _award(key: str, held: object) -> Award | None:
    """Return one award of a title as the page gets it -- what it won and how
    many more it was nominated for -- or None for junk or for nothing."""
    if not isinstance(held, list) or len(held) != 2 or not isinstance(held[0], list):
        return None
    wins, more = held
    won = [win[:_CATEGORY_LIMIT] for win in wins if isinstance(win, str) and win][:_WIN_LIMIT]
    nominated = _count(more)
    return {"award": key, "won": won, "nominated": nominated} if won or nominated else None


def awards_of(kind: str, tmdb: str) -> list[Award]:
    """Return the awards the title of *kind* ("movie", "tv") with TMDb id
    *tmdb* won or was nominated for, in the order they are shown."""
    titles = _table().get(kind)
    held = titles.get(tmdb) if isinstance(titles, dict) and tmdb else None
    if not isinstance(held, dict):
        return []
    found = (_award(key, held.get(key)) for key in _ORDER)
    return [award for award in found if award]
