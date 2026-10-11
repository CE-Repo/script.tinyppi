# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Marking titles seen or unseen and clearing resume points."""

import time

import xbmc
from web.library import cache, common
from web.library.common import log
from web.values import Json, Unchecked, library_id

# Id key and setter per markable kind.  Shows are marked via their episodes
# (Kodi counts a show as watched when all episodes are).
_MARKABLE = {
    "movie":   ("movieid", "VideoLibrary.SetMovieDetails"),
    "episode": ("episodeid", "VideoLibrary.SetEpisodeDetails"),
}


def set_watched(kind: str, item_id: Unchecked, watched: bool) -> bool:
    """Mark a film, episode or show as watched or unwatched, like Kodi does.

    Watched sets a play count and clears the resume point; unwatched clears
    the play count and keeps the resume point.  Returns whether the library
    accepted it; the cache is dropped either way.
    """
    wanted = library_id(item_id)
    if not wanted:
        return False

    if kind == "tvshow":
        done = _mark_show(wanted, watched)
    elif kind in _MARKABLE:
        done = _mark_one(kind, wanted, watched)
    else:
        return False
    # Drop now, so the page's immediate re-read sees the change.
    cache.invalidate()
    if done:
        log(f"{kind} {wanted} marked {'seen' if watched else 'unseen'} "
            "from the dashboard", xbmc.LOGINFO)
    return done


def clear_resume(kind: str, item_id: Unchecked) -> bool:
    """Clear a film's or episode's resume point, keeping its play count."""
    if kind not in _MARKABLE:
        return False
    wanted = library_id(item_id)
    if not wanted:
        return False
    key, method = _MARKABLE[kind]
    done = common.rpc(method, {key: wanted,
                               "resume": {"position": 0, "total": 0}}).get("result") == "OK"
    cache.invalidate()
    if done:
        log(f"{kind} {wanted}: resume point cleared from the dashboard",
            xbmc.LOGINFO)
    return done


def _mark_one(kind: str, wanted: int, watched: bool) -> bool:
    key, method = _MARKABLE[kind]
    params: dict[str, object] = {key: wanted, "playcount": 1 if watched else 0}
    if watched:
        params["resume"] = {"position": 0, "total": 0}
        params["lastplayed"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return common.rpc(method, params).get("result") == "OK"


def _mark_show(show_id: int, watched: bool) -> bool:
    """Mark every episode of a show, writing only those that change."""
    answer = common.rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": show_id, "properties": ["playcount", "resume"],
    })
    if answer.get("error"):
        log(f"VideoLibrary.GetEpisodes failed for {show_id}: {answer['error']}")
        return False

    done = True
    for row in common.rows_of(answer, "episodes"):
        if _needs_mark(row, watched) and not _mark_one("episode", row["episodeid"], watched):
            done = False
    return done


def _needs_mark(row: Json, watched: bool) -> bool:
    """Return whether marking an episode *watched* would change its row.

    Marking watched also clears a resume point, so a played episode that
    was started again still counts as a change.
    """
    if not isinstance(row.get("episodeid"), int):
        return False
    played = isinstance(row.get("playcount"), int) and row["playcount"] > 0
    started = common.resume_of(row.get("resume")) > 0
    return played != watched or (watched and started)
