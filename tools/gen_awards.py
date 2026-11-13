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

Without a key, too, ``--wikidata`` writes it from Wikidata (wikidata.org,
CC0), which anyone may ask and which is kept up to date by hand: what a film
or a show won and was nominated for, and what somebody won or was nominated
for for their work on it, with the title's IMDb, TMDb and TheTVDB ids.  It
holds fewer nominations than TheTVDB does, and names a category its own way:

    python3 tools/gen_awards.py --wikidata

Development only: the add-on reads the file and asks nobody anything.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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


WIKIDATA = "https://query.wikidata.org/sparql"
WIKIDATA_SOURCE = "Wikidata (https://www.wikidata.org), by tools/gen_awards.py --wikidata"
# Wikidata's items for the awards shown; a category is an instance, a
# subclass or a part of one.  The BAFTAs are two there, film and television.
FAMILIES = {"Q19020": "oscar", "Q1011547": "globe", "Q732997": "bafta", "Q1369077": "bafta",
            "Q1044427": "emmy"}
# What a category's name there starts with, which the plot card's shield says.
_AWARD_PREFIX = re.compile(r"^(Academy|Golden Globe|BAFTA( TV)?|British Academy( Film| Television)?"
                           r"|Primetime Emmy) Award for ")
# Wikidata's classes of what the plot card knows as a film and as a show.
_KINDS = {"movie": "Q11424", "tv": "Q5398426"}

Json = dict
Ask = Callable[[str], list[dict[str, str]]]
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


def ask_wikidata(query: str) -> list[dict[str, str]]:
    """Return the rows of Wikidata's answer to a SPARQL *query*, each the
    value of its variables; an item is its id (``Q42``)."""
    request = urllib.request.Request(
        WIKIDATA, data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"Accept": "application/sparql-results+json",
                 "User-Agent": "gen_awards.py (Kodi add-on development script)"})
    rows = Tvdb._send(request).get("results", {}).get("bindings", [])
    prefix = "http://www.wikidata.org/entity/"
    return [{name: cell["value"].removeprefix(prefix) for name, cell in row.items()}
            for row in rows]


def _batches(items: Iterable[str], size: int) -> Iterable[list[str]]:
    held = sorted(set(items), key=lambda item: int(item[1:]))
    for start in range(0, len(held), size):
        yield held[start:start + size]


def _values(items: Iterable[str]) -> str:
    return " ".join("wd:" + item for item in items)


def wikidata_categories(ask: Ask) -> dict[str, tuple[str, str]]:
    """Return Wikidata's categories of the awards shown: by item, the award
    and the category's name without the award's."""
    rows = ask("SELECT ?cat ?fam ?name WHERE { VALUES ?fam { %s } "
               "?cat wdt:P31|wdt:P279|wdt:P361 ?fam . ?cat rdfs:label ?name . "
               'FILTER(LANG(?name) = "en") }' % _values(FAMILIES))
    found: dict[str, tuple[str, str]] = {}
    for row in rows:
        name = _AWARD_PREFIX.sub("", row["name"]).strip()
        # A ceremony ("79th British Academy Film Awards") is part of the
        # award as well, and no category.
        if name and not re.search(r"\b(19|20)\d\d\b|^\d+(st|nd|rd|th)\b", name):
            found.setdefault(row["cat"], (FAMILIES[row["fam"]], name))
    return found


def wikidata_statements(ask: Ask,
                        categories: Iterable[str]) -> Iterable[tuple[str, str, str, bool]]:
    """Yield what Wikidata holds of *categories*: the item it is said of or,
    of somebody's, the work it was for; the category; the year; and whether
    it was won rather than a nomination."""
    for batch in _batches(categories, 15):
        for prop, won in (("P166", True), ("P1411", False)):
            rows = ask("SELECT ?item ?work ?cat ?date WHERE { VALUES ?cat { %s } "
                       "?item p:%s ?said . ?said ps:%s ?cat . "
                       "OPTIONAL { ?said pq:P1686 ?work } OPTIONAL { ?said pq:P585 ?date } }"
                       % (_values(batch), prop, prop))
            for row in rows:
                item = row.get("work") or row["item"]
                year = row.get("date", "")[:4]
                # A year before the first of these awards is a slip there.
                year = year if year.isdigit() and int(year) >= 1927 else ""
                if re.fullmatch(r"Q\d+", item):
                    yield item, row["cat"], year, won


def wikidata_titles(ask: Ask, items: Iterable[str]) -> dict[str, tuple[str, dict[str, str]]]:
    """Return which of *items* are films and shows: by item, the kind and
    the ids it is known by ("tvdb", "imdb", "tmdb").  An episode is its
    show; anything else, somebody alone above all, is left out."""
    found: dict[str, tuple[str, dict[str, str]]] = {}
    shows: dict[str, str] = {}
    for batch in _batches(items, 200):
        rows = ask("SELECT ?item ?movie ?tv ?show ?imdb ?tmdbmovie ?tmdbtv ?tvdbmovie ?tvdbtv "
                   "WHERE { VALUES ?item { %s } "
                   "OPTIONAL { ?item wdt:P31/wdt:P279* wd:%s . BIND(1 AS ?movie) } "
                   "OPTIONAL { ?item wdt:P31/wdt:P279* wd:%s . BIND(1 AS ?tv) } "
                   "OPTIONAL { ?item wdt:P179 ?show } OPTIONAL { ?item wdt:P345 ?imdb } "
                   "OPTIONAL { ?item wdt:P4947 ?tmdbmovie } OPTIONAL { ?item wdt:P4983 ?tmdbtv } "
                   "OPTIONAL { ?item wdt:P12196 ?tvdbmovie } OPTIONAL { ?item wdt:P4835 ?tvdbtv } }"
                   % (_values(batch), _KINDS["movie"], _KINDS["tv"]))
        for row in rows:
            kind = "tv" if row.get("tv") or row.get("tmdbtv") else \
                "movie" if row.get("movie") or row.get("tmdbmovie") else ""
            if not kind:
                if re.fullmatch(r"Q\d+", row.get("show", "")):
                    shows.setdefault(row["item"], row["show"])
                continue
            ids = {"tvdb": row.get("tvdb" + kind, ""), "imdb": row.get("imdb", ""),
                   "tmdb": row.get("tmdb" + kind, "")}
            held = found.setdefault(row["item"], (kind, {}))[1]
            for name, ident in ids.items():
                if ident and name not in held:
                    held[name] = ident
    if shows:
        of_show = wikidata_titles(ask, set(shows.values()) - set(found))
        for episode, show in shows.items():
            if (show in found or show in of_show) and episode not in found:
                found[episode] = (found.get(show) or of_show[show])
    return found


def _held(wins: set[tuple[str, str]], nominated: set[tuple[str, str]]) -> list:
    """Return one award of a title as the file holds it: what it won, and
    how many more it was nominated for.  Wikidata says some of it twice,
    once with its year and once without, which counts once."""
    def dated(found: set[tuple[str, str]], others: set[tuple[str, str]]) -> set[tuple[str, str]]:
        named = {name for name, year in found | others if year}
        return {(name, year) for name, year in found if year or name not in named}
    wins = dated(wins, set())
    won = {name for name, year in wins if not year}
    more = {(name, year) for name, year in dated(nominated, wins) - wins if name not in won}
    labels = sorted((f"{name} ({year})" if year else name for name, year in wins),
                    key=lambda label: (label[-5:-1], label))
    return [labels, len(more)]


def from_wikidata(ask: Ask) -> dict:
    """Return the awards as Wikidata holds them, in this file's shape.  A
    title is held by its TheTVDB id where Wikidata knows it, else by its
    Wikidata item, and found by its IMDb and TMDb ids either way."""
    categories = wikidata_categories(ask)
    missing = set(FAMILIES.values()) - {award for award, _ in categories.values()}
    if missing:
        sys.exit("Wikidata has no category of: " + ", ".join(sorted(missing)))
    said = list(wikidata_statements(ask, categories))
    known = wikidata_titles(ask, {item for item, _, _, _ in said})
    # By kind, title and award: what it won and what it was up for, each a
    # category and a year once, however many of its makers it is said of.
    seen: dict[str, dict[str, dict[str, tuple[set, set]]]] = {"movie": {}, "tv": {}}
    index: dict[str, dict[str, dict[str, str]]] = {kind: {"imdb": {}, "tmdb": {}} for kind in seen}
    for item, category, year, won in said:
        if item not in known:
            continue
        kind, ids = known[item]
        key = ids.get("tvdb") or item
        award, name = categories[category]
        seen[kind].setdefault(key, {}).setdefault(award, (set(), set()))[not won].add((name, year))
        for source in ("imdb", "tmdb"):
            if ids.get(source):
                index[kind][source].setdefault(ids[source], key)
    out: dict = {"source": WIKIDATA_SOURCE}
    for kind, titles in seen.items():
        order = sorted(titles, key=lambda key: (not key.isdigit(), int(key.lstrip("Q"))))
        held = {key: {award: _held(*titles[key][award])
                      for award in AWARDS.values() if award in titles[key]} for key in order}
        out[kind] = {"titles": held,
                     **{source: {ident: key for ident, key in sorted(found.items())
                                 if key in held}
                        for source, found in index[kind].items()}}
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
    parser.add_argument("--wikidata", action="store_true",
                        help="write it from Wikidata, which asks for no key")
    args = parser.parse_args()
    if args.wikidata:
        data = from_wikidata(ask_wikidata)
    elif args.helper:
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
                     "or use --wikidata or --helper.")
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
