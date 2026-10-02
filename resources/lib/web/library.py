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
"""

import threading
import time
import zlib

import xbmc

from core.log import channel
from web.snapshot import clean_value, rpc

# Film properties the tiles need.  ``dateadded`` feeds the "recently added"
# row (see ``_added``), read here so the row matches the wall.
_PROPERTIES = ("title", "year", "art", "runtime", "playcount", "resume",
               "ratings", "dateadded")

# Art keys for a film's poster, best first (``thumb`` for unscraped files).
_POSTER_KEYS = ("poster", "thumb")
_FANART_KEYS = ("fanart",)

# Rating sources (Kodi key, label), best first.  ``themoviedb`` and ``tmdb``
# come from different scraper versions.
_RATING_SOURCES = (("imdb", "imdb"),
                   ("themoviedb", "tmdb"),
                   ("tmdb", "tmdb"))

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


_log = channel("library")


# --- The cache -------------------------------------------------------------

class _Slot:
    """One cached list, read on demand and kept for ``_TTL``.

    Readers arriving while a read runs wait for its answer instead of
    querying again.  A read that a drop overtook is handed to its caller but
    not kept: it may predate the change that caused the drop, and keeping it
    would serve the old list until the TTL ran out.
    """

    def __init__(self, cache: "_Cache", read) -> None:
        self._cache   = cache
        self._read    = read
        self._value: dict | None = None
        self._read_at = 0.0
        # Held for the length of a read: one query per list at a time.
        self._reading = threading.Lock()

    def _fresh(self) -> dict | None:
        """Return the kept list while it is fresh (cache lock held)."""
        if self._value is not None and time.monotonic() - self._read_at < _TTL:
            return self._value
        return None

    def peek(self) -> dict | None:
        """Return the kept list without reading, or None."""
        with self._cache.lock:
            return self._value

    def clear(self) -> None:
        """Forget the kept list (cache lock held)."""
        self._value   = None
        self._read_at = 0.0

    def get(self) -> dict:
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


class _Cache:
    """The cached lists, the revision that versions them and pending drops.

    The revision is bumped on every drop and sent with every snapshot (see
    web/producer.py); clients re-read their lists when it changes.
    """

    def __init__(self) -> None:
        self.lock     = threading.Lock()
        self.revision = 0
        self.films      = _Slot(self, _read)
        self.shows      = _Slot(self, _read_shows)
        # Partly watched films and episodes (see ``continuing``).
        self.continuing = _Slot(self, _load_continuing)
        # Episodes of opened shows, by show id.
        self.episodes: dict[int, _Slot] = {}
        # Episode art paths by episode id (artwork URLs name only the
        # episode).
        self.episode_art: dict[int, dict[str, str]] = {}
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
        for slot in (self.films, self.shows, self.continuing):
            slot.clear()
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


# --- The list --------------------------------------------------------------

def invalidate() -> None:
    """Drop all cached lists and bump the revision.

    Called on library changes; reads nothing itself.
    """
    _cache.drop()


def changed() -> None:
    """Drop the lists once a burst of item notifications has passed.

    Called by the monitor for each ``OnUpdate`` / ``OnRemove``; the drop
    itself runs on the producer's cadence (see ``revision``).
    """
    _cache.burst()


def settle() -> None:
    """Schedule cache drops shortly after playback stopped (see ``_SETTLE``).

    Kodi writes the resume point after the stop notification and does not
    announce it, so dropping right away would re-read stale rows.
    """
    _cache.settle()


def revision() -> int:
    """Return the library revision, running due deferred drops first.

    Called on the producer's cadence, which serves as the add-on's timer
    (an extra timer thread would delay Kodi's shutdown).
    """
    return _cache.current()


def catalogue() -> dict:
    """Return the films as ``{"movies": [...], "art": {...}, "tag": str}``.

    ``tag`` changes only with the list (for 304 answers).
    """
    return _cache.films.get()


def movies() -> dict:
    """Return the film list for clients (without the art paths)."""
    held = catalogue()
    return {"movies": held["movies"], "count": len(held["movies"]),
            "tag": held["tag"]}


def art_path(movie_id: int, kind: str) -> str:
    """Return a film's raw artwork path from the cached list, or ''."""
    entry = catalogue()["art"].get(int(movie_id)) or {}
    return entry.get(kind, "")


def _read() -> dict:
    answer = rpc("VideoLibrary.GetMovies", {
        "properties": list(_PROPERTIES),
        # Kodi sorts by sort title, ignoring articles.
        "sort": {"method": "sorttitle", "order": "ascending",
                 "ignorearticle": True},
    })
    error = answer.get("error")
    if error:
        # No database, or one being upgraded: debug only, the page retries.
        _log(f"VideoLibrary.GetMovies failed: {error}")
        return {"movies": [], "art": {}, "tag": "none"}

    result = answer.get("result")
    rows = (result.get("movies") or []) if isinstance(result, dict) else []

    films: list[dict] = []
    art: dict[int, dict[str, str]] = {}
    signature = zlib.crc32(b"")

    for row in rows:
        if not isinstance(row, dict):
            continue
        movie_id = row.get("movieid")
        if not isinstance(movie_id, int):
            continue
        title = clean_value(str(row.get("title") or row.get("label") or ""))
        if not title:
            continue

        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        poster = _picture(pictures, _POSTER_KEYS)
        art[movie_id] = {"poster": poster,
                         "fanart": _picture(pictures, _FANART_KEYS)}

        film = {"id": movie_id, "title": title, "poster": _tag(poster)}
        year = row.get("year")
        if isinstance(year, int) and year > 0:
            film["year"] = year
        runtime = row.get("runtime")
        if isinstance(runtime, int) and runtime > 0:
            film["duration"] = runtime
        if isinstance(row.get("playcount"), int) and row["playcount"] > 0:
            film["watched"] = True
        resume = _resume(row.get("resume"))
        if resume:
            film["resume"] = resume
        _rate(film, row.get("ratings"))
        added = _added(row.get("dateadded"))
        if added:
            film["added"] = added
        films.append(film)

        signature = zlib.crc32(
            f"{movie_id}\x1f{title}\x1f{film['poster']}\x1f"
            f"{film.get('resume', 0)}\x1f{film.get('watched', False)}\x1f"
            f"{film.get('duration', 0)}\x1f{film.get('rating', 0)}\x1f"
            f"{added}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(films)} films read from the video database", xbmc.LOGINFO)
    return {"movies": films, "art": art,
            "tag": f"{len(films):x}-{signature:08x}"}


def _picture(pictures: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        path = pictures.get(key)
        if isinstance(path, str) and path.strip():
            return path.strip()
    return ""


def _rate(entry: dict, ratings) -> None:
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


def _resume(resume) -> int:
    """Return the resume position in seconds, or 0 below 30 seconds."""
    if not isinstance(resume, dict):
        return 0
    try:
        position = float(resume.get("position") or 0)
        total = float(resume.get("total") or 0)
    except (TypeError, ValueError):
        return 0
    if position < 30 or total <= 0 or position >= total:
        return 0
    return int(position)


# Bump when an art URL starts returning a different picture: responses are
# cached as immutable, so only a new tag replaces them (see web/artwork.py).
_ART_REVISION = "#2"


def _added(value) -> str:
    """Return the date added as Kodi's sortable text, or ''."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or value.startswith("0000"):
        return ""
    return value


def _tag(path: str) -> str:
    """Return a short, stable tag for a picture path (used in its URL)."""
    if not path:
        return ""
    named = (path + _ART_REVISION).encode("utf-8", "replace")
    return f"{zlib.crc32(named):08x}"


# --- Starting one ----------------------------------------------------------

def play(movie_id, resume: bool = True) -> bool:
    """Play a film and return whether Kodi accepted it.

    Resumes when a resume point exists, unless *resume* is False; the option
    is always explicit so Kodi does not ask on the TV.  JSON-RPC reports
    success, unlike a builtin.
    """
    try:
        wanted = int(movie_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False

    params: dict = {"item": {"movieid": wanted}}
    if not resume:
        params["options"] = {"resume": False}
    elif _resume_point(wanted):
        params["options"] = {"resume": True}
    if rpc("Player.Open", params).get("result") != "OK":
        return False
    _log(f"film {wanted} started from the dashboard", xbmc.LOGINFO)
    # Lists change with playback; drop them.
    invalidate()
    return True


def _resume_point(movie_id: int) -> int:
    for film in catalogue()["movies"]:
        if film["id"] == movie_id:
            return int(film.get("resume") or 0)
    return 0


# --- The series ------------------------------------------------------------

# Show properties the tiles need.  A show's ``dateadded`` is its newest
# episode's, so new episodes put the show on the "recently added" row.
_SHOW_PROPERTIES = ("title", "year", "art", "episode", "watchedepisodes",
                    "ratings", "dateadded")

# Episode properties the episode list needs.
_EPISODE_PROPERTIES = ("title", "season", "episode", "art", "runtime",
                       "playcount", "resume")

# Episode picture keys: the still, then season or show poster (as Kodi).
_EPISODE_PICTURE_KEYS = ("thumb", "season.poster", "tvshow.poster")


def shows() -> dict:
    """Return the show list for clients."""
    held = _show_catalogue()
    return {"shows": held["shows"], "count": len(held["shows"]),
            "tag": held["tag"]}


def episodes(show_id) -> dict | None:
    """Return the episodes of show *show_id*, or None for an unknown show.

    Read on first open, then cached.
    """
    try:
        wanted = int(show_id)
    except (TypeError, ValueError):
        return None
    if wanted <= 0:
        return None

    with _cache.lock:
        slot = _cache.episodes.get(wanted)
    if slot is None:
        # The title comes from the cached show list.
        title = ""
        for show in _show_catalogue()["shows"]:
            if show["id"] == wanted:
                title = show["title"]
                break
        if not title:
            return None
        with _cache.lock:
            slot = _cache.episodes.setdefault(
                wanted, _Slot(_cache, lambda: _load_episodes(wanted, title)))

    held = slot.get()
    return {"tvshowid": wanted, "title": held["title"],
            "episodes": held["episodes"], "count": len(held["episodes"]),
            "tag": held["tag"]}


def show_art_path(show_id, kind: str) -> str:
    """Return a show's raw artwork path, or ''."""
    try:
        entry = _show_catalogue()["art"].get(int(show_id)) or {}
    except (TypeError, ValueError):
        return ""
    return entry.get(kind, "")


def episode_art_path(episode_id, kind: str) -> str:
    """Return an episode still's raw path, or ''.

    Only episodes of opened shows or on the "continue" row are known, the
    only ways their URLs can reach a browser.
    """
    try:
        wanted = int(episode_id)
    except (TypeError, ValueError):
        return ""
    with _cache.lock:
        entry = _cache.episode_art.get(wanted)
    if entry is None and _cache.continuing.peek() is None:
        # Cache dropped since: re-read the "continue" row, the one list with
        # episodes of unopened shows.
        continuing()
        with _cache.lock:
            entry = _cache.episode_art.get(wanted)
    return (entry or {}).get(kind, "")


def _show_catalogue() -> dict:
    """Return the shows as ``{"shows": [...], "art": {...}, "tag": str}``."""
    return _cache.shows.get()


def _read_shows() -> dict:
    answer = rpc("VideoLibrary.GetTVShows", {
        "properties": list(_SHOW_PROPERTIES),
        "sort": {"method": "sorttitle", "order": "ascending",
                 "ignorearticle": True},
    })
    error = answer.get("error")
    if error:
        _log(f"VideoLibrary.GetTVShows failed: {error}")
        return {"shows": [], "art": {}, "tag": "none"}

    result = answer.get("result")
    rows = (result.get("tvshows") or []) if isinstance(result, dict) else []

    series: list[dict] = []
    art: dict[int, dict[str, str]] = {}
    signature = zlib.crc32(b"")

    for row in rows:
        if not isinstance(row, dict):
            continue
        show_id = row.get("tvshowid")
        if not isinstance(show_id, int):
            continue
        title = clean_value(str(row.get("title") or row.get("label") or ""))
        if not title:
            continue

        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        poster = _picture(pictures, _POSTER_KEYS)
        fanart = _picture(pictures, _FANART_KEYS)
        art[show_id] = {"poster": poster, "fanart": fanart}

        # Shows carry their fanart tag too: the episode view shows it.
        show = {"id": show_id, "title": title,
                "poster": _tag(poster), "fanart": _tag(fanart)}
        year = row.get("year")
        if isinstance(year, int) and year > 0:
            show["year"] = year
        total = row.get("episode")
        seen = row.get("watchedepisodes")
        if isinstance(total, int) and total > 0:
            show["episodes"] = total
            # Remaining episodes, not watched ones.
            if isinstance(seen, int):
                show["unseen"] = max(0, total - seen)
                if show["unseen"] == 0:
                    show["watched"] = True
        _rate(show, row.get("ratings"))
        added = _added(row.get("dateadded"))
        if added:
            show["added"] = added
        series.append(show)

        signature = zlib.crc32(
            f"{show_id}\x1f{title}\x1f{show['poster']}\x1f{show['fanart']}\x1f"
            f"{show.get('unseen', -1)}\x1f{show.get('episodes', 0)}\x1f"
            f"{show.get('rating', 0)}\x1f{added}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(series)} series read from the video database", xbmc.LOGINFO)
    return {"shows": series, "art": art,
            "tag": f"{len(series):x}-{signature:08x}"}


def _load_episodes(show_id: int, title: str) -> dict:
    """Read a show's episodes and register their stills' paths."""
    built = _read_episodes(show_id, title)
    with _cache.lock:
        _cache.episode_art.update(built["art"])
    return built


def _read_episodes(show_id: int, title: str) -> dict:
    answer = rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id,
        "properties": list(_EPISODE_PROPERTIES),
        # Episode order.
        "sort": {"method": "episode", "order": "ascending"},
    })
    error = answer.get("error")
    if error:
        _log(f"VideoLibrary.GetEpisodes failed for {show_id}: {error}")
        return {"title": title, "episodes": [], "art": {}, "tag": "none"}

    result = answer.get("result")
    rows = (result.get("episodes") or []) if isinstance(result, dict) else []

    listing: list[dict] = []
    art: dict[int, dict[str, str]] = {}
    signature = zlib.crc32(b"")

    for row in rows:
        if not isinstance(row, dict):
            continue
        episode_id = row.get("episodeid")
        if not isinstance(episode_id, int):
            continue

        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        still = _picture(pictures, _EPISODE_PICTURE_KEYS)
        art[episode_id] = {"thumb": still}

        entry = {
            "id": episode_id,
            # No invented titles; season and number identify the episode.
            "title": clean_value(str(row.get("title") or row.get("label") or "")),
            "thumb": _tag(still),
        }
        season = row.get("season")
        if isinstance(season, int) and season >= 0:
            entry["season"] = season
        number = row.get("episode")
        if isinstance(number, int) and number >= 0:
            entry["episode"] = number
        runtime = row.get("runtime")
        if isinstance(runtime, int) and runtime > 0:
            entry["duration"] = runtime
        if isinstance(row.get("playcount"), int) and row["playcount"] > 0:
            entry["watched"] = True
        resume = _resume(row.get("resume"))
        if resume:
            entry["resume"] = resume
        listing.append(entry)

        signature = zlib.crc32(
            f"{episode_id}\x1f{entry['title']}\x1f{entry['thumb']}\x1f"
            f"{entry.get('resume', 0)}\x1f{entry.get('watched', False)}\x1f"
            f"{entry.get('duration', 0)}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(listing)} episodes read for series {show_id}")
    return {"title": title, "episodes": listing, "art": art,
            "tag": f"{show_id:x}-{len(listing):x}-{signature:08x}"}


def play_episode(episode_id, resume: bool = True) -> bool:
    """Play an episode and return whether Kodi accepted it.

    Resumes like ``play``; the resume point comes from the cached lists.
    """
    try:
        wanted = int(episode_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False

    params: dict = {"item": {"episodeid": wanted}}
    if not resume:
        params["options"] = {"resume": False}
    elif _episode_resume_point(wanted):
        params["options"] = {"resume": True}
    if rpc("Player.Open", params).get("result") != "OK":
        return False
    _log(f"episode {wanted} started from the dashboard", xbmc.LOGINFO)
    # Lists change with playback; drop them.
    invalidate()
    return True


def _episode_resume_point(episode_id: int) -> int:
    with _cache.lock:
        opened = list(_cache.episodes.values())
    started = _cache.continuing.peek()
    for slot in opened:
        show = slot.peek()
        if show is None:
            continue
        for episode in show["episodes"]:
            if episode["id"] == episode_id:
                return int(episode.get("resume") or 0)
    # Episodes on the "continue" row may belong to unopened shows.
    if started is not None:
        for entry in started["items"]:
            if entry["kind"] == "episode" and entry["id"] == episode_id:
                return int(entry.get("resume") or 0)
        return 0
    # Cache dropped meanwhile: ask Kodi instead of starting from zero.
    answer = rpc("VideoLibrary.GetEpisodeDetails",
                 {"episodeid": episode_id, "properties": ["resume"]})
    result = answer.get("result")
    details = result.get("episodedetails") if isinstance(result, dict) else None
    return _resume((details or {}).get("resume"))


# --- Seen and unseen -------------------------------------------------------

# Id key and setter per markable kind.  Shows are marked via their episodes
# (Kodi counts a show as watched when all episodes are).
_MARKABLE = {
    "movie":   ("movieid", "VideoLibrary.SetMovieDetails"),
    "episode": ("episodeid", "VideoLibrary.SetEpisodeDetails"),
}


def set_watched(kind: str, item_id, watched: bool) -> bool:
    """Mark a film, episode or show as watched or unwatched, like Kodi does.

    Watched sets a play count and clears the resume point; unwatched clears
    the play count and keeps the resume point.  Returns whether the library
    accepted it; the cache is dropped either way.
    """
    try:
        wanted = int(item_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False

    if kind == "tvshow":
        done = _mark_show(wanted, watched)
    elif kind in _MARKABLE:
        done = _mark_one(kind, wanted, watched)
    else:
        return False
    # Drop now, so the page's immediate re-read sees the change.
    invalidate()
    if done:
        _log(f"{kind} {wanted} marked {'seen' if watched else 'unseen'} "
             "from the dashboard", xbmc.LOGINFO)
    return done


def clear_resume(kind: str, item_id) -> bool:
    """Clear a film's or episode's resume point, keeping its play count."""
    if kind not in _MARKABLE:
        return False
    try:
        wanted = int(item_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False
    key, method = _MARKABLE[kind]
    done = rpc(method, {key: wanted,
                        "resume": {"position": 0, "total": 0}}).get("result") == "OK"
    invalidate()
    if done:
        _log(f"{kind} {wanted}: resume point cleared from the dashboard",
             xbmc.LOGINFO)
    return done


def _mark_one(kind: str, wanted: int, watched: bool) -> bool:
    key, method = _MARKABLE[kind]
    params: dict = {key: wanted, "playcount": 1 if watched else 0}
    if watched:
        params["resume"] = {"position": 0, "total": 0}
        params["lastplayed"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return rpc(method, params).get("result") == "OK"


def _mark_show(show_id: int, watched: bool) -> bool:
    """Mark every episode of a show, writing only those that change."""
    answer = rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id, "properties": ["playcount", "resume"],
    })
    if answer.get("error"):
        _log(f"VideoLibrary.GetEpisodes failed for {show_id}: {answer['error']}")
        return False
    result = answer.get("result")
    rows = (result.get("episodes") or []) if isinstance(result, dict) else []

    done = True
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("episodeid"), int):
            continue
        played = isinstance(row.get("playcount"), int) and row["playcount"] > 0
        started = _resume(row.get("resume")) > 0
        if played == watched and not (watched and started):
            continue
        if not _mark_one("episode", row["episodeid"], watched):
            done = False
    return done


# --- Continue watching -----------------------------------------------------

# Maximum titles on the "continue" row.
_CONTINUE_LIMIT = 30

# Kodi's "in progress" filter: a resume point on an unfinished title.
_IN_PROGRESS = {"field": "inprogress", "operator": "true", "value": ""}

_CONTINUE_FILM_PROPERTIES = ("title", "year", "art", "runtime", "resume",
                             "lastplayed", "ratings")
_CONTINUE_EPISODE_PROPERTIES = ("title", "showtitle", "tvshowid", "season",
                                "episode", "art", "runtime", "resume",
                                "lastplayed")

# On the row an episode shows its show's poster.
_EPISODE_POSTER_KEYS = ("tvshow.poster", "season.poster", "poster")


def continuing(films: bool = True, series: bool = True) -> dict:
    """Return partly watched films and episodes, most recent first.

    One list (``{"items": [...], "count": int, "tag": str}``), each entry
    marked by ``kind``.  *films* / *series* leave out disabled shelves.
    """
    held = _cache.continuing.get()
    items = [entry for entry in held["items"]
             if (films and entry["kind"] == "movie")
             or (series and entry["kind"] == "episode")]
    return {"items": items, "count": len(items),
            "tag": f"{int(films)}{int(series)}-{held['tag']}"}


def _load_continuing() -> dict:
    """Read the "continue" row and register its episodes' pictures.

    Episodes of unopened shows are known only from here (see
    ``episode_art_path``).
    """
    built = _read_continuing()
    with _cache.lock:
        _cache.episode_art.update(built["art"])
    return built


def _read_continuing() -> dict:
    listing: list[dict] = []
    art: dict[int, dict[str, str]] = {}
    sort = {"method": "lastplayed", "order": "descending"}
    limits = {"start": 0, "end": _CONTINUE_LIMIT}

    answer = rpc("VideoLibrary.GetMovies", {
        "properties": list(_CONTINUE_FILM_PROPERTIES),
        "filter": _IN_PROGRESS, "sort": sort, "limits": limits,
    })
    if answer.get("error"):
        _log(f"VideoLibrary.GetMovies (in progress) failed: {answer['error']}")
    result = answer.get("result")
    for row in (result.get("movies") or []) if isinstance(result, dict) else []:
        entry = _continue_entry(row, "movie")
        # A film without a title cannot be shown.
        if entry is None or not entry["title"]:
            continue
        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        entry["poster"] = _tag(_picture(pictures, _POSTER_KEYS))
        year = row.get("year")
        if isinstance(year, int) and year > 0:
            entry["year"] = year
        _rate(entry, row.get("ratings"))
        listing.append(entry)

    # Episodes show their show's rating (episode ratings are rarely set).
    show_ratings: dict[int, dict] = {}

    answer = rpc("VideoLibrary.GetEpisodes", {
        "properties": list(_CONTINUE_EPISODE_PROPERTIES),
        "filter": _IN_PROGRESS, "sort": sort, "limits": limits,
    })
    if answer.get("error"):
        _log(f"VideoLibrary.GetEpisodes (in progress) failed: {answer['error']}")
    result = answer.get("result")
    for row in (result.get("episodes") or []) if isinstance(result, dict) else []:
        entry = _continue_entry(row, "episode")
        if entry is None:
            continue
        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        poster = _picture(pictures, _EPISODE_POSTER_KEYS)
        still = _picture(pictures, _EPISODE_PICTURE_KEYS)
        art[entry["id"]] = {"poster": poster, "thumb": still}
        entry["poster"] = _tag(poster)
        entry["thumb"] = _tag(still)
        show = clean_value(str(row.get("showtitle") or ""))
        if show:
            entry["show"] = show
        show_id = row.get("tvshowid")
        if isinstance(show_id, int) and show_id > 0:
            entry["tvshowid"] = show_id
            if not show_ratings:
                show_ratings = _show_ratings()
            rated = show_ratings.get(show_id)
            if rated:
                entry.update(rated)
        season = row.get("season")
        if isinstance(season, int) and season >= 0:
            entry["season"] = season
        number = row.get("episode")
        if isinstance(number, int) and number >= 0:
            entry["episode"] = number
        listing.append(entry)

    # Kodi's timestamps sort correctly as text.
    listing.sort(key=lambda entry: entry.get("lastplayed", ""), reverse=True)
    del listing[_CONTINUE_LIMIT:]

    signature = zlib.crc32(b"")
    for entry in listing:
        signature = zlib.crc32(
            f"{entry['kind']}\x1f{entry['id']}\x1f{entry['title']}\x1f"
            f"{entry.get('poster', '')}\x1f{entry.get('resume', 0)}\x1f"
            f"{entry.get('lastplayed', '')}\x1f{entry.get('rating', 0)}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(listing)} titles in progress read from the video database")
    return {"items": listing, "art": art,
            "tag": f"{len(listing):x}-{signature:08x}"}


def _show_ratings() -> dict[int, dict]:
    """Return each show's rating by show id, from the cached show list.

    Never empty, so the caller asks only once.
    """
    rated: dict[int, dict] = {0: {}}
    try:
        shows = _show_catalogue()["shows"]
    except Exception as exc:
        _log(f"reading the series for their ratings failed: {exc}")
        return rated
    for show in shows:
        if show.get("rating"):
            rated[show["id"]] = {"rating": show["rating"],
                                 "rating_from": show.get("rating_from", "")}
    return rated


def _continue_entry(row, kind: str) -> dict | None:
    """Return the common fields of a "continue" entry, or None.

    None without an id or a meaningful resume point.
    """
    if not isinstance(row, dict):
        return None
    wanted = row.get("movieid" if kind == "movie" else "episodeid")
    if not isinstance(wanted, int):
        return None
    resume = _resume(row.get("resume"))
    if not resume:
        return None
    entry = {"kind": kind, "id": wanted, "resume": resume,
             "title": clean_value(str(row.get("title") or row.get("label") or ""))}
    runtime = row.get("runtime")
    if isinstance(runtime, int) and runtime > 0:
        entry["duration"] = runtime
    else:
        # Without a runtime, take the length from the resume point.
        try:
            total = int(float((row.get("resume") or {}).get("total") or 0))
        except (TypeError, ValueError, AttributeError):
            total = 0
        if total > 0:
            entry["duration"] = total
    played = row.get("lastplayed")
    if isinstance(played, str) and played.strip():
        entry["lastplayed"] = played.strip()
    return entry


# Created last: the slots name the readers defined above.
_cache = _Cache()
