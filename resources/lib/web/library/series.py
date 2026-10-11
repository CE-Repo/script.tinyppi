# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The series list, the episodes of an opened series and starting one."""

from collections.abc import Sequence

import xbmc
from web.library import cache, common
from web.library.common import log
from web.library.entries import (
    ArtPaths,
    Episode,
    EpisodeListing,
    Episodes,
    Resumable,
    Show,
    ShowListing,
    Shows,
)
from web.values import Json, Unchecked, library_id

# Show properties the tiles need.  A show's ``dateadded`` is its newest
# episode's, so new episodes put the show on the "recently added" row.
_SHOW_PROPERTIES = ("title", "year", "art", "episode", "watchedepisodes",
                    "ratings", "dateadded")

# Episode properties the episode list needs.
_EPISODE_PROPERTIES = ("title", "season", "episode", "art", "runtime",
                       "playcount", "resume")


def shows() -> ShowListing:
    """Return the show list for clients."""
    held = catalogue()
    return {"shows": held["shows"], "count": len(held["shows"]),
            "tag": held["tag"]}


def catalogue() -> Shows:
    """Return the shows as ``{"shows": [...], "art": {...}, "tag": str}``."""
    return cache.lists.shows.get()


def episodes(show_id: Unchecked) -> EpisodeListing | None:
    """Return the episodes of show *show_id*, or None for an unknown show.

    Read on first open, then cached.
    """
    wanted = library_id(show_id)
    if not wanted:
        return None

    lists = cache.lists
    with lists.lock:
        slot = lists.episodes.get(wanted)
    if slot is None:
        # The title comes from the cached show list.
        title = next((show["title"] for show in catalogue()["shows"]
                      if show["id"] == wanted), "")
        if not title:
            return None
        with lists.lock:
            slot = lists.episodes.setdefault(
                wanted, cache.Slot(lists, lambda: _load_episodes(wanted, title)))

    held = slot.get()
    return {"tvshowid": wanted, "title": held["title"],
            "episodes": held["episodes"], "count": len(held["episodes"]),
            "tag": held["tag"]}


def show_art_path(show_id: Unchecked, kind: str) -> str:
    """Return a show's raw artwork path, or ''."""
    entry = catalogue()["art"].get(library_id(show_id)) or {}
    return entry.get(kind, "")


def episode_art_path(episode_id: Unchecked, kind: str) -> str:
    """Return an episode still's raw path, or ''.

    Only episodes of opened shows or on the "continue" row are known, the
    only ways their URLs can reach a browser.
    """
    wanted = library_id(episode_id)
    if not wanted:
        return ""
    lists = cache.lists
    entry = lists.episode_art_of(wanted)
    if entry is None and lists.continuing.peek() is None:
        # Cache dropped since: re-read the "continue" row, the one list with
        # episodes of unopened shows (reading it registers their art).
        lists.continuing.get()
        entry = lists.episode_art_of(wanted)
    return (entry or {}).get(kind, "")


def read_shows() -> Shows:
    """Read the show list from Kodi (the reader of ``cache.lists.shows``)."""
    answer = common.rpc("VideoLibrary.GetTVShows", {
        "properties": list(_SHOW_PROPERTIES),
        "sort": {"method": "sorttitle", "order": "ascending",
                 "ignorearticle": True},
    })
    error = answer.get("error")
    if error:
        log(f"VideoLibrary.GetTVShows failed: {error}")
        return {"shows": [], "art": {}, "tag": "none"}

    series: list[Show] = []
    art: ArtPaths = {}
    for row in common.rows_of(answer, "tvshows"):
        show = _show(row, art)
        if show is not None:
            series.append(show)

    log(f"{len(series)} series read from the video database", xbmc.LOGINFO)
    return {"shows": series, "art": art,
            "tag": f"{len(series):x}-{common.signature(series)}"}


def _show(row: Json, art: ArtPaths) -> Show | None:
    """Return a show's tile from its row, registering its art in *art*.

    None without an id or a title.
    """
    show_id = row.get("tvshowid")
    if not isinstance(show_id, int):
        return None
    title = common.clean_title(row)
    if not title:
        return None

    pictures = common.art_of(row)
    poster = common.picture(pictures, common.POSTER_KEYS)
    fanart = common.picture(pictures, common.FANART_KEYS)
    art[show_id] = {"poster": poster, "fanart": fanart}

    # Shows carry their fanart tag too: the episode view shows it.
    show: Show = {"id": show_id, "title": title,
                  "poster": common.tag(poster), "fanart": common.tag(fanart)}
    if (year := common.number(row, "year")) is not None:
        show["year"] = year
    _count_episodes(show, row.get("episode"), row.get("watchedepisodes"))
    common.rate(show, row.get("ratings"))
    added = common.added(row.get("dateadded"))
    if added:
        show["added"] = added
    return show


def _count_episodes(show: Show, total: object, seen: object) -> None:
    """Set a show's episode count and the episodes still to watch."""
    if not isinstance(total, int) or total <= 0:
        return
    show["episodes"] = total
    # Remaining episodes, not watched ones.
    if isinstance(seen, int):
        unseen = show["unseen"] = max(0, total - seen)
        if unseen == 0:
            show["watched"] = True


def _load_episodes(show_id: int, title: str) -> Episodes:
    """Read a show's episodes and register their stills' paths."""
    built = _read_episodes(show_id, title)
    cache.lists.remember_art(built["art"])
    return built


def _read_episodes(show_id: int, title: str) -> Episodes:
    answer = common.rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id,
        "properties": list(_EPISODE_PROPERTIES),
        # Episode order.
        "sort": {"method": "episode", "order": "ascending"},
    })
    error = answer.get("error")
    if error:
        log(f"VideoLibrary.GetEpisodes failed for {show_id}: {error}")
        return {"title": title, "episodes": [], "art": {}, "tag": "none"}

    listing: list[Episode] = []
    art: ArtPaths = {}
    for row in common.rows_of(answer, "episodes"):
        entry = _episode(row, art)
        if entry is not None:
            listing.append(entry)

    log(f"{len(listing)} episodes read for series {show_id}")
    # The show's title is sent with the episodes, so it counts too.
    return {"title": title, "episodes": listing, "art": art,
            "tag": f"{show_id:x}-{len(listing):x}-{common.signature(listing, title)}"}


def _episode(row: Json, art: ArtPaths) -> Episode | None:
    """Return an episode's list entry, registering its still in *art*."""
    episode_id = row.get("episodeid")
    if not isinstance(episode_id, int):
        return None

    still = common.picture(common.art_of(row), common.EPISODE_PICTURE_KEYS)
    art[episode_id] = {"thumb": still}

    entry: Episode = {
        "id": episode_id,
        # No invented titles; season and number identify the episode.
        "title": common.clean_title(row),
        "thumb": common.tag(still),
    }
    _describe(entry, row)
    return entry


def _describe(entry: Episode, row: Json) -> None:
    """Add the optional fields Kodi has meaningful values for."""
    if (season := common.number(row, "season", low=0)) is not None:
        entry["season"] = season
    if (number := common.number(row, "episode", low=0)) is not None:
        entry["episode"] = number
    if (duration := common.number(row, "runtime")) is not None:
        entry["duration"] = duration
    if isinstance(row.get("playcount"), int) and row["playcount"] > 0:
        entry["watched"] = True
    resume = common.resume_of(row.get("resume"))
    if resume:
        entry["resume"] = resume


def play_episode(episode_id: Unchecked, resume: bool = True) -> bool:
    """Play an episode and return whether Kodi accepted it.

    Resumes like ``films.play``; the resume point comes from the cached
    lists.
    """
    wanted = library_id(episode_id)
    if not wanted:
        return False
    return common.open_item({"episodeid": wanted},
                            common.resume_option(resume,
                                                 lambda: _episode_resume_point(wanted)),
                            f"episode {wanted}")


def _episode_resume_point(episode_id: int) -> int:
    lists = cache.lists
    with lists.lock:
        opened = list(lists.episodes.values())
    started = lists.continuing.peek()
    for slot in opened:
        show = slot.peek()
        found = None if show is None else _resume_in(show["episodes"], episode_id)
        if found is not None:
            return found
    # Episodes on the "continue" row may belong to unopened shows.
    if started is not None:
        episodes = [entry for entry in started["items"] if entry["kind"] == "episode"]
        return _resume_in(episodes, episode_id) or 0
    # Cache dropped meanwhile: ask Kodi instead of starting from zero.
    answer = common.rpc("VideoLibrary.GetEpisodeDetails",
                        {"episodeid": episode_id, "properties": ["resume"]})
    result = answer.get("result")
    details = result.get("episodedetails") if isinstance(result, dict) else None
    return common.resume_of((details or {}).get("resume"))


def _resume_in(episodes: Sequence[Episode | Resumable], episode_id: int) -> int | None:
    """Return the resume point of *episode_id* among *episodes*, or None."""
    for episode in episodes:
        if episode["id"] == episode_id:
            return int(episode.get("resume") or 0)
    return None
