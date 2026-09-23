// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The three themes the dashboard wears, remembered across visits.

   All of them are dark -- the page is watched in the room the projector is in
   -- and they differ in how far down they go and in where their colour comes
   from:

     dark           the plain one, and what a first visit gets
     dark-adaptive  the same page, with the now-playing card taking its colour
                    from the poster of whatever is on screen (js/cover-tint.js)
     midnight       deeper and bluer, for a room with nothing else lit in it

   They are picked on the settings tab, where this file draws the choice into
   #themeSettings.  While the adaptive theme is the one in force it also
   offers how strongly it tints, which is a property of that theme rather
   than a setting of its own.

   This file is loaded from <head> rather than with the rest of the scripts:
   the stored theme has to be on <html> before the first paint, or the page
   shows the default one for a frame first.  Everything that needs the document
   waits for it.
=========================================================================== */

window.TinyPPITheme = (function () {

  const THEME_KEY    = "tinyppi.theme";
  const STRENGTH_KEY = "tinyppi.tint";

  /* Also the order they are offered in: the two that share a palette, then
     the one that does not. */
  const THEME_ORDER = ["dark", "dark-adaptive", "midnight"];

  /* What a first visit gets, and what an unreadable or unknown stored value
     falls back to. */
  const DEFAULT_THEME = "dark-adaptive";

  /* The one theme js/cover-tint.js paints for; every other one ignores it. */
  const ADAPTIVE = "dark-adaptive";

  /* How strongly that theme tints, from subtle to loudest.  Only it reads the
     setting, so the row of buttons is only offered while it is in force. */
  const STRENGTH_KEYS = ["tint_subtle", "tint_standard", "tint_strong"];
  const DEFAULT_STRENGTH = 1;

  /* What the phone paints its own bars in, per theme: the colour the top bar
     sits on rather than the page's, since that is what reaches the edge. */
  const META_COLORS = {
    dark: "#0b0d10", "dark-adaptive": "#0b0d10", midnight: "#04060c"
  };

  const NAME_KEYS = {
    dark: "theme_dark", "dark-adaptive": "theme_adaptive", midnight: "theme_midnight"
  };

  const ICONS = {
    dark: "/icons/theme-dark.svg",
    "dark-adaptive": "/icons/theme-adaptive.svg",
    midnight: "/icons/theme-midnight.svg"
  };

  /* The chrome this file owns, in the language the add-on answers in.  The
     English here is only what shows in the instant before /api/hello arrives;
     core.js hands the localized set over through strings(). */
  const T = {
    theme_dark: "Dark", theme_adaptive: "Dark (adaptive)", theme_midnight: "Midnight",
    theme_menu: "Choose a theme",
    tint_label: "Intensity", tint_subtle: "Subtle", tint_standard: "Standard",
    tint_strong: "Strong"
  };

  let host = null;       /* #themeSettings, once the document has it */

  /* --- what is on the page ---------------------------------------------- */

  function readTheme() {
    const value = document.documentElement.getAttribute("data-theme");
    return THEME_ORDER.includes(value) ? value : DEFAULT_THEME;
  }

  function readStrength() {
    const value = parseInt(
      document.documentElement.getAttribute("data-cover-strength"), 10);
    return Number.isInteger(value) && value >= 0 && value < STRENGTH_KEYS.length
      ? value : DEFAULT_STRENGTH;
  }

  function store(key, value) {
    try { localStorage.setItem(key, String(value)); }
    catch (_) { /* no localStorage -> the choice just will not persist */ }
  }

  /* Both attributes are set before the first paint, below, so this is only
     what puts a *change* on the page.  js/cover-tint.js watches them. */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", META_COLORS[theme] || META_COLORS[DEFAULT_THEME]);
    paint();
  }

  function setTheme(theme) {
    if (!THEME_ORDER.includes(theme)) theme = DEFAULT_THEME;
    store(THEME_KEY, theme);
    applyTheme(theme);
  }

  function setStrength(level) {
    store(STRENGTH_KEY, level);
    document.documentElement.setAttribute("data-cover-strength", String(level));
    paint();
  }

  /* --- the settings ------------------------------------------------------ */

  /* The three themes as a row of keys, each with its mark and its name, and
     under them how strongly the adaptive one tints.  Choosing takes effect at
     once, on the whole page -- the tint can be tried against the cards of any
     tab and then changed again. */
  function build() {
    if (!host) return;
    host.replaceChildren();

    const choices = document.createElement("div");
    choices.className = "theme-choices";
    choices.setAttribute("role", "radiogroup");
    choices.setAttribute("aria-label", T.theme_menu);
    for (const theme of THEME_ORDER) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "theme-option";
      option.dataset.theme = theme;
      option.setAttribute("role", "radio");

      /* Painted rather than drawn, so the mark follows the colour of the key
         it is on (see .ui-icon.painted). */
      const image = document.createElement("span");
      image.className = "ui-icon painted";
      image.style.setProperty("--icon", `url("${ICONS[theme]}")`);
      const text = document.createElement("span");
      text.textContent = T[NAME_KEYS[theme]];

      option.append(image, text);
      option.addEventListener("click", () => setTheme(theme));
      choices.append(option);
    }
    host.append(choices, buildStrengthRow());
    paint();
  }

  function buildStrengthRow() {
    const row = document.createElement("div");
    row.className = "theme-group";
    row.id = "themeStrength";
    row.setAttribute("role", "group");

    const label = document.createElement("span");
    label.className = "theme-group-label";
    label.textContent = T.tint_label;
    row.append(label);

    const options = document.createElement("div");
    options.className = "theme-group-options";
    STRENGTH_KEYS.forEach((key, level) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "theme-group-option";
      option.dataset.level = String(level);
      option.textContent = T[key];
      option.addEventListener("click", () => setStrength(level));
      options.append(option);
    });
    row.append(options);
    return row;
  }

  function paint() {
    if (!host || !host.firstChild) return;
    const theme = readTheme();
    for (const option of host.querySelectorAll(".theme-option")) {
      const chosen = option.dataset.theme === theme;
      option.classList.toggle("selected", chosen);
      option.setAttribute("aria-checked", chosen ? "true" : "false");
    }

    /* There is nothing to dose on a theme that paints no poster, so the row is
       only offered by the one that does. */
    const row = host.querySelector("#themeStrength");
    if (!row) return;
    row.hidden = theme !== ADAPTIVE;
    row.setAttribute("aria-label", T.tint_label);
    const strength = String(readStrength());
    for (const option of row.querySelectorAll(".theme-group-option")) {
      option.setAttribute("aria-pressed",
        option.dataset.level === strength ? "true" : "false");
    }
  }

  function attach() {
    host = document.getElementById("themeSettings");
    build();
  }

  /* --- before the first paint -------------------------------------------- */

  /* This runs while <head> is being parsed, which is the whole reason the file
     is loaded there: read what was chosen last time and put it on <html>
     before anything is drawn with the default. */
  (function () {
    let theme = DEFAULT_THEME;
    let strength = DEFAULT_STRENGTH;
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (THEME_ORDER.includes(saved)) theme = saved;
      const level = parseInt(localStorage.getItem(STRENGTH_KEY), 10);
      if (Number.isInteger(level) && level >= 0 && level < STRENGTH_KEYS.length) {
        strength = level;
      }
    } catch (_) { /* no localStorage -> keep the defaults */ }
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-cover-strength", String(strength));
  })();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attach, { once: true });
  } else {
    attach();
  }

  return {
    ADAPTIVE,
    theme: readTheme,
    strength: readStrength,

    /* The localized words, handed over by core.js once /api/hello answers.
       The choices are built from them, so they are made again. */
    strings(source) {
      let changed = false;
      for (const key of Object.keys(T)) {
        if (source[key] && source[key] !== T[key]) { T[key] = source[key]; changed = true; }
      }
      if (changed) build();
    }
  };

})();
