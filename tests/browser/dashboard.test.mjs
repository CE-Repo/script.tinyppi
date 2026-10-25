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
  assert.equal(await page.locator("#poster").evaluate((node) => getComputedStyle(node).borderWidth), "0px");
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

test("the overview is a key under the playing card that opens the title's details", async () => {
  await page.waitForSelector("#plotCard:not(.hidden)");
  const [now, card] = await Promise.all(
    ["#nowCard", "#plotCard"].map((selector) => page.locator(selector).boundingBox()));
  assert.ok(card.y > now.y + now.height - 1, "under the playing card");
  // Its heading alone: nothing of the title in it.
  assert.equal(await page.locator("#plotCard").innerText(), "#32370");
  await page.locator("#plotCard").click();
  await page.waitForSelector("#detailsDialog[open]");
  await page.waitForFunction(() => document.getElementById("detailsPlot").textContent.length > 0);
  assert.equal(await page.locator("#detailsPlot").innerText(), "A film about somebody.");
  // The playing title's: nothing to play.
  assert.equal(await page.locator(".detailsactions").isVisible(), false);
  // The shields as the details draw them, every one one height.
  await page.waitForFunction(() => [...document.querySelectorAll("#detailsRatings img")]
    .every((image) => image.complete && image.naturalWidth > 0));
  const heights = await page.$$eval("#detailsRatings .rating",
    (nodes) => nodes.map((node) => node.getBoundingClientRect().height));
  assert.ok(heights.length && heights.every((height) => height === 28));
  // Verify narrow and wide layouts, including cards beyond the visible edge.
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const rows = await page.locator("#detailsCast .castrow").evaluateAll((nodes) => nodes.map((row) => ({
      cards: [...row.querySelectorAll("li:not(.more)")].map((card) => ({
        width: card.getBoundingClientRect().width,
        height: card.getBoundingClientRect().height,
        centered: (() => {
          const bounds = card.getBoundingClientRect();
          const top = card.querySelector(".initial").getBoundingClientRect().top;
          const last = card.querySelector(".role:not(:empty)") || card.querySelector("strong");
          return Math.abs((top + last.getBoundingClientRect().bottom) / 2 - (bounds.top + bounds.height / 2)) < 1;
        })(),
        fits: [...card.querySelectorAll("strong, .role")].every((text) =>
          text.scrollHeight <= text.clientHeight && text.scrollWidth <= text.clientWidth)
      }))
    })));
    assert.equal(rows.length, 3, "director, writer and cast have their own rows");
    for (const { cards } of rows) {
      assert.ok(cards.length && cards.every((card) => card.width === 136));
      assert.ok(cards.every((card) => card.height === cards[0].height && card.fits && card.centered));
    }
    assert.ok(rows[0].cards[0].height < rows[2].cards[0].height, "crew has no empty role slot");
    await page.locator("#detailsCast").screenshot({ path: `node_modules/credits-${width}.png` });
  }
  await page.locator("#detailsX").click();
  await page.waitForFunction(() => !document.getElementById("detailsDialog").open);
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
  const cover = page.locator("#filmGrid .filmposter").first();
  const border = await cover.evaluate((node) => getComputedStyle(node).borderColor);
  await cover.hover();
  assert.notEqual(await cover.evaluate((node) => getComputedStyle(node).boxShadow), "none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.waitForFunction(() => new DOMMatrixReadOnly(getComputedStyle(document.querySelector("#filmGrid .filmposter")).transform).m42 < -1);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(() => getComputedStyle(document.querySelector("#filmGrid .filmposter")).transform === "none");
  assert.equal(await cover.evaluate((node) => getComputedStyle(node).borderColor), border);
  await page.fill("#filmSearch", "Film 1");
  // "Film 10" to "Film 19"; the titles are numbered with two digits.
  await page.waitForFunction(() =>
    [...document.querySelectorAll("#filmGrid .film")].filter((tile) => !tile.hidden).length === 10);
  assert.equal(await page.textContent("#filmsCount"), "10 / 20");
  await page.click("#filmSearchClear");
  assert.equal(await page.inputValue("#filmSearch"), "");
  assert.equal(await page.textContent("#filmsCount"), "20");
});

test("a short press opens a film's details without starting playback", async () => {
  const before = posts.length;
  await page.locator("#filmGrid .film").nth(4).click();
  await page.waitForSelector("#detailsDialog[open]");
  assert.equal(await page.locator("#detailsTitle").innerText(), "Film 05");
  assert.equal(await page.locator("#detailsPlot").innerText(), "A film about somebody.");
  assert.equal(await page.locator("#markDialog").isVisible(), false);
  assert.equal(posts.length, before);
  await page.locator("#detailsX").click();
  await page.waitForFunction(() => !document.getElementById("detailsDialog").open);
});

test("details keep scrolling inside the dialog and rating hints work by click and keyboard", async () => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator("#filmGrid .film").nth(4).click();
    await page.waitForSelector("#detailsDialog[open]");
    await page.locator("#detailsPlot").evaluate((node) => {
      node.textContent = Array(80).fill("A long plot paragraph to make the details scroll.").join("\n\n");
    });
    const rootY = await page.evaluate(() => window.scrollY);
    assert.equal(await page.locator("#detailsClose").count(), 0);
    assert.equal(await page.locator("html").evaluate((node) => getComputedStyle(node).overflowY), "hidden");
    const badge = page.locator("#detailsRatings .rating:has(.side.imdb)");
    await badge.click();
    const tip = page.locator("#detailsRatings .rating-tip:popover-open");
    await tip.waitFor();
    assert.equal(await tip.innerText(), "IMDb");
    const rect = await tip.boundingBox();
    assert.ok(rect.x >= 0 && rect.x + rect.width <= width);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#detailsDialog").isVisible(), true);
    await badge.focus();
    await page.keyboard.press("Enter");
    await tip.waitFor();
    const form = page.locator("#detailsDialog form");
    const before = await form.evaluate((node) => node.scrollTop);
    const box = await form.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 300);
    await page.waitForFunction((at) => document.querySelector("#detailsDialog form").scrollTop > at, before);
    await tip.waitFor({ state: "hidden" });
    assert.equal(await page.evaluate(() => window.scrollY), rootY);
    await form.evaluate((node) => { node.scrollTop = node.scrollHeight; });
    await page.mouse.wheel(0, 600);
    // Wait for wheel scrolling to reach the compositor before checking the root.
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(() => window.scrollY), rootY, "no scroll chaining at the end");
    await page.mouse.move(4, 450);
    await page.mouse.wheel(0, 300);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(() => window.scrollY), rootY, "the backdrop cannot scroll the page");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.getElementById("detailsDialog").open);
    assert.notEqual(await page.locator("html").evaluate((node) => getComputedStyle(node).overflowY), "hidden");
  }
  await page.setViewportSize({ width: 1280, height: 900 });
});

test("details show all resume actions and marks without clipping on a phone", async () => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.locator("#filmGrid .film").nth(2).click({ delay: 600 });
  await page.waitForSelector("#detailsDialog[open]");
  assert.equal(await page.locator("#markDialog").count(), 0);
  for (const id of ["detailsPlay", "detailsRestart", "detailsClear", "detailsWatched", "detailsUnwatched"]) {
    const button = page.locator("#" + id);
    assert.equal(await button.isVisible(), true, id);
    assert.ok(await button.evaluate((node) => node.scrollWidth <= node.clientWidth && node.scrollHeight <= node.clientHeight), id);
  }
  await page.locator("#detailsActions").screenshot({ path: "node_modules/details-actions-phone.png" });
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.getElementById("detailsDialog").open);
  await page.setViewportSize({ width: 1280, height: 900 });
});

test("a long press opens details, and marking the film sends the id", async () => {
  await page.locator("#filmGrid .film").nth(4).click({ delay: 600 });
  await page.waitForSelector("#detailsDialog[open]");
  // Listened for before the press: the wall may be read again (the library
  // moved) before the click itself has returned.
  const [request] = await Promise.all([
    page.waitForRequest((sent) => sent.method() === "POST" && sent.url().endsWith("/api/watched")),
    page.waitForResponse((answer) => answer.url().includes("/api/library")),
    page.click("#detailsWatched"),
  ]);
  const body = JSON.parse(request.postData());
  assert.equal(typeof body.movieid, "number");
  assert.equal(typeof body.watched, "boolean");
  await page.waitForFunction(() => !document.querySelector("#detailsDialog[open]"));
});

test("cancelling the question sends nothing", async () => {
  const before = posts.length;
  await page.locator("#filmGrid .film").first().click({ delay: 600 });
  await page.waitForSelector("#detailsDialog[open]");
  await page.click("#detailsX");
  await page.waitForFunction(() => !document.querySelector("#detailsDialog[open]"));
  assert.equal(posts.length, before);
});

test("series: a show opens with its seasons and episodes", async () => {
  await tab("series");
  await page.waitForFunction(() => document.querySelectorAll("#seriesGrid .film").length === 5);
  await page.locator("#seriesGrid .film").nth(1).click();
  await page.waitForSelector("#detailsDialog[open]");
  assert.equal(await page.locator("#markDialog").isVisible(), false);
  await page.click("#detailsPlay");
  await page.waitForFunction(() => !document.getElementById("detailsDialog").open);
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
