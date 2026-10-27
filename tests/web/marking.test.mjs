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
  const table = { "/api/details": [200, {}], "/api/hello": [200, { version: "2.15.0", strings: STRINGS }],
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

/** What the dialog is asking, as somebody reading it would see it. */
function asked({ $ }) {
  return {
    open: $("detailsDialog").open, title: $("detailsTitle").textContent,
    play: $("detailsPlay").textContent,
    restart: !$("detailsRestart").hidden, clear: !$("detailsClear").hidden,
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
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.deepEqual(asked(view), { open: true, title: "Film 01", play: "Play", restart: false, clear: false });
  assert.equal(view.$("detailsDialog").returnValue, "");
  answer(view, "cancel");
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.deepEqual(asked(view), { open: true, title: "Film 03", play: "Resume", restart: true, clear: true });
  answer(view, "cancel");
  // A show is opened rather than played.
  tile(view, "Show 2").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.deepEqual(asked(view), { open: true, title: "Show 2", play: "Open", restart: false, clear: false });
  answer(view, "cancel");
  assert.deepEqual(posts(view), []);
});

test("nothing is asked once the box will no longer be told what to play", async (t) => {
  const view = await open(t);
  const film = tile(view, "Film 01");
  await view.state({ seq: 2, playing: false, control: false });
  film.dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsActions").hidden, true);
});

test("a second press while the question is open does not replace it", async (t) => {
  const view = await open(t);
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(asked(view).title, "Film 01");
  answer(view, "play");
  await settle();
  assert.deepEqual(posts(view), [["/api/play", { movieid: 1 }]]);
});

test("play starts the title where it was, and play from the start starts it from the top", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "play");
  await settle();
  // The wall waits on the film until it plays, or until it plainly will not.
  view.clock.tick(4000);
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "restart");
  await settle();
  assert.deepEqual(posts(view), [["/api/play", { movieid: 3 }],
                                 ["/api/play", { movieid: 3, resume: false }]]);
});

test("marking as watched or unwatched writes it with the token, then reads every list again", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  assert.deepEqual(reads(view), { library: 1, series: 1, continue: 1, episodes: 0 });

  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

  await settle();
  answer(view, "unwatched");
  await settle();
  const sent = view.requests.find((request) => request.url === "/api/watched");
  assert.equal(sent.init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent.init.headers["Content-Type"], "application/json");
  assert.deepEqual(reads(view), { library: 2, series: 2, continue: 2, episodes: 0 });
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsWatched").hidden, false);
  assert.equal(view.$("detailsUnwatched").hidden, true);
  answer(view, "close");

  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

  await settle();
  answer(view, "watched");
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  answer(view, "close");
  // A series marked either way is every episode of it.
  tile(view, "Show 2").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), [["/api/watched", { watched: false, movieid: 1 }],
                                 ["/api/watched", { watched: true, movieid: 3 }],
                                 ["/api/watched", { watched: true, tvshowid: 2 }]]);
  assert.deepEqual(reads(view), { library: 4, series: 4, continue: 4, episodes: 0 });
  assert.equal(view.$("detailsDialog").open, true);
});

test("marking an episode reads the open show again as well", async (t) => {
  const view = await open(t);
  tile(view, "Show 2").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "play");
  await settle();
  assert.equal(reads(view).episodes, 1);
  tile(view, "Episode 2").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.deepEqual(asked(view), { open: true, title: "S01E03 · Episode 2", play: "Resume",
                                  restart: true, clear: true });
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), [["/api/watched", { watched: true, episodeid: 102 }]]);
  assert.deepEqual(reads(view), { library: 2, series: 2, continue: 2, episodes: 2 });
});

test("clearing the resume point forgets where it got to and leaves seen or unseen alone", async (t) => {
  const view = await open(t);
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "clear");
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsClear").hidden, true);
  assert.equal(view.$("detailsPlay").textContent, "Play");
  answer(view, "close");
  // From the continue row: the episode it stands for.
  view.$("continueSeriesRow").firstElementChild.dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "clear");
  await settle();
  assert.deepEqual(posts(view), [["/api/resume", { movieid: 3 }],
                                 ["/api/resume", { episodeid: 99 }]]);
  assert.deepEqual(reads(view), { library: 3, series: 3, continue: 3, episodes: 0 });
});

test("cancelling, or a dialog closed with no question or no answer, sends nothing", async (t) => {
  const view = await open(t);
  const before = reads(view);
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "cancel");
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "");
  // Closed again with nothing asked: the last answer is not given twice.
  answer(view, "watched");
  await settle();
  assert.deepEqual(posts(view), []);
  assert.deepEqual(reads(view), before);
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "unwatched");
  answer(view, "unwatched");
  await settle();
  assert.equal(posts(view).length, 1);
});

test("a write refused for the token asks for it and reads nothing again", async (t) => {
  const view = await open(t, { routes: { "/api/watched": [401, {}] } });
  const before = reads(view);
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
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
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "clear");
  await settle();
  assert.equal(view.$("toast").textContent, "Could not be marked");
  assert.equal(view.$("toast").classList.contains("bad"), true);

  view.$("toast").textContent = "";
  const fetch = view.window.fetch;
  view.window.fetch = (url, init) => (url === "/api/watched"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "watched");
  await settle();
  assert.equal(view.$("toast").textContent, "Could not be marked");
  assert.deepEqual(reads(view), before);
  assert.equal(view.$("tokenDialog").open, false);
});

test("before /api/hello has given any words, the question and its failure are in English", async (t) => {
  const view = await open(t, { routes: {
    "/api/hello": [200, { version: "2.15.0", strings: {} }], "/api/watched": [500, {}] } });
  tile(view, "Film 01").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(asked(view).play, "Play");
  assert.deepEqual(["detailsWatched", "detailsUnwatched"].map((id) => view.$(id).textContent),
                   ["Mark as watched", "Mark as unwatched"]);
  answer(view, "unwatched");
  await settle();
  assert.equal(view.$("toast").textContent, "The library could not be updated");

  tile(view, "Film 03").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

  await settle();
  assert.deepEqual(["detailsRestart", "detailsClear"].map((id) => view.$(id).textContent),
                   ["Play from the beginning", "Clear resume point"]);
  answer(view, "");
  tile(view, "Show 2").dispatchEvent(new view.dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(asked(view).play, "Open");
});


test("a tap and a hold open the same details while scrolling cancels the hold", async (t) => {
  const view = await open(t, { routes: { "/api/details": [200, { plot: "Full details", cast: [] }] } });
  const film = tile(view, "Film 01");
  film.click();
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("markDialog"), null);
  view.$("detailsDialog").close();
  view.$("detailsDialog").dispatchEvent(new view.window.Event("close"));
  const pointer = (type, x = 0, y = 0) => film.dispatchEvent(new view.window.MouseEvent(type, { button: 0, clientX: x, clientY: y }));
  pointer("pointermove", 1, 1);
  film.dispatchEvent(new view.window.MouseEvent("pointerdown", { button: 2 }));
  view.clock.tick(600);
  assert.equal(view.$("detailsDialog").open, false, "a secondary button does not arm a hold");
  pointer("pointerdown");
  pointer("pointermove", 1, 1);
  pointer("pointercancel");
  view.clock.tick(600);
  assert.equal(view.$("detailsDialog").open, false, "a cancelled gesture does not open actions");
  pointer("pointerdown");
  pointer("pointerleave");
  view.clock.tick(600);
  assert.equal(view.$("detailsDialog").open, false, "leaving the tile cancels the hold");
  pointer("pointerdown");
  pointer("pointermove", 0, 30);
  view.clock.tick(600);
  assert.equal(view.$("detailsDialog").open, false);
  pointer("pointerup");
  pointer("pointerdown");
  view.clock.tick(500);
  pointer("pointerup");
  film.click();
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("markDialog"), null);
});


test("status edits stay open, reject duplicates, preserve scroll and leave failures unchanged", async (t) => {
  const view = await open(t, { routes: { "/api/watched": [500, {}] } });
  tile(view, "Film 01").click();
  await settle();
  const dialog = view.$("detailsDialog");
  const form = dialog.querySelector("form");
  form.scrollTop = 123;
  let release;
  let gate = new Promise((resolve) => { release = resolve; });
  const fetch = view.window.fetch;
  view.window.fetch = async (url, init) => {
    if (url === "/api/watched") await gate;
    return fetch(url, init);
  };
  view.$("detailsUnwatched").click();
  await settle();
  assert.equal(dialog.open, true);
  assert.ok([...view.$("detailsActions").querySelectorAll("button")].every((button) => button.disabled));
  view.$("detailsUnwatched").dispatchEvent(new view.window.MouseEvent("click"));
  release();
  await settle();
  assert.equal(posts(view).length, 1);
  assert.equal(dialog.open, true);
  assert.equal(view.$("detailsError").hidden, false);
  assert.equal(view.$("detailsWatched").hidden, true);
  assert.equal(view.$("detailsUnwatched").disabled, false);
  assert.equal(form.scrollTop, 123);
  view.routes["/api/watched"] = [200, {}];
  view.$("detailsUnwatched").click();
  await settle();
  assert.equal(view.$("detailsWatched").hidden, false);
  assert.equal(view.$("detailsUnwatched").hidden, true);
  assert.equal(view.$("detailsError").hidden, true);
  assert.equal(form.scrollTop, 123);
  gate = new Promise((resolve) => { release = resolve; });
  view.routes["/api/watched"] = [500, {}];
  view.$("detailsWatched").click();
  answer(view, "close");
  release();
  await settle();
  assert.equal(dialog.open, false, "finishing a write must not reopen manually closed details");
  assert.equal(view.$("detailsError").hidden, true, "a late failure must not change another page");
});


test("the opened title uses the current watched and resume state instead of stale shelf values", async (t) => {
  const view = await open(t, { routes: { "/api/details": [200, { watched: true, resume: 0 }] } });
  tile(view, "Film 03").click();
  await settle();
  assert.equal(view.$("detailsWatched").hidden, true);
  assert.equal(view.$("detailsUnwatched").hidden, false);
  assert.equal(view.$("detailsClear").hidden, true);
  assert.equal(view.$("detailsPlay").textContent, "Play");
  answer(view, "close");
  view.routes["/api/details"] = [200, { watched: false, resume: 600 }];
  tile(view, "Film 01").click();
  await settle();
  assert.equal(view.$("detailsWatched").hidden, false);
  assert.equal(view.$("detailsUnwatched").hidden, true);
  assert.equal(view.$("detailsClear").hidden, false);
  assert.equal(view.$("detailsPlay").textContent, "Resume");
  answer(view, "restart");
  await settle();
  assert.equal(view.$("detailsDialog").open, false);
});

test("a late details response cannot replace the newer title", async (t) => {
  const view = await open(t);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fetch = view.window.fetch;
  view.window.fetch = async (url, init) => {
    if (String(url).includes("movieid=91")) await gate;
    return fetch(url, init);
  };
  const first = view.window.TinyPPI.openDetails({ title: "Old", kind: "movie", id: 91 });
  await view.window.showDetails({ title: "New", body: { movieid: 92 } }, true);
  release();
  await first;
  assert.equal(view.$("detailsTitle").textContent, "New");
});

test("a broadcast's details are drawn from the snapshot, asking the box nothing", async (t) => {
  const view = await open(t);
  const asked = view.requests.filter((request) => request.url.startsWith("/api/details")).length;
  await view.window.TinyPPI.openSnapshotDetails({
    title: "Tagesschau", art: { poster: "p1" },
    media: { plot: "Die Nachrichten.", year: 2026, genres: ["News"],
             directors: ["Ann Regie"], cast: ["Jens Riewa", "Judith Rakers"], roles: ["Sprecher"],
             ratings: [{ source: "imdb", rating: 6.5 }] } });
  await settle();
  assert.equal(view.requests.filter((request) => request.url.startsWith("/api/details")).length, asked);
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsTitle").textContent, "Tagesschau");
  assert.equal(view.$("detailsMeta").textContent, "2026");
  assert.equal(view.$("detailsPlot").textContent, "Die Nachrichten.");
  // The playing title's pictures, asked for without an id.
  assert.equal(view.$("detailsPoster").getAttribute("src"), "/api/art?kind=poster&v=p1");
  assert.equal(view.$("detailsBackdrop").hidden, true);
  // Each of the cast with who they played, "" where the snapshot says nobody.
  const cast = [...view.$("detailsCast").querySelectorAll(".castrow li")].map((item) =>
    [item.querySelector("strong").textContent, item.querySelector(".role").textContent]);
  assert.deepEqual(cast.slice(0, 2), [["Jens Riewa", "Sprecher"], ["Judith Rakers", ""]]);
  assert.ok(view.$("detailsRatings").children.length > 0);
  // Already playing: no keys to play or mark it.
  assert.equal(view.$("detailsActions").hidden, true);
});

test("a snapshot that names no cast, roles or pictures still draws its page", async (t) => {
  const view = await open(t);
  await view.window.TinyPPI.openSnapshotDetails({ title: "Kanal 1", art: {}, media: { plot: "Live." } });
  await settle();
  assert.equal(view.$("detailsPlot").textContent, "Live.");
  assert.equal(view.$("detailsPoster").hidden, true);
  assert.equal(view.$("detailsCast").children.length, 0);
});

test("reopening a closing page reverses its exit without jumping offscreen", async (t) => {
  const view = await open(t);
  tile(view, "Film 01").click();
  await settle();
  const dialog = view.$("detailsDialog");
  view.$("detailsX").click();
  assert.equal(dialog.classList.contains("away"), true);
  view.window.slideIn(dialog);
  assert.equal(dialog.classList.contains("away"), false);
  view.clock.tick(250);
  assert.equal(dialog.open, true);
});

for (const [name, details, visible] of [
  ["plot only", { plot: "Plot." }, true],
  ["slogan only", { tagline: "Slogan." }, true],
  ["no description", {}, false]
]) {
  test("description section handles " + name, async (t) => {
    const view = await open(t, { routes: { "/api/details": [200, details] } });
    tile(view, "Film 01").click();
    await settle();
    assert.equal(view.$("detailsDescription").hidden, !visible);
    assert.equal(view.$("detailsDescriptionTitle").textContent, "Description");
    assert.equal(view.$("detailsTagline").textContent, details.tagline || "");
    assert.equal(view.$("detailsPlot").textContent, details.plot || "");
  });
}
