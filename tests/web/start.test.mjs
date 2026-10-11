// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// Starting the dashboard (resources/web/js/start.js): the tab it opens on --
// the one the address names, else the one this device was left on, else the
// live one -- the stream it connects, and the words it writes into the page
// before and after /api/hello answers.  The whole page is loaded in the order
// index.html gives.

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
 * does, so that the page can be prepared (storage, address) first. */
function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/** The dashboard as index.html loads it, with the page's timers held (none
 * of them is wanted here) and the window closed when the test ends.
 * *before* runs on the bare page ahead of the scripts. */
function open(t, { hello = { version: "2.15.0", strings: {} }, status = 200, before } = {}) {
  const view = page({ scripts: [], routes: { "/api/hello": [status, hello] } });
  const { window, dom } = view;
  t.after(() => window.close());
  window.setTimeout = () => 0;
  window.clearTimeout = () => {};
  window.requestAnimationFrame = () => 0;
  window.scrollTo = () => {};
  if (before) before(window);
  for (const name of ORDER) load(dom, name);
  return { ...view, $: (id) => window.document.getElementById(id) };
}

/** Which tab is in front, checking that its key and its panel agree. */
function front({ window }) {
  const doc = window.document;
  const lit = [...doc.querySelectorAll("#tabBar .tab.on")].map((key) => key.dataset.tab);
  const shown = [...doc.querySelectorAll(".tabpanel.active")].map((panel) => panel.dataset.tab);
  assert.deepEqual(shown, lit, "the panel in front belongs to the lit key");
  return lit.join(",");
}

/* What each localized string is written into: [element id, where, key]. */
const PLACES = [
  ["idleTitle", "text", "idle_title"], ["idleText", "text", "idle_text"],
  ["lastLabel", "text", "last_played"],
  ["historyIdleTitle", "text", "events_empty"], ["historyIdleText", "text", "idle_text"],
  ["continueFilmsLabel", "text", "continue"], ["continueSeriesLabel", "text", "continue"],
  ["themeHead", "text", "theme_menu"], ["tokenHead", "text", "token_title"],
  ["tokenNote", "text", "token_text"], ["tokenBtnText", "text", "token_enter"],
  ["reportHead", "text", "copy"], ["copyBtnText", "text", "report_live"],
  ["copyMetaBtnText", "text", "tab_metadata"], ["filmsLabel", "text", "films"],
  ["filmsEmpty", "text", "films_empty"],
  ["filmSearch", "placeholder", "films_search"], ["filmSearch", "aria-label", "films_search"],
  ["filmSearchClear", "aria-label", "search_clear"], ["filmSearchClear", "title", "search_clear"],
  ["seriesSearchClear", "aria-label", "search_clear"], ["seriesSearchClear", "title", "search_clear"],
  ["seriesLabel", "text", "series"], ["unseenFilmsLabel", "text", "films_unseen"],
  ["recentFilmsLabel", "text", "recent"], ["recentSeriesLabel", "text", "recent"],
  ["unseenSeriesLabel", "text", "series_unseen_shows"],
  ["markRestart", "text", "play_from_start"], ["markClear", "text", "resume_clear"],
  ["markWatched", "text", "mark_watched"], ["markUnwatched", "text", "mark_unwatched"],
  ["markCancel", "text", "cancel"],
  ["seriesBackText", "text", "series_back"], ["seriesBack", "aria-label", "series_back"],
  ["seriesEmpty", "text", "series_empty"],
  ["seriesSearch", "placeholder", "series_search"], ["seriesSearch", "aria-label", "series_search"],
  ["vs10Title", "text", "vs10"], ["vs10OutLabel", "text", "output"],
  // Handed on to the live panels and the metadata tab.
  ["eventsTitle", "text", "events"], ["metadataTitle", "text", "metadata_section"],
];
const TAB_KEYS = { live: "tab_live", metadata: "tab_metadata", films: "films",
                   series: "series", history: "tab_history", settings: "tab_settings" };

function written($, id, where) {
  const node = $(id);
  if (where === "text") return node.textContent;
  if (where === "placeholder") return node.placeholder;
  if (where === "title") return node.title;
  return node.getAttribute(where);
}

/* A whole set of words, each telling where it went. */
const GERMAN = Object.fromEntries(
  [...PLACES.map(([, , name]) => name), ...Object.values(TAB_KEYS)]
    .map((name) => [name, "de:" + name]));

test("with nothing asked for, the page opens on the live tab and connects", async (t) => {
  const view = open(t);
  assert.equal(front(view), "live");
  assert.equal(view.window.location.hash, "#live");
  assert.equal(view.window.localStorage.getItem("tinyppi.tab"), "live");
  assert.deepEqual(view.streams.map((stream) => stream.url), ["/api/stream"]);
  assert.deepEqual(view.requests.map((request) => request.url), ["/api/hello"]);
  // The stream feeds the page: a snapshot is drawn the moment it arrives.
  view.streams[0].emit("state", { seq: 1, playing: false, control: false });
  assert.equal(view.$("idleCard").classList.contains("hidden"), false);
  assert.equal(view.$("status").dataset.state, "live");
});

test("the address picks the first tab, the old metadata window's address too", async (t) => {
  for (const [address, tab] of [["#history", "history"], ["#series", "series"],
                                ["/metadata", "metadata"], ["/metadata.html", "metadata"],
                                ["/metadata.htm", "live"], ["#unknown", "live"]]) {
    const view = open(t, { before: (w) => { w.history.replaceState(null, "", address); } });
    assert.equal(front(view), tab, address);
  }
});

test("otherwise the page opens on the tab this device was last left on", (t) => {
  const stored = (name) => (w) => { w.localStorage.setItem("tinyppi.tab", name); };
  assert.equal(front(open(t, { before: stored("settings") })), "settings");
  assert.equal(front(open(t, { before: stored("no-such-tab") })), "live");
  // The address wins over the device.
  const both = open(t, { before: (w) => { stored("settings")(w); w.location.hash = "#films"; } });
  assert.equal(front(both), "films");
});

test("until /api/hello answers, the frame carries the built-in English", (t) => {
  const { $, window } = open(t);
  // Nothing has been awaited: boot has only drawn and connected so far.
  assert.equal($("idleTitle").textContent, "Nothing is playing");
  assert.equal($("historyIdleTitle").textContent, "No events yet");
  assert.equal($("filmSearch").placeholder, "Search films");
  assert.equal($("markCancel").textContent, "Cancel");
  assert.equal($("tokenHead").textContent, "Access token");
  assert.equal($("vs10Title").textContent, "VS10 output");
  assert.equal($("continueFilmsLabel").textContent, "Continue watching");
  assert.equal($("recentSeriesLabel").textContent, "Recently added");
  assert.equal($("unseenFilmsLabel").textContent, "Unwatched films");
  assert.equal($("unseenSeriesLabel").textContent, "Unwatched series");
  assert.equal($("markRestart").textContent, "Play from the beginning");
  assert.equal($("markClear").textContent, "Clear resume point");
  assert.equal($("markWatched").textContent, "Mark as watched");
  assert.equal($("markUnwatched").textContent, "Mark as unwatched");
  assert.equal($("version").textContent, "");
  const live = window.document.querySelector('#tabBar .tab[data-tab="live"]');
  assert.equal(live.getAttribute("aria-label"), "Live");
  assert.equal(live.title, "Live");
});

test("the localized words replace them once /api/hello answers, with the version", async (t) => {
  const view = open(t, { hello: { version: "2.15.0", strings: GERMAN } });
  await settle();
  const { $, window } = view;
  for (const [id, where, name] of PLACES) {
    assert.equal(written($, id, where), "de:" + name, `${id} ${where}`);
  }
  for (const button of window.document.querySelectorAll("#tabBar .tab")) {
    const words = "de:" + TAB_KEYS[button.dataset.tab];
    assert.equal(button.getAttribute("aria-label"), words);
    assert.equal(button.title, words);
  }
  assert.equal($("version").textContent, "v2.15.0");
});

test("a key the bar does not know is given an empty name rather than a wrong one", async (t) => {
  const view = open(t, { before: (w) => {
    const stray = w.document.createElement("button");
    stray.className = "tab";
    stray.dataset.tab = "stray";
    stray.title = "left over";
    w.document.getElementById("tabBar").append(stray);
  } });
  await settle();
  const stray = view.window.document.querySelector('.tab[data-tab="stray"]');
  assert.equal(stray.getAttribute("aria-label"), "");
  assert.equal(stray.title, "");
});

test("a box with neither shelf on offer takes both tabs off the bar, and off the screen", async (t) => {
  const view = open(t, {
    hello: { version: "2.15.0", strings: {}, library: false, series: false },
    before: (w) => { w.location.hash = "#films"; },
  });
  assert.equal(front(view), "films", "until the box has said");
  await settle();
  assert.equal(front(view), "live");
  const offered = [...view.window.document.querySelectorAll("#tabBar .tab:not(.hidden)")]
    .map((key) => key.dataset.tab);
  assert.deepEqual(offered, ["live", "metadata", "history", "settings"]);
});

test("an add-on older than the shelf flags keeps both shelves", async (t) => {
  const view = open(t, { before: (w) => { w.location.hash = "#series"; } });
  await settle();
  assert.equal(front(view), "series");
  assert.equal(view.window.document.querySelectorAll("#tabBar .tab.hidden").length, 0);
});

test("a /api/hello that cannot be reached leaves the English and the tab in place", async (t) => {
  const view = open(t, { before: (w) => {
    w.location.hash = "#settings";
    w.fetch = () => Promise.reject(new TypeError("Failed to fetch"));
  } });
  await settle();
  assert.equal(front(view), "settings");
  assert.equal(view.$("idleTitle").textContent, "Nothing is playing");
  assert.equal(view.$("version").textContent, "");
});

test("an error answer from /api/hello, or one without a version, writes no version", async (t) => {
  const failed = open(t, { status: 500, hello: {
    error: "boom", version: "2.15.0", strings: { idle_title: "Nichts läuft" } } });
  await settle();
  assert.equal(failed.$("version").textContent, "");
  assert.equal(failed.$("idleTitle").textContent, "Nothing is playing");

  const bare = open(t, { hello: { strings: {} } });
  await settle();
  assert.equal(bare.$("version").textContent, "");
});
