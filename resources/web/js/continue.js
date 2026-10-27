// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The "continue watching" rows on the films and series tabs, and the "next
   up" row on the series tab.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global openShowDetails, selectTab, bindTitle, el, episodeCode, FILMS_RETRY_MS, FILMS_START_MS, filmsStale,
   metaLine, ratingBadge, seriesStale, T */
/* exported continueStale, hideContinue, releaseContinue, requestContinue,
   resumeReleasing, resuming */

/* --- continue watching ------------------------------------------------- */

/* The films and episodes the box was stopped in the middle of, the last one
   seen first: the quickest way back into whatever was on.

   One list from the box, drawn as two rows: the films at the head of the
   films tab and the episodes at the head of the series tab, as the app draws
   them.  The box reads it with Kodi's own "in progress" filter and holds it
   with the shelves (see ``continuing`` in web/library.py), so it is read
   again on the same occasions they are: a title ending, and the library's
   number moving.  A row with nothing on it is no card at all. */

let continueTag = "";      /* the row's own tag, unchanged rows skipped    */
let continueBusy = false;  /* a request for the row is in flight           */
let continueRead = false;  /* the row has been read since it last moved    */
let continueShown = false; /* the row has been read at least once          */
let continueOffered = true; /* until the box says it offers no shelves     */
let continueNextTry = 0;   /* not before this, after a failure             */
let continueFilms = 0;     /* how many films the films row holds           */
let continueEpisodes = 0;  /* how many episodes the series row holds       */
let nextEpisodes = 0;      /* how many episodes the next-up row holds      */
let resuming = 0;          /* the tile a press is waiting on               */
let resumeReleasing = 0;   /* the timer that gives the row back            */

/* Called from the other parts of the page once the continue row may have moved: the
   next request reads it again. */
function continueStale() {
  continueRead = false;
}

function requestContinue(force) {
  if (continueBusy || !continueOffered) return;
  if (resuming) return;    /* as with the walls: not under a pressed tile */
  if (!force && continueRead) return;
  if (Date.now() < continueNextTry) return;
  continueBusy = true;
  loadContinue().finally(() => { continueBusy = false; });
}

async function loadContinue() {
  /* As with the walls: read as the request goes out, so that a move announced
     while it is out still stands afterwards. */
  continueRead = true;
  try {
    const answer = await TinyPPI.getJSON("/api/continue");
    /* Nor built under a tile pressed while the box was answering. */
    if (resuming) {
      continueRead = false;
      return;
    }
    continueShown = true;
    continueNextTry = 0;
    const list = Array.isArray(answer.items) ? answer.items : [];
    /* An add-on older than the next-up row sends none, and the row is no card. */
    const next = Array.isArray(answer.next) ? answer.next : [];
    if ((answer.tag || "") !== continueTag ||
        !(el.continueFilmsRow.children.length ||
          el.continueSeriesRow.children.length ||
          el.nextSeriesRow.children.length)) {
      continueTag = answer.tag || "";
      buildContinue(list, next);
    }
    el.continueFilmsCard.classList.toggle("hidden", continueFilms === 0);
    el.continueSeriesCard.classList.toggle("hidden", continueEpisodes === 0);
    el.nextSeriesCard.classList.toggle("hidden", nextEpisodes === 0);
  } catch (error) {
    continueRead = false;
    continueNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: neither shelf on offer.  404: an add-on older than the row. */
    const code = String((error || {}).message);
    if (code === "403" || code === "404") continueOffered = false;
    if (!continueShown) hideContinue();
  }
}

function buildContinue(list, next) {
  const films = document.createDocumentFragment();
  const episodes = document.createDocumentFragment();
  continueFilms = 0;
  continueEpisodes = 0;
  for (const item of list) {
    if (item.kind === "episode") {
      episodes.append(continueTile(item));
      continueEpisodes += 1;
    } else {
      films.append(continueTile(item));
      continueFilms += 1;
    }
  }
  el.continueFilmsRow.replaceChildren(films);
  el.continueSeriesRow.replaceChildren(episodes);
  /* Back to the newest title, which is the one the row was read again for. */
  el.continueFilmsRow.scrollLeft = 0;
  el.continueSeriesRow.scrollLeft = 0;
  el.continueFilmsCount.textContent = continueFilms ? String(continueFilms) : "";
  el.continueSeriesCount.textContent =
    continueEpisodes ? String(continueEpisodes) : "";

  /* What comes after: the next unseen episode of each show being watched,
     drawn like the row above it without the bar -- nothing of it has been
     seen yet -- and started from its beginning. */
  const upcoming = document.createDocumentFragment();
  for (const item of next) upcoming.append(continueTile(item));
  nextEpisodes = next.length;
  el.nextSeriesRow.replaceChildren(upcoming);
  el.nextSeriesRow.scrollLeft = 0;
  el.nextSeriesCount.textContent = nextEpisodes ? String(nextEpisodes) : "";
}

/* Both rows off the page, for a box with no shelves to offer. */
function hideContinue() {
  el.continueFilmsCard.classList.add("hidden");
  el.continueSeriesCard.classList.add("hidden");
  el.nextSeriesCard.classList.add("hidden");
}

/* Every tile on the rows: a press on one waits for its title on all. */
function continueTiles() {
  return [...el.continueFilmsRow.children, ...el.continueSeriesRow.children,
          ...el.nextSeriesRow.children];
}

function continueTile(item) {
  const episode = item.kind === "episode";
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "film";

  const frame = document.createElement("div");
  frame.className = "filmposter";
  if (item.poster) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = "";
    /* An episode stands on the row as its show's poster, which the box files
       under the episode's own id (see web/library/progress.py). */
    image.src =
      "/api/art?kind=poster&" + (episode ? "episodeid=" : "movieid=") +
      encodeURIComponent(item.id) + "&v=" + encodeURIComponent(item.poster);
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  /* The same badge the walls wear: a film's own rating, an episode its
     show's -- the poster it stands on is the show's. */
  const rated = ratingBadge(item);
  if (rated) frame.append(rated);
  if (item.resume && item.duration) {
    const bar = document.createElement("div");
    bar.className = "filmresume";
    bar.title = T.films_resume;
    const done = document.createElement("span");
    const at = Math.min(100, Math.max(2, (item.resume / item.duration) * 100));
    done.style.width = at.toFixed(1) + "%";
    bar.append(done);
    frame.append(bar);
  }

  const title = document.createElement("div");
  title.className = "filmtitle";
  /* An episode is called by its show, which is what somebody scanning the row
     is looking for; which episode it is goes on the line under it. */
  title.textContent = episode ? (item.show || item.title) : item.title;
  tile.append(frame, title);

  const meta = episode
    ? [episodeCode(item), item.show ? item.title : ""].filter(Boolean).join(" · ")
    : metaLine(item);
  if (meta) {
    const line = document.createElement("div");
    line.className = "filmyear";
    line.textContent = meta;
    /* Cut to one line on the row (see .continuerow in css/dashboard.css). */
    line.title = meta;
    tile.append(line);
  }

  /* A tile of the next-up row has no resume point to go back to. */
  const resumable = !!item.resume;
  bindTitle(tile, {
    title: episode ? [item.show, episodeCode(item)].filter(Boolean).join(" \u00b7 ")
                   : item.title,
    body: episode ? { episodeid: item.id } : { movieid: item.id },
    play: resumable ? T.films_resume : T.films_play,
    resumable,
    onPlay: (fromStart) => startContinue(item, tile, fromStart),
    /* An episode offers the way to its show as well, where the box says
       which show that is. */
    onShow: episode && item.tvshowid ? () => openShowDetails(item.tvshowid) : null
  });
  return tile;
}

async function startContinue(item, tile, fromStart) {
  if (resuming) return;
  resuming = item.id;
  tile.classList.add("busy");
  for (const node of continueTiles()) node.disabled = true;
  TinyPPI.toast(T.films_starting);

  const body = item.kind === "episode"
    ? { episodeid: item.id } : { movieid: item.id };
  if (fromStart) body.resume = false;
  let failed = false;
  try {
    const response = await fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify(body)
    });
    if (response.status === 401) {
      failed = true;
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      failed = true;
      TinyPPI.toast(T.films_failed, true);
    } else {
      /* What was last played has just changed, on the row and on the shelf
         the title came off. */
      continueRead = false;
      if (item.kind === "episode") seriesStale();
      else filmsStale();
      selectTab("live");
    }
  } catch (_) {
    failed = true;
    TinyPPI.toast(T.films_failed, true);
  }

  if (failed) {
    releaseContinue();
    return;
  }
  clearTimeout(resumeReleasing);
  resumeReleasing = setTimeout(releaseContinue, FILMS_START_MS);
}

function releaseContinue() {
  clearTimeout(resumeReleasing);
  resumeReleasing = 0;
  resuming = 0;
  for (const tile of continueTiles()) {
    tile.disabled = false;
    tile.classList.remove("busy");
  }
}
