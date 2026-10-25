// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The dashboard in Chromium against the real server (tests/browser/serve.py,
// Kodi faked): every tab, the format badges, search, the question a press
// asks and what it sends, a show with its seasons, the history and the
// report.  Fails on any script error the page raises.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const TOKEN = "BROWSER1";

let server, browser, context, page, base;
const problems = [];
const posts = [];
const addresses = [];

before(async () => {
  server = spawn(process.env.PYTHON || "python3", ["-I", join(HERE, "serve.py")],
                 { stdio: ["ignore", "pipe", "inherit"] });
  const port = await new Promise((resolve, reject) => {
    server.on("exit", (code) => reject(new Error("server exited with " + code)));
    server.stdout.on("data", (chunk) => {
      const found = /PORT (\d+)/.exec(String(chunk));
      if (found) resolve(found[1]);
    });
  });
  base = `http://127.0.0.1:${port}/`;
  browser = await chromium.launch();
  context = await browser.newContext({ viewport: { width: 1280, height: 900 },
                                             reducedMotion: "reduce" });
  await context.addInitScript((token) => localStorage.setItem("tinyppi.token", token), TOKEN);
  page = await context.newPage();
  page.on("pageerror", (error) => problems.push("page error: " + error.message));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push("console: " + message.text());
  });
  page.on("request", (request) => {
    addresses.push(request.url());
    // The session the token buys on connect is no write.
    if (request.method() === "POST" && !request.url().endsWith("/api/session")) {
      posts.push([new URL(request.url()).pathname, JSON.parse(request.postData() || "{}")]);
    }
  });
  await page.goto(base + "#live");
});

after(async () => {
  await browser?.close();
  server?.kill();
});

const tab = (name) => page.click(`.tab[data-tab="${name}"]`);
const texts = (selector) => page.locator(selector).allInnerTexts();

test("the live tab connects and shows the format badges", async () => {
  await page.waitForSelector('#status[data-state="live"]');
  await page.waitForFunction(() => document.querySelectorAll(".format").length >= 5);
  const badges = await texts(".format");
  for (const badge of ["UHD", "DV P7.6 FEL", "TrueHD Atmos", "Atmos", "7.1"]) {
    assert.ok(badges.includes(badge), `${badge} in ${badges}`);
  }
  // The studio under the year and the genre, as one block with them: closer
  // to them than the column's lines are to each other.
  assert.equal(await page.locator("#studio").innerText(), "A Studio");
  const [title, meta, studio] = await Promise.all(
    ["#title", "#meta", "#studio"].map((selector) => page.locator(selector).boundingBox()));
  const gap = studio.y - (meta.y + meta.height);
  assert.ok(gap >= 0 && gap < meta.y - (title.y + title.height), `${gap} under the genre`);
  // Who directed it is the overview's, not this card's.
  assert.equal(await page.locator("#director").count(), 0);
});

test("the ratings, the slogan and the plot stand in a card of their own under the playing one", async () => {
  await page.waitForSelector("#plotCard:not(.hidden)");
  // As a title's details page: the ratings over the whole plot, the facts
  // and the cast, nothing folded away.
  for (const id of ["ratings", "plotText", "credits", "castBlock"]) {
    assert.equal(await page.locator("#" + id).isVisible(), true, id);
  }
  const [ratings, plotBox] = await Promise.all(
    ["#ratings", "#plotText"].map((selector) => page.locator(selector).boundingBox()));
  assert.ok(ratings.y + ratings.height <= plotBox.y, "the ratings first");
  // The cast cards all one height.
  const cards = await page.$$eval("#castBlock li:not(.more)",
    (nodes) => nodes.map((node) => node.getBoundingClientRect().height));
  assert.ok(cards.length && cards.every((height) => height === cards[0]));
  // The stubs' strings are only their ids, so the words of a badge are the
  // jsdom tests'; here it is which marks stand there, served and drawn.
  await page.waitForFunction(() => [...document.querySelectorAll("#ratings img")]
    .every((image) => image.complete && image.naturalWidth > 0));
  // Each as wide as it is drawn: the FSK's plate, IMDb's square logo and
  // the awards' square drawings.
  const sizes = await page.$$eval("#ratings img", (images) => images.map((image) => {
    const box = image.getBoundingClientRect();
    return Math.round(box.width / box.height * 10) / 10;
  }));
  assert.deepEqual(sizes, [1.4, 1, 1, 1]);
  // Every badge one height: the age rating's mark and the shields beside it.
  const heights = await page.$$eval("#ratings .rating",
    (nodes) => nodes.map((node) => node.getBoundingClientRect().height));
  assert.deepEqual(heights, heights.map(() => 28));
  // A tap on one shows its words over it.
  await page.locator("#ratings .rating").last().click();
  const [tip, shield] = await Promise.all(
    ["#ratingTip", "#ratings .rating:last-child"].map((selector) => page.locator(selector).boundingBox()));
  assert.ok(tip, "the words are shown");
  assert.ok(tip.y + tip.height <= shield.y, "over the shield");
  assert.ok(Math.abs(tip.x + tip.width / 2 - (shield.x + shield.width / 2)) <= 1, "over its middle");
  const marks = await page.$$eval("#ratings .rating", (nodes) => nodes.map((node) => [
    node.querySelector("img").getAttribute("src"),
    [...node.querySelectorAll(".value")].map((part) => part.textContent).join("")]));
  // The age rating first, the awards last: what was won, then what was
  // only nominated for.
  assert.deepEqual(marks, [["/ratings/fsk12.svg", "12"], ["/ratings/imdb.svg", "7.9"],
                           ["/ratings/award_oscar.svg", "1"], ["/ratings/award_globe.svg", "1"]]);
  // That one quieter: its plate dimmed.
  assert.deepEqual(await page.$$eval("#ratings .rating .side", (nodes) =>
    nodes.map((node) => getComputedStyle(node).opacity)), ["1", "1", "1", "0.6"]);
  assert.equal(await page.locator("#tagline").innerText(), "One night changes everything.");
  // The plot's own line break, drawn as one.
  assert.equal(await page.locator("#plotText").innerText(),
               "A film about somebody.\nAnd what happens to them.");
  // The slogan in italics right over the plot, as the app sets it.
  assert.equal(await page.$eval("#tagline", (node) => getComputedStyle(node).fontStyle), "italic");
  const [sloganBox, textBox] = await Promise.all(
    ["#tagline", "#plotText"].map((selector) => page.locator(selector).boundingBox()));
  assert.ok(Math.abs(textBox.y - (sloganBox.y + sloganBox.height) - 8) <= 1, "the slogan a little over the plot");
  const [now, plot] = await Promise.all(
    ["#nowCard", "#plotCard"].map((selector) => page.locator(selector).boundingBox()));
  assert.ok(plot.y > now.y + now.height - 1, "under the playing card");
  // The ratings centred over the plot; the facts under it, each its name over
  // the names, and the cast under them.
  const [row, first, last, credits, cast] = await Promise.all(
    ["#ratings", "#ratings .rating:first-child", "#ratings .rating:last-child", "#credits", "#castBlock"]
      .map((selector) => page.locator(selector).boundingBox()));
  const left = first.x - row.x;
  const right = row.x + row.width - (last.x + last.width);
  assert.ok(Math.abs(left - right) <= 2, `centred: ${left} vs ${right}`);
  assert.ok(credits.y >= textBox.y + textBox.height - 1, "the facts under the plot");
  assert.ok(cast.y >= credits.y + credits.height - 1, "the cast under the facts");
  assert.deepEqual(await page.$$eval("#credits .fact", (facts) => facts.map((fact) => fact.innerText)),
                   ["#32410\nDrama", "#32386\nSomebody", "#32408\nA Studio"]);
  const [term, names] = await Promise.all(["#credits dt", "#credits dd"].map((selector) =>
    page.locator(selector).first().boundingBox()));
  assert.ok(names.y >= term.y + term.height - 1, "the names under what they are");
});

test("the chapters ahead sit on the bar, a mouse brings up the rest, a click jumps", async () => {
  await page.mouse.move(0, 0);
  await page.waitForSelector(".chapter-dot");
  // Chapter 2 plays at 8.3 %: its own start (4.2 %) is behind the bar, the
  // first starts at 0 and has none.
  assert.equal(await page.locator(".chapter-dot").count(), 2, "only the ones ahead");
  // The stubs hand out string ids for words (see tests/stubs/xbmcaddon.py).
  assert.equal(await page.locator("#chapterNow").innerText(), "#32367 · Arrival");

  // Every dot sits on the middle of the fill's run, whatever it is laid over.
  const bar = await page.locator("#track").boundingBox();
  const boxes = () => page.locator(".chapter-dot").evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect().toJSON()));
  const dots = await boxes();
  for (const dot of dots) {
    const middle = dot.y + dot.height / 2;
    assert.ok(Math.abs(middle - (bar.y + 8 + 6)) <= 1, `dot at ${middle}, bar at ${bar.y}`);
    assert.ok(dot.x >= bar.x && dot.x + dot.width <= bar.x + bar.width);
  }

  const third = dots[0];
  await page.mouse.move(third.x + third.width / 2, third.y + third.height / 2);
  await page.waitForFunction(() => document.querySelectorAll(".chapter-dot").length === 3);
  await page.waitForSelector("#chapterTip:not(.hidden)");
  assert.equal(await page.locator("#chapterTip").innerText(), "#32366 · 01:00:00");
  const tip = await page.locator("#chapterTip").boundingBox();
  assert.ok(tip.y + tip.height <= bar.y + 8, "the name stands over the bar");

  // The one already seen, now that the mouse has brought it up.
  const [seen] = await boxes();
  await page.mouse.move(seen.x + seen.width / 2, seen.y + seen.height / 2);
  await page.waitForFunction(() => document.querySelector("#chapterTip").textContent.includes("00:05:00"));
  assert.equal(await page.locator(".chapter-dot.played").count(), 1);

  const [request] = await Promise.all([
    page.waitForRequest((sent) => sent.method() === "POST" && sent.url().endsWith("/api/command")),
    page.mouse.click(seen.x + seen.width / 2, seen.y + seen.height / 2),
  ]);
  assert.deepEqual(JSON.parse(request.postData()), { action: "chapter_goto", value: 2 });
  await page.mouse.move(0, 0);
  await page.waitForSelector("#chapterTip.hidden", { state: "attached" });
  await page.waitForFunction(() => document.querySelectorAll(".chapter-dot").length === 2);
});

test("a finger drags the bar, and the box hears once, where it let go", async () => {
  // A phone of its own: touch, and a narrow screen.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 },
                                           hasTouch: true, isMobile: true });
  await phone.addInitScript((token) => localStorage.setItem("tinyppi.token", token), TOKEN);
  const handset = await phone.newPage();
  const errors = [];
  handset.on("pageerror", (error) => errors.push(error.message));
  const sent = [];
  handset.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/command")) {
      sent.push(JSON.parse(request.postData()));
    }
  });
  await handset.goto(base + "#live");
  await handset.waitForSelector(".track.seekable");
  const bar = await handset.locator("#track").boundingBox();
  const y = bar.y + bar.height / 2;
  const cdp = await phone.newCDPSession(handset);
  const touch = (type, at) => cdp.send("Input.dispatchTouchEvent", {
    type, touchPoints: type === "touchEnd" ? [] : [{ x: bar.x + bar.width * at, y }] });

  await touch("touchStart", 0.2);
  for (let step = 1; step <= 10; step++) await touch("touchMove", 0.2 + step * 0.04);
  // Chromium hands a finger's moves on to the page once a frame, so the last
  // may still be on its way: wait for the fill to arrive under the finger
  // rather than read it at once.
  const fill = () => handset.evaluate(() => parseFloat(document.getElementById("bar").style.width));
  try {
    await handset.waitForFunction(() =>
      Math.abs(parseFloat(document.getElementById("bar").style.width) - 60) < 0.5, null, { timeout: 5000 });
  } catch {
    assert.fail(`the fill under the finger, not ${await fill()}`);
  }
  const held = await handset.evaluate(() => ({
    dots: document.querySelectorAll(".chapter-dot").length,
    clock: document.getElementById("tElapsed").textContent,
  }));
  assert.equal(held.dots, 3, "every chapter while the finger is on the bar");
  assert.equal(held.clock, "01:12:00", "and the clock with it");
  assert.deepEqual(sent, [], "nothing is asked of the box mid-drag");

  const asked = handset.waitForRequest((request) =>
    request.method() === "POST" && request.url().endsWith("/api/command"));
  await touch("touchEnd");
  const command = JSON.parse((await asked).postData());
  assert.equal(command.action, "seek_percent");
  assert.ok(Math.abs(command.value - 60) < 0.5, `seeks to ${command.value}`);
  await handset.waitForFunction(() => document.querySelectorAll(".chapter-dot").length === 2);
  assert.equal(sent.length, 1, "once");
  assert.deepEqual(errors, []);
  await phone.close();
});

test("films: the wall, search and clearing it", async () => {
  await tab("films");
  await page.waitForFunction(() => document.querySelectorAll("#filmGrid .film").length === 20);
  await page.fill("#filmSearch", "Film 1");
  // "Film 10" to "Film 19"; the titles are numbered with two digits.
  await page.waitForFunction(() =>
    [...document.querySelectorAll("#filmGrid .film")].filter((tile) => !tile.hidden).length === 10);
  assert.equal(await page.textContent("#filmsCount"), "10 / 20");
  await page.click("#filmSearchClear");
  assert.equal(await page.inputValue("#filmSearch"), "");
  assert.equal(await page.textContent("#filmsCount"), "20");
});

test("a press on a film asks, and marking it sends the id", async () => {
  await page.locator("#filmGrid .film").nth(4).click();
  await page.waitForSelector("#markDialog[open]");
  // Listened for before the press: the wall may be read again (the library
  // moved) before the click itself has returned.
  const [request] = await Promise.all([
    page.waitForRequest((sent) => sent.method() === "POST" && sent.url().endsWith("/api/watched")),
    page.waitForResponse((answer) => answer.url().includes("/api/library")),
    page.click("#markWatched"),
  ]);
  const body = JSON.parse(request.postData());
  assert.equal(typeof body.movieid, "number");
  assert.equal(typeof body.watched, "boolean");
  await page.waitForFunction(() => !document.querySelector("#markDialog[open]"));
});

test("cancelling the question sends nothing", async () => {
  const before = posts.length;
  await page.locator("#filmGrid .film").first().click();
  await page.waitForSelector("#markDialog[open]");
  await page.click("#markCancel");
  await page.waitForFunction(() => !document.querySelector("#markDialog[open]"));
  assert.equal(posts.length, before);
});

test("series: a show opens with its seasons and episodes", async () => {
  await tab("series");
  await page.waitForFunction(() => document.querySelectorAll("#seriesGrid .film").length === 5);
  await page.locator("#seriesGrid .film").nth(1).click();
  await page.waitForSelector("#markDialog[open]");
  await page.click("#markPlay");
  await page.waitForSelector(".seasonfold");
  assert.equal(await page.locator(".seasonfold").count(), 2);
  await page.locator(".seasonfold .season").first().click();
  await page.waitForFunction(() => document.querySelector(".seasonepisodes")?.children.length > 0);
  await page.click("#seriesBack");
  await page.waitForFunction(() => document.querySelectorAll(".seasonfold").length === 0);
});

test("history: the events are worded for people", async () => {
  await tab("history");
  await page.waitForFunction(() => document.body.innerText.includes("Deutsch"));
  const body = await page.locator("body").innerText();
  assert.ok(body.includes("77 °C"));
  assert.ok(!body.includes("#2 · GER"), "track numbers and codes are dropped");
});

test("metadata and settings tabs open", async () => {
  await tab("metadata");
  await page.waitForSelector("#tab-metadata:not([hidden])");
  await tab("settings");
  await page.waitForSelector("#copyBtn");
});

test("the token travels in headers only; the stream reads with an HttpOnly session", async () => {
  assert.ok(addresses.some((address) => address.endsWith("/api/stream")));
  assert.deepEqual(addresses.filter((address) => /token=/i.test(address)), []);
  const [session] = (await context.cookies(base + "api/state")).filter((cookie) => cookie.name === "tinyppi_session");
  assert.ok(session, "the session cookie is set");
  assert.equal(session.httpOnly, true);
  assert.equal(session.sameSite, "Strict");
  assert.equal(session.path, "/api/");
  assert.equal(await page.evaluate(() => document.cookie), "");
});

test("no script errors anywhere", () => {
  assert.deepEqual(problems, []);
});
