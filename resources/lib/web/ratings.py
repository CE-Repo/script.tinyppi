# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing title's ratings, for the plot card.

Kodi's InfoLabels carry only the default rating.  The library holds one per
source (``ratings``), the reader's own (``userrating``), the age rating
(``mpaa``) and the IMDb Top 250 place, so the playing title's library entry
is read over JSON-RPC, once per title (see ``SnapshotBuilder._rating_info``).
An episode's age rating is its show's: Kodi keeps it there.  A German one is
read for its FSK level too, which the page draws as the coloured FSK mark.
"""

import re
from collections.abc import Mapping

from web.payloads import Rating, Ratings
from web.player import rpc, video_player_id
from web.values import Json, clean_value

# Rating sources as Kodi names them, and the name the page knows them by (and
# draws the mark of), in the order they are shown.  One source can go by
# several names: ``themoviedb`` and ``tmdb`` are two scraper versions', and
# an NFO writer has its own for Metacritic and Rotten Tomatoes.  Any other
# name (an NFO may carry anything) follows these, alphabetically.
_SOURCES = (("imdb", "imdb"), ("themoviedb", "tmdb"), ("tmdb", "tmdb"),
            ("trakt", "trakt"), ("tvdb", "tvdb"),
            ("metacritic", "metacritic"), ("metascore", "metacritic"),
            ("rottentomatoes", "rottentomatoes"), ("tomatometer", "rottentomatoes"),
            ("tomatometerallcritics", "rottentomatoes"))
_ALIASES = dict(_SOURCES)
# Each name once, tmdb included, so a name outside it sorts after all of them.
_ORDER = {name: index for index, name in enumerate(dict.fromkeys(_ALIASES.values()))}

# More than any scraper writes; an NFO with more is cut off.
_RATING_LIMIT = 8
# A source's name is a label on a badge, not a sentence.
_NAME_LIMIT = 24

# A German age rating, however a scraper or an NFO wrote it: "FSK 12",
# "FSK ab 16 freigegeben", "DE:FSK 18", "Germany:6".  A bare "12" is not one:
# the British board writes its ratings the same way.
_FSK = re.compile(r"(?:\bFSK\s*|^(?:de|ger|germany|deutschland)\s*:\s*(?:FSK\s*)?)"
                  r"(?:ab\s*)?(0|6|12|16|18)(?!\d)", re.IGNORECASE)

_MOVIE = ("ratings", "userrating", "mpaa", "top250")
_EPISODE = ("ratings", "userrating", "tvshowid")


def no_ratings() -> Ratings:
    """Return the ratings of a title the library knows nothing about."""
    return {"ratings": [], "mpaa": "", "fsk": "", "userrating": 0, "top250": 0}


def fsk_level(mpaa: str) -> str:
    """Return the FSK level an age rating names ("0" to "18"), or ""."""
    found = _FSK.search(mpaa)
    return found.group(1) if found else ""


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
        key = clean_value(str(raw)).lower()[:_NAME_LIMIT].rstrip()
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


def _collect(details: Json, aged: Json) -> Ratings:
    """Return the ratings of *details*, with the age rating of *aged*."""
    mpaa = clean_value(str(aged.get("mpaa") or ""))
    return {
        "ratings":    rating_list(details.get("ratings")),
        "mpaa":       mpaa,
        "fsk":        fsk_level(mpaa),
        "userrating": _count(details.get("userrating"), 10),
        "top250":     _count(details.get("top250"), 250),
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
        return _collect(details, details)
    if item_id and kind == "episode":
        return _episode_ratings(item_id)
    return no_ratings()
