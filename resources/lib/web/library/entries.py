# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The shapes of the library's lists: as cached, and as sent to the page.

An entry carries an optional field only when Kodi had a meaningful value
for it (see ``common.number``, ``common.rating``); js/films.js,
js/series.js and js/continue.js read them.
"""

from typing import NotRequired, TypedDict

from web.payloads import Award, Rating

# Artwork paths by library id and kind; kept beside a list, never sent.
ArtPaths = dict[int, dict[str, str]]


class Formats(TypedDict, total=False):
    """A title's formats, where Kodi has read its file (``common.formats``)."""

    video: str
    dv_profile: str
    resolution: str
    audio: str


class Film(TypedDict):
    """A film's tile."""

    id: int
    title: str
    poster: str
    year: NotRequired[int]
    duration: NotRequired[int]
    watched: NotRequired[bool]
    resume: NotRequired[int]
    rating: NotRequired[float]
    rating_from: NotRequired[str]
    added: NotRequired[str]
    # For sorting and filtering on the page (see ``common.formats``).
    genres: NotRequired[list[str]]
    video: NotRequired[str]
    dv_profile: NotRequired[str]
    resolution: NotRequired[str]
    audio: NotRequired[str]


class Show(TypedDict):
    """A series' tile; ``unseen`` counts the episodes still to watch."""

    id: int
    title: str
    poster: str
    fanart: str
    year: NotRequired[int]
    episodes: NotRequired[int]
    unseen: NotRequired[int]
    watched: NotRequired[bool]
    rating: NotRequired[float]
    rating_from: NotRequired[str]
    added: NotRequired[str]
    genres: NotRequired[list[str]]


class Episode(TypedDict):
    """An episode of an opened series."""

    id: int
    title: str
    thumb: str
    season: NotRequired[int]
    episode: NotRequired[int]
    duration: NotRequired[int]
    watched: NotRequired[bool]
    resume: NotRequired[int]


class Resumable(TypedDict):
    """An entry of the "continue" row: a film or an episode (``kind``)."""

    kind: str
    id: int
    resume: int
    title: str
    duration: int
    lastplayed: NotRequired[str]
    poster: NotRequired[str]
    thumb: NotRequired[str]
    show: NotRequired[str]
    tvshowid: NotRequired[int]
    year: NotRequired[int]
    season: NotRequired[int]
    episode: NotRequired[int]
    rating: NotRequired[float]
    rating_from: NotRequired[str]


class Upcoming(TypedDict):
    """An entry of the "next up" row: the next unwatched episode of a show
    being watched."""

    kind: str
    id: int
    title: str
    tvshowid: int
    show: str
    poster: str
    thumb: str
    season: NotRequired[int]
    episode: NotRequired[int]
    duration: NotRequired[int]
    rating: NotRequired[float]
    rating_from: NotRequired[str]


class Person(TypedDict):
    """One of the cast, and the role played ("" where none is known)."""

    name: str
    role: str
    thumbnail: NotRequired[str]
    # The person's TMDb id, for a link to their page; only where TMDb's
    # credits of the title name them unambiguously.
    tmdb: NotRequired[int]


class Related(TypedDict):
    """A title a details page leads on to (``kind`` movie or tvshow).

    One the library holds carries its library ``id`` and the tag of its
    poster, as a tile does; one it does not, TMDb's poster as a ``portrait``
    tag (see ``details.portrait_path``), and the clients open its TMDb page.
    """

    kind: str
    tmdb: int
    title: str
    year: NotRequired[int]
    id: NotRequired[int]
    poster: NotRequired[str]
    portrait: NotRequired[str]
    # The title the page is about, in its own film series.
    current: NotRequired[bool]


class Collection(TypedDict):
    """The film series a film belongs to on TMDb, in release order."""

    name: str
    parts: list[Related]


class Airing(TypedDict):
    """An episode of a show TMDb dates: the next to air or the last aired."""

    season: int
    episode: int
    date: NotRequired[str]
    title: NotRequired[str]


class Details(TypedDict):
    """A title's details (``details.details``), sent as they are.

    ``kind`` is movie, tvshow or episode; anything else only where the
    library has it.
    """

    kind: str
    id: int
    title: str
    ratings: list[Rating]
    watched: NotRequired[bool]
    resume: NotRequired[int]
    plot: NotRequired[str]
    tagline: NotRequired[str]
    show: NotRequired[str]
    premiered: NotRequired[str]
    # A film's from TMDb: budget and takings in US dollars, and the day it
    # first ran in cinemas (YYYY-MM-DD) in the country Kodi's language names.
    budget: NotRequired[int]
    revenue: NotRequired[int]
    cinema: NotRequired[str]
    # The country that day is the first in cinemas of ("DE", "US"); absent
    # where it is TMDb's primary release date instead.
    cinema_country: NotRequired[str]
    # A film's series on TMDb, with this film among its parts.
    collection: NotRequired[Collection]
    # Titles of the library TMDb recommends after this one, of its kind.
    recommended: NotRequired[list[Related]]
    # A show's state on TMDb: returning, ended, canceled, production,
    # planned or pilot; who airs it; how many seasons and episodes there
    # are in all (the library may hold fewer); and the episodes either
    # side of today.
    status: NotRequired[str]
    networks: NotRequired[list[str]]
    tmdb_seasons: NotRequired[int]
    tmdb_episodes: NotRequired[int]
    next_episode: NotRequired[Airing]
    last_episode: NotRequired[Airing]
    mpaa: NotRequired[str]
    age: NotRequired[str]
    age_level: NotRequired[str]
    year: NotRequired[int]
    duration: NotRequired[int]
    season: NotRequired[int]
    episode: NotRequired[int]
    tvshowid: NotRequired[int]
    userrating: NotRequired[int]
    top250: NotRequired[int]
    awards: NotRequired[list[Award]]
    genres: NotRequired[list[str]]
    directors: NotRequired[list[str]]
    writers: NotRequired[list[str]]
    studios: NotRequired[list[str]]
    countries: NotRequired[list[str]]
    cast: NotRequired[list[Person]]
    # Regie/Drehbuch roles use stable codes: director or writer.
    crew: NotRequired[list[Person]]
    cast_more: NotRequired[bool]
    # The tags of its pictures (see ``common.tag``), for /api/art.
    poster: NotRequired[str]
    fanart: NotRequired[str]
    thumb: NotRequired[str]
    video: NotRequired[str]
    dv_profile: NotRequired[str]
    resolution: NotRequired[str]
    audio: NotRequired[str]


# What may carry a rating.
Rated = Film | Show | Resumable | Upcoming


# --- As cached (``cache.lists``) ---------------------------------------------

class Films(TypedDict):
    """The film list; ``tag`` changes only with it (for 304 answers).

    ``tmdb`` finds a film by the TMDb id Kodi's scraper filed it under (for
    the series and recommendations on a details page); never sent.
    """

    movies: list[Film]
    art: ArtPaths
    tmdb: dict[int, Film]
    tag: str


class Shows(TypedDict):
    shows: list[Show]
    art: ArtPaths
    tmdb: dict[int, Show]
    tag: str


class Episodes(TypedDict):
    """One series' episodes, with its title (sent along)."""

    title: str
    episodes: list[Episode]
    art: ArtPaths
    tag: str


class Continuing(TypedDict):
    """The "continue" row, most recently played first, and the "next up"
    row (``next``), the show watched last first."""

    items: list[Resumable]
    next: list[Upcoming]
    art: ArtPaths
    tag: str


# --- As sent (without the art paths) ---------------------------------------

class FilmListing(TypedDict):
    movies: list[Film]
    count: int
    tag: str


class ShowListing(TypedDict):
    shows: list[Show]
    count: int
    tag: str


class EpisodeListing(TypedDict):
    tvshowid: int
    title: str
    episodes: list[Episode]
    count: int
    tag: str


class ContinueListing(TypedDict):
    items: list[Resumable]
    next: list[Upcoming]
    count: int
    tag: str


# Any list the library sends; each carries its ``tag`` as ETag.
Listing = FilmListing | ShowListing | EpisodeListing | ContinueListing
