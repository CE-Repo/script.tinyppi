// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   TinyPPI second-screen dashboard.

   Everything printed here comes from the snapshot TinyPPI.boot delivers; the
   labels come translated with it, out of Kodi's own string table.  The
   connection itself lives in core.js, which this page shares with the
   metadata window.
=========================================================================== */

const $ = TinyPPI.$;
const T = TinyPPI.T;

const el = {
  version: $("version"), idleCard: $("idleCard"),
  vs10Card: $("vs10Card"), vs10Out: $("vs10Out"), modes: $("modes"),
  groups: $("groups"),
  metricsCard: $("tiles"), metricsGrid: $("tiles").querySelector(".tilegrid"),
  eventsCard: $("eventsCard"), metaLink: $("metaLink"), sideRail: $("sideRail"),
  copyBtn: $("copyBtn"), idleStack: $("idleStack"),
  lastCard: $("lastCard"), lastTitle: $("lastTitle"), lastTiles: $("lastTiles"),
  filmsCard: $("filmsCard"), filmGrid: $("filmGrid"),
  filmsCount: $("filmsCount"), filmsEmpty: $("filmsEmpty"),
  filmSearch: $("filmSearch"), filmSearchClear: $("filmSearchClear"),
  seriesCard: $("seriesCard"), seriesGrid: $("seriesGrid"),
  seriesCount: $("seriesCount"), seriesEmpty: $("seriesEmpty"),
  seriesSearch: $("seriesSearch"), seriesSearchClear: $("seriesSearchClear"),
  seriesBox: $("seriesSearchBox"), seriesBack: $("seriesBack"),
  seriesOpen: $("seriesOpen"), episodeList: $("episodeList")
};

/* Keep VS10 by the playback card.  The figures are the first thing inside the
   events card, followed by the event list; its old disclosure shell is no
   longer needed. */
$("nowCard").after(el.vs10Card);
el.eventsCard.querySelector(".eventswrap").before(el.metricsGrid);
/* Keep the empty shell in the document because the shared localization code
   still owns its heading node; the hidden attribute cannot be undone by the
   live module's class toggles. */
el.metricsCard.hidden = true;
el.sideRail.append(el.eventsCard);

let state = null;
let control = false;
let rowNodes = new Map();  /* row id -> {element, key, value, last}     */
let groupNodes = new Map();
let pending = null;        /* the VS10 mode a button is waiting on      */
let wasPlaying = null;     /* what the last snapshot said, for the library */

/* Only the two per-frame L1 summaries use the transient change colour. */
const FLASH_ROWS = new Set(["metadata.32375", "metadata.32376"]);
const DEFAULT_OPEN_GROUPS = new Set([
  "video", "audio", "processing", "dv", "system", "metadata"
]);

TinyPPI.bindDisclosure(el.vs10Card, "dashboard.vs10", false);
/* Open to begin with: the card is the idle page's reason to be there, and one
   that arrived folded would be a heading on an empty screen.  Folded is
   remembered per device all the same, the way every other card here is. */
TinyPPI.bindDisclosure(el.filmsCard, "dashboard.films", true);
TinyPPI.bindDisclosure(el.seriesCard, "dashboard.series", true);

/* --- render ------------------------------------------------------------- */

function render(next) {
  state = next;
  control = !!next.control;

  /* The common live module draws what is playing and the summary tiles.  Its
     L1 chart is reserved for the metadata window. */
  TinyPPI.panels.update(next);
  /* The former metrics card disappeared while idle; preserve that behaviour
     now that its grid lives inside the event card, which may hold the events
     of the title that just ended. */
  el.metricsGrid.classList.toggle("hidden", !next.playing);

  if (!next.playing) {
    /* The line saying nothing is playing is for a box that has played nothing:
       with the title that just ended on the page under it, it says what the
       page already shows and takes a card to say it. */
    el.idleCard.classList.toggle("hidden", !!(next.last && next.last.title));
    for (const id of ["vs10Card", "metaLink"]) {
      $(id).classList.add("hidden");
    }
    el.groups.innerHTML = "";
    rowNodes.clear();
    groupNodes.clear();
    renderLast(next.last);
    /* The events of the title that just ended join the two cards above them,
       so the idle page is one centred column rather than a card floating in
       the middle of the viewport with its own events stranded at the top.
       Above the film library rather than below it: that card is a shelf
       somebody scrolls, and a card under a shelf is a card nobody reaches. */
    if (el.eventsCard.parentElement !== el.idleStack) {
      el.filmsCard.before(el.eventsCard);
    }
    /* And what could be playing instead.  Asked for when the page arrives on
       an idle box and again the moment a film ends -- which is exactly when
       somebody is looking for the next one. */
    if (control) requestFilms(wasPlaying !== false);
    else el.filmsCard.classList.add("hidden");
    if (control) requestSeries(wasPlaying !== false);
    else el.seriesCard.classList.add("hidden");
    wasPlaying = false;
    /* The button goes with the report: there is one for as long as the title
       that just ended is still held, and none at all once it is let go -- a
       button that answers a press with nothing is worse than one that is not
       there. */
    el.copyBtn.classList.toggle("hidden", !next.last || !next.last.title);
    return;
  }

  el.idleCard.classList.add("hidden");
  el.lastCard.classList.add("hidden");
  el.filmsCard.classList.add("hidden");
  el.seriesCard.classList.add("hidden");
  el.copyBtn.classList.remove("hidden");
  wasPlaying = true;
  /* A film that was pressed is on: whatever tile was waiting on it is done
     waiting, and the next visit to the idle page starts from a clean wall. */
  if (starting || releasing) releaseFilms();
  if (startingEpisode || episodeReleasing) releaseSeries();
  /* Back to the foot of the page, where it belongs while something plays. */
  if (el.eventsCard.parentElement === el.idleStack) {
    el.sideRail.append(el.eventsCard);
  }

  renderVs10(next.vs10 || {});
  renderGroups(ordered(next.groups || []));
  /* The metadata list is a window of its own; this page only says whether
     there is one to open. */
  el.metaLink.classList.toggle("hidden", !(next.metadata && next.metadata.length));
}

/* --- the title that just ended ------------------------------------------ */

/* The add-on holds a finished session for ten minutes (see SessionLog.end in
   web/snapshot.py), which is the window in which someone walks over to the
   phone and asks what that film actually did.  What it did is three figures
   and the events beneath them; the event list is the same card that was there
   while it played, and stays where it was. */
function renderLast(last) {
  if (!last || !last.title) {
    el.lastCard.classList.add("hidden");
    return;
  }
  el.lastCard.classList.remove("hidden");
  el.lastTitle.textContent = last.title;

  /* The two figures only the add-on could have counted: it saw every frame of
     the title and the browser saw whichever ones it was connected for.  The
     peak the grade reached is in the report rather than here -- it is a
     reading about the film, and these are about the playing of it. */
  const tiles = [
    [T.switches, String(last.switches || 0)],
    [T.warnings, String(last.warnings || 0)]
  ];

  el.lastTiles.replaceChildren();
  for (const [label, value] of tiles) {
    const tile = document.createElement("div");
    tile.className = "tile";
    const key = document.createElement("span");
    key.className = "k";
    key.textContent = label;
    const wrap = document.createElement("span");
    wrap.className = "vwrap";
    const reading = document.createElement("span");
    reading.className = "v mono";
    reading.textContent = value;
    wrap.append(reading);
    tile.append(key, wrap);
    el.lastTiles.append(tile);
  }
}

/* --- VS10 --------------------------------------------------------------- */

function renderVs10(vs10) {
  const options = vs10.options || [];
  if (!control || !options.length) {
    el.vs10Card.classList.add("hidden");
    return;
  }
  el.vs10Card.classList.remove("hidden");
  el.vs10Out.textContent = vs10.output || "—";

  const signature = options.map((option) => option.mode).join("|");
  if (el.modes.dataset.signature !== signature) {
    el.modes.dataset.signature = signature;
    el.modes.innerHTML = "";
    for (const option of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mode";
      button.dataset.mode = option.mode;
      button.textContent = option.label;
      button.addEventListener("click", () => switchMode(option.mode, button));
      el.modes.appendChild(button);
    }
  }
}

async function switchMode(mode, button) {
  if (pending) return;
  pending = mode;
  for (const node of el.modes.children) node.disabled = true;
  button.classList.add("busy");
  TinyPPI.toast(T.switching);
  try {
    const response = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify({ mode })
    });
    if (response.status === 401) {
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      TinyPPI.toast(T.switch_failed, true);
    } else {
      TinyPPI.toast(T.switched);
    }
  } catch (_) {
    TinyPPI.toast(T.switch_failed, true);
  } finally {
    /* The driver needs a moment to settle before the next snapshot shows the
       new output; keep the buttons locked until then rather than inviting a
       second press into the middle of the switch. */
    setTimeout(() => {
      pending = null;
      button.classList.remove("busy");
      for (const node of el.modes.children) node.disabled = false;
    }, 1200);
  }
}

/* --- detail groups ------------------------------------------------------ */

/* The order the cards are laid out in, by the group ids the snapshot carries.
   The snapshot names them in an order of its own (web/snapshot.py _GROUPS),
   but that one lives in the service, which reads its code once when Kodi
   starts -- so the layout is decided here instead, where reloading the page
   is enough to change it.  A group not named here keeps its place, after the
   ones that are.

   Read in rows of three on a desktop: picture, sound and processing first,
   then the Dolby Vision declaration, the machine and the per-frame numbers.
   The static HDR card is last because it only appears at all on an HDR title
   that is not Dolby Vision (see snapshot.py). */
const GROUP_ORDER =
  ["video", "audio", "processing", "dv", "system", "metadata", "hdr"];

function ordered(groups) {
  const rank = (group) => {
    const at = GROUP_ORDER.indexOf(group.id);
    return at === -1 ? GROUP_ORDER.length : at;
  };
  return [...groups].sort((first, second) => rank(first) - rank(second));
}

function renderGroups(groups) {
  const seen = new Set();

  groups.forEach((group, index) => {
    seen.add(group.id);
    let card = groupNodes.get(group.id);
    if (!card) {
      card = document.createElement("details");
      card.className = "card";
      TinyPPI.bindDisclosure(
        card, "dashboard.group." + group.id, DEFAULT_OPEN_GROUPS.has(group.id)
      );
      const heading = document.createElement("summary");
      heading.className = "panel-toggle";
      heading.textContent = group.title;
      const rows = document.createElement("div");
      rows.className = "rows";
      card.append(heading, rows);
      card.dataset.group = group.id;
      groupNodes.set(group.id, card);
    }
    /* Placed on every pass, not just when the card is made: the groups do not
       all arrive with the first snapshot -- the system readings settle after
       playback has run for a moment, the HDR blocks once the source is known
       -- and a card merely appended would keep whatever place it was late to,
       rather than the one the snapshot gives it. */
    const at = el.groups.children[index];
    if (at !== card) el.groups.insertBefore(card, at || null);
    renderRows(card.querySelector(".rows"), group);
  });

  for (const [id, card] of groupNodes) {
    if (!seen.has(id)) { card.remove(); groupNodes.delete(id); }
  }
}

function renderRows(container, group) {
  const wanted = group.rows.map((row) => row.id);
  const seen = new Set(wanted);

  group.rows.forEach((row, index) => {
    let node = rowNodes.get(row.id);
    if (!node) {
      const element = document.createElement("div");
      element.className = "row";
      const key = document.createElement("span");
      key.className = "k";
      const value = document.createElement("span");
      value.className = "v mono";
      element.append(key, value);
      node = { element, key, value, last: null, timer: 0 };
      rowNodes.set(row.id, node);
    }
    /* Keep the DOM in the order the snapshot names, so a row that appears
       mid-title lands where it belongs instead of at the end. */
    const at = container.children[index];
    if (at !== node.element) container.insertBefore(node.element, at || null);

    node.key.textContent = row.label;
    const text = row.detail ? row.value + "  " : row.value;
    if (node.last !== row.value + "\n" + row.detail) {
      if (node.last !== null && FLASH_ROWS.has(row.id)) flash(node);
      node.last = row.value + "\n" + row.detail;
      TinyPPI.renderValue(node.value, text);
      if (row.detail) {
        const detail = document.createElement("span");
        detail.className = "d";
        detail.textContent = row.detail;
        node.value.append(detail);
      }
    }
  });

  for (const [id, node] of rowNodes) {
    if (id.startsWith(group.id + ".") && !seen.has(id)) {
      node.element.remove();
      rowNodes.delete(id);
    }
  }
}

/* A changed L1 summary flashes briefly, then fades back to the normal colour. */
function flash(node) {
  node.element.classList.add("changed");
  clearTimeout(node.timer);
  node.timer = setTimeout(() => node.element.classList.remove("changed"), 750);
}

/* --- the film library ---------------------------------------------------- */

/* What the box could be playing instead of nothing.

   The add-on reads its video database once and holds the answer (see
   web/library.py), so asking again whenever a film ends costs a request and a
   validator rather than a query per phone in the house.  The wall is built
   once per list and then left alone: a library of a few thousand films is a
   few thousand nodes, and a keystroke in the search box is not a reason to
   make them again -- what does not match is hidden instead.

   The posters are fetched as they are scrolled to.  A wall of five hundred
   would otherwise ask the box for five hundred pictures the moment it was
   drawn, of which a phone shows six. */

const FILMS_RETRY_MS = 5000;
/* How long a pressed tile stays pressed with nothing having happened.  A film
   that starts takes the card off the page long before this; this is for the
   one that does not -- a missing file, a share that has gone away -- so the
   wall does not stay disabled for the evening. */
const FILMS_START_MS = 4000;

let films = [];            /* what the box last said its library holds    */
let filmsTag = "";         /* that list's own tag, unchanged lists skipped */
let filmsBusy = false;     /* a request is in flight                      */
let filmsRead = false;     /* the list has been read at least once        */
let filmsOffered = true;   /* until the box says it offers no library     */
let filmsNextTry = 0;      /* not before this, after a failure            */
let starting = 0;          /* the film a press is waiting on              */
let releasing = 0;         /* the timer that gives the wall back          */

function requestFilms(force) {
  if (filmsBusy || !filmsOffered) return;
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
  } catch (error) {
    filmsNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: there is no library on offer -- switched off in the add-on's
       settings, or a box that will not be told what to play.  Asking again
       every time a film ends would be asking to be told the same thing all
       evening. */
    if (String((error || {}).message) === "403") filmsOffered = false;
    if (!filmsRead) el.filmsCard.classList.add("hidden");
  }
}

function buildFilms() {
  const wall = document.createDocumentFragment();
  for (const film of films) wall.append(filmTile(film));
  el.filmGrid.replaceChildren(wall);
  applyFilmSearch();
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
  if (film.year) {
    const year = document.createElement("div");
    year.className = "filmyear";
    year.textContent = String(film.year);
    tile.append(year);
  }

  tile.addEventListener("click", () => startFilm(film, tile));
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

async function startFilm(film, tile) {
  if (starting) return;
  starting = film.id;
  tile.classList.add("busy");
  for (const node of el.filmGrid.children) node.disabled = true;
  TinyPPI.toast(T.films_starting);

  let failed = false;
  try {
    const response = await fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify({ movieid: film.id })
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
         it last played: the next idle page reads the list again. */
      filmsRead = false;
    }
  } catch (_) {
    failed = true;
    TinyPPI.toast(T.films_failed, true);
  }

  if (failed) {
    releaseFilms();
    return;
  }
  /* The snapshot takes the card off the page as soon as the film is on (see
     render); this is only for the film that never starts. */
  clearTimeout(releasing);
  releasing = setTimeout(releaseFilms, FILMS_START_MS);
}

function releaseFilms() {
  clearTimeout(releasing);
  releasing = 0;
  starting = 0;
  for (const tile of el.filmGrid.children) {
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

/* --- the series library -------------------------------------------------- */

/* The same shelf as the films, with one floor more.

   A series is not a thing that can be put on -- an episode is -- so a press on
   a poster does not start anything: the wall gives way to that show's
   episodes, and a press on one of those starts it.  The way back out is a
   button at the top of the card, where it is one press away however far down
   a forty-episode show somebody has scrolled.

   The episodes of a show are asked for when the show is opened and not before.
   A house with ninety series in it would otherwise be sent every episode of
   all of them to draw a wall of ninety posters, and it is the wall that is
   being looked at. */

let shows = [];            /* what the box last said its shelf holds      */
let seriesTag = "";        /* that list's own tag, unchanged lists skipped */
let seriesBusy = false;    /* a request for the shelf is in flight        */
let seriesRead = false;    /* the shelf has been read at least once       */
let seriesOffered = true;  /* until the box says it offers no series      */
let seriesNextTry = 0;     /* not before this, after a failure            */
let openShow = null;       /* the show whose episodes are on the card     */
let episodesBusy = false;  /* a request for one show's episodes           */
let startingEpisode = 0;   /* the episode a press is waiting on           */
let episodeReleasing = 0;  /* the timer that gives the list back          */

function requestSeries(force) {
  if (seriesBusy || !seriesOffered) return;
  if (!force && seriesRead) return;
  if (Date.now() < seriesNextTry) return;
  seriesBusy = true;
  loadSeries().finally(() => { seriesBusy = false; });
}

async function loadSeries() {
  try {
    const answer = await TinyPPI.getJSON("/api/series");
    seriesRead = true;
    seriesNextTry = 0;
    const list = Array.isArray(answer.shows) ? answer.shows : [];
    if (!el.seriesGrid.children.length || (answer.tag || "") !== seriesTag) {
      seriesTag = answer.tag || "";
      shows = list;
      buildSeries();
    }
    el.seriesCard.classList.remove("hidden");
    /* Away only inside a show, where there is no wall to narrow. */
    el.seriesBox.classList.toggle("hidden", openShow !== null);
  } catch (error) {
    seriesNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: no series on offer -- switched off in the add-on's settings, or a
       box that will not be told what to play.  A settled answer rather than a
       failure, so it is not asked again. */
    if (String((error || {}).message) === "403") seriesOffered = false;
    if (!seriesRead) el.seriesCard.classList.add("hidden");
  }
}

function buildSeries() {
  const wall = document.createDocumentFragment();
  for (const show of shows) wall.append(showTile(show));
  el.seriesGrid.replaceChildren(wall);
  /* A shelf that has just been read again is a shelf that may no longer hold
     the show somebody was inside, so the card comes back to the wall. */
  closeShow();
}

function showTile(show) {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "film";
  tile.dataset.key = (show.title + " " + (show.year || "")).toLowerCase();

  const frame = document.createElement("div");
  frame.className = "filmposter";
  if (show.poster) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = "";
    image.src = TinyPPI.withToken(
      "/api/art?kind=poster&tvshowid=" + encodeURIComponent(show.id) +
      "&v=" + encodeURIComponent(show.poster));
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  if (show.watched) {
    const seen = document.createElement("span");
    seen.className = "filmseen";
    seen.setAttribute("role", "img");
    seen.setAttribute("aria-label", T.films_watched);
    seen.title = T.films_watched;
    frame.append(seen);
  } else if (show.unseen) {
    /* How many episodes are still waiting, in the corner a watched film wears
       its tick in.  The one number a shelf of series is scanned for: what
       there is left to see, rather than how long the show is. */
    const waiting = document.createElement("span");
    waiting.className = "seriesnew";
    waiting.textContent = String(show.unseen);
    waiting.setAttribute("role", "img");
    waiting.setAttribute("aria-label", show.unseen + " " + T.series_unseen);
    waiting.title = T.series_unseen;
    frame.append(waiting);
  }

  const title = document.createElement("div");
  title.className = "filmtitle";
  title.textContent = show.title;
  tile.append(frame, title);
  if (show.year) {
    const year = document.createElement("div");
    year.className = "filmyear";
    year.textContent = String(show.year);
    tile.append(year);
  }

  tile.addEventListener("click", () => openShowView(show));
  return tile;
}

function applySeriesSearch() {
  const needle = el.seriesSearch.value.trim().toLowerCase();
  let shown = 0;
  for (const tile of el.seriesGrid.children) {
    const match = !needle || tile.dataset.key.includes(needle);
    tile.hidden = !match;
    if (match) shown += 1;
  }
  el.seriesSearchClear.classList.toggle("hidden", el.seriesSearch.value === "");
  if (openShow === null) {
    el.seriesCount.textContent = shown === shows.length
      ? String(shows.length) : shown + " / " + shows.length;
    el.seriesEmpty.classList.toggle("hidden", shown > 0);
  }
}

/* --- one show ------------------------------------------------------------ */

async function openShowView(show) {
  if (episodesBusy || startingEpisode) return;
  episodesBusy = true;
  try {
    const answer = await TinyPPI.getJSON(
      "/api/episodes?tvshowid=" + encodeURIComponent(show.id));
    openShow = show;
    buildEpisodes(Array.isArray(answer.episodes) ? answer.episodes : []);
    el.seriesGrid.classList.add("hidden");
    el.seriesSearch.classList.add("hidden");
    el.episodeList.classList.remove("hidden");
    el.seriesBack.classList.remove("hidden");
    el.seriesOpen.classList.remove("hidden");
    el.seriesOpen.textContent = show.title;
    /* The line about an empty shelf belongs to the wall, and the wall is not
       what is being looked at. */
    el.seriesEmpty.classList.add("hidden");
  } catch (_) {
    /* A shelf that has moved under the page -- the show scanned away while
       this was open -- reads the same as a box that cannot answer, and the
       next idle page reads the shelf again either way. */
    seriesRead = false;
    TinyPPI.toast(T.series_failed, true);
  } finally {
    episodesBusy = false;
  }
}

/* A show as its seasons, each folded away under its own heading.

   Shut to begin with, all of them: a series that has run for nine years is
   several hundred rows, and a list that opens on all of them is a list whose
   first screen is the middle of season one.  Shut, the whole show is a dozen
   lines -- which season, and how many episodes are in it -- and the one being
   looked for is one press away.

   It also costs nothing to draw: a still inside a shut fold is never fetched,
   so opening a show asks the box for the pictures of one season rather than of
   nine. */
function buildEpisodes(list) {
  const rows = document.createDocumentFragment();
  const many = new Map();
  for (const episode of list) {
    const number = seasonOf(episode);
    many.set(number, (many.get(number) || 0) + 1);
  }

  let season = null;
  let fold = null;          /* where this season's rows go, or null outside one */
  for (const episode of list) {
    const number = seasonOf(episode);
    if (number !== season) {
      season = number;
      /* An episode the library files under no season at all goes under no
         heading, and so into no fold either: there is nothing to call it, and
         a fold with no name on it is a row that hides things. */
      fold = number >= 0 ? seasonFold(number, many.get(number), rows) : null;
    }
    (fold || rows).append(episodeRow(episode));
  }
  el.episodeList.replaceChildren(rows);
  el.seriesCount.textContent = String(list.length);
}

function seasonOf(episode) {
  return typeof episode.season === "number" ? episode.season : -1;
}

/* One season's fold, added to the list; what comes back is where its episodes
   go. */
function seasonFold(number, count, into) {
  const fold = document.createElement("details");
  fold.className = "seasonfold";

  const heading = document.createElement("summary");
  heading.className = "season";
  const name = document.createElement("span");
  name.textContent = number === 0
    ? T.series_specials : T.series_season.replace("%s", number);
  const total = document.createElement("span");
  total.className = "seasoncount mono";
  total.textContent = String(count);
  heading.append(name, total);

  const body = document.createElement("div");
  body.className = "seasonepisodes";
  fold.append(heading, body);
  into.append(fold);
  return body;
}

function episodeRow(episode) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "episode";

  const frame = document.createElement("div");
  frame.className = "episodestill";
  if (episode.thumb) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = "";
    image.src = TinyPPI.withToken(
      "/api/art?kind=thumb&episodeid=" + encodeURIComponent(episode.id) +
      "&v=" + encodeURIComponent(episode.thumb));
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  if (episode.watched) {
    const seen = document.createElement("span");
    seen.className = "filmseen";
    seen.setAttribute("role", "img");
    seen.setAttribute("aria-label", T.films_watched);
    seen.title = T.films_watched;
    frame.append(seen);
  }
  if (episode.resume && episode.duration) {
    const bar = document.createElement("div");
    bar.className = "filmresume";
    bar.title = T.films_resume;
    const done = document.createElement("span");
    const at = Math.min(100, Math.max(2, (episode.resume / episode.duration) * 100));
    done.style.width = at.toFixed(1) + "%";
    bar.append(done);
    frame.append(bar);
  }

  const meta = document.createElement("div");
  meta.className = "episodemeta";
  const code = episodeCode(episode);
  if (code) {
    const number = document.createElement("div");
    number.className = "episodenumber mono";
    number.textContent = code;
    meta.append(number);
  }
  const title = document.createElement("div");
  title.className = "episodetitle";
  /* An episode the library has no name for is called by its number, which is
     the only name it has ever had. */
  title.textContent = episode.title || code;
  meta.append(title);

  row.append(frame, meta);
  row.addEventListener("click", () => startEpisode(episode, row));
  return row;
}

/* S01E04, or E04 where the library knows the number but not the season. */
function episodeCode(episode) {
  const pad = (value) => (value < 10 ? "0" + value : String(value));
  const season = typeof episode.season === "number" && episode.season > 0
    ? "S" + pad(episode.season) : "";
  const number = typeof episode.episode === "number" && episode.episode >= 0
    ? "E" + pad(episode.episode) : "";
  return season + number;
}

function closeShow() {
  openShow = null;
  el.episodeList.replaceChildren();
  el.episodeList.classList.add("hidden");
  el.seriesBack.classList.add("hidden");
  el.seriesOpen.classList.add("hidden");
  el.seriesGrid.classList.remove("hidden");
  el.seriesBox.classList.remove("hidden");
  applySeriesSearch();
}

async function startEpisode(episode, row) {
  if (startingEpisode) return;
  startingEpisode = episode.id;
  row.classList.add("busy");
  for (const node of el.episodeList.querySelectorAll(".episode")) {
    node.disabled = true;
  }
  TinyPPI.toast(T.films_starting);

  let failed = false;
  try {
    const response = await fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify({ episodeid: episode.id })
    });
    if (response.status === 401) {
      failed = true;
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      failed = true;
      TinyPPI.toast(T.films_failed, true);
    } else {
      /* What has been watched is about to move, on this episode and on the
         count its show's tile wears: the next idle page reads the shelf. */
      seriesRead = false;
    }
  } catch (_) {
    failed = true;
    TinyPPI.toast(T.films_failed, true);
  }

  if (failed) {
    releaseSeries();
    return;
  }
  clearTimeout(episodeReleasing);
  episodeReleasing = setTimeout(releaseSeries, FILMS_START_MS);
}

function releaseSeries() {
  clearTimeout(episodeReleasing);
  episodeReleasing = 0;
  startingEpisode = 0;
  for (const row of el.episodeList.querySelectorAll(".episode")) {
    row.disabled = false;
    row.classList.remove("busy");
  }
}

el.seriesSearch.addEventListener("input", applySeriesSearch);
el.seriesSearchClear.addEventListener("click", () => {
  el.seriesSearch.value = "";
  applySeriesSearch();
  el.seriesSearch.focus();
});
el.seriesBack.addEventListener("click", closeShow);

/* --- report ------------------------------------------------------------- */

function reportValue(row) {
  const value = TinyPPI.plainValue(row.value);
  const detail = row.detail ? TinyPPI.plainValue(row.detail) : "";
  if (!/[✔✘]/.test(row.value || "")) {
    return value + (detail ? "  " + detail : "");
  }

  /* The left report column already names both fields, so the right column
     only carries their values in the same order. */
  const parts = value.split(/\s*[|/]\s*/);
  if (detail) {
    const cleanDetail = detail.replace(/^\((.*)\)$/, "$1");
    parts.push(cleanDetail);
  }
  return parts.join(" | ");
}

/* What the title added up to, and what happened along the way.  Both come
   from the session the add-on has been keeping since playback started, so a
   report written a minute in and one written at the credits differ by exactly
   what happened in between -- and one written after the credits still has all
   of it (see renderLast). */
function summaryLines(session, peak) {
  const lines = [];
  if (peak !== null && peak !== undefined) {
    lines.push(TinyPPI.reportLine(T.peak, TinyPPI.fmtNits(peak) + " nits"));
  }
  lines.push(TinyPPI.reportLine(T.switches, String((session || {}).switches || 0)));
  lines.push(TinyPPI.reportLine(T.warnings, String((session || {}).warnings || 0)));
  return ["[" + T.summary + "]", ...lines, ""];
}

function eventLines() {
  const events = TinyPPI.panels.events();
  if (!events.length) return [];
  const lines = ["[" + T.events + "]"];
  for (const event of events) {
    lines.push(TinyPPI.reportLine(
      (event.pos ? event.pos + "  " : "") + event.label, event.text));
  }
  lines.push("");
  return lines;
}

function buildReport() {
  if (!state) return "";
  const peak = TinyPPI.panels.peak();
  if (!state.playing) {
    /* Nothing is playing, so the report is of the title that was: its heading,
       its figures and its events, with no rows to print between them. */
    const last = state.last;
    if (!last || !last.title) return "";
    return ["TinyPPI", last.title, "",
            ...summaryLines(last, last.peak === undefined ? peak : last.peak),
            ...eventLines()].join("\n");
  }

  const lines = ["TinyPPI"];
  if (state.title) lines.push(state.title);
  if (state.filename) lines.push(state.filename);
  lines.push("");
  for (const group of ordered(state.groups || [])) {
    lines.push("[" + group.title + "]");
    for (const row of group.rows) {
      lines.push(TinyPPI.reportLine(row.label, reportValue(row)));
    }
    lines.push("");
  }
  lines.push(...summaryLines(state.session, peak));
  lines.push(...eventLines());
  return lines.join("\n");
}

/* The clipboard, or a file named after the film where the browser will not
   give it the clipboard; both pages hand it over the same way (see
   TinyPPI.copyReport). */
el.copyBtn.addEventListener("click", () => {
  const title = (state || {}).playing
    ? state.title : ((state || {}).last || {}).title;
  TinyPPI.copyReport(buildReport(), title);
});

/* --- boot --------------------------------------------------------------- */

function applyStrings(strings, hello) {
  $("idleTitle").textContent = strings.idle_title;
  $("idleText").textContent = strings.idle_text;
  $("lastLabel").textContent = strings.last_played;
  $("filmsLabel").textContent = strings.films;
  el.filmsEmpty.textContent = strings.films_empty;
  el.filmSearch.placeholder = strings.films_search;
  el.filmSearch.setAttribute("aria-label", strings.films_search);
  for (const cross of [el.filmSearchClear, el.seriesSearchClear]) {
    cross.setAttribute("aria-label", strings.search_clear);
    cross.title = strings.search_clear;
  }
  $("seriesLabel").textContent = strings.series;
  $("seriesBackText").textContent = strings.series_back;
  el.seriesBack.setAttribute("aria-label", strings.series_back);
  el.seriesEmpty.textContent = strings.series_empty;
  el.seriesSearch.placeholder = strings.series_search;
  el.seriesSearch.setAttribute("aria-label", strings.series_search);
  TinyPPI.panels.strings(strings);
  $("vs10Title").textContent = strings.vs10;
  $("vs10OutLabel").textContent = strings.output;
  $("metaLinkText").textContent = strings.metadata;
  el.copyBtn.setAttribute("aria-label", strings.copy);
  el.copyBtn.title = strings.copy;
  if (hello) {
    el.version.textContent = "v" + hello.version;
  }
}

TinyPPI.boot({ onState: render, onStrings: applyStrings });
