// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The film library tab (resources/web/js/films.js): the wall of posters and
// what each tile wears, the unwatched and recent rows, the search, when the
// list is read again and when it is not, and starting a film -- what is sent,
// how the wall waits on it and how it is given back.  The whole page is
// loaded in the order index.html gives, with its timers on a clock the test
// moves.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { page, settle, source } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");
const ORDER = ["theme.js", "core.js", "colour.js", "cover-tint.js", "readings.js",
               "live-remote.js", "live-panels.js", "metadata.js", "dashboard.js", "films.js", "series.js",
               "continue.js", "marking.js", "start.js"];

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

const FILMS = [
  { id: 1, title: "Alien", year: 1979, duration: 7020, watched: true, poster: "p1",
    rating: 8.5, rating_from: "imdb", added: "2026-09-01 10:00:00" },
  { id: 2, title: "Brazil", year: 1985, duration: 8520, resume: 1800, poster: "p 2",
    rating: 7.9, rating_from: "tmdb", added: "2026-09-03 10:00:00" },
  { id: 3, title: "Cube", duration: 5400, added: "2026-09-03 10:00:00" },
  { id: 4, title: "Dune", year: 2021, rating: 6, rating_from: "kinopoisk" },
  { id: 5, title: "Eraserhead", duration: 20, watched: true },
];

const IDLE = { playing: false, control: true };
const PLAYING = { playing: true, control: true };

/** The dashboard with *movies* on the film shelf and control allowed; the
 * first idle snapshot is delivered unless *quiet*.  The window is closed when
 * the test ends. */
async function open(t, { movies = FILMS, routes = {}, token = "", quiet = false } = {}) {
  const table = {
    "/api/hello": [200, { version: "2.15.0", strings: STRINGS }],
    "/api/library": [200, { tag: "f1", movies }],
    "/api/series": [200, { tag: "s1", shows: [] }],
    "/api/continue": [200, { tag: "c1", items: [] }],
    "/api/play": [200, {}],
    ...routes,
  };
  const view = page({ scripts: [], routes: table, token });
  const { window, dom } = view;
  t.after(() => window.close());
  const clock = fakeClock(window);
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  for (const name of ORDER) load(dom, name);
  await settle();
  let seq = 1;
  const result = {
    ...view, routes: table, clock,
    $: (id) => window.document.getElementById(id),
    async state(snapshot) {
      seq += 1;
      view.streams.at(-1).emit("state", { ...snapshot, seq });
      await settle();
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

/** The tiles in the row or wall *id*. */
const tiles = (view, id) => [...view.$(id).children];
const titles = (view, id) => tiles(view, id)
  .map((node) => node.querySelector(".filmtitle").textContent);
const shown = (view, id) => tiles(view, id).filter((node) => !node.hidden)
  .map((node) => node.querySelector(".filmtitle").textContent);
const hidden = (view, id) => view.$(id).classList.contains("hidden");

/** The wall's tile for the film called *title*. */
function tile(view, title, id = "filmGrid") {
  const found = tiles(view, id)
    .find((node) => node.querySelector(".filmtitle").textContent === title);
  assert.ok(found, title);
  return found;
}

/** Answer the question that is open, as the dialog's form would. */
function answer({ window, $ }, value) {
  const dialog = $("markDialog");
  dialog.returnValue = value;
  dialog.close();
  dialog.dispatchEvent(new window.Event("close"));
}

/** Press the film called *title* and give *value* as the answer. */
async function press(view, title, value = "play") {
  tile(view, title).click();
  answer(view, value);
  await settle();
}

const reads = ({ requests }, path) =>
  requests.filter((request) => request.url.replace(/\?.*$/, "") === path).length;

const plays = ({ requests }) => requests
  .filter((request) => request.url === "/api/play")
  .map((request) => JSON.parse(request.init.body));

/** Every film tile on the page, on any of the three rows. */
const everyTile = (view) => ["filmGrid", "unseenFilmGrid", "recentFilmsRow"]
  .flatMap((id) => tiles(view, id));

test("the wall holds every film, with its poster, rating, tick and the line under it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  assert.deepEqual(titles(view, "filmGrid"), ["Alien", "Brazil", "Cube", "Dune", "Eraserhead"]);
  assert.equal(hidden(view, "filmsCard"), false);
  assert.equal(view.$("filmsCount").textContent, "5");
  assert.equal(hidden(view, "filmsEmpty"), true);

  const alien = tile(view, "Alien");
  assert.equal(alien.type, "button");
  assert.equal(alien.dataset.key, "alien 1979");
  const poster = alien.querySelector(".filmposter img");
  assert.equal(poster.getAttribute("src"), "/api/art?kind=poster&movieid=1&v=p1");
  assert.equal(poster.alt, "");
  assert.equal(poster.loading, "lazy");
  const rating = alien.querySelector(".filmrating");
  assert.equal(rating.textContent, "8.5");
  assert.equal(rating.getAttribute("role"), "img");
  assert.equal(rating.getAttribute("aria-label"), "IMDb 8.5");
  assert.equal(rating.title, "IMDb 8.5");
  const seen = alien.querySelector(".filmseen");
  assert.equal(seen.getAttribute("aria-label"), "Watched");
  assert.equal(seen.title, "Watched");
  assert.equal(alien.querySelector(".filmresume"), null);
  assert.equal(alien.querySelector(".filmyear").textContent, "1979 · 1 h 57 min");

  // The poster's tag is passed along as it is, escaped for the address.
  const brazil = tile(view, "Brazil");
  assert.equal(brazil.querySelector("img").getAttribute("src"),
               "/api/art?kind=poster&movieid=2&v=p%202");
  assert.equal(brazil.querySelector(".filmrating").getAttribute("aria-label"), "TMDb 7.9");
  assert.equal(brazil.querySelector(".filmseen"), null);

  // No poster, no rating, no year: an empty frame and the running time alone.
  const cube = tile(view, "Cube");
  assert.equal(cube.dataset.key, "cube ");
  assert.equal(cube.querySelector(".filmposter").children.length, 0);
  assert.equal(cube.querySelector(".filmyear").textContent, "1 h 30 min");

  // A house the badge has no name for is left unnamed.
  const dune = tile(view, "Dune");
  assert.equal(dune.querySelector(".filmrating").textContent, "6.0");
  assert.equal(dune.querySelector(".filmrating").getAttribute("aria-label"), "6.0");
  assert.equal(dune.querySelector(".filmyear").textContent, "2021");

  // Twenty seconds is no whole minute, and a line with nothing on it is left out.
  assert.equal(tile(view, "Eraserhead").querySelector(".filmyear"), null);
});

test("running times split out the hours and leave out what is not there", async (t) => {
  const view = await open(t, { movies: [
    { id: 1, title: "Short", duration: 2700 },
    { id: 2, title: "Round", duration: 7200 },
    { id: 3, title: "Long", duration: 11880 },
    { id: 4, title: "Unknown", year: 1999 },
    { id: 5, title: "Rounded", duration: 89 },
  ] });
  const line = (title) => tile(view, title).querySelector(".filmyear").textContent;
  assert.equal(line("Short"), "45 min");
  assert.equal(line("Round"), "2 h");
  assert.equal(line("Long"), "3 h 18 min");
  assert.equal(line("Unknown"), "1999");
  assert.equal(line("Rounded"), "1 min");
});

test("the resume bar shows how far in, never less than a sliver nor more than full", async (t) => {
  const view = await open(t, { movies: [
    { id: 1, title: "Begun", duration: 10000, resume: 10 },
    { id: 2, title: "Half", duration: 7200, resume: 3600 },
    { id: 3, title: "Over", duration: 100, resume: 150 },
    { id: 4, title: "Untimed", resume: 600 },
  ] });
  const bar = (title) => tile(view, title).querySelector(".filmresume");
  assert.equal(bar("Begun").querySelector("span").style.width, "2%");
  assert.equal(bar("Half").querySelector("span").style.width, "50%");
  assert.equal(bar("Half").title, "Resume");
  assert.equal(bar("Over").querySelector("span").style.width, "100%");
  // Without a length there is nothing to measure the point against.
  assert.equal(bar("Untimed"), null);
});

test("a poster the box cannot read leaves the empty frame behind", async (t) => {
  const view = await open(t);
  const frame = tile(view, "Alien").querySelector(".filmposter");
  frame.querySelector("img").dispatchEvent(new view.window.Event("error"));
  assert.equal(frame.querySelector("img"), null);
  // The badge and the tick stay on the frame.
  assert.ok(frame.querySelector(".filmrating"));
  assert.ok(frame.querySelector(".filmseen"));
});

test("the unwatched row holds every film not yet seen, and says how many", async (t) => {
  const view = await open(t);
  assert.deepEqual(titles(view, "unseenFilmGrid"), ["Brazil", "Cube", "Dune"]);
  assert.equal(view.$("unseenFilmsCount").textContent, "3");
  assert.equal(hidden(view, "unseenFilmsCard"), false);
  // Tiles of their own, not the wall's moved.
  assert.notEqual(tile(view, "Brazil", "unseenFilmGrid"), tile(view, "Brazil"));
  assert.equal(titles(view, "filmGrid").length, 5);
});

test("with everything seen the unwatched row goes away and its count is blank", async (t) => {
  const view = await open(t, { movies: FILMS.map((film) => ({ ...film, watched: true })) });
  assert.deepEqual(titles(view, "unseenFilmGrid"), []);
  assert.equal(view.$("unseenFilmsCount").textContent, "");
  assert.equal(hidden(view, "unseenFilmsCard"), true);
});

test("the recent row is the ten that arrived last, newest first, a tie going to the later id", async (t) => {
  const movies = [];
  for (let id = 1; id <= 12; id++) {
    movies.push({ id, title: `Film ${String(id).padStart(2, "0")}`,
                  added: `2026-09-${String(id).padStart(2, "0")} 10:00:00` });
  }
  // A batch scanned in the same second, and a film from an add-on with no date.
  movies.push({ id: 13, title: "Same second A", added: "2026-09-12 10:00:00" });
  movies.push({ id: 14, title: "Same second B", added: "2026-09-12 10:00:00" });
  movies.push({ id: 15, title: "Undated" });
  const view = await open(t, { movies });
  assert.deepEqual(titles(view, "recentFilmsRow"), [
    "Same second B", "Same second A", "Film 12", "Film 11", "Film 10", "Film 09",
    "Film 08", "Film 07", "Film 06", "Film 05"]);
  assert.equal(hidden(view, "recentFilmsCard"), false);
});

test("a library that sends no dates has no recent row", async (t) => {
  const view = await open(t, { movies: [{ id: 1, title: "Old" }, { id: 2, title: "Older" }] });
  assert.deepEqual(titles(view, "recentFilmsRow"), []);
  assert.equal(hidden(view, "recentFilmsCard"), true);
});

test("an empty library, or an answer without a list, says there is nothing", async (t) => {
  const view = await open(t, { movies: [] });
  assert.equal(hidden(view, "filmsCard"), false);
  assert.equal(view.$("filmsCount").textContent, "0");
  assert.equal(hidden(view, "filmsEmpty"), false);
  assert.equal(hidden(view, "recentFilmsCard"), true);
  assert.equal(hidden(view, "unseenFilmsCard"), true);

  const other = await open(t, { routes: { "/api/library": [200, { movies: "none" }] } });
  assert.deepEqual(titles(other, "filmGrid"), []);
  assert.equal(other.$("filmsCount").textContent, "0");
  assert.equal(hidden(other, "filmsEmpty"), false);
});

test("the search narrows the wall by title and year and says how many of how many", async (t) => {
  const view = await open(t);
  const search = view.$("filmSearch");
  assert.equal(hidden(view, "filmSearchClear"), true);

  search.value = "19";
  search.dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "filmGrid"), ["Alien", "Brazil"]);
  assert.equal(view.$("filmsCount").textContent, "2 / 5");
  assert.equal(hidden(view, "filmSearchClear"), false);
  assert.equal(hidden(view, "filmsEmpty"), true);

  // Case and the spaces around it do not matter.
  search.value = "  CUBE ";
  search.dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "filmGrid"), ["Cube"]);
  assert.equal(view.$("filmsCount").textContent, "1 / 5");

  search.value = "zzz";
  search.dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "filmGrid"), []);
  assert.equal(view.$("filmsCount").textContent, "0 / 5");
  assert.equal(hidden(view, "filmsEmpty"), false);

  // Only the wall of everything is searched: the two rows stay whole.
  assert.equal(tiles(view, "unseenFilmGrid").every((node) => !node.hidden), true);
});

test("clearing the search puts the whole shelf back and the cursor in the box", async (t) => {
  const view = await open(t);
  const search = view.$("filmSearch");
  search.value = "dune";
  search.dispatchEvent(new view.window.Event("input"));
  view.$("filmSearchClear").click();
  assert.equal(search.value, "");
  assert.equal(shown(view, "filmGrid").length, 5);
  assert.equal(view.$("filmsCount").textContent, "5");
  assert.equal(hidden(view, "filmSearchClear"), true);
  assert.equal(view.window.document.activeElement, search);
});

test("a list read again with the tag it had leaves the wall and the search alone", async (t) => {
  const view = await open(t);
  const alien = tile(view, "Alien");
  const search = view.$("filmSearch");
  search.value = "alien";
  search.dispatchEvent(new view.window.Event("input"));

  // The add-on's library number moves: the list is read again, and is the same.
  await view.state({ ...IDLE, library: 1 });
  await view.state({ ...IDLE, library: 2 });
  assert.equal(reads(view, "/api/library"), 2);
  assert.equal(tile(view, "Alien"), alien);
  assert.deepEqual(shown(view, "filmGrid"), ["Alien"]);

  // A new tag is a new list: the wall is built again, under the same search.
  view.routes["/api/library"] = [200, { tag: "f2", movies: [
    ...FILMS, { id: 6, title: "Alien Resurrection", year: 1997 }] }];
  await view.state({ ...IDLE, library: 3 });
  assert.equal(reads(view, "/api/library"), 3);
  assert.notEqual(tile(view, "Alien"), alien);
  assert.deepEqual(shown(view, "filmGrid"), ["Alien", "Alien Resurrection"]);
  assert.equal(view.$("filmsCount").textContent, "2 / 6");
});

test("a list that comes without a tag is built once and then left as it is", async (t) => {
  const view = await open(t, { routes: { "/api/library": [200, { movies: FILMS }] } });
  const alien = tile(view, "Alien");
  await view.state(PLAYING);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 2);
  assert.equal(tile(view, "Alien"), alien);
});

test("a list is not asked for twice at once, nor again once read, until a film ends", async (t) => {
  const view = await open(t, { quiet: true });
  const release = hold(view, "/api/library");
  await view.state(IDLE);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 1);
  assert.deepEqual(titles(view, "filmGrid"), []);
  await release();
  assert.equal(titles(view, "filmGrid").length, 5);

  await view.state(IDLE);
  await view.state(PLAYING);
  assert.equal(reads(view, "/api/library"), 1);
  // The film has ended: what was watched, and how far, has moved.
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 2);
});

test("a read that fails hides walls never shown and waits before asking again", async (t) => {
  const view = await open(t, { routes: { "/api/library": [500, {}] } });
  assert.equal(reads(view, "/api/library"), 1);
  for (const card of ["filmsCard", "recentFilmsCard", "unseenFilmsCard"]) {
    assert.equal(hidden(view, card), true, card);
  }
  await view.state(IDLE);
  view.clock.tick(4999);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 1);

  view.routes["/api/library"] = [200, { tag: "f1", movies: FILMS }];
  view.clock.tick(1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 2);
  assert.equal(hidden(view, "filmsCard"), false);
  assert.equal(titles(view, "filmGrid").length, 5);
});

test("a read that fails after the wall was shown leaves it standing", async (t) => {
  const view = await open(t);
  await view.state(PLAYING);
  view.routes["/api/library"] = [500, {}];
  // The film has ended, and the list it was read from is asked for again.
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 2);
  assert.equal(hidden(view, "filmsCard"), false);
  assert.equal(hidden(view, "unseenFilmsCard"), false);
  assert.equal(titles(view, "filmGrid").length, 5);
});

test("a box that refuses the library is taken at its word and not asked again", async (t) => {
  const view = await open(t, { routes: { "/api/library": [403, {}] } });
  assert.equal(hidden(view, "filmsCard"), true);
  view.clock.tick(60000);
  await view.state(PLAYING);
  await view.state({ ...IDLE, library: 5 });
  await view.state({ ...IDLE, library: 6 });
  assert.equal(reads(view, "/api/library"), 1);
  // The tab goes with it.
  assert.equal(view.$("tabbtn-films").classList.contains("hidden"), true);
});

test("a failure that carries no error at all still counts as a failure", async (t) => {
  const view = await open(t, { quiet: true });
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (String(url).startsWith("/api/library")
    ? Promise.reject(undefined) : fetch(url, init));
  await view.state(IDLE);
  assert.equal(hidden(view, "filmsCard"), true);

  // Not a refusal: once the wait is over the list is asked for again.
  view.window.fetch = fetch;
  view.clock.tick(5000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 1);
  assert.equal(titles(view, "filmGrid").length, 5);
});

test("a press asks to play a film, or to resume one that got somewhere", async (t) => {
  const view = await open(t);
  tile(view, "Alien").click();
  assert.equal(view.$("markDialog").open, true);
  assert.equal(view.$("markTitle").textContent, "Alien");
  assert.equal(view.$("markPlay").textContent, "Play");
  assert.equal(view.$("markRestart").hidden, true);
  answer(view, "cancel");

  tile(view, "Brazil", "unseenFilmGrid").click();
  assert.equal(view.$("markTitle").textContent, "Brazil");
  assert.equal(view.$("markPlay").textContent, "Resume");
  assert.equal(view.$("markRestart").hidden, false);
  answer(view, "cancel");
  await settle();
  assert.deepEqual(plays(view), []);
});

test("playing sends the film with the token, and every wall waits on it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  await press(view, "Brazil");
  const sent = view.requests.find((request) => request.url === "/api/play");
  assert.equal(sent.init.method, "POST");
  assert.equal(sent.init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent.init.headers["Content-Type"], "application/json");
  assert.deepEqual(plays(view), [{ movieid: 2 }]);
  assert.equal(view.$("toast").textContent, "Starting…");
  assert.equal(view.$("toast").classList.contains("bad"), false);

  assert.equal(tile(view, "Brazil").classList.contains("busy"), true);
  assert.equal(everyTile(view).every((node) => node.disabled), true);

  // A film that never comes on gives the walls back after a while.
  view.clock.tick(3999);
  assert.equal(everyTile(view).every((node) => node.disabled), true);
  view.clock.tick(1);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(tile(view, "Brazil").classList.contains("busy"), false);
});

test("play from the start says so", async (t) => {
  const view = await open(t);
  await press(view, "Brazil", "restart");
  assert.deepEqual(plays(view), [{ movieid: 2, resume: false }]);
});

test("a film that comes on gives the walls back at once", async (t) => {
  const view = await open(t);
  await press(view, "Alien");
  assert.equal(everyTile(view).every((node) => node.disabled), true);
  await view.state(PLAYING);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(tile(view, "Alien").classList.contains("busy"), false);
});

test("a refused token says so, asks for a new one and frees the walls", async (t) => {
  const view = await open(t, { routes: { "/api/play": [401, {}] } });
  await press(view, "Alien");
  assert.equal(view.$("toast").textContent, "Wrong or missing token");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(view.$("tokenDialog").open, true);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(tile(view, "Alien").classList.contains("busy"), false);
});

test("a box that will not play it, or cannot be reached, says so and frees the walls", async (t) => {
  const view = await open(t, { routes: { "/api/play": [500, {}] } });
  await press(view, "Dune");
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(everyTile(view).some((node) => node.disabled), false);

  view.$("toast").textContent = "";
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (url === "/api/play"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  await press(view, "Cube");
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(view.$("tokenDialog").open, false);
});

test("the wall is not read again under a pressed tile, and is once the press is over", async (t) => {
  const view = await open(t);
  const continued = reads(view, "/api/continue");
  await press(view, "Brazil");
  // Where the box got to has moved: the wall and the continue row are stale.
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 1);
  assert.equal(reads(view, "/api/continue"), continued + 1);
  assert.equal(tile(view, "Brazil").classList.contains("busy"), true);

  view.clock.tick(4000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 2);
});

test("a second film pressed while the first is waiting starts nothing", async (t) => {
  const view = await open(t);
  await press(view, "Alien");
  // A waiting wall takes no press; a click that reaches a tile all the same
  // (sent by a script, say) is dropped.
  assert.equal(tile(view, "Dune").disabled, true);
  tile(view, "Dune").dispatchEvent(new view.window.MouseEvent("click"));
  answer(view, "play");
  await settle();
  assert.deepEqual(plays(view), [{ movieid: 1 }]);
});

test("a read already on its way when a tile is pressed does not build the wall under it", async (t) => {
  const view = await open(t);
  await view.state({ ...IDLE, library: 1 });
  const release = hold(view, "/api/library");
  view.routes["/api/library"] = [200, { tag: "f2", movies: FILMS }];
  await view.state({ ...IDLE, library: 2 });
  await press(view, "Alien");
  const dune = tile(view, "Dune");
  await release();
  assert.equal(tile(view, "Dune"), dune);
  assert.equal(dune.disabled, true);
  assert.equal(tile(view, "Alien").classList.contains("busy"), true);

  // The answer that was put off is asked for again once the press is over.
  view.clock.tick(4000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/library"), 3);
  assert.notEqual(tile(view, "Dune"), dune);
  assert.equal(tile(view, "Dune").disabled, false);
});

test("an answer put off under a press is asked for again when the press fails", async (t) => {
  const view = await open(t);
  await view.state({ ...IDLE, library: 1 });
  const library = hold(view, "/api/library");
  view.routes["/api/library"] = [200, { tag: "f2", movies: FILMS.slice(1) }];
  await view.state({ ...IDLE, library: 2 });
  view.routes["/api/play"] = [500, {}];
  const play = hold(view, "/api/play");
  await press(view, "Alien");
  await library();
  assert.equal(titles(view, "filmGrid").length, 5);
  // Nothing started, so only the move put off says the wall is unread.
  await play();
  assert.equal(tile(view, "Dune").disabled, false);
  await view.state({ ...IDLE, library: 2 });
  assert.equal(reads(view, "/api/library"), 3);
  assert.deepEqual(titles(view, "filmGrid"), ["Brazil", "Cube", "Dune", "Eraserhead"]);
});

test("a library that moves again while it is being read is read once more", async (t) => {
  const view = await open(t);
  await view.state({ ...IDLE, library: 1 });
  const release = hold(view, "/api/library");
  await view.state({ ...IDLE, library: 2 });
  view.routes["/api/library"] = [200, { tag: "f2", movies: FILMS.slice(1) }];
  await view.state({ ...IDLE, library: 3 });
  assert.equal(reads(view, "/api/library"), 2);
  await release();
  assert.equal(titles(view, "filmGrid").length, 5);

  await view.state({ ...IDLE, library: 3 });
  assert.equal(reads(view, "/api/library"), 3);
  assert.deepEqual(titles(view, "filmGrid"), ["Brazil", "Cube", "Dune", "Eraserhead"]);
});

test("a read that fails after the library moved leaves the wall standing", async (t) => {
  const view = await open(t);
  await view.state({ ...IDLE, library: 1 });
  view.routes["/api/library"] = [500, {}];
  await view.state({ ...IDLE, library: 2 });
  assert.equal(reads(view, "/api/library"), 2);
  for (const card of ["filmsCard", "recentFilmsCard", "unseenFilmsCard"]) {
    assert.equal(hidden(view, card), false, card);
  }
  assert.equal(titles(view, "filmGrid").length, 5);

  // Still unread: once the wait is over it is asked for again.
  view.clock.tick(5000);
  await view.state({ ...IDLE, library: 2 });
  assert.equal(reads(view, "/api/library"), 3);
});
