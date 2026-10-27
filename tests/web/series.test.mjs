// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The series library tab (resources/web/js/series.js): the shelf of shows
// and what each tile wears, the unwatched and recent rows, the search, one
// show opened as its folded seasons and episode rows, the way back out, the
// open show read again in place, when the shelf is read again and when it is
// not, and starting an episode.  The whole page is loaded in the order
// index.html gives, with its timers on a clock the test moves.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { page, settle, source } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");
const ORDER = ["theme.js", "core.js", "colour.js", "cover-tint.js", "readings.js",
               "live-chapters.js", "live-remote.js", "live-panels.js", "metadata.js", "dashboard.js", "shelf-tools.js", "films.js", "series.js",
               "continue.js", "marking.js", "cards.js", "start.js"];

/** Run one of the page's scripts under its own file URL, as harness.mjs
 * does, so that the page's timers can be replaced first. */
function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/** The page's timers and Date.now on a clock only the test moves. */
function fakeClock(window) {
  let now = Date.now();
  let serial = 0;
  const timers = new Map();
  window.setTimeout = (fn, delay = 0) => {
    serial += 1;
    timers.set(serial, { fn, at: now + Math.max(0, Number(delay) || 0) });
    return serial;
  };
  window.clearTimeout = (id) => { timers.delete(id); };
  window.requestAnimationFrame = (fn) => window.setTimeout(fn, 16);
  window.Date.now = () => now;
  return {
    tick(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        for (const [id, timer] of timers) {
          if (timer.at <= end && (!next || timer.at < next[1].at)) next = [id, timer];
        }
        if (!next) break;
        timers.delete(next[0]);
        now = next[1].at;
        next[1].fn();
      }
      now = end;
    },
  };
}

const STRINGS = { films_play: "Play", series_open: "Open" };

const SHOWS = [
  { id: 1, title: "Andor", year: 2022, poster: "a1", rating: 8.4, rating_from: "imdb",
    episodes: 12, unseen: 4, added: "2026-08-01 10:00:00" },
  { id: 2, title: "Babylon 5", year: 1993, episodes: 110, unseen: 0, watched: true,
    added: "2026-08-03 10:00:00" },
  { id: 3, title: "Columbo", episodes: 69 },
  { id: 4, title: "Dark", year: 2017, poster: "d 4", episodes: 26, unseen: 26 },
];

const EPISODES = [
  { id: 100, title: "Making of", season: 0, episode: 1, duration: 600 },
  { id: 101, title: "Kassa", season: 1, episode: 1, duration: 2400, watched: true,
    thumb: "t 1" },
  { id: 102, title: "That Would Be Me", season: 1, episode: 2, duration: 2400, resume: 600 },
  { id: 110, title: "One Way Out", season: 2, episode: 10 },
  { id: 111, season: 2, episode: 11 },
  { id: 120, title: "Lost reel" },
];

const IDLE = { playing: false, control: true };
const PLAYING = { playing: true, control: true };

/** The dashboard with *shows* on the series shelf, *episodes* in every show
 * and control allowed; the first idle snapshot is delivered unless *quiet*.
 * The window is closed when the test ends. */
async function open(t, { shows = SHOWS, episodes = EPISODES, routes = {}, token = "",
                         quiet = false } = {}) {
  const table = { "/api/details": [200, {}],
    "/api/hello": [200, { version: "2.15.0", strings: STRINGS }],
    "/api/library": [200, { tag: "f1", movies: [] }],
    "/api/series": [200, { tag: "s1", shows }],
    "/api/episodes": [200, { tag: "e1", episodes }],
    "/api/continue": [200, { tag: "c1", items: [] }],
    "/api/play": [200, {}],
    ...routes,
  };
  const view = page({ scripts: [], routes: table, token });
  const { window, dom } = view;
  t.after(() => window.close());
  const clock = fakeClock(window);
  window.scrollTo = () => {};
  const scrolled = [];
  window.HTMLElement.prototype.scrollIntoView = function (options) {
    scrolled.push([this.id, JSON.parse(JSON.stringify(options))]);
  };
  for (const name of ORDER) load(dom, name);
  await settle();
  let seq = 0;
  let library = 0;
  const result = {
    ...view, routes: table, clock, scrolled,
    $: (id) => window.document.getElementById(id),
    async state(snapshot) {
      seq += 1;
      view.streams.at(-1).emit("state", { library, ...snapshot, seq });
      await settle();
    },
    /** A snapshot saying the box's library has moved. */
    async moved() {
      library += 1;
      await result.state(IDLE);
    },
  };
  if (!quiet) await result.state(IDLE);
  return result;
}

/** Hold every answer to *path* until the returned function is called. */
function hold(view, path) {
  const fetch = view.window.fetch;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  view.window.fetch = async (url, init) => {
    const answer = fetch(url, init);
    if (String(url).replace(/\?.*$/, "") === path) await gate;
    return answer;
  };
  return async () => {
    view.window.fetch = fetch;
    release();
    await settle();
  };
}

const tiles = (view, id) => [...view.$(id).children];
const titles = (view, id) => tiles(view, id)
  .map((node) => node.querySelector(".filmtitle").textContent);
const shown = (view, id) => tiles(view, id).filter((node) => !node.hidden)
  .map((node) => node.querySelector(".filmtitle").textContent);
const hidden = (view, id) => view.$(id).classList.contains("hidden");

/** The tile for the show called *title* on the wall or row *id*. */
function tile(view, title, id = "seriesGrid") {
  const found = tiles(view, id)
    .find((node) => node.querySelector(".filmtitle").textContent === title);
  assert.ok(found, title);
  return found;
}

/** The open show's row for the episode called *title*. */
function row(view, title) {
  const found = [...view.$("episodeList").querySelectorAll(".episode")]
    .find((node) => node.querySelector(".episodetitle").textContent === title);
  assert.ok(found, title);
  return found;
}

const rows = (view) => [...view.$("episodeList").querySelectorAll(".episode")];

/** Answer the question that is open, as the dialog's form would. */
function answer({ window, $ }, value) {
  if (value === "details") return;
  const dialog = $("detailsDialog");
  if (["restart", "clear", "watched", "unwatched"].includes(value)) {
    dialog.querySelector('button[value="' + value + '"]').click();
    return;
  }
  dialog.returnValue = value;
  dialog.close();
  dialog.dispatchEvent(new window.Event("close"));
}

/** Press *node* and give *value* as the answer. */
async function press(view, node, value = "play") {
  node.dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, value);
  await settle();
}

/** Open the show called *title* from the wall or row *id*. */
const openShow = (view, title, id = "seriesGrid") => press(view, tile(view, title, id));

/** Whether the dialog of the open show's seasons is up. */
const seasonsOpen = (view) => view.$("seasonsDialog").open;

/** Close that dialog, as its key or Escape would, and then -- unless
 * *keep* -- the show's details it gives way to. */
async function closeSeasons(view, { keep = false } = {}) {
  const dialog = view.$("seasonsDialog");
  dialog.close();
  dialog.dispatchEvent(new view.window.Event("close"));
  await settle();
  if (!keep && view.$("detailsDialog").open) answer(view, "cancel");
  await settle();
}

/** A pull on *dialog* from *from* down to *to*, as a finger would. */
function pull({ window }, dialog, from, to) {
  const touch = (type, key, y) => {
    const event = new window.Event(type, { bubbles: true });
    Object.defineProperty(event, key, { value: [{ clientY: y }] });
    dialog.dispatchEvent(event);
  };
  touch("touchstart", "touches", from);
  touch("touchend", "changedTouches", to);
}

const reads = ({ requests }, path) =>
  requests.filter((request) => request.url.replace(/\?.*$/, "") === path).length;

const plays = ({ requests }) => requests
  .filter((request) => request.url === "/api/play")
  .map((request) => JSON.parse(request.init.body));

/** Each season fold as [heading, count line, open, episodes in it]. */
const folds = (view) => [...view.$("episodeList").querySelectorAll(".seasonfold")]
  .map((fold) => [fold.querySelector(".season span").textContent,
                  fold.querySelector(".seasoncount").textContent, fold.open,
                  fold.querySelectorAll(".episode").length]);

test("the shelf holds every show, with its poster, rating and what is left to see", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  assert.deepEqual(titles(view, "seriesGrid"), ["Andor", "Babylon 5", "Columbo", "Dark"]);
  assert.equal(hidden(view, "seriesCard"), false);
  assert.equal(view.$("seriesCount").textContent, "4");
  assert.equal(hidden(view, "seriesEmpty"), true);

  const andor = tile(view, "Andor");
  assert.equal(andor.dataset.key, "andor 2022");
  const poster = andor.querySelector(".filmposter img");
  assert.equal(poster.getAttribute("src"), "/api/art?kind=poster&tvshowid=1&v=a1");
  assert.equal(poster.alt, "");
  assert.equal(andor.querySelector(".filmrating").getAttribute("aria-label"), "IMDb 8.4");
  const waiting = andor.querySelector(".seriesnew");
  assert.equal(waiting.textContent, "4");
  assert.equal(waiting.getAttribute("role"), "img");
  assert.equal(waiting.getAttribute("aria-label"), "4 Unwatched episodes");
  assert.equal(waiting.title, "Unwatched episodes");
  assert.equal(andor.querySelector(".filmseen"), null);
  assert.equal(andor.querySelector(".filmyear").textContent, "2022");

  // Seen to the end: the tick instead of a count.
  const babylon = tile(view, "Babylon 5");
  assert.equal(babylon.querySelector(".filmseen").getAttribute("aria-label"), "Watched");
  assert.equal(babylon.querySelector(".filmseen").title, "Watched");
  assert.equal(babylon.querySelector(".seriesnew"), null);

  // Nothing known but the title: an empty frame and no line under it.
  const columbo = tile(view, "Columbo");
  assert.equal(columbo.dataset.key, "columbo ");
  assert.equal(columbo.querySelector(".filmposter").children.length, 0);
  assert.equal(columbo.querySelector(".filmyear"), null);

  assert.equal(tile(view, "Dark").querySelector("img").getAttribute("src"),
               "/api/art?kind=poster&tvshowid=4&v=d%204");
});

test("a poster or a still the box cannot read leaves the empty frame behind", async (t) => {
  const view = await open(t);
  const frame = tile(view, "Andor").querySelector(".filmposter");
  frame.querySelector("img").dispatchEvent(new view.window.Event("error"));
  assert.equal(frame.querySelector("img"), null);
  assert.ok(frame.querySelector(".seriesnew"));

  await openShow(view, "Andor");
  const still = row(view, "Kassa").querySelector(".episodestill");
  still.querySelector("img").dispatchEvent(new view.window.Event("error"));
  assert.equal(still.querySelector("img"), null);
  assert.ok(still.querySelector(".filmseen"));
});

test("the unwatched row holds the shows with an episode waiting, and says how many", async (t) => {
  const view = await open(t);
  // Columbo has no count of what is waiting, so nothing says it has any.
  assert.deepEqual(titles(view, "unseenSeriesGrid"), ["Andor", "Dark"]);
  assert.equal(view.$("unseenSeriesCount").textContent, "2");
  assert.equal(hidden(view, "unseenSeriesCard"), false);
  assert.notEqual(tile(view, "Andor", "unseenSeriesGrid"), tile(view, "Andor"));
});

test("with nothing waiting the unwatched row goes away and its count is blank", async (t) => {
  const view = await open(t, { shows: [SHOWS[1], SHOWS[2]] });
  assert.deepEqual(titles(view, "unseenSeriesGrid"), []);
  assert.equal(view.$("unseenSeriesCount").textContent, "");
  assert.equal(hidden(view, "unseenSeriesCard"), true);
});

test("the recent row holds the shows that gained an episode lately, newest first", async (t) => {
  const view = await open(t);
  assert.deepEqual(titles(view, "recentSeriesRow"), ["Babylon 5", "Andor"]);
  assert.equal(hidden(view, "recentSeriesCard"), false);

  const undated = await open(t, { shows: [SHOWS[2], SHOWS[3]] });
  assert.deepEqual(titles(undated, "recentSeriesRow"), []);
  assert.equal(hidden(undated, "recentSeriesCard"), true);
});

test("an empty shelf, or an answer without a list, says there is nothing", async (t) => {
  const view = await open(t, { shows: [] });
  assert.equal(hidden(view, "seriesCard"), false);
  assert.equal(view.$("seriesCount").textContent, "0");
  assert.equal(hidden(view, "seriesEmpty"), false);
  assert.equal(hidden(view, "recentSeriesCard"), true);
  assert.equal(hidden(view, "unseenSeriesCard"), true);

  const other = await open(t, { routes: { "/api/series": [200, { shows: null }] } });
  assert.deepEqual(titles(other, "seriesGrid"), []);
  assert.equal(other.$("seriesCount").textContent, "0");
});

test("the search narrows the shelf by title and year, and clearing it puts it back", async (t) => {
  const view = await open(t);
  const search = view.$("seriesSearch");
  search.value = " 20";
  search.dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "seriesGrid"), ["Andor", "Dark"]);
  assert.equal(view.$("seriesCount").textContent, "2 / 4");
  assert.equal(hidden(view, "seriesSearchClear"), false);
  assert.equal(hidden(view, "seriesEmpty"), true);

  search.value = "Lost";
  search.dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "seriesGrid"), []);
  assert.equal(view.$("seriesCount").textContent, "0 / 4");
  assert.equal(hidden(view, "seriesEmpty"), false);

  view.$("seriesSearchClear").click();
  assert.equal(search.value, "");
  assert.equal(shown(view, "seriesGrid").length, 4);
  assert.equal(view.$("seriesCount").textContent, "4");
  assert.equal(hidden(view, "seriesSearchClear"), true);
  assert.equal(view.window.document.activeElement, search);
});

test("a press on a show asks to open it, and opening it lists its seasons folded away in a dialog", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  tile(view, "Andor").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsTitle").textContent, "Andor");
  assert.equal(view.$("detailsPlay").textContent, "Open");
  assert.equal(view.$("detailsRestart").hidden, true);
  answer(view, "play");
  await settle();

  const asked = view.requests.filter((request) => request.url.startsWith("/api/episodes"));
  assert.deepEqual(asked.map((request) => request.url), ["/api/episodes?tvshowid=1"]);
  assert.deepEqual(plays(view), []);
  // Shut, every one, with how many episodes and how long they run.
  assert.deepEqual(folds(view), [["Specials", "1 · 10 min", false, 1],
                                 ["Season 1", "2 · 1 h 20 min", false, 2],
                                 ["Season 2", "2", false, 2]]);
  // An episode filed under no season stands under no heading.
  const loose = view.$("episodeList").lastElementChild;
  assert.equal(loose.classList.contains("episode"), true);
  assert.equal(loose.querySelector(".episodetitle").textContent, "Lost reel");

  assert.equal(seasonsOpen(view), true);
  assert.equal(view.$("seasonsDialog").contains(view.$("episodeList")), true);
  assert.equal(view.$("seriesOpen").textContent, "Andor");
  assert.equal(view.$("seasonsCount").textContent, "2022 · 6 episodes");
  // The wall stays as it was under the dialog, still counting the shows.
  assert.equal(hidden(view, "seriesGrid"), false);
  assert.equal(hidden(view, "seriesSearchBox"), false);
  assert.equal(view.$("seriesCount").textContent, "4");
  assert.deepEqual(view.scrolled, []);
});

test("an episode row carries its still, tick, resume bar, number and running time", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  await openShow(view, "Andor");

  const kassa = row(view, "Kassa");
  assert.equal(kassa.type, "button");
  const still = kassa.querySelector(".episodestill img");
  assert.equal(still.getAttribute("src"), "/api/art?kind=thumb&episodeid=101&v=t%201");
  assert.equal(still.alt, "");
  assert.equal(kassa.querySelector(".filmseen").getAttribute("aria-label"), "Watched");
  assert.equal(kassa.querySelector(".filmresume"), null);
  assert.equal(kassa.querySelector(".episodenumber").textContent, "S01E01 · 40 min");

  const started = row(view, "That Would Be Me");
  assert.equal(started.querySelector(".episodestill").querySelector("img"), null);
  assert.equal(started.querySelector(".filmseen"), null);
  const bar = started.querySelector(".filmresume");
  assert.equal(bar.title, "Resume");
  assert.equal(bar.querySelector("span").style.width, "25%");
});

test("episodes are numbered S01E04, E04 without a season, and named by number when nameless", async (t) => {
  const view = await open(t, { episodes: [
    ...EPISODES, { id: 130, title: "Zero", season: 3, episode: 0, duration: 1500, resume: 1 },
  ] });
  await openShow(view, "Andor");
  const number = (title) => {
    const line = row(view, title).querySelector(".episodenumber");
    return line && line.textContent;
  };
  assert.equal(number("Making of"), "E01 · 10 min");     // a special
  assert.equal(number("One Way Out"), "S02E10");
  assert.equal(number("S02E11"), "S02E11");                    // no title of its own
  assert.equal(number("Zero"), "S03E00 · 25 min");
  // No number and no length: no line for them at all.
  assert.equal(number("Lost reel"), null);
  // Barely begun still shows a sliver.
  assert.equal(row(view, "Zero").querySelector(".filmresume span").style.width, "2%");
});

test("a press on an episode asks to play it, or to resume one that got somewhere", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  row(view, "Kassa").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(view.$("detailsTitle").textContent, "S01E01 · Kassa");
  assert.equal(view.$("detailsPlay").textContent, "Play");
  assert.equal(view.$("detailsRestart").hidden, true);
  answer(view, "cancel");

  row(view, "That Would Be Me").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

  await settle();
  assert.equal(view.$("detailsTitle").textContent, "S01E02 · That Would Be Me");
  assert.equal(view.$("detailsPlay").textContent, "Resume");
  assert.equal(view.$("detailsRestart").hidden, false);
  answer(view, "cancel");

  row(view, "S02E11").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

  await settle();
  assert.equal(view.$("detailsTitle").textContent, "S02E11");
  answer(view, "cancel");
  row(view, "Lost reel").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(view.$("detailsTitle").textContent, "Lost reel");
  answer(view, "cancel");
  await settle();
  assert.deepEqual(plays(view), []);
});

test("closing the dialog lets the show go and leaves the wall as it was", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  await closeSeasons(view);
  assert.equal(seasonsOpen(view), false);
  assert.equal(view.$("episodeList").children.length, 0);
  assert.equal(view.$("seasonsCount").textContent, "");
  assert.equal(hidden(view, "seriesGrid"), false);
  assert.equal(view.$("seriesCount").textContent, "4");
  // Nothing is read for a show nobody has open.
  await view.moved();
  assert.equal(reads(view, "/api/episodes"), 1);
});

test("the seasons wear the show's backdrop and poster as its details do, or stand bare without them", async (t) => {
  const view = await open(t, { shows: [{ ...SHOWS[0], fanart: "f 1" }, SHOWS[2]] });
  await openShow(view, "Andor");
  const backdrop = view.$("seasonsBackdrop");
  const poster = view.$("seasonsPoster");
  assert.equal(backdrop.hidden, false);
  assert.equal(backdrop.getAttribute("src"), "/api/art?kind=fanart&tvshowid=1&v=f%201");
  assert.equal(poster.getAttribute("src"), "/api/art?kind=poster&tvshowid=1&v=a1");
  assert.equal(view.$("seasonsHero").classList.contains("bare"), false);
  // A backdrop the box cannot read leaves the heading on the plain page.
  backdrop.dispatchEvent(new view.window.Event("error"));
  assert.equal(backdrop.hidden, true);
  assert.equal(view.$("seasonsHero").classList.contains("bare"), true);
  await closeSeasons(view);

  // Nothing to show at all: no pictures, and no line under the name.
  view.routes["/api/episodes"] = [200, { episodes: [] }];
  await openShow(view, "Columbo");
  assert.equal(view.$("seasonsBackdrop").hidden, true);
  assert.equal(view.$("seasonsPoster").hidden, true);
  assert.equal(view.$("seasonsPoster").getAttribute("src"), null);
  assert.equal(view.$("seasonsHero").classList.contains("bare"), true);
  assert.equal(view.$("seasonsCount").textContent, "");
});

test("Open keeps the show's page under its seasons, which slide away to it again", async (t) => {
  const view = await open(t);
  const details = view.$("detailsDialog");
  const ask = async (node) => {
    node.dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    await settle();
  };
  const press = (button) => {
    const click = new view.window.MouseEvent("click", { bubbles: true, cancelable: true });
    button.dispatchEvent(click);
    return click.defaultPrevented;
  };
  await ask(tile(view, "Andor"));
  const read = reads(view, "/api/details");
  assert.equal(press(view.$("detailsPlay")), true, "the page is not put away");
  await settle();
  assert.equal(seasonsOpen(view), true);
  assert.equal(details.open, true);
  assert.equal(view.$("seasonsDialog").style.minHeight, "0px");

  // Left again: the page under them is simply there, nothing read for it.
  await closeSeasons(view, { keep: true });
  assert.equal(details.open, true);
  assert.equal(view.$("detailsTitle").textContent, "Andor");
  assert.equal(reads(view, "/api/details"), read);

  // An episode's page comes up in front of the seasons in the show's place.
  press(view.$("detailsPlay"));
  await settle();
  await ask(row(view, "Kassa"));
  assert.equal(details.open, true);
  assert.equal(view.$("detailsTitle").textContent, "S01E01 · Kassa");
  // The close that shut it only to show it again in front answers nothing.
  details.dispatchEvent(new view.window.Event("close"));
  assert.deepEqual(plays(view), []);
  answer(view, "cancel");
  await settle();
  assert.equal(details.open, false);

  // Leaving the seasons now puts the show's page back, drawn from what was
  // read of it rather than asked for again.
  await closeSeasons(view, { keep: true });
  assert.equal(details.open, true);
  assert.equal(view.$("detailsTitle").textContent, "Andor");
  assert.equal(reads(view, "/api/details"), read + 1);
  assert.equal(view.$("seasonsDialog").style.minHeight, "0px");
});

test("the seasons slide in, and slide out by their key or Escape before they close", async (t) => {
  const view = await open(t);
  const seasons = view.$("seasonsDialog");
  const classes = [];
  const add = seasons.classList.add.bind(seasons.classList);
  seasons.classList.add = (...names) => { classes.push(...names); add(...names); };
  await openShow(view, "Andor");
  // Put off to the side to be laid out, and taken back to slide in.
  assert.deepEqual(classes, ["away"]);
  assert.equal(seasons.classList.contains("away"), false);

  const key = new view.window.MouseEvent("click", { bubbles: true, cancelable: true });
  view.$("seasonsX").dispatchEvent(key);
  assert.equal(key.defaultPrevented, true);
  assert.equal(seasons.classList.contains("away"), true);
  // A second way out while it is going changes nothing.
  view.$("seasonsX").click();
  view.clock.tick(249);
  assert.equal(seasons.open, true);
  view.clock.tick(1);
  assert.equal(seasons.open, false);
  await closeSeasons(view);

  await openShow(view, "Andor");
  const escape = new view.window.Event("cancel", { cancelable: true });
  seasons.dispatchEvent(escape);
  assert.equal(escape.defaultPrevented, true);
  view.clock.tick(250);
  assert.equal(seasons.open, false);
});

test("a title's page asked for again within a minute is drawn from what was read, later it is read again", async (t) => {
  const view = await open(t);
  const ask = async () => {
    tile(view, "Andor").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    await settle();
    answer(view, "cancel");
    await settle();
  };
  // While the box is asked, the page says so; drawn from what was read, it
  // has nothing to wait for.
  const root = view.window.document.documentElement;
  tile(view, "Andor").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  assert.equal(root.classList.contains("detailsloading"), true);
  await settle();
  assert.equal(root.classList.contains("detailsloading"), false);
  answer(view, "cancel");
  await settle();
  const read = reads(view, "/api/details");
  tile(view, "Andor").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  assert.equal(root.classList.contains("detailsloading"), false);
  await settle();
  answer(view, "cancel");
  await settle();
  assert.equal(reads(view, "/api/details"), read);
  view.clock.tick(60000);
  await ask();
  assert.equal(reads(view, "/api/details"), read + 1);
});

test("a press on a title's first answer that does not stay is the form's", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  row(view, "Kassa").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  const play = view.$("detailsPlay");
  // Kept from jsdom's form submission, which it does not carry out.
  play.addEventListener("click", (event) => event.preventDefault());
  play.click();
  assert.deepEqual(plays(view), []);
  answer(view, "cancel");
  await settle();
  // And with nothing open, the key answers nothing at all.
  play.click();
  assert.deepEqual(plays(view), []);
});

test("leaving the seasons goes back to the show's details they were opened over", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  await closeSeasons(view, { keep: true });
  assert.equal(seasonsOpen(view), false);
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsTitle").textContent, "Andor");
  assert.equal(view.$("detailsPlay").textContent, "Open");
  // And opening it again from there opens the seasons again.
  answer(view, "play");
  await settle();
  assert.equal(seasonsOpen(view), true);
  assert.equal(reads(view, "/api/episodes"), 2);
});

test("a pull closes seasons only; details stay open and scroll normally", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const seasons = view.$("seasonsDialog");
  const page = seasons.querySelector("form");
  pull(view, seasons, 100, 150);
  assert.equal(seasons.open, true);
  Object.defineProperty(page, "scrollTop", { configurable: true, value: 300 });
  pull(view, seasons, 100, 400);
  assert.equal(seasons.open, true);
  Object.defineProperty(page, "scrollTop", { configurable: true, value: 0 });
  pull(view, seasons, 100, 260);
  // It slides out first, then closes.
  assert.equal(seasons.classList.contains("away"), true);
  assert.equal(seasons.open, true);
  view.clock.tick(250);
  assert.equal(seasons.open, false);
  assert.equal(seasons.classList.contains("away"), false);

  const details = view.$("detailsDialog");
  details.open = true;
  pull(view, details, 50, 200);
  view.clock.tick(250);
  assert.equal(details.open, true);
});

test("a title's page slides in, and out by its key, Escape or a click beside it", async (t) => {
  const view = await open(t);
  const details = view.$("detailsDialog");
  const ask = async () => {
    tile(view, "Andor").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    await settle();
    assert.equal(details.open, true);
    assert.equal(details.classList.contains("away"), false);
  };
  const gone = () => {
    assert.equal(details.classList.contains("away"), true);
    view.clock.tick(250);
    assert.equal(details.open, false);
    details.dispatchEvent(new view.window.Event("close"));
  };

  await ask();
  const key = new view.window.MouseEvent("click", { bubbles: true, cancelable: true });
  view.$("detailsX").dispatchEvent(key);
  assert.equal(key.defaultPrevented, true);
  gone();

  await ask();
  details.dispatchEvent(new view.window.Event("cancel", { cancelable: true }));
  gone();

  await ask();
  const beside = (target, from) => {
    from.dispatchEvent(new view.window.PointerEvent("pointerdown", { bubbles: true }));
    target.dispatchEvent(new view.window.MouseEvent("click", { bubbles: true }));
  };
  // A press on the page itself, or one that began on it and ended beside it,
  // leaves it where it is.
  beside(view.$("detailsTitle"), view.$("detailsTitle"));
  beside(details, view.$("detailsTitle"));
  assert.equal(details.classList.contains("away"), false);
  beside(details, details);
  gone();
});

test("a show from the unwatched or the recent row opens the same dialog, without scrolling", async (t) => {
  const view = await open(t);
  view.$("seriesCard").open = false;
  await openShow(view, "Dark", "unseenSeriesGrid");
  assert.equal(view.requests.filter((request) => request.url === "/api/episodes?tvshowid=4").length, 1);
  assert.equal(view.$("seriesOpen").textContent, "Dark");
  assert.equal(seasonsOpen(view), true);
  assert.equal(view.$("seriesCard").open, false);

  await closeSeasons(view);
  await openShow(view, "Babylon 5", "recentSeriesRow");
  assert.equal(view.$("seriesOpen").textContent, "Babylon 5");
  assert.equal(seasonsOpen(view), true);
  assert.deepEqual(view.scrolled, []);
});

test("a show that cannot be opened says so, stays on the wall and has the shelf read again", async (t) => {
  const view = await open(t, { routes: { "/api/episodes": [500, {}] } });
  view.$("seriesCard").open = false;
  await openShow(view, "Andor", "unseenSeriesGrid");
  assert.equal(view.$("toast").textContent, "Episodes could not be loaded");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(seasonsOpen(view), false);
  assert.equal(hidden(view, "seriesGrid"), false);
  assert.equal(view.$("seriesCard").open, false);
  assert.deepEqual(view.scrolled, []);

  assert.equal(reads(view, "/api/series"), 1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
});

test("an answer without episodes opens an empty show, or empties the open one", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  view.routes["/api/episodes"] = [200, { episodes: "none" }];
  await view.moved();
  assert.equal(view.$("seriesOpen").textContent, "Andor");
  assert.equal(view.$("episodeList").children.length, 0);
  assert.equal(view.$("seasonsCount").textContent, "2022");

  await closeSeasons(view);
  await openShow(view, "Columbo");
  assert.equal(view.$("seriesOpen").textContent, "Columbo");
  assert.equal(seasonsOpen(view), true);
  assert.equal(view.$("episodeList").children.length, 0);
  assert.equal(view.$("seasonsCount").textContent, "");
});

test("a second show pressed while one is opening is not opened", async (t) => {
  const view = await open(t);
  const release = hold(view, "/api/episodes");
  await openShow(view, "Andor");
  await openShow(view, "Dark");
  await release();
  assert.equal(reads(view, "/api/episodes"), 1);
  assert.equal(view.$("seriesOpen").textContent, "Andor");
});

test("the shelf read again keeps the open show, under the name the shelf now gives it", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  view.routes["/api/series"] = [200, { tag: "s2", shows: [
    { ...SHOWS[0], title: "Andor (2022)" }, ...SHOWS.slice(1)] }];
  await view.moved();
  assert.equal(reads(view, "/api/series"), 2);
  assert.equal(view.$("seriesOpen").textContent, "Andor (2022)");
  assert.equal(seasonsOpen(view), true);
  assert.equal(view.$("seasonsCount").textContent, "2022 · 6 episodes");
  assert.equal(view.$("seriesCount").textContent, "4");
  assert.equal(titles(view, "seriesGrid")[0], "Andor (2022)");
});

test("a show scanned away under the dialog closes it", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  view.routes["/api/series"] = [200, { tag: "s2", shows: SHOWS.slice(1) }];
  await view.moved();
  assert.equal(seasonsOpen(view), false);
  assert.equal(view.$("episodeList").children.length, 0);
  assert.equal(hidden(view, "seriesGrid"), false);
  assert.equal(view.$("seriesCount").textContent, "3");
  assert.deepEqual(titles(view, "seriesGrid"), ["Babylon 5", "Columbo", "Dark"]);
});

test("the open show is read again in place when the library moves, its open seasons left open", async (t) => {
  const view = await open(t);
  await view.moved();
  // With no show open there is no list of episodes to read.
  assert.equal(reads(view, "/api/episodes"), 0);
  await openShow(view, "Andor");
  view.$("episodeList").querySelector('.seasonfold[data-season="1"]').open = true;
  view.routes["/api/episodes"] = [200, { tag: "e2", episodes: EPISODES.map((episode) =>
    (episode.id === 102 ? { ...episode, resume: 0, watched: true } : episode)) }];
  await view.moved();
  assert.equal(reads(view, "/api/episodes"), 2);
  assert.deepEqual(folds(view).map((fold) => [fold[0], fold[2]]),
                   [["Specials", false], ["Season 1", true], ["Season 2", false]]);
  const watched = row(view, "That Would Be Me");
  assert.ok(watched.querySelector(".filmseen"));
  assert.equal(watched.querySelector(".filmresume"), null);
});

test("the open show is not read twice at once", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const release = hold(view, "/api/episodes");
  await view.moved();
  await view.moved();
  assert.equal(reads(view, "/api/episodes"), 2);
  // The second move waits for the first read, then has its own.
  await release();
  await settle();
  assert.equal(reads(view, "/api/episodes"), 3);
});

test("an answer about a show that was left in the meantime draws nothing", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const release = hold(view, "/api/episodes");
  await view.moved();
  await closeSeasons(view);
  await release();
  assert.equal(view.$("episodeList").children.length, 0);
  assert.equal(seasonsOpen(view), false);
  assert.equal(view.$("seriesCount").textContent, "4");
});

test("a show that cannot be read again stays as it was, and the shelf is asked for again", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const before = rows(view);
  view.routes["/api/episodes"] = [500, {}];
  const release = hold(view, "/api/episodes");
  await view.moved();
  assert.equal(reads(view, "/api/series"), 2);
  await release();
  // The very same rows, not a list built again (deepEqual would take any
  // two elements as equal, so they are compared one by one).
  const after = rows(view);
  assert.equal(after.length, before.length);
  assert.ok(after.every((node, index) => node === before[index]));
  assert.equal(seasonsOpen(view), true);
  assert.equal(view.$("seriesOpen").textContent, "Andor");
  assert.equal(view.$("toast").textContent, "");
  // The shelf read that came back first is no longer taken as current.
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 3);
});

/** Which tab is in front. */
const front = (view) => view.window.document.querySelector(".tabpanel.active")?.dataset.tab;

test("an episode that starts closes the dialog and takes the page to the live tab", async (t) => {
  const view = await open(t);
  view.window.selectTab("series");
  await openShow(view, "Andor");
  await press(view, row(view, "That Would Be Me"));
  assert.equal(seasonsOpen(view), false);
  assert.equal(front(view), "live");
});

test("an episode that will not start leaves the dialog open on the series tab", async (t) => {
  const view = await open(t, { routes: { "/api/play": [500, {}] } });
  view.window.selectTab("series");
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  assert.equal(seasonsOpen(view), true);
  assert.equal(front(view), "series");
});

test("the series search and filters sit at the top of the tab", async (t) => {
  const view = await open(t);
  assert.equal(view.$("tab-series").firstElementChild, view.$("seriesSearchBox"));
  assert.equal(view.$("seriesCard").contains(view.$("seriesSearch")), false);
  assert.equal(view.$("seriesSearchBox").contains(view.$("seriesTools")), true);
});

test("playing an episode sends it with the token, and the list waits on it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  await openShow(view, "Andor");
  await press(view, row(view, "That Would Be Me"));
  const sent = view.requests.find((request) => request.url === "/api/play");
  assert.equal(sent.init.method, "POST");
  assert.equal(sent.init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent.init.headers["Content-Type"], "application/json");
  assert.deepEqual(plays(view), [{ episodeid: 102 }]);
  assert.equal(view.$("toast").textContent, "Starting…");
  assert.equal(row(view, "That Would Be Me").classList.contains("busy"), true);
  assert.equal(rows(view).every((node) => node.disabled), true);

  view.clock.tick(3999);
  assert.equal(rows(view).every((node) => node.disabled), true);
  view.clock.tick(1);
  assert.equal(rows(view).some((node) => node.disabled), false);
  assert.equal(row(view, "That Would Be Me").classList.contains("busy"), false);

  await press(view, row(view, "That Would Be Me"), "restart");
  assert.deepEqual(plays(view).at(-1), { episodeid: 102, resume: false });
});

test("an episode that comes on gives the list back at once", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  assert.equal(rows(view).every((node) => node.disabled), true);
  await view.state(PLAYING);
  assert.equal(rows(view).some((node) => node.disabled), false);
  assert.equal(row(view, "Kassa").classList.contains("busy"), false);
});

test("a refused token says so, asks for a new one and frees the list", async (t) => {
  const view = await open(t, { routes: { "/api/play": [401, {}] } });
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  assert.equal(view.$("toast").textContent, "Wrong or missing token");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(view.$("tokenDialog").open, true);
  assert.equal(rows(view).some((node) => node.disabled), false);
});

test("an episode the box will not play, or cannot be reached for, says so and frees the list", async (t) => {
  const view = await open(t, { routes: { "/api/play": [500, {}] } });
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(rows(view).some((node) => node.disabled), false);

  view.$("toast").textContent = "";
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (url === "/api/play"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  await press(view, row(view, "Kassa"));
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(rows(view).some((node) => node.disabled), false);
  assert.equal(view.$("tokenDialog").open, false);
});

test("under a pressed episode the shelf and the show wait; once it is over the shelf is read and the closed show let go", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const continued = reads(view, "/api/continue");
  await press(view, row(view, "Kassa"));
  await view.moved();
  assert.equal(reads(view, "/api/series"), 1);
  assert.equal(reads(view, "/api/episodes"), 1);
  assert.equal(reads(view, "/api/continue"), continued + 1);
  // The rows are still there, pressed, in the closed dialog.
  assert.equal(row(view, "Kassa").classList.contains("busy"), true);

  view.clock.tick(4000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
  assert.equal(reads(view, "/api/episodes"), 1);
  assert.equal(view.$("episodeList").children.length, 0);
});

test("no other show is opened while an episode is waiting", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  await openShow(view, "Dark", "unseenSeriesGrid");
  assert.equal(reads(view, "/api/episodes"), 1);
  assert.equal(view.$("seriesOpen").textContent, "Andor");
  assert.equal(seasonsOpen(view), false);

  // Not even once the dialog has been closed again.
  await closeSeasons(view);
  await openShow(view, "Dark", "unseenSeriesGrid");
  assert.equal(reads(view, "/api/episodes"), 1);
  assert.equal(seasonsOpen(view), false);
});

test("a second episode pressed while the first is waiting starts nothing", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  await press(view, row(view, "Kassa"));
  // A waiting list takes no press; a context-menu event that reaches a row all the same
  // (sent by a script, say) is dropped.
  assert.equal(row(view, "One Way Out").disabled, true);
  row(view, "One Way Out").dispatchEvent(new view.window.MouseEvent("contextmenu", { cancelable: true }));
  await settle();
  answer(view, "play");
  await settle();
  assert.deepEqual(plays(view), [{ episodeid: 101 }]);
});

test("a read of the show already on its way when an episode is pressed does not build the list under it", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const release = hold(view, "/api/episodes");
  view.routes["/api/episodes"] = [200, { tag: "e2", episodes: EPISODES.slice(1) }];
  await view.moved();
  await press(view, row(view, "Kassa"));
  const before = rows(view);
  await release();
  const after = rows(view);
  assert.equal(after.length, before.length);
  assert.ok(after.every((node, index) => node === before[index]));
  assert.equal(row(view, "One Way Out").disabled, true);
  assert.equal(row(view, "Kassa").classList.contains("busy"), true);

  // Once the press is over the answer put off is not asked for again: the
  // episode started, the dialog closed, and the show is let go instead.
  view.clock.tick(4000);
  await settle();
  assert.equal(reads(view, "/api/episodes"), 2);
  assert.equal(rows(view).length, 0);
});

test("a read put off under a press that failed is asked for again, the dialog still open", async (t) => {
  const view = await open(t, { routes: { "/api/play": [500, {}] } });
  await openShow(view, "Andor");
  const play = hold(view, "/api/play");
  view.routes["/api/episodes"] = [200, { tag: "e2", episodes: EPISODES.slice(1) }];
  await press(view, row(view, "Kassa"));
  await view.moved();
  assert.equal(reads(view, "/api/episodes"), 1);
  await play();
  await settle();
  assert.equal(reads(view, "/api/episodes"), 2);
  assert.equal(rows(view).length, EPISODES.length - 1);
  assert.equal(rows(view).some((node) => node.disabled), false);
});

test("a shelf read already on its way when an episode is pressed does not close the show under it", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  // The show is scanned away, and the shelf saying so is on its way.
  view.routes["/api/series"] = [200, { tag: "s2", shows: SHOWS.slice(1) }];
  const release = hold(view, "/api/series");
  await view.moved();
  await press(view, row(view, "Kassa"));
  await release();
  assert.equal(rows(view).length, EPISODES.length);
  assert.equal(row(view, "Kassa").classList.contains("busy"), true);
  assert.equal(titles(view, "seriesGrid").length, 4);

  view.clock.tick(4000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 3);
  assert.equal(view.$("episodeList").children.length, 0);
  assert.deepEqual(titles(view, "seriesGrid"), ["Babylon 5", "Columbo", "Dark"]);
});

test("a shelf put off under a press is asked for again when the press fails", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  view.routes["/api/series"] = [200, { tag: "s2", shows: SHOWS.slice(1) }];
  const shelf = hold(view, "/api/series");
  await view.moved();
  view.routes["/api/play"] = [500, {}];
  const play = hold(view, "/api/play");
  await press(view, row(view, "Kassa"));
  await shelf();
  assert.equal(seasonsOpen(view), true);
  // Nothing started, so only the move put off says the shelf is unread.
  await play();
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 3);
  assert.equal(seasonsOpen(view), false);
  assert.deepEqual(titles(view, "seriesGrid"), ["Babylon 5", "Columbo", "Dark"]);
});

test("a shelf that moves again while it is being read is read once more", async (t) => {
  const view = await open(t);
  const release = hold(view, "/api/series");
  await view.moved();
  view.routes["/api/series"] = [200, { tag: "s2", shows: SHOWS.slice(1) }];
  await view.moved();
  assert.equal(reads(view, "/api/series"), 2);
  await release();
  assert.equal(titles(view, "seriesGrid").length, 4);

  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 3);
  assert.deepEqual(titles(view, "seriesGrid"), ["Babylon 5", "Columbo", "Dark"]);
});

test("a shelf read that fails after the library moved leaves the wall standing", async (t) => {
  const view = await open(t);
  view.routes["/api/series"] = [500, {}];
  await view.moved();
  assert.equal(reads(view, "/api/series"), 2);
  for (const card of ["seriesCard", "recentSeriesCard", "unseenSeriesCard"]) {
    assert.equal(hidden(view, card), false, card);
  }
  assert.equal(titles(view, "seriesGrid").length, 4);

  // Still unread: once the wait is over it is asked for again.
  view.clock.tick(5000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 3);
});

test("the search stays where it is while a show is open, and keeps what it holds", async (t) => {
  const view = await open(t);
  const search = view.$("seriesSearch");
  search.value = "an";
  search.dispatchEvent(new view.window.Event("input"));
  await openShow(view, "Andor");
  assert.equal(hidden(view, "seriesSearchBox"), false);
  await closeSeasons(view);
  assert.equal(search.value, "an");
  assert.deepEqual(shown(view, "seriesGrid"), ["Andor"]);
});

test("the shelf is not asked for twice at once, nor again once read, until a title ends", async (t) => {
  const view = await open(t, { quiet: true });
  const release = hold(view, "/api/series");
  await view.state(IDLE);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 1);
  await release();
  assert.equal(titles(view, "seriesGrid").length, 4);

  await view.state(IDLE);
  await view.state(PLAYING);
  assert.equal(reads(view, "/api/series"), 1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
});

test("a shelf that comes without a tag is built once and then left as it is", async (t) => {
  const view = await open(t, { routes: { "/api/series": [200, { shows: SHOWS }] } });
  const andor = tile(view, "Andor");
  await view.state(PLAYING);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
  assert.equal(tile(view, "Andor"), andor);
});

test("a shelf read that fails hides walls never shown and waits before asking again", async (t) => {
  const view = await open(t, { routes: { "/api/series": [500, {}] } });
  for (const card of ["seriesCard", "recentSeriesCard", "unseenSeriesCard"]) {
    assert.equal(hidden(view, card), true, card);
  }
  view.clock.tick(4999);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 1);

  view.routes["/api/series"] = [200, { tag: "s1", shows: SHOWS }];
  view.clock.tick(1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
  assert.equal(hidden(view, "seriesCard"), false);
});

test("a shelf read that fails after the wall was shown leaves it standing", async (t) => {
  const view = await open(t);
  await view.state(PLAYING);
  view.routes["/api/series"] = [500, {}];
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 2);
  assert.equal(hidden(view, "seriesCard"), false);
  assert.equal(titles(view, "seriesGrid").length, 4);
});

test("a box that refuses the shelf is taken at its word and not asked again", async (t) => {
  const view = await open(t, { routes: { "/api/series": [403, {}] } });
  assert.equal(hidden(view, "seriesCard"), true);
  view.clock.tick(60000);
  await view.state(PLAYING);
  await view.state(IDLE);
  await view.moved();
  assert.equal(reads(view, "/api/series"), 1);
  assert.equal(view.$("tabbtn-series").classList.contains("hidden"), true);
});

test("a shelf read failing with no error at all still counts as a failure", async (t) => {
  const view = await open(t, { quiet: true });
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (String(url).startsWith("/api/series")
    ? Promise.reject(null) : fetch(url, init));
  await view.state(IDLE);
  assert.equal(hidden(view, "seriesCard"), true);
  view.window.fetch = fetch;
  view.clock.tick(5000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/series"), 1);
  assert.equal(titles(view, "seriesGrid").length, 4);
});

test("a move announced while the show is being read reads it once more", async (t) => {
  const view = await open(t);
  await openShow(view, "Andor");
  const release = hold(view, "/api/episodes");
  await view.moved();
  // The episode ends while the first read is out: its answer predates it.
  view.routes["/api/episodes"] = [200, { tag: "e2", episodes: EPISODES.slice(1) }];
  await view.moved();
  await release();
  await settle();
  assert.equal(reads(view, "/api/episodes"), 3);
  assert.equal(rows(view).length, EPISODES.length - 1);
});

test("a move announced while a show is being opened reads it once more", async (t) => {
  const view = await open(t);
  const release = hold(view, "/api/episodes");
  await openShow(view, "Andor");
  // The answer on its way was asked for before the episode ended.
  view.routes["/api/episodes"] = [200, { tag: "e2", episodes: EPISODES.slice(1) }];
  await view.moved();
  await release();
  await settle();
  assert.equal(reads(view, "/api/episodes"), 2);
  assert.equal(rows(view).length, EPISODES.length - 1);
});
