// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// Arranging the cards on a tab and the tabs on the bar
// (resources/web/js/cards.js, and the hidden tabs in js/dashboard.js): the
// order rule the app shares, a heading pressed to open a tab for arranging,
// moving and taking cards off it, the line a tab with nothing left on it
// shows, putting everything back, and the switches for the tabs.  The whole
// page is loaded in the order index.html gives.

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

function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/** The page's timers on a clock only the test moves. */
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

const FILMS = [
  { id: 1, title: "Alien", year: 1979, watched: true, added: "2026-09-01 10:00:00" },
  { id: 2, title: "Brazil", year: 1985, added: "2026-09-03 10:00:00" },
];

/** The dashboard with a film shelf, a series shelf and control allowed, the
 * first idle snapshot delivered.  *stored* is put in the page's storage
 * before it loads, as a reader's earlier visit would have left it. */
async function open(t, { stored = {}, raw = {} } = {}) {
  const routes = {
    "/api/details": [200, {}],
    "/api/hello": [200, { version: "2.20.0", strings: {} }],
    "/api/library": [200, { tag: "f1", movies: FILMS }],
    "/api/series": [200, { tag: "s1", shows: [{ id: 1, title: "Andor", unseen: 2 }] }],
    "/api/continue": [200, { tag: "c1", items: [] }],
  };
  const view = page({ scripts: [], routes });
  const { window, dom } = view;
  t.after(() => window.close());
  const clock = fakeClock(window);
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  for (const [key, value] of Object.entries(stored)) {
    window.localStorage.setItem(key, JSON.stringify(value));
  }
  for (const [key, value] of Object.entries(raw)) window.localStorage.setItem(key, value);
  for (const name of ORDER) load(dom, name);
  await settle();
  const result = {
    ...view, clock,
    $: (id) => window.document.getElementById(id),
    async state(snapshot) {
      view.streams.at(-1).emit("state", snapshot);
      await settle();
    },
  };
  await result.state({ playing: false, control: true, seq: 1 });
  await settle();
  return result;
}

const heading = (view, id) => view.$(id).querySelector(":scope > .panel-toggle");

/** Right-click a card's heading, which opens its tab for arranging. */
async function arrange(view, id) {
  heading(view, id).dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
}

const arranger = (view, tab) => view.$("tab-" + tab).querySelector(":scope > .arranger");
const rowsOf = (view, tab) => [...arranger(view, tab).querySelectorAll(".arrangerow")];
const rowOf = (view, tab, id) => rowsOf(view, tab).find((row) => row.dataset.card === id);
const listed = (view, tab) => rowsOf(view, tab).map((row) => row.dataset.card);
const order = (view, id) => Number(view.$(id).style.order);
const stored = (view) => JSON.parse(view.window.localStorage.getItem("tinyppi.cards"));
const offered = ({ window }) =>
  [...window.document.querySelectorAll("#tabBar .tab:not(.hidden)")].map((key) => key.dataset.tab);

async function pressKey(view, tab, id, kind) {
  rowOf(view, tab, id).querySelector(".arrange-" + kind).click();
  await settle();
}

test("the order rule is the app's: stored cards first, new ones after the card they follow", async (t) => {
  const view = await open(t);
  const { arrangeCards, moveCard } = view.window;
  const plain = (value) => JSON.parse(JSON.stringify(value));
  assert.deepEqual(plain(arrangeCards([], ["a", "b", "c"])), ["a", "b", "c"]);
  assert.deepEqual(plain(arrangeCards(["c", "a"], ["a", "b", "c"])), ["c", "a", "b"]);
  // A card new to the reader that follows nothing goes to the top.
  assert.deepEqual(plain(arrangeCards(["b"], ["a", "b"])), ["a", "b"]);
  // A stored card that is not there now is left out, and kept by a move.
  assert.deepEqual(plain(arrangeCards(["x", "b", "a"], ["a", "b"])), ["b", "a"]);
  assert.deepEqual(plain(moveCard(["x", "b", "a"], ["a", "b"], "a", -1)), ["a", "b", "x"]);
  assert.equal(moveCard([], ["a", "b"], "a", -1), null);
  assert.equal(moveCard([], ["a", "b"], "b", 1), null);
  assert.equal(moveCard([], ["a", "b"], "z", 1), null);
  // A move that cannot be made stores nothing.
  view.window.moveCardBy("films", "recentFilmsCard", -1);
  assert.equal(view.window.localStorage.getItem("tinyppi.cards"), null);
});

test("storage that is broken, blocked or holds something else leaves every card where it is", async (t) => {
  const broken = await open(t, { raw: { "tinyppi.cards": "{not json",
                                        "tinyppi.hiddentabs": "{not json" } });
  assert.equal(broken.$("cardsReset").disabled, true);
  assert.ok(offered(broken).includes("films"));

  const odd = await open(t, { stored: { "tinyppi.cards": 5, "tinyppi.hiddentabs": "films" } });
  assert.equal(odd.$("cardsReset").disabled, true);
  assert.equal(offered(odd).includes("films"), false);

  // Storage that will not be written to: the page goes on, unremembered.
  const full = await open(t);
  full.window.Storage.prototype.setItem = () => { throw new Error("quota"); };
  await arrange(full, "filmsCard");
  await pressKey(full, "films", "filmsCard", "up");
  assert.deepEqual(listed(full, "films"), ["recentFilmsCard", "filmsCard", "unseenFilmsCard"]);
  full.window.setTabHidden("history", true);
  assert.equal(offered(full).includes("history"), false);
});

test("a card is listed by its heading, or by its name while it has none", async (t) => {
  const view = await open(t);
  view.$("filmsLabel").textContent = "";
  // What the last title came to is listed by its own label.
  view.$("lastCard").classList.remove("hidden");
  view.$("lastLabel").textContent = "Last played";
  await settle();
  await arrange(view, "filmsCard");
  assert.equal(rowOf(view, "films", "filmsCard").querySelector(".arrangelabel span").textContent,
               "filmsCard");
  view.$("lastCard").querySelector(".lasthead").dispatchEvent(
    new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  // Opening another tab ends the arranging of the first.
  assert.equal(arranger(view, "films"), null);
  assert.equal(view.$("tab-films").classList.contains("arranging"), false);
  assert.equal(rowOf(view, "history", "lastCard").querySelector(".arrangelabel span").textContent,
               "Last played");
});

test("a right click away from a card's heading is left to the page", async (t) => {
  const view = await open(t);
  const event = new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
  view.$("tabbtn-films").dispatchEvent(event);
  assert.equal(event.defaultPrevented, false);
  // Nor is the card of what is playing arranged from.
  view.$("nowCard").dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(arranger(view, "live"), null);
});

test("a right click on a card's heading opens its tab for arranging, listing the cards there", async (t) => {
  const view = await open(t);
  await arrange(view, "filmsCard");
  const panel = view.$("tab-films");
  assert.equal(panel.classList.contains("arranging"), true);
  assert.equal(panel.firstElementChild, arranger(view, "films"));
  // The row of half-watched films is not there, so it is not listed.
  assert.deepEqual(listed(view, "films"), ["recentFilmsCard", "unseenFilmsCard", "filmsCard"]);
  assert.equal(rowOf(view, "films", "filmsCard").querySelector(".arrangelabel span").textContent,
               view.$("filmsLabel").textContent);
  assert.equal(rowOf(view, "films", "recentFilmsCard").querySelector(".arrange-up").disabled, true);
  assert.equal(rowOf(view, "films", "filmsCard").querySelector(".arrange-down").disabled, true);
  assert.equal(rowOf(view, "films", "unseenFilmsCard").querySelector(".arrange-up").disabled, false);

  arranger(view, "films").querySelector(".arrangedone").click();
  assert.equal(panel.classList.contains("arranging"), false);
  assert.equal(arranger(view, "films"), null);
});

test("a poster's own press is left alone: only a heading opens the arranging", async (t) => {
  const view = await open(t);
  const poster = view.$("filmGrid").firstElementChild;
  poster.dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(arranger(view, "films"), null);
  assert.equal(view.$("detailsDialog").open, true);
});

test("a long press on a heading opens the arranging, and does not fold the card", async (t) => {
  const view = await open(t);
  const summary = heading(view, "unseenFilmsCard");
  const card = view.$("unseenFilmsCard");
  const was = card.open;
  summary.dispatchEvent(new view.window.PointerEvent("pointerdown", { bubbles: true, button: 0 }));
  view.clock.tick(499);
  assert.equal(arranger(view, "films"), null);
  view.clock.tick(1);
  assert.ok(arranger(view, "films"));
  summary.dispatchEvent(new view.window.PointerEvent("pointerup", { bubbles: true }));
  summary.click();
  assert.equal(card.open, was);
});

test("a short press, a press that moves off, another button or a press elsewhere opens nothing", async (t) => {
  const view = await open(t);
  const summary = heading(view, "unseenFilmsCard");
  const down = (node, init = {}) => node.dispatchEvent(
    new view.window.PointerEvent("pointerdown", { bubbles: true, button: 0, ...init }));
  const up = (node) => node.dispatchEvent(new view.window.PointerEvent("pointerup", { bubbles: true }));

  down(summary);
  view.clock.tick(200);
  up(summary);
  view.clock.tick(1000);

  down(summary, { clientX: 0, clientY: 0 });
  summary.dispatchEvent(new view.window.PointerEvent("pointermove", { bubbles: true, clientX: 4, clientY: 3 }));
  summary.dispatchEvent(new view.window.PointerEvent("pointermove", { bubbles: true, clientX: 40, clientY: 0 }));
  view.clock.tick(1000);
  up(summary);
  // A pointer moving with nothing held does nothing either.
  summary.dispatchEvent(new view.window.PointerEvent("pointermove", { bubbles: true, clientX: 90, clientY: 0 }));

  down(summary, { button: 2 });
  view.clock.tick(1000);
  down(view.$("tabbtn-films"));
  view.clock.tick(1000);
  assert.equal(arranger(view, "films"), null);
});

test("moving a card changes where the tab draws it, and is kept for the next visit", async (t) => {
  const view = await open(t);
  await arrange(view, "filmsCard");
  await pressKey(view, "films", "filmsCard", "up");
  assert.deepEqual(listed(view, "films"), ["recentFilmsCard", "filmsCard", "unseenFilmsCard"]);
  assert.ok(order(view, "filmsCard") < order(view, "unseenFilmsCard"));
  assert.ok(order(view, "recentFilmsCard") < order(view, "filmsCard"));
  // The head with the search stays above every card.
  assert.equal(Number(view.$("filmsHead").style.order || 0), 0);
  assert.deepEqual(stored(view).orders.films,
                   ["recentFilmsCard", "filmsCard", "unseenFilmsCard"]);

  const again = await open(t, { stored: { "tinyppi.cards": stored(view) } });
  assert.ok(order(again, "filmsCard") < order(again, "unseenFilmsCard"));
  // The row that was away when the order was stored lands where it would have.
  assert.ok(order(again, "continueFilmsCard") < order(again, "recentFilmsCard"));
});

test("a card taken off the tab is still listed, faded, and can be put back", async (t) => {
  const view = await open(t);
  await arrange(view, "unseenFilmsCard");
  await pressKey(view, "films", "unseenFilmsCard", "hide");
  assert.equal(view.$("unseenFilmsCard").classList.contains("userhidden"), true);
  const row = rowOf(view, "films", "unseenFilmsCard");
  assert.equal(row.classList.contains("off"), true);
  assert.equal(row.querySelector("small").textContent, "Hidden");
  assert.deepEqual(stored(view).hidden, ["films/unseenFilmsCard"]);

  // The shelf read again leaves it off.
  view.$("unseenFilmsCard").classList.remove("hidden");
  await settle();
  assert.equal(view.$("unseenFilmsCard").classList.contains("userhidden"), true);

  await pressKey(view, "films", "unseenFilmsCard", "show");
  assert.equal(view.$("unseenFilmsCard").classList.contains("userhidden"), false);
  assert.deepEqual(stored(view).hidden, []);
});

test("a tab with every card taken off says so, with the way back", async (t) => {
  const view = await open(t, { stored: { "tinyppi.cards": { orders: {}, hidden: [
    "films/recentFilmsCard", "films/unseenFilmsCard", "films/filmsCard"] } } });
  const note = view.$("tab-films").querySelector(".allhidden");
  assert.ok(note);
  assert.equal(note.querySelector("p").textContent, "Every card on this tab is hidden.");
  note.querySelector("button").click();
  await settle();
  assert.ok(arranger(view, "films"));
  await pressKey(view, "films", "filmsCard", "show");
  assert.equal(view.$("tab-films").querySelector(".allhidden"), null);
});

test("reset puts one tab back; the settings put every tab back", async (t) => {
  const view = await open(t, { stored: { "tinyppi.cards": {
    orders: { films: ["filmsCard"], series: ["seriesCard"] },
    hidden: ["films/recentFilmsCard", "series/unseenSeriesCard"] } } });
  assert.equal(view.$("cardsReset").disabled, false);
  assert.ok(order(view, "filmsCard") < order(view, "recentFilmsCard"));

  await arrange(view, "filmsCard");
  arranger(view, "films").querySelector(".arrangereset").click();
  await settle();
  assert.ok(order(view, "recentFilmsCard") < order(view, "filmsCard"));
  assert.equal(view.$("recentFilmsCard").classList.contains("userhidden"), false);
  assert.equal(view.$("unseenSeriesCard").classList.contains("userhidden"), true);

  view.$("cardsReset").click();
  await settle();
  assert.equal(view.$("unseenSeriesCard").classList.contains("userhidden"), false);
  assert.deepEqual(stored(view), { orders: {}, hidden: [] });
  assert.equal(view.$("cardsReset").disabled, true);
});

test("the readings on the live tab move among themselves, not into the cards over them", async (t) => {
  const view = await open(t);
  await view.state({ playing: true, control: true, seq: 2, title: "Alien",
    groups: [{ id: "video", title: "Video", rows: [] }, { id: "audio", title: "Audio", rows: [] }] });
  const groups = [...view.$("groups").children].map((card) => card.dataset.group);
  assert.deepEqual(groups, ["video", "audio"]);
  const video = view.$("groups").children[0];
  video.querySelector(".panel-toggle").dispatchEvent(
    new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.ok(arranger(view, "live"));
  const ids = listed(view, "live");
  assert.ok(ids.includes("group.video") && ids.includes("group.audio"));
  assert.equal(ids.includes("nowCard"), false);
  // The first reading cannot go up among the cards under what is playing.
  assert.equal(rowOf(view, "live", "group.video").querySelector(".arrange-up").disabled, true);
  await pressKey(view, "live", "group.audio", "up");
  assert.ok(Number(view.$("groups").children[1].style.order) <
            Number(view.$("groups").children[0].style.order));
});

test("a tab switched off in the settings leaves the bar, and comes back when switched on", async (t) => {
  const view = await open(t);
  const switches = () => [...view.$("tabSwitches").querySelectorAll("input")];
  assert.deepEqual(switches().map((input) => input.dataset.tab),
                   ["metadata", "films", "series", "history"]);
  assert.ok(switches().every((input) => input.checked));
  assert.ok(offered(view).includes("films"));

  view.window.selectTab("films");
  const films = switches().find((input) => input.dataset.tab === "films");
  films.checked = false;
  films.dispatchEvent(new view.window.Event("change"));
  assert.equal(offered(view).includes("films"), false);
  // The tab that was in front goes, and the live one takes its place.
  assert.equal(view.window.document.querySelector(".tabpanel.active").dataset.tab, "live");
  view.window.selectTab("films");
  assert.equal(view.window.document.querySelector(".tabpanel.active").dataset.tab, "live");
  assert.deepEqual(JSON.parse(view.window.localStorage.getItem("tinyppi.hiddentabs")), ["films"]);

  const again = await open(t, { stored: { "tinyppi.hiddentabs": ["films"] } });
  assert.equal(offered(again).includes("films"), false);
  const back = [...again.$("tabSwitches").querySelectorAll("input")]
    .find((input) => input.dataset.tab === "films");
  assert.equal(back.checked, false);
  back.checked = true;
  back.dispatchEvent(new again.window.Event("change"));
  assert.equal(offered(again).includes("films"), true);
});

test("live and the settings cannot be switched off, and a stored name that is no tab is ignored", async (t) => {
  const view = await open(t, { stored: { "tinyppi.hiddentabs": ["live", "settings", "nowhere"] } });
  assert.ok(offered(view).includes("live"));
  assert.ok(offered(view).includes("settings"));
  view.window.setTabHidden("live", true);
  assert.ok(offered(view).includes("live"));
});
