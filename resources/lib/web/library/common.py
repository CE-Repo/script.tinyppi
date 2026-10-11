# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What the library's lists share: the JSON-RPC seam and the row helpers."""

import json
import math
import zlib
from collections.abc import Callable, Mapping, Sequence

import xbmc
from core.log import channel
from web import player
from web.library import cache
from web.library.entries import Rated
from web.values import Json, clean_value

# Every query of the library goes through here, so the tests answer them
# from a fake video database by replacing this one name.
rpc = player.rpc

log = channel("library")

# Art keys for a poster, best first (``thumb`` for unscraped files).
POSTER_KEYS = ("poster", "thumb")
FANART_KEYS = ("fanart",)

# Episode picture keys: the still, then season or show poster (as Kodi).
EPISODE_PICTURE_KEYS = ("thumb", "season.poster", "tvshow.poster")

# Rating sources (Kodi key, label), best first.  ``themoviedb`` and ``tmdb``
# come from different scraper versions.
_RATING_SOURCES = (("imdb", "imdb"),
                   ("themoviedb", "tmdb"),
                   ("tmdb", "tmdb"))

# Bump when an art URL starts returning a different picture: responses are
# cached as immutable, so only a new tag replaces them (see web/artwork.py).
_ART_REVISION = "#2"


def rows_of(answer: Json, key: str) -> list[Json]:
    """Return the rows (JSON objects) under *key* of a JSON-RPC answer.

    Anything else Kodi sent there is left out.
    """
    result = answer.get("result")
    rows = (result.get(key) or []) if isinstance(result, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def clean_title(row: Json) -> str:
    """Return a row's title (or label) as shown, or ''."""
    return clean_value(str(row.get("title") or row.get("label") or ""))


def art_of(row: Json) -> Json:
    """Return a JSON-RPC row's ``art`` mapping, or an empty one."""
    pictures = row.get("art")
    return pictures if isinstance(pictures, dict) else {}


def picture(pictures: Json, keys: tuple[str, ...]) -> str:
    """Return the first non-empty path among *keys*, or ''."""
    for key in keys:
        path = pictures.get(key)
        if isinstance(path, str) and path.strip():
            return path.strip()
    return ""


def number(row: Json, key: str, low: int = 1) -> int | None:
    """Return *row*'s int *key* when it is at least *low*, else None.

    For years, runtimes, season and episode numbers; anything else (a
    missing value, 0 for "unknown") is left out of the entry.
    """
    value = row.get(key)
    if isinstance(value, int) and value >= low:
        return value
    return None


def rate(entry: Rated, ratings: object) -> None:
    """Set the best available rating and its source on *entry*.

    Nothing is set without a valid rating (e.g. unscraped files).
    """
    if not isinstance(ratings, dict):
        return
    for source, name in _RATING_SOURCES:
        held = ratings.get(source)
        if not isinstance(held, dict):
            continue
        try:
            value = float(held.get("rating") or 0)
        except (TypeError, ValueError):
            continue
        # Ratings are out of ten; anything else is scraper junk.
        if not 0 < value <= 10:
            continue
        entry["rating"] = round(value, 1)
        entry["rating_from"] = name
        return


def resume_of(resume: object) -> int:
    """Return the resume position in seconds, or 0 below 30 seconds."""
    if not isinstance(resume, dict):
        return 0
    try:
        position = float(resume.get("position") or 0)
        total = float(resume.get("total") or 0)
    except (TypeError, ValueError):
        return 0
    # json.loads reads NaN and Infinity: NaN slips past the checks below and
    # int() fails on both.
    if not (math.isfinite(position) and math.isfinite(total)):
        return 0
    if position < 30 or total <= 0 or position >= total:
        return 0
    return int(position)


def added(value: object) -> str:
    """Return the date added as Kodi's sortable text, or ''."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or value.startswith("0000"):
        return ""
    return value


def signature(rows: Sequence[Mapping[str, object]], head: str = "") -> str:
    """Return a checksum of *rows* as sent, for a list's tag.

    Every field counts: the tag is the list's ETag (see web/routes.py), so a
    field left out would never reach a page holding the list.
    """
    checksum = zlib.crc32(head.encode("utf-8", "replace"))
    for row in rows:
        sent = json.dumps(row, sort_keys=True, ensure_ascii=False)
        checksum = zlib.crc32(sent.encode("utf-8", "replace"), checksum)
    return f"{checksum:08x}"


def tag(path: str) -> str:
    """Return a short, stable tag for a picture path (used in its URL)."""
    if not path:
        return ""
    named = (path + _ART_REVISION).encode("utf-8", "replace")
    return f"{zlib.crc32(named):08x}"


def resume_option(resume: bool, point: Callable[[], int]) -> bool | None:
    """Return Player.Open's resume option.

    False to start over, True to resume from the resume point (*point* is
    asked only then), None (no option) when there is nothing to resume.
    """
    if not resume:
        return False
    return True if point() else None


def open_item(item: dict[str, int], resume: bool | None, what: str) -> bool:
    """Play a library *item* and return whether Kodi accepted it.

    The resume option is explicit whenever there is a choice, so Kodi does
    not ask on the TV.  JSON-RPC reports success, unlike a builtin.
    """
    params: dict[str, object] = {"item": item}
    if resume is not None:
        params["options"] = {"resume": resume}
    if rpc("Player.Open", params).get("result") != "OK":
        return False
    log(f"{what} started from the dashboard", xbmc.LOGINFO)
    # Lists change with playback; drop them.
    cache.invalidate()
    return True
