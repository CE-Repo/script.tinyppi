# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The film list and starting a film."""

import xbmc
from web.library import cache, common
from web.library.common import log
from web.library.entries import ArtPaths, Film, FilmListing, Films
from web.values import Json, Unchecked, library_id

# Film properties the tiles need.  ``dateadded`` feeds the "recently added"
# row (see ``common.added``), read here so the row matches the wall.
_PROPERTIES = ("title", "year", "art", "runtime", "playcount", "resume",
               "ratings", "dateadded")


def catalogue() -> Films:
    """Return the films as ``{"movies": [...], "art": {...}, "tag": str}``.

    ``tag`` changes only with the list (for 304 answers).
    """
    return cache.lists.films.get()


def movies() -> FilmListing:
    """Return the film list for clients (without the art paths)."""
    held = catalogue()
    return {"movies": held["movies"], "count": len(held["movies"]),
            "tag": held["tag"]}


def art_path(movie_id: int, kind: str) -> str:
    """Return a film's raw artwork path from the cached list, or ''."""
    entry = catalogue()["art"].get(int(movie_id)) or {}
    return entry.get(kind, "")


def read() -> Films:
    """Read the film list from Kodi (the reader of ``cache.lists.films``)."""
    answer = common.rpc("VideoLibrary.GetMovies", {
        "properties": list(_PROPERTIES),
        # Kodi sorts by sort title, ignoring articles.
        "sort": {"method": "sorttitle", "order": "ascending",
                 "ignorearticle": True},
    })
    error = answer.get("error")
    if error:
        # No database, or one being upgraded: debug only, the page retries.
        log(f"VideoLibrary.GetMovies failed: {error}")
        return {"movies": [], "art": {}, "tag": "none"}

    films: list[Film] = []
    art: ArtPaths = {}
    for row in common.rows_of(answer, "movies"):
        film = _film(row, art)
        if film is not None:
            films.append(film)

    log(f"{len(films)} films read from the video database", xbmc.LOGINFO)
    return {"movies": films, "art": art,
            "tag": f"{len(films):x}-{common.signature(films)}"}


def _film(row: Json, art: ArtPaths) -> Film | None:
    """Return a film's tile from its row, registering its art in *art*.

    None without an id or a title.
    """
    movie_id = row.get("movieid")
    if not isinstance(movie_id, int):
        return None
    title = common.clean_title(row)
    if not title:
        return None

    pictures = common.art_of(row)
    poster = common.picture(pictures, common.POSTER_KEYS)
    art[movie_id] = {"poster": poster,
                     "fanart": common.picture(pictures, common.FANART_KEYS)}

    film: Film = {"id": movie_id, "title": title, "poster": common.tag(poster)}
    _describe(film, row)
    return film


def _describe(film: Film, row: Json) -> None:
    """Add the optional fields Kodi has meaningful values for."""
    if (year := common.number(row, "year")) is not None:
        film["year"] = year
    if (duration := common.number(row, "runtime")) is not None:
        film["duration"] = duration
    if isinstance(row.get("playcount"), int) and row["playcount"] > 0:
        film["watched"] = True
    resume = common.resume_of(row.get("resume"))
    if resume:
        film["resume"] = resume
    common.rate(film, row.get("ratings"))
    added = common.added(row.get("dateadded"))
    if added:
        film["added"] = added


def play(movie_id: Unchecked, resume: bool = True) -> bool:
    """Play a film and return whether Kodi accepted it.

    Resumes when a resume point exists, unless *resume* is False; the option
    is always explicit so Kodi does not ask on the TV.  JSON-RPC reports
    success, unlike a builtin.
    """
    wanted = library_id(movie_id)
    if not wanted:
        return False
    return common.open_item({"movieid": wanted},
                            common.resume_option(resume, lambda: _resume_point(wanted)),
                            f"film {wanted}")


def _resume_point(movie_id: int) -> int:
    for film in catalogue()["movies"]:
        if film["id"] == movie_id:
            return int(film.get("resume") or 0)
    return 0
