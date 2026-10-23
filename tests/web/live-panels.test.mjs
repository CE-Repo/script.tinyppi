// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The live panels (resources/web/js/live-panels.js): the now-playing card
// with its poster, badges and progress, the remote and its track pickers,
// the four figures, the event list fetched from /api/history, the luminance
// chart, and what the dashboard reads back (events, peak, draw).

import assert from "node:assert/strict";
import { test } from "node:test";
import { bare, page, settle } from "./harness.mjs";

const SCRIPTS = ["core.js", "readings.js", "live-chapters.js", "live-remote.js", "live-panels.js"];
const START = 1_700_000_000_000;

/* The shapes tests/browser/serve.py serves, which are the add-on's own. */
const GROUPS = [
  { id: "video", title: "Video", rows: [
    { id: "video.res", label: "Resolution", value: "3840x2160p 23.976FPS", detail: "" },
    { id: "video.hdr", label: "HDR", value: "Dolby Vision ✔", detail: "" },
    { id: "dv.profile", label: "Profile", value: "7.6", detail: "" },
    { id: "dv.layer", label: "Layer", value: "FEL", detail: "" }] },
  { id: "audio", title: "Audio", rows: [
    { id: "audio.32238", label: "Codec", value: "TrueHD Atmos 7.1", detail: "" }] }];

const SNAPSHOT = {
  playing: true, paused: false, title: "Film", time: "00:10:00", duration: "02:00:00",
  hdr_type: "dolbyvision", output_type: "dolbyvision", groups: GROUPS,
  metrics: { fps_out: 23.976, cache: 87.6, progress: 8.4,
             l1: { max: 1000, avg: 120 }, frame: { w: 3840, h: 2160 } },
  session: { switches: 1, warnings: 2 },
};

const HISTORY = {
  t: [0, 1], max: [900, 1000], avg: [100, 120], now: 1, step: 1, seq: 3, switches: 4,
  events: [
    { t: 0.5, pos: "00:00:10", kind: "fps", from: 24, to: 60 },
    { t: 0.8, pos: "00:00:12", kind: "audio",
      from: "#1 · ENG · English", to: "#2 · GER · Deutsch" },
    { t: 0.9, pos: "00:00:13", kind: "temperature", value: 77.4 }],
};

const snap = (over = {}) => ({ ...SNAPSHOT, ...over });
const metrics = (over = {}) => ({ ...SNAPSHOT.metrics, ...over });

/* Where the chart puts a reading, from the margins drawLuminance uses on a
   300 x 150 box: 34 px left, 6 right, 8 top, 6 bottom, four decades above
   0.01 nits on a log axis. */
const yOf = (nits) => 8 + 136 * (1 - (Math.log10(nits) + 2) / 6);
const xOf = (age, span) => 34 + 260 * (1 - Math.min(1, age / span));

const close = (actual, expected, message) =>
  assert.ok(Math.abs(actual - expected) < 1e-6, `${message || ""} ${actual} is not ${expected}`);

function closePath(actual, expected) {
  assert.equal(actual.length, expected.length, "path length");
  actual.forEach(([verb, x, y], index) => {
    assert.equal(verb, expected[index][0]);
    if (verb !== "Z") {
      close(x, expected[index][1], `x of point ${index}:`);
      close(y, expected[index][2], `y of point ${index}:`);
    }
  });
}

/** The panels on the real page, with the clock and the network in the
 * test's hands. */
function panels(t, { routes = {}, token = "" } = {}) {
  const view = page({
    scripts: SCRIPTS, token,
    routes: { "/api/command": [200, {}], "/api/history": [200, HISTORY], ...routes },
  });
  const { window } = view;
  t.after(() => window.close());
  const clock = { now: START };
  window.Date.now = () => clock.now;
  const $ = (id) => window.document.getElementById(id);
  const commands = () => view.requests
    .filter((request) => request.url === "/api/command")
    .map((request) => JSON.parse(request.init.body));
  const fetched = (path) => view.requests
    .filter((request) => request.url.replace(/\?.*$/, "") === path);
  return { ...view, $, clock, commands, fetched, P: window.TinyPPI.panels };
}

/* jsdom lays nothing out and has no canvas: the chart's box is given a size
   and its context is a recorder, one frame per clearRect, so a test reads back
   what was drawn. */
function fakeCanvas(window, { width = 300, height = 150 } = {}) {
  const canvas = window.document.getElementById("chart");
  const box = { width, height };
  Object.defineProperty(canvas, "clientWidth", { configurable: true, get: () => box.width });
  Object.defineProperty(canvas, "clientHeight", { configurable: true, get: () => box.height });
  const frames = [];
  let frame = null;
  let path = [];
  let dash = [];
  const ctx = {
    setTransform(...args) { this.transform = args; },
    clearRect(...args) {
      frame = { clear: args, transform: this.transform, ops: [] };
      frames.push(frame);
    },
    setLineDash(next) { dash = [...next]; },
    beginPath() { path = []; },
    moveTo(x, y) { path.push(["M", x, y]); },
    lineTo(x, y) { path.push(["L", x, y]); },
    closePath() { path.push(["Z"]); },
    stroke() {
      frame.ops.push({ op: "stroke", style: this.strokeStyle, width: this.lineWidth, dash, path });
    },
    fill() { frame.ops.push({ op: "fill", style: this.fillStyle, alpha: this.globalAlpha, path }); },
    fillText(text, x, y) { frame.ops.push({ op: "text", text, x, y }); },
    createLinearGradient(...args) {
      const gradient = { args, stops: [], addColorStop: (at, colour) => gradient.stops.push([at, colour]) };
      return gradient;
    },
  };
  canvas.getContext = (kind) => (kind === "2d" ? ctx : null);
  const last = () => frames.at(-1);
  const strokes = () => last().ops.filter((op) => op.op === "stroke");
  return { canvas, box, frames, last, strokes };
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

// Objects built inside the page have the page's prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));
const texts = (nodes) => [...nodes].map((node) => node.textContent);

test("a page without a live mount point gets no panels", () => {
  const window = bare(...SCRIPTS);
  assert.equal(window.TinyPPI.panels, undefined);
  window.close();
});

test("the panels arrive hidden, with the chart and the events unfolded", (t) => {
  const { $ } = panels(t);
  const toggle = $("controlToggle");
  assert.equal(toggle.parentElement, $("nowCard"));
  assert.ok(toggle.classList.contains("hidden"));
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.getAttribute("aria-controls"), "controlDrawer");
  assert.equal($("controlDrawer").classList.contains("open"), false);
  assert.equal($("tiles").open, false);
  assert.equal($("chartCard").open, true);
  assert.equal($("eventsCard").open, true);
  for (const id of ["tiles", "chartCard", "eventsCard"]) {
    assert.ok($(id).classList.contains("hidden"), id);
  }
});

test("what is playing: title, show line, file, progress and times", (t) => {
  const { $, P } = panels(t);
  P.update(snap({ media: { show: "Show", season: "2", episode: "5", year: "2024", genre: "Drama",
                           studios: ["A Studio", "Another"] },
                  filename: "/films/Show.S02E05.mkv" }));
  assert.equal($("nowCard").classList.contains("hidden"), false);
  assert.equal($("title").textContent, "Film");
  assert.equal($("meta").textContent, "Show · 2×05  ·  2024  ·  Drama");
  // The studio on a line of its own under the genre.
  assert.equal($("meta").nextElementSibling, $("studio"));
  assert.equal($("studio").textContent, "A Studio, Another");
  assert.equal($("file").textContent, "/films/Show.S02E05.mkv");
  assert.equal($("file").classList.contains("hidden"), false);
  assert.equal($("bar").style.width, "8.4%");
  assert.equal($("track").getAttribute("aria-valuenow"), "8");
  assert.equal($("tElapsed").textContent, "00:10:00");
  assert.equal($("tTotal").textContent, "02:00:00");

  P.update(snap({ title: "", media: { show: "Show" }, time: undefined, duration: undefined,
                  metrics: metrics({ progress: null }) }));
  assert.equal($("title").textContent, "—");
  assert.equal($("meta").textContent, "Show");
  assert.equal($("studio").textContent, "");
  assert.ok($("file").classList.contains("hidden"));
  assert.equal($("bar").style.width, "0%");
  assert.equal($("track").getAttribute("aria-valuenow"), "0");
  assert.equal($("tElapsed").textContent, "--:--");
  assert.equal($("tTotal").textContent, "--:--");

  // Kodi numbers the specials season 0, and says so as text.
  P.update(snap({ media: { show: "Show", season: "0", episode: "3" } }));
  assert.equal($("meta").textContent, "Show · 0×03");

  // A list the add-on cut ends in an ellipsis.
  P.update(snap({ media: { studios: ["One", "Two", "Three", "Four"], studios_more: true } }));
  assert.equal($("studio").textContent, "One, Two, Three, Four, …");

  P.update(snap({ metrics: undefined }));
  assert.equal($("meta").textContent, "");
  assert.equal($("bar").style.width, "0%");
});

test("who directed it stands in the card of what is playing, over its badges", (t) => {
  const { $, P } = panels(t);
  P.update(snap({ media: { directors: ["Denis Villeneuve"] } }));
  // The last line over the badges, the name alone.
  assert.equal($("director").nextElementSibling, $("formats"));
  assert.equal($("director").classList.contains("hidden"), false);
  assert.equal($("director").textContent, "Denis Villeneuve");

  // One the add-on cut ends in an ellipsis.
  P.update(snap({ media: { directors: ["Joel Coen"], directors_more: true } }));
  assert.equal($("director").textContent, "Joel Coen, …");

  // Written only when it changes.
  const written = $("director").firstChild;
  P.update(snap({ media: { directors: ["Joel Coen"], directors_more: true } }));
  assert.equal($("director").firstChild, written);

  // None: gone, and the overview no card for it.
  P.update(snap({ media: { directors: [] } }));
  assert.ok($("director").classList.contains("hidden"));
  assert.equal($("director").textContent, "");
  P.update(snap({ media: { directors: ["Somebody"] } }));
  assert.ok($("plotCard").classList.contains("hidden"));
});

test("the plot card: the plot under what is playing, with its slogan where there is one", (t) => {
  const { $, P, window } = panels(t);
  assert.equal($("nowCard").nextElementSibling, $("plotCard"));
  assert.ok($("plotCard").classList.contains("hidden"));
  assert.equal($("plotCard").open, true, "it arrives unfolded");

  P.update(snap({ media: { tagline: " Long live the fighters. ",
                           plot: "Paul joins the Fremen.\nChani does not trust it." } }));
  assert.equal($("plotCard").classList.contains("hidden"), false);
  assert.equal($("tagline").textContent, "Long live the fighters.");
  assert.equal($("plotText").textContent, "Paul joins the Fremen.\nChani does not trust it.");
  assert.equal($("tagline").classList.contains("hidden"), false);
  assert.equal($("plotText").classList.contains("hidden"), false);

  // An episode: a plot and no slogan.
  P.update(snap({ media: { plot: "Episode plot." } }));
  assert.equal($("tagline").textContent, "");
  assert.ok($("tagline").classList.contains("hidden"));
  assert.equal($("plotText").textContent, "Episode plot.");
  assert.equal($("plotCard").classList.contains("hidden"), false);

  // A slogan and no plot: too little for a card.
  P.update(snap({ media: { tagline: "Only this." } }));
  assert.ok($("plotCard").classList.contains("hidden"));
  assert.ok($("plotText").classList.contains("hidden"));

  // A file the library does not know: neither, and no card.
  P.update(snap({ media: { tagline: "  ", plot: "" } }));
  assert.ok($("plotCard").classList.contains("hidden"));
  P.update(snap());
  assert.ok($("plotCard").classList.contains("hidden"));

  // Words that stayed the same are not written again.
  P.update(snap({ media: { plot: "Same." } }));
  const written = $("plotText").firstChild;
  P.update(snap({ media: { plot: "Same." } }));
  assert.equal($("plotText").firstChild, written);

  // Nothing playing puts it away with the rest.
  P.update({ playing: false });
  assert.ok($("plotCard").classList.contains("hidden"));

  P.strings({ ...window.TinyPPI.T, plot: "Handlung" });
  assert.equal($("plotTitle").textContent, "Handlung");
});

test("the overview card carries every rating as a shield with its mark, under the slogan and the plot", (t) => {
  const { $, P, window } = panels(t);
  /* Each shield as [class, what it says, its left, what is written on its right]. */
  const badges = () => [...$("ratings").children].map((node) => {
    const side = node.querySelector(".side");
    const image = side && side.querySelector("img");
    const drawn = !side ? "" : image
      ? side.className + " " + image.getAttribute("src")
      : side.className + ":" + side.textContent;
    const figures = node.querySelector(".figures");
    return [node.className, node.querySelector(".said").textContent, drawn,
            figures ? [...figures.children].map((part) => [part.className, part.textContent]) : []];
  });
  const rated = {
    tagline: "Long live the fighters.", plot: "Paul joins the Fremen.",
    ratings: [{ source: "imdb", rating: 8.5, votes: 612345 }, { source: "tmdb", rating: 8.2, votes: 0 },
              { source: "trakt", rating: 8.4, votes: 31902 },
              { source: "rottentomatoes", rating: 9.2, votes: 0 },
              { source: "letterboxd", rating: 8.9, votes: 3 }],
    userrating: 9, top250: 27, mpaa: "FSK 12", age: "fsk12", age_level: "12" };
  P.update(snap({ media: rated }));
  assert.equal($("plotCard").classList.contains("hidden"), false);
  assert.equal($("ratings").classList.contains("hidden"), false);
  // Under the slogan and the plot, and the cast where there is one: last.
  assert.equal($("ratings").nextElementSibling, null);
  assert.equal($("plotText").nextElementSibling, $("credits"));
  assert.equal($("tagline").nextElementSibling, $("plotText"));
  assert.deepEqual(plain(badges()), [
    ["rating age", "FSK 12", "side fsk12 plate /ratings/fsk12.svg", [["value", "12"]]],
    ["rating score", "IMDb 8.5, 612,345 votes", "side imdb /ratings/imdb.svg",
     [["value", "8.5"], ["note", "612,345"]]],
    ["rating score", "TMDb 8.2", "side tmdb /ratings/tmdb.svg", [["value", "8.2"]]],
    ["rating score", "Trakt 8.4, 31,902 votes", "side trakt /ratings/trakt.svg",
     [["value", "8.4"], ["note", "31,902"]]],
    ["rating score", "Rotten Tomatoes 9.2", "side rottentomatoes /ratings/rottentomatoes.svg", [["value", "9.2"]]],
    ["rating score", "Letterboxd 8.9, 3 votes", "side letter:L", [["value", "8.9"], ["note", "3"]]],
    ["rating mine", "My rating 9", "side heart:", [["value", "9"]]],
    ["rating rank", "Top 250 · #27", "side top250 /ratings/top250.svg", [["value", "#27"]]]]);
  // Said in words, drawn as marks: the drawing is kept from a screen reader.
  for (const node of $("ratings").children) {
    assert.equal(node.getAttribute("role"), "listitem");
    assert.equal(node.title, node.querySelector(".said").textContent);
    assert.equal(node.querySelector(".look").getAttribute("aria-hidden"), "true");
  }
  assert.equal($("ratings").querySelector("img").alt, "");

  // The same badges again are not built again.
  const first = $("ratings").firstChild;
  P.update(snap({ media: { ...rated } }));
  assert.equal($("ratings").firstChild, first);

  // The words arrive later, and the badges say them.
  P.strings({ ...window.TinyPPI.T, votes: "%s Stimmen", my_rating: "Eigene Bewertung",
              top250: "Top 250 · Platz %s" });
  const said = () => [...$("ratings").children].map((node) => node.querySelector(".said").textContent);
  assert.deepEqual(said().slice(0, 2), ["FSK 12", "IMDb 8.5, 612,345 Stimmen"]);
  assert.deepEqual(said().slice(6, 8), ["Eigene Bewertung 9", "Top 250 · Platz 27"]);

  // An age rating no FSK level is read from is written out, with no mark.
  P.update(snap({ media: { ...rated, ratings: [{ source: "imdb", rating: 7.0, votes: 0 }],
                           userrating: 0, top250: 0, mpaa: "Rated PG-13 for violence", age: "" } }));
  assert.deepEqual(plain(badges()), [
    ["rating age", "Rated PG-13 for violence", "", [["value", "Rated PG-13 for violence"]]],
    ["rating score", "IMDb 7.0", "side imdb /ratings/imdb.svg", [["value", "7.0"]]]]);

  // Ratings without a plot: the card for them alone, and no slogan.
  P.update(snap({ media: { tagline: "Only this.", mpaa: "FSK 16", age: "fsk16", age_level: "16" } }));
  assert.equal($("plotCard").classList.contains("hidden"), false);
  assert.deepEqual(plain(badges()), [["rating age", "FSK 16", "side fsk16 plate /ratings/fsk16.svg",
                                      [["value", "16"]]]]);

  assert.ok($("tagline").classList.contains("hidden"));
  assert.ok($("plotText").classList.contains("hidden"));
  // An American or a British one wears its own board's mark.
  for (const [mpaa, age, level] of [["Rated PG-13", "mpa_pg13", "PG-13"], ["TV-MA", "tv_ma", "MA"],
                                    ["Rated 15", "bbfc_15", "15"]]) {
    P.update(snap({ media: { plot: "Plot.", mpaa, age, age_level: level } }));
    assert.deepEqual(plain(badges()),
                     [["rating age", mpaa, `side ${age} plate /ratings/${age}.svg`, [["value", level]]]]);
  }
  // An add-on that sent the mark and not yet the level: the plate alone.
  P.update(snap({ media: { plot: "Plot.", mpaa: "FSK 6", age: "fsk6" } }));
  assert.deepEqual(plain(badges()), [["rating age", "FSK 6", "side fsk6 plate /ratings/fsk6.svg", []]]);

  // A plot without ratings: no row of badges.
  P.update(snap({ media: { plot: "An episode.", ratings: [], userrating: 0, top250: 0, mpaa: "" } }));
  assert.ok($("ratings").classList.contains("hidden"));
  assert.equal($("ratings").children.length, 0);
  assert.equal($("plotCard").classList.contains("hidden"), false);

  // Neither: no card.
  P.update(snap({ media: { tagline: "Only this.", ratings: [] } }));
  assert.ok($("plotCard").classList.contains("hidden"));

  // A source with no name is drawn on an empty plate and said by its figure.
  P.update(snap({ media: { ratings: [{ rating: 5 }] } }));
  assert.deepEqual(plain(badges()), [["rating score", "5.0", "side letter:", [["value", "5.0"]]]]);
});

test("the overview card ends with the credits, a line each under the ratings", (t) => {
  const { $, P, window } = panels(t);
  const lines = () => [...$("credits").children].map((line) =>
    [line.className, ...[...line.children].map((part) => part.tagName + " " + part.textContent)]);
  const credited = {
    plot: "Paul joins the Fremen.", ratings: [{ source: "imdb", rating: 8.5, votes: 0 }],
    genres: ["Science Fiction"], directors: ["Denis Villeneuve"],
    cast: ["Timothée Chalamet", "Zendaya", "Rebecca Ferguson", "Javier Bardem", "Josh Brolin"],
    cast_more: true, studios: ["Legendary Pictures"], studios_more: false
  };
  P.update(snap({ media: credited }));
  // Over the ratings, the cast, cut with an ellipsis; the genre, the
  // studio and the director are the card above's.
  assert.equal($("credits").nextElementSibling, $("ratings"));
  assert.equal($("credits").classList.contains("hidden"), false);
  assert.deepEqual(lines(), [
    ["credit", "DT Cast", "DD Timothée Chalamet, Zendaya, Rebecca Ferguson, Javier Bardem, Josh Brolin, …"]]);

  // The same credits again are not built again.
  const first = $("credits").firstChild;
  P.update(snap({ media: { ...credited } }));
  assert.equal($("credits").firstChild, first);

  // The words arrive later, into the page's table, and the lines are named
  // in them.
  Object.assign(window.TinyPPI.T, { cast: "Darsteller" });
  P.strings(window.TinyPPI.T);
  assert.deepEqual(lines().map((line) => line[1]), ["DT Darsteller"]);

  // A cast the add-on did not cut ends without one.  A studio or a
  // director alone is no credit.
  P.update(snap({ media: { plot: "Plot.", cast: ["Somebody", "Somebody Else"] } }));
  assert.deepEqual(lines(), [["credit", "DT Darsteller", "DD Somebody, Somebody Else"]]);
  P.update(snap({ media: { studios: ["A24"], directors: ["Somebody"] } }));
  assert.ok($("plotCard").classList.contains("hidden"));

  // Credits alone are still an overview.
  P.update(snap({ media: { cast: ["Somebody"] } }));
  assert.equal($("plotCard").classList.contains("hidden"), false);
  assert.ok($("plotText").classList.contains("hidden"));
  assert.ok($("ratings").classList.contains("hidden"));

  // None at all: no lines.
  P.update(snap({ media: { plot: "An episode.", genres: ["Drama"] } }));
  assert.ok($("credits").classList.contains("hidden"));
  assert.equal($("credits").children.length, 0);
});

test("the finish clock shows as it arrived and takes its label from the strings", (t) => {
  const { $, P, window } = panels(t);
  P.update(snap({ finish: "23:40" }));
  assert.equal($("tFinish").classList.contains("hidden"), false);
  assert.equal($("tFinishLabel").textContent, "");
  assert.equal($("tFinishTime").textContent, "23:40");

  P.strings({ ...window.TinyPPI.T, ends_at: "Ends at" });
  assert.equal($("tFinishLabel").textContent, "Ends at ");
  assert.equal($("tFinishTime").textContent, "23:40");

  P.update(snap({ finish: "" }));
  assert.ok($("tFinish").classList.contains("hidden"));
  assert.equal($("tFinishLabel").textContent, "");

  P.update(snap({ finish: "23:45" }));
  P.strings({ ...window.TinyPPI.T });          // a table without the label
  assert.equal($("tFinishLabel").textContent, "");
  assert.equal($("tFinishTime").textContent, "23:45");
});

test("the poster is fetched once per tag and handed to the cover tint", (t) => {
  const { $, P, window } = panels(t, { token: "AB" });
  // Without the tint script the poster still shows.
  P.update(snap({ art: { poster: "p1" } }));
  assert.equal($("poster").getAttribute("src"), "/api/art?kind=poster&v=p1");
  assert.equal($("artBox").classList.contains("hidden"), false);

  const shown = [];
  window.TinyPPICover = { show: (card, url, image) => shown.push([card.id, url, image && image.id]) };
  P.update(snap({ art: { poster: "p2" } }));
  P.update(snap({ art: { poster: "p2" } }));
  assert.deepEqual(shown, [["nowCard", "/api/art?kind=poster&v=p2", "poster"]]);

  $("poster").dispatchEvent(new window.Event("error"));
  assert.ok($("artBox").classList.contains("hidden"));
  assert.deepEqual(shown.at(-1), ["nowCard", "", "poster"]);

  P.update(snap({ art: undefined }));
  assert.equal($("poster").hasAttribute("src"), false);
  assert.ok($("artBox").classList.contains("hidden"));
  assert.equal(shown.length, 3);
  assert.equal(shown.at(-1)[1], "");
});

test("the badge row says only whether playback is held", (t) => {
  const { $, P } = panels(t);
  P.update(snap({ paused: true }));
  const badge = $("badges").firstElementChild;
  assert.equal($("badges").children.length, 1);
  assert.equal(badge.className, "badge alt");
  assert.equal(badge.querySelector("img").getAttribute("src"), "/icons/pause.svg");
  P.update(snap({ paused: true }));
  assert.equal($("badges").firstElementChild, badge, "not rebuilt for the same state");
  P.update(snap({ paused: false }));
  assert.equal($("badges").children.length, 0);
  assert.equal($("badges").dataset.paused, "false");
});

test("picture and sound badges are drawn and rebuilt only when they change", (t) => {
  const { $, P } = panels(t);
  P.update(snap());
  assert.deepEqual(texts($("pictureBadges").children), ["UHD", "DV P7.6 FEL"]);
  assert.deepEqual(texts($("soundBadges").children), ["TrueHD Atmos", "Atmos", "7.1"]);
  assert.ok([...$("soundBadges").children].every((node) => node.className === "format"));
  const first = $("soundBadges").firstElementChild;
  P.update(snap());
  assert.equal($("soundBadges").firstElementChild, first);
  P.update(snap({ groups: [GROUPS[0], { id: "audio", rows: [{ id: "audio.32238", value: "AAC 2.0" }] }] }));
  assert.deepEqual(texts($("soundBadges").children), ["AAC", "2.0"]);
  assert.notEqual($("soundBadges").firstElementChild, first);
});

test("the remote is built once and every key sends its command with the token", (t) => {
  const { $, P, commands, requests } = panels(t, { token: "AB" });
  P.update(snap({ control: true, controls: { chapters: 12 } }));
  assert.equal($("controlToggle").classList.contains("hidden"), false);
  assert.equal($("transport").classList.contains("hidden"), false);
  assert.ok($("track").classList.contains("seekable"));

  const jumps = [...$("transport").querySelectorAll(".tkeys .tbtn")];
  assert.deepEqual(texts(jumps), ["−10m", "−1m", "−10s", "+10s", "+1m", "+10m"]);
  assert.deepEqual(jumps.map((node) => node.title), texts(jumps));
  for (const key of jumps) key.click();
  assert.deepEqual(commands().map((command) => command.value), [-600, -60, -10, 10, 60, 600]);
  assert.ok(commands().every((command) => command.action === "seek"));
  assert.equal(requests.at(-1).init.method, "POST");
  assert.equal(requests.at(-1).init.headers["X-TinyPPI-Token"], "AB");

  const rest = [...$("transport").querySelectorAll(".tvol .tbtn")];
  assert.deepEqual(rest.map((node) => node.dataset.label),
                   ["chapter_previous", "playpause", "volume_down", "mute", "volume_up", "stop", "chapter_next"]);
  assert.deepEqual(rest.map((node) => node.getAttribute("aria-label")),
                   ["Previous chapter", "Play / pause", "Volume down", "Mute", "Volume up", "Stop", "Next chapter"]);
  assert.equal(rest[0].title, "Previous chapter");
  const down = rest[2];
  assert.equal(down.querySelector("img").getAttribute("src"), "/icons/volume.svg");
  assert.equal(down.querySelector(".sign").textContent, "−");
  assert.equal(rest[4].querySelector(".sign").textContent, "+");
  const before = commands().length;
  for (const key of rest) key.click();
  assert.deepEqual(commands().slice(before).map((command) => command.action),
                   ["chapter_previous", "playpause", "volume_down", "mute", "volume_up", "stop", "chapter_next"]);

  P.update(snap({ control: true, controls: { chapters: 12 } }));
  assert.equal($("transport").querySelectorAll(".tbtn").length, 13);
  assert.equal($("transport").querySelector(".tbtn"), jumps[0], "built once");
});

test("the play and mute keys follow the player, the chapter keys need chapters", (t) => {
  const { $, P } = panels(t);
  P.update(snap({ control: true, paused: false, controls: { chapters: 12, muted: false } }));
  const play = $("transport").querySelector(".tbtn.play");
  const mute = $("transport").querySelector(".mute");
  const chapters = [...$("transport").querySelectorAll(".tbtn.chapter")];
  assert.equal(play.dataset.icon, "pause");
  assert.equal(play.querySelector(".ui-icon").getAttribute("src"), "/icons/pause.svg");
  assert.equal(mute.classList.contains("on"), false);
  assert.ok(chapters.every((key) => !key.disabled));

  P.update(snap({ control: true, paused: true, controls: { chapters: 1, muted: true } }));
  assert.equal(play.dataset.icon, "play");
  assert.equal(play.querySelectorAll(".ui-icon").length, 1);
  assert.equal(play.querySelector(".ui-icon").getAttribute("src"), "/icons/play.svg");
  assert.ok(mute.classList.contains("on"));
  assert.equal(mute.querySelector(".ui-icon").getAttribute("src"), "/icons/volume-muted.svg");
  assert.ok(chapters.every((key) => key.disabled));

  P.update(snap({ control: true, controls: undefined }));
  assert.ok(chapters.every((key) => key.disabled));
  assert.equal(mute.dataset.icon, "volume");
});

test("the controls drawer opens on its toggle and is remembered", (t) => {
  const { $, P, window } = panels(t);
  const stored = () => window.localStorage.getItem("tinyppi.disclosure.dashboard.controls");
  P.update(snap({ control: true }));
  $("controlToggle").click();
  assert.ok($("controlDrawer").classList.contains("open"));
  assert.equal($("controlToggle").getAttribute("aria-expanded"), "true");
  assert.equal(stored(), "1");

  // Losing control folds it away without forgetting what was chosen.
  P.update(snap({ control: false }));
  assert.equal($("controlDrawer").classList.contains("open"), false);
  assert.ok($("controlToggle").classList.contains("hidden"));
  assert.ok($("transport").classList.contains("hidden"));
  assert.ok($("tracks").classList.contains("hidden"));
  assert.equal($("track").classList.contains("seekable"), false);
  assert.equal(stored(), "1");

  P.update(snap({ control: true }));
  assert.ok($("controlDrawer").classList.contains("open"), "restored when control returns");
  $("controlToggle").click();
  assert.equal($("controlDrawer").classList.contains("open"), false);
  assert.equal(stored(), "0");
});

test("a tap on the bar seeks there and the arrow keys step ten seconds", (t) => {
  const { $, P, commands, window } = panels(t);
  const track = $("track");
  const tap = (clientX) => {
    for (const type of ["pointerdown", "pointerup", "click"]) {
      track.dispatchEvent(new window.PointerEvent(type, { clientX, pointerId: 1, button: 0, bubbles: true }));
    }
  };
  const key = (name) => {
    const event = new window.KeyboardEvent("keydown", { key: name, cancelable: true });
    track.dispatchEvent(event);
    return event.defaultPrevented;
  };
  P.update(snap({ control: true }));
  let box = { left: 100, width: 200 };
  track.getBoundingClientRect = () => box;

  tap(150);
  assert.deepEqual(commands().at(-1), { action: "seek_percent", value: 25 });
  assert.equal($("bar").style.width, "25%");
  tap(400);
  assert.deepEqual(commands().at(-1), { action: "seek_percent", value: 100 });
  tap(20);
  assert.deepEqual(commands().at(-1), { action: "seek_percent", value: 0 });
  box = { left: 0, width: 0 };                   // not laid out
  tap(10);
  assert.equal(commands().length, 3);

  assert.equal(key("ArrowLeft"), true);
  assert.deepEqual(commands().at(-1), { action: "seek", value: -10 });
  assert.equal(key("ArrowRight"), true);
  assert.deepEqual(commands().at(-1), { action: "seek", value: 10 });
  assert.equal(key("Enter"), false);
  assert.equal(commands().length, 5);

  P.update(snap({ control: false }));
  box = { left: 100, width: 200 };
  tap(150);
  assert.equal(key("ArrowLeft"), false);
  assert.equal(commands().length, 5);
});

test("track pickers: audio when there is a choice, subtitles with an off switch", (t) => {
  const { $, P, commands, window } = panels(t);
  const audio = [{ index: 0, label: "English" }, { index: 1, label: "Deutsch" }];
  const subtitle = [{ index: 3, label: "English SDH" }];
  const options = (select) => [...select.options].map((option) => [option.value, option.text]);

  P.update(snap({ control: true, controls: { audio: audio.slice(0, 1), subtitle: [] } }));
  assert.ok($("tracks").classList.contains("hidden"));

  P.update(snap({ control: true, controls: { audio, audio_current: 1, subtitle,
                                             subtitle_on: false, subtitle_current: 3 } }));
  assert.equal($("tracks").classList.contains("hidden"), false);
  const audioPick = $("pick-audio");
  assert.deepEqual(options(audioPick), [["0", "English"], ["1", "Deutsch"]]);
  assert.equal(audioPick.value, "1");
  assert.equal(audioPick.previousElementSibling.textContent, "Audio track");
  assert.deepEqual(options($("pick-subtitle")), [["-1", "Off"], ["3", "English SDH"]]);
  assert.equal($("pick-subtitle").value, "-1");

  P.update(snap({ control: true, controls: { audio, audio_current: 0, subtitle,
                                             subtitle_on: true, subtitle_current: 3 } }));
  assert.equal($("pick-audio"), audioPick, "kept while the tracks are the same");
  assert.equal(audioPick.value, "0");
  assert.equal($("pick-subtitle").value, "3");

  audioPick.value = "1";
  audioPick.dispatchEvent(new window.Event("change"));
  $("pick-subtitle").value = "-1";
  $("pick-subtitle").dispatchEvent(new window.Event("change"));
  assert.deepEqual(commands(), [{ action: "audio", value: 1 }, { action: "subtitle", value: -1 }]);

  P.update(snap({ control: true, controls: { audio: audio.slice(0, 1), subtitle, subtitle_on: false } }));
  assert.equal($("pick-audio"), null);
  assert.equal($("pick-subtitle").value, "-1");
  P.update(snap({ control: true, controls: { audio, audio_current: 1 } }));
  assert.equal($("pick-subtitle"), null);
  assert.equal($("pick-audio").value, "1");

  // New words are carried into the pickers on the next snapshot.
  Object.assign(window.TinyPPI.T, { audio_track: "Tonspur", off: "Aus" });
  P.strings(window.TinyPPI.T);
  const kept = $("pick-audio");
  P.update(snap({ control: true, controls: { audio, audio_current: 1, subtitle } }));
  assert.notEqual($("pick-audio"), kept);
  assert.equal($("pick-audio").previousElementSibling.textContent, "Tonspur");
  assert.equal($("pick-subtitle").options[0].text, "Aus");
});

test("the four figures: switches, warnings, cache and the frames that made it out", (t) => {
  const { $, P } = panels(t);
  const unit = () => $("vPlayerCache").nextElementSibling.textContent;
  P.update(snap());
  assert.equal($("tiles").classList.contains("hidden"), false);
  assert.equal($("vSwitches").textContent, "1");
  assert.equal($("vWarnings").textContent, "2");
  assert.equal($("vPlayerCache").textContent, "88");
  assert.equal(unit(), "%");
  assert.equal($("vFps").textContent, "23.976");

  P.update(snap({ session: undefined, metrics: { cache: null, fps_in: 50, fps_drop: 0.06 } }));
  assert.equal($("vSwitches").textContent, "0");
  assert.equal($("vWarnings").textContent, "0");
  assert.equal($("vPlayerCache").textContent, "N/A");
  assert.equal(unit(), "", "no unit beside N/A");
  assert.equal($("vFps").textContent, "49.94");

  P.update(snap({ metrics: { fps_in: 24 } }));
  assert.equal($("vFps").textContent, "24");
  P.update(snap({ metrics: { fps_in: 1, fps_drop: 3 } }));
  assert.equal($("vFps").textContent, "0", "never below nothing");
  P.update(snap({ metrics: { fps_out: "garbled" } }));
  assert.equal($("vFps").textContent, "N/A");
  P.update(snap({ metrics: undefined }));
  assert.equal($("vFps").textContent, "N/A");
  assert.equal($("vPlayerCache").textContent, "N/A");
});

test("the frame rate tile points the way the rate last moved", (t) => {
  const { $, P } = panels(t);
  const arrow = () => [$("tFps").textContent, $("tFps").className];
  P.update(snap({ metrics: { fps_out: 24 } }));
  assert.deepEqual(arrow(), ["", "trend"]);
  P.update(snap({ metrics: { fps_out: 60 } }));
  assert.deepEqual(arrow(), ["▲", "trend up"]);
  P.update(snap({ metrics: { fps_out: 60 } }));
  assert.deepEqual(arrow(), ["▲", "trend up"], "kept until the rate moves again");
  P.update(snap({ metrics: { fps_out: 50 } }));
  assert.deepEqual(arrow(), ["▼", "trend down"]);
  P.update(snap({ metrics: {} }));
  assert.deepEqual(arrow(), ["", "trend"]);
  P.update(snap({ metrics: { fps_out: 24 } }));
  assert.deepEqual(arrow(), ["", "trend"], "the first reading after a gap is no change");
});

test("events come from the add-on's history, newest first", async (t) => {
  const { $, P, fetched } = panels(t, { token: "AB" });
  P.update(snap({ session: { seq: 3, switches: 1, warnings: 0 } }));
  assert.equal($("vSwitches").textContent, "1");
  assert.deepEqual(fetched("/api/history").map((request) => request.url), ["/api/history"]);
  await settle();

  assert.equal($("eventsCard").classList.contains("hidden"), false);
  assert.equal($("events").getAttribute("role"), "list");
  assert.equal($("events").className, "events");
  const rows = [...$("events").children];
  assert.deepEqual(rows.map((row) => row.className), ["event temperature", "event shift", "event shift"]);
  assert.deepEqual(rows.map((row) => row.dataset.kind), ["temperature", "audio", "fps"]);
  assert.ok(rows.every((row) => row.getAttribute("role") === "listitem"));
  assert.deepEqual(texts(rows[0].children), ["00:00:13", "Temperature", "77 °C"]);
  assert.deepEqual(texts(rows[1].children), ["00:00:12", "Audio track", "Deutsch"]);
  assert.deepEqual(texts(rows[2].children), ["00:00:10", "FPS", "60▲"]);
  const trend = rows[2].querySelector(".detail .trend");
  assert.equal(trend.className, "trend up");
  assert.equal(trend.getAttribute("aria-hidden"), "true");
  assert.equal(rows[1].querySelector(".trend"), null);
  assert.equal($("vSwitches").textContent, "4", "the history's own total");

  // The same count again: the fetched total stands and nothing is asked.
  P.update(snap({ session: { seq: 3, switches: 1, warnings: 0 } }));
  assert.equal($("vSwitches").textContent, "4");
  assert.equal(fetched("/api/history").length, 1);
});

test("a moved event count fetches again, but never twice within a second", async (t) => {
  const { $, P, clock, fetched } = panels(t);
  P.update(snap({ session: { seq: 3, switches: 1 } }));
  await settle();
  P.update(snap({ session: { seq: 4, switches: 5 } }));
  assert.equal($("vSwitches").textContent, "5", "a count the history has not caught up with");
  assert.equal(fetched("/api/history").length, 1);
  clock.now += 1500;
  P.update(snap({ session: { seq: 4, switches: 5 } }));
  assert.equal(fetched("/api/history").length, 2);
  // One in flight is not asked for again, however long it takes.
  clock.now += 1500;
  P.update(snap({ session: { seq: 5, switches: 5 } }));
  assert.equal(fetched("/api/history").length, 2);
  await settle();
});

test("a failed history leaves the events away and is tried again later", async (t) => {
  const { $, P, clock, fetched } = panels(t, { routes: { "/api/history": [500, {}] } });
  P.update(snap({ session: { seq: 1 } }));
  await settle();
  assert.ok($("eventsCard").classList.contains("hidden"));
  assert.deepEqual(plain(P.events()), []);
  assert.equal(P.peak(), null);
  P.update(snap({ session: { seq: 1 } }));
  assert.equal(fetched("/api/history").length, 1, "not within the second");
  clock.now += 1001;
  P.update(snap({ session: { seq: 1 } }));
  assert.equal(fetched("/api/history").length, 2);
  await settle();
});

test("an empty history says so", async (t) => {
  const { $, P } = panels(t, { routes: { "/api/history": [200, { seq: 1, events: [] }] } });
  P.update(snap({ session: { seq: 1, switches: 3 } }));
  await settle();
  assert.equal($("events").className, "events empty");
  assert.equal($("events").textContent, "No events yet");
  assert.equal($("vSwitches").textContent, "0");
  assert.equal($("eventsCard").classList.contains("hidden"), false);
  assert.deepEqual(plain(P.events()), []);
  assert.equal(P.peak(), null);
});

test("a falling frame rate is marked down, on the page and in the report", async (t) => {
  const history = { ...HISTORY, max: [900, null, 1000, 950],
                    events: [...HISTORY.events, { pos: "00:00:20", kind: "fps", from: 60, to: 24 },
                             { kind: "cpu", value: 99.5 }] };
  const { $, P } = panels(t, { routes: { "/api/history": [200, history] } });
  assert.deepEqual(plain(P.events()), []);
  assert.equal(P.peak(), null);
  P.update(snap({ session: { seq: 3 } }));
  await settle();
  const fall = $("events").children[1];
  assert.deepEqual(texts(fall.children), ["00:00:20", "FPS", "24▼"]);
  assert.equal(fall.querySelector(".trend").className, "trend down");
  assert.equal($("events").children[0].querySelector(".at").textContent, "", "no position, no time");
  assert.deepEqual(plain(P.events()), [
    { pos: "00:00:10", label: "FPS", text: "60 ▲" },
    { pos: "00:00:12", label: "Audio track", text: "Deutsch" },
    { pos: "00:00:13", label: "Temperature", text: "77 °C" },
    { pos: "00:00:20", label: "FPS", text: "24 ▼" },
    { pos: "", label: "Processor", text: "100%" }]);
  assert.equal(P.peak(), 1000, "the highest peak, gaps skipped");
});

test("the strings name every panel, range and key", async (t) => {
  const { $, P, window } = panels(t);
  delete window.TinyPPI.T.mute;
  P.update(snap({ control: true, session: { seq: 3 } }));
  await settle();
  const mute = $("transport").querySelector(".mute");
  assert.equal(mute.hasAttribute("aria-label"), false, "a key with no name is left unnamed");

  window.TinyPPI.T.stop = "Stopp";
  window.TinyPPI.T.temperature = "Temperatur";
  P.strings({
    ...window.TinyPPI.T,
    metrics: "Messwerte", controls: "Steuerung", switches: "Wechsel", warnings: "Warnungen",
    player_cache: "Puffer", fps: "BPS", chart: "Helligkeit", peak: "Spitze", average: "Mittel",
    events: "Ereignisse", range_1m: "1 Min.", range_10m: undefined, range_all: "Alles",
  });
  assert.equal($("tilesTitle").textContent, "Messwerte");
  assert.equal($("controlToggle").getAttribute("aria-label"), "Steuerung");
  assert.equal($("controlToggle").title, "Steuerung");
  assert.deepEqual([$("kSwitches"), $("kWarnings"), $("kPlayerCache"), $("kFps")].map((node) => node.textContent),
                   ["Wechsel", "Warnungen", "Puffer", "BPS"]);
  assert.equal($("chartTitle").textContent, "Helligkeit");
  assert.equal($("legendPeak").textContent, "Spitze");
  assert.equal($("legendAvg").textContent, "Mittel");
  assert.equal($("chartScale").textContent, "nits · log");
  assert.equal($("eventsTitle").textContent, "Ereignisse");
  assert.deepEqual(texts($("ranges").children), ["1 Min.", "range_10m", "Alles"]);
  // History drawn before the words arrived is drawn again with them.
  assert.equal($("events").firstElementChild.querySelector(".what").textContent, "Temperatur");
  const stop = $("transport").querySelector("[data-label=stop]");
  assert.equal(stop.getAttribute("aria-label"), "Stopp");
  assert.equal(stop.title, "Stopp");
});

test("the chart card shows with luminance to draw and its ranges switch", (t) => {
  const { $, P, window, fetched } = panels(t);
  delete window.TinyPPI.T.range_all;
  P.update(snap({ metrics: metrics({ l1: {} }) }));
  assert.ok($("chartCard").classList.contains("hidden"));
  assert.equal($("ranges").children.length, 0);

  P.update(snap());
  assert.equal($("chartCard").classList.contains("hidden"), false);
  const buttons = [...$("ranges").children];
  assert.deepEqual(texts(buttons), ["1 min", "10 min", "range_all"]);
  assert.deepEqual(buttons.map((button) => button.dataset.range), ["60", "600", "0"]);
  const on = () => buttons.map((button) => button.classList.contains("on"));
  assert.deepEqual(on(), [true, false, false]);

  buttons[1].click();
  assert.deepEqual(on(), [false, true, false]);
  assert.equal(fetched("/api/history").length, 1, "a longer range asks for the history");
  buttons[0].click();
  assert.deepEqual(on(), [true, false, false]);
  assert.equal(fetched("/api/history").length, 1, "the last minute is the page's own");

  P.update(snap({ metrics: metrics({ l1: undefined }) }));
  assert.ok($("chartCard").classList.contains("hidden"));
  P.update(snap());
  assert.equal($("ranges").children.length, 3, "built once");
});

test("the chart draws the decade grid, the peak area and both traces", (t) => {
  const { P, window, clock } = panels(t);
  const style = window.document.createElement("style");
  style.textContent = "#chart { --accent: #ff8800; --accent-2: #00ff88 }";
  window.document.head.append(style);
  window.devicePixelRatio = 2;
  const chart = fakeCanvas(window);

  P.update(snap({ metrics: metrics({ l1: { max: 1000, avg: 120 } }) }));
  assert.equal(chart.canvas.width, 600);
  assert.equal(chart.canvas.height, 300);
  assert.deepEqual(chart.last().transform, [2, 0, 0, 2, 0, 0]);
  assert.deepEqual(chart.last().clear, [0, 0, 300, 150]);
  const labels = chart.last().ops.filter((op) => op.op === "text");
  assert.deepEqual(labels.map((op) => op.text), ["0.1", "1", "10", "100", "1k", "10k"]);
  assert.ok(labels.every((op) => op.x === 28));
  close(labels[3].y, Math.round(yOf(100)) + 0.5);
  // One sample is no line: the grid only, in the theme's fallback colour.
  assert.equal(chart.strokes().length, 6);
  assert.ok(chart.strokes().every((op) => op.style === "#242c36" && op.width === 1));
  closePath(chart.strokes()[0].path, [["M", 34, Math.round(yOf(0.1)) + 0.5],
                                       ["L", 294, Math.round(yOf(0.1)) + 0.5]]);

  clock.now += 1000;
  P.update(snap({ metrics: metrics({ l1: { max: 500 } }) }));
  const ops = chart.last().ops;
  const fill = ops.find((op) => op.op === "fill");
  assert.equal(fill.alpha, 0.28);
  assert.deepEqual(fill.style.stops, [[0, "#ff8800"], [1, "transparent"]]);
  closePath(fill.path, [["M", xOf(1, 60), 144], ["L", xOf(1, 60), yOf(1000)],
                        ["L", 294, yOf(500)], ["L", 294, 144], ["Z"]]);
  const [peak, average] = chart.strokes().slice(6);
  assert.deepEqual([peak.style, peak.width, peak.dash], ["#ff8800", 1.7, []]);
  closePath(peak.path, [["M", xOf(1, 60), yOf(1000)], ["L", 294, yOf(500)]]);
  assert.deepEqual([average.style, average.width, average.dash], ["#00ff88", 1.5, [4, 3]]);
  // A sample without an average is drawn at its peak.
  closePath(average.path, [["M", xOf(1, 60), yOf(120)], ["L", 294, yOf(500)]]);
});

test("the canvas follows its box and draws nothing while it has no size", (t) => {
  const { P, window } = panels(t);
  window.devicePixelRatio = 0;                    // unknown: one to one
  const chart = fakeCanvas(window, { width: 0, height: 0 });
  P.update(snap());
  assert.equal(chart.frames.length, 0, "a tab that is not in front is not drawn");

  chart.box.width = 300;
  chart.box.height = 150;
  P.draw();
  assert.equal(chart.frames.length, 1);
  assert.deepEqual([chart.canvas.width, chart.canvas.height], [300, 150]);
  chart.box.height = 200;
  P.draw();
  assert.deepEqual([chart.canvas.width, chart.canvas.height], [300, 200]);
  P.draw();
  assert.equal(chart.frames.length, 3);
});

test("the last minute drops older samples and those without a peak", (t) => {
  const { P, window, clock } = panels(t);
  const chart = fakeCanvas(window);
  P.update(snap({ metrics: metrics({ l1: { max: 100, avg: 10 } }) }));
  clock.now += 30_000;
  P.update(snap({ metrics: metrics({ l1: undefined }) }));
  clock.now += 10_000;
  P.update(snap({ metrics: metrics({ l1: { max: 200, avg: 20 } }) }));
  clock.now += 30_000;
  P.update(snap({ metrics: metrics({ l1: { max: 400, avg: 40 } }) }));
  const [peak] = chart.strokes().slice(6);
  closePath(peak.path, [["M", xOf(30, 60), yOf(200)], ["L", 294, yOf(400)]]);
});

test("the longer ranges draw the add-on's history on the same axis", async (t) => {
  const history = { t: [0, 300, 600], max: [100, null, 1000], avg: [10, 20, null],
                    now: 600, seq: 1, events: [] };
  const { $, P, window, clock, fetched } = panels(t, { routes: { "/api/history": [200, history] } });
  const chart = fakeCanvas(window);
  P.update(snap());
  const [, tenMinutes, all] = $("ranges").children;

  all.click();
  await settle();
  // The whole title reaches back to its first sample.
  let [peak, average] = chart.strokes().slice(6);
  closePath(peak.path, [["M", 34, yOf(100)], ["L", 294, yOf(1000)]]);
  closePath(average.path, [["M", 34, yOf(10)], ["L", 294, yOf(1000)]]);

  // Time moves on between fetches; the history moves along the axis with it.
  clock.now += 30_000;
  P.draw();
  [peak] = chart.strokes().slice(6);
  closePath(peak.path, [["M", 34, yOf(100)], ["L", xOf(30, 630), yOf(1000)]]);

  tenMinutes.click();
  [peak] = chart.strokes().slice(6);
  closePath(peak.path, [["M", 34, yOf(100)], ["L", xOf(30, 600), yOf(1000)]]);
  assert.equal(fetched("/api/history").length, 2);
  await settle();
});

test("a long range is fetched again every five seconds while it is shown", async (t) => {
  const { $, P, clock, fetched } = panels(t);
  P.update(snap());
  $("ranges").children[2].click();
  await settle();
  assert.equal(fetched("/api/history").length, 1);
  clock.now += 2000;
  P.update(snap());
  assert.equal(fetched("/api/history").length, 1, "still fresh");
  clock.now += 4000;
  P.update(snap());
  assert.equal(fetched("/api/history").length, 2);
  await settle();
});

test("a history without samples or without peaks draws the grid only", async (t) => {
  const routes = { "/api/history": [200, { seq: 1, events: [] }] };
  const { $, P, window, clock } = panels(t, { routes });
  const chart = fakeCanvas(window);
  P.update(snap());
  $("ranges").children[2].click();
  await settle();
  assert.equal(chart.strokes().length, 6);

  routes["/api/history"] = [200, { t: [0, 1], now: 1, seq: 2, events: [] }];
  clock.now += 6000;
  P.update(snap());
  await settle();
  assert.equal(chart.strokes().length, 6);
  assert.equal(chart.last().ops.some((op) => op.op === "fill"), false);
});

test("the chart is drawn again on a new tint, a resize and when its tab asks", (t) => {
  const { P, window } = panels(t);
  const chart = fakeCanvas(window);
  const timers = heldTimers(window);
  P.update(snap());
  const drawn = chart.frames.length;

  window.document.dispatchEvent(new window.CustomEvent("tinyppi-tint"));
  assert.equal(chart.frames.length, drawn + 1);

  window.dispatchEvent(new window.Event("resize"));
  window.dispatchEvent(new window.Event("resize"));
  assert.deepEqual(timers.delays(), [120], "one redraw for a burst of resizes");
  timers.run();
  assert.equal(chart.frames.length, drawn + 2);

  P.draw();
  assert.equal(chart.frames.length, drawn + 3);
});

test("the event list is shaded while there is more of it below", (t) => {
  const { $, P, window } = panels(t);
  const list = $("events");
  const more = () => $("eventsWrap").classList.contains("more");
  const sizes = { scrollHeight: 500, clientHeight: 100, scrollTop: 0 };
  for (const name of Object.keys(sizes)) {
    Object.defineProperty(list, name, { configurable: true, get: () => sizes[name] });
  }
  list.dispatchEvent(new window.Event("scroll"));
  assert.equal(more(), true);
  sizes.scrollTop = 398;
  list.dispatchEvent(new window.Event("scroll"));
  assert.equal(more(), false, "within two pixels of the end");
  sizes.scrollTop = 0;
  window.dispatchEvent(new window.Event("resize"));
  assert.equal(more(), true);
  sizes.scrollHeight = 100;
  $("eventsCard").dispatchEvent(new window.Event("toggle"));
  assert.equal(more(), false);
  sizes.scrollHeight = 300;
  P.draw();
  assert.equal(more(), true);
});

test("when playback ends the panels are put away once and the ended title's events stay", async (t) => {
  const { $, P, window, clock, fetched } = panels(t);
  const shown = [];
  window.TinyPPICover = { show: (card, url) => shown.push(url) };
  const playing = snap({ control: true, finish: "23:40", art: { poster: "p1" },
                         controls: { audio: [{ index: 0, label: "A" }, { index: 1, label: "B" }] },
                         metrics: metrics({ fps_out: 24 }) });
  P.update(playing);
  P.update(snap({ ...playing, metrics: metrics({ fps_out: 60 }) }));
  $("controlToggle").click();
  const picker = $("pick-audio");

  P.update({ playing: false, last: { events: 3 } });
  for (const id of ["nowCard", "plotCard", "tiles", "chartCard"]) {
    assert.ok($(id).classList.contains("hidden"), id);
  }
  assert.ok($("tFinish").classList.contains("hidden"));
  assert.deepEqual([$("tFps").textContent, $("tFps").className], ["", "trend"]);
  assert.equal($("controlDrawer").classList.contains("open"), false);
  assert.equal(window.localStorage.getItem("tinyppi.disclosure.dashboard.controls"), "1");
  assert.equal(fetched("/api/history").length, 1, "the ended title's events are asked for");
  await settle();
  assert.equal($("eventsCard").classList.contains("hidden"), false);
  assert.equal($("events").children.length, 3);

  // Put away once: a card shown since is left alone, and nothing is asked again.
  $("tiles").classList.remove("hidden");
  clock.now += 2000;
  P.update({ playing: false, last: { events: 3 } });
  assert.equal($("tiles").classList.contains("hidden"), false);
  assert.equal(fetched("/api/history").length, 1);

  // Once the add-on lets the ended title go, so does the page.
  P.update({ playing: false });
  assert.ok($("eventsCard").classList.contains("hidden"));
  assert.deepEqual(plain(P.events()), []);
  assert.equal(P.peak(), null);
  P.update({ playing: false, last: { events: 3 } });
  assert.equal(fetched("/api/history").length, 2);
  await settle();

  // The next title starts clean: the same poster is set again, the pickers
  // are built again.
  P.update(playing);
  assert.equal($("nowCard").classList.contains("hidden"), false);
  assert.deepEqual(shown, ["/api/art?kind=poster&v=p1", "/api/art?kind=poster&v=p1"]);
  assert.notEqual($("pick-audio"), picker);
  assert.deepEqual([$("tFps").textContent, $("tFps").className], ["", "trend"]);

  P.update(null);
  assert.ok($("nowCard").classList.contains("hidden"));
});
