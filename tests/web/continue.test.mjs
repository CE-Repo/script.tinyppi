// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The "continue watching" rows (resources/web/js/continue.js): one list from
// the box drawn as a films row and an episodes row, what each tile wears,
// when the list is read again and when it is not, and resuming a title --
// what is sent, how the rows wait on it and which shelf is read again after.
// The whole page is loaded in the order index.html gives, with its timers on
// a clock the test moves.

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

const ITEMS = [
  { kind: "movie", id: 3, title: "Film 03", year: 2003, duration: 7200, resume: 1800,
    poster: "f 3", rating: 6.5, rating_from: "imdb" },
  { kind: "episode", id: 99, title: "Started", show: "Show 2", season: 1, episode: 3,
    duration: 1000, resume: 100, poster: "s2", rating: 7.2, rating_from: "tmdb" },
  { kind: "episode", id: 98, title: "Pilot", season: 2, episode: 1, resume: 5 },
  { kind: "movie", id: 4, title: "Film 04", resume: 30 },
];

const IDLE = { playing: false, control: true };
const PLAYING = { playing: true, control: true };

/** The dashboard with *items* on the continue row and control allowed; the
 * first idle snapshot is delivered unless *quiet*.  The window is closed when
 * the test ends. */
async function open(t, { items = ITEMS, routes = {}, token = "", quiet = false } = {}) {
  const table = {
    "/api/hello": [200, { version: "2.15.0", strings: STRINGS }],
    "/api/library": [200, { tag: "f1", movies: [] }],
    "/api/series": [200, { tag: "s1", shows: [] }],
    "/api/continue": [200, { tag: "c1", items }],
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
  let seq = 0;
  let library = 0;
  const result = {
    ...view, routes: table, clock,
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

const ROWS = ["continueFilmsRow", "continueSeriesRow"];
const tiles = (view, id) => [...view.$(id).children];
const titles = (view, id) => tiles(view, id)
  .map((node) => node.querySelector(".filmtitle").textContent);
const hidden = (view, id) => view.$(id).classList.contains("hidden");
const everyTile = (view) => ROWS.flatMap((id) => tiles(view, id));

/** The tile called *title* on either row. */
function tile(view, title) {
  const found = everyTile(view)
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

/** Press the tile called *title* and give *value* as the answer. */
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

test("one list is drawn as two rows, the films and the episodes, each with its count", async (t) => {
  const view = await open(t);
  assert.deepEqual(titles(view, "continueFilmsRow"), ["Film 03", "Film 04"]);
  assert.deepEqual(titles(view, "continueSeriesRow"), ["Show 2", "Pilot"]);
  assert.equal(view.$("continueFilmsCount").textContent, "2");
  assert.equal(view.$("continueSeriesCount").textContent, "2");
  assert.equal(hidden(view, "continueFilmsCard"), false);
  assert.equal(hidden(view, "continueSeriesCard"), false);
});

test("a film's tile wears its poster, rating, resume bar and the line under it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  const film = tile(view, "Film 03");
  assert.equal(film.type, "button");
  const poster = film.querySelector(".filmposter img");
  assert.equal(poster.getAttribute("src"), "/api/art?kind=poster&movieid=3&v=f%203");
  assert.equal(poster.alt, "");
  assert.equal(film.querySelector(".filmrating").getAttribute("aria-label"), "IMDb 6.5");
  const bar = film.querySelector(".filmresume");
  assert.equal(bar.title, "Resume");
  assert.equal(bar.querySelector("span").style.width, "25%");
  const line = film.querySelector(".filmyear");
  assert.equal(line.textContent, "2003 · 2 h");
  assert.equal(line.title, "2003 · 2 h");

  // Nothing known but the title and where it got to: an empty frame, no bar
  // without a length to measure it against, and no line.
  const bare = tile(view, "Film 04");
  assert.equal(bare.querySelector(".filmposter").children.length, 0);
  assert.equal(bare.querySelector(".filmyear"), null);
});

test("an episode stands on its show's poster and name, with which episode under it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  const episode = tile(view, "Show 2");
  assert.equal(episode.querySelector("img").getAttribute("src"),
               "/api/art?kind=poster&episodeid=99&v=s2");
  assert.equal(episode.querySelector(".filmrating").getAttribute("aria-label"), "TMDb 7.2");
  assert.equal(episode.querySelector(".filmresume span").style.width, "10%");
  const line = episode.querySelector(".filmyear");
  assert.equal(line.textContent, "S01E03 · Started");
  assert.equal(line.title, "S01E03 · Started");

  // Without the show's name the episode goes by its own, and is not named twice.
  const pilot = tile(view, "Pilot");
  assert.equal(pilot.querySelector(".filmyear").textContent, "S02E01");
  assert.equal(pilot.querySelector(".filmresume"), null);
});

test("an episode with neither number nor show has no line under it", async (t) => {
  const view = await open(t, { items: [{ kind: "episode", id: 97, title: "Loose" }] });
  assert.equal(tile(view, "Loose").querySelector(".filmyear"), null);
  assert.equal(hidden(view, "continueFilmsCard"), true);
});

test("a poster the box cannot read leaves the empty frame behind", async (t) => {
  const view = await open(t);
  const frame = tile(view, "Show 2").querySelector(".filmposter");
  frame.querySelector("img").dispatchEvent(new view.window.Event("error"));
  assert.equal(frame.querySelector("img"), null);
  assert.ok(frame.querySelector(".filmrating"));
});

test("a row with nothing on it is no card at all, and its count is blank", async (t) => {
  const films = await open(t, { items: ITEMS.filter((item) => item.kind === "movie") });
  assert.equal(hidden(films, "continueFilmsCard"), false);
  assert.equal(hidden(films, "continueSeriesCard"), true);
  assert.equal(films.$("continueSeriesCount").textContent, "");

  const none = await open(t, { items: [] });
  assert.equal(hidden(none, "continueFilmsCard"), true);
  assert.equal(hidden(none, "continueSeriesCard"), true);
  assert.equal(none.$("continueFilmsCount").textContent, "");
  // Read again with the same tag and still nothing on it: still no cards.
  await none.moved();
  assert.equal(reads(none, "/api/continue"), 2);
  assert.equal(hidden(none, "continueFilmsCard"), true);

  const broken = await open(t, { routes: { "/api/continue": [200, { tag: "c1", items: {} }] } });
  assert.deepEqual(everyTile(broken), []);
  assert.equal(hidden(broken, "continueSeriesCard"), true);
});

test("a press asks to resume, and offers a fresh start and forgetting the point", async (t) => {
  const view = await open(t);
  tile(view, "Film 03").click();
  assert.equal(view.$("markDialog").open, true);
  assert.equal(view.$("markTitle").textContent, "Film 03");
  assert.equal(view.$("markPlay").textContent, "Resume");
  assert.equal(view.$("markRestart").hidden, false);
  assert.equal(view.$("markClear").hidden, false);
  answer(view, "cancel");

  tile(view, "Show 2").click();
  assert.equal(view.$("markTitle").textContent, "Show 2 · S01E03");
  answer(view, "cancel");
  tile(view, "Pilot").click();
  assert.equal(view.$("markTitle").textContent, "S02E01");
  answer(view, "cancel");
  await settle();
  assert.deepEqual(plays(view), []);
});

test("resuming sends the title with the token, and both rows wait on it", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  await press(view, "Film 03");
  const sent = view.requests.find((request) => request.url === "/api/play");
  assert.equal(sent.init.method, "POST");
  assert.equal(sent.init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent.init.headers["Content-Type"], "application/json");
  assert.deepEqual(plays(view), [{ movieid: 3 }]);
  assert.equal(view.$("toast").textContent, "Starting…");
  assert.equal(view.$("toast").classList.contains("bad"), false);
  assert.equal(tile(view, "Film 03").classList.contains("busy"), true);
  assert.equal(everyTile(view).every((node) => node.disabled), true);

  view.clock.tick(3999);
  assert.equal(everyTile(view).every((node) => node.disabled), true);
  view.clock.tick(1);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(tile(view, "Film 03").classList.contains("busy"), false);

  // From the start, for an episode.
  await press(view, "Show 2", "restart");
  assert.deepEqual(plays(view).at(-1), { episodeid: 99, resume: false });
});

test("a title that comes on gives the rows back at once", async (t) => {
  const view = await open(t);
  await press(view, "Show 2");
  assert.equal(everyTile(view).every((node) => node.disabled), true);
  await view.state(PLAYING);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(tile(view, "Show 2").classList.contains("busy"), false);
});

test("a refused token says so, asks for a new one and frees the rows", async (t) => {
  const view = await open(t, { routes: { "/api/play": [401, {}] } });
  await press(view, "Film 03");
  assert.equal(view.$("toast").textContent, "Wrong or missing token");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(view.$("tokenDialog").open, true);
  assert.equal(everyTile(view).some((node) => node.disabled), false);
});

test("a title the box will not play, or cannot be reached for, says so and frees the rows", async (t) => {
  const view = await open(t, { routes: { "/api/play": [500, {}] } });
  await press(view, "Pilot");
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(everyTile(view).some((node) => node.disabled), false);

  view.$("toast").textContent = "";
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (url === "/api/play"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  await press(view, "Film 04");
  assert.equal(view.$("toast").textContent, "Playback could not be started");
  assert.equal(everyTile(view).some((node) => node.disabled), false);
  assert.equal(view.$("tokenDialog").open, false);
});

test("a resumed film has the films wall read again, a resumed episode the series shelf", async (t) => {
  const view = await open(t);
  const counts = () => [reads(view, "/api/library"), reads(view, "/api/series"),
                        reads(view, "/api/continue")];
  assert.deepEqual(counts(), [1, 1, 1]);
  await press(view, "Film 03");
  // The row itself waits for the press to be over.
  await view.state(IDLE);
  assert.deepEqual(counts(), [2, 1, 1]);
  view.clock.tick(4000);
  await view.state(IDLE);
  assert.deepEqual(counts(), [2, 1, 2]);

  await press(view, "Show 2");
  view.clock.tick(4000);
  await view.state(IDLE);
  assert.deepEqual(counts(), [2, 2, 3]);
});

test("the row is not asked for twice at once, nor again once read, until a title ends", async (t) => {
  const view = await open(t, { quiet: true });
  const release = hold(view, "/api/continue");
  await view.state(IDLE);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 1);
  await release();
  assert.equal(everyTile(view).length, 4);

  await view.state(IDLE);
  await view.state(PLAYING);
  assert.equal(reads(view, "/api/continue"), 1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 2);
});

test("a row read again with the tag it had is left as it is, a new tag builds it again", async (t) => {
  const view = await open(t);
  const film = tile(view, "Film 03");
  await view.moved();
  assert.equal(reads(view, "/api/continue"), 2);
  assert.equal(tile(view, "Film 03"), film);

  view.routes["/api/continue"] = [200, { tag: "c2", items: ITEMS.slice(1) }];
  await view.moved();
  assert.deepEqual(titles(view, "continueFilmsRow"), ["Film 04"]);
  assert.equal(view.$("continueFilmsCount").textContent, "1");
});

test("a row that comes without a tag is built once and then left as it is", async (t) => {
  const view = await open(t, { routes: { "/api/continue": [200, { items: ITEMS }] } });
  const film = tile(view, "Film 03");
  await view.moved();
  assert.equal(reads(view, "/api/continue"), 2);
  assert.equal(tile(view, "Film 03"), film);
});

test("a read that fails hides rows never shown and waits before asking again", async (t) => {
  const view = await open(t, { routes: { "/api/continue": [500, {}] } });
  assert.equal(hidden(view, "continueFilmsCard"), true);
  assert.equal(hidden(view, "continueSeriesCard"), true);
  view.clock.tick(4999);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 1);

  view.routes["/api/continue"] = [200, { tag: "c1", items: ITEMS }];
  view.clock.tick(1);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 2);
  assert.equal(hidden(view, "continueFilmsCard"), false);
});

test("a read that fails after the rows were shown leaves them standing", async (t) => {
  const view = await open(t);
  await view.state(PLAYING);
  view.routes["/api/continue"] = [500, {}];
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 2);
  assert.equal(hidden(view, "continueFilmsCard"), false);
  assert.equal(everyTile(view).length, 4);
});

test("a box with no shelves, or an add-on older than the row, is not asked again", async (t) => {
  for (const status of [403, 404]) {
    const view = await open(t, { routes: { "/api/continue": [status, {}] } });
    assert.equal(hidden(view, "continueFilmsCard"), true, String(status));
    view.clock.tick(60000);
    await view.state(PLAYING);
    await view.state(IDLE);
    await view.moved();
    assert.equal(reads(view, "/api/continue"), 1, String(status));
  }
});

test("a read failing with no error at all still counts as a failure", async (t) => {
  const view = await open(t, { quiet: true });
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (String(url).startsWith("/api/continue")
    ? Promise.reject(undefined) : fetch(url, init));
  await view.state(IDLE);
  assert.equal(hidden(view, "continueFilmsCard"), true);
  view.window.fetch = fetch;
  view.clock.tick(5000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 1);
  assert.equal(everyTile(view).length, 4);
});

test("a second title pressed while the first is waiting starts nothing", async (t) => {
  const view = await open(t);
  await press(view, "Film 03");
  // A waiting row takes no press; a click that reaches a tile all the same
  // (sent by a script, say) is dropped.
  assert.equal(tile(view, "Show 2").disabled, true);
  tile(view, "Show 2").dispatchEvent(new view.window.MouseEvent("click"));
  answer(view, "play");
  await settle();
  assert.deepEqual(plays(view), [{ movieid: 3 }]);
});

test("a read already on its way when a tile is pressed does not build the rows under it", async (t) => {
  const view = await open(t);
  const release = hold(view, "/api/continue");
  view.routes["/api/continue"] = [200, { tag: "c2", items: ITEMS }];
  await view.moved();
  await press(view, "Film 03");
  const show = tile(view, "Show 2");
  await release();
  assert.equal(tile(view, "Show 2"), show);
  assert.equal(show.disabled, true);
  assert.equal(tile(view, "Film 03").classList.contains("busy"), true);

  // The answer that was put off is asked for again once the press is over.
  view.clock.tick(4000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 3);
  assert.notEqual(tile(view, "Show 2"), show);
  assert.equal(tile(view, "Show 2").disabled, false);
});

test("an answer put off under a press is asked for again when the press fails", async (t) => {
  const view = await open(t);
  const row = hold(view, "/api/continue");
  view.routes["/api/continue"] = [200, { tag: "c2", items: ITEMS.slice(1) }];
  await view.moved();
  view.routes["/api/play"] = [500, {}];
  const play = hold(view, "/api/play");
  await press(view, "Film 03");
  await row();
  assert.equal(everyTile(view).length, 4);
  // Nothing started, so only the move put off says the row is unread.
  await play();
  assert.equal(tile(view, "Show 2").disabled, false);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 3);
  assert.deepEqual(titles(view, "continueFilmsRow"), ["Film 04"]);
});

test("a row that moves again while it is being read is read once more", async (t) => {
  const view = await open(t);
  const release = hold(view, "/api/continue");
  await view.moved();
  view.routes["/api/continue"] = [200, { tag: "c2", items: ITEMS.slice(1) }];
  await view.moved();
  assert.equal(reads(view, "/api/continue"), 2);
  await release();
  assert.equal(everyTile(view).length, 4);

  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 3);
  assert.deepEqual(titles(view, "continueFilmsRow"), ["Film 04"]);
});

test("a read that fails after the library moved leaves the rows standing", async (t) => {
  const view = await open(t);
  view.routes["/api/continue"] = [500, {}];
  await view.moved();
  assert.equal(reads(view, "/api/continue"), 2);
  assert.equal(hidden(view, "continueFilmsCard"), false);
  assert.equal(hidden(view, "continueSeriesCard"), false);
  assert.equal(everyTile(view).length, 4);

  // Still unread: once the wait is over it is asked for again.
  view.clock.tick(5000);
  await view.state(IDLE);
  assert.equal(reads(view, "/api/continue"), 3);
});
