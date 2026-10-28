// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The sorting and the filters over the film and series walls
// (resources/web/js/shelf-tools.js), the next-up row (continue.js) and a
// title's details (marking.js), on the whole page loaded in index.html's
// order.

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
                  sort_year: "Jahr", genre: "Genre" };

const FILMS = [
  { id: 1, title: "Alien", year: 1979, duration: 7020, rating: 8.5, added: "2026-09-01 10:00:00",
    genres: ["Horror", "Sci-Fi"], video: "sdr", resolution: "1080p", audio: "dts" },
  { id: 2, title: "Brazil", year: 1985, duration: 8520, rating: 7.9,
    genres: ["Comedy"], video: "dv", dv_profile: "8.1", resolution: "2160p", audio: "truehd" },
  { id: 3, title: "Cube", duration: 5400, added: "2026-09-03 10:00:00",
    genres: ["Sci-Fi"], video: "hdr10", resolution: "2160p", audio: "truehd" },
  { id: 4, title: "Dune", year: 2021, rating: 6, added: "2026-09-02 10:00:00",
    video: "dv", dv_profile: "7 FEL" },
  { id: 5, title: "Eraserhead" },
];

const SHOWS = [
  { id: 7, title: "Andor", year: 2022, rating: 8.4, genres: ["Sci-Fi"], added: "2026-01-01" },
  { id: 8, title: "Bluey", year: 2018, genres: ["Animation", "Family"] },
  { id: 9, title: "Columbo", year: 1971, rating: 8.2, genres: ["Crime"] },
];

const NEXT = [
  { kind: "episode", id: 71, title: "Rix Road", tvshowid: 7, show: "Andor", poster: "ap",
    thumb: "at", season: 1, episode: 12, duration: 3000, rating: 8.4, rating_from: "imdb" },
];

const DETAILS = {
  kind: "movie", id: 1, title: "Alien", year: 1979, duration: 7020, mpaa: "Rated R",
  video: "dv", dv_profile: "5", resolution: "1080p", audio: "wma", tagline: "In space no one can hear you scream.",
  plot: "One\nTwo", genres: ["Horror", "Sci-Fi"], directors: ["Ridley Scott"], writers: [],
  studios: ["20th Century Fox"], countries: ["United Kingdom", "USA"], userrating: 9, top250: 51, cast_more: true,
  cast: [{ name: "Sigourney Weaver", role: "Ripley" }, { name: "Jones", role: "" }],
  ratings: [{ source: "imdb", rating: 8.5, votes: 1 }, { source: "kinopoisk", rating: 8, votes: 0 }],
  age: "mpa_r", age_level: "R", poster: "p1", fanart: "f1",
};

const IDLE = { playing: false, control: true };

async function open(t, { routes = {}, token = "", stored = {}, storage = true } = {}) {
  const table = {
    "/api/hello": [200, { version: "2.20.0", strings: STRINGS }],
    "/api/library": [200, { tag: "f1", movies: FILMS }],
    "/api/series": [200, { tag: "s1", shows: SHOWS }],
    "/api/continue": [200, { tag: "c1", items: [], next: NEXT }],
    "/api/details": [200, DETAILS],
    "/api/play": [200, {}],
    ...routes,
  };
  const view = page({ scripts: [], routes: table, token });
  const { window, dom } = view;
  t.after(() => window.close());
  fakeClock(window);
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  for (const [key, value] of Object.entries(stored)) window.localStorage.setItem(key, value);
  if (!storage) {
    Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
  }
  for (const name of ORDER) load(dom, name);
  await settle();
  view.streams.at(-1).emit("state", { ...IDLE, seq: 2 });
  await settle();
  return { ...view, routes: table, $: (id) => window.document.getElementById(id) };
}

const pick = (view, box, name) =>
  view.$(box).querySelector(`select[data-name="${name}"]`);
const options = (select) => [...select.options].map((option) => [option.value, option.text]);
const choose = (view, box, name, value) => {
  const select = pick(view, box, name);
  select.value = value;
  select.dispatchEvent(new view.window.Event("change"));
};
const order = (view, id) => [...view.$(id).children]
  .map((node) => node.querySelector(".filmtitle").textContent);
const shown = (view, id) => [...view.$(id).children].filter((node) => !node.hidden)
  .map((node) => node.querySelector(".filmtitle").textContent);

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

test("the film wall offers every order, and each puts titles without the value last", async (t) => {
  const view = await open(t);
  const sort = pick(view, "filmTools", "sort");
  assert.deepEqual(options(sort), [["title", "Title"], ["year", "Jahr"], ["rating", "Rating"],
                                   ["added", "Date added"], ["runtime", "Runtime"]]);
  assert.equal(sort.getAttribute("aria-label"), "Sort by");
  assert.deepEqual(order(view, "filmGrid"), ["Alien", "Brazil", "Cube", "Dune", "Eraserhead"]);
  const cases = { year: ["Dune", "Brazil", "Alien", "Cube", "Eraserhead"],
                  rating: ["Alien", "Brazil", "Dune", "Cube", "Eraserhead"],
                  added: ["Cube", "Dune", "Alien", "Brazil", "Eraserhead"],
                  runtime: ["Cube", "Alien", "Brazil", "Dune", "Eraserhead"],
                  title: ["Alien", "Brazil", "Cube", "Dune", "Eraserhead"] };
  const posters = [...view.$("filmGrid").children];
  for (const [key, expected] of Object.entries(cases)) {
    choose(view, "filmTools", "sort", key);
    assert.deepEqual(order(view, "filmGrid"), expected, key);
  }
  assert.ok([...view.$("filmGrid").children].every((node) => posters.includes(node)),
            "the tiles are moved, not made again");
});

test("each order runs either way, a press turning it, and is kept", async (t) => {
  const view = await open(t);
  const way = view.$("filmTools").querySelector(".shelfway");
  const kept = () => view.window.localStorage.getItem("tinyppi.order.films");
  assert.equal(way.textContent, "\u2191 Ascending");
  assert.equal(way.getAttribute("aria-label"), "Ascending");
  // A new order starts its own way round: the newest first.
  choose(view, "filmTools", "sort", "year");
  assert.equal(way.textContent, "\u2193 Descending");
  assert.ok(way.classList.contains("down"));
  assert.equal(kept(), "year:down");
  way.click();
  assert.deepEqual(order(view, "filmGrid"), ["Alien", "Brazil", "Dune", "Cube", "Eraserhead"]);
  assert.equal(kept(), "year");
  // The titles the other way round.
  choose(view, "filmTools", "sort", "title");
  way.click();
  assert.deepEqual(order(view, "filmGrid"), ["Eraserhead", "Dune", "Cube", "Brazil", "Alien"]);
  assert.equal(kept(), "title:down");
});

test("a kept order is the wall's on the next visit, and one it does not offer is not", async (t) => {
  const view = await open(t, { stored: { "tinyppi.order.films": "rating:down",
                                          "tinyppi.order.series": "runtime" } });
  assert.equal(pick(view, "filmTools", "sort").value, "rating");
  assert.deepEqual(order(view, "filmGrid"), ["Alien", "Brazil", "Dune", "Cube", "Eraserhead"]);
  assert.equal(pick(view, "seriesTools", "sort").value, "title");
});

test("a browser that keeps nothing still sorts both ways", async (t) => {
  const view = await open(t, { storage: false });
  choose(view, "filmTools", "sort", "runtime");
  view.$("filmTools").querySelector(".shelfway").click();
  assert.deepEqual(order(view, "filmGrid"), ["Brazil", "Alien", "Cube", "Dune", "Eraserhead"]);
});

test("the filters offer what the wall holds, in their order, and narrow it with the search", async (t) => {
  const view = await open(t);
  assert.deepEqual(options(pick(view, "filmTools", "genre")),
                   [["", "All genres"], ["Comedy", "Comedy"], ["Horror", "Horror"], ["Sci-Fi", "Sci-Fi"]]);
  assert.deepEqual(options(pick(view, "filmTools", "video")),
                   [["", "All picture formats"], ["dv", "Dolby Vision"],
                    ["dv/7 FEL", "Dolby Vision P7 FEL"], ["dv/8.1", "Dolby Vision P8.1"],
                    ["hdr10", "HDR10"], ["sdr", "SDR"]]);
  assert.deepEqual(options(pick(view, "filmTools", "resolution")),
                   [["", "All resolutions"], ["2160p", "4K"], ["1080p", "1080p"]]);
  assert.deepEqual(options(pick(view, "filmTools", "audio")),
                   [["", "All audio formats"], ["truehd", "Dolby TrueHD"], ["dts", "DTS"]]);
  assert.equal(pick(view, "filmTools", "genre").getAttribute("aria-label"), "Genre");

  // A profile narrows to its films; the grade takes in every profile of it.
  choose(view, "filmTools", "video", "dv/7 FEL");
  assert.deepEqual(shown(view, "filmGrid"), ["Dune"]);
  choose(view, "filmTools", "video", "dv");
  assert.deepEqual(shown(view, "filmGrid"), ["Brazil", "Dune"]);
  choose(view, "filmTools", "video", "");

  choose(view, "filmTools", "genre", "Sci-Fi");
  assert.deepEqual(shown(view, "filmGrid"), ["Alien", "Cube"]);
  assert.equal(view.$("filmsCount").textContent, "2 / 5");
  choose(view, "filmTools", "resolution", "2160p");
  assert.deepEqual(shown(view, "filmGrid"), ["Cube"]);
  view.$("filmSearch").value = "alien";
  view.$("filmSearch").dispatchEvent(new view.window.Event("input"));
  assert.deepEqual(shown(view, "filmGrid"), []);
  assert.equal(view.$("filmsEmpty").textContent, "No titles match the filter");
  assert.equal(view.$("filmsEmpty").classList.contains("hidden"), false);
  // Without a filter, the line is the empty library's again.
  choose(view, "filmTools", "genre", "");
  choose(view, "filmTools", "resolution", "");
  assert.deepEqual(shown(view, "filmGrid"), ["Alien"]);
  view.$("filmSearch").value = "zzz";
  view.$("filmSearch").dispatchEvent(new view.window.Event("input"));
  assert.equal(view.$("filmsEmpty").textContent, "No films in the video library");
});

test("a filter with nothing to choose between is not drawn, and a choice the list lost is let go", async (t) => {
  const view = await open(t);
  choose(view, "filmTools", "video", "dv");
  choose(view, "filmTools", "audio", "truehd");
  view.routes["/api/library"] = [200, { tag: "f2", movies: [
    { ...FILMS[0] }, { ...FILMS[2], video: "sdr" }] }];
  view.streams.at(-1).emit("state", { ...IDLE, seq: 3, library: 1 });
  view.streams.at(-1).emit("state", { ...IDLE, seq: 4, library: 2 });
  await settle();
  assert.equal(order(view, "filmGrid").length, 2);
  assert.ok(pick(view, "filmTools", "video").hidden, "only SDR is left");
  assert.equal(pick(view, "filmTools", "video").value, "");
  assert.equal(pick(view, "filmTools", "audio").value, "truehd", "still offered, still chosen");
  assert.deepEqual(shown(view, "filmGrid"), ["Cube"]);
});

test("profiles of one number are told apart by their layer", async (t) => {
  const view = await open(t, { routes: { "/api/library": [200, { tag: "f9", movies: [
    { id: 1, title: "One", video: "dv", dv_profile: "7 MEL" },
    { id: 2, title: "Two", video: "dv", dv_profile: "7 FEL" },
    { id: 3, title: "Three", video: "dv", dv_profile: "5" }] }] } });
  assert.deepEqual(options(pick(view, "filmTools", "video")).map(([value]) => value),
                   ["", "dv", "dv/5", "dv/7 FEL", "dv/7 MEL"]);
});

test("the series wall sorts and filters by genre the same way", async (t) => {
  const view = await open(t);
  assert.deepEqual(options(pick(view, "seriesTools", "sort")).map(([key]) => key),
                   ["title", "year", "rating", "added"]);
  assert.equal(pick(view, "seriesTools", "video"), null);
  choose(view, "seriesTools", "sort", "rating");
  assert.deepEqual(order(view, "seriesGrid"), ["Andor", "Columbo", "Bluey"]);
  choose(view, "seriesTools", "genre", "Family");
  assert.deepEqual(shown(view, "seriesGrid"), ["Bluey"]);
  view.$("seriesSearch").value = "andor";
  view.$("seriesSearch").dispatchEvent(new view.window.Event("input"));
  assert.equal(view.$("seriesEmpty").textContent, "No titles match the filter");
  choose(view, "seriesTools", "genre", "");
  assert.equal(view.$("seriesEmpty").textContent, "No series in the video library");
});

test("the next-up row holds each show's next episode and starts it from the top", async (t) => {
  const view = await open(t, { token: "T0K3N" });
  assert.equal(view.$("nextSeriesCard").classList.contains("hidden"), false);
  assert.ok(view.$("continueSeriesCard").classList.contains("hidden"));
  assert.equal(view.$("nextSeriesLabel").textContent, "Next up");
  assert.equal(view.$("nextSeriesCount").textContent, "1");
  const [tile] = view.$("nextSeriesRow").children;
  assert.equal(tile.querySelector(".filmtitle").textContent, "Andor");
  assert.equal(tile.querySelector(".filmresume"), null);
  assert.equal(tile.querySelector("img").getAttribute("src"), "/api/art?kind=poster&episodeid=71&v=ap");
  tile.dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  assert.equal(view.$("detailsPlay").textContent, "Play");
  assert.ok(view.$("detailsRestart").hidden && view.$("detailsClear").hidden);
  answer(view, "play");
  await settle();
  const sent = view.requests.filter((request) => request.url === "/api/play");
  assert.deepEqual(JSON.parse(sent[0].init.body), { episodeid: 71 });
  assert.ok(tile.disabled, "the row waits on the press");
});

test("an add-on without the next-up row leaves no card for it", async (t) => {
  const view = await open(t, { routes: { "/api/continue": [200, { tag: "c1", items: [] }] } });
  assert.ok(view.$("nextSeriesCard").classList.contains("hidden"));
  assert.equal(view.$("nextSeriesCount").textContent, "");
});

test("details stand under the title's backdrop with its poster, shields, plot, facts and cast", async (t) => {
  const view = await open(t);
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "details");
  await settle();
  const asked = view.requests.filter((request) => request.url.startsWith("/api/details"));
  assert.deepEqual(asked.map((request) => request.url), ["/api/details?movieid=1"]);
  assert.ok(view.$("detailsDialog").open);
  assert.equal(view.$("detailsBackdrop").getAttribute("src"), "/api/art?kind=fanart&movieid=1&v=f1");
  assert.equal(view.$("detailsPoster").getAttribute("src"), "/api/art?kind=poster&movieid=1&v=p1");
  assert.equal(view.$("detailsHero").classList.contains("bare"), false);
  assert.equal(view.$("detailsTitle").textContent, "Alien");
  assert.equal(view.$("detailsMeta").textContent, "1979 · 1 h 57 min");
  assert.deepEqual([...view.$("detailsFormats").children].map((node) => node.textContent),
                   ["Dolby Vision P5", "1080p", "wma"]);
  // The ratings as the overview card's shields, the age rating first.
  assert.deepEqual([...view.$("detailsRatings").querySelectorAll(".said")].map((node) => node.textContent),
                   ["Rated R", "IMDb 8.5", "Kinopoisk 8.0", "My rating 9", "Top 250 · #51"]);
  assert.equal(view.$("detailsTagline").textContent, "In space no one can hear you scream.");
  assert.equal(view.$("detailsPlot").textContent, "One\nTwo");
  // The facts and the cast as the overview card draws them.
  const facts = [...view.$("detailsFacts").children].map((node) =>
    [...node.children].map((part) => part.textContent));
  assert.deepEqual(facts, [["Genre", "Horror, Sci-Fi"],
                           ["Studio", "20th Century Fox"],
                           ["Production country", "United Kingdom, USA"]]);
  // More in the library than the row shows: the count says so.
  assert.deepEqual(cast(view), ["Cast (2+)", "Sigourney WeaverRipley", "Jones", "…", "Ridley ScottDirector"]);
  assert.equal(view.$("detailsClose"), null);
  assert.equal(view.$("detailsX").getAttribute("aria-label"), "Close");
  // A backdrop the box cannot read leaves the heading on the plain panel.
  view.$("detailsBackdrop").onerror();
  assert.ok(view.$("detailsBackdrop").hidden && view.$("detailsHero").classList.contains("bare"));
});

/* The details' cast as it reads: its heading, then each card. */
const cast = (view) => {
  const block = view.$("detailsCast");
  return [block.querySelector(".casthead").textContent,
          ...[...block.querySelectorAll("li")].map((card) => card.textContent)];
};

function closeDetails(view, value) { answer(view, value); }

test("the details play, resume or start over, as the question does", async (t) => {
  const films = [{ id: 1, title: "Alien", duration: 7020, resume: 600 }, { id: 2, title: "Brazil" }];
  const view = await open(t, { routes: { "/api/library": [200, { tag: "f2", movies: films }] } });
  const played = () => view.requests.filter((request) => request.url === "/api/play")
    .map((request) => JSON.parse(request.init.body));
  const details = async (index) => {
    [...view.$("filmGrid").children][index].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    await settle();
    answer(view, "details");
    await settle();
  };
  // A film not begun: play alone; closing plays nothing.
  await details(1);
  assert.equal(view.$("detailsPlay").textContent, "Play");
  assert.ok(view.$("detailsRestart").hidden);
  closeDetails(view, "close");
  await settle();
  assert.deepEqual(played(), []);
  // A film with a point to resume from: resume, or start over.
  await details(0);
  assert.equal(view.$("detailsPlay").textContent, "Resume");
  assert.equal(view.$("detailsRestart").hidden, false);
  closeDetails(view, "restart");
  await settle();
  assert.deepEqual(played(), [{ movieid: 1, resume: false }]);
});

test("the details' play is the question's", async (t) => {
  const view = await open(t);
  [...view.$("filmGrid").children][1].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "details");
  await settle();
  closeDetails(view, "play");
  await settle();
  const sent = view.requests.filter((request) => request.url === "/api/play");
  assert.deepEqual(sent.map((request) => JSON.parse(request.init.body)), [{ movieid: 2 }]);
});

test("an episode stands under its still, and one without pictures under none", async (t) => {
  const view = await open(t, { routes: { "/api/details": [200, {
    kind: "episode", id: 71, title: "Rix Road", thumb: "t71",
    cast: [{ name: "Diego Luna", role: "Cassian" }] }] } });
  [...view.$("nextSeriesRow").children][0].click();
  answer(view, "details");
  await settle();
  assert.equal(view.$("detailsBackdrop").getAttribute("src"), "/api/art?kind=thumb&episodeid=71&v=t71");
  assert.ok(view.$("detailsPoster").hidden);
  assert.deepEqual(cast(view), ["Cast (1)", "Diego LunaCassian"]);
});

test("a title with little to say leaves its rows out, and a failed read says so", async (t) => {
  const view = await open(t, { routes: { "/api/details": [200, { kind: "tvshow", id: 7, title: "Andor" }] } });
  [...view.$("seriesGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "details");
  await settle();
  assert.ok(view.requests.some((request) => request.url === "/api/details?tvshowid=7"));
  assert.equal(view.$("detailsMeta").textContent, "");
  assert.equal(view.$("detailsPlot").textContent, "");
  assert.equal(view.$("detailsFacts").children.length, 0);
  assert.equal(view.$("detailsCast").children.length, 0);
  assert.ok(view.$("detailsBackdrop").hidden && view.$("detailsHero").classList.contains("bare"));
  assert.equal(view.$("detailsBackdrop").getAttribute("src"), null);
  view.$("detailsDialog").close();
  view.$("detailsDialog").dispatchEvent(new view.window.Event("close"));

  view.routes["/api/details"] = [404, { error: "no such title" }];
  [...view.$("filmGrid").children][1].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "details");
  await settle();
  assert.equal(view.$("detailsDialog").open, true);
  assert.equal(view.$("detailsActions").hidden, false);
  assert.equal(view.$("toast").textContent, "The details could not be read.");
});

test("on the adaptive theme the details wear their own title's colour, not what is playing", async (t) => {
  const view = await open(t);
  const dialog = view.$("detailsDialog");
  const asked = [];
  let answer = [200, 40, 40];
  view.window.TinyPPICover.accent = (url, image) => {
    asked.push([url, image.id]);
    return Promise.resolve(answer);
  };
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  const show = async () => {
    await settle();
  };
  await show();
  // The film's poster is read, and the page wears what it gave.
  assert.deepEqual(asked, [["/api/art?kind=poster&movieid=1&v=p1", "detailsPoster"]]);
  assert.ok(dialog.classList.contains("tinted"));
  assert.equal(dialog.style.getPropertyValue("--cover-accent-rgb"), "200, 40, 40");
  dialog.close();
  dialog.dispatchEvent(new view.window.Event("close"));
  // A picture with no colour: the theme's own, and nothing left of the last.
  answer = null;
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  await show();
  assert.equal(dialog.classList.contains("tinted"), false);
  assert.equal(dialog.style.getPropertyValue("--cover-accent-rgb"), "");
  dialog.close();
  dialog.dispatchEvent(new view.window.Event("close"));
  // One whose picture moved on before the answer came is not painted.
  answer = [1, 2, 3];
  view.window.TinyPPICover.accent = (url, image) => {
    image.setAttribute("src", "/elsewhere");
    return Promise.resolve(answer);
  };
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  await show();
  assert.equal(dialog.classList.contains("tinted"), false);
  dialog.close();
  dialog.dispatchEvent(new view.window.Event("close"));
  // A title with no picture at all asks nothing, and nor does a page
  // without the tint.
  asked.length = 0;
  view.window.TinyPPICover.accent = () => { asked.push(1); return Promise.resolve(answer); };
  view.routes["/api/details"] = [200, { kind: "tvshow", id: 7, title: "Andor" }];
  [...view.$("seriesGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  await show();
  dialog.close();
  dialog.dispatchEvent(new view.window.Event("close"));
  delete view.window.TinyPPICover;
  view.routes["/api/details"] = [200, { kind: "movie", id: 1, title: "Alien", poster: "p1" }];
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  await show();
  assert.deepEqual(asked, []);
  assert.equal(dialog.classList.contains("tinted"), false);
});


test("the overview opens the playing title's details, with nothing to play on them", async (t) => {
  const view = await open(t);
  view.window.TinyPPI.openDetails({ kind: "movie", id: 1, title: "Alien" });
  await settle();
  assert.ok(view.requests.some((request) => request.url === "/api/details?movieid=1"));
  assert.ok(view.$("detailsDialog").open);
  assert.equal(view.$("detailsTitle").textContent, "Alien");
  assert.ok(view.$("detailsPlay").parentElement.hidden);
  assert.equal(view.$("detailsPlay").textContent, "");
  closeDetails(view, "close");
  // Opened from a shelf again, the keys are back.
  [...view.$("filmGrid").children][0].dispatchEvent(new view.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  await settle();
  answer(view, "details");
  await settle();
  assert.equal(view.$("detailsPlay").parentElement.hidden, false);
});


test("Atmos and DTS:X are named and filter the film shelf", async (t) => {
  const view = await open(t, { routes: { "/api/library": [200, { tag: "immersive", movies: [
    { id: 1, title: "Atmos film", audio: "atmos" },
    { id: 2, title: "DTS film", audio: "dtsx" }
  ] }] } });
  assert.deepEqual(options(pick(view, "filmTools", "audio")).map(([value]) => value), ["", "atmos", "dtsx"]);
  assert.match(pick(view, "filmTools", "audio").textContent, /Dolby Atmos/);
  assert.match(pick(view, "filmTools", "audio").textContent, /DTS:X/);
  choose(view, "filmTools", "audio", "atmos");
  assert.deepEqual(shown(view, "filmGrid"), ["Atmos film"]);
  choose(view, "filmTools", "audio", "dtsx");
  assert.deepEqual(shown(view, "filmGrid"), ["DTS film"]);
});


test("scrolling details dismisses the rating popovers", async (t) => {
  const view = await open(t);
  [...view.$("filmGrid").children][0].click();
  await settle();
  const tips = [...view.$("detailsRatings").querySelectorAll(".rating-tip")];
  assert.ok(tips.length);
  let closed = 0;
  for (const tip of tips) tip.hidePopover = () => { closed++; };
  view.$("detailsDialog").querySelector("form").dispatchEvent(new view.window.Event("scroll"));
  assert.equal(closed, tips.length);
});
