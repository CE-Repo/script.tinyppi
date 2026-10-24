#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Write the awards the plot card shows to resources/data/awards.json.

The awards come from TheTVDB (thetvdb.com), which keeps every nominee of the
big awards by year and category, and whether it won.  This asks its API for
the four the plot card shows -- the Academy Awards, the Golden Globes, the
BAFTAs and the Primetime Emmys -- and every film and show nominated for one
of them, then each of those for the ids it is known by elsewhere (IMDb,
TMDb), so the add-on finds a title by whichever id the library holds rather
than by its name.  Of each title it keeps, by award, what it won (by
category and year) and how many more it was nominated for.

The file holds, for films (``movie``) and shows (``tv``), the titles by their
TheTVDB id, and indexes from their IMDb and TMDb ids to it:

    {"source": ..., "movie": {"titles": {"<tvdb>": {"oscar": [["Visual Effects (2015)"], 4]}},
                              "imdb": {"tt0816692": "<tvdb>"}, "tmdb": {"157336": "<tvdb>"}},
     "tv": {...}}

Run it from the repository root after an awards season, with a TheTVDB API
key (thetvdb.com/api-information) and, for a key that asks for one, a
subscriber PIN.  The answers are kept in a cache folder, so a run that
stopped half way asks again only for what it did not have yet; delete the
folder for a new season:

    TVDB_API_KEY=... [TVDB_PIN=...] python3 tools/gen_awards.py [--cache DIR]

Without a key, ``--helper`` writes the file from TheMovieDb Helper's awards
list instead (plugin.video.themoviedb.helper by jurialmunkey, GPL-3.0),
which its author builds from TheTVDB's the same way, about once a year, but
matches a film to TMDb by its name and year and keeps no IMDb id:

    python3 tools/gen_awards.py --helper [awards.json]

Development only: the add-on reads the file and asks TheTVDB nothing.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "resources", "data", "awards.json")
API = "https://api4.thetvdb.com/v4"
SOURCE = "TheTVDB (https://thetvdb.com), by tools/gen_awards.py"
HELPER = ("https://raw.githubusercontent.com/jurialmunkey/plugin.video.themoviedb.helper/"
          "nexus/resources/jsondata/awards.json")

# The awards shown, as TheTVDB names them and as the page knows them, in
# the order the plot card shows them.
AWARDS = {"academy awards": "oscar", "golden globe awards": "globe",
          "bafta awards": "bafta", "primetime emmy awards": "emmy"}

# TheTVDB's names for the other databases a title's remote ids are from.
REMOTE = {"imdb": "imdb", "themoviedb.com": "tmdb"}

Json = dict
Get = Callable[[str], object]


class Tvdb:
    """TheTVDB's API, signed in with a key, each answer cached on disk."""

    def __init__(self, key: str, pin: str, cache: str) -> None:
        self.cache = cache
        os.makedirs(cache, exist_ok=True)
        body = {"apikey": key, **({"pin": pin} if pin else {})}
        try:
            answer = self._send(urllib.request.Request(
                API + "/login", data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}))
        except urllib.error.HTTPError as error:
            sys.exit(f"TheTVDB refused the key ({error.code}): check TVDB_API_KEY and TVDB_PIN.")
        self.token = answer["data"]["token"]

    @staticmethod
    def _send(request: urllib.request.Request) -> Json:
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=60) as answer:
                    return json.load(answer)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return {}
                if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                    raise
            except urllib.error.URLError:
                if attempt == 4:
                    raise
            time.sleep(2 ** attempt)
        return {}

    def get(self, path: str) -> object:
        """Return the ``data`` of TheTVDB's answer to *path*, or None."""
        name = os.path.join(self.cache, hashlib.sha1(path.encode()).hexdigest() + ".json")
        if os.path.exists(name):
            with open(name, encoding="utf-8") as handle:
                return json.load(handle)
        request = urllib.request.Request(API + path,
                                         headers={"Authorization": "Bearer " + self.token})
        data = self._send(request).get("data")
        with open(name, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return data


def _records(found: object) -> list[Json]:
    if not isinstance(found, list):
        return []
    return [record for record in found if isinstance(record, dict)]


def categories(get: Get) -> Iterable[tuple[str, Json]]:
    """Yield every category of the awards shown, with the award it is of."""
    awards = {AWARDS[name]: award["id"] for award in _records(get("/awards"))
              if (name := str(award.get("name", "")).strip().lower()) in AWARDS}
    missing = set(AWARDS.values()) - set(awards)
    if missing:
        sys.exit("TheTVDB has none of these awards by the expected name: "
                 + ", ".join(sorted(missing)))
    for key, award_id in awards.items():
        extended = get(f"/awards/{award_id}/extended")
        held = extended.get("categories") if isinstance(extended, dict) else None
        for category in _records(held):
            yield key, category


def nominees(get: Get, workers: int = 8) -> Iterable[tuple[str, Json, Json]]:
    """Yield every nominee of the awards shown: the award, the category and
    the nominee."""
    listed = list(categories(get))
    with ThreadPoolExecutor(workers) as pool:
        extended = pool.map(
            lambda pair: get(f"/awards/categories/{pair[1]['id']}/extended"), listed)
        for (key, category), found in zip(listed, extended, strict=True):
            named = dict(category, **(found if isinstance(found, dict) else {}))
            for nominee in _records(named.get("nominees")):
                yield key, named, nominee


def collect(found: Iterable[tuple[str, Json, Json]]) -> dict[str, dict[str, dict[str, list]]]:
    """Return, by kind and TheTVDB id, what each title won and was
    nominated for: by award, [what it won, how many more it was nominated
    for].  A nominee that is a person alone, with no film or show, is left
    out; one for an episode counts for its show."""
    titles: dict[str, dict[str, dict[str, list]]] = {"movie": {}, "tv": {}}
    for key, category, nominee in found:
        found_title = _title_of(nominee)
        if not found_title:
            continue
        kind, tvdb = found_title
        held = titles[kind].setdefault(tvdb, {}).setdefault(key, [[], 0])
        if nominee.get("isWinner"):
            year = str(nominee.get("year") or "").strip()
            name = str(category.get("name") or "").strip()
            label = f"{name} ({year})" if year else name
            if label and label not in held[0]:
                held[0].append(label)
        else:
            held[1] += 1
    for kind in titles.values():
        for awards in kind.values():
            for held in awards.values():
                held[0].sort(key=lambda label: (label[-5:-1], label))
    return titles


def _title_of(nominee: Json) -> tuple[str, str] | None:
    """Return the kind and TheTVDB id of the film or show a nominee is for,
    an episode's show's for an episode, or None for a person alone."""
    for field, kind, ident in (("movie", "movie", "id"), ("series", "tv", "id"),
                               ("episode", "tv", "seriesId")):
        title = nominee.get(field)
        if isinstance(title, dict) and title.get(ident):
            return kind, str(title[ident])
    return None


def from_helper(source: Json) -> dict:
    """Return TheMovieDb Helper's awards list in this file's shape: its
    titles by their TheTVDB id, indexed by the TMDb id it found for them."""
    out: dict = {"source": HELPER}
    for kind in ("movie", "tv"):
        titles: dict[str, dict[str, list]] = {}
        index: dict[str, str] = {}
        for tmdb, title in (source.get(kind) or {}).items():
            tvdb = str(title.get("tvdb_id") or "")
            if not tvdb:
                continue
            won, nominated = title.get("awards_won") or {}, title.get("awards_nominated") or {}
            awards = {key: [list(won.get(name) or []), len(nominated.get(name) or [])]
                      for name in set(won) | set(nominated)
                      if (key := AWARDS.get(name.strip().lower()))}
            if awards:
                titles[tvdb] = {key: awards[key] for key in AWARDS.values() if key in awards}
                index.setdefault(tmdb, tvdb)
        order = sorted(titles, key=int)
        out[kind] = {"titles": {tvdb: titles[tvdb] for tvdb in order}, "imdb": {},
                     "tmdb": dict(sorted(index.items(), key=lambda item: int(item[0])))}
    return out


def remote_ids(get: Get, kind: str, tvdb: str) -> dict[str, str]:
    """Return the IMDb and TMDb ids TheTVDB holds for one title."""
    path = "/movies" if kind == "movie" else "/series"
    found = get(f"{path}/{tvdb}/extended?short=true")
    ids = {}
    for remote in _records(found.get("remoteIds") if isinstance(found, dict) else None):
        name = REMOTE.get(str(remote.get("sourceName", "")).strip().lower())
        ident = str(remote.get("id") or "").strip()
        if name and ident and name not in ids:
            ids[name] = ident
    return ids


def indexed(titles: dict, ids_of: Callable[[str, str], dict[str, str]], workers: int = 8) -> dict:
    """Return *titles* with the indexes from their IMDb and TMDb ids."""
    out: dict = {"source": SOURCE}
    for kind, held in titles.items():
        order = sorted(held, key=int)
        with ThreadPoolExecutor(workers) as pool:
            found = list(pool.map(lambda tvdb, kind=kind: ids_of(kind, tvdb), order))
        index: dict[str, dict[str, str]] = {"imdb": {}, "tmdb": {}}
        for tvdb, ids in zip(order, found, strict=True):
            for name, ident in ids.items():
                index[name].setdefault(ident, tvdb)
        out[kind] = {"titles": {tvdb: held[tvdb] for tvdb in order}, **index}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", default=os.path.join(ROOT, ".cache", "tvdb"),
                        help="where TheTVDB's answers are kept between runs")
    parser.add_argument("--helper", nargs="?", const=HELPER, metavar="FILE",
                        help="write it from TheMovieDb Helper's list "
                             "(a file, or its own on GitHub)")
    args = parser.parse_args()
    if args.helper:
        if os.path.exists(args.helper):
            with open(args.helper, encoding="utf-8") as handle:
                data = from_helper(json.load(handle))
        else:
            with urllib.request.urlopen(args.helper, timeout=60) as answer:
                data = from_helper(json.load(answer))
    else:
        key = os.environ.get("TVDB_API_KEY", "")
        if not key:
            sys.exit("Set TVDB_API_KEY (and TVDB_PIN, where the key asks for one), "
                     "or use --helper.")
        tvdb = Tvdb(key, os.environ.get("TVDB_PIN", ""), args.cache)
        data = indexed(collect(nominees(tvdb.get)),
                       lambda kind, ident: remote_ids(tvdb.get, kind, ident))
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    films, shows = len(data["movie"]["titles"]), len(data["tv"]["titles"])
    print(f"{films} films and {shows} shows written to {OUT}")


if __name__ == "__main__":
    main()
