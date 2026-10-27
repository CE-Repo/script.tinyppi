// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The sorting and the filters over the film and the series walls.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global T */
/* exported FORMAT_NAMES, formatName, shelfTools */

/* --- sorting and filtering a wall ----------------------------------------- */

/* What the formats the box reads off a file are called (see ``formats`` in
   web/library/common.py), in the order a filter offers them: the grades from
   the most to the least, the resolutions from the largest, the sound from
   the lossless down.  Trade names, so the same in every language. */
const FORMAT_NAMES = {
  video: { dv: "Dolby Vision", hdr10plus: "HDR10+", hdr10: "HDR10", hlg: "HLG",
           sdr: "SDR" },
  resolution: { "2160p": "4K", "1080p": "1080p", "720p": "720p", sd: "SD" },
  audio: { atmos: "Dolby Atmos", dtsx: "DTS:X", truehd: "Dolby TrueHD", dtshd_ma: "DTS-HD MA", pcm: "PCM", flac: "FLAC",
           dtshd_hra: "DTS-HD HRA", eac3: "Dolby Digital Plus", dts: "DTS",
           ac3: "Dolby Digital", aac: "AAC", opus: "Opus", vorbis: "Vorbis",
           mp3: "MP3" }
};

/* What a picture filter's value is called: a grade, or one Dolby Vision
   profile under it ("dv/8.1"), written the way the playing card writes a
   profile. */
function formatName(name, value) {
  if (name === "video" && value.startsWith("dv/")) return "Dolby Vision P" + value.slice(3);
  return FORMAT_NAMES[name][value] || value;
}

/* The profiles a Dolby Vision filter offers, in order: 5, 7, 7 FEL, 7 MEL,
   8.1, 8.4 -- by number, then by what follows it. */
const byProfile = (first, second) =>
  parseFloat(first.slice(3)) - parseFloat(second.slice(3)) || first.localeCompare(second);

/* How each order compares two titles; a title without the value goes last
   whichever way the order runs.  The title order is the box's own (Kodi's
   sort title, articles ignored), so it is the list as it came, A to Z. */
const SORTS = {
  year: (entry) => entry.year,
  rating: (entry) => entry.rating,
  added: (entry) => entry.added,
  runtime: (entry) => entry.duration
};
/* The orders that start from the newest, the best and the most recently
   added when they are picked; the titles and the running time start from
   the first and the shortest.  Either can be turned round. */
const FALLING = new Set(["year", "rating", "added"]);
/* Where each wall's order is kept between visits, as "year" or "year:down". */
const ORDER_KEY = "tinyppi.order.";

/* The sort and the filters for one wall, drawn into *box*: *shelf* is what
   its order is kept under, *sorts* names the orders it offers ("title"
   first), *filters* what it filters by ("genre", "video", "resolution",
   "audio"), and *onChange* is called with nothing whenever a choice changes.
   The order and its way round are kept in the browser; the filters stand
   until the page is left, and one the list no longer offers anything for is
   put back to "all". */
function shelfTools(box, { shelf, sorts, filters, onChange }) {
  const pickers = {};
  let descending = false;

  const picker = (key, label, first = () => {}) => {
    const select = document.createElement("select");
    select.className = "shelfpick";
    select.dataset.name = key;
    select.dataset.label = label;
    select.addEventListener("change", () => {
      first();
      onChange();
    });
    box.append(select);
    pickers[key] = select;
    return select;
  };

  /* A new order starts its own way round, and both are kept. */
  const sort = picker("sort", "sort", () => {
    descending = FALLING.has(sort.value);
    keep();
    strings();
  });
  for (const key of sorts) sort.append(new Option("", key));
  /* Beside it, which way it runs: an arrow and its name, a press turning it. */
  const way = document.createElement("button");
  way.type = "button";
  way.className = "shelfway";
  way.addEventListener("click", () => {
    descending = !descending;
    keep();
    strings();
    onChange();
  });
  box.append(way);
  try {
    const [kept, down] = (localStorage.getItem(ORDER_KEY + shelf) || "").split(":");
    if (sorts.includes(kept)) {
      sort.value = kept;
      descending = down === "down";
    }
  } catch (_) { /* no storage: the box's own order */ }

  function keep() {
    try { localStorage.setItem(ORDER_KEY + shelf, sort.value + (descending ? ":down" : "")); }
    catch (_) { /* no storage: kept until the page is left */ }
  }

  for (const name of filters) {
    picker(name, name === "genre" ? "genre" : "filter_" + name).append(new Option("", ""));
  }

  /* What *entry* is filed under for *name*: every genre, or its one format --
     and a Dolby Vision title under its profile as well ("dv/8.1"), so the
     grade and the profile are both choices the same title answers. */
  const values = (entry, name) => {
    if (name === "genre") return entry.genres || [];
    if (!entry[name]) return [];
    return name === "video" && entry.dv_profile
      ? [entry.video, "dv/" + entry.dv_profile] : [entry[name]];
  };

  /* The words, put on again whenever the strings change. */
  function strings() {
    for (const select of Object.values(pickers)) {
      select.setAttribute("aria-label", T[select.dataset.label]);
      select.title = T[select.dataset.label];
    }
    for (const option of sort.options) option.text = T["sort_" + option.value];
    for (const name of filters) pickers[name].options[0].text = T["filter_" + name];
    const said = T[descending ? "sort_descending" : "sort_ascending"];
    way.textContent = (descending ? "\u2193 " : "\u2191 ") + said;
    way.setAttribute("aria-label", said);
    way.classList.toggle("down", descending);
  }

  /* The choices each filter offers, taken from *list*: the genres in
     alphabetical order, the formats in the order above.  A filter with fewer
     than two to choose between has nothing to narrow and is not drawn, which
     is also what an add-on too old to send them gets. */
  function fill(list) {
    for (const name of filters) {
      const select = pickers[name];
      const held = select.value;
      const found = new Set();
      for (const entry of list) for (const value of values(entry, name)) found.add(value);
      const named = FORMAT_NAMES[name];
      const offered = named
        ? Object.keys(named).filter((value) => found.has(value))
        : [...found].sort((first, second) => first.localeCompare(second));
      /* Under Dolby Vision, its profiles -- where there is more than one, as
         one profile alone is the grade under another name. */
      const profiles = [...found].filter((value) => value.startsWith("dv/")).sort(byProfile);
      if (profiles.length > 1) offered.splice(offered.indexOf("dv") + 1, 0, ...profiles);
      select.replaceChildren(new Option("", ""));
      for (const value of offered) {
        select.append(new Option(named ? formatName(name, value) : value, value));
      }
      select.value = offered.includes(held) ? held : "";
      select.hidden = offered.length < 2;
    }
    strings();
  }

  /* Whether *entry* passes every filter that is set. */
  function matches(entry) {
    return filters.every((name) =>
      !pickers[name].value || values(entry, name).includes(pickers[name].value));
  }

  /* *list* in the chosen order and way round; the title order is *list* as
     it stands, or turned round. */
  function order(list) {
    const value = SORTS[sort.value];
    if (!value) return descending ? [...list].reverse() : list;
    return [...list].sort((first, second) => {
      const one = value(first);
      const two = value(second);
      if (!one || !two) return (one ? 0 : 1) - (two ? 0 : 1);
      const ahead = typeof one === "string" ? one.localeCompare(two) : one - two;
      return descending ? -ahead : ahead;
    });
  }

  /* Whether any filter is set, for the line that says nothing is left. */
  function filtering() {
    return filters.some((name) => !!pickers[name].value);
  }

  return { fill, matches, order, filtering, strings };
}
