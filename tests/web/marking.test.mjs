// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The question a press on a film, a show or an episode asks
// (resources/web/js/marking.js): what it offers, what each answer sends --
// play, play from the start, clear the resume point, mark as watched or
// unwatched -- and the lists read again once the box has taken a write.
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

const STRINGS = { films_play: "Play", films_resume: "Resume", series_open: "Open",
                  mark_failed: "Could not be marked" };

const LIBRARY = {
  "/api/library": [200, { tag: "f1", movies: [
    { id: 1, title: "Film 01", year: 2001, duration: 5460, watched: true,
      added: "2026-09-01 10:00:00" },
    { id: 3, title: "Film 03", year: 2003, duration: 5580, resume: 1800,
      added: "2026-09-03 10:00:00" }] }],
  "/api/series": [200, { tag: "s1", shows: [
    { id: 2, title: "Show 2", year: 2012, episodes: 10, unseen: 8 }] }],
  "/api/episodes": [200, { title: "Show 2", tag: "e1", episodes: [
    { id: 101, title: "Episode 1", season: 1, episode: 2, duration: 2700, watched: true },
    { id: 102, title: "Episode 2", season: 1, episode: 3, duration: 2700, resume: 600 }] }],
  "/api/continue": [200, { tag: "c1", items: [
    { kind: "episode", id: 99, title: "Started", show: "Show 2", season: 1, episode: 3,
      duration: 1000, resume: 100 }] }],
  "/api/play": [200, {}],
  "/api/watched": [200, {}],
  "/api/resume": [200, {}],
};

/** The dashboard with the box's library on its shelves and control allowed;
 * the window is closed when the test ends. */
async function open(t, { routes = {}, token = "" } = {}) {
  const table = { "/api/hello": [200, { version: "2.15.0", strings: STRINGS }],
                  ...LIBRARY, ...routes };
  const view = page({ scripts: [], routes: table, token });
  const { window, dom } = view;
  t.after(() => window.close());
  const clock = fakeClock(window);
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  for (const name of ORDER) load(dom, name);
  await settle();
  const result = {
    ...view, routes: table, clock,
    $: (id) => window.document.getElementById(id),
    async state(snapshot) {
      view.streams.at(-1).emit("state", snapshot);
      await settle();
    },
  };
  await result.state({ seq: 1, playing: false, control: true });
  return result;
}

/** The film, show or episode tile called *title*. */
function tile({ window }, title) {
  const found = [...window.document.querySelectorAll("#filmGrid .film, #seriesGrid .film, .episode")]
    .find((node) => node.querySelector(".filmtitle, .episodetitle").textContent === title);
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

/** What the dialog is asking, as somebody reading it would see it. */
function asked({ $ }) {
  return {
    open: $("markDialog").open, title: $("markTitle").textContent,
    play: $("markPlay").textContent,
    restart: !$("markRestart").hidden, clear: !$("markClear").hidden,
  };
}

// The session a token buys on connect is no write.
const posts = ({ requests }) => requests
  .filter((request) => request.init && request.init.method === "POST"
          && request.url !== "/api/session")
  .map((request) => [request.url, JSON.parse(request.init.body)]);

const reads = ({ requests }) => Object.fromEntries(
  ["/api/library", "/api/series", "/api/continue", "/api/episodes"].map((path) =>
    [path.slice(5), requests.filter((request) => request.url.replace(/\?.*$/, "") === path).length]));

test("a press asks what is wanted, offering a fresh start and forgetting only where there is a point to resume", async (t) => {
  const view = await open(t);
  tile(view, "Film 01").click();
  assert.deepEqual(asked(view), { open: true, title: "Film 01", play: "Play", restart: false, clear: false });
  assert.equal(view.$("markDialog").returnValue, "");
  answer(view, "cancel");
  tile(view, "Film 03").click();
  assert.deepEqual(asked(view), { open: true, title: "Film 03", play: "Resume", restart: true, clear: true });
  answer(view, "cancel");
  // A show is opened rather than played.
  tile(view, "Show 2").click();
  assert.deepEqual(asked(view), { open: true, title: "Show 2", play: "Open", restart: false, clear: false });
  answer(view, "cancel");
  assert.deepEqual(posts(view), []);
});

test("nothing is asked once the box will no longer be told what to play", async (t) => {
  const view = await open(t);
  const film = tile(view, "Film 01");
  await view.state({ seq: 2, playing: false, control: false });
  film.click();
  assert.equal(view.$("markDialog").open, false);
  assert.equal(view.$("markTitle").textContent, "");
});

test("a second press while the question is open does not replace it", async (t) => {
  const view = await open(t);
  tile(view, "Film 01").click();
  tile(view, "Film 03").click();
  assert.equal(asked(view).title, "Film 01");
  answer(view, "play");
  await settle();
  assert.deepEqual(posts(view), [["/api/play", { movieid: 1 }]]);
});

test("play starts the title where it was, and play from the start starts it from the top", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  tile(view, "Film 03").click();
  answer(view, "play");
  await settle();
  // The wall waits on the film until it plays, or until it plainly will not.
  view.clock.tick(4000);
  tile(view, "Film 03").click();
  answer(view, "restart");
  await settle();
  assert.deepEqual(posts(view), [["/api/play", { movieid: 3 }],
                                 ["/api/play", { movieid: 3, resume: false }]]);
});

test("marking as watched or unwatched writes it with the token, then reads every list again", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  assert.deepEqual(reads(view), { library: 1, series: 1, continue: 1, episodes: 0 });

  tile(view, "Film 01").click();
  answer(view, "unwatched");
  await settle();
  const sent = view.requests.find((request) => request.url === "/api/watched");
  assert.equal(sent.init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent.init.headers["Content-Type"], "application/json");
  assert.deepEqual(reads(view), { library: 2, series: 2, continue: 2, episodes: 0 });

  tile(view, "Film 03").click();
  answer(view, "watched");
  await settle();
  // A series marked either way is every episode of it.
  tile(view, "Show 2").click();
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), [["/api/watched", { watched: false, movieid: 1 }],
                                 ["/api/watched", { watched: true, movieid: 3 }],
                                 ["/api/watched", { watched: true, tvshowid: 2 }]]);
  assert.deepEqual(reads(view), { library: 4, series: 4, continue: 4, episodes: 0 });
  assert.equal(view.$("markDialog").open, false);
});

test("marking an episode reads the open show again as well", async (t) => {
  const view = await open(t);
  tile(view, "Show 2").click();
  answer(view, "play");
  await settle();
  assert.equal(reads(view).episodes, 1);
  tile(view, "Episode 2").click();
  assert.deepEqual(asked(view), { open: true, title: "S01E03 · Episode 2", play: "Resume",
                                  restart: true, clear: true });
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), [["/api/watched", { watched: true, episodeid: 102 }]]);
  assert.deepEqual(reads(view), { library: 2, series: 2, continue: 2, episodes: 2 });
});

test("clearing the resume point forgets where it got to and leaves seen or unseen alone", async (t) => {
  const view = await open(t);
  tile(view, "Film 03").click();
  answer(view, "clear");
  await settle();
  // From the continue row: the episode it stands for.
  view.$("continueSeriesRow").firstElementChild.click();
  answer(view, "clear");
  await settle();
  assert.deepEqual(posts(view), [["/api/resume", { movieid: 3 }],
                                 ["/api/resume", { episodeid: 99 }]]);
  assert.deepEqual(reads(view), { library: 3, series: 3, continue: 3, episodes: 0 });
});

test("cancelling, or a dialog closed with no question or no answer, sends nothing", async (t) => {
  const view = await open(t);
  const before = reads(view);
  tile(view, "Film 01").click();
  answer(view, "cancel");
  tile(view, "Film 01").click();
  answer(view, "");
  // Closed again with nothing asked: the last answer is not given twice.
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), []);
  assert.deepEqual(reads(view), before);
  tile(view, "Film 01").click();
  answer(view, "watched");
  answer(view, "watched");
  await settle();
  assert.equal(posts(view).length, 1);
});

test("a write refused for the token asks for it and reads nothing again", async (t) => {
  const view = await open(t, { routes: { "/api/watched": [401, {}] } });
  const before = reads(view);
  tile(view, "Film 01").click();
  answer(view, "unwatched");
  await settle();
  assert.equal(view.$("toast").textContent, "Wrong or missing token");
  assert.equal(view.$("toast").classList.contains("bad"), true);
  assert.equal(view.$("tokenDialog").open, true);
  assert.deepEqual(reads(view), before);
});

test("a write that fails, or never reaches the box, says so and reads nothing again", async (t) => {
  const view = await open(t, { routes: { "/api/resume": [500, {}] } });
  const before = reads(view);
  tile(view, "Film 03").click();
  answer(view, "clear");
  await settle();
  assert.equal(view.$("toast").textContent, "Could not be marked");
  assert.equal(view.$("toast").classList.contains("bad"), true);

  view.$("toast").textContent = "";
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (url === "/api/watched"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  tile(view, "Film 03").click();
  answer(view, "watched");
  await settle();
  assert.equal(view.$("toast").textContent, "Could not be marked");
  assert.deepEqual(reads(view), before);
  assert.equal(view.$("tokenDialog").open, false);
});

test("before /api/hello has given any words, the question and its failure are in English", async (t) => {
  const view = await open(t, { routes: {
    "/api/hello": [200, { version: "2.15.0", strings: {} }], "/api/watched": [500, {}] } });
  tile(view, "Film 01").click();
  assert.equal(asked(view).play, "Play");
  assert.deepEqual(["markWatched", "markUnwatched", "markCancel"].map((id) => view.$(id).textContent),
                   ["Mark as watched", "Mark as unwatched", "Cancel"]);
  answer(view, "watched");
  await settle();
  assert.equal(view.$("toast").textContent, "The library could not be updated");

  tile(view, "Film 03").click();
  assert.deepEqual(["markRestart", "markClear"].map((id) => view.$(id).textContent),
                   ["Play from the beginning", "Clear resume point"]);
  answer(view, "");
  tile(view, "Show 2").click();
  assert.equal(asked(view).play, "Open");
});
