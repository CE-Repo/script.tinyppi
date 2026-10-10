// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The dashboard's connection (resources/web/js/core.js): whole snapshots,
// delta frames as web/delta.py writes them, reconnects, the token, and the
// small formatting helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
import { page, settle } from "./harness.mjs";

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

test("the token travels in the stream address", async () => {
  const { stream, window } = await booted({ token: "AB CD" });
  assert.equal(stream.url, "/api/stream?token=AB%20CD");
  assert.equal(window.TinyPPI.withToken("/api/art?kind=poster"), "/api/art?kind=poster&token=AB%20CD");
});

test("a closed stream that wants a token opens the token dialog", async () => {
  const view = page({ routes: { "/api/hello": [200, {}], "/api/state": [401, {}] } });
  await view.window.TinyPPI.boot({});
  const stream = view.streams.at(-1);
  stream.readyState = view.window.EventSource.CLOSED;
  stream.emit("error");
  await settle();
  assert.equal(view.window.document.getElementById("status").dataset.state, "down");
  assert.equal(view.window.document.getElementById("tokenDialog").open, true);
});

test("bye closes the stream and stays away as long as asked", async (t) => {
  const { stream, window } = await booted();
  const delays = [];
  const realSetTimeout = window.setTimeout;
  window.setTimeout = (fn, delay) => { delays.push(delay); return realSetTimeout(() => {}, 0); };
  t.after(() => { window.setTimeout = realSetTimeout; });
  stream.emit("bye", { retry_ms: 45000 });
  assert.equal(stream.closed, true);
  assert.ok(delays.includes(45000));
  stream.emit("bye", {});
  assert.ok(delays.includes(20000));       // the floor
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
