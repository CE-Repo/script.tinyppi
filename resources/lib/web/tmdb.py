# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Optional title credits and facts from TMDb, used only by the details view.

Kodi's names, roles and portraits take precedence. Never search people by name:
match only members of the identified title's credits, and only unambiguous names,
for their portraits and their TMDb person ids (the clients link to their pages).
A film's budget, takings and cinema release come in the same request, and so
do a show's state and either title's recommendations; a film's series, in
Kodi's language, takes one more.
The API credential stays on Kodi; clients receive opaque artwork tags.
"""

import http.client
import json
import re
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from urllib.parse import urlencode

import xbmc
from core import settings
from web.library import common
from web.values import Json

_CACHE: OrderedDict[tuple[str, str], tuple[float, Json]] = OrderedDict()
_LOCK = Lock()
_LIMIT = 256
_BIGGEST = 2 * 1024 * 1024
# The time one details view gives TMDb in all, shared by its requests.
_BUDGET = 4.0
# A request that timed out with less than this left of the view's budget says
# nothing of TMDb, only of the requests before it, so its empty answer is not
# kept: the next view asks again.
_FAIR_TRY = 2.0
_PROFILE = re.compile(r"/[A-Za-z0-9_-]+\.(?:jpg|png)")
_LANGUAGE = re.compile(r"[a-z]{2}(?:-[A-Z]{2})?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_COUNTRY = re.compile(r"[A-Z]{2}")
# TMDb's release types that are a run in cinemas: limited and wide.
_THEATRICAL = (2, 3)
# A show's states as TMDb words them, and the codes the clients name them by.
_STATUSES = {"Returning Series": "returning", "Ended": "ended", "Canceled": "canceled",
             "Cancelled": "canceled", "In Production": "production", "Planned": "planned",
             "Pilot": "pilot"}
# The order the crew's departments stand in, the ones a reader looks for
# first; any other comes after these.
_DEPARTMENTS = ("Directing", "Writing", "Production", "Sound", "Camera", "Editing", "Art",
                "Costume & Make-Up", "Visual Effects", "Crew", "Lighting")


def api_key() -> str:
    """Read a personal v3 API key or API read access token, never a client's key."""
    try:
        return settings.addon().getSetting("web_tmdb_key").strip()
    except RuntimeError:
        return ""


def _read(path: str, key: str, deadline: float) -> Json:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    headers = {"Accept": "application/json", "User-Agent": "script.tinyppi (Kodi add-on)"}
    if re.fullmatch(r"[a-fA-F0-9]{32}", key):
        path += ("&" if "?" in path else "?") + urlencode({"api_key": key})
    else:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request("https://api.themoviedb.org/3/" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=remaining) as response:
        raw = response.read(_BIGGEST + 1)
    if len(raw) > _BIGGEST:
        raise ValueError("TMDb response too large")
    answer = json.loads(raw)
    return answer if isinstance(answer, dict) else {}


def _get(path: str, key: str, deadline: float) -> Json:
    wanted = (key, path)
    with _LOCK:
        held = _CACHE.get(wanted)
        if held is not None and held[0] > time.monotonic():
            _CACHE.move_to_end(wanted)
            return held[1]
    allowed = deadline - time.monotonic()
    try:
        answer = _read(path, key, deadline)
    except (OSError, ValueError, http.client.HTTPException) as error:
        if _timed_out(error) and allowed < _FAIR_TRY:
            return {}
        # Missing credentials, rate limits and outages must not hide Kodi's data.
        answer = {}
    with _LOCK:
        _CACHE[wanted] = (time.monotonic() + (86400 if answer else 300), answer)
        _CACHE.move_to_end(wanted)
        if len(_CACHE) > _LIMIT:
            _CACHE.popitem(last=False)
    return answer


def _timed_out(error: Exception) -> bool:
    """Return whether *error* is a timeout, also one urllib wraps while connecting."""
    return (isinstance(error, TimeoutError)
            or isinstance(getattr(error, "reason", None), TimeoutError))


def _title_id(row: Json, kind: str, key: str, deadline: float) -> int | None:
    ids = row.get("uniqueid")
    if not isinstance(ids, dict):
        return None
    ident = _ident(ids.get("tmdb"))
    if ident is not None:
        return ident
    imdb = str(ids.get("imdb") or "")
    if not re.fullmatch(r"tt[0-9]+", imdb):
        return None
    answer = _get(f"find/{imdb}?external_source=imdb_id", key, deadline)
    matches = answer.get("movie_results" if kind == "movie" else "tv_results")
    if isinstance(matches, list) and len(matches) == 1 and isinstance(matches[0], dict):
        return _ident(matches[0].get("id"))
    return None


def _ident(value: object) -> int | None:
    text = str(value)
    return int(text) if re.fullmatch(r"[0-9]{1,10}", text) and int(text) > 0 else None


def lookup(kind: str, row: Json, key: str) -> Json:
    """Read the title's credits under ``credits`` -- an episode's own, specials
    included -- and, for a film, its own facts beside them in the same request."""
    deadline = time.monotonic() + _BUDGET
    title = row
    if kind == "episode":
        show = common.number(row, "tvshowid", low=1)
        if show is None:
            return {}
        result = common.rpc("VideoLibrary.GetTVShowDetails", {
            "tvshowid": show, "properties": ["uniqueid"],
        }).get("result")
        title = result.get("tvshowdetails", {}) if isinstance(result, dict) else {}
        if not isinstance(title, dict):
            return {}
    ident = _title_id(title, kind, key, deadline)
    if ident is None:
        return {}
    if kind == "movie":
        answer = _get(f"movie/{ident}?append_to_response=credits,release_dates,"
                      "recommendations", key, deadline)
        return _with_collection(answer, key, deadline)
    if kind == "tvshow":
        return _get(f"tv/{ident}?append_to_response=credits,recommendations", key, deadline)
    season = common.number(row, "season", low=0)
    episode = common.number(row, "episode", low=0)
    if season is None or episode is None:
        return {}
    return {"credits": _get(f"tv/{ident}/season/{season}/episode/{episode}/credits",
                            key, deadline)}


def _with_collection(answer: Json, key: str, deadline: float) -> Json:
    """Return a film's *answer* with the series it belongs to under
    ``collection``, where it belongs to one TMDb has the films of.

    A copy: the answer itself is cached as it came.
    """
    held = answer.get("belongs_to_collection")
    ident = _ident(held.get("id")) if isinstance(held, dict) else None
    if ident is None:
        return answer
    path = f"collection/{ident}?" + urlencode({"language": _language()})
    series = _get(path, key, deadline)
    return {**answer, "collection": series} if series else answer


def _language() -> str:
    """Kodi's language as TMDb names one ("de-DE", "en"), English if unknown."""
    language, _, region = xbmc.getLanguage(xbmc.ISO_639_1, True).replace("_", "-") \
        .partition("-")
    tag = language.lower() + ("-" + region.upper() if region else "")
    return tag if _LANGUAGE.fullmatch(tag) else "en"


def collection(answer: Json) -> tuple[str, list[Json]]:
    """Return the name of the film series in *answer* (see ``lookup``) and its
    films in release order, those TMDb has no date for last.

    Each with its TMDb ``id`` and ``title`` and, where TMDb has them, its
    ``date`` (YYYY-MM-DD) and ``poster`` address; ``current`` marks the film
    *answer* is about.
    """
    held = answer.get("collection")
    if not isinstance(held, dict):
        return "", []
    own = _ident(answer.get("id"))
    parts: list[Json] = []
    for part in _members(held, "parts"):
        ident = _ident(part.get("id"))
        title = str(part.get("title") or "").strip()
        if ident is None or not title:
            continue
        entry: Json = {"id": ident, "title": title, "current": ident == own}
        date = _date(part.get("release_date"))
        if date:
            entry["date"] = date
        poster = _poster(part)
        if poster:
            entry["poster"] = poster
        parts.append(entry)
    parts.sort(key=lambda part: (not part.get("date"), part.get("date", "")))
    return str(held.get("name") or "").strip(), parts


def recommended(answer: Json) -> list[int]:
    """Return the TMDb ids TMDb recommends after the title in *answer*, best first."""
    held = answer.get("recommendations")
    found = [_ident(entry.get("id"))
             for entry in _members(held if isinstance(held, dict) else {}, "results")]
    return [ident for ident in found if ident is not None]


def show_state(answer: Json) -> Json:
    """Return what TMDb says of a show's run, each only where it says it:
    ``status`` (a code, see ``_STATUSES``), ``networks`` (names),
    ``seasons`` and ``episodes`` in all, and the ``next`` episode to air and
    the ``last`` aired (``season``, ``episode``, ``date``, ``title``)."""
    found: Json = {}
    status = _STATUSES.get(str(answer.get("status") or ""))
    if status:
        found["status"] = status
    networks = _names(answer, "networks")
    if networks:
        found["networks"] = networks
    for field, name in (("number_of_seasons", "seasons"), ("number_of_episodes", "episodes")):
        count = _ident(answer.get(field))
        if count is not None:
            found[name] = count
    for field, name in (("next_episode_to_air", "next"), ("last_episode_to_air", "last")):
        airing = _airing(answer.get(field))
        if airing:
            found[name] = airing
    return found


def _names(answer: Json, group: str) -> list[str]:
    """The names of the entries under *group*, those with none left out."""
    names = (str(entry.get("name") or "").strip() for entry in _members(answer, group))
    return [name for name in names if name]


def _airing(value: object) -> Json:
    """An episode TMDb dates, as ``show_state`` gives it, or {}."""
    if not isinstance(value, dict):
        return {}
    season = _count(value.get("season_number"))
    episode = _ident(value.get("episode_number"))
    if season is None or episode is None:
        return {}
    found: Json = {"season": season, "episode": episode}
    date = _date(value.get("air_date"))
    if date:
        found["date"] = date
    title = str(value.get("name") or "").strip()
    if title:
        found["title"] = title
    return found


def _count(value: object) -> int | None:
    """A whole number from 0 (a season of specials), or None."""
    text = str(value)
    return int(text) if re.fullmatch(r"[0-9]{1,4}", text) else None


def portraits(answer: Json, group: str, role: str = "") -> dict[str, str]:
    """Map normalized names to safe image URLs; reject ambiguous names."""
    return _unique(answer, group, role, _profile)


def people(answer: Json, group: str, role: str = "") -> dict[str, int]:
    """Map normalized names to TMDb person ids; reject ambiguous names."""
    return _unique(answer, group, role, lambda person: _ident(person.get("id")))


def crew(answer: Json) -> list[Json]:
    """Return the whole crew, department by department, TMDb's order within each."""
    def rank(person: Json) -> int:
        department = person.get("department")
        return _DEPARTMENTS.index(department) if department in _DEPARTMENTS \
            else len(_DEPARTMENTS)
    return sorted(_members(answer, "crew"), key=rank)


def money(answer: Json, field: str) -> int:
    """Return a film's ``budget`` or ``revenue`` in US dollars, or 0 for unknown."""
    value = answer.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def cinema(answer: Json, home: str) -> tuple[str, str]:
    """Return the day a film first ran in cinemas, as YYYY-MM-DD, and where ("DE").

    At *home* ("de") where TMDb has a cinema run there; else the earliest run
    anywhere; else its primary release date, with no country. ("", "") where
    it has none of them.
    """
    runs = _theatrical(answer)
    if home.upper() in runs:
        return runs[home.upper()], home.upper()
    if runs:
        return min((date, country) for country, date in runs.items())
    return _date(answer.get("release_date")), ""


def _theatrical(answer: Json) -> dict[str, str]:
    """The first day in cinemas in each country TMDb has one for, by country code."""
    countries = answer.get("release_dates")
    runs: dict[str, str] = {}
    for country in _members(countries if isinstance(countries, dict) else {}, "results"):
        code = str(country.get("iso_3166_1") or "").upper()
        dates = [_date(release.get("release_date"))
                 for release in _members(country, "release_dates")
                 if release.get("type") in _THEATRICAL]
        dates = [date for date in dates if date]
        if _COUNTRY.fullmatch(code) and dates:
            runs[code] = min(dates)
    return runs


def _date(value: object) -> str:
    text = str(value or "")[:10]
    return text if _DATE.fullmatch(text) else ""


def _poster(title: Json) -> str | None:
    poster = str(title.get("poster_path") or "")
    return "https://image.tmdb.org/t/p/w342" + poster if _PROFILE.fullmatch(poster) else None


def _profile(person: Json) -> str | None:
    profile = str(person.get("profile_path") or "")
    return "https://image.tmdb.org/t/p/w185" + profile if _PROFILE.fullmatch(profile) else None


def _unique[T](answer: Json, group: str, role: str,
               value: Callable[[Json], T | None]) -> dict[str, T]:
    found: dict[str, set[T]] = {}
    for person in _members(answer, group):
        if not _role(person, role):
            continue
        name = str(person.get("name") or "").strip().casefold()
        held = value(person)
        if name and held is not None:
            found.setdefault(name, set()).add(held)
    return {name: next(iter(values)) for name, values in found.items() if len(values) == 1}


def _members(answer: Json, group: str) -> list[Json]:
    people = answer.get(group)
    return [person for person in people if isinstance(person, dict)] \
        if isinstance(people, list) else []


def _role(person: Json, role: str) -> bool:
    if role == "director":
        return person.get("job") == "Director"
    if role == "writer":
        return person.get("department") == "Writing"
    return True
