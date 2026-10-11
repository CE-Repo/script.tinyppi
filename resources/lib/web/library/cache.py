# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The cached lists, the revision that versions them and pending drops."""

import importlib
import threading
import time
from collections.abc import Callable
from typing import Any

from web.library.entries import ArtPaths, Continuing, Episodes, Films, Shows

# Cache lifetime; changes normally arrive as notifications (see
# ``invalidate``), so this only covers missed ones.
_TTL = 300.0

# Delays after playback stops before the lists are dropped.  Kodi writes the
# resume point and play count after the stop notification (and announces
# only the play count), so the drop waits.  The second delay covers a video
# database on a network share; an extra drop costs one query.
_SETTLE = (1.5, 5.0)

# Item notifications come in bursts (a scan sends one per item), and every
# drop makes each open page re-read its list, so a burst is dropped once
# after _QUIET seconds without a new one (see ``changed``).  A long scan
# still reaches open pages every _BURST_LIMIT seconds.
_QUIET       = 2.0
_BURST_LIMIT = 10.0

# A list's reader: queries Kodi and returns the list as kept.
type Reader[Kept] = Callable[[], Kept]


class Slot[Kept]:
    """One cached list, read on demand and kept for ``_TTL``.

    Readers arriving while a read runs wait for its answer instead of
    querying again.  A read that a drop overtook is handed to its caller but
    not kept: it may predate the change that caused the drop, and keeping it
    would serve the old list until the TTL ran out.
    """

    def __init__(self, cache: Cache, read: Reader[Kept]) -> None:
        self._cache   = cache
        self._read    = read
        self._value: Kept | None = None
        self._read_at = 0.0
        # Held for the length of a read: one query per list at a time.
        self._reading = threading.Lock()

    def _fresh(self) -> Kept | None:
        """Return the kept list while it is fresh (cache lock held)."""
        if self._value is not None and time.monotonic() - self._read_at < _TTL:
            return self._value
        return None

    def peek(self) -> Kept | None:
        """Return the kept list without reading, or None."""
        with self._cache.lock:
            return self._value

    def clear(self) -> None:
        """Forget the kept list (cache lock held)."""
        self._value   = None
        self._read_at = 0.0

    def get(self) -> Kept:
        """Return the list, reading it when none is kept or it is stale."""
        cache = self._cache
        with cache.lock:
            held = self._fresh()
        if held is not None:
            return held

        with self._reading:
            with cache.lock:
                # Read by the reader this one waited for.
                held = self._fresh()
                started = cache.revision
            if held is not None:
                return held
            built = self._read()
            with cache.lock:
                if cache.revision == started:
                    self._value   = built
                    self._read_at = time.monotonic()
        return built


class Cache:
    """The cached lists, the revision that versions them and pending drops.

    The revision is bumped on every drop and sent with every snapshot (see
    web/producer.py); clients re-read their lists when it changes.  The
    readers of the three whole lists are handed in, since they live in the
    modules that use this one (see ``web/library/__init__.py``).
    """

    def __init__(self, films: Reader[Films], shows: Reader[Shows],
                 continuing: Reader[Continuing]) -> None:
        self.lock     = threading.Lock()
        self.revision = 0
        self.films      = Slot(self, films)
        self.shows      = Slot(self, shows)
        # Partly watched films and episodes (see ``progress.continuing``).
        self.continuing = Slot(self, continuing)
        # Episodes of opened shows, by show id.
        self.episodes: dict[int, Slot[Episodes]] = {}
        # Episode art paths by episode id (artwork URLs name only the
        # episode).
        self.episode_art: ArtPaths = {}
        # Due times of the drops after playback stopped, soonest first.
        self._settling: list[float] = []
        # Start and due time of the drop for a burst of item notifications.
        self._burst_since: float | None = None
        self._burst_due:   float | None = None

    def drop(self) -> None:
        """Drop every list and bump the revision."""
        with self.lock:
            self._drop()

    def _drop(self) -> None:
        # Lock held.  A pending burst is covered by this drop.
        self.films.clear()
        self.shows.clear()
        self.continuing.clear()
        self.episodes.clear()
        self.episode_art.clear()
        self._burst_since = None
        self._burst_due   = None
        self.revision += 1

    def settle(self) -> None:
        """Schedule the drops after playback stopped (see ``_SETTLE``)."""
        now = time.monotonic()
        with self.lock:
            self._settling = sorted(now + delay for delay in _SETTLE)

    def burst(self) -> None:
        """Schedule, or postpone, the drop for a burst (see ``_QUIET``)."""
        now = time.monotonic()
        with self.lock:
            if self._burst_since is None:
                self._burst_since = now
            self._burst_due = min(now + _QUIET,
                                  self._burst_since + _BURST_LIMIT)

    def current(self) -> int:
        """Return the revision, running the drops that have fallen due."""
        now = time.monotonic()
        with self.lock:
            due = False
            while self._settling and self._settling[0] <= now:
                self._settling.pop(0)
                due = True
            if self._burst_due is not None and self._burst_due <= now:
                due = True
            if due:
                self._drop()
            return self.revision

    def remember_art(self, art: ArtPaths) -> None:
        """Register episode art paths read with a list."""
        with self.lock:
            self.episode_art.update(art)

    def episode_art_of(self, episode_id: int) -> dict[str, str] | None:
        """Return an episode's registered art paths, or None."""
        with self.lock:
            return self.episode_art.get(episode_id)


def _late(module: str, name: str) -> Reader[Any]:
    """Return a reader that finds ``web.library.<module>.<name>`` when it reads.

    The modules holding the readers import this one, so they cannot be
    named at import time (and its list's type is checked there).
    """
    def read() -> Any:
        reader: Reader[Any] = getattr(importlib.import_module(f"web.library.{module}"), name)
        return reader()
    return read


def new_cache() -> Cache:
    """Return an empty cache reading the package's lists."""
    return Cache(_late("films", "read"), _late("series", "read_shows"),
                 _late("progress", "load"))


# The one cache.  Modules look it up here on every use (``cache.lists``) and
# never keep it, so a test can swap in a fresh one.
lists = new_cache()


# --- Drops -----------------------------------------------------------------

def invalidate() -> None:
    """Drop all cached lists and bump the revision.

    Called on library changes and after playback starts or a title is
    marked; reads nothing itself.
    """
    lists.drop()


def changed() -> None:
    """Drop the lists once a burst of item notifications has passed.

    Called by the monitor for each ``OnUpdate`` / ``OnRemove``; the drop
    itself runs on the producer's cadence (see ``revision``).
    """
    lists.burst()


def settle() -> None:
    """Schedule cache drops shortly after playback stopped (see ``_SETTLE``).

    Kodi writes the resume point after the stop notification and does not
    announce it, so dropping right away would re-read stale rows.
    """
    lists.settle()


def revision() -> int:
    """Return the library revision, running due deferred drops first.

    Called on the producer's cadence, which serves as the add-on's timer
    (an extra timer thread would delay Kodi's shutdown).
    """
    return lists.current()
