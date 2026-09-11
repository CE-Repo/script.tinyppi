# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The film library behind the dashboard's idle page.

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


def _log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"{_ADDON_ID} --> library: {message}", level=level)


# --- The list --------------------------------------------------------------

def invalidate() -> None:
    """Forget the held list, so the next reader reads a fresh one.

    Called from the monitor whenever Kodi says the video database moved.  It
    does not read anything itself: a scan finishing while nobody is looking at
    a dashboard should cost nothing at all.
    """
    global _catalogue, _read_at
    with _lock:
        _catalogue = None
        _read_at = 0.0


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
