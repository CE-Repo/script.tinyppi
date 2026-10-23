# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing title's ratings, for the plot card.

Kodi's InfoLabels carry only the default rating.  The library holds one per
source (``ratings``), the reader's own (``userrating``), the age rating
(``mpaa``) and the IMDb Top 250 place, so the playing title's library entry
is read over JSON-RPC, once per title (see ``SnapshotBuilder._rating_info``).
An episode's age rating is its show's: Kodi keeps it there.  A German,
American or British one is read for its board and level too (see
``age_rating``), which the page draws as a shield like the others: the board
on the level's colour, the level beside it.  A film's IMDb and TMDb ids go
with them, for MDBList to be asked by (see web.mdblist).
"""

import re
from collections.abc import Mapping

import xbmc
from web.payloads import Rating, Ratings
from web.player import rpc, video_player_id
from web.values import Json, clean_value

# Rating sources as Kodi and MDBList name them, and the name the page knows
# them by (and draws the mark of), in the order they are shown.  One source
# can go by several names: ``themoviedb`` and ``tmdb`` are two scraper
# versions', an NFO writer has its own for Metacritic and Rotten Tomatoes,
# and MDBList calls Rotten Tomatoes' critics ``tomatoes`` and its audience
# ``popcorn``, which an OMDb-fed scraper calls ``tomatometerallaudience``.
# Any other name (an NFO may carry anything) follows these, alphabetically.
_SOURCES = (("imdb", "imdb"), ("themoviedb", "tmdb"), ("tmdb", "tmdb"),
            ("trakt", "trakt"), ("tvdb", "tvdb"), ("letterboxd", "letterboxd"),
            ("metacritic", "metacritic"), ("metascore", "metacritic"),
            ("metacriticuser", "metacriticuser"),
            ("rottentomatoes", "rottentomatoes"), ("tomatometer", "rottentomatoes"),
            ("tomatometerallcritics", "rottentomatoes"), ("tomatoes", "rottentomatoes"),
            ("popcorn", "popcorn"), ("popcornmeter", "popcorn"),
            ("tomatometerallaudience", "popcorn"),
            ("rogerebert", "rogerebert"), ("myanimelist", "myanimelist"))
_ALIASES = dict(_SOURCES)
# Each name once, tmdb included, so a name outside it sorts after all of them.
_ORDER = {name: index for index, name in enumerate(dict.fromkeys(_ALIASES.values()))}

# Every source named above, and a few more an NFO may carry; one with more
# still is cut off.
_RATING_LIMIT = len(_ORDER) + 4
# A source's name is a label on a badge, not a sentence.
_SOURCE_NAME_LIMIT = 24

# The levels each country's boards give, and the mark each is drawn as (see
# tools/gen_rating_marks.py).  America has two boards, one for films and one
# for television, whose levels never share a name.
_LEVELS = {
    "de": {"0": "fsk0", "6": "fsk6", "12": "fsk12", "16": "fsk16", "18": "fsk18"},
    "us": {"G": "mpa_g", "PG": "mpa_pg", "PG-13": "mpa_pg13", "R": "mpa_r",
           "NC-17": "mpa_nc17", "TV-Y": "tv_y", "TV-Y7": "tv_y7", "TV-G": "tv_g",
           "TV-PG": "tv_pg", "TV-14": "tv_14", "TV-MA": "tv_ma"},
    "gb": {"U": "bbfc_u", "PG": "bbfc_pg", "12A": "bbfc_12a", "12": "bbfc_12",
           "15": "bbfc_15", "18": "bbfc_18", "R18": "bbfc_r18"},
}

# What names the country in front of a level: an NFO's "DE:" or "GB:", the
# country written out, or the board itself.
_COUNTRIES = {
    "de": "de", "ger": "de", "germany": "de", "deutschland": "de", "fsk": "de",
    "us": "us", "usa": "us", "united states": "us", "mpa": "us", "mpaa": "us",
    "gb": "gb", "uk": "gb", "united kingdom": "gb", "great britain": "gb", "bbfc": "gb",
}

# An age rating however a scraper or an NFO wrote it: "FSK 12", "FSK ab 16
# freigegeben", "DE:FSK 18", "Germany:6", "Rated PG-13", "TV-MA", "GB:15".
_AGE = re.compile(
    r"^\s*(?:(?P<country>[a-z ]+?)\s*:\s*)?(?:rated\s+)?(?:(?P<board>fsk|bbfc|mpaa?)\s*)?"
    r"(?:ab\s*)?(?P<level>tv-[a-z0-9]+|nc-17|pg-13|r18|12a|[a-z]+|\d+)"
    r"(?:\s*freigegeben)?\s*$", re.IGNORECASE)

# The country Kodi's language points to, for a level more than one country's
# board gives.  Kodi's English is British unless it is set to American.
_HOMES = {"en": "gb", "en-gb": "gb", "en-us": "us"}

_MOVIE = ("ratings", "userrating", "mpaa", "top250", "uniqueid")
_EPISODE = ("ratings", "userrating", "tvshowid")


def no_ratings() -> Ratings:
    """Return the ratings of a title the library knows nothing about."""
    return {"ratings": [], "mpaa": "", "age": "", "age_level": "", "userrating": 0,
            "top250": 0, "ids": {}}


def home_country() -> str:
    """Return the country Kodi's language points to ("de", "us", "gb"), or ""."""
    language = xbmc.getLanguage(xbmc.ISO_639_1, True).lower().replace("_", "-")
    return "de" if language.startswith("de") else _HOMES.get(language, "")


def age_rating(mpaa: str, home: str = "") -> tuple[str, str]:
    """Return the mark an age rating's shield wears and the level written
    beside it -- ("fsk12", "12"), ("mpa_pg13", "PG-13"), ("tv_ma", "MA") --
    or ("", "") for one with no mark, which is written out instead.

    A rating that names its country or its board is read as that one's.  One
    that names neither is read as the one board that gives its level -- "PG-13"
    is American, "15" British -- and where more than one does ("12", "18",
    "PG") as *home*'s, when *home* is among them.
    """
    found = _AGE.match(mpaa)
    if not found:
        return ("", "")
    level = found["level"].upper()
    named = found["country"] or found["board"]
    if named:
        country = _COUNTRIES.get(named.strip().lower(), "")
    else:
        boards = [country for country, levels in _LEVELS.items() if level in levels]
        country = boards[0] if len(boards) == 1 else (home if home in boards else "")
    mark = _LEVELS.get(country, {}).get(level, "")
    # The television board's name is on the mark already: "TV" | "MA".
    return (mark, level.removeprefix("TV-")) if mark else ("", "")


def _count(value: object, high: int | None = None) -> int:
    """Return *value* if JSON gave it as a whole number above 0 (and up to
    *high*), else 0."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return 0
    return 0 if high is not None and value > high else value


def _rating(name: str, held: object) -> Rating | None:
    """Return one source's rating, or None where it is no rating out of ten."""
    if not isinstance(held, dict):
        return None
    try:
        value = float(held.get("rating") or 0)
    except (TypeError, ValueError):
        return None
    # Out of ten; anything else (NaN included) is scraper junk.
    if not 0 < value <= 10:
        return None
    return {"source": name, "rating": round(value, 1), "votes": _count(held.get("votes"))}


def rating_list(ratings: object) -> list[Rating]:
    """Return the library's ``ratings`` as a list, the known sources first.

    A source that turns up twice (``themoviedb`` beside ``tmdb``) is kept
    once, as it came first.
    """
    if not isinstance(ratings, Mapping):
        return []
    found: dict[str, Rating] = {}
    for raw, held in ratings.items():
        key = clean_value(str(raw)).lower()[:_SOURCE_NAME_LIMIT].rstrip()
        name = _ALIASES.get(key, key)
        entry = _rating(name, held) if name and name not in found else None
        if entry:
            found[name] = entry
    ordered = sorted(found.values(),
                     key=lambda entry: (_ORDER.get(entry["source"], len(_ORDER)), entry["source"]))
    return ordered[:_RATING_LIMIT]


def _answer(method: str, params: Mapping[str, object], key: str) -> Json:
    """Return the object *key* of a JSON-RPC result, or {}."""
    result = rpc(method, params).get("result")
    found = result.get(key) if isinstance(result, dict) else None
    return found if isinstance(found, dict) else {}


def _details(method: str, id_key: str, item_id: int, properties: tuple[str, ...],
             answer: str) -> Json:
    """Return a library entry's *properties*, or {}."""
    return _answer(method, {id_key: item_id, "properties": list(properties)}, answer)


# An IMDb id as Kodi and MDBList keep one: "tt" and its digits.
IMDB_ID = re.compile(r"tt\d+")


def film_ids(details: Json) -> dict[str, str]:
    """Return the ids a film is known by elsewhere -- its IMDb and its TMDb
    one -- as the library holds them, for MDBList to be asked by."""
    held = details.get("uniqueid")
    if not isinstance(held, dict):
        return {}
    imdb = str(held.get("imdb") or "").strip()
    tmdb = str(held.get("tmdb") or "").strip()
    ids = {"imdb": imdb} if IMDB_ID.fullmatch(imdb) else {}
    if tmdb.isdigit() and int(tmdb):
        ids["tmdb"] = tmdb
    return ids


def _collect(details: Json, aged: Json, ids: dict[str, str] | None = None) -> Ratings:
    """Return the ratings of *details*, with the age rating of *aged* and
    the *ids* it is known by elsewhere."""
    mpaa = clean_value(str(aged.get("mpaa") or ""))
    mark, level = age_rating(mpaa, home_country())
    return {
        "ratings":    rating_list(details.get("ratings")),
        "mpaa":       mpaa,
        "age":        mark,
        "age_level":  level,
        "userrating": _count(details.get("userrating"), 10),
        "top250":     _count(details.get("top250"), 250),
        "ids":        ids or {},
    }


def _episode_ratings(episode_id: int) -> Ratings:
    """Return an episode's ratings, with its show's age rating."""
    details = _details("VideoLibrary.GetEpisodeDetails", "episodeid", episode_id,
                       _EPISODE, "episodedetails")
    show_id = _count(details.get("tvshowid"))
    show = _details("VideoLibrary.GetTVShowDetails", "tvshowid", show_id, ("mpaa",),
                    "tvshowdetails") if show_id else {}
    return _collect(details, show)


def playing_ratings() -> Ratings | None:
    """Return the playing title's ratings; None while Kodi cannot say yet
    what is playing.

    A file that is not in the library has none to give, and says so.
    """
    player_id = video_player_id()
    if player_id is None:
        return None
    item = _answer("Player.GetItem", {"playerid": player_id}, "item")
    if not item:
        return None
    item_id = _count(item.get("id"))
    kind = item.get("type")
    if item_id and kind == "movie":
        details = _details("VideoLibrary.GetMovieDetails", "movieid", item_id, _MOVIE,
                           "moviedetails")
        return _collect(details, details, film_ids(details))
    if item_id and kind == "episode":
        return _episode_ratings(item_id)
    return no_ratings()
