# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The film and series library shown on the dashboard's idle page.

Lists are read over JSON-RPC once and cached, since large libraries are slow
to query.  The cache is dropped when Kodi reports a library change (see
``service/monitor.py``), and each drop bumps ``revision``, which travels
with every snapshot so open pages re-read their lists.

Only artwork paths are kept, never the pictures (the browser caches those,
see ``CACHE`` in ``web/artwork.py``).  Episodes of a series are read only
when the series is opened, then cached alongside.

- ``cache``: the cached lists, their revision and the deferred drops
- ``common``: the JSON-RPC seam and what the rows share
- ``entries``: the shapes of the lists, as cached and as sent
- ``films``, ``series``: the two shelves and starting a title
- ``progress``: the "continue watching" row
- ``marks``: seen, unseen and clearing resume points

The rest of the add-on uses only the names below.
"""

from web.library import cache, common, films, marks, progress, series
from web.library.cache import changed, invalidate, new_cache, revision, settle
from web.library.films import art_path, catalogue, movies, play
from web.library.marks import clear_resume, set_watched
from web.library.progress import continuing
from web.library.series import (
    episode_art_path,
    episodes,
    play_episode,
    show_art_path,
    shows,
)

__all__ = [
    "art_path", "catalogue", "changed", "clear_resume", "continuing",
    "episode_art_path", "episodes", "invalidate", "movies", "new_cache",
    "play", "play_episode", "revision", "set_watched", "settle",
    "show_art_path", "shows",
    "cache", "common", "films", "marks", "progress", "series",
]

