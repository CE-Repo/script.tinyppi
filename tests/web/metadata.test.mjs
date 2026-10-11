// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The Dolby Vision metadata tab (resources/web/js/metadata.js): the idle
// card, the L5 active-picture card, the list laid out in blocks with its trim
// tables turned on their side, readings written in place and lit when they
// move, and the plain-text report.

import assert from "node:assert/strict";
import { test } from "node:test";
import { page, settle } from "./harness.mjs";

const SCRIPTS = ["core.js", "readings.js", "live-remote.js", "live-panels.js", "metadata.js"];

/* The rows as info.dvmetadata builds them: (kind, name, value), and the trim
   tables as a heading row naming the controls over a row per pass. */
const ROWS = [
  { kind: "section", name: "L1", value: "" },
  { kind: "row", name: "Max", value: "1000" },
  { kind: "row", name: "Avg", value: "120" },
  { kind: "space", name: "", value: "" },
  { kind: "section", name: "L5", value: "Cached" },
  { kind: "row", name: "Active area", value: "✔" },
  { kind: "wide", name: "", value: "Letterbox 0 0 276 276" },
  { kind: "space", name: "", value: "" },
  { kind: "section", name: "L2" },
  { kind: "headings", name: "Trims", cells: ["Slope", "Offset", "Power"] },
  { kind: "columns", name: "100 nits", cells: ["2048", "2048", "2048"] },
  { kind: "columns", name: "600 nits", cells: ["2100", "2000", "1990"] },
];

const copyRows = () => ROWS.map((row) => ({ ...row, cells: row.cells && [...row.cells] }));
const texts = (nodes) => [...nodes].map((node) => node.textContent);
const heading = (name, cells) => ({ kind: "headings", name, cells });
const pass = (name, cells) => ({ kind: "columns", name, cells });

function metadataTab(t) {
  const view = page({ scripts: SCRIPTS });
  t.after(() => view.window.close());
  const $ = (id) => view.window.document.getElementById(id);
  return { ...view, $, M: view.window.TinyPPI.metadata };
}

/* setTimeout in the page, held until the test runs it. */
function heldTimers(window) {
  const timers = new Map();
  let next = 1;
  window.setTimeout = (fn, delay) => { timers.set(next, { fn, delay }); return next++; };
  window.clearTimeout = (id) => { timers.delete(id); };
  return {
    delays: () => [...timers.values()].map((timer) => timer.delay),
    run() { const due = [...timers.values()]; timers.clear(); for (const timer of due) timer.fn(); },
  };
}

/* The trim tables on the page, each as the text of its grid cells. */
const tables = ($) => [...$("metaRows").querySelectorAll(".mgrid")]
  .map((grid) => texts(grid.children));

test("the luminance chart moves in under the active-picture card", (t) => {
  const { $ } = metadataTab(t);
  assert.equal($("frameCard").nextElementSibling, $("chartCard"));
  assert.equal($("chartCard").closest(".tabpanel").id, "tab-metadata");
  assert.equal($("frameCard").open, false);
  assert.equal($("listCard").open, true);
});

test("with nothing to list the idle card says which nothing it is", (t) => {
  const { $, M, window } = metadataTab(t);
  // The English fallbacks leave both texts empty; give them words to tell apart.
  Object.assign(window.TinyPPI.T, { idle_text: "Start a film.",
                                    no_metadata_text: "This title carries no RPU." });
  M.render({ playing: false });
  assert.ok($("listCard").classList.contains("hidden"));
  assert.equal($("metaIdleCard").classList.contains("hidden"), false);
  assert.equal($("metaIdleTitle").textContent, "Nothing is playing");
  assert.equal($("metaIdleText").textContent, "Start a film.");

  M.render({ playing: true, metadata: ROWS });
  assert.equal($("listCard").classList.contains("hidden"), false);
  assert.ok($("metaIdleCard").classList.contains("hidden"));
  assert.equal($("metaRows").children.length, 3);

  M.render({ playing: true, metadata: [] });
  assert.ok($("listCard").classList.contains("hidden"));
  assert.equal($("metaIdleCard").classList.contains("hidden"), false);
  assert.equal($("metaIdleTitle").textContent, "No Dolby Vision metadata");
  assert.equal($("metaIdleText").textContent, "This title carries no RPU.");
  assert.equal($("metaRows").textContent, "");
  assert.equal($("metaRows").children.length, 0);

  // The list after an idle spell is built afresh, not written into old nodes.
  M.render({ playing: true, metadata: ROWS });
  assert.equal($("metaRows").querySelector(".mrow .v").textContent, "1000");
});

test("the active picture is drawn to scale and its bars written out", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metrics: { bars: [192, 96, 108, 54], frame: { w: 1920, h: 1080 } } });
  assert.equal($("frameCard").classList.contains("hidden"), false);
  assert.equal($("frameActive").parentElement.style.aspectRatio, "1920 / 1080");
  assert.equal($("frameActive").style.inset, "10% 5% 5% 10%");
  assert.equal($("frameNote").textContent, "1920×1080   L 192  R 96  T 108  B 54");

  for (const metrics of [{ frame: { w: 1920, h: 1080 } }, { bars: [0, 0, 0, 0] },
                         { bars: [0, 0, 0, 0], frame: { w: 0, h: 1080 } },
                         { bars: [0, 0, 0, 0], frame: { w: 1920, h: 0 } }, undefined]) {
    M.render({ playing: true, metrics: { bars: [192, 96, 108, 54], frame: { w: 1920, h: 1080 } } });
    M.render({ playing: true, metrics });
    assert.ok($("frameCard").classList.contains("hidden"), JSON.stringify(metrics));
  }
});

test("rows are laid out in blocks, one per section, presence as images", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: ROWS });
  const blocks = [...$("metaRows").children];
  assert.ok(blocks.every((block) => block.className === "mblock"));
  assert.equal(blocks.length, 3);

  const [l1, l5] = blocks;
  assert.deepEqual([...l1.children].map((node) => node.className), ["msection", "mrow", "mrow"]);
  assert.deepEqual(texts(l1.querySelector(".msection").children), ["L1", ""]);
  assert.equal(l1.querySelector(".msection .state").className, "state");
  const max = l1.querySelector(".mrow");
  assert.equal(max.querySelector(".k").textContent, "Max");
  assert.equal(max.querySelector(".v").className, "v mono");
  assert.equal(max.querySelector(".v").textContent, "1000");

  assert.equal(l5.querySelector(".msection .state").textContent, "Cached");
  const yes = l5.querySelector(".mrow .v img");
  assert.equal(yes.alt, "Yes");
  assert.equal(yes.getAttribute("src"), "/icons/yes.svg");
  assert.equal(l5.querySelector(".mwide").className, "mwide mono");
  assert.equal(l5.querySelector(".mwide").textContent, "Letterbox 0 0 276 276");
  assert.equal($("metaRows").querySelectorAll(".mrow, .mwide, .msection").length, 7,
               "spaces draw nothing");
});

test("rows ahead of any section still get a block, pass rows on their own draw nothing", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: [
    pass("100 nits", ["1"]),
    { kind: "row", name: "Source", value: "Profile 8.1" },
    { kind: "wide", name: "", value: undefined }] });
  const blocks = [...$("metaRows").children];
  assert.equal(blocks.length, 1);
  assert.deepEqual([...blocks[0].children].map((node) => node.className), ["mrow", "mwide mono"]);
  assert.equal(blocks[0].querySelector(".mrow").textContent, "SourceProfile 8.1");
  assert.equal(blocks[0].querySelector(".mwide").textContent, "");
});

test("a reading with no value is drawn empty and lights only once one arrives", (t) => {
  const { $, M, window } = metadataTab(t);
  const timers = heldTimers(window);
  const list = (value) => [{ kind: "section", name: "L6" },
                           { kind: "row", name: "MaxCLL", value }];
  M.render({ playing: true, metadata: list(undefined) });
  const row = $("metaRows").querySelector(".mrow");
  assert.equal(row.querySelector(".v").textContent, "");
  M.render({ playing: true, metadata: list("") });
  assert.equal(row.classList.contains("changed"), false, "nothing is not a change from nothing");
  assert.deepEqual(timers.delays(), []);
  M.render({ playing: true, metadata: list("1000") });
  assert.equal(row.querySelector(".v").textContent, "1000");
  assert.ok(row.classList.contains("changed"));
  assert.deepEqual(timers.delays(), [750]);
});

test("a trim table is turned on its side: controls down, passes across", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: ROWS });
  const grid = $("metaRows").querySelector(".mtable > .mgrid");
  assert.equal(grid.style.gridTemplateColumns,
               "minmax(var(--lead), auto) repeat(2, minmax(var(--cell), 1fr))");
  assert.deepEqual([...grid.children].slice(0, 4).map((node) => node.className),
                   ["corner", "head", "head", "rule"]);
  assert.deepEqual(tables($), [[
    "Trims", "100 nits", "600 nits", "",
    "Slope", "2048", "2100",
    "Offset", "2048", "2000",
    "Power", "2048", "1990"]]);
  assert.equal(grid.querySelector(".lead").className, "lead");
  assert.equal(grid.children[5].className, "mono");
  // The table sits in the block of its section.
  assert.equal(grid.closest(".mblock").querySelector(".msection span").textContent, "L2");
});

test("a table cut at six controls is read back into the one it came from", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: [
    { kind: "section", name: "L8" },
    heading("L8", ["Slope", "Offset", "Power", "Chroma", "Saturation", "MS"]),
    pass("100 nits", ["1", "2", "3", "4", "5", "6"]),
    pass("600 nits", ["7", "8", "9", "10", "11"]),          // one cell short
    { kind: "space" },
    heading("L8", ["Mid", "Clip"]),
    pass("100 nits", ["13", "14"]),
    pass("600 nits"),                                        // no cells at all
    { kind: "row", name: "After", value: "x" }] });
  assert.deepEqual(tables($), [[
    "L8", "100 nits", "600 nits", "",
    "Slope", "1", "7", "Offset", "2", "8", "Power", "3", "9",
    "Chroma", "4", "10", "Saturation", "5", "11", "MS", "6", "",
    "Mid", "13", "", "Clip", "14", ""]]);
  assert.equal($("metaRows").querySelector(".mrow .k").textContent, "After",
               "the rows after the table are laid out after it");
});

test("a heading row that does not continue the table starts one of its own", (t) => {
  const { $, M } = metadataTab(t);
  // Another legend.
  M.render({ playing: true, metadata: [
    heading("L2", ["Slope"]), pass("100 nits", ["1"]),
    heading("L8", ["Mid"]), pass("100 nits", ["2"])] });
  assert.deepEqual(tables($).map((table) => table[0]), ["L2", "L8"]);

  // The same legend over other passes.
  M.render({ playing: true, metadata: [
    heading("L2", ["Slope"]), pass("100 nits", ["1"]),
    heading("L2", ["Offset"]), pass("1000 nits", ["2"])] });
  assert.deepEqual(tables($), [["L2", "100 nits", "", "Slope", "1"],
                               ["L2", "1000 nits", "", "Offset", "2"]]);

  // The same legend over fewer passes than the first had.
  M.render({ playing: true, metadata: [
    heading("L2", ["Slope"]), pass("100 nits", ["1"]), pass("600 nits", ["2"]),
    heading("L2", ["Offset"]), pass("100 nits", ["3"])] });
  assert.deepEqual(tables($), [["L2", "100 nits", "600 nits", "", "Slope", "1", "2"],
                               ["L2", "100 nits", "", "Offset", "3"]]);
});

test("a heading row with nothing under it, or naming nothing, draws no table", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: [
    heading("L2", ["Slope"]), pass("100 nits", ["1"]),
    heading("L2", ["Offset"]), { kind: "row", name: "Max", value: "1000" }] });
  assert.equal(tables($).length, 1);
  assert.equal($("metaRows").querySelector(".mrow .k").textContent, "Max");

  M.render({ playing: true, metadata: [
    heading("L9", undefined), pass("100 nits", ["1"]), { kind: "row", name: "Min", value: "0" }] });
  assert.equal(tables($).length, 0);
  assert.equal($("metaRows").querySelectorAll(".mrow").length, 1, "its pass row is taken with it");
  assert.equal($("metaRows").querySelector(".mrow .k").textContent, "Min");
});

test("readings move in place and light up for a moment", (t) => {
  const { $, M, window } = metadataTab(t);
  const timers = heldTimers(window);
  const rows = copyRows();
  rows.push(pass("1000 nits"));
  M.render({ playing: true, metadata: rows });
  const [maxRow, avgRow] = $("metaRows").querySelectorAll(".mrow");
  const cached = $("metaRows").querySelectorAll(".msection .state")[1];
  const wide = $("metaRows").querySelector(".mwide");
  const cells = [...$("metaRows").querySelectorAll(".mgrid .mono")];
  const offset600 = cells[4];
  assert.equal(offset600.textContent, "2000");

  const next = copyRows();
  next.push(pass("1000 nits"));
  next[1].value = "1100";
  next[2].value = undefined;
  next[4].value = "";
  next[6].value = "Letterbox 0 0 140 140";
  next[11].cells[1] = "2010";
  M.render({ playing: true, metadata: next });

  assert.equal($("metaRows").querySelectorAll(".mrow")[0], maxRow, "written in place");
  assert.equal(maxRow.querySelector(".v").textContent, "1100");
  assert.ok(maxRow.classList.contains("changed"), "a name and its value light as a pair");
  assert.equal(avgRow.querySelector(".v").textContent, "", "a reading that went away");
  assert.ok(avgRow.classList.contains("changed"));
  assert.equal(cached.textContent, "");
  assert.equal(cached.classList.contains("changed"), false, "a heading is not lit");
  assert.equal(wide.textContent, "Letterbox 0 0 140 140");
  assert.equal(wide.classList.contains("changed"), false);
  assert.equal(offset600.textContent, "2010");
  assert.ok(offset600.classList.contains("changed"), "the trim cell lights on its own");
  assert.equal(cells[3].classList.contains("changed"), false);
  assert.equal($("metaRows").querySelectorAll(".changed").length, 3);
  assert.deepEqual(timers.delays(), [750, 750, 750]);

  timers.run();
  assert.equal($("metaRows").querySelectorAll(".changed").length, 0);

  // The same values again light nothing.
  M.render({ playing: true, metadata: next });
  assert.equal($("metaRows").querySelectorAll(".changed").length, 0);
  assert.deepEqual(timers.delays(), []);

  // A reading that moves again starts its fade over.
  next[1].value = "1200";
  M.render({ playing: true, metadata: next });
  next[1].value = "1300";
  M.render({ playing: true, metadata: next });
  assert.deepEqual(timers.delays(), [750]);
  assert.equal(maxRow.querySelector(".v").textContent, "1300");
});

test("a list that changes shape is built again", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: ROWS });
  const first = $("metaRows").querySelector(".mrow");

  const renamed = copyRows();
  renamed[9].cells[0] = "Gain";
  M.render({ playing: true, metadata: renamed });
  assert.equal(first.isConnected, false, "a renamed control is a new table");
  assert.equal(tables($)[0][4], "Gain");

  const longer = [...renamed, { kind: "row", name: "Min", value: "0.005" }];
  const before = $("metaRows").querySelector(".mrow");
  M.render({ playing: true, metadata: longer });
  assert.equal(before.isConnected, false);
  assert.equal([...$("metaRows").querySelectorAll(".mrow .k")].at(-1).textContent, "Min");
});

test("a shorter list that happens to share the old list's shape leaves its missing rows alone", (t) => {
  const { $, M } = metadataTab(t);
  M.render({ playing: true, metadata: [
    { kind: "row", name: "A", value: "1" }, { kind: "row", name: "B", value: "2" }] });
  const [first, second] = $("metaRows").querySelectorAll(".mrow .v");
  // A name carrying the shape's own separators spells the same shape with one
  // row fewer: the rows the list no longer has are skipped, not read.
  M.render({ playing: true, metadata: [
    { kind: "row", name: "A\u001f\u001erow\u001fB", value: "9" }] });
  assert.equal(first.isConnected, true, "taken for the same shape and written in place");
  assert.equal(first.textContent, "9");
  assert.equal(second.textContent, "2");
  assert.equal($("listCard").classList.contains("hidden"), false);
});

test("the report copies the list as plain text", async (t) => {
  const { M, window } = metadataTab(t);
  const written = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true, value: { writeText: async (text) => { written.push(text); } },
  });
  const line = (label, value) => ("  " + label).padEnd(29) + value;
  M.render({ playing: true, title: "Film", filename: "/films/Film.mkv", metadata: ROWS });
  M.copy();
  await settle();
  assert.deepEqual(written, [[
    "TinyPPI — Dolby Vision metadata view",
    "Film",
    "/films/Film.mkv",
    "",
    "[L1]",
    line("Max", "1000"),
    line("Avg", "120"),
    "",
    "[L5 - Cached]",
    line("Active area", "Yes"),
    "  Letterbox 0 0 276 276",
    "",
    "[L2]",
    line("Trims", "Slope  Offset  Power"),
    line("100 nits", "2048  2048  2048"),
    line("600 nits", "2100  2000  1990"),
  ].join("\n")]);

  M.render({ playing: true, metadata: [{ kind: "section", name: "L6", value: "✘" }] });
  M.copy();
  await settle();
  assert.equal(written[1], "TinyPPI — Dolby Vision metadata view\n\n[L6 - No]");
});

test("without the clipboard the report is saved under the film's name, tailed metadata", async (t) => {
  const { M, window } = metadataTab(t);
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true, value: { writeText: async () => { throw new Error("insecure"); } },
  });
  const blobs = [];
  window.URL.createObjectURL = (blob) => { blobs.push(blob); return "blob:metadata"; };
  window.URL.revokeObjectURL = () => {};
  const saved = [];
  window.document.addEventListener("click", (event) => {
    saved.push({ name: event.target.download, href: event.target.href });
    event.preventDefault();
  });
  M.render({ playing: true, title: "Film: Part 2", metadata: ROWS });
  M.copy();
  await settle();
  assert.equal(saved.length, 1);
  assert.equal(saved[0].name, "TinyPPI_Film_Part_2_metadata.txt");
  assert.equal(saved[0].href, "blob:metadata");
  assert.equal(blobs[0].type, "text/plain");
  const text = await blobs[0].text();
  assert.ok(text.startsWith("TinyPPI — Dolby Vision metadata view\nFilm: Part 2\n\n[L1]\n"), text);
  assert.ok(text.endsWith("2100  2000  1990"), text);
});

test("nothing listed is nothing to copy", async (t) => {
  const { M, window } = metadataTab(t);
  const written = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true, value: { writeText: async (text) => { written.push(text); } },
  });
  assert.equal(M.listed(), false);
  M.copy();
  M.render({ playing: true });
  assert.equal(M.listed(), false);
  M.copy();
  M.render({ playing: true, metadata: ROWS });
  assert.equal(M.listed(), true);
  M.render({ playing: true, metadata: [] });
  assert.equal(M.listed(), false);
  M.copy();
  await settle();
  assert.deepEqual(written, []);
});

test("the strings title the cards and write the idle card again", (t) => {
  const { $, M, window } = metadataTab(t);
  const T = window.TinyPPI.T;
  M.strings({ ...T, active_area: "Aktives Bild", metadata_section: "Metadaten" });
  assert.equal($("frameTitle").textContent, "Aktives Bild");
  assert.equal($("metadataTitle").textContent, "Metadaten");
  assert.ok($("metaIdleCard").classList.contains("hidden"), "nothing drawn before a snapshot");

  M.render({ playing: false });
  assert.equal($("metaIdleTitle").textContent, "Nothing is playing");
  Object.assign(T, { idle_title: "Nichts läuft", idle_text: "Starte einen Film." });
  M.strings(T);
  assert.equal($("metaIdleTitle").textContent, "Nichts läuft");
  assert.equal($("metaIdleText").textContent, "Starte einen Film.");
});
