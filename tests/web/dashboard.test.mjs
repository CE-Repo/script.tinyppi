// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The dashboard's frame (resources/web/js/dashboard.js): the tabs and the
// bar that switches them, the bar stepping out of the way, the settings tab,
// the idle and playing cards, the detail groups, VS10, the library reads a
// snapshot sets off, and the report.  The whole page is loaded in the order
// index.html gives, with its timers on a clock the test moves.

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
 * does, so that the page can be prepared (storage, address, timers) first. */
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

/** The dashboard as index.html loads it.  *before* runs on the bare page
 * ahead of the scripts; the window is closed when the test ends. */
function open(t, { routes = {}, hello = {}, token = "", before, scripts = ORDER } = {}) {
  const table = { "/api/hello": [200, { version: "2.15.0", strings: {}, ...hello }], ...routes };
  const view = page({ scripts: [], routes: table, token });
  const { window, dom } = view;
  t.after(() => window.close());
  const clock = fakeClock(window);
  const scrolled = [];
  window.scrollTo = (...args) => { scrolled.push(args.length === 1 ? plain(args[0]) : args); };
  const copied = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true, value: { writeText: async (text) => { copied.push(text); } },
  });
  if (before) before(window);
  for (const name of scripts) load(dom, name);
  return {
    ...view, routes: table, clock, scrolled, copied,
    $: (id) => window.document.getElementById(id),
    async state(snapshot) {
      // With a token the stream opens once the session is bought.
      if (!view.streams.length) await settle();
      view.streams.at(-1).emit("state", snapshot);
      await settle();
    },
  };
}

// Objects built inside the page have the page's prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));

/** Which tab is in front, checking that its key and its panel agree. */
function front({ window }) {
  const doc = window.document;
  const lit = [...doc.querySelectorAll("#tabBar .tab.on")].map((key) => key.dataset.tab);
  const shown = [...doc.querySelectorAll(".tabpanel.active")].map((panel) => panel.dataset.tab);
  assert.deepEqual(shown, lit, "the panel in front belongs to the lit key");
  return lit.join(",");
}

const offered = ({ window }) =>
  [...window.document.querySelectorAll("#tabBar .tab:not(.hidden)")].map((key) => key.dataset.tab);

const hidden = (node) => node.classList.contains("hidden");

/** Let jsdom fire the hashchange a new address queues: it is queued with
 * setImmediate, which settle()'s timer may or may not come after. */
const navigated = () => new Promise((resolve) => setImmediate(resolve)).then(settle);

const reads = ({ requests }, path) =>
  requests.filter((request) => request.url.replace(/\?.*$/, "") === path).length;

/** Answer the question a press asked, as the dialog's form would. */
function answer({ window, $ }, value) {
  const dialog = $("markDialog");
  dialog.returnValue = value;
  dialog.close();
  dialog.dispatchEvent(new window.Event("close"));
}

function key(view, name) {
  const event = new view.window.KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true });
  view.window.document.activeElement.dispatchEvent(event);
  return event;
}

const PLAYING = {
  seq: 1, playing: true, paused: false, control: true, library: 1,
  title: "Film", filename: "/media/Film.mkv", time: "00:10:00", duration: "02:00:00",
  hdr_type: "dolbyvision", output_type: "dolbyvision",
  groups: [
    { id: "video", title: "Video", rows: [
      { id: "video.res", label: "Resolution", value: "3840x2160p 23.976FPS", detail: "" },
      { id: "video.hdr", label: "HDR", value: "Dolby Vision ✔", detail: "" }] },
    { id: "audio", title: "Audio", rows: [
      { id: "audio.32238", label: "Codec", value: "TrueHD Atmos 7.1", detail: "" }] }],
  metrics: { cpu: 20, cpu_temp: 50, fps_in: 24, l1: { max: 1000, avg: 120 },
             frame: { w: 3840, h: 2160 } },
  metadata: [{ kind: "row", name: "L1 max", value: "1000" }],
  session: { seq: 3, switches: 1, warnings: 1 },
};
const IDLE = { seq: 1, playing: false, control: true };

const HISTORY = {
  t: [0, 1, 2], max: [700, 812.4, null], avg: [100, 120, null], now: 2, step: 1,
  seq: 3, switches: 1,
  events: [
    { t: 0.5, pos: "00:00:10", kind: "fps", from: 24, to: 60 },
    { t: 0.8, kind: "audio", from: "#1 · ENG · English", to: "#2 · GER · Deutsch" },
    { t: 0.9, pos: "00:00:13", kind: "temperature", value: 77.4 }],
};

const LIBRARY = {
  "/api/library": [200, { tag: "f1", movies: [
    { id: 1, title: "Film 01", year: 2001, duration: 5460, watched: true,
      added: "2026-09-01 10:00:00", rating: 5.1, rating_from: "imdb" },
    { id: 3, title: "Film 03", year: 2003, duration: 5580, resume: 1800,
      added: "2026-09-03 10:00:00" }] }],
  "/api/series": [200, { tag: "s1", shows: [
    { id: 2, title: "Show 2", year: 2012, episodes: 10, unseen: 8,
      added: "2026-08-02 10:00:00" }] }],
  "/api/episodes": [200, { title: "Show 2", tag: "e1", episodes: [
    { id: 101, title: "Episode 1", season: 1, episode: 2, duration: 2700, watched: true },
    { id: 102, title: "Episode 2", season: 1, episode: 3, duration: 2700, resume: 600 }] }],
  "/api/continue": [200, { tag: "c1", items: [
    { kind: "movie", id: 3, title: "Film 03", year: 2003, duration: 7200, resume: 1800 },
    { kind: "episode", id: 99, title: "Started", show: "Show 2", season: 1, episode: 3,
      duration: 1000, resume: 100 }] }],
};

/* --- the frame -------------------------------------------------------- */

test("the frame is rearranged at load: VS10 under the playing card, figures and events on the history tab", (t) => {
  const { $ } = open(t);
  assert.equal($("nowCard").nextElementSibling, $("vs10Card"));
  const events = $("eventsCard");
  const grid = events.querySelector(".tilegrid");
  assert.ok(grid, "the figures moved into the events card");
  assert.equal(events.querySelector(".eventswrap").previousElementSibling, grid);
  assert.equal($("tiles").hidden, true);
  assert.equal($("lastCard").nextElementSibling, events);
  assert.equal(events.closest(".tabpanel").dataset.tab, "history");
});

test("the shelves arrive open, a shelf somebody folded stays folded, and retired marks are dropped", (t) => {
  const { window, $ } = open(t, { before: (w) => {
    w.localStorage.setItem("tinyppi.disclosure.dashboard.films", "1");
    w.localStorage.setItem("tinyppi.disclosure.dashboard.continue", "0");
    w.localStorage.setItem("tinyppi.disclosure.dashboard.filmshelf", "0");
  } });
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.dashboard.films"), null);
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.dashboard.continue"), null);
  assert.equal($("filmsCard").open, false);
  for (const id of ["seriesCard", "unseenFilmsCard", "unseenSeriesCard", "continueFilmsCard",
                    "continueSeriesCard", "recentFilmsCard", "recentSeriesCard"]) {
    assert.equal($(id).open, true, id);
  }
  assert.equal($("vs10Card").open, false);
});

/* --- tabs ------------------------------------------------------------- */

test("a press on a tab key brings its panel forward, writes it into the address and remembers it", (t) => {
  const view = open(t);
  const { window, $, clock } = view;
  let draws = 0;
  window.TinyPPI.panels.draw = () => { draws += 1; };
  clock.tick(16);
  draws = 0;
  $("tabbtn-history").querySelector(".ui-icon").click();
  assert.equal(front(view), "history");
  for (const button of window.document.querySelectorAll("#tabBar .tab")) {
    const on = button.dataset.tab === "history";
    assert.equal(button.getAttribute("aria-selected"), on ? "true" : "false");
    assert.equal(button.tabIndex, on ? 0 : -1);
  }
  assert.equal(window.location.hash, "#history");
  assert.equal(window.localStorage.getItem("tinyppi.tab"), "history");
  // The chart and the event list are measured again once the tab is laid out.
  assert.equal(draws, 0);
  clock.tick(16);
  assert.equal(draws, 1);
  // A press on the bar between the keys changes nothing.
  $("tabBar").click();
  assert.equal(front(view), "history");
});

test("each tab comes back where it was left, and a press on the tab in front goes back to its top", (t) => {
  const view = open(t);
  const { window, $, scrolled } = view;
  window.scrollY = 420;
  $("tabbtn-settings").click();
  assert.deepEqual(scrolled.at(-1), [0, 0]);
  window.scrollY = 0;
  $("tabbtn-live").click();
  assert.deepEqual(scrolled.at(-1), [0, 420]);
  $("tabbtn-live").click();
  assert.equal(front(view), "live");
  assert.deepEqual(scrolled.at(-1), { top: 0, behavior: "smooth" });
});

test("the arrow keys walk the keys on offer, wrapping round at either end", async (t) => {
  const view = open(t);
  await view.state({ ...IDLE, control: false });
  assert.deepEqual(offered(view), ["live", "history", "settings"]);
  view.$("tabbtn-live").focus();
  const right = key(view, "ArrowRight");
  assert.equal(front(view), "history");
  assert.equal(view.window.document.activeElement, view.$("tabbtn-history"));
  assert.equal(right.defaultPrevented, true);
  key(view, "ArrowRight");
  assert.equal(front(view), "settings");
  key(view, "ArrowRight");
  assert.equal(front(view), "live");
  key(view, "ArrowLeft");
  assert.equal(front(view), "settings");
  const other = key(view, "Enter");
  assert.equal(front(view), "settings");
  assert.equal(other.defaultPrevented, false);
});

test("the arrow keys do nothing before the page has chosen a tab", (t) => {
  const view = open(t, { scripts: ORDER.filter((name) => name !== "start.js") });
  view.$("tabbtn-live").focus();
  const event = key(view, "ArrowRight");
  assert.equal(front(view), "");
  assert.equal(event.defaultPrevented, false);
});

test("a changed address changes the tab, and one naming no tab is ignored", async (t) => {
  const view = open(t);
  view.window.location.hash = "#settings";
  await navigated();
  assert.equal(front(view), "settings");
  view.window.location.hash = "#nowhere";
  await navigated();
  assert.equal(front(view), "settings");
  // An address naming a tab that is not on offer lands on the live one.
  await view.state({ ...PLAYING, hdr_type: "hdr10", metadata: [] });
  view.window.location.hash = "#metadata";
  await navigated();
  assert.equal(front(view), "live");
  assert.equal(view.window.location.hash, "#live");
});

test("the metadata tab is on offer only while a Dolby Vision title plays", async (t) => {
  const view = open(t, { before: (w) => { w.location.hash = "#metadata"; } });
  assert.equal(front(view), "metadata", "nothing is known yet, so it may be there");
  await view.state({ ...PLAYING, hdr_type: "hdr10", output_type: "hdr10", metadata: [] });
  assert.equal(front(view), "live");
  assert.equal(offered(view).includes("metadata"), false);
  // The add-on already sending its metadata list counts as well.
  await view.state({ ...PLAYING, hdr_type: "hdr10", metadata: [{ kind: "row", name: "L1 max", value: "1" }] });
  assert.equal(offered(view).includes("metadata"), true);
  await view.state({ ...PLAYING, metadata: [] });
  assert.equal(offered(view).includes("metadata"), true);
  await view.state({ ...IDLE, hdr_type: "dolbyvision" });
  assert.equal(offered(view).includes("metadata"), false);
});

test("the shelf tabs are there only on a box that will be told what to play", async (t) => {
  const view = open(t, { before: (w) => { w.location.hash = "#films"; } });
  assert.equal(front(view), "films", "until a snapshot says otherwise");
  await view.state({ ...IDLE, control: false });
  assert.equal(front(view), "live");
  assert.deepEqual(offered(view), ["live", "history", "settings"]);
  await view.state({ ...IDLE, control: true });
  assert.deepEqual(offered(view), ["live", "films", "series", "history", "settings"]);
});

test("a box that refuses the film or the series list loses that tab", async (t) => {
  const view = open(t, { routes: { "/api/library": [403, {}], "/api/series": [403, {}] } });
  await view.state(IDLE);
  // The refusal is heard after the first snapshot asked; the next one redraws the bar.
  await view.state(IDLE);
  assert.deepEqual(offered(view), ["live", "history", "settings"]);
});

test("a browser that blocks storage and address writes still switches tabs", (t) => {
  const view = open(t, { before: (w) => {
    const refuse = () => { throw new w.DOMException("blocked", "SecurityError"); };
    for (const name of ["getItem", "setItem", "removeItem"]) w.Storage.prototype[name] = refuse;
    w.history.replaceState = refuse;
  } });
  assert.equal(front(view), "live");
  view.$("tabbtn-settings").click();
  assert.equal(front(view), "settings");
  assert.equal(view.window.location.hash, "");
});

/* --- the bar's comings and goings ------------------------------------- */

test("the bar steps away after three quiet seconds, and any activity brings it back", (t) => {
  const { window, clock } = open(t);
  const away = () => window.document.documentElement.classList.contains("bar-away");
  clock.tick(2999);
  assert.equal(away(), false);
  clock.tick(1);
  assert.equal(away(), true);
  for (const kind of ["pointermove", "wheel", "keydown", "touchmove"]) {
    window.document.dispatchEvent(new window.Event(kind));
    assert.equal(away(), false, kind);
    clock.tick(3000);
    assert.equal(away(), true, kind);
  }
});

test("the bar stays while a finger is down, a dialog is open or one of its keys has the focus", (t) => {
  const { window, $, clock } = open(t);
  const doc = window.document;
  const away = () => doc.documentElement.classList.contains("bar-away");
  doc.dispatchEvent(new window.Event("pointerdown"));
  clock.tick(9000);
  assert.equal(away(), false, "a finger is still down");
  doc.dispatchEvent(new window.Event("pointerup"));
  clock.tick(3000);
  assert.equal(away(), true);

  doc.dispatchEvent(new window.Event("pointerdown"));
  doc.dispatchEvent(new window.Event("pointercancel"));
  $("markDialog").showModal();
  clock.tick(9000);
  assert.equal(away(), false, "a dialog is open");
  $("markDialog").close();
  clock.tick(3000);
  assert.equal(away(), true);

  doc.dispatchEvent(new window.Event("pointermove"));
  $("tabbtn-live").focus();
  clock.tick(9000);
  assert.equal(away(), false, "a key has the focus");
  $("tabbtn-live").blur();
  clock.tick(3000);
  assert.equal(away(), true);
});

test("a scroll brings the bar back, but not the browser's own scroll as it leaves", (t) => {
  const { window, clock } = open(t);
  const away = () => window.document.documentElement.classList.contains("bar-away");
  clock.tick(3000);
  assert.equal(away(), true);
  clock.tick(600);
  window.dispatchEvent(new window.Event("scroll"));
  assert.equal(away(), true);
  clock.tick(1);
  window.dispatchEvent(new window.Event("scroll"));
  assert.equal(away(), false);
});

/* --- settings --------------------------------------------------------- */

test("the settings tab shows which token this device holds, all but two characters hidden", async (t) => {
  const view = open(t, { token: "T0K3N", hello: { strings: { na: "k. A." } } });
  const { window, $ } = view;
  await settle();
  assert.equal($("tokenShown").textContent, "•••3N");
  const enter = (value) => {
    $("tokenBtn").click();
    assert.equal($("tokenDialog").open, true);
    $("tokenInput").value = value;
    $("tokenDialog").returnValue = "ok";
    $("tokenDialog").close();
    $("tokenDialog").dispatchEvent(new window.Event("close"));
  };
  enter("ab12cd");
  assert.equal($("tokenShown").textContent, "••••CD");
  enter("  ");
  assert.equal($("tokenShown").textContent, "k. A.");
});

test("the report keys are dimmed while there is nothing to copy", async (t) => {
  const view = open(t);
  const { $ } = view;
  assert.equal($("copyBtn").disabled, true);
  assert.equal($("copyMetaBtn").disabled, true);
  await view.state(PLAYING);
  assert.equal($("copyBtn").disabled, false);
  assert.equal($("copyMetaBtn").disabled, false);
  await view.state({ ...PLAYING, metadata: [] });
  assert.equal($("copyMetaBtn").disabled, true);
  await view.state(IDLE);
  assert.equal($("copyBtn").disabled, true);
  await view.state({ ...IDLE, last: { title: "Film" } });
  assert.equal($("copyBtn").disabled, false);
  await view.state({ ...IDLE, last: { title: "" } });
  assert.equal($("copyBtn").disabled, true);
});

/* --- idle and playing ------------------------------------------------- */

const lastTiles = ({ $ }) => [...$("lastTiles").children].map((tile) =>
  [tile.querySelector(".k").textContent, tile.querySelector(".v").textContent]);

test("an idle box shows its idle card and what was last played, and the groups are cleared", async (t) => {
  const view = open(t);
  const { $ } = view;
  await view.state(PLAYING);
  assert.equal($("groups").children.length, 2);
  await view.state({ ...IDLE, last: { title: "Film", switches: 2, warnings: 1 } });
  assert.equal(hidden($("idleCard")), false);
  assert.equal(hidden($("vs10Card")), true);
  assert.equal($("groups").children.length, 0);
  assert.equal(hidden($("lastCard")), false);
  assert.equal($("lastTitle").textContent, "Film");
  assert.deepEqual(lastTiles(view), [["Switches", "2"], ["Warnings", "1"]]);
  assert.equal(hidden($("historyIdleCard")), true, "the title that ended is the history");
  assert.equal(hidden($("eventsCard").querySelector(".tilegrid")), true);
  // An idle page standing still stays as it is.
  await view.state({ ...IDLE, last: { title: "Film", switches: 2, warnings: 1 } });
  assert.equal($("groups").children.length, 0);
  assert.equal(hidden($("lastCard")), false);
});

test("with nothing played yet the history tab says so", async (t) => {
  const view = open(t);
  await view.state(IDLE);
  assert.equal(hidden(view.$("lastCard")), true);
  assert.equal(hidden(view.$("historyIdleCard")), false);
  assert.equal(hidden(view.$("idleCard")), false);
});

test("what was last played is drawn again only when it would come out differently", async (t) => {
  const view = open(t);
  const { $ } = view;
  await view.state({ ...IDLE, last: { title: "Film", switches: 2 } });
  const first = $("lastTiles").firstElementChild;
  assert.deepEqual(lastTiles(view), [["Switches", "2"], ["Warnings", "0"]]);
  await view.state({ ...IDLE, last: { title: "Film", switches: 2 } });
  assert.equal($("lastTiles").firstElementChild, first);
  await view.state({ ...IDLE, last: { title: "Film", warnings: 4 } });
  assert.notEqual($("lastTiles").firstElementChild, first);
  assert.deepEqual(lastTiles(view), [["Switches", "0"], ["Warnings", "4"]]);
  // A title playing in between puts the card away and it is drawn afresh.
  const second = $("lastTiles").firstElementChild;
  await view.state(PLAYING);
  assert.equal(hidden($("lastCard")), true);
  assert.equal(hidden($("idleCard")), true);
  assert.equal(hidden($("historyIdleCard")), true);
  assert.equal(hidden($("eventsCard").querySelector(".tilegrid")), false);
  await view.state({ ...IDLE, last: { title: "Film", warnings: 4 } });
  assert.notEqual($("lastTiles").firstElementChild, second);
  assert.deepEqual(lastTiles(view), [["Switches", "0"], ["Warnings", "4"]]);
});

const cards = ({ $ }) => [...$("groups").children].map((card) =>
  [card.dataset.group, card.querySelector("summary").textContent, card.open]);

const rows = (card) => [...card.querySelector(".rows").children].map((row) =>
  [row.querySelector(".k").textContent, row.querySelector(".v").textContent]);

test("a playing title lays its groups out in a fixed order, unknown ones last and folded", async (t) => {
  const view = open(t);
  const group = (id, title) => ({ id, title, rows: [] });
  await view.state({ ...PLAYING, groups: [group("hdr", "HDR"), group("extra", "Extra"),
                                          group("audio", "Audio"), group("system", "System"),
                                          group("video", "Video")] });
  assert.deepEqual(cards(view), [["video", "Video", true], ["audio", "Audio", true],
                                 ["system", "System", true], ["hdr", "HDR", false],
                                 ["extra", "Extra", false]]);
});

test("a group that arrives late takes its place, and one that goes away is taken off", async (t) => {
  const view = open(t);
  const { $ } = view;
  const group = (id) => ({ id, title: id.toUpperCase(), rows: [] });
  await view.state({ ...PLAYING, groups: [group("video"), group("system")] });
  const video = $("groups").firstElementChild;
  await view.state({ ...PLAYING, groups: [group("system"), group("dv"), group("video")] });
  assert.deepEqual(cards(view).map(([id]) => id), ["video", "dv", "system"]);
  assert.equal($("groups").firstElementChild, video, "a card is kept, not rebuilt");
  await view.state({ ...PLAYING, groups: [group("video")] });
  assert.deepEqual(cards(view).map(([id]) => id), ["video"]);
  // A snapshot without groups takes them all off.
  await view.state({ ...PLAYING, groups: undefined });
  assert.equal($("groups").children.length, 0);
});

test("rows keep the snapshot's order, are written only when they change and leave when dropped", async (t) => {
  const view = open(t);
  const { $ } = view;
  const res = { id: "video.res", label: "Resolution", value: "2160p", detail: "" };
  const hdr = { id: "video.hdr", label: "HDR", value: "Dolby Vision ✔", detail: "(FEL)" };
  const fps = { id: "video.fps", label: "Frame rate", value: "23.976", detail: "" };
  const video = (...list) => ({ ...PLAYING, groups: [{ id: "video", title: "Video", rows: list }] });

  await view.state(video(res, hdr));
  const card = $("groups").firstElementChild;
  assert.deepEqual(rows(card), [["Resolution", "2160p"], ["HDR", "Dolby Vision   (FEL)"]]);
  const hdrValue = card.querySelectorAll(".row .v")[1];
  assert.equal(hdrValue.querySelector("img").alt, "Yes");
  assert.equal(hdrValue.querySelector(".d").textContent, "(FEL)");
  const resText = card.querySelector(".row .v").firstChild;

  await view.state(video(res, fps, hdr));
  assert.deepEqual(rows(card).map(([label]) => label), ["Resolution", "Frame rate", "HDR"]);
  assert.equal(card.querySelector(".row .v").firstChild, resText, "an unchanged row is left alone");

  await view.state(video({ ...res, value: "1080p" }, hdr));
  assert.deepEqual(rows(card), [["Resolution", "1080p"], ["HDR", "Dolby Vision   (FEL)"]]);
});

test("only the two per-frame L1 summaries flash when they change, and the flash fades", async (t) => {
  const view = open(t);
  const { $, clock } = view;
  const snapshot = (max, avg, other) => ({ ...PLAYING, groups: [{ id: "metadata", title: "Metadata", rows: [
    { id: "metadata.32269", label: "L1 max", value: max, detail: "" },
    { id: "metadata.32270", label: "L1 avg", value: avg, detail: "" },
    { id: "metadata.other", label: "Other", value: other, detail: "" }] }] });
  const flashing = () => [...$("groups").querySelectorAll(".row")]
    .filter((row) => row.classList.contains("changed"))
    .map((row) => row.querySelector(".k").textContent);

  await view.state(snapshot("1000", "120", "a"));
  assert.deepEqual(flashing(), [], "nothing flashes on its first value");
  await view.state(snapshot("1000", "120", "a"));
  assert.deepEqual(flashing(), []);
  await view.state(snapshot("980", "118", "b"));
  assert.deepEqual(flashing(), ["L1 max", "L1 avg"]);
  clock.tick(500);
  await view.state(snapshot("960", "118", "b"));
  clock.tick(300);
  assert.deepEqual(flashing(), ["L1 max"], "a second change starts the fade over");
  clock.tick(450);
  assert.deepEqual(flashing(), []);
});

/* --- the library ------------------------------------------------------ */

test("a box that will not be told what to play shows no shelves and reads none", async (t) => {
  const view = open(t, { routes: LIBRARY });
  await view.state({ ...IDLE, control: false });
  await view.state({ ...PLAYING, control: false });
  for (const path of ["/api/library", "/api/series", "/api/continue"]) assert.equal(reads(view, path), 0, path);
  for (const id of ["filmsCard", "seriesCard", "continueFilmsCard", "continueSeriesCard"]) {
    assert.equal(hidden(view.$(id)), true, id);
  }
});

test("the shelves hidden while control is withdrawn come back with it", async (t) => {
  const view = open(t, { routes: LIBRARY });
  const shelves = ["filmsCard", "seriesCard", "continueFilmsCard", "continueSeriesCard"];
  await view.state(IDLE);
  for (const id of shelves) assert.equal(hidden(view.$(id)), false, id);
  await view.state({ ...IDLE, control: false });
  for (const id of shelves) assert.equal(hidden(view.$(id)), true, id);
  await view.state(IDLE);
  for (const id of shelves) assert.equal(hidden(view.$(id)), false, id);
});

test("the shelves are read on arrival and again when a title ends, not on every snapshot", async (t) => {
  const view = open(t, { routes: LIBRARY });
  const counts = () => ["/api/library", "/api/series", "/api/continue"].map((path) => reads(view, path));
  await view.state(IDLE);
  assert.deepEqual(counts(), [1, 1, 1]);
  assert.equal(hidden(view.$("filmsCard")), false);
  assert.equal(view.$("filmGrid").children.length, 2);
  await view.state(IDLE);
  await view.state(PLAYING);
  await view.state(PLAYING);
  assert.deepEqual(counts(), [1, 1, 1]);
  await view.state(IDLE);
  assert.deepEqual(counts(), [2, 2, 2]);
});

test("a new library version marks every list unread, and the open show is read again", async (t) => {
  const view = open(t, { routes: LIBRARY });
  const counts = () => ["/api/library", "/api/series", "/api/continue", "/api/episodes"]
    .map((path) => reads(view, path));
  await view.state({ ...PLAYING, library: 1 });
  assert.deepEqual(counts(), [1, 1, 1, 0]);
  await view.state({ ...PLAYING, library: 1 });
  assert.deepEqual(counts(), [1, 1, 1, 0]);
  view.$("seriesGrid").querySelector(".film").click();
  answer(view, "play");
  await settle();
  assert.deepEqual(counts(), [1, 1, 1, 1]);
  await view.state({ ...PLAYING, library: 2 });
  assert.deepEqual(counts(), [2, 2, 2, 2]);
  // An add-on older than the number sends none, and nothing is read for it.
  await view.state({ ...PLAYING, library: undefined });
  assert.deepEqual(counts(), [2, 2, 2, 2]);
});

test("a playing snapshot gives back the wall, the row and the show a press was waiting on", async (t) => {
  const view = open(t, { routes: { ...LIBRARY, "/api/play": [200, {}] } });
  const { $ } = view;
  await view.state(IDLE);
  $("seriesGrid").querySelector(".film").click();
  answer(view, "play");
  await settle();
  const press = async (tile) => {
    tile.click();
    answer(view, "play");
    await settle();
  };
  await press($("filmGrid").children[1]);
  await press($("continueFilmsRow").firstElementChild);
  await press($("episodeList").querySelector(".episode"));
  const waiting = [$("filmGrid").children[0], $("continueSeriesRow").firstElementChild,
                   $("episodeList").querySelectorAll(".episode")[1]];
  assert.equal(reads(view, "/api/play"), 3);
  for (const tile of waiting) assert.equal(tile.disabled, true);
  await view.state(PLAYING);
  for (const tile of waiting) assert.equal(tile.disabled, false);
  assert.equal(view.window.document.querySelectorAll(".busy").length, 0);
});

/* --- VS10 ------------------------------------------------------------- */

const VS10 = { output: "DV-LL BT.2020", options: [{ mode: "auto", label: "Auto" },
                                                  { mode: "sdr", label: "SDR BT.709" }] };
const modes = ({ $ }) => [...$("modes").children].map((button) =>
  [button.dataset.mode, button.textContent, button.type, button.className]);

test("VS10 offers its modes only to a box that will switch them, and keeps its buttons", async (t) => {
  const view = open(t);
  const { $ } = view;
  await view.state({ ...PLAYING, control: false, vs10: VS10 });
  assert.equal(hidden($("vs10Card")), true);
  await view.state({ ...PLAYING, vs10: VS10 });
  assert.equal(hidden($("vs10Card")), false);
  assert.equal($("vs10Out").textContent, "DV-LL BT.2020");
  assert.deepEqual(modes(view), [["auto", "Auto", "button", "mode"],
                                 ["sdr", "SDR BT.709", "button", "mode"]]);
  const auto = $("modes").firstElementChild;
  await view.state({ ...PLAYING, vs10: { ...VS10, output: "SDR BT.709" } });
  assert.equal($("modes").firstElementChild, auto, "the same modes keep their buttons");
  assert.equal($("vs10Out").textContent, "SDR BT.709");
  await view.state({ ...PLAYING, vs10: { options: [{ mode: "hdr10", label: "HDR10" }] } });
  assert.deepEqual(modes(view), [["hdr10", "HDR10", "button", "mode"]]);
  assert.equal($("vs10Out").textContent, "N/A");
  await view.state({ ...PLAYING, vs10: { output: "SDR", options: [] } });
  assert.equal(hidden($("vs10Card")), true);
  await view.state({ ...PLAYING, vs10: VS10 });
  await view.state({ ...PLAYING, vs10: undefined });
  assert.equal(hidden($("vs10Card")), true);
});

test("a mode switch posts the mode with the token and keeps the buttons locked while the driver settles", async (t) => {
  const view = open(t, { token: "T0K3N", routes: { "/api/mode": [200, {}] } });
  const { $, clock } = view;
  await view.state({ ...PLAYING, vs10: VS10 });
  const [, sdr] = $("modes").children;
  sdr.click();
  assert.deepEqual([...$("modes").children].map((button) => button.disabled), [true, true]);
  assert.equal(sdr.classList.contains("busy"), true);
  assert.equal($("toast").textContent, "Switching…");
  await settle();
  const sent = view.requests.filter((request) => request.url === "/api/mode");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].init.method, "POST");
  assert.equal(sent[0].init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.equal(sent[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(sent[0].init.body), { mode: "sdr" });
  assert.equal($("toast").textContent, "Switched");
  assert.equal($("toast").classList.contains("bad"), false);

  // New modes arriving mid-switch are drawn locked like the others, and a
  // press that reaches one all the same is dropped while the switch is still
  // settling.
  await view.state({ ...PLAYING, vs10: { ...VS10, options: [{ mode: "hdr10", label: "HDR10" }] } });
  assert.deepEqual(modes(view), [["hdr10", "HDR10", "button", "mode"]]);
  assert.equal($("modes").firstElementChild.disabled, true);
  $("modes").firstElementChild.dispatchEvent(new view.window.MouseEvent("click"));
  await settle();
  assert.equal(view.requests.filter((request) => request.url === "/api/mode").length, 1);

  clock.tick(1199);
  assert.equal(sdr.classList.contains("busy"), true);
  clock.tick(1);
  assert.equal(sdr.classList.contains("busy"), false);
  assert.equal($("modes").firstElementChild.disabled, false);
  $("modes").firstElementChild.click();
  await settle();
  const last = view.requests.filter((request) => request.url === "/api/mode").at(-1);
  assert.deepEqual(JSON.parse(last.init.body), { mode: "hdr10" });
});

test("a refused or failed mode switch says so", async (t) => {
  const view = open(t, { routes: { "/api/mode": [401, {}] } });
  const { window, $, clock, routes } = view;
  await view.state({ ...PLAYING, vs10: VS10 });
  const toast = () => [$("toast").textContent, $("toast").classList.contains("bad")];

  $("modes").firstElementChild.click();
  await settle();
  assert.deepEqual(toast(), ["Wrong or missing token", true]);
  assert.equal($("tokenDialog").open, true);

  clock.tick(1200);
  routes["/api/mode"] = [500, {}];
  $("modes").firstElementChild.click();
  await settle();
  assert.deepEqual(toast(), ["Switching failed", true]);

  clock.tick(1200);
  const fetch = window.fetch;
  window.fetch = (url, init) => (url === "/api/mode"
    ? Promise.reject(new TypeError("Failed to fetch")) : fetch(url, init));
  $("toast").textContent = "";
  $("modes").firstElementChild.click();
  await settle();
  assert.deepEqual(toast(), ["Switching failed", true]);
  clock.tick(1200);
  assert.equal($("modes").firstElementChild.disabled, false);
});

/* --- the report ------------------------------------------------------- */

test("the report of a playing title lists its groups in order, the summary and the events", async (t) => {
  const view = open(t, { routes: { "/api/history": [200, HISTORY] } });
  const { window, $, copied } = view;
  const line = window.TinyPPI.reportLine;
  await view.state({
    ...PLAYING, title: "Film: The Cut", session: { seq: 3, switches: 1, warnings: 2 },
    groups: [
      { id: "audio", title: "Audio", rows: [
        { id: "audio.32238", label: "Codec", value: "TrueHD Atmos 7.1", detail: "48 kHz" }] },
      { id: "video", title: "Video", rows: [
        { id: "video.res", label: "Resolution", value: "3840x2160p", detail: "" },
        { id: "video.hdr", label: "HDR10 / HLG", value: "✔ / ✘", detail: "(MEL)" },
        { id: "video.dv", label: "Dolby Vision", value: "✔", detail: "" },
        { id: "video.note", label: "Note", value: "", detail: "" }] }],
  });
  $("copyBtn").click();
  await settle();
  assert.equal(copied.length, 1);
  assert.equal(copied[0], [
    "TinyPPI", "Film: The Cut", "/media/Film.mkv", "",
    "[Video]",
    line("Resolution", "3840x2160p"),
    line("HDR10 / HLG", "Yes | No | MEL"),
    line("Dolby Vision", "Yes"),
    line("Note", ""),
    "",
    "[Audio]",
    line("Codec", "TrueHD Atmos 7.1  48 kHz"),
    "",
    "[Summary]",
    line("Peak", "812 nits"),
    line("Switches", "1"),
    line("Warnings", "2"),
    "",
    "[Events]",
    line("00:00:10  FPS", "60 ▲"),
    line("Audio track", "Deutsch"),
    line("00:00:13  Temperature", "77 °C"),
    "",
  ].join("\n"));
  assert.equal($("toast").textContent, "Copied");
});

test("a bare playing snapshot gives a bare report", async (t) => {
  const view = open(t);
  const line = view.window.TinyPPI.reportLine;
  await view.state({ seq: 1, playing: true, control: true });
  view.$("copyBtn").click();
  await settle();
  assert.deepEqual(view.copied, [["TinyPPI", "", "[Summary]", line("Switches", "0"),
                                  line("Warnings", "0"), ""].join("\n")]);
});

test("after the credits the report is of the title that was, with its own peak or the samples'", async (t) => {
  const view = open(t, { routes: { "/api/history": [200, HISTORY] } });
  const { $, copied } = view;
  const line = view.window.TinyPPI.reportLine;
  const events = ["[Events]", line("00:00:10  FPS", "60 ▲"), line("Audio track", "Deutsch"),
                  line("00:00:13  Temperature", "77 °C"), ""];
  const last = { title: "Film", switches: 3, warnings: 0, events: 3 };

  await view.state({ ...IDLE, last: { ...last, peak: 640.2 } });
  $("copyBtn").click();
  await settle();
  assert.equal(copied.at(-1), ["TinyPPI", "Film", "", "[Summary]", line("Peak", "640 nits"),
                               line("Switches", "3"), line("Warnings", "0"), "",
                               ...events].join("\n"));

  await view.state({ ...IDLE, last });
  $("copyBtn").click();
  await settle();
  assert.equal(copied.at(-1).split("\n")[4], line("Peak", "812 nits"));

  await view.state({ ...IDLE, last: { ...last, peak: null } });
  $("copyBtn").click();
  await settle();
  assert.equal(copied.at(-1).split("\n")[4], line("Switches", "3"), "no peak to print");
});

test("the report key copies nothing before a snapshot, nor for an idle box that has played nothing", async (t) => {
  const view = open(t);
  const { window, $, copied } = view;
  const press = () => $("copyBtn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  assert.equal($("copyBtn").disabled, true);
  press();
  await settle();
  await view.state(IDLE);
  press();
  await settle();
  assert.deepEqual(copied, []);
  assert.equal($("toast").textContent, "");
});

test("where the clipboard is refused the report is saved under the title's name", async (t) => {
  const saved = [];
  const revoked = [];
  const view = open(t, { before: (w) => {
    Object.defineProperty(w.navigator, "clipboard", {
      configurable: true,
      value: { writeText: async () => { throw new w.DOMException("denied", "NotAllowedError"); } },
    });
    w.URL.createObjectURL = () => "blob:report";
    w.URL.revokeObjectURL = (url) => { revoked.push(url); };
    w.HTMLAnchorElement.prototype.click = function () { saved.push(this.download); };
  } });
  const { $, clock } = view;
  await view.state({ ...PLAYING, title: "Film: The Cut" });
  $("copyBtn").click();
  await settle();
  await view.state({ ...IDLE, last: { title: "Other Film" } });
  $("copyBtn").click();
  await settle();
  assert.deepEqual(saved, ["TinyPPI_Film_The_Cut.txt", "TinyPPI_Other_Film.txt"]);
  clock.tick(2000);
  assert.deepEqual(revoked, ["blob:report", "blob:report"]);
});

test("the metadata key copies the Dolby Vision list", async (t) => {
  const view = open(t);
  await view.state(PLAYING);
  view.$("copyMetaBtn").click();
  await settle();
  const report = view.copied.at(-1).split("\n");
  assert.equal(report[0], "TinyPPI — Dolby Vision metadata view");
  assert.ok(report.includes(view.window.TinyPPI.reportLine("L1 max", "1000")));
});
