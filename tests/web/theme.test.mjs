// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The three themes and the adaptive one's strength (resources/web/js/theme.js):
// what is put on <html> before the first paint, the choice drawn into the
// settings tab, what a press on it changes and keeps, and the localized words
// core.js hands over.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { bare, page as harnessPage, source } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");

const opened = [];
after(() => { for (const window of opened) window.close(); });

function page(options) {
  const view = harnessPage(options);
  opened.push(view.window);
  return view;
}

/* A script run into a page after the fact, under its own file URL like the
   harness does: for storage that has to be filled or blocked first, or a
   document that has to have finished loading first. */
function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/* theme.js runs while the document is still loading and draws the choice
   once it has finished. */
function contentLoaded(window) {
  if (window.document.readyState !== "loading") return Promise.resolve();
  return new Promise((resolve) =>
    window.document.addEventListener("DOMContentLoaded", resolve, { once: true }));
}

/* A page whose storage holds *stored* when theme.js first reads it. */
async function themed(stored = {}) {
  const view = page({ scripts: [] });
  for (const [key, value] of Object.entries(stored)) view.window.localStorage.setItem(key, value);
  load(view.dom, "theme.js");
  await contentLoaded(view.window);
  return view;
}

const html = (window) => [window.document.documentElement.getAttribute("data-theme"),
                          window.document.documentElement.getAttribute("data-cover-strength")];
const options = (window) => [...window.document.querySelectorAll("#themeSettings .theme-option")];
const levels = (window) => [...window.document.querySelectorAll("#themeStrength .theme-group-option")];
const chosen = (window) => options(window)
  .filter((option) => option.classList.contains("selected")).map((option) => option.dataset.theme);
const pressed = (window) => levels(window)
  .filter((option) => option.getAttribute("aria-pressed") === "true").map((option) => option.dataset.level);

test("a first visit gets the adaptive theme at standard strength, before anything is drawn", async () => {
  const { window } = page({ scripts: ["theme.js"] });
  assert.equal(window.document.readyState, "loading");
  assert.deepEqual(html(window), ["dark-adaptive", "1"]);
  assert.equal(window.document.getElementById("themeSettings").childElementCount, 0);
  await contentLoaded(window);
  assert.equal(options(window).length, 3);
  assert.equal(window.TinyPPITheme.theme(), "dark-adaptive");
  assert.equal(window.TinyPPITheme.strength(), 1);
  assert.equal(window.TinyPPITheme.ADAPTIVE, "dark-adaptive");
});

test("the theme and strength chosen last time are put back", async () => {
  const { window } = await themed({ "tinyppi.theme": "midnight", "tinyppi.tint": "2" });
  assert.deepEqual(html(window), ["midnight", "2"]);
  assert.deepEqual(chosen(window), ["midnight"]);
  assert.equal(window.document.getElementById("themeStrength").hidden, true);
  assert.deepEqual(pressed(window), ["2"]);
});

test("the phone's bars wear the theme from the first paint, not only after a press", async () => {
  const bars = (window) => window.document.querySelector('meta[name="theme-color"]').getAttribute("content");
  assert.equal(bars((await themed()).window), "#0b0d10");
  assert.equal(bars((await themed({ "tinyppi.theme": "midnight" })).window), "#04060c");
});

test("unknown stored values fall back to the defaults", async () => {
  for (const [theme, tint] of [["neon", "7"], ["Midnight", "-1"], ["", "x"], ["dark", "0.5"]]) {
    const { window } = await themed({ "tinyppi.theme": theme, "tinyppi.tint": tint });
    const expected = theme === "dark" ? ["dark", "0"] : ["dark-adaptive", "1"];
    assert.deepEqual(html(window), expected, `${theme} / ${tint}`);
  }
});

test("blocked storage keeps the defaults and a choice still takes effect", async () => {
  const view = page({ scripts: [] });
  const { window } = view;
  Object.defineProperty(window, "localStorage", {
    configurable: true, get() { throw new window.DOMException("blocked", "SecurityError"); }
  });
  load(view.dom, "theme.js");
  await contentLoaded(window);
  assert.deepEqual(html(window), ["dark-adaptive", "1"]);
  options(window)[2].click();
  levels(window)[0].click();
  assert.deepEqual(html(window), ["midnight", "0"]);
});

test("the choice is a radio group of the three themes, each with its mark and name", async () => {
  const { window } = await themed();
  const group = window.document.querySelector("#themeSettings .theme-choices");
  assert.equal(group.getAttribute("role"), "radiogroup");
  assert.equal(group.getAttribute("aria-label"), "Choose a theme");
  assert.deepEqual(options(window).map((option) => [
    option.type, option.dataset.theme, option.getAttribute("role"), option.getAttribute("aria-checked"),
    option.querySelector(".ui-icon.painted").style.getPropertyValue("--icon"), option.textContent
  ]), [
    ["button", "dark", "radio", "false", 'url("/icons/theme-dark.svg")', "Dark"],
    ["button", "dark-adaptive", "radio", "true", 'url("/icons/theme-adaptive.svg")', "Dark (adaptive)"],
    ["button", "midnight", "radio", "false", 'url("/icons/theme-midnight.svg")', "Midnight"]
  ]);

  const row = window.document.getElementById("themeStrength");
  assert.equal(row.getAttribute("role"), "group");
  assert.equal(row.getAttribute("aria-label"), "Intensity");
  assert.equal(row.querySelector(".theme-group-label").textContent, "Intensity");
  assert.equal(row.hidden, false);
  assert.deepEqual(levels(window).map((option) => [option.dataset.level, option.textContent]),
                   [["0", "Subtle"], ["1", "Standard"], ["2", "Strong"]]);
  assert.deepEqual(pressed(window), ["1"]);
});

test("a press on a theme wears it at once, keeps it, and paints the phone's bars", async () => {
  const { window } = await themed();
  const meta = window.document.querySelector('meta[name="theme-color"]');
  options(window)[2].click();
  assert.deepEqual(html(window), ["midnight", "1"]);
  assert.equal(window.localStorage.getItem("tinyppi.theme"), "midnight");
  assert.equal(meta.getAttribute("content"), "#04060c");
  assert.deepEqual(chosen(window), ["midnight"]);
  assert.deepEqual(options(window).map((option) => option.getAttribute("aria-checked")),
                   ["false", "false", "true"]);
  // Only the adaptive theme tints, so only it offers how strongly.
  assert.equal(window.document.getElementById("themeStrength").hidden, true);

  options(window)[0].click();
  assert.equal(meta.getAttribute("content"), "#0b0d10");
  assert.deepEqual(chosen(window), ["dark"]);
  options(window)[1].click();
  assert.equal(window.document.getElementById("themeStrength").hidden, false);
  assert.equal(window.TinyPPITheme.theme(), "dark-adaptive");
});

test("a press on a strength sets it, keeps it and marks it", async () => {
  const { window } = await themed();
  levels(window)[2].click();
  assert.deepEqual(html(window), ["dark-adaptive", "2"]);
  assert.equal(window.localStorage.getItem("tinyppi.tint"), "2");
  assert.deepEqual(pressed(window), ["2"]);
  assert.equal(window.TinyPPITheme.strength(), 2);
  levels(window)[0].click();
  assert.deepEqual(pressed(window), ["0"]);
  assert.equal(window.TinyPPITheme.strength(), 0);
});

test("what is on <html> is read back, and nonsense there reads as the default", async () => {
  const { window } = await themed();
  const root = window.document.documentElement;
  root.setAttribute("data-theme", "midnight");
  root.setAttribute("data-cover-strength", "0");
  assert.equal(window.TinyPPITheme.theme(), "midnight");
  assert.equal(window.TinyPPITheme.strength(), 0);
  root.setAttribute("data-theme", "sepia");
  root.setAttribute("data-cover-strength", "3");
  assert.equal(window.TinyPPITheme.theme(), "dark-adaptive");
  assert.equal(window.TinyPPITheme.strength(), 1);
  root.removeAttribute("data-cover-strength");
  assert.equal(window.TinyPPITheme.strength(), 1);
});

test("localized words rebuild the choice, the same words leave it be", async () => {
  const { window } = await themed();
  const before = options(window)[0];
  window.TinyPPITheme.strings({ theme_dark: "Dark", tint_label: "", other: "x" });
  assert.equal(options(window)[0], before);              // nothing changed, nothing rebuilt
  window.TinyPPITheme.strings({ theme_dark: "Dunkel", theme_menu: "Thema wählen", tint_strong: "Stark" });
  assert.notEqual(options(window)[0], before);
  assert.equal(options(window)[0].textContent, "Dunkel");
  assert.equal(options(window)[2].textContent, "Midnight");
  assert.equal(window.document.querySelector(".theme-choices").getAttribute("aria-label"), "Thema wählen");
  assert.equal(levels(window)[2].textContent, "Stark");
  assert.deepEqual(chosen(window), ["dark-adaptive"]);    // still marked after the rebuild
});

test("core.js hands the add-on's words over once /api/hello answers", async () => {
  const { window } = page({
    scripts: ["theme.js", "core.js"],
    routes: { "/api/hello": [200, { strings: { theme_adaptive: "Dunkel (adaptiv)", tint_label: "Stärke" } }] }
  });
  await contentLoaded(window);
  await window.TinyPPI.boot({});
  assert.equal(options(window)[1].textContent, "Dunkel (adaptiv)");
  assert.equal(window.document.querySelector("#themeStrength .theme-group-label").textContent, "Stärke");
});

test("loaded after the document is ready, the choice is drawn at once", async () => {
  const view = page({ scripts: [] });
  await contentLoaded(view.window);
  load(view.dom, "theme.js");
  assert.equal(options(view.window).length, 3);
  assert.deepEqual(chosen(view.window), ["dark-adaptive"]);
});

test("a page without the settings card still wears the theme", async () => {
  const window = bare("theme.js");
  opened.push(window);
  await contentLoaded(window);
  assert.deepEqual(html(window), ["dark-adaptive", "1"]);
  window.TinyPPITheme.strings({ theme_dark: "Dunkel" });
  assert.equal(window.document.querySelector(".theme-option"), null);
});

test("a theme page without the phone's colour tag still changes theme", async () => {
  const { window } = await themed();
  window.document.querySelector('meta[name="theme-color"]').remove();
  options(window)[0].click();
  assert.deepEqual(html(window), ["dark", "1"]);
  assert.deepEqual(chosen(window), ["dark"]);
});

test("keys whose card was emptied or cut down still change the theme", async () => {
  const { window } = await themed();
  const host = window.document.getElementById("themeSettings");
  // Without its strength row the choice is still marked.
  window.document.getElementById("themeStrength").remove();
  options(window)[2].click();
  assert.deepEqual(chosen(window), ["midnight"]);
  // A key from a card somebody emptied changes the theme and draws nothing.
  const [dark] = options(window);
  host.replaceChildren();
  dark.click();
  assert.deepEqual(html(window), ["dark", "1"]);
  assert.equal(host.childElementCount, 0);
  assert.equal(dark.classList.contains("selected"), false);
});
