// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The chapters on the progress bar (resources/web/js/live-chapters.js): the
// dots ahead of the position, every one while a mouse is over the bar, the
// chapter the position is in, the name under the pointer, a tap on a dot that
// jumps to it, Page Up and Page Down, and the switch on the settings tab -- on
// the real page, through the live panels that host them.

import assert from "node:assert/strict";
import { join, dirname } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { bare, page, source } from "./harness.mjs";

const SCRIPTS = ["core.js", "readings.js", "live-chapters.js", "live-remote.js", "live-panels.js"];
const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");

const CHAPTERS = [
  { index: 1, start: 0, at: 0, time: "00:00:00", name: "Opening" },
  { index: 2, start: 1800, at: 25, time: "00:30:00", name: "Arrival" },
  { index: 3, start: 3636, at: 50.5, time: "01:00:36", name: "" },
  { index: 4, start: 6840, at: 95, time: "01:54:00", name: "Credits" },
];

const SNAPSHOT = {
  playing: true, paused: false, title: "Film", time: "00:36:00", duration: "02:00:00",
  groups: [], metrics: { progress: 30 }, session: {},
  chapters: CHAPTERS, chapter: 2,
};

const snap = (over = {}) => ({ ...SNAPSHOT, ...over });

/** The panels on the real page, the bar laid out *width* pixels wide from
 * x = 100, and the page's timers held. */
function chapters(t, { width = 206, stored, routes = {} } = {}) {
  const view = page({ scripts: [], routes: { "/api/command": [200, {}], ...routes } });
  const { window } = view;
  t.after(() => window.close());
  if (stored !== undefined) window.localStorage.setItem("tinyppi.chapters", stored);
  for (const name of SCRIPTS) load(view.dom, name);
  const $ = (id) => window.document.getElementById(id);
  const box = { left: 100, width };
  $("track").getBoundingClientRect = () => box;
  const timers = new Map();
  let next = 1;
  window.setTimeout = (fn, delay) => { timers.set(next, { fn, delay }); return next++; };
  window.clearTimeout = (id) => { timers.delete(id); };
  const runTimers = () => {
    const due = [...timers.values()];
    timers.clear();
    for (const timer of due) timer.fn();
  };
  const commands = () => view.requests
    .filter((request) => request.url === "/api/command")
    .map((request) => JSON.parse(request.init.body));
  const dots = () => [...$("chapterDots").children];
  /* Where a dot at *at* % is on the screen: three pixels in from either end. */
  const xOf = (at) => box.left + 3 + at / 100 * (box.width - 6);
  /* Where *percent* of the bar is, end to end, which is what a drag reads. */
  const along = (percent) => box.left + box.width * percent / 100;
  const mouse = (type, clientX) =>
    $("track").dispatchEvent(new window.MouseEvent(type, { clientX, bubbles: true }));
  /* A pointer event on the bar, from pointer 1 unless said otherwise. */
  const pointer = (type, clientX, more = {}) => $("track").dispatchEvent(
    new window.PointerEvent(type, { clientX, pointerId: 1, button: 0, bubbles: true, ...more }));
  /* A press and a release in one place, and the click a browser adds. */
  const tap = (clientX) => {
    for (const type of ["pointerdown", "pointerup", "click"]) pointer(type, clientX);
  };
  return { ...view, $, box, timers, runTimers, commands, dots, xOf, along, mouse, pointer, tap,
           P: window.TinyPPI.panels };
}

function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

const lefts = (nodes) => nodes.map((node) => node.style.left);
const played = (nodes) => nodes.map((node) => node.classList.contains("played"));

test("a dot where each chapter ahead starts, none behind the position", (t) => {
  const { $, P, dots } = chapters(t);
  assert.ok($("chapterDots").classList.contains("hidden"), "no dots before a title");
  P.update(snap());
  assert.equal($("chapterDots").classList.contains("hidden"), false);
  assert.deepEqual(lefts(dots()), ["50.5%", "95%"], "25 % is behind the bar at 30 %");
  assert.ok(dots().every((node) => node.className === "chapter-dot"));
  P.update(snap({ chapter: 0, metrics: { progress: 0 } }));   // nothing seen yet
  assert.deepEqual(lefts(dots()), ["25%", "50.5%", "95%"], "and none at the very beginning");
});

test("the dots are built once and a dot goes as the bar passes it", (t) => {
  const { P, dots } = chapters(t);
  P.update(snap());
  const first = dots()[0];
  P.update(snap({ metrics: { progress: 40 } }));
  assert.equal(dots()[0], first, "the same nodes");
  P.update(snap({ metrics: { progress: 51 }, chapter: 3 }));
  assert.deepEqual(lefts(dots()), ["95%"]);
  P.update(snap({ metrics: { progress: 96 }, chapter: 4 }));
  assert.equal(dots().length, 0);
});

test("a mouse over the bar shows every chapter, those already seen as well", (t) => {
  const { $, P, dots, mouse, tap, xOf, commands, window } = chapters(t);
  P.update(snap({ control: true, controls: { chapters: 4 }, chapter: 3, metrics: { progress: 60 } }));
  assert.deepEqual(lefts(dots()), ["95%"]);
  mouse("pointermove", xOf(25));
  assert.ok($("chapterTip").classList.contains("hidden"), "no dot, no name");

  mouse("pointerenter", xOf(25));
  assert.deepEqual(lefts(dots()), ["25%", "50.5%", "95%"]);
  assert.deepEqual(played(dots()), [true, true, false], "the ones behind in a light tone of the accent");
  mouse("pointermove", xOf(25));
  assert.equal($("chapterTip").textContent, "Chapter 2 · Arrival · 00:30:00");
  tap(xOf(25));
  assert.deepEqual(commands().at(-1), { action: "chapter_goto", value: 2 });

  $("track").dispatchEvent(new window.Event("pointerleave"));
  assert.deepEqual(lefts(dots()), ["95%"]);
  assert.ok($("chapterTip").classList.contains("hidden"));

  // A finger is on the bar for the tap alone: it brings none of them up.
  const touch = new window.Event("pointerenter");
  Object.defineProperty(touch, "pointerType", { value: "touch" });
  $("track").dispatchEvent(touch);
  assert.deepEqual(lefts(dots()), ["95%"]);
  mouse("click", xOf(25));
  assert.ok($("chapterTip").classList.contains("hidden"), "a tap names no dot it cannot see");
});

test("dots too close to tell apart are drawn as one that answers for both", (t) => {
  const { $, P, dots, box } = chapters(t);
  const close = [...CHAPTERS.slice(0, 3),
                 { index: 4, start: 3650, at: 51, time: "01:00:50", name: "Twin" }];
  P.update(snap({ chapters: close }));
  assert.deepEqual(lefts(dots()), ["50.5%"], "51 % is under six pixels from 50.5 % on a 206-pixel bar");
  P.update(snap({ chapters: close, chapter: 3, metrics: { progress: 50.7 } }));
  assert.deepEqual(lefts(dots()), ["51%"], "past the first, the second has a dot of its own");

  P.update(snap({ chapters: close }));
  box.width = 2006;
  P.draw();                                       // the tab came forward, wider
  assert.deepEqual(lefts(dots()), ["50.5%", "51%"]);
  assert.equal($("chapterNow").textContent, "Chapter 2 of 4 · Arrival");
});

test("a bar that is not laid out yet draws every dot", (t) => {
  const { P, dots } = chapters(t, { width: 0 });
  const close = [...CHAPTERS.slice(0, 3),
                 { index: 4, start: 3650, at: 51, time: "01:00:50", name: "" }];
  P.update(snap({ chapters: close }));
  assert.equal(dots().length, 2);
  P.update(snap({ chapters: close }));            // still not laid out: asked again
  assert.equal(dots().length, 2);
});

test("a resize lays the dots out again once it has settled", (t) => {
  const { P, dots, box, timers, runTimers, window } = chapters(t);
  const close = [...CHAPTERS.slice(0, 3),
                 { index: 4, start: 3650, at: 51, time: "01:00:50", name: "" }];
  P.update(snap({ chapters: close }));
  assert.equal(dots().length, 1);
  box.width = 2006;
  P.update(snap({ chapters: close }));
  assert.equal(dots().length, 1, "the width is only read again after a resize");
  window.dispatchEvent(new window.Event("resize"));
  assert.deepEqual([...timers.values()].map((timer) => timer.delay), [120]);
  runTimers();
  assert.equal(dots().length, 2);
});

test("the chapter the position is in is named over the bar", (t) => {
  const { $, P } = chapters(t);
  const label = $("chapterNow");
  assert.ok(label.classList.contains("hidden"));
  P.update(snap());
  assert.equal(label.classList.contains("hidden"), false);
  assert.equal(label.querySelector(".chapter-num").textContent, "Chapter 2 of 4");
  assert.equal(label.querySelector(".chapter-name").textContent, " · Arrival");
  const number = label.firstElementChild;
  P.update(snap());
  assert.equal(label.firstElementChild, number, "written only when it changes");

  P.update(snap({ chapter: 3 }));                 // a chapter with no name
  assert.equal(label.textContent, "Chapter 3 of 4");
  assert.equal(label.querySelector(".chapter-name"), null);

  P.update(snap({ chapter: 0 }));                 // before the first one starts
  assert.ok(label.classList.contains("hidden"));
  assert.equal(label.textContent, "");
});

test("a title without chapters shows neither dots nor a label", (t) => {
  const { $, P, dots } = chapters(t);
  P.update(snap());
  P.update(snap({ chapters: undefined, chapter: undefined }));
  assert.equal(dots().length, 0);
  assert.ok($("chapterDots").classList.contains("hidden"));
  assert.ok($("chapterNow").classList.contains("hidden"));
  P.update(snap({ chapters: "junk", chapter: "x" }));
  assert.equal(dots().length, 0);
});

test("the label takes the words of the box's language", (t) => {
  const { $, P, window } = chapters(t);
  P.update(snap());
  window.TinyPPI.T.chapter_of = "Kapitel %s von %s";
  P.strings({ ...window.TinyPPI.T });
  assert.equal($("chapterNow").textContent, "Kapitel 2 von 4 · Arrival");
});

test("a pointer over a dot names it, and leaving the bar puts the name away", (t) => {
  const { $, P, mouse, xOf, window } = chapters(t);
  const tip = $("chapterTip");
  P.update(snap());
  assert.ok(tip.classList.contains("hidden"));

  mouse("pointerenter", xOf(25) + 8);
  mouse("pointermove", xOf(25) + 8);
  assert.equal(tip.classList.contains("hidden"), false);
  assert.equal(tip.textContent, "Chapter 2 · Arrival · 00:30:00");
  assert.equal(tip.style.left, "25%");
  assert.deepEqual(["start", "end"].filter((name) => tip.classList.contains(name)), []);

  mouse("pointermove", xOf(50.5));
  assert.equal(tip.textContent, "Chapter 3 · 01:00:36", "no name, no gap for one");

  mouse("pointermove", xOf(95) - 2);
  assert.ok(tip.classList.contains("end"));

  mouse("pointermove", xOf(25) + 11);
  assert.ok(tip.classList.contains("hidden"), "out of reach");

  mouse("pointermove", xOf(25));
  $("track").dispatchEvent(new window.Event("pointerleave"));
  assert.ok(tip.classList.contains("hidden"));
});

test("the nearer of two dots in reach is the one named", (t) => {
  const { $, P, mouse, xOf, box } = chapters(t);
  box.width = 1006;
  const near = [CHAPTERS[0], { ...CHAPTERS[1], at: 10 }, { ...CHAPTERS[2], at: 11.5 }];
  P.update(snap({ chapters: near }));
  mouse("pointerenter", xOf(11.5) - 6);
  mouse("pointermove", xOf(11.5) - 6);
  assert.equal($("chapterTip").textContent, "Chapter 3 · 01:00:36");
  mouse("pointermove", xOf(10) + 6);
  assert.equal($("chapterTip").textContent, "Chapter 2 · Arrival · 00:30:00");
  assert.ok($("chapterTip").classList.contains("start"));
});

test("a tap names the dot it landed on for a while, control or not", (t) => {
  const { $, P, mouse, xOf, timers, runTimers, commands } = chapters(t);
  const tip = $("chapterTip");
  P.update(snap({ control: false }));
  mouse("click", xOf(50.5));
  assert.equal(tip.textContent, "Chapter 3 · 01:00:36");
  assert.ok([...timers.values()].some((timer) => timer.delay === 2000));
  assert.deepEqual(commands(), [], "no control, no jump");
  runTimers();
  assert.ok(tip.classList.contains("hidden"));

  mouse("click", xOf(75));
  assert.ok(tip.classList.contains("hidden"), "a tap between dots names nothing");
});

test("with control a tap on a dot jumps to that chapter, anywhere else seeks", (t) => {
  const { $, P, tap, xOf, commands, box } = chapters(t);
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  tap(xOf(50.5) - 4);
  assert.deepEqual(commands(), [{ action: "chapter_goto", value: 3 }], "one command, not two");
  assert.equal($("bar").style.width, "50.5%");

  tap(box.left + box.width / 2 + 30);
  assert.equal(commands().at(-1).action, "seek_percent");
});

test("a drag holds the bar, brings up every chapter and snaps onto one", (t) => {
  const { $, P, dots, pointer, xOf, along, commands } = chapters(t, { width: 200 });
  const track = $("track");
  const captured = [];
  track.setPointerCapture = (id) => captured.push(id);
  P.update(snap({ control: true, controls: { chapters: 4 }, chapter: 3, metrics: { progress: 60 } }));
  assert.deepEqual(lefts(dots()), ["95%"]);

  pointer("pointerdown", along(70));
  assert.deepEqual(captured, [1]);
  assert.ok(track.classList.contains("dragging"), "the fill follows without easing");
  assert.deepEqual(lefts(dots()), ["25%", "50.5%", "95%"], "every chapter while it is held");
  assert.equal($("bar").style.width, "70%");
  assert.equal($("tElapsed").textContent, "01:24:00", "the clock follows the finger");
  assert.equal($("chapterNow").textContent, "Chapter 3 of 4", "and so does the label");

  // The box goes on reporting where it is; the bar stays under the finger.
  P.update(snap({ control: true, controls: { chapters: 4 }, chapter: 3, metrics: { progress: 61 },
                  time: "01:13:12" }));
  assert.equal($("bar").style.width, "70%");
  assert.equal($("tElapsed").textContent, "01:24:00");

  pointer("pointermove", xOf(25) + 5);
  assert.equal($("bar").style.width, "25%", "close to a dot, onto it");
  assert.equal($("tElapsed").textContent, "00:30:00");
  assert.equal($("chapterNow").textContent, "Chapter 2 of 4 · Arrival");
  assert.equal($("chapterTip").textContent, "Chapter 2 · Arrival · 00:30:00");
  assert.deepEqual(dots().map((node) => node.classList.contains("played")), [true, false, false]);

  pointer("pointermove", xOf(10), { pointerId: 2 });  // another finger moves nothing
  pointer("pointerup", xOf(10), { pointerId: 2 });
  assert.equal($("bar").style.width, "25%");
  assert.deepEqual(commands(), []);

  pointer("pointerup", xOf(25) + 5);
  assert.deepEqual(commands(), [{ action: "chapter_goto", value: 2 }]);
  assert.equal(track.classList.contains("dragging"), false);
  assert.deepEqual(lefts(dots()), ["95%"], "let go, the chapters behind go again");
  assert.equal($("chapterNow").textContent, "Chapter 3 of 4");
  P.update(snap({ control: true, controls: { chapters: 4 }, chapter: 2, metrics: { progress: 25 },
                  time: "00:30:00" }));
  assert.equal($("bar").style.width, "25%");
});

test("a drag let go between dots seeks there, and one the browser cancels sends nothing", (t) => {
  const { $, P, pointer, xOf, along, commands } = chapters(t, { width: 200 });
  P.update(snap({ control: true, controls: { chapters: 4 }, duration: "45:00" }));
  pointer("pointerdown", along(40));
  assert.equal($("tElapsed").textContent, "18:00", "a clock shaped like the length");
  pointer("pointerup", along(40));
  assert.deepEqual(commands(), [{ action: "seek_percent", value: 40 }]);

  pointer("pointerdown", xOf(70));
  pointer("pointercancel", xOf(70), { pointerId: 2 });   // not this drag's
  pointer("pointercancel", xOf(70));
  pointer("pointerup", xOf(70));
  assert.equal(commands().length, 1, "a scroll took it over");
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  assert.equal($("bar").style.width, "30%", "and the bar is the box's again");
});

test("a drag needs control, the main button and a bar with a width", (t) => {
  const { $, P, pointer, xOf, commands, box } = chapters(t);
  P.update(snap({ control: false }));
  pointer("pointerdown", xOf(70));
  pointer("pointerup", xOf(70));
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  pointer("pointerdown", xOf(70), { button: 2 });
  pointer("pointerup", xOf(70), { button: 2 });
  pointer("pointermove", xOf(70));
  box.width = 0;
  pointer("pointerdown", 0);
  pointer("pointerup", 0);
  assert.deepEqual(commands(), []);

  // Control taken away in the middle of a drag ends it.
  box.width = 206;
  pointer("pointerdown", xOf(70));
  P.update(snap({ control: false, duration: "soon" }));
  pointer("pointerup", xOf(70));
  assert.deepEqual(commands(), []);
  assert.equal($("chapterNow").textContent, "Chapter 2 of 4 · Arrival");
});

test("a drag before the first chapter has begun names none", (t) => {
  const { $, P, pointer, xOf } = chapters(t);
  const later = [{ index: 1, start: 600, at: 10, time: "00:10:00", name: "Late" },
                 { index: 2, start: 3600, at: 50, time: "01:00:00", name: "" }];
  P.update(snap({ control: true, controls: { chapters: 2 }, chapters: later, chapter: 1,
                  duration: "soon" }));
  const clock = $("tElapsed").textContent;
  pointer("pointerdown", xOf(3));
  assert.ok($("chapterNow").classList.contains("hidden"));
  assert.equal($("tElapsed").textContent, clock, "a length that is no clock leaves the clock be");
  pointer("pointerup", xOf(3));
  P.update(snap({ control: true, controls: { chapters: 2 }, chapters: later, chapter: 1,
                  duration: "ab:cd", time: "00:01:00" }));
  pointer("pointerdown", xOf(3));
  assert.equal($("tElapsed").textContent, "00:01:00", "nor does one that only looks like one");
  pointer("pointerup", xOf(3));
});

test("Page Up and Page Down step a chapter on a file that has them", (t) => {
  const { $, P, commands } = chapters(t);
  const key = (name) => {
    const event = new ($("track").ownerDocument.defaultView.KeyboardEvent)(
      "keydown", { key: name, cancelable: true });
    $("track").dispatchEvent(event);
    return event.defaultPrevented;
  };
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  assert.equal(key("PageUp"), true);
  assert.equal(key("PageDown"), true);
  assert.deepEqual(commands().map((command) => command.action), ["chapter_previous", "chapter_next"]);

  P.update(snap({ control: true, controls: { chapters: 1 } }));
  assert.equal(key("PageUp"), false, "left to scroll the page");
  assert.equal(key("PageDown"), false);
  assert.equal(commands().length, 2);
});

test("the switch on the settings tab takes the dots off the bar and is remembered", (t) => {
  const { $, P, dots, mouse, tap, xOf, commands, window } = chapters(t);
  const toggle = $("chapterMarks");
  assert.equal(toggle.checked, true, "on until switched off");
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  mouse("pointermove", xOf(50.5));
  assert.equal($("chapterTip").classList.contains("hidden"), false);

  toggle.checked = false;
  toggle.dispatchEvent(new window.Event("change"));
  assert.equal(window.localStorage.getItem("tinyppi.chapters"), "0");
  assert.ok($("chapterDots").classList.contains("hidden"));
  assert.ok($("chapterNow").classList.contains("hidden"));
  assert.ok($("chapterTip").classList.contains("hidden"));
  P.update(snap({ control: true, controls: { chapters: 4 } }));
  mouse("pointermove", xOf(50.5));
  assert.ok($("chapterTip").classList.contains("hidden"), "no dots, no names");
  tap(xOf(50.5));
  assert.equal(commands().at(-1).action, "seek_percent", "and a tap is a tap on the bar");

  toggle.checked = true;
  toggle.dispatchEvent(new window.Event("change"));
  assert.equal(window.localStorage.getItem("tinyppi.chapters"), "1");
  assert.equal(dots().length, 2);
  assert.equal($("chapterNow").classList.contains("hidden"), false);
});

test("a device that switched the dots off finds them off", (t) => {
  const { $, P, dots } = chapters(t, { stored: "0" });
  assert.equal($("chapterMarks").checked, false);
  P.update(snap());
  assert.equal(dots().length, 0);
  assert.ok($("chapterNow").classList.contains("hidden"));
});

test("when playback ends the dots, the label and the name are put away", (t) => {
  const { $, P, dots, mouse, xOf } = chapters(t);
  P.update(snap());
  mouse("pointermove", xOf(50.5));
  P.update({ playing: false, groups: [], metrics: {} });
  assert.equal(dots().length, 0);
  assert.ok($("chapterDots").classList.contains("hidden"));
  assert.ok($("chapterNow").classList.contains("hidden"));
  assert.ok($("chapterTip").classList.contains("hidden"));
});

test("a page without the switch, and a browser that blocks storage", () => {
  const window = bare("core.js", "live-chapters.js");
  Object.defineProperty(window, "localStorage", {
    configurable: true, get() { throw new window.DOMException("blocked", "SecurityError"); }
  });
  const document = window.document;
  const node = (tag) => document.body.appendChild(document.createElement(tag));
  const el = { track: node("div"), dots: node("span"), now: node("div"), tip: node("span") };
  el.track.getBoundingClientRect = () => ({ left: 0, width: 106 });
  const marks = window.TinyPPIChapters.create(el);
  marks.render({ chapters: CHAPTERS, chapter: 2 }, 30);
  assert.equal(el.dots.children.length, 2, "shown when storage cannot say otherwise");
  assert.deepEqual(JSON.parse(JSON.stringify(marks.hit(3 + 50.5))), { index: 3, at: 50.5 });
  assert.equal(marks.hit(3 + 25), null, "behind the position, no dot to hit");
  assert.equal(marks.hit(3 + 75), null);
  marks.reset();
  assert.equal(marks.hit(3 + 50.5), null, "no dots, nothing to hit");
  el.track.getBoundingClientRect = () => ({ left: 0, width: 0 });
  marks.render({ chapters: CHAPTERS, chapter: 2 }, 30);
  assert.equal(marks.hit(3), null, "a bar with no width is hit nowhere");

  const toggle = node("input");
  toggle.type = "checkbox";
  const second = { track: node("div"), dots: node("span"), now: node("div"), tip: node("span"), toggle };
  const switched = window.TinyPPIChapters.create(second);
  assert.equal(toggle.checked, true);
  toggle.checked = false;
  toggle.dispatchEvent(new window.Event("change"));   // not remembered, but switched
  switched.render({ chapters: CHAPTERS, chapter: 2 }, 30);
  assert.ok(second.dots.classList.contains("hidden"));
  window.close();
});
