// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The sorting and the filters over the film and the series walls.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global T */
/* exported FORMAT_NAMES, shelfTools */

/* --- sorting and filtering a wall ----------------------------------------- */

/* What the formats the box reads off a file are called (see ``formats`` in
   web/library/common.py), in the order a filter offers them: the grades from
   the most to the least, the resolutions from the largest, the sound from
   the lossless down.  Trade names, so the same in every language. */
const FORMAT_NAMES = {
  video: { dv: "Dolby Vision", hdr10plus: "HDR10+", hdr10: "HDR10", hlg: "HLG",
           sdr: "SDR" },
  resolution: { "2160p": "4K", "1080p": "1080p", "720p": "720p", sd: "SD" },
  audio: { truehd: "Dolby TrueHD", dtshd_ma: "DTS-HD MA", pcm: "PCM", flac: "FLAC",
           dtshd_hra: "DTS-HD HRA", eac3: "Dolby Digital Plus", dts: "DTS",
           ac3: "Dolby Digital", aac: "AAC", opus: "Opus", vorbis: "Vorbis",
           mp3: "MP3" }
};

/* How each order compares two titles; a title without the value goes last
   whichever way the order runs.  The title order is the box's own (Kodi's
   sort title, articles ignored), so it is the list as it came. */
const SORTS = {
  year: (entry) => entry.year,
  rating: (entry) => entry.rating,
  added: (entry) => entry.added,
  runtime: (entry) => entry.duration
};
/* The ones read from the shortest or the oldest first; the others from the
   newest, the best and the most recently added. */
const RISING = new Set(["runtime"]);

/* The sort and the filters for one wall, drawn into *box*: *sorts* names the
   orders it offers ("title" first), *filters* what it filters by ("genre",
   "video", "resolution", "audio"), and *onChange* is called with nothing
   whenever a choice changes.  The choices stand until the page is left; a
   filter the list no longer offers anything for is put back to "all". */
function shelfTools(box, { sorts, filters, onChange }) {
  const pickers = {};

  const picker = (name, label) => {
    const select = document.createElement("select");
    select.className = "shelfpick";
    select.dataset.name = name;
    select.dataset.label = label;
    select.addEventListener("change", onChange);
    box.append(select);
    pickers[name] = select;
    return select;
  };

  const sort = picker("sort", "sort");
  for (const key of sorts) sort.append(new Option("", key));
  for (const name of filters) {
    picker(name, name === "genre" ? "genre" : "filter_" + name).append(new Option("", ""));
  }

  /* What *entry* is filed under for *name*: every genre, or its one format. */
  const values = (entry, name) =>
    name === "genre" ? (entry.genres || []) : (entry[name] ? [entry[name]] : []);

  /* The words, put on again whenever the strings change. */
  function strings() {
    for (const select of Object.values(pickers)) {
      select.setAttribute("aria-label", T[select.dataset.label]);
      select.title = T[select.dataset.label];
    }
    for (const option of sort.options) option.text = T["sort_" + option.value];
    for (const name of filters) pickers[name].options[0].text = T["filter_" + name];
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
      select.replaceChildren(new Option("", ""));
      for (const value of offered) select.append(new Option(named ? named[value] : value, value));
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

  /* *list* in the chosen order; the title order is *list* as it stands. */
  function order(list) {
    const value = SORTS[sort.value];
    if (!value) return list;
    const rising = RISING.has(sort.value);
    return [...list].sort((first, second) => {
      const one = value(first);
      const two = value(second);
      if (!one || !two) return (one ? 0 : 1) - (two ? 0 : 1);
      const ahead = typeof one === "string" ? one.localeCompare(two) : one - two;
      return rising ? ahead : -ahead;
    });
  }

  /* Whether any filter is set, for the line that says nothing is left. */
  function filtering() {
    return filters.some((name) => !!pickers[name].value);
  }

  return { fill, matches, order, filtering, strings };
}
