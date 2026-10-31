# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Optional title credits and film facts from TMDb, used only by the details view.

Kodi's names, roles and portraits take precedence. Never search people by name:
match only members of the identified title's credits, and only unambiguous names,
for their portraits and their TMDb person ids (the clients link to their pages).
A film's budget, takings and cinema release come in the same request.
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
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_COUNTRY = re.compile(r"[A-Z]{2}")
# TMDb's release types that are a run in cinemas: limited and wide.
_THEATRICAL = (2, 3)
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
        return _get(f"movie/{ident}?append_to_response=credits,release_dates", key, deadline)
    path = f"tv/{ident}"
    if kind == "episode":
        season = common.number(row, "season", low=0)
        episode = common.number(row, "episode", low=0)
        if season is None or episode is None:
            return {}
        path += f"/season/{season}/episode/{episode}"
    return {"credits": _get(path + "/credits", key, deadline)}


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
