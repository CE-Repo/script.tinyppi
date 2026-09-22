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

Dropping it is also announced.  Every screen holds a copy of one of these lists
for as long as it is open, and a copy is wrong the moment a film is watched to
the end or switched off in the middle -- so a number that moves with every drop
rides out with every snapshot (``revision``), and a page or an app that sees it
move reads its list again.  Without it a dashboard left on a television showed
yesterday's answer until somebody reloaded the page.

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
_PROPERTIES = ("title", "year", "art", "runtime", "playcount", "resume",
               "ratings")

# Which piece of art stands for a film, best first.  A library entry usually
# carries a poster; ``thumb`` is what a film scraped from a folder of files
# tends to have instead.
_POSTER_KEYS = ("poster", "thumb")
_FANART_KEYS = ("fanart",)

# Which rating a tile wears, best first.  A library holds one per scraper that
# ever wrote to it -- Kodi files them under the scraper's own name -- and the
# two that matter are the two people quote at each other.  IMDb first because
# it is the one somebody means when they say a film is an eight.
#
# ``tmdb`` beside ``themoviedb`` is not the same scraper twice: the name
# depends on which version of the scraper wrote the entry, and a library that
# has been carried across a few Kodi releases holds both.
_RATING_SOURCES = (("imdb", "imdb"),
                   ("themoviedb", "tmdb"),
                   ("tmdb", "tmdb"))

# How long a list is held before it is read again.  The library changing is a
# notification rather than something to poll for (see ``invalidate``), so this
# is only the floor under a box whose notifications never arrive -- an add-on
# writing into the database behind Kodi's back, say.
_TTL = 300.0

_lock = threading.Lock()
_catalogue: dict | None = None
_read_at = 0.0

# How long after playback stops before the lists are dropped again.
#
# What Kodi writes when a title ends -- the point to resume it from, and the
# play count of one watched to the end -- is written by a background job that
# outlives the announcement the box makes when playback stops, and only the
# play-count half of it is announced to add-ons at all.  So the end of a title
# is taken as notice that the lists are about to be wrong rather than that they
# already are, and they are dropped once the box has had a moment to write.
#
# Two distances rather than one: the first is for a box that writes at once,
# which is nearly all of them, and the second for one whose video database is
# on the far end of a network share.  Dropping a list twice costs one query
# that finds nothing has changed; dropping it too early costs an evening of a
# phone showing a film as unwatched.
_SETTLE = (1.5, 5.0)

# Counts up every time the held lists are dropped, and rides out with every
# snapshot (see ``_Producer.run`` in web/server.py).  It is the whole of how a
# phone finds out that what it drew is no longer what the box holds: the page
# and the app each remember the number their lists were read at, and read them
# again when it moves.  Without it a dashboard shows the film it watched last
# night as unwatched until somebody reloads the page.
_revision = 0
# When deferred drops fall due, soonest first; see ``settle``.
_settling: list[float] = []

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
# The films and episodes somebody stopped in the middle of, newest first; see
# ``continuing``.  Held and dropped with the rest.
_continuing: dict | None = None
_continuing_read_at = 0.0


def _log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"{_ADDON_ID} --> library: {message}", level=level)


# --- The list --------------------------------------------------------------

def invalidate() -> None:
    """Forget the held lists, so the next reader reads fresh ones.

    Called from the monitor whenever Kodi says the video database moved.  It
    does not read anything itself: a scan finishing while nobody is looking at
    a dashboard should cost nothing at all.

    The revision moves with it, which is what tells the screens already showing
    a list that theirs is now the old one.
    """
    global _catalogue, _read_at, _shows, _shows_read_at, _revision
    global _continuing, _continuing_read_at
    with _lock:
        _catalogue = None
        _read_at = 0.0
        _shows = None
        _shows_read_at = 0.0
        _continuing = None
        _continuing_read_at = 0.0
        _episodes.clear()
        _episode_art.clear()
        _revision += 1


def settle() -> None:
    """Drop the lists again shortly, a title having just ended.

    Kodi writes where the title got to after it has said that playback stopped,
    and says nothing at all when what it wrote was only a resume point -- which
    is the half of it that a title switched off in the middle produces.  So the
    stop is noted here and the lists are dropped once the writing is done (see
    ``_SETTLE``), rather than at the moment of the stop, when dropping them
    would only re-read the same stale rows.
    """
    now = time.monotonic()
    with _lock:
        _settling[:] = sorted(now + delay for delay in _SETTLE)


def revision() -> int:
    """A number that changes whenever the held lists are dropped.

    Read on the snapshot producer's own cadence, which is also what runs the
    deferred drops ``settle`` asked for: the add-on has no timer of its own to
    spare -- a thread parked on one is a thread Kodi waits for on the way out
    (see the shutdown note in service/monitor.py) -- and the producer is
    already awake five times a second.
    """
    due = False
    with _lock:
        now = time.monotonic()
        while _settling and _settling[0] <= now:
            _settling.pop(0)
            due = True
        held = _revision
    if not due:
        return held
    # Outside the lock: invalidate takes it for itself.
    invalidate()
    with _lock:
        return _revision


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
        _rate(film, row.get("ratings"))
        films.append(film)

        signature = zlib.crc32(
            f"{movie_id}\x1f{title}\x1f{film['poster']}\x1f"
            f"{film.get('resume', 0)}\x1f{film.get('watched', False)}\x1f"
            f"{film.get('duration', 0)}\x1f{film.get('rating', 0)}"
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
    """Hang the best rating a library holds on a tile, if it holds one.

    Two fields rather than one: the number is what the badge draws, and where
    it came from is what the badge says it is.  A number alone in the corner of
    a poster is a number somebody has to guess the provenance of, and the two
    houses do not agree closely enough for that to be a safe guess.

    Nothing is written at all where there is no rating worth drawing, so a
    library that was never scraped -- a folder of files -- carries no badges
    rather than a wall of noughts.
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
        # Out-of-range answers are a scraper having written something odd, not
        # a film nobody liked: a rating is out of ten.
        if not 0 < value <= 10:
            continue
        entry["rating"] = round(value, 1)
        entry["rating_from"] = name
        return


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


# Bumped whenever an address starts answering with a different picture than
# it used to.  These are handed out with a week and an immutable on them, so a
# browser that has already been given the full-size poster would go on drawing
# it until the week was up -- the tag is the only thing that can tell it
# otherwise (see _shelf_art in web/server.py).
_ART_REVISION = "#2"


def _tag(path: str) -> str:
    """A short, stable name for a picture, hung on its address so a browser
    fetches one poster once rather than once per visit."""
    if not path:
        return ""
    named = (path + _ART_REVISION).encode("utf-8", "replace")
    return f"{zlib.crc32(named):08x}"


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
_SHOW_PROPERTIES = ("title", "year", "art", "episode", "watchedepisodes",
                    "ratings")

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

    Only episodes whose show has been opened, or which stand on the row of
    things left half-watched, are here -- which are the only ways an address
    for one can have reached a browser in the first place.
    """
    try:
        wanted = int(episode_id)
    except (TypeError, ValueError):
        return ""
    with _lock:
        entry = _episode_art.get(wanted)
        dropped = _continuing is None
    if entry is None and dropped:
        # The lists were dropped since the address was handed out, and the row
        # of things half-watched is the one list that hands out episodes whose
        # show nobody opened: reading it again files their pictures again.
        continuing()
        with _lock:
            entry = _episode_art.get(wanted)
    return (entry or {}).get(kind, "")


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
        fanart = _picture(pictures, _FANART_KEYS)
        art[show_id] = {"poster": poster, "fanart": fanart}

        # The fanart travels with the show, where a film's does not: opening a
        # series gives its episodes a picture of it to stand under, and the
        # shape that picture wants is the one a television is -- which is the
        # fanart's and not the poster's.
        show = {"id": show_id, "title": title,
                "poster": _tag(poster), "fanart": _tag(fanart)}
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
        _rate(show, row.get("ratings"))
        series.append(show)

        signature = zlib.crc32(
            f"{show_id}\x1f{title}\x1f{show['poster']}\x1f{show['fanart']}\x1f"
            f"{show.get('unseen', -1)}\x1f{show.get('episodes', 0)}\x1f"
            f"{show.get('rating', 0)}"
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
            f"{entry.get('resume', 0)}\x1f{entry.get('watched', False)}\x1f"
            f"{entry.get('duration', 0)}"
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
        started = _continuing
    for show in held:
        for episode in show["episodes"]:
            if episode["id"] == episode_id:
                return int(episode.get("resume") or 0)
    # An episode pressed on the row of things left half-watched may belong to a
    # show nobody has opened, and that row holds its resume point as well.
    if started is not None:
        for entry in started["items"]:
            if entry["kind"] == "episode" and entry["id"] == episode_id:
                return int(entry.get("resume") or 0)
        return 0
    # The lists were dropped between the row being drawn and the press, which
    # is what a title ending just before it looks like: asked of Kodi instead,
    # rather than starting the episode from the beginning.
    answer = rpc("VideoLibrary.GetEpisodeDetails",
                 {"episodeid": episode_id, "properties": ["resume"]})
    result = answer.get("result")
    details = result.get("episodedetails") if isinstance(result, dict) else None
    return _resume((details or {}).get("resume"))


# --- Continue watching -----------------------------------------------------

# How many titles the row holds.  It is the way back into what was being
# watched, not a history: a phone shows four of them, and the thirtieth thing
# somebody stopped in the middle of is not what they came back for.
_CONTINUE_LIMIT = 30

# Only what somebody would actually resume: Kodi's own "in progress" filter,
# which is a resume point on a title not yet watched to the end.
_IN_PROGRESS = {"field": "inprogress", "operator": "true", "value": ""}

_CONTINUE_FILM_PROPERTIES = ("title", "year", "art", "runtime", "resume",
                             "lastplayed")
_CONTINUE_EPISODE_PROPERTIES = ("title", "showtitle", "tvshowid", "season",
                                "episode", "art", "runtime", "resume",
                                "lastplayed")

# An episode stands on the row as its show: the show's poster is what the row
# is scanned for, and a still from the middle of season three is not.
_EPISODE_POSTER_KEYS = ("tvshow.poster", "season.poster", "poster")


def continuing(films: bool = True, series: bool = True) -> dict:
    """The films and episodes left half-watched, the last one seen first.

    One list of both, as ``{"items": [...], "count": int, "tag": str}``: the
    row is the quickest way back into whatever was on, and whether that was a
    film or an episode is not what somebody reaching for it is thinking about.
    Each entry says which of the two it is under ``kind``.

    ``films`` and ``series`` leave out the half a box does not offer, so a box
    whose series shelf is switched off does not put episodes on the row.
    """
    global _continuing, _continuing_read_at
    with _lock:
        held = _continuing
        fresh = (held is not None
                 and time.monotonic() - _continuing_read_at < _TTL)
    if held is None or not fresh:
        held = _read_continuing()
        with _lock:
            _continuing = held
            _continuing_read_at = time.monotonic()
            # The row hands out addresses for episodes whose show may never
            # have been opened; the pictures behind them are filed with the
            # rest (see ``episode_art_path``).
            _episode_art.update(held["art"])

    items = [entry for entry in held["items"]
             if (films and entry["kind"] == "movie")
             or (series and entry["kind"] == "episode")]
    return {"items": items, "count": len(items),
            "tag": f"{int(films)}{int(series)}-{held['tag']}"}


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
        # A film has no season and number to be called by instead.
        if entry is None or not entry["title"]:
            continue
        pictures = row.get("art") if isinstance(row.get("art"), dict) else {}
        entry["poster"] = _tag(_picture(pictures, _POSTER_KEYS))
        year = row.get("year")
        if isinstance(year, int) and year > 0:
            entry["year"] = year
        listing.append(entry)

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
        season = row.get("season")
        if isinstance(season, int) and season >= 0:
            entry["season"] = season
        number = row.get("episode")
        if isinstance(number, int) and number >= 0:
            entry["episode"] = number
        listing.append(entry)

    # Kodi writes the time as "2026-09-22 20:15:00", which sorts as text in the
    # order it happened -- so the two lists are one list without a date parser.
    listing.sort(key=lambda entry: entry.get("lastplayed", ""), reverse=True)
    del listing[_CONTINUE_LIMIT:]

    signature = zlib.crc32(b"")
    for entry in listing:
        signature = zlib.crc32(
            f"{entry['kind']}\x1f{entry['id']}\x1f{entry['title']}\x1f"
            f"{entry.get('poster', '')}\x1f{entry.get('resume', 0)}\x1f"
            f"{entry.get('lastplayed', '')}"
            .encode("utf-8", "replace"), signature)

    _log(f"{len(listing)} titles in progress read from the video database")
    return {"items": listing, "art": art,
            "tag": f"{len(listing):x}-{signature:08x}"}


def _continue_entry(row, kind: str) -> dict | None:
    """What a film and an episode on the row have in common, or None for a row
    that is not one: no id, or a resume point too small to be worth one."""
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
        # A file the scraper never timed still knows how long it is from the
        # resume point Kodi wrote, and the bar needs a length to be drawn.
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
