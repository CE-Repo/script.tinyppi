// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The film library tab: the wall of posters, the search, the recent and
   unwatched rows, and starting a film.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global ask, continueStale, el, T */
/* exported FILMS_RETRY_MS, FILMS_START_MS, filmsOffered, filmsStale,
   hideFilms, metaLine, newest, ratingBadge, releaseFilms, releasing,
   requestFilms, runtime, starting */

/* --- the film library ---------------------------------------------------- */

/* What the box could be playing, whether or not anything already is.

   The add-on reads its video database once and holds the answer (see
   web/library.py), so asking again -- whenever a film ends, and once more on a
   page that arrives while one is playing -- costs a request and a validator
   rather than a query per phone in the house.  The wall is built once per list
   and then left alone: a library of a few thousand films is a few thousand
   nodes, and a keystroke in the search box is not a reason to make them again
   -- what does not match is hidden instead.

   The posters are fetched as they are scrolled to.  A wall of five hundred
   would otherwise ask the box for five hundred pictures the moment it was
   drawn, of which a phone shows six. */

/* What a badge calls the house whose rating it is drawing.  Brand names, so
   they are the same in every language the box speaks. */
const RATING_NAMES = { imdb: "IMDb", tmdb: "TMDb" };

const FILMS_RETRY_MS = 5000;
/* How long a pressed tile stays pressed with nothing having happened.  A film
   that starts gives the wall back as soon as the snapshot says it is on (see
   render); this is for the one that does not -- a missing file, a share that
   has gone away -- so the wall does not stay disabled for the evening. */
const FILMS_START_MS = 4000;

let films = [];            /* what the box last said its library holds    */
let filmsTag = "";         /* that list's own tag, unchanged lists skipped */
let filmsBusy = false;     /* a request is in flight                      */
let filmsRead = false;     /* the list has been read at least once        */
let filmsOffered = true;   /* until the box says it offers no library     */
let filmsNextTry = 0;      /* not before this, after a failure            */
let starting = 0;          /* the film a press is waiting on              */
let releasing = 0;         /* the timer that gives the wall back          */

/* Called from the other parts of the page once the films may have moved: the
   next request reads it again. */
function filmsStale() {
  filmsRead = false;
}

function requestFilms(force) {
  if (filmsBusy || !filmsOffered) return;
  /* Not while a tile is waiting on the film it was pressed on: the wall would
     be built again under it and the press would stop showing.  Nothing is
     lost by waiting -- the list is still marked unread, and the press is over
     within seconds either way (see releaseFilms). */
  if (starting) return;
  if (!force && filmsRead) return;
  if (Date.now() < filmsNextTry) return;
  filmsBusy = true;
  loadFilms().finally(() => { filmsBusy = false; });
}

async function loadFilms() {
  try {
    const answer = await TinyPPI.getJSON("/api/library");
    filmsRead = true;
    filmsNextTry = 0;
    const list = Array.isArray(answer.movies) ? answer.movies : [];
    /* The tag changes only when the library does, so a list that has not
       moved leaves the wall -- and anything the search box is holding -- as
       it is. */
    if (!el.filmGrid.children.length || (answer.tag || "") !== filmsTag) {
      filmsTag = answer.tag || "";
      films = list;
      buildFilms();
    }
    el.filmsCard.classList.remove("hidden");
    el.recentFilmsCard.classList.toggle("hidden",
                                        !el.recentFilmsRow.children.length);
    el.unseenFilmsCard.classList.toggle("hidden",
                                        !el.unseenFilmGrid.children.length);
  } catch (error) {
    filmsNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: there is no library on offer -- switched off in the add-on's
       settings, or a box that will not be told what to play.  Asking again
       every time a film ends would be asking to be told the same thing all
       evening. */
    if (String((error || {}).message) === "403") filmsOffered = false;
    if (!filmsRead) hideFilms();
  }
}

function buildFilms() {
  const wall = document.createDocumentFragment();
  const unseen = document.createDocumentFragment();
  let waiting = 0;
  for (const film of films) {
    wall.append(filmTile(film));
    /* A tile of its own on the second wall rather than the same one moved:
       a node stands in one place, and the film is on both. */
    if (!film.watched) {
      unseen.append(filmTile(film));
      waiting += 1;
    }
  }
  el.filmGrid.replaceChildren(wall);
  el.unseenFilmGrid.replaceChildren(unseen);
  /* A row that scrolls sideways, like the two above it, rather than a second
     wall: the wall of everything is the card under it.  Back to its start
     whenever it is built again. */
  el.unseenFilmGrid.scrollLeft = 0;
  const recent = document.createDocumentFragment();
  for (const film of newest(films)) recent.append(filmTile(film));
  el.recentFilmsRow.replaceChildren(recent);
  el.recentFilmsRow.scrollLeft = 0;
  el.unseenFilmsCount.textContent = waiting ? String(waiting) : "";
  applyFilmSearch();
}

/* Both film walls off the page, for a box with no library to offer. */
function hideFilms() {
  el.filmsCard.classList.add("hidden");
  el.recentFilmsCard.classList.add("hidden");
  el.unseenFilmsCard.classList.add("hidden");
}

/* Every film tile on the page, on either wall: a press on one waits for its
   film on both. */
function filmTiles() {
  return [...el.filmGrid.children, ...el.unseenFilmGrid.children,
          ...el.recentFilmsRow.children];
}

/* How many titles the row of what arrived last holds.  A phone shows three or
   four of them at once, so ten is two or three flicks along: enough for last
   week's films, and not so many that the row becomes a second wall. */
const RECENT_LIMIT = 10;

/* The films or the shows that arrived last, newest first, off the list the
   wall was built from.  Kodi writes the date as "2026-09-22 20:15:00", which
   sorts as text in the order it happened; a batch scanned in the same second
   falls back on the id, which Kodi hands out in the order it added them.  An
   add-on older than the date sends none, and the row is left empty. */
function newest(list) {
  return list
    .filter((entry) => entry.added)
    .sort((first, second) =>
      second.added.localeCompare(first.added) || second.id - first.id)
    .slice(0, RECENT_LIMIT);
}

/* How long something runs, as a tile writes it: 1 h 38 min for a film, 45 min
   for an episode.

   The hours split out rather than a hundred and ninety-eight minutes, because
   what is being asked of a film is how long an evening it is and an hour is
   the unit an evening is measured in.  Under the hour there is no hour to
   write, so the minutes stand on their own with their own unit -- a bare
   number beside a year would be a number nobody can name.

   Whole minutes either way: the seconds are noise at this size.  Empty for a
   library that does not know how long it is, so nothing is drawn at all. */
function runtime(seconds) {
  const minutes = Math.round((seconds || 0) / 60);
  if (minutes <= 0) return "";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours <= 0) return T.runtime_m.replace("%s", minutes);
  /* An hour with nothing left over says so and stops: "1 h 0 min" is a length
     nobody writes, and a season adding up to a round number of hours is not
     rare. */
  if (rest === 0) return T.runtime_h.replace("%s", hours);
  /* Two holes to fill and one at a time, so the second number cannot land in
     the hole the first one left. */
  return T.runtime_hm.replace("%s", hours).replace("%s", rest);
}

/* The rating in the corner of a poster, or nothing at all.

   The number alone is what it draws -- a poster has room for a number and not
   for a sentence -- and which house said so is what it answers to a finger
   held on it, because 8.3 means different things at the two of them. */
function ratingBadge(entry) {
  if (!entry.rating) return null;
  const badge = document.createElement("span");
  badge.className = "filmrating mono";
  badge.textContent = entry.rating.toFixed(1);
  const said = ((RATING_NAMES[entry.rating_from] || "") + " " +
                badge.textContent).trim();
  badge.setAttribute("role", "img");
  badge.setAttribute("aria-label", said);
  badge.title = said;
  return badge;
}

/* The line under a title: when it came out and how long it runs, whichever of
   the two the library knows. */
function metaLine(entry) {
  return [entry.year ? String(entry.year) : "", runtime(entry.duration)]
    .filter(Boolean).join(" \u00b7 ");
}

function filmTile(film) {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "film";
  /* What the search box matches against, lower-cased once here rather than
     once per tile per keystroke. */
  tile.dataset.key = (film.title + " " + (film.year || "")).toLowerCase();

  const frame = document.createElement("div");
  frame.className = "filmposter";
  if (film.poster) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    /* The tile already says the title in type under the picture, so the
       picture itself is decoration as far as a screen reader is concerned. */
    image.alt = "";
    image.src = TinyPPI.withToken(
      "/api/art?kind=poster&movieid=" + encodeURIComponent(film.id) +
      "&v=" + encodeURIComponent(film.poster));
    /* A poster the box cannot read leaves the frame it would have filled,
       which is the same empty frame a film with no poster at all gets. */
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  const rated = ratingBadge(film);
  if (rated) frame.append(rated);
  if (film.watched) {
    /* The tick a film the box counts as seen wears, in the corner of its
       poster.  An element of its own rather than a class on the frame: it is
       a thing on the picture, and the picture is a photograph that has to go
       on being read around it. */
    const seen = document.createElement("span");
    seen.className = "filmseen";
    seen.setAttribute("role", "img");
    seen.setAttribute("aria-label", T.films_watched);
    seen.title = T.films_watched;
    frame.append(seen);
  }
  if (film.resume && film.duration) {
    const bar = document.createElement("div");
    bar.className = "filmresume";
    bar.title = T.films_resume;
    const done = document.createElement("span");
    const at = Math.min(100, Math.max(2, (film.resume / film.duration) * 100));
    done.style.width = at.toFixed(1) + "%";
    bar.append(done);
    frame.append(bar);
  }

  const title = document.createElement("div");
  title.className = "filmtitle";
  title.textContent = film.title;
  tile.append(frame, title);
  const meta = metaLine(film);
  if (meta) {
    const line = document.createElement("div");
    line.className = "filmyear";
    line.textContent = meta;
    tile.append(line);
  }

  tile.addEventListener("click", () => ask({
    title: film.title, body: { movieid: film.id },
    play: film.resume ? T.films_resume : T.films_play,
    resumable: !!film.resume,
    onPlay: (fromStart) => startFilm(film, tile, fromStart)
  }));
  return tile;
}

function applyFilmSearch() {
  const needle = el.filmSearch.value.trim().toLowerCase();
  let shown = 0;
  for (const tile of el.filmGrid.children) {
    const match = !needle || tile.dataset.key.includes(needle);
    tile.hidden = !match;
    if (match) shown += 1;
  }
  el.filmSearchClear.classList.toggle("hidden", el.filmSearch.value === "");
  el.filmsCount.textContent = shown === films.length
    ? String(films.length) : shown + " / " + films.length;
  /* The line that says there is nothing: an empty library, or a search that
     nothing answers.  Both are the card having no film to offer. */
  el.filmsEmpty.classList.toggle("hidden", shown > 0);
}

async function startFilm(film, tile, fromStart) {
  if (starting) return;
  starting = film.id;
  tile.classList.add("busy");
  for (const node of filmTiles()) node.disabled = true;
  TinyPPI.toast(T.films_starting);

  let failed = false;
  try {
    const response = await fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify(fromStart ? { movieid: film.id, resume: false }
                                     : { movieid: film.id })
    });
    if (response.status === 401) {
      failed = true;
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      failed = true;
      TinyPPI.toast(T.films_failed, true);
    } else {
      /* Where the box got to in this film has just changed, and so has what
         it last played: the wall is read again rather than left standing on
         what it said before the press. */
      filmsRead = false;
      continueStale();
    }
  } catch (_) {
    failed = true;
    TinyPPI.toast(T.films_failed, true);
  }

  if (failed) {
    releaseFilms();
    return;
  }
  /* The snapshot gives the wall back as soon as the film is on (see render);
     this is only for the film that never starts. */
  clearTimeout(releasing);
  releasing = setTimeout(releaseFilms, FILMS_START_MS);
}

function releaseFilms() {
  clearTimeout(releasing);
  releasing = 0;
  starting = 0;
  for (const tile of filmTiles()) {
    tile.disabled = false;
    tile.classList.remove("busy");
  }
}

el.filmSearch.addEventListener("input", applyFilmSearch);
/* Emptying the box puts the whole shelf back, and leaves the cursor where
   somebody who meant to search again would want it. */
el.filmSearchClear.addEventListener("click", () => {
  el.filmSearch.value = "";
  applyFilmSearch();
  el.filmSearch.focus();
});
