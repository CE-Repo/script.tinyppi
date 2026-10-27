# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The "continue watching" row: partly watched films and episodes; and the
"next up" row: the next unwatched episode of each show being watched."""

from web.library import cache, common
from web.library.common import log
from web.library.entries import ArtPaths, ContinueListing, Continuing, Resumable, Upcoming
from web.values import Json, clean_value

# Maximum titles on the "continue" row.
_CONTINUE_LIMIT = 30

# Kodi's "in progress" filter: a resume point on an unfinished title.
_IN_PROGRESS = {"field": "inprogress", "operator": "true", "value": ""}

_FILM_PROPERTIES = ("title", "year", "art", "runtime", "resume",
                    "lastplayed", "ratings")
_EPISODE_PROPERTIES = ("title", "showtitle", "tvshowid", "season",
                       "episode", "art", "runtime", "resume", "lastplayed")

# On the row an episode shows its show's poster.
_EPISODE_POSTER_KEYS = ("tvshow.poster", "season.poster", "poster")

# Shows on the "next up" row.  Each costs a query of its own (Kodi has no
# "next episode" of a show), so the row stays short.
_NEXT_LIMIT = 15
# A show's next episode: its first unwatched one in episode order, the
# specials (season 0) left out, as Kodi's own "next up" lists do.
_UNWATCHED = {"and": [{"field": "playcount", "operator": "is", "value": "0"},
                      {"field": "season", "operator": "greaterthan", "value": "0"}]}
_NEXT_PROPERTIES = ("title", "season", "episode", "art", "runtime")


def continuing(films: bool = True, series: bool = True) -> ContinueListing:
    """Return partly watched films and episodes, most recent first.

    One list (``{"items": [...], "count": int, "tag": str}``), each entry
    marked by ``kind``.  *films* / *series* leave out disabled shelves.
    """
    held = cache.lists.continuing.get()
    items = [entry for entry in held["items"]
             if (films and entry["kind"] == "movie")
             or (series and entry["kind"] == "episode")]
    return {"items": items, "next": held["next"] if series else [], "count": len(items),
            "tag": f"{int(films)}{int(series)}-{held['tag']}"}


def load() -> Continuing:
    """Read the "continue" row and register its episodes' pictures.

    The reader of ``cache.lists.continuing``.  Episodes of unopened shows
    are known only from here (see ``series.episode_art_path``).
    """
    built = _read()
    cache.lists.remember_art(built["art"])
    return built


def _in_progress(method: str, properties: tuple[str, ...], key: str) -> list[Json]:
    """Return the rows of *method* in progress, most recently played first."""
    answer = common.rpc(method, {
        "properties": list(properties),
        "filter": _IN_PROGRESS,
        "sort": {"method": "lastplayed", "order": "descending"},
        "limits": {"start": 0, "end": _CONTINUE_LIMIT},
    })
    if answer.get("error"):
        log(f"{method} (in progress) failed: {answer['error']}")
    return common.rows_of(answer, key)


def _read() -> Continuing:
    art: ArtPaths = {}
    listing = _films() + _episodes(art)

    # Kodi's timestamps sort correctly as text.
    listing.sort(key=lambda entry: entry.get("lastplayed", ""), reverse=True)
    del listing[_CONTINUE_LIMIT:]
    # An episode already on the "continue" row is not next up as well.
    upcoming = _next_up(art, {entry["id"] for entry in listing if entry["kind"] == "episode"})

    log(f"{len(listing)} titles in progress and {len(upcoming)} next episodes read "
        "from the video database")
    return {"items": listing, "next": upcoming, "art": art,
            "tag": f"{len(listing):x}-{common.signature([*listing, *upcoming])}"}


def _next_up(art: ArtPaths, continuing: set[int]) -> list[Upcoming]:
    """Return the next episode of each show being watched, the show watched
    last first, registering their art in *art*.

    Episodes in *continuing* (on the "continue" row) are left out.
    """
    answer = common.rpc("VideoLibrary.GetInProgressTVShows", {
        "properties": ["title", "art", "lastplayed", "ratings"],
        "sort": {"method": "lastplayed", "order": "descending"},
        "limits": {"start": 0, "end": _NEXT_LIMIT},
    })
    if answer.get("error"):
        log(f"VideoLibrary.GetInProgressTVShows failed: {answer['error']}")
    listing: list[Upcoming] = []
    for show in common.rows_of(answer, "tvshows"):
        entry = _next_episode(show, art)
        if entry is not None and entry["id"] not in continuing:
            listing.append(entry)
    return listing


def _next_episode(show: Json, art: ArtPaths) -> Upcoming | None:
    """Return *show*'s next unwatched episode, or None (none, or no show)."""
    show_id = show.get("tvshowid")
    title = common.clean_title(show)
    if not isinstance(show_id, int) or show_id <= 0 or not title:
        return None
    answer = common.rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id,
        "properties": list(_NEXT_PROPERTIES),
        "filter": _UNWATCHED,
        "sort": {"method": "episode", "order": "ascending"},
        "limits": {"start": 0, "end": 1},
    })
    rows = common.rows_of(answer, "episodes")
    episode_id = rows[0].get("episodeid") if rows else None
    if not isinstance(episode_id, int):
        return None
    row = rows[0]
    poster = common.picture(common.art_of(show), common.POSTER_KEYS)
    still = common.picture(common.art_of(row), common.EPISODE_PICTURE_KEYS)
    art[episode_id] = {"poster": poster, "thumb": still}
    entry: Upcoming = {"kind": "episode", "id": episode_id,
                       "title": common.clean_title(row), "tvshowid": show_id, "show": title,
                       "poster": common.tag(poster), "thumb": common.tag(still)}
    _number_episode(entry, row)
    # Rated as its show is, as on the "continue" row.
    common.rate(entry, show.get("ratings"))
    return entry


def _number_episode(entry: Upcoming, row: Json) -> None:
    """Add an upcoming episode's season, number and length."""
    if (season := common.number(row, "season", low=0)) is not None:
        entry["season"] = season
    if (number := common.number(row, "episode", low=0)) is not None:
        entry["episode"] = number
    if (duration := common.number(row, "runtime")) is not None:
        entry["duration"] = duration


def _films() -> list[Resumable]:
    listing: list[Resumable] = []
    for row in _in_progress("VideoLibrary.GetMovies", _FILM_PROPERTIES, "movies"):
        entry = _entry(row, "movie")
        # A film without a title cannot be shown.
        if entry is None or not entry["title"]:
            continue
        entry["poster"] = common.tag(common.picture(common.art_of(row),
                                                    common.POSTER_KEYS))
        if (year := common.number(row, "year")) is not None:
            entry["year"] = year
        common.rate(entry, row.get("ratings"))
        listing.append(entry)
    return listing


def _episodes(art: ArtPaths) -> list[Resumable]:
    """Return the episodes in progress, registering their art in *art*."""
    listing: list[Resumable] = []
    # Episodes show their show's rating (episode ratings are rarely set);
    # read once, on the first episode that needs it.
    show_ratings: dict[int, tuple[float, str] | None] = {}
    for row in _in_progress("VideoLibrary.GetEpisodes", _EPISODE_PROPERTIES, "episodes"):
        entry = _entry(row, "episode")
        if entry is None:
            continue
        pictures = common.art_of(row)
        poster = common.picture(pictures, _EPISODE_POSTER_KEYS)
        still = common.picture(pictures, common.EPISODE_PICTURE_KEYS)
        art[entry["id"]] = {"poster": poster, "thumb": still}
        entry["poster"] = common.tag(poster)
        entry["thumb"] = common.tag(still)
        show_id = _place_episode(entry, row)
        if show_id:
            show_ratings = show_ratings or _show_ratings()
            rating = show_ratings.get(show_id)
            if rating:
                entry["rating"], entry["rating_from"] = rating
        listing.append(entry)
    return listing


def _place_episode(entry: Resumable, row: Json) -> int:
    """Add an episode's show, season and number; return the show id (or 0)."""
    show = clean_value(str(row.get("showtitle") or ""))
    if show:
        entry["show"] = show
    if (season := common.number(row, "season", low=0)) is not None:
        entry["season"] = season
    if (number := common.number(row, "episode", low=0)) is not None:
        entry["episode"] = number
    show_id = row.get("tvshowid")
    if isinstance(show_id, int) and show_id > 0:
        entry["tvshowid"] = show_id
        return show_id
    return 0


def _show_ratings() -> dict[int, tuple[float, str] | None]:
    """Return each show's rating and its source by show id, from the cached
    show list.

    Never empty, so the caller asks only once.
    """
    rated: dict[int, tuple[float, str] | None] = {0: None}
    try:
        shows = cache.lists.shows.get()["shows"]
    except Exception as exc:
        log(f"reading the series for their ratings failed: {exc}")
        return rated
    for show in shows:
        rating = show.get("rating")
        if rating:
            rated[show["id"]] = (rating, show.get("rating_from", ""))
    return rated


def _entry(row: Json, kind: str) -> Resumable | None:
    """Return the common fields of a "continue" entry, or None.

    None without an id or a meaningful resume point.
    """
    wanted = row.get("movieid" if kind == "movie" else "episodeid")
    if not isinstance(wanted, int):
        return None
    resume = common.resume_of(row.get("resume"))
    if not resume:
        return None
    runtime = row.get("runtime")
    if isinstance(runtime, int) and runtime > 0:
        duration = runtime
    else:
        # Without a runtime, take the length from the resume point, which
        # resume_of has found a finite number past the position.
        duration = int(float(row["resume"]["total"]))
    entry: Resumable = {"kind": kind, "id": wanted, "resume": resume,
                        "title": common.clean_title(row), "duration": duration}
    played = row.get("lastplayed")
    if isinstance(played, str) and played.strip():
        entry["lastplayed"] = played.strip()
    return entry
