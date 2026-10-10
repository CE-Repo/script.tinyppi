// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   TinyPPI second-screen dashboard.

   Everything printed here comes from the snapshot TinyPPI.boot delivers; the
   labels come translated with it, out of Kodi's own string table.  The
   connection itself lives in core.js.

   One page in six tabs -- live, Dolby Vision metadata, films, series and
   history, the same five in the same order as the floating bar of the
   TinyPPI app, and the settings.  Every tab is fed from the one stream whichever is in front;
   the metadata tab draws itself (js/metadata.js) and this file hands it the
   snapshot.

   This file holds the page's frame: the tabs, the bar, the live cards, VS10
   and the report.  The libraries live in js/films.js, js/series.js and
   js/continue.js, the question a press asks in js/marking.js, and js/start.js
   starts the page once all of them are loaded.  They are classic scripts and
   share one global scope; each lists what it takes from the others.
=========================================================================== */

/* global continueStale, episodeReleasing, filmsOffered, filmsStale,
   hideContinue, hideFilms, hideSeries, refreshEpisodes, releaseContinue,
   releaseFilms, releaseSeries, releasing, requestContinue, requestFilms,
   requestSeries, resumeReleasing, resuming, seriesOffered, seriesStale,
   starting, startingEpisode */
/* exported $, T, control, el, offerShelves, render, selectTab, storedTab,
   tabFromAddress */

const $ = TinyPPI.$;
const T = TinyPPI.T;

const el = {
  version: $("version"), idleCard: $("idleCard"),
  vs10Card: $("vs10Card"), vs10Out: $("vs10Out"), modes: $("modes"),
  groups: $("groups"),
  metricsCard: $("tiles"), metricsGrid: $("tiles").querySelector(".tilegrid"),
  eventsCard: $("eventsCard"), copyBtn: $("copyBtn"),
  copyMetaBtn: $("copyMetaBtn"), tokenShown: $("tokenShown"),
  historyIdleCard: $("historyIdleCard"),
  tabBar: $("tabBar"),
  continueFilmsCard: $("continueFilmsCard"), continueFilmsRow: $("continueFilmsRow"),
  continueFilmsCount: $("continueFilmsCount"),
  continueSeriesCard: $("continueSeriesCard"), continueSeriesRow: $("continueSeriesRow"),
  continueSeriesCount: $("continueSeriesCount"),
  lastCard: $("lastCard"), lastTitle: $("lastTitle"), lastTiles: $("lastTiles"),
  filmsCard: $("filmsCard"), filmGrid: $("filmGrid"),
  filmsCount: $("filmsCount"), filmsEmpty: $("filmsEmpty"),
  filmSearch: $("filmSearch"), filmSearchClear: $("filmSearchClear"),
  seriesCard: $("seriesCard"), seriesGrid: $("seriesGrid"),
  seriesCount: $("seriesCount"), seriesEmpty: $("seriesEmpty"),
  seriesSearch: $("seriesSearch"), seriesSearchClear: $("seriesSearchClear"),
  seriesBox: $("seriesSearchBox"), seriesBack: $("seriesBack"),
  seriesOpen: $("seriesOpen"), episodeList: $("episodeList"),
  recentFilmsCard: $("recentFilmsCard"), recentFilmsRow: $("recentFilmsRow"),
  recentSeriesCard: $("recentSeriesCard"), recentSeriesRow: $("recentSeriesRow"),
  unseenFilmsCard: $("unseenFilmsCard"), unseenFilmGrid: $("unseenFilmGrid"),
  unseenFilmsCount: $("unseenFilmsCount"),
  unseenSeriesCard: $("unseenSeriesCard"), unseenSeriesGrid: $("unseenSeriesGrid"),
  unseenSeriesCount: $("unseenSeriesCount"),
  markDialog: $("markDialog"), markTitle: $("markTitle"), markPlay: $("markPlay"),
  markRestart: $("markRestart"), markClear: $("markClear"),
  markWatched: $("markWatched"), markUnwatched: $("markUnwatched"),
  markCancel: $("markCancel")
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
/* The events are the history tab's, under what the title that has just ended
   came to.  (The luminance chart is moved to the metadata tab by
   js/metadata.js.) */
el.lastCard.after(el.eventsCard);

let state = null;
let control = false;
const rowNodes = new Map();  /* row id -> {element, key, value, last}     */
const groupNodes = new Map();
let pending = null;        /* the VS10 mode a button is waiting on      */
let wasPlaying = null;     /* what the last snapshot said, for the library */
let lastDrawn = "";        /* what the report card was last drawn from      */
let libraryAt = null;      /* which version of the shelves are on the page  */

/* Only the two per-frame L1 summaries use the transient change colour. */
const FLASH_ROWS = new Set(["metadata.32269", "metadata.32270"]);
const DEFAULT_OPEN_GROUPS = new Set([
  "video", "audio", "processing", "dv", "system", "metadata"
]);

TinyPPI.bindDisclosure(el.vs10Card, "dashboard.vs10", false);
/* The shelves arrive open, as they do in the app: each has a tab of its own
   now, and somebody who pressed "Films" came for the films.  They used to
   arrive folded, when they stood under the readings on the one page and two
   walls of posters opened there pushed everything else a screen and a half
   down.  A fold somebody shut stays shut.

   It costs nothing while the tab is not in front: a browser lays out nothing
   in a panel that is not displayed, so the posters are neither fetched nor
   drawn until the tab is opened.

   The first marks these cards ever wrote are dropped rather than left in
   storage to mean nothing (see bindDisclosure in js/core.js). */
TinyPPI.forgetDisclosure("dashboard.films");
TinyPPI.forgetDisclosure("dashboard.series");
TinyPPI.forgetDisclosure("dashboard.continue");
TinyPPI.bindDisclosure(el.filmsCard, "dashboard.filmshelf", true);
TinyPPI.bindDisclosure(el.seriesCard, "dashboard.seriesshelf", true);
TinyPPI.bindDisclosure(el.unseenFilmsCard, "dashboard.unseenfilms", true);
TinyPPI.bindDisclosure(el.unseenSeriesCard, "dashboard.unseenseries", true);
/* The row of things left half-watched, one on either shelf: the films on the
   films tab and the episodes on the series tab, as the app splits them. */
TinyPPI.bindDisclosure(el.continueFilmsCard, "dashboard.continuefilms", true);
TinyPPI.bindDisclosure(el.continueSeriesCard, "dashboard.continueseries", true);
/* And what arrived last, under them. */
TinyPPI.bindDisclosure(el.recentFilmsCard, "dashboard.recentfilms", true);
TinyPPI.bindDisclosure(el.recentSeriesCard, "dashboard.recentseries", true);

/* --- tabs --------------------------------------------------------------- */

/* The places the bar switches between, in its order. */
const TABS = ["live", "metadata", "films", "series", "history", "settings"];
const TAB_KEY = "tinyppi.tab";

let tab = null;            /* the tab in front                               */
const scrolls = new Map(); /* how far down each tab was left                 */
/* Whether the box offers either shelf at all, from /api/hello.  Until it has
   answered both are taken to be there, so a tab asked for by its address is
   not thrown back to the live one in the moment before the answer. */
let offered = { films: true, series: true };

/* Whether a tab has anything to show.  The shelves are tabs only on a box
   that will say what it holds and be told what to play, and the metadata tab
   only while a Dolby Vision title is playing -- there is no RPU to read on
   any other source, and with nothing playing there is nothing at all.
   Everything else is always there, with an idle card of its own for when
   nothing is playing. */
function tabAvailable(name) {
  if (name === "metadata") return state === null || dolbyVision(state);
  if (name === "films") {
    return offered.films && filmsOffered && (state === null || control);
  }
  if (name === "series") {
    return offered.series && seriesOffered && (state === null || control);
  }
  return TABS.includes(name);
}

/* A Dolby Vision title is playing: the source says so, or the add-on is
   already sending its metadata list. */
function dolbyVision(snapshot) {
  return !!snapshot.playing && (snapshot.hdr_type === "dolbyvision" ||
                                (snapshot.metadata || []).length > 0);
}

/* The tab the address asks for: #films, or /metadata -- the address the
   metadata window used to have, so a bookmark of it still lands there. */
function tabFromAddress() {
  const hash = location.hash.replace(/^#/, "");
  if (TABS.includes(hash)) return hash;
  if (/^\/metadata(\.html)?$/.test(location.pathname)) return "metadata";
  return "";
}

function storedTab() {
  try { return localStorage.getItem(TAB_KEY) || ""; } catch (_) { return ""; }
}

function selectTab(name, fromUser) {
  if (!tabAvailable(name)) name = "live";
  if (name === tab) {
    /* A press on the tab already in front goes back to its top, as a press on
       the app's bar does. */
    if (fromUser) window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (tab) scrolls.set(tab, window.scrollY);
  tab = name;

  for (const panel of document.querySelectorAll(".tabpanel")) {
    panel.classList.toggle("active", panel.dataset.tab === name);
  }
  for (const button of el.tabBar.querySelectorAll(".tab")) {
    const on = button.dataset.tab === name;
    button.classList.toggle("on", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  }

  /* Written into the address rather than pushed onto the history: back leaves
     the page, as it did before there were tabs, and a reload or a bookmark
     still comes back to the tab it was on. */
  if (location.hash !== "#" + name) {
    try { history.replaceState(null, "", "#" + name); } catch (_) {}
  }
  try { localStorage.setItem(TAB_KEY, name); } catch (_) {}

  window.scrollTo(0, scrolls.get(name) || 0);
  /* The chart and the event list are measured, and a tab that was away was
     measured at no size at all. */
  requestAnimationFrame(() => TinyPPI.panels.draw());
}

/* The tab bar itself: which of the five are on offer.  A tab that has just
   gone away takes the page back to the live one. */
function renderTabs() {
  for (const button of el.tabBar.querySelectorAll(".tab")) {
    button.classList.toggle("hidden", !tabAvailable(button.dataset.tab));
  }
  if (tab && !tabAvailable(tab)) selectTab("live");
}

/* Which shelves the box offers, from /api/hello.  An add-on older than the
   flags says nothing about them, and its shelves are taken to be there. */
function offerShelves(hello) {
  offered = {
    films: hello.library !== false,
    series: hello.series !== false
  };
  renderTabs();
}

el.tabBar.addEventListener("click", (event) => {
  const button = event.target.closest(".tab");
  if (button) selectTab(button.dataset.tab, true);
});

/* Left and right step along the bar, the way a tab list is walked with the
   keyboard; the tabs that are not on offer are stepped over. */
el.tabBar.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const shown = [...el.tabBar.querySelectorAll(".tab:not(.hidden)")];
  const at = shown.findIndex((button) => button.dataset.tab === tab);
  if (at === -1) return;
  const step = event.key === "ArrowRight" ? 1 : -1;
  const next = shown[(at + step + shown.length) % shown.length];
  selectTab(next.dataset.tab, true);
  next.focus();
  event.preventDefault();
});

window.addEventListener("hashchange", () => {
  const name = tabFromAddress();
  if (name) selectTab(name);
});

/* --- the bar's comings and goings -------------------------------------- */

/* The bar keeps out of the way unless somebody is doing something, the way
   the app's does: a finger on the screen, a scroll, a wheel, a key or a
   moving pointer brings it back, and once nothing has happened for
   BAR_HIDE_MS it steps away, so a page of readings is left to be read on its
   own and its last card can come all the way down the screen.  It does not
   leave from under a finger that is still down, a pointer resting on it or a
   key that has the focus, nor while a dialog is open. */
const BAR_HIDE_MS = 3000;
let barTimer = 0;
let barHeld = false;       /* a finger or a button is down                  */
let barLeftAt = 0;         /* when it last stepped away                     */

function barMayLeave() {
  return !barHeld && !el.tabBar.matches(":hover, :focus-within") &&
         !document.querySelector("dialog[open]");
}

function wakeBar() {
  document.documentElement.classList.remove("bar-away");
  clearTimeout(barTimer);
  barTimer = setTimeout(function hide() {
    if (barMayLeave()) {
      document.documentElement.classList.add("bar-away");
      barLeftAt = Date.now();
    } else barTimer = setTimeout(hide, BAR_HIDE_MS);
  }, BAR_HIDE_MS);
}

document.addEventListener("pointerdown", () => { barHeld = true; wakeBar(); },
                          { capture: true, passive: true });
for (const kind of ["pointerup", "pointercancel"]) {
  document.addEventListener(kind, () => { barHeld = false; wakeBar(); },
                            { capture: true, passive: true });
}
for (const kind of ["pointermove", "wheel", "keydown", "touchmove"]) {
  document.addEventListener(kind, wakeBar, { capture: true, passive: true });
}
/* A page scrolled to its foot is scrolled by the browser itself as the room
   at the bottom shrinks behind the leaving bar; that is not somebody
   scrolling, and taken for one it would call the bar straight back, for
   good. */
window.addEventListener("scroll", () => {
  if (Date.now() - barLeftAt > 600) wakeBar();
}, { passive: true });
wakeBar();

/* --- settings ----------------------------------------------------------- */

/* The two reports on the settings tab: the readings and the events, and the
   metadata list.  A key with nothing to copy is dimmed rather than taken
   away, so the card keeps its shape. */
function updateCopy() {
  el.copyBtn.disabled =
    !state || !(state.playing || (state.last && state.last.title));
  el.copyMetaBtn.disabled = !TinyPPI.metadata.listed();
}

/* Which token this device holds, all but its last two characters hidden: it
   says whether there is one and which, without putting it on a screen that
   may be the one on the wall. */
function renderToken() {
  const token = TinyPPI.token || "";
  el.tokenShown.textContent = token
    ? "\u2022".repeat(Math.max(0, token.length - 2)) + token.slice(-2)
    : T.na;
}
document.addEventListener("tinyppi-token", renderToken);
renderToken();

/* --- render ------------------------------------------------------------- */

function render(next) {
  state = next;
  control = !!next.control;
  /* Before anything is drawn: what the box says about its own library decides
     whether the two shelves are still what it holds. */
  libraryVersion(next.library);

  /* The common live module draws what is playing, the summary tiles, the
     luminance chart on the metadata tab and the events on the history tab. */
  TinyPPI.panels.update(next);
  TinyPPI.metadata.render(next);
  /* The former metrics card disappeared while idle; preserve that behaviour
     now that its grid lives inside the event card, which may hold the events
     of the title that just ended. */
  el.metricsGrid.classList.toggle("hidden", !next.playing);
  renderTabs();

  /* What could be playing, on the two shelf tabs, whether or not anything
     already is.  Read again the moment a film ends, however lately the
     playing page read it: what the box last played and how far into it, on
     every tile the walls carry, has just moved.  While something plays it is
     asked for once -- the first arrival on a box that is already playing has
     never read either list -- and nothing is forced: a poster wall rebuilt
     under somebody scrolling it is a wall that jumps. */
  const ended = !next.playing && wasPlaying !== false;
  if (control) requestFilms(ended);
  else hideFilms();
  if (control) requestSeries(ended);
  else hideSeries();
  if (control) requestContinue(ended);
  else hideContinue();

  if (!next.playing) {
    el.idleCard.classList.remove("hidden");
    el.vs10Card.classList.add("hidden");
    /* Asked for rather than done: the box builds a snapshot five times a
       second whether or not anything in it moved, so this runs five times a
       second on a page that is standing still -- and every write to the
       document is a page laid out again. */
    if (el.groups.firstChild) el.groups.innerHTML = "";
    rowNodes.clear();
    groupNodes.clear();
    renderLast(next.last);
    /* The line saying there is no history is for a box that has played
       nothing: the title that just ended is the history tab's while the
       add-on still holds it. */
    el.historyIdleCard.classList.toggle("hidden", !!(next.last && next.last.title));
    wasPlaying = false;
    updateCopy();
    return;
  }

  el.idleCard.classList.add("hidden");
  el.historyIdleCard.classList.add("hidden");
  el.lastCard.classList.add("hidden");
  lastDrawn = "";
  wasPlaying = true;
  /* A film that was pressed is on: whatever tile was waiting on it is done
     waiting, so the wall it was pressed on can be used again. */
  if (starting || releasing) releaseFilms();
  if (startingEpisode || episodeReleasing) releaseSeries();
  if (resuming || resumeReleasing) releaseContinue();

  renderVs10(next.vs10 || {});
  renderGroups(ordered(next.groups || []));
  updateCopy();
}

/* Which version of the box's two shelves this page is holding.

   Every snapshot carries the number the add-on is on (see ``revision`` in
   web/library.py), and that number moves whenever what the shelves would say
   moves: a film watched to the end, one switched off in the middle, a scan
   that added a series.  None of which this page could otherwise hear about --
   the lists are read once and then left alone -- which is why a dashboard left
   open on a television for an evening went on showing everything it had
   watched as unwatched until somebody reloaded it.

   What happens here is only that the lists are marked unread.  Whichever of
   them this page is actually showing asks for itself further down the same
   render, and a list nobody has ever opened is not fetched for the sake of a
   number.  A read that comes back with the tag it had leaves the wall -- and
   anything the search box is holding -- exactly as it was, so a version that
   moved without moving these two costs one validator and no redraw. */
function libraryVersion(version) {
  /* An add-on older than this sends no number at all, and a page talking to
     one keeps the behaviour it had: the lists are read when a film ends. */
  if (typeof version !== "number") return;
  if (libraryAt === null) {
    libraryAt = version;
    return;
  }
  if (version === libraryAt) return;
  libraryAt = version;
  filmsStale();
  seriesStale();
  continueStale();
  /* The show somebody is inside is a list of its own, and the episode they
     have just watched is a row in it. */
  refreshEpisodes();
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
    lastDrawn = "";
    return;
  }
  el.lastCard.classList.remove("hidden");

  /* Drawn again only when it would come out differently.  Two figures and a
     title is nothing to build -- but it is five node replacements a second on
     a page that is not moving, and each one costs the browser a fresh layout
     of everything under it, which on the idle page is the film wall (see
     content-visibility in css/dashboard.css). */
  const drawn = last.title + "\x1f" + (last.switches || 0) +
    "\x1f" + (last.warnings || 0);
  if (drawn === lastDrawn) return;
  lastDrawn = drawn;

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
  el.vs10Out.textContent = vs10.output || T.na;

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
   give it the clipboard; the metadata list is handed over the same way (see
   TinyPPI.copyReport). */
el.copyMetaBtn.addEventListener("click", () => TinyPPI.metadata.copy());
el.copyBtn.addEventListener("click", () => {
  const title = (state || {}).playing
    ? state.title : ((state || {}).last || {}).title;
  TinyPPI.copyReport(buildReport(), title);
});
