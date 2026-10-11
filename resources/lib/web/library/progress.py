# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The "continue watching" row: partly watched films and episodes."""

from web.library import cache, common
from web.library.common import log
from web.values import clean_value

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


def continuing(films: bool = True, series: bool = True) -> dict:
    """Return partly watched films and episodes, most recent first.

    One list (``{"items": [...], "count": int, "tag": str}``), each entry
    marked by ``kind``.  *films* / *series* leave out disabled shelves.
    """
    held = cache.lists.continuing.get()
    items = [entry for entry in held["items"]
             if (films and entry["kind"] == "movie")
             or (series and entry["kind"] == "episode")]
    return {"items": items, "count": len(items),
            "tag": f"{int(films)}{int(series)}-{held['tag']}"}


def load() -> dict:
    """Read the "continue" row and register its episodes' pictures.

    The reader of ``cache.lists.continuing``.  Episodes of unopened shows
    are known only from here (see ``series.episode_art_path``).
    """
    built = _read()
    cache.lists.remember_art(built["art"])
    return built


def _in_progress(method: str, properties: tuple[str, ...], key: str) -> list:
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


def _read() -> dict:
    art: dict[int, dict[str, str]] = {}
    listing = _films() + _episodes(art)

    # Kodi's timestamps sort correctly as text.
    listing.sort(key=lambda entry: entry.get("lastplayed", ""), reverse=True)
    del listing[_CONTINUE_LIMIT:]

    log(f"{len(listing)} titles in progress read from the video database")
    return {"items": listing, "art": art,
            "tag": f"{len(listing):x}-{common.signature(listing)}"}


def _films() -> list[dict]:
    listing = []
    for row in _in_progress("VideoLibrary.GetMovies", _FILM_PROPERTIES, "movies"):
        entry = _entry(row, "movie")
        # A film without a title cannot be shown.
        if entry is None or not entry["title"]:
            continue
        entry["poster"] = common.tag(common.picture(common.art_of(row),
                                                    common.POSTER_KEYS))
        common.counted(entry, row, "year")
        common.rate(entry, row.get("ratings"))
        listing.append(entry)
    return listing


def _episodes(art: dict[int, dict[str, str]]) -> list[dict]:
    """Return the episodes in progress, registering their art in *art*."""
    listing = []
    # Episodes show their show's rating (episode ratings are rarely set);
    # read once, on the first episode that needs it.
    show_ratings: dict[int, dict] = {}
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
        show = clean_value(str(row.get("showtitle") or ""))
        if show:
            entry["show"] = show
        show_id = row.get("tvshowid")
        if isinstance(show_id, int) and show_id > 0:
            entry["tvshowid"] = show_id
            show_ratings = show_ratings or _show_ratings()
            entry.update(show_ratings.get(show_id) or {})
        common.counted(entry, row, "season", low=0)
        common.counted(entry, row, "episode", low=0)
        listing.append(entry)
    return listing


def _show_ratings() -> dict[int, dict]:
    """Return each show's rating by show id, from the cached show list.

    Never empty, so the caller asks only once.
    """
    rated: dict[int, dict] = {0: {}}
    try:
        shows = cache.lists.shows.get()["shows"]
    except Exception as exc:
        log(f"reading the series for their ratings failed: {exc}")
        return rated
    for show in shows:
        if show.get("rating"):
            rated[show["id"]] = {"rating": show["rating"],
                                 "rating_from": show.get("rating_from", "")}
    return rated


def _entry(row: object, kind: str) -> dict | None:
    """Return the common fields of a "continue" entry, or None.

    None without an id or a meaningful resume point.
    """
    if not isinstance(row, dict):
        return None
    wanted = row.get("movieid" if kind == "movie" else "episodeid")
    if not isinstance(wanted, int):
        return None
    resume = common.resume_of(row.get("resume"))
    if not resume:
        return None
    entry = {"kind": kind, "id": wanted, "resume": resume,
             "title": common.clean_title(row)}
    runtime = row.get("runtime")
    if isinstance(runtime, int) and runtime > 0:
        entry["duration"] = runtime
    else:
        # Without a runtime, take the length from the resume point, which
        # resume_of has found a finite number past the position.
        entry["duration"] = int(float(row["resume"]["total"]))
    played = row.get("lastplayed")
    if isinstance(played, str) and played.strip():
        entry["lastplayed"] = played.strip()
    return entry
