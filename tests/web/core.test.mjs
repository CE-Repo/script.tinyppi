// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The dashboard's connection (resources/web/js/core.js): whole snapshots,
// delta frames as web/delta.py writes them, reconnects and what a closed
// stream finds out, the token and its dialog, the toast, folded cards, the
// copied report, and the small formatting helpers.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { page as harnessPage, settle, source } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");

/* Every page this file opens is closed once it is done, so no timer a page
   left running keeps the test process alive. */
const opened = [];
after(() => { for (const window of opened) window.close(); });

function page(options) {
  const view = harnessPage(options);
  opened.push(view.window);
  return view;
}

/* A script run into a page after the fact, under its own file URL like the
   harness does -- for a page whose storage has to be blocked first. */
function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/* The page's timers, held instead of run: the test sees each delay and fires
   them when it chooses. */
function fakeTimers(window) {
  const pending = new Map();
  let next = 1;
  window.setTimeout = (fn, delay) => { pending.set(next, { fn, delay }); return next++; };
  window.clearTimeout = (id) => { pending.delete(id); };
  return {
    delays: () => [...pending.values()].map((timer) => timer.delay),
    run(delay) {
      for (const [id, timer] of [...pending]) {
        if (delay !== undefined && timer.delay !== delay) continue;
        pending.delete(id);
        timer.fn();
      }
    }
  };
}

function setHidden(window, hidden) {
  Object.defineProperty(window.document, "hidden", { configurable: true, get: () => hidden });
}

/* How the dialog's form answers: jsdom does not submit method="dialog". */
function answer(window, value) {
  const dialog = window.document.getElementById("tokenDialog");
  dialog.returnValue = value;
  dialog.open = false;
  dialog.dispatchEvent(new window.Event("close"));
}

const BASE = {
  seq: 1, playing: true, time: "00:10", title: "Film",
  groups: [{ id: "video", title: "Video", rows: [
    { id: "res", label: "Resolution", value: "2160p", detail: "" },
    { id: "fps", label: "Frame rate", value: "23.976", detail: "" }] }],
  metadata: [{ kind: "row", name: "L1 max", value: "1000" },
             { kind: "table", name: "L2", cells: ["1", "2"] }],
};

// Objects built inside the page have the page's prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));

async function booted(options = {}) {
  const states = [];
  const view = page({ routes: { "/api/hello": [200, { strings: {} }] }, ...options });
  await view.window.TinyPPI.boot({ onState: (state) => states.push(state) });
  return { ...view, states, stream: view.streams.at(-1) };
}

/* A stream the browser has given up on, and what the probe after it finds. */
async function closeStream(view) {
  const stream = view.streams.at(-1);
  stream.readyState = view.window.EventSource.CLOSED;
  stream.emit("error");
  await settle();
  return stream;
}

const statusOf = (window) => {
  const status = window.document.getElementById("status");
  return [status.dataset.state, window.document.getElementById("statusText").textContent];
};

test("a whole snapshot is delivered as it is", async () => {
  const { stream, states, window } = await booted();
  stream.emit("open");
  stream.emit("state", BASE);
  assert.deepEqual(plain(states), [BASE]);
  assert.equal(window.document.getElementById("status").dataset.state, "live");
});

test("delta frames patch values, rows and cells", async () => {
  const { stream, states } = await booted();
  stream.emit("state", BASE);
  stream.emit("delta", {
    seq: 2, set: { time: "00:11" }, del: ["title"],
    groups: { rows: [["fps", "24", "drop 1"]] },
    metadata: { rows: [[0, "1100"], [1, ["3", "4"]], [9, "ignored"]] },
  });
  const state = states.at(-1);
  assert.equal(state.seq, 2);
  assert.equal(state.time, "00:11");
  assert.equal("title" in state, false);
  assert.deepEqual(plain(state.groups[0].rows[1]), { id: "fps", label: "Frame rate", value: "24", detail: "drop 1" });
  assert.equal(state.groups[0].rows[0].value, "2160p");
  assert.equal(state.metadata[0].value, "1100");
  assert.deepEqual(plain(state.metadata[1].cells), ["3", "4"]);
  assert.equal(state.metadata.length, 2);
  // The base is not changed in place: a page may hold on to the last state.
  assert.equal(states[0].time, "00:10");
});

test("a list of another shape is replaced outright", async () => {
  const { stream, states } = await booted();
  stream.emit("state", BASE);
  const groups = [{ id: "audio", title: "Audio", rows: [] }];
  stream.emit("delta", { seq: 2, groups, metadata: [] });
  assert.deepEqual(plain(states.at(-1).groups), groups);
  assert.deepEqual(plain(states.at(-1).metadata), []);
});

test("deltas build on each other", async () => {
  const { stream, states } = await booted();
  stream.emit("state", BASE);
  stream.emit("delta", { seq: 2, set: { time: "00:11" } });
  stream.emit("delta", { seq: 3, groups: { rows: [["res", "1080p", ""]] } });
  const state = states.at(-1);
  assert.equal(state.time, "00:11");
  assert.equal(state.groups[0].rows[0].value, "1080p");
});

test("a delta before any snapshot asks for a whole one", async () => {
  const states = [];
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [200, BASE] } });
  await view.window.TinyPPI.boot({ onState: (state) => states.push(state) });
  view.streams.at(-1).emit("delta", { seq: 5, set: { time: "x" } });
  await settle();
  assert.deepEqual(plain(states), [BASE]);
  assert.ok(view.requests.some((request) => request.url === "/api/state"));
});

test("a bad frame is skipped and a throwing page does not end the stream", async () => {
  const view = page({ routes: { "/api/hello": [200, {}] } });
  let calls = 0;
  await view.window.TinyPPI.boot({ onState: () => { calls += 1; throw new Error("page bug"); } });
  const stream = view.streams.at(-1);
  stream.emit("state", "{not json");
  stream.emit("state", BASE);
  stream.emit("delta", { seq: 2 });
  assert.equal(calls, 2);
  assert.equal(stream.closed, undefined);
});

test("the token buys a session before the stream and never travels in an address", async () => {
  const { stream, requests, window } = await booted({ token: "AB CD" });
  const [session] = requests.filter((request) => request.url === "/api/session");
  assert.equal(session.init.method, "POST");
  assert.equal(session.init.headers["X-TinyPPI-Token"], "AB CD");
  assert.equal(requests.indexOf(session), 0, "bought before anything else is asked");
  assert.equal(stream.url, "/api/stream");
  assert.equal(window.TinyPPI.withToken, undefined);
  assert.equal(requests.some((request) => request.url.includes("token=")), false);
});

test("without a token the stream opens at once, and no session is bought", async () => {
  const view = page({ routes: { "/api/hello": [200, {}] } });
  const booting = view.window.TinyPPI.boot({});
  assert.equal(view.streams.length, 1);
  await booting;
  assert.equal(view.requests.some((request) => request.url === "/api/session"), false);
});

test("a session the add-on refuses, or a network that fails it, still opens the stream", async () => {
  for (const answer of ["refused", "failed"]) {
    const view = page({ routes: { "/api/hello": [200, {}], "/api/session": [401, {}] }, token: "OLD1" });
    if (answer === "failed") {
      const fetch = view.window.fetch;
      view.window.fetch = (url, init) =>
        url === "/api/session" ? Promise.reject(new Error("offline")) : fetch(url, init);
    }
    await view.window.TinyPPI.boot({});
    await settle();
    assert.equal(view.streams.length, 1, answer);
  }
});

test("a connect overtaken while its session is bought opens no stream", async () => {
  const view = page({ routes: { "/api/hello": [200, {}] }, token: "AB" });
  const { window } = view;
  let release;
  const fetch = window.fetch;
  window.fetch = (url, init) => url === "/api/session"
    ? new Promise((resolve) => { release = () => resolve(fetch(url, init)); })
    : fetch(url, init);
  window.TinyPPI.boot({});
  setHidden(window, true);
  window.document.dispatchEvent(new window.Event("visibilitychange"));
  release();
  await settle();
  await settle();
  assert.equal(view.streams.length, 0);
});

test("a closed stream that wants a token opens the token dialog", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [401, {}] } });
  await view.window.TinyPPI.boot({});
  await closeStream(view);
  assert.equal(view.window.document.getElementById("status").dataset.state, "down");
  assert.equal(view.window.document.getElementById("tokenDialog").open, true);
});

test("bye closes the stream, stays away as long as asked, then backs off afresh", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [502, {}] } });
  await view.window.TinyPPI.boot({});
  const timers = fakeTimers(view.window);
  // Two missed attempts first, so the next wait would have grown to 4 s.
  for (let attempt = 0; attempt < 2; attempt++) { await closeStream(view); timers.run(); }

  const stream = view.streams.at(-1);
  stream.emit("bye", { retry_ms: 45000 });
  assert.equal(stream.closed, true);
  assert.deepEqual(statusOf(view.window), ["down", "Disconnected"]);
  assert.deepEqual(timers.delays(), [45000]);
  const count = view.streams.length;
  timers.run(45000);
  assert.equal(view.streams.length, count + 1);
  assert.equal(view.streams.at(-1).closed, undefined);

  // The backoff starts over rather than going on from 4 s.
  await closeStream(view);
  assert.deepEqual(timers.delays(), [1000]);
  timers.run();
  // A bye that asks for less, or says nothing, stays away 20 s at least.
  for (const body of [{ retry_ms: 3000 }, {}]) {
    view.streams.at(-1).emit("bye", body);
    assert.deepEqual(timers.delays(), [20000], JSON.stringify(body));
    timers.run();
  }
});

test("hello's strings and auth_read reach the page", async () => {
  const view = page({ routes: { "/api/hello": [200, { strings: { connected: "Verbunden" }, auth_read: true }] } });
  const seen = [];
  await view.window.TinyPPI.boot({ onStrings: (T, hello) => seen.push([T.connected, !!hello]) });
  assert.deepEqual(seen, [["Connected", false], ["Verbunden", true]]);
  assert.equal(view.window.document.getElementById("tokenDialog").open, true);
});

test("commands carry the token in a header and report the outcome", async () => {
  const view = page({ routes: { "/api/command": [200, {}] }, token: "T0K3N" });
  assert.equal(await view.window.TinyPPI.command("pause"), true);
  const { init } = view.requests.at(-1);
  assert.equal(init.headers["X-TinyPPI-Token"], "T0K3N");
  assert.deepEqual(JSON.parse(init.body), { action: "pause" });
  const refused = page({ routes: { "/api/command": [401, {}] } });
  assert.equal(await refused.window.TinyPPI.command("stop"), false);
});

test("fmtNits keeps the reading's precision sensible", () => {
  const { window } = page();
  const { fmtNits } = window.TinyPPI;
  assert.equal(fmtNits(null), "N/A");
  assert.equal(fmtNits(4000), (4000).toLocaleString());
  assert.equal(fmtNits(203.4), "203");
  assert.equal(fmtNits(48.25), "48.3");
  assert.equal(fmtNits(1.5), "1.50");
  assert.equal(fmtNits(0.005), "0.005");
  assert.equal(fmtNits(0), "0");
});

test("presence markers become words in reports and images on screen", () => {
  const { window } = page();
  const { plainValue, renderValue, reportLine } = window.TinyPPI;
  assert.equal(plainValue("✔ | ✘"), "Yes | No");
  assert.equal(plainValue(null), "");
  const node = window.document.createElement("span");
  renderValue(node, "HDR10 ✔");
  assert.equal(node.textContent, "HDR10 ");
  assert.equal(node.querySelector("img").alt, "Yes");
  assert.equal(reportLine("Resolution", "2160p"), "  Resolution" + " ".repeat(17) + "2160p");
  const long = "A name longer than the column itself";
  assert.equal(reportLine(long, "✘"), "  " + long + "  No");
});

test("folded cards are remembered, but not the default", () => {
  const { window } = page();
  const { bindDisclosure, disclosureState } = window.TinyPPI;
  const card = window.document.createElement("details");
  bindDisclosure(card, "video", true);
  assert.equal(card.open, true);
  card.dispatchEvent(new window.Event("toggle"));       // the restoring toggle
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.video"), null);
  card.open = false;
  card.dispatchEvent(new window.Event("toggle"));
  assert.equal(disclosureState("video", true), false);
});

test("an open card is written as 1, and a retired key is forgotten", () => {
  const { window } = page();
  const { setDisclosureState, disclosureState, forgetDisclosure } = window.TinyPPI;
  setDisclosureState("audio", true);
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.audio"), "1");
  assert.equal(disclosureState("audio", false), true);
  forgetDisclosure("audio");
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.audio"), null);
  assert.equal(disclosureState("audio", false), false);
});

test("a fold flashes the card's own heading, every time it is moved", async () => {
  const { window } = page();
  const { document } = window;
  window.localStorage.setItem("tinyppi.disclosure.video", "1");
  const card = document.createElement("details");
  card.innerHTML = '<summary class="panel-toggle">Video</summary>' +
                   '<div><span class="panel-toggle"></span></div>';
  document.body.append(card);
  window.TinyPPI.bindDisclosure(card, "video", false);
  assert.equal(card.open, true);                       // restored from storage
  await settle();                                      // jsdom's own restoring toggle
  const heading = card.querySelector(":scope > .panel-toggle");
  assert.equal(heading.classList.contains("flash"), false);

  card.open = false;
  await settle();
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.video"), "0");
  assert.equal(heading.classList.contains("flash"), true);
  assert.equal(heading.dataset.flashbound, "1");
  heading.dispatchEvent(new window.Event("animationend"));
  assert.equal(heading.classList.contains("flash"), false);

  card.open = true;
  await settle();
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.video"), "1");
  assert.equal(heading.classList.contains("flash"), true);
  // Only the card's own heading wears the mark.
  assert.equal(card.querySelector("div > .panel-toggle").classList.contains("flash"), false);
});

test("blocked storage: defaults stand in and the token lasts as long as the tab", async () => {
  const view = page({ scripts: [], routes: { "/api/hello": [200, {}] } });
  const { window } = view;
  Object.defineProperty(window, "localStorage", {
    configurable: true, get() { throw new window.DOMException("blocked", "SecurityError"); }
  });
  load(view.dom, "core.js");
  const T = window.TinyPPI;
  assert.equal(T.token, "");
  assert.equal(T.disclosureState("video", true), true);
  assert.equal(T.disclosureState("video", false), false);
  assert.doesNotThrow(() => T.setDisclosureState("video", true));
  assert.doesNotThrow(() => T.forgetDisclosure("video"));

  await T.boot({});
  window.document.getElementById("tokenInput").value = "abc123";
  answer(window, "ok");
  assert.equal(T.token, "ABC123");
  await settle();
  assert.equal(view.requests.at(-1).init.headers["X-TinyPPI-Token"], "ABC123");
  assert.equal(view.streams.at(-1).url, "/api/stream");
});

test("the token dialog's answer becomes the token and reconnects with it", async () => {
  const view = page({ routes: { "/api/hello": [200, {
    strings: { token_title: "Zugangsschlüssel", save: "Speichern", cancel: "Abbrechen" } }] } });
  const { window, streams } = view;
  await window.TinyPPI.boot({});
  const { document } = window;
  assert.equal(document.getElementById("dlgTitle").textContent, "Zugangsschlüssel");
  assert.equal(document.getElementById("dlgOk").textContent, "Speichern");
  assert.equal(document.getElementById("dlgCancel").textContent, "Abbrechen");

  const announced = [];
  document.addEventListener("tinyppi-token", () => announced.push(window.TinyPPI.token));
  const first = streams.at(-1);
  document.getElementById("tokenBtn").click();          // the key on the settings tab
  const input = document.getElementById("tokenInput");
  assert.equal(document.getElementById("tokenDialog").open, true);
  assert.equal(input.value, "");
  input.value = "  ab12cd ";
  answer(window, "ok");

  assert.equal(window.TinyPPI.token, "AB12CD");
  assert.equal(window.localStorage.getItem("tinyppi.token"), "AB12CD");
  assert.deepEqual(announced, ["AB12CD"]);
  assert.equal(first.closed, true);
  await settle();
  const session = view.requests.filter((request) => request.url === "/api/session").at(-1);
  assert.equal(session.init.headers["X-TinyPPI-Token"], "AB12CD");
  assert.equal(streams.at(-1).url, "/api/stream");
  assert.notEqual(streams.at(-1), first);

  // Asked again, it opens on the token the device holds.
  window.TinyPPI.askToken();
  assert.equal(input.value, "AB12CD");
});

test("a dismissed dialog tries again later, but only with nothing connected", async () => {
  const { window, streams } = await booted();
  const timers = fakeTimers(window);
  answer(window, "cancel");
  assert.deepEqual(timers.delays(), []);                 // the stream is still there
  window.dispatchEvent(new window.Event("pagehide"));
  answer(window, "cancel");
  assert.deepEqual(timers.delays(), [5000]);
  const count = streams.length;
  timers.run(5000);
  assert.equal(streams.length, count + 1);
});

test("before boot there is no light, toast or dialog to touch", () => {
  const { window } = page();
  const { TinyPPI } = window;
  TinyPPI.setStatus("live", "Connected");
  TinyPPI.toast("Hello");
  TinyPPI.askToken();
  assert.deepEqual(statusOf(window), ["wait", "…"]);
  assert.equal(window.document.getElementById("toast"), null);
  assert.equal(window.document.getElementById("tokenDialog"), null);
});

test("a toast shows, says when it is bad, and leaves after a while", async () => {
  const { window } = await booted();
  const timers = fakeTimers(window);
  const toast = window.document.getElementById("toast");
  window.TinyPPI.toast("Saved");
  assert.equal(toast.textContent, "Saved");
  assert.deepEqual([toast.classList.contains("show"), toast.classList.contains("bad")], [true, false]);
  window.TinyPPI.toast("Refused", true);
  assert.equal(toast.textContent, "Refused");
  assert.equal(toast.classList.contains("bad"), true);
  assert.deepEqual(timers.delays(), [2600]);             // the first one's timer is dropped
  timers.run(2600);
  assert.equal(toast.classList.contains("show"), false);
});

test("the status light is only rewritten when it has moved", async () => {
  const { window } = await booted();
  const status = window.document.getElementById("status");
  window.TinyPPI.setStatus("live", "Connected");
  const watcher = new window.MutationObserver(() => {});
  watcher.observe(status, { attributes: true, childList: true, subtree: true, characterData: true });
  window.TinyPPI.setStatus("live", "Connected");
  assert.equal(watcher.takeRecords().length, 0);
  window.TinyPPI.setStatus("live", "Verbunden");
  assert.ok(watcher.takeRecords().length > 0);
  assert.equal(status.title, "Verbunden");
  watcher.disconnect();
});

test("a cross is an image too, and the words fall back to English", () => {
  const { window } = page();
  const { T, renderValue, plainValue } = window.TinyPPI;
  const node = window.document.createElement("span");
  renderValue(node, "Dolby Vision ✘");
  const image = node.querySelector("img");
  assert.deepEqual([image.className, image.getAttribute("src"), image.alt, image.title],
                   ["presence-icon", "/icons/no.svg", "No", "No"]);
  T.yes = ""; T.no = "";
  renderValue(node, "✔✘");
  assert.deepEqual([...node.querySelectorAll("img")].map((img) => img.alt), ["Yes", "No"]);
  assert.equal(node.childNodes.length, 2);             // the old content went
  assert.equal(plainValue("✔ / ✘"), "Yes / No");
  renderValue(node, undefined);
  assert.equal(node.childNodes.length, 0);
});

test("a page out of sight lets its stream go and takes it up again when seen", async () => {
  const { window, streams, stream } = await booted();
  const timers = fakeTimers(window);
  stream.emit("open");
  setHidden(window, true);
  window.document.dispatchEvent(new window.Event("visibilitychange"));
  assert.equal(stream.closed, true);
  assert.deepEqual(statusOf(window), ["wait", "Connecting…"]);
  answer(window, "cancel");                              // nothing is retried out of sight
  assert.deepEqual(timers.delays(), []);

  const count = streams.length;
  setHidden(window, false);
  window.document.dispatchEvent(new window.Event("visibilitychange"));
  assert.equal(streams.length, count + 1);
  assert.equal(streams.at(-1).closed, undefined);
});

test("a page booted out of sight opens nothing until it is seen", async () => {
  const { window, streams } = page({ routes: { "/api/hello": [200, {}] } });
  setHidden(window, true);
  await window.TinyPPI.boot();                           // no options at all
  assert.equal(streams.length, 0);
  window.dispatchEvent(new window.Event("pageshow"));
  assert.equal(streams.length, 0);
  setHidden(window, false);
  window.document.dispatchEvent(new window.Event("visibilitychange"));
  assert.equal(streams.length, 1);
});

test("leaving the page closes the stream, coming back from the cache reopens it once", async () => {
  const { window, streams, stream } = await booted();
  window.dispatchEvent(new window.Event("pagehide"));
  assert.equal(stream.closed, true);
  const count = streams.length;
  window.dispatchEvent(new window.Event("pageshow"));
  assert.equal(streams.length, count + 1);
  window.dispatchEvent(new window.Event("pageshow"));
  assert.equal(streams.length, count + 1);
});

test("a page that takes no snapshots still shows the connection live", async () => {
  const view = page({ routes: { "/api/hello": [200, {}] } });
  await view.window.TinyPPI.boot({});
  const stream = view.streams.at(-1);
  stream.emit("delta", "{not json");
  assert.equal(view.requests.some((request) => request.url.startsWith("/api/state")), false);
  stream.emit("state", BASE);
  assert.deepEqual(statusOf(view.window), ["live", "Connected"]);
});

test("row patches leave cards without rows alone, and empty patches change nothing", async () => {
  const { stream, states } = await booted();
  stream.emit("state", { seq: 1, groups: [{ id: "empty" },
    { id: "video", rows: [{ id: "res", value: "1080p", detail: "" }] }] });
  stream.emit("delta", { seq: 2, groups: { rows: [] }, metadata: {} });
  assert.deepEqual(plain(states.at(-1)), plain({ seq: 2, groups: states[0].groups, metadata: [] }));
  stream.emit("delta", { seq: 3, groups: {} });
  assert.equal(states.at(-1).groups, states[0].groups);
  stream.emit("delta", { seq: 4, groups: { rows: [["res", "2160p", "HDR"]] }, metadata: { rows: [[0, "x"]] } });
  const state = states.at(-1);
  assert.deepEqual(plain(state.groups), [{ id: "empty", rows: [] },
    { id: "video", rows: [{ id: "res", value: "2160p", detail: "HDR" }] }]);
  assert.deepEqual(plain(state.metadata), []);

  stream.emit("state", { seq: 9 });                      // a snapshot with no lists at all
  stream.emit("delta", { seq: 10, groups: { rows: [["res", "x", ""]] } });
  assert.deepEqual(plain(states.at(-1).groups), []);
  assert.equal(states.at(-1).metadata, undefined);
});

test("a whole snapshot that cannot be had after a stray delta is left to the stream", async () => {
  const states = [];
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [500, {}] } });
  await view.window.TinyPPI.boot({ onState: (state) => states.push(state) });
  view.streams.at(-1).emit("delta", { seq: 5, set: { time: "x" } });
  await settle();
  assert.deepEqual(states, []);
  assert.ok(view.requests.some((request) => request.url === "/api/state"));
});

test("an error on a stream that is only reconnecting asks the add-on nothing", async () => {
  const view = await booted();
  view.stream.emit("error");
  await settle();
  assert.deepEqual(statusOf(view.window), ["down", "Disconnected"]);
  assert.equal(view.stream.closed, undefined);
  assert.equal(view.requests.some((request) => request.url.startsWith("/api/state")), false);
});

test("a token the add-on turns down is said so, and asked for again", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [401, {}] }, token: "OLD1" });
  await view.window.TinyPPI.boot({});
  await closeStream(view);
  const { document } = view.window;
  assert.equal(view.requests.at(-1).url, "/api/state");
  assert.equal(view.requests.at(-1).init.headers["X-TinyPPI-Token"], "OLD1");
  assert.deepEqual(statusOf(view.window), ["down", "Wrong or missing token"]);
  assert.equal(document.getElementById("toast").textContent, "Wrong or missing token");
  assert.equal(document.getElementById("toast").classList.contains("bad"), true);
  assert.equal(document.getElementById("tokenDialog").open, true);
  assert.equal(document.getElementById("tokenInput").value, "OLD1");
});

test("after too many wrong tokens the page waits as long as it is told", async () => {
  for (const [body, delay] of [[{ retry_ms: 90000 }, 90000], [{ retry_ms: 10 }, 5000], [null, 5000]]) {
    const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [429, body] } });
    await view.window.TinyPPI.boot({});
    const timers = fakeTimers(view.window);
    await closeStream(view);
    assert.deepEqual(statusOf(view.window), ["down", "Wrong or missing token"]);
    assert.equal(view.window.document.getElementById("toast").classList.contains("bad"), true);
    assert.deepEqual(timers.delays().filter((ms) => ms !== 2600), [delay], JSON.stringify(body));
    assert.equal(view.window.document.getElementById("tokenDialog").open, false);
  }
});

test("a refusal whose answer cannot be read waits a whole minute", async () => {
  const view = page({ routes: { "/api/hello": [200, {}] } });
  await view.window.TinyPPI.boot({});
  const timers = fakeTimers(view.window);
  view.window.fetch = async () => ({ status: 429, ok: false, json: async () => { throw new SyntaxError("cut off"); } });
  await closeStream(view);
  assert.deepEqual(timers.delays().filter((ms) => ms !== 2600), [60000]);
});

test("a full house of streams is waited out for a moment", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [503, { streams_full: true }] } });
  await view.window.TinyPPI.boot({});
  const timers = fakeTimers(view.window);
  await closeStream(view);
  assert.deepEqual(statusOf(view.window), ["wait", "Too many connections"]);
  assert.deepEqual(timers.delays(), [1500]);
});

test("an add-on that is not there is retried ever more slowly, and afresh once it answers", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [502, {}] } });
  await view.window.TinyPPI.boot({});
  const timers = fakeTimers(view.window);
  const waits = [];
  for (let attempt = 0; attempt < 6; attempt++) {
    await closeStream(view);
    assert.deepEqual(statusOf(view.window), ["down", "Disconnected"]);
    waits.push(...timers.delays());
    timers.run();                                        // reconnects
  }
  assert.deepEqual(waits, [1000, 2000, 4000, 8000, 15000, 15000]);
  view.streams.at(-1).emit("open");
  await closeStream(view);
  assert.deepEqual(timers.delays(), [1000]);

  // No answer at all counts the same.
  timers.run();
  view.window.fetch = async () => { throw new TypeError("network down"); };
  await closeStream(view);
  assert.deepEqual(timers.delays(), [2000]);
});

test("copying a report: nothing to copy, the clipboard, or a named file", async () => {
  const { window } = await booted();
  const { document } = window;
  assert.equal(window.TinyPPI.copyReport("", "Film", "live"), undefined);

  const written = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true, value: { writeText: async (text) => { written.push(text); } }
  });
  await window.TinyPPI.copyReport("Report", "Film", "live");
  assert.deepEqual(written, ["Report"]);
  assert.equal(document.getElementById("toast").textContent, "Copied");

  // Plain http over a LAN: no clipboard, so the report is saved instead.
  Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: undefined });
  const blobs = [];
  const revoked = [];
  window.URL.createObjectURL = (blob) => { blobs.push(blob); return "blob:report-" + blobs.length; };
  window.URL.revokeObjectURL = (url) => revoked.push(url);
  const clicks = [];
  document.addEventListener("click", (event) => {
    clicks.push({ name: event.target.download, href: event.target.href,
                  attached: event.target.isConnected, hidden: event.target.style.display });
    event.preventDefault();
  });
  const timers = fakeTimers(window);
  await window.TinyPPI.copyReport("Line one\n", 'The "Film": Part 2?', "live");
  await window.TinyPPI.copyReport("x", "", "metadata");
  await window.TinyPPI.copyReport("x", " ..A  /  B.. ");
  assert.deepEqual(clicks, [
    { name: "TinyPPI_The_Film_Part_2_live.txt", href: "blob:report-1", attached: true, hidden: "none" },
    { name: "TinyPPI_metadata.txt", href: "blob:report-2", attached: true, hidden: "none" },
    { name: "TinyPPI_A_B.txt", href: "blob:report-3", attached: true, hidden: "none" }]);
  assert.equal(blobs[0].type, "text/plain");
  assert.equal(await blobs[0].text(), "Line one\n");
  assert.equal(document.querySelectorAll("a[download]").length, 3);
  assert.deepEqual(revoked, []);                         // not in the same breath as the click
  timers.run(2000);
  assert.equal(document.querySelectorAll("a[download]").length, 0);
  assert.deepEqual(revoked, ["blob:report-1", "blob:report-2", "blob:report-3"]);
});

test("an unreadable hello leaves the page on its English", async () => {
  const view = page({ routes: { "/api/hello": [200, null] } });
  const seen = [];
  await view.window.TinyPPI.boot({ onStrings: (T, hello) => seen.push([T.connected, hello]) });
  assert.deepEqual(seen, [["Connected", undefined]]);
  assert.equal(view.streams.length, 1);
});

test("every word the add-on sends has an English stand-in until it does", () => {
  const table = readFileSync(join(JS, "..", "..", "lib", "web", "strings.py"), "utf8");
  const sent = [...table.match(/_UI_STRINGS = \{([^}]*)\}/)[1].matchAll(/"(\w+)":/g)]
    .map((found) => found[1]);
  assert.ok(sent.length > 90);
  const { T } = page().window.TinyPPI;
  /* Bar the end time's label, which the live panels leave off until Kodi's
     own word for it arrives rather than put an English one in front of a
     clock already in the box's regional format. */
  assert.deepEqual(sent.filter((key) => typeof T[key] !== "string"), ["ends_at"]);
});

test("an error answer from hello is no hello, whatever its body says", async () => {
  const view = page({ routes: { "/api/hello": [500, {
    error: "boom", strings: { connected: "Verbunden" }, auth_read: true }] } });
  const seen = [];
  await view.window.TinyPPI.boot({ onStrings: (T, hello) => seen.push([T.connected, hello]) });
  assert.deepEqual(seen, [["Connected", undefined]]);
  assert.equal(view.window.TinyPPI.T.connected, "Connected");
  assert.equal(view.window.document.getElementById("tokenDialog").open, false);
});

test("a page that already holds a token is not asked for one", async () => {
  const view = page({ routes: { "/api/hello": [200, { auth_read: true }] }, token: "HELD" });
  await view.window.TinyPPI.boot({});
  assert.equal(view.window.TinyPPI.token, "HELD");
  assert.equal(view.window.document.getElementById("tokenDialog").open, false);
});

test("a command that cannot reach the add-on fails, a refused one asks for the token", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/command": [401, {}] } });
  await view.window.TinyPPI.boot({});
  assert.equal(await view.window.TinyPPI.command("volume", 40), false);
  assert.deepEqual(JSON.parse(view.requests.at(-1).init.body), { action: "volume", value: 40 });
  assert.equal(view.requests.at(-1).init.method, "POST");
  assert.equal(view.window.document.getElementById("tokenDialog").open, true);
  assert.equal(view.window.document.getElementById("toast").textContent, "Wrong or missing token");
  view.window.fetch = async () => { throw new TypeError("offline"); };
  assert.equal(await view.window.TinyPPI.command("stop"), false);
});

test("getJSON carries the token and turns a failed answer into an error", async () => {
  const view = page({ routes: { "/api/library/films": [200, { films: [] }], "/api/library/series": [503, {}] },
                      token: "K3Y" });
  assert.deepEqual(plain(await view.window.TinyPPI.getJSON("/api/library/films")), { films: [] });
  assert.equal(view.requests.at(-1).url, "/api/library/films");
  assert.equal(view.requests.at(-1).init.headers["X-TinyPPI-Token"], "K3Y");
  await assert.rejects(view.window.TinyPPI.getJSON("/api/library/series"), /503/);
});
