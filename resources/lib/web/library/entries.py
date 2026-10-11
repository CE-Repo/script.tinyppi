# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The shapes of the library's lists: as cached, and as sent to the page.

An entry carries an optional field only when Kodi had a meaningful value
for it (see ``common.number``, ``common.rating``); js/films.js,
js/series.js and js/continue.js read them.
"""

from typing import NotRequired, TypedDict

# Artwork paths by library id and kind; kept beside a list, never sent.
ArtPaths = dict[int, dict[str, str]]


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


# What may carry a rating.
Rated = Film | Show | Resumable


# --- As cached (``cache.lists``) ---------------------------------------------

class Films(TypedDict):
    """The film list; ``tag`` changes only with it (for 304 answers)."""

    movies: list[Film]
    art: ArtPaths
    tag: str


class Shows(TypedDict):
    shows: list[Show]
    art: ArtPaths
    tag: str


class Episodes(TypedDict):
    """One series' episodes, with its title (sent along)."""

    title: str
    episodes: list[Episode]
    art: ArtPaths
    tag: str


class Continuing(TypedDict):
    """The "continue" row, most recently played first."""

    items: list[Resumable]
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
    count: int
    tag: str


# Any list the library sends; each carries its ``tag`` as ETag.
Listing = FilmListing | ShowListing | EpisodeListing | ContinueListing
