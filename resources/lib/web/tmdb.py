# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Optional title-credit portraits from TMDb, used only by the details view.

Kodi's names, roles and portraits take precedence. Never search people by name:
match only members of the identified title's credits, and only unambiguous names.
The API credential stays on Kodi; clients receive opaque artwork tags.
"""

import http.client
import json
import re
import time
import urllib.request
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlencode

from core import settings
from web.library import common
from web.values import Json

_CACHE: OrderedDict[tuple[str, str], tuple[float, Json]] = OrderedDict()
_LOCK = Lock()
_LIMIT = 256
_BIGGEST = 2 * 1024 * 1024
_PROFILE = re.compile(r"/[A-Za-z0-9_-]+\.(?:jpg|png)")


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
    try:
        answer = _read(path, key, deadline)
    except (OSError, ValueError, http.client.HTTPException):
        # Missing credentials, rate limits and outages must not hide Kodi's data.
        answer = {}
    with _LOCK:
        _CACHE[wanted] = (time.monotonic() + (86400 if answer else 300), answer)
        _CACHE.move_to_end(wanted)
        if len(_CACHE) > _LIMIT:
            _CACHE.popitem(last=False)
    return answer


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


def credits(kind: str, row: Json, key: str) -> Json:
    """Read movie/show credits, or the exact episode's credits (including specials)."""
    deadline = time.monotonic() + 4.0
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
    path = f"movie/{ident}" if kind == "movie" else f"tv/{ident}"
    if kind == "episode":
        season = common.number(row, "season", low=0)
        episode = common.number(row, "episode", low=0)
        if season is None or episode is None:
            return {}
        path += f"/season/{season}/episode/{episode}"
    return _get(path + "/credits", key, deadline)


def portraits(answer: Json, group: str, role: str = "") -> dict[str, str]:
    """Map normalized names to safe image URLs; reject ambiguous names."""
    found: dict[str, set[str]] = {}
    for person in _members(answer, group):
        if not _role(person, role):
            continue
        name = str(person.get("name") or "").strip().casefold()
        profile = str(person.get("profile_path") or "")
        if name and _PROFILE.fullmatch(profile):
            found.setdefault(name, set()).add("https://image.tmdb.org/t/p/w185" + profile)
    return {name: next(iter(paths)) for name, paths in found.items() if len(paths) == 1}


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
