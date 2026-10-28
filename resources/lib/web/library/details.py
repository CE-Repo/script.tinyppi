# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""A library title's details, for the page's details view (``/api/details``).

Read when a title is opened, one query each and not cached: the lists carry
what a tile needs, this what only one opened title needs.  The ratings are
the ones the now-playing card shows for the same title: the library's,
MDBList's over them, WhatsOn's Rotten Tomatoes certificates and what both
lack, the IMDb Top 250 place and the big awards (see ``web.ratings``).  A
film MDBList or WhatsOn is being asked for is waited on for a moment; one
that takes longer has the library's ratings this time and theirs the next,
from what they keep.
"""

import hashlib
import time
from collections import OrderedDict
from threading import Lock

from core import settings
from web import mdblist, tmdb, whatson
from web.library import common
from web.library.entries import Details, Person
from web.payloads import Ratings
from web.ratings import home_country, title_ratings
from web.values import Json, Unchecked, clean_value, library_id, plain_text

# A plot is a few paragraphs; a text longer still is cut off.
_PLOT_LIMIT = 4000
_PORTRAITS: OrderedDict[str, str] = OrderedDict()
_PORTRAITS_LOCK = Lock()

# How long a details read waits on MDBList and WhatsOn, and how often it
# looks whether they have answered, in seconds.
_RATINGS_WAIT = 4.0
_RATINGS_STEP = 0.2
_sleep = time.sleep
_clock = time.monotonic

_FILM = ("title", "plot", "tagline", "genre", "director", "writer", "cast", "studio",
         "country", "mpaa", "year", "runtime", "ratings", "userrating", "top250",
         "streamdetails", "premiered", "art", "uniqueid", "playcount", "resume")
_SHOW = ("title", "plot", "genre", "studio", "cast", "mpaa", "year", "ratings",
         "userrating", "premiered", "episode", "season", "art", "uniqueid", "watchedepisodes")
_EPISODE = ("title", "plot", "showtitle", "tvshowid", "season", "episode", "director",
            "writer", "cast", "firstaired", "runtime", "ratings", "userrating",
            "streamdetails", "art", "playcount", "resume")

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
            ("episode", "episode", 0), ("tvshowid", "tvshowid", 1))
# Optional lists of names and the key each is sent under (all of them: a
# details view has room for every genre and director).
_NAMES = (("genre", "genres"), ("director", "directors"), ("writer", "writers"),
          ("studio", "studios"), ("country", "countries"))


# The crew's jobs as TMDb names them, and the strings the add-on says them
# in; any other job is shown as TMDb wrote it.
_JOBS = {
    "Director": 32386, "Writer": 32407, "Producer": 32446, "Executive Producer": 32447,
    "Co-Producer": 32448, "Associate Producer": 32449, "Line Producer": 32450,
    "Original Music Composer": 32451, "Music": 32452, "Director of Photography": 32453,
    "Editor": 32454, "Casting": 32455, "Production Design": 32456, "Art Direction": 32457,
    "Set Decoration": 32458, "Costume Design": 32459, "Makeup Artist": 32460,
    "Visual Effects Supervisor": 32461, "Sound Designer": 32462, "Stunt Coordinator": 32463,
    "Screenplay": 32464, "Novel": 32465, "Story": 32466, "Characters": 32467,
    "Creator": 32468, "Teleplay": 32469, "Assistant Director": 32470,
    "Script Supervisor": 32471, "Supervising Sound Editor": 32472,
}


def portrait_path(tag: str) -> str:
    """Resolve only registered Kodi/TMDb portraits, never arbitrary request paths."""
    with _PORTRAITS_LOCK:
        return _PORTRAITS.get(tag, "")


def _portrait(path: str) -> str:
    """Keep a bounded set of portrait paths for the authenticated artwork route.

    Tagged by 64 bits of the path rather than the shelves' 32 (``common.tag``):
    the tag is the only key a portrait is found by, and among thousands of
    them a 32-bit one would now and then hand out somebody else's face.
    """
    tag = hashlib.blake2b(path.encode("utf-8", "replace"), digest_size=8).hexdigest()
    with _PORTRAITS_LOCK:
        _PORTRAITS[tag] = path
        _PORTRAITS.move_to_end(tag)
        if len(_PORTRAITS) > 4096:
            _PORTRAITS.popitem(last=False)
    return tag


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
                      "ratings": []}
    _rated(found, _shown(title_ratings(kind, row)))
    _texts(found, row)
    _numbers(found, row)
    _watching(found, row, kind)
    _people(found, row)
    _from_tmdb(found, row, kind)
    common.add_formats(found, row.get("streamdetails"))
    _pictures(found, row, _PICTURES[kind])
    return found


# Optional texts and the key each is sent under: prose keeps its line
# breaks, a name does not.
_TEXTS = (("plot", "plot", plain_text), ("tagline", "tagline", plain_text),
          ("showtitle", "show", clean_value))


def _shown(ratings: Ratings) -> Ratings:
    """Return *ratings* as the now-playing card shows them (see
    ``SnapshotBuilder._shown_ratings``), waiting a moment on MDBList and
    WhatsOn where they are being asked."""
    mdblist_key, whatson_key = mdblist.api_key(), whatson.api_key()
    ids = ratings["ids"]
    deadline = _clock() + _RATINGS_WAIT
    while True:
        shown = mdblist.with_mdblist(ratings, key=mdblist_key)
        waiting = mdblist.asking(mdblist_key, ids)
        if not waiting:
            shown = whatson.with_whatson(shown, key=whatson_key)
            waiting = whatson.asking(ids, whatson_key)
        if not waiting or _clock() >= deadline:
            return shown
        _sleep(_RATINGS_STEP)


def _rated(found: Details, ratings: Ratings) -> None:
    """Add the ratings, the age rating, the reader's own, the Top 250 place
    and the awards, each only where there is one."""
    found["ratings"] = ratings["ratings"]
    if ratings["mpaa"]:
        found["mpaa"] = ratings["mpaa"]
        found["age"], found["age_level"] = ratings["age"], ratings["age_level"]
    if ratings["userrating"]:
        found["userrating"] = ratings["userrating"]
    if ratings["top250"]:
        found["top250"] = ratings["top250"]
    if ratings["awards"]:
        found["awards"] = ratings["awards"]


def _texts(found: Details, row: Json) -> None:
    """Add the plot, the tagline, the show and the date."""
    for source, key, clean in _TEXTS:
        text = clean(str(row.get(source) or ""))[:_PLOT_LIMIT]
        if text:
            found[key] = text  # type: ignore[literal-required]
    date = common.added(row.get("premiered") or row.get("firstaired"))
    if date:
        found["premiered"] = date


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
        found["cast"] = cast
        found["cast_more"] = False


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
            person: Person = {"name": name, "role": clean_value(str(entry.get("role") or ""))}
            thumbnail = common.picture(entry, ("thumbnail",))
            if thumbnail:
                person["thumbnail"] = _portrait(thumbnail)
            cast.append(person)
    return cast


def _from_tmdb(found: Details, row: Json, kind: str) -> None:
    """Keep Kodi's names and roles, filling missing images from title credits
    and giving each person found there their TMDb id; add the rest of the
    crew TMDb names, and a film's budget, takings and cinema release."""
    key = tmdb.api_key()
    if not key:
        return
    cast = found.get("cast", [])
    crew = _crew(found)
    answer = tmdb.lookup(kind, row, key)
    credits = answer.get("credits")
    if isinstance(credits, dict):
        _credited(cast, crew, credits)
        crew += _more_crew(crew, credits)
    if crew:
        found["crew"] = crew
    if kind == "movie":
        _film_facts(found, answer)


def _credited(cast: list[Person], crew: list[Person], credits: Json) -> None:
    _match(cast, credits, ("cast", "guest_stars"), "")
    for role in ("director", "writer"):
        _match([person for person in crew if person["role"] == role], credits, ("crew",), role)


def _more_crew(listed: list[Person], credits: Json) -> list[Person]:
    """Everyone else behind the camera, once each with all their jobs, in
    Kodi's language where the add-on knows the job ("Producer, Screenplay").

    Those Kodi already lists as director or writer stay as they are.
    """
    known = {person["name"].strip().casefold() for person in listed}
    jobs: dict[str, tuple[str, list[str]]] = {}
    for member in tmdb.crew(credits):
        name = clean_value(str(member.get("name") or ""))
        job = clean_value(str(member.get("job") or ""))
        key = name.strip().casefold()
        if name and job and key not in known:
            held = jobs.setdefault(key, (name, []))[1]
            if job not in held:
                held.append(job)
    more: list[Person] = [{"name": name, "role": ", ".join(map(_job, held))}
                          for name, held in jobs.values()]
    _match(more, credits, ("crew",), "")
    return more


def _job(job: str) -> str:
    """A TMDb job as Kodi's language says it, or as TMDb wrote it."""
    string_id = _JOBS.get(job)
    return (settings.addon().getLocalizedString(string_id) or job) if string_id else job


def _crew(found: Details) -> list[Person]:
    return [
        {"name": name, "role": role}
        for names, role in ((found.get("directors", []), "director"),
                            (found.get("writers", []), "writer"))
        for name in names
    ]


def _match(people: list[Person], credits: Json, groups: tuple[str, ...], role: str) -> None:
    images: dict[str, str] = {}
    ids: dict[str, int] = {}
    for group in groups:
        images.update(tmdb.portraits(credits, group, role))
        ids.update(tmdb.people(credits, group, role))
    for person in people:
        name = person["name"].strip().casefold()
        path = images.get(name)
        if not person.get("thumbnail") and path:
            person["thumbnail"] = _portrait(path)
        if name in ids:
            person["tmdb"] = ids[name]


def _film_facts(found: Details, answer: Json) -> None:
    """Add the budget and the takings (US dollars) and the cinema release,
    with the country it is that of."""
    for field in ("budget", "revenue"):
        value = tmdb.money(answer, field)
        if value:
            found[field] = value
    date, country = tmdb.cinema(answer, home_country())
    if date:
        found["cinema"] = date
    if date and country:
        found["cinema_country"] = country


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


def _watching(found: Details, row: Json, kind: str) -> None:
    """Expose the current library state for the actions on the opened page."""
    if kind == "tvshow":
        total = common.number(row, "episode", 1) or 0
        seen = common.number(row, "watchedepisodes", 0) or 0
        found["watched"] = total > 0 and seen >= total
    else:
        found["watched"] = (common.number(row, "playcount", 0) or 0) > 0
    found["resume"] = common.resume_of(row.get("resume"))
