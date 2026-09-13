# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The film and series library behind the dashboard's idle page.

A box that is playing nothing is the one somebody is standing in front of with
a phone in their hand, and what they want from it is a film.  So the page that
says nothing is playing offers the video database instead: every film Kodi
knows about, as posters, and a press puts one on the television.

The list is read over JSON-RPC once and then held.  A library of a few
thousand films is a query Kodi answers in its own time, and a browser opening
-- or a film ending, which is when every phone in the house asks at once -- is
not a reason to ask again.  What is held is dropped the moment Kodi says the
library changed (see ``service/monitor.py``), so a film added this evening is
on the phone without anyone waiting the hold out.

Only the poster addresses are kept here, never the pictures themselves: a
thousand posters is more memory than the whole add-on has any business taking,
and the browser holds the handful it drew far better than this could (see
``_ART_CACHE`` in ``web/server.py``).

Series are the same shelf with one floor more.  A show is not something that
can be put on -- an episode is -- so the wall of shows is read and held the way
the films are, and the episodes of one show are read only when somebody opens
that show, and then held beside it.  A house that watches three series does not
pay for the episodes of the ninety it does not.
"""

import threading
import time
import zlib

import xbmc

from web.snapshot import clean_value, rpc

_ADDON_ID = "script.tinyppi"

# What the card draws, and nothing beyond it: a poster, a title, a year, how
# long it runs, and whether it has been seen or left half-watched.  The plot
# and the cast belong to a screen the dashboard does not have.
_PROPERTIES = ("title", "year", "art", "runtime", "playcount", "resume")

# Which piece of art stands for a film, best first.  A library entry usually
# carries a poster; ``thumb`` is what a film scraped from a folder of files
# tends to have instead.
_POSTER_KEYS = ("poster", "thumb")
_FANART_KEYS = ("fanart",)

# How long a list is held before it is read again.  The library changing is a
# notification rather than something to poll for (see ``invalidate``), so this
# is only the floor under a box whose notifications never arrive -- an add-on
# writing into the database behind Kodi's back, say.
_TTL = 300.0

_lock = threading.Lock()
_catalogue: dict | None = None
_read_at = 0.0

# The same three things again for the shows, and then the episodes of whichever
# shows have been opened, each held under its show's own id.  Kept apart from
# the films rather than folded in with them: the two lists are read at
# different moments and a reader after one of them has no reason to wait for
# the other.
_shows: dict | None = None
_shows_read_at = 0.0
_episodes: dict[int, dict] = {}
# Every episode picture the lists above have handed out, by episode id.  The
# address the browser asks for names an episode and not its show, and walking
# every held show to find out whose it is would be a search per picture.
_episode_art: dict[int, dict[str, str]] = {}


def _log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"{_ADDON_ID} --> library: {message}", level=level)


# --- The list --------------------------------------------------------------

def invalidate() -> None:
    """Forget the held list, so the next reader reads a fresh one.

    Called from the monitor whenever Kodi says the video database moved.  It
    does not read anything itself: a scan finishing while nobody is looking at
    a dashboard should cost nothing at all.
    """
    global _catalogue, _read_at, _shows, _shows_read_at
    with _lock:
        _catalogue = None
        _read_at = 0.0
        _shows = None
        _shows_read_at = 0.0
        _episodes.clear()
        _episode_art.clear()


def catalogue(force: bool = False) -> dict:
    """The films, as ``{"movies": [...], "art": {...}, "tag": str}``.

    ``tag`` changes only when the list does, which is what lets a phone be
    answered with an empty 304 rather than the whole library every time it
    opens the page.

    Two readers arriving together may both read the library rather than one
    waiting on the other's lock: the query is Kodi's to answer and holding the
    lock across it would park every other request behind it.
    """
    global _catalogue, _read_at
    with _lock:
        held = _catalogue
        fresh = held is not None and time.monotonic() - _read_at < _TTL
    if held is not None and fresh and not force:
        return held

    built = _read()
    with _lock:
        _catalogue = built
        _read_at = time.monotonic()
    return built


def movies() -> dict:
    """What a client is sent: the list and its tag, without the art paths,
    which are addresses of this server rather than anything a client can use.
    """
    held = catalogue()
    return {"movies": held["movies"], "count": len(held["movies"]),
            "tag": held["tag"]}


def art_path(movie_id: int, kind: str) -> str:
    """The raw path Kodi holds for one film's artwork, or ''.

    Read out of the list that has already been built rather than through a
    query of its own: the address the browser asks for came from that list in
    the first place, so the film is in it.
    """
    entry = catalogue()["art"].get(int(movie_id)) or {}
    return entry.get(kind, "")


def _read() -> dict:
    answer = rpc("VideoLibrary.GetMovies", {
        "properties": list(_PROPERTIES),
        # Sorted where the library is, not in the page: Kodi knows to file
        # "The Thing" under T and a browser would have to be taught.
        "sort": {"method": "sorttitle", "order": "ascending",
                 "ignorearticle": True},
    })
    error = answer.get("error")
    if error:
        # A box with no video database at all answers this way, and so does one
        # whose database is being upgraded.  Neither is worth a line above
        # debug: the page shows an empty card and asks again later.
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
        films.append(film)

        signature = zlib.crc32(
            f"{movie_id}\x1f{title}\x1f{film['poster']}\x1f"
            f"{film.get('resume', 0)}\x1f{film.get('watched', False)}"
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


def _resume(resume) -> int:
    """How far into a film the box got, in whole seconds, or 0.

    Only a point somebody would actually resume from counts: Kodi keeps a
    position of a second or two for a film that was started and stopped again,
    and a progress bar a pixel wide says nothing.
    """
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


def _tag(path: str) -> str:
    """A short, stable name for a picture, hung on its address so a browser
    fetches one poster once rather than once per visit."""
    return f"{zlib.crc32(path.encode('utf-8', 'replace')):08x}" if path else ""


# --- Starting one ----------------------------------------------------------

def play(movie_id) -> bool:
    """Put a film on the television, returning whether Kodi took it.

    Resumed where the library holds a point to resume from, which is what
    pressing the film in Kodi's own window does.  ``Player.Open`` rather than
    a builtin for the reason every other command here uses JSON-RPC: the page
    has to be able to say whether the thing happened.
    """
    try:
        wanted = int(movie_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False

    params: dict = {"item": {"movieid": wanted}}
    if _resume_point(wanted):
        params["options"] = {"resume": True}
    if rpc("Player.Open", params).get("result") != "OK":
        return False
    _log(f"film {wanted} started from the dashboard", xbmc.LOGINFO)
    # What is playing is about to be a different film, and every screen that
    # asked for the list holds one saying it is not being played.
    invalidate()
    return True


def _resume_point(movie_id: int) -> int:
    for film in catalogue()["movies"]:
        if film["id"] == movie_id:
            return int(film.get("resume") or 0)
    return 0


# --- The series ------------------------------------------------------------

# What a show's tile draws: a poster, a name, a year, and how much of it is
# still unwatched -- which is the one number that decides whether a shelf of
# shows is worth opening tonight.
_SHOW_PROPERTIES = ("title", "year", "art", "episode", "watchedepisodes")

# And what an episode's row draws.  ``firstaired`` is not among them: a row
# that already says which season and which number it is has said where in the
# series it falls, and the date it went out on television years ago is not what
# anybody is choosing by.
_EPISODE_PROPERTIES = ("title", "season", "episode", "art", "runtime",
                       "playcount", "resume")

# An episode's own picture is a still from it, filed under ``thumb``.  The
# season's or the show's poster stands in where the episode has none of its
# own, which is what Kodi's own window falls back to as well.
_EPISODE_PICTURE_KEYS = ("thumb", "season.poster", "tvshow.poster")


def shows() -> dict:
    """What a client is sent: the shows and the list's own tag."""
    held = _show_catalogue()
    return {"shows": held["shows"], "count": len(held["shows"]),
            "tag": held["tag"]}


def episodes(show_id) -> dict | None:
    """The episodes of one show, or None where there is no such show.

    Read the first time somebody opens the show and then held beside the rest,
    so scrolling back out of a show and into it again -- which is what choosing
    an episode looks like -- asks Kodi nothing.
    """
    try:
        wanted = int(show_id)
    except (TypeError, ValueError):
        return None
    if wanted <= 0:
        return None

    with _lock:
        held = _episodes.get(wanted)
    if held is not None:
        return {"tvshowid": wanted, "title": held["title"],
                "episodes": held["episodes"], "count": len(held["episodes"]),
                "tag": held["tag"]}

    # The name is taken from the wall of shows rather than asked for again: the
    # only way to be here is to have pressed a show that came off it.
    title = ""
    for show in _show_catalogue()["shows"]:
        if show["id"] == wanted:
            title = show["title"]
            break
    if not title:
        return None

    built = _read_episodes(wanted, title)
    with _lock:
        _episodes[wanted] = built
        _episode_art.update(built["art"])
    return {"tvshowid": wanted, "title": title, "episodes": built["episodes"],
            "count": len(built["episodes"]), "tag": built["tag"]}


def show_art_path(show_id, kind: str) -> str:
    """The raw path Kodi holds for one show's artwork, or ''."""
    try:
        entry = _show_catalogue()["art"].get(int(show_id)) or {}
    except (TypeError, ValueError):
        return ""
    return entry.get(kind, "")


def episode_art_path(episode_id, kind: str) -> str:
    """The raw path Kodi holds for one episode's still, or ''.

    Only episodes whose show has been opened are here, which is the only way an
    address for one can have reached a browser in the first place.
    """
    try:
        wanted = int(episode_id)
    except (TypeError, ValueError):
        return ""
    with _lock:
        entry = _episode_art.get(wanted) or {}
    return entry.get(kind, "")


def _show_catalogue(force: bool = False) -> dict:
    """The shows, as ``{"shows": [...], "art": {...}, "tag": str}``.

    Held the same way the films are, and dropped by the same notification: a
    scan that adds an episode moves the unwatched count on a show's tile, and
    that count is what somebody is deciding by.
    """
    global _shows, _shows_read_at
    with _lock:
        held = _shows
        fresh = held is not None and time.monotonic() - _shows_read_at < _TTL
    if held is not None and fresh and not force:
        return held

    built = _read_shows()
    with _lock:
        _shows = built
        _shows_read_at = time.monotonic()
    return built


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
        art[show_id] = {"poster": poster,
                        "fanart": _picture(pictures, _FANART_KEYS)}

        show = {"id": show_id, "title": title, "poster": _tag(poster)}
        year = row.get("year")
        if isinstance(year, int) and year > 0:
            show["year"] = year
        total = row.get("episode")
        seen = row.get("watchedepisodes")
        if isinstance(total, int) and total > 0:
            show["episodes"] = total
            # How many are left rather than how many have been watched: a shelf
            # is scanned for what there is still to see, and a tile saying "4"
            # is read as four waiting, not four gone.
            if isinstance(seen, int):
                show["unseen"] = max(0, total - seen)
                if show["unseen"] == 0:
                    show["watched"] = True
        series.append(show)

        signature = zlib.crc32(
            f"{show_id}\x1f{title}\x1f{show['poster']}\x1f"
            f"{show.get('unseen', -1)}\x1f{show.get('episodes', 0)}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(series)} series read from the video database", xbmc.LOGINFO)
    return {"shows": series, "art": art,
            "tag": f"{len(series):x}-{signature:08x}"}


def _read_episodes(show_id: int, title: str) -> dict:
    answer = rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id,
        "properties": list(_EPISODE_PROPERTIES),
        # In the order they were made, which is the order they are watched in.
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
            # An episode with no name of its own is left without one rather
            # than given a made-up one: the row already says which season and
            # which number it is, and that is a name.
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
            f"{entry.get('resume', 0)}\x1f{entry.get('watched', False)}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(listing)} episodes read for series {show_id}")
    return {"title": title, "episodes": listing, "art": art,
            "tag": f"{show_id:x}-{len(listing):x}-{signature:08x}"}


def play_episode(episode_id) -> bool:
    """Put one episode on the television, returning whether Kodi took it.

    Resumed where the library holds a point to resume from, the same as a film.
    The episode has to have come off a list this module read -- which is the
    only place an id for one can have come from -- so the point is already held
    and nothing is asked of Kodi to find it.
    """
    try:
        wanted = int(episode_id)
    except (TypeError, ValueError):
        return False
    if wanted <= 0:
        return False

    params: dict = {"item": {"episodeid": wanted}}
    if _episode_resume_point(wanted):
        params["options"] = {"resume": True}
    if rpc("Player.Open", params).get("result") != "OK":
        return False
    _log(f"episode {wanted} started from the dashboard", xbmc.LOGINFO)
    # What has been watched is about to change, and every screen holding a list
    # of this show's episodes holds one that says otherwise.
    invalidate()
    return True


def _episode_resume_point(episode_id: int) -> int:
    with _lock:
        held = list(_episodes.values())
    for show in held:
        for episode in show["episodes"]:
            if episode["id"] == episode_id:
                return int(episode.get("resume") or 0)
    return 0
