#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Write the awards the plot card shows to resources/data/awards.json.

The awards come from TheMovieDb Helper's ``resources/jsondata/awards.json``
(plugin.video.themoviedb.helper by jurialmunkey, GPL-3.0-or-later): every
film and show TMDb knows that was nominated for one of the big awards, by
its TMDb id, with what it won and what it was nominated for.  This keeps
only the four the plot card shows -- the Academy Awards, the Golden Globes,
the BAFTAs and the Primetime Emmys -- and of each what it won, by category,
and how many more it was nominated for.  A title nominated for none of them
is left out.

Run it again after an awards season, from the repository root (it downloads
the file, or reads one given):

    python3 tools/gen_awards.py [awards.json]
"""

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "resources", "data", "awards.json")
SOURCE = ("https://raw.githubusercontent.com/jurialmunkey/plugin.video.themoviedb.helper/"
          "nexus/resources/jsondata/awards.json")

# The awards shown, as the source names them and as the page knows them, in
# the order the plot card shows them.
AWARDS = {"Academy Awards": "oscar", "Golden Globe Awards": "globe",
          "BAFTA Awards": "bafta", "Primetime Emmy Awards": "emmy"}


def kept(title: dict) -> dict:
    """Return the awards of one of the source's titles that are shown: by
    award, what it won and how many more it was nominated for."""
    won, nominated = title.get("awards_won") or {}, title.get("awards_nominated") or {}
    found = {}
    for name, key in AWARDS.items():
        wins, more = list(won.get(name) or []), len(nominated.get(name) or [])
        if wins or more:
            found[key] = [wins, more]
    return found


def trimmed(source: dict) -> dict:
    """Return the shown awards of every title in *source*, by kind and TMDb id."""
    out: dict = {"source": SOURCE}
    for kind in ("movie", "tv"):
        titles = {}
        for tmdb, title in sorted((source.get(kind) or {}).items(), key=lambda item: int(item[0])):
            found = kept(title)
            if found:
                titles[tmdb] = found
        out[kind] = titles
    return out


def main() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as handle:
            source = json.load(handle)
    else:
        with urllib.request.urlopen(SOURCE, timeout=60) as answer:
            source = json.load(answer)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(trimmed(source), handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


if __name__ == "__main__":
    main()
