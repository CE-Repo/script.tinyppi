# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A library title's details, for the page's details view (``/api/details``).

Read when a title is opened, one query each and not cached: the lists carry
what a tile needs, this what only one opened title needs.  The ratings are
the library's own (see ``web.ratings.rating_list``); MDBList and WhatsOn are
asked only for the playing title.
"""

from web.library import common
from web.library.entries import Details, Person
from web.ratings import age_rating, home_country, rating_list
from web.values import Json, Unchecked, clean_value, library_id, plain_text

# The cast's first twenty in billing order, as on the overview card.
_CAST_LIMIT = 20
# A plot is a few paragraphs; a text longer still is cut off.
_PLOT_LIMIT = 4000

_FILM = ("title", "plot", "tagline", "genre", "director", "writer", "cast", "studio",
         "country", "mpaa", "year", "runtime", "ratings", "userrating", "top250",
         "streamdetails", "premiered", "art")
_SHOW = ("title", "plot", "genre", "studio", "cast", "mpaa", "year", "ratings",
         "userrating", "premiered", "episode", "season", "art")
_EPISODE = ("title", "plot", "showtitle", "tvshowid", "season", "episode", "director",
            "writer", "cast", "firstaired", "runtime", "ratings", "userrating",
            "streamdetails", "art")

# The pictures a details view stands under, by kind of title: the art kind
# the artwork route serves each as and the keys Kodi files it under, best
# first.  An episode has its still where a film and a show have a poster and
# a backdrop.
_TITLE_PICTURES = (("poster", common.POSTER_KEYS), ("fanart", common.FANART_KEYS))
_PICTURES = {"movie": _TITLE_PICTURES, "tvshow": _TITLE_PICTURES,
             "episode": (("thumb", ("thumb",)),)}

# Each kind's query: method, id parameter, answer key and properties.
_KINDS = {
    "movie":   ("VideoLibrary.GetMovieDetails", "movieid", "moviedetails", _FILM),
    "tvshow":  ("VideoLibrary.GetTVShowDetails", "tvshowid", "tvshowdetails", _SHOW),
    "episode": ("VideoLibrary.GetEpisodeDetails", "episodeid", "episodedetails", _EPISODE),
}

# Optional whole numbers and the key each is sent under.
_NUMBERS = (("year", "year", 1), ("runtime", "duration", 1), ("season", "season", 0),
            ("episode", "episode", 0), ("tvshowid", "tvshowid", 1),
            ("userrating", "userrating", 1), ("top250", "top250", 1))
# Optional lists of names and the key each is sent under (all of them: a
# details view has room for every genre and director).
_NAMES = (("genre", "genres"), ("director", "directors"), ("writer", "writers"),
          ("studio", "studios"), ("country", "countries"))


def details(kind: str, item_id: Unchecked) -> Details | None:
    """Return the details of a film, series or episode, or None.

    None for an unknown kind or id, or a title the library no longer holds.
    """
    query = _KINDS.get(kind)
    wanted = library_id(item_id)
    if query is None or not wanted:
        return None
    method, id_key, answer_key, properties = query
    result = common.rpc(method, {id_key: wanted, "properties": list(properties)}).get("result")
    row = result.get(answer_key) if isinstance(result, dict) else None
    if not isinstance(row, dict):
        return None
    found: Details = {"kind": kind, "id": wanted, "title": common.clean_title(row),
                      "ratings": rating_list(row.get("ratings"))}
    _texts(found, row)
    _numbers(found, row)
    _people(found, row)
    _formats(found, row)
    _pictures(found, row, _PICTURES[kind])
    return found


# Optional texts and the key each is sent under: prose keeps its line
# breaks, a name does not.
_TEXTS = (("plot", "plot", plain_text), ("tagline", "tagline", plain_text),
          ("showtitle", "show", clean_value))


def _texts(found: Details, row: Json) -> None:
    """Add the plot, the tagline, the show, the date and the age rating."""
    for source, key, clean in _TEXTS:
        text = clean(str(row.get(source) or ""))[:_PLOT_LIMIT]
        if text:
            found[key] = text  # type: ignore[literal-required]
    date = common.added(row.get("premiered") or row.get("firstaired"))
    if date:
        found["premiered"] = date
    mpaa = clean_value(str(row.get("mpaa") or ""))
    if mpaa:
        found["mpaa"] = mpaa
        found["age"], found["age_level"] = age_rating(mpaa, home_country())


def _numbers(found: Details, row: Json) -> None:
    """Add the whole numbers Kodi has meaningful values for."""
    for source, key, low in _NUMBERS:
        value = common.number(row, source, low)
        if value is not None:
            found[key] = value  # type: ignore[literal-required]


def _people(found: Details, row: Json) -> None:
    """Add the name lists and the cast."""
    for source, key in _NAMES:
        names = common.names(row, source, None)
        if names:
            found[key] = names  # type: ignore[literal-required]
    cast = _cast(row.get("cast"))
    if cast:
        found["cast"] = cast[:_CAST_LIMIT]
        found["cast_more"] = len(cast) > _CAST_LIMIT


def _cast(raw: object) -> list[Person]:
    """Return the cast in billing order, each with the role played."""
    if not isinstance(raw, list):
        return []
    people = [entry for entry in raw if isinstance(entry, dict)]
    people.sort(key=lambda entry: common.number(entry, "order", low=0) or 0)
    cast: list[Person] = []
    for entry in people:
        name = clean_value(str(entry.get("name") or ""))
        if name:
            cast.append({"name": name, "role": clean_value(str(entry.get("role") or ""))})
    return cast


def _pictures(found: Details, row: Json,
              wanted: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    """Add the tags of the title's pictures, for their artwork addresses.

    The same tags the shelves give the same pictures (``common.tag``), so a
    poster already fetched for a wall is not fetched again.
    """
    pictures = common.art_of(row)
    for kind, keys in wanted:
        path = common.picture(pictures, keys)
        if path:
            found[kind] = common.tag(path)  # type: ignore[literal-required]


def _formats(found: Details, row: Json) -> None:
    """Add the formats of a film's or an episode's file."""
    formats = common.formats(row.get("streamdetails"))
    if "video" in formats:
        found["video"] = formats["video"]
    if "dv_profile" in formats:
        found["dv_profile"] = formats["dv_profile"]
    if "resolution" in formats:
        found["resolution"] = formats["resolution"]
    if "audio" in formats:
        found["audio"] = formats["audio"]
