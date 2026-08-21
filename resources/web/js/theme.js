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

   A press on the button in the top bar walks that order; a long press (or a
   right-click) opens a menu to jump straight to one of them.  While the
   adaptive theme is the one in force the menu also carries how strongly it
   tints, which is a property of that theme rather than a setting of its own.

   This file is loaded from <head> rather than with the rest of the scripts:
   the stored theme has to be on <html> before the first paint, or the page
   shows the default one for a frame first.  Everything that needs the document
   waits for it.
=========================================================================== */

window.TinyPPITheme = (function () {

  const THEME_KEY    = "tinyppi.theme";
  const STRENGTH_KEY = "tinyppi.tint";

  /* Also the order the menu lists them in, so a press walks the menu top to
     bottom -- the two that share a palette, then the one that does not. */
  const THEME_ORDER = ["dark", "dark-adaptive", "midnight"];

  /* What a first visit gets, and what an unreadable or unknown stored value
     falls back to. */
  const DEFAULT_THEME = "dark-adaptive";

  /* The one theme js/cover-tint.js paints for; every other one ignores it. */
  const ADAPTIVE = "dark-adaptive";

  /* How strongly that theme tints, from subtle to loudest.  Only it reads the
     setting, so the row of buttons is only in the menu while it is in force. */
  const STRENGTH_KEYS = ["tint_subtle", "tint_standard", "tint_strong"];
  const DEFAULT_STRENGTH = 1;

  /* What the phone paints its own bars in, per theme: the colour the top bar
     sits on rather than the page's, since that is what reaches the edge. */
  const META_COLORS = {
    dark: "#070a0e", "dark-adaptive": "#070a0e", midnight: "#03060d"
  };

  const NAME_KEYS = {
    dark: "theme_dark", "dark-adaptive": "theme_adaptive", midnight: "theme_midnight"
  };

  const ICONS = {
    dark: "/icons/theme-dark.svg",
    "dark-adaptive": "/icons/theme-adaptive.svg",
    midnight: "/icons/theme-midnight.svg"
  };

  /* Holding the button down this long opens the menu instead of cycling. */
  const LONG_PRESS_MS = 500;

  /* The menu closes itself after sitting idle this long, so it never lingers
     open once whoever opened it has walked away. */
  const MENU_IDLE_MS = 5000;

  /* How close to the edge of the viewport the menu may end up once it has been
     pushed back in, on a screen too narrow to hang it off the button. */
  const MENU_MARGIN = 8;

  /* The chrome this file owns, in the language the add-on answers in.  The
     English here is only what shows in the instant before /api/hello arrives;
     core.js hands the localized set over through strings(). */
  const T = {
    theme_dark: "Dark", theme_adaptive: "Dark (adaptive)", theme_midnight: "Midnight",
    theme_switch: "Switch to {name} (hold for the full list)",
    theme_menu: "Choose a theme",
    tint_label: "Intensity", tint_subtle: "Subtle", tint_standard: "Standard",
    tint_strong: "Strong"
  };

  let button = null;
  let menu = null;
  let icon = null;
  let pressTimer = 0;
  let longPressed = false;
  let idleTimer = 0;

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
    paintButton();
    paintMenu();
  }

  function setTheme(theme) {
    if (!THEME_ORDER.includes(theme)) theme = DEFAULT_THEME;
    store(THEME_KEY, theme);
    applyTheme(theme);
  }

  function setStrength(level) {
    store(STRENGTH_KEY, level);
    document.documentElement.setAttribute("data-cover-strength", String(level));
    paintMenu();
  }

  function nextTheme() {
    return THEME_ORDER[(THEME_ORDER.indexOf(readTheme()) + 1) % THEME_ORDER.length];
  }

  /* --- the button -------------------------------------------------------- */

  /* It always shows the theme a press switches *to*, which is what says the
     button is a cycle rather than a state. */
  function paintButton() {
    if (!button) return;
    const next = nextTheme();
    const label = T.theme_switch.replace("{name}", T[NAME_KEYS[next]]);
    icon.style.setProperty("--icon", `url("${ICONS[next]}")`);
    button.title = label;
    button.setAttribute("aria-label", label);
  }

  /* --- the menu ---------------------------------------------------------- */

  function buildMenu() {
    menu.replaceChildren();
    menu.setAttribute("aria-label", T.theme_menu);

    for (const theme of THEME_ORDER) {
      const item = document.createElement("li");
      item.className = "theme-option";
      item.dataset.theme = theme;
      item.setAttribute("role", "menuitemradio");

      /* Painted like the key in the bar, so the mark follows the row it is in:
         the chosen row already colours its text, and a white symbol beside
         coloured text was the one part of the row that did not answer. */
      const image = document.createElement("span");
      image.className = "ui-icon painted";
      image.style.setProperty("--icon", `url("${ICONS[theme]}")`);
      const text = document.createElement("span");
      text.textContent = T[NAME_KEYS[theme]];

      item.append(image, text);
      item.addEventListener("click", () => { setTheme(theme); closeMenu(); });
      menu.append(item);
    }

    menu.append(buildStrengthRow());
    paintMenu();
  }

  /* How strongly the adaptive theme tints, as a labelled row of buttons under
     the themes.  It stays in this menu rather than becoming a setting of its
     own: it is a property of one theme, and this is where that theme is
     picked.  Choosing does not close the menu -- the point is to see the
     difference on the card behind it and then try the next one. */
  function buildStrengthRow() {
    const row = document.createElement("li");
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
      option.addEventListener("click", () => { setStrength(level); keepOpen(); });
      options.append(option);
    });
    row.append(options);
    return row;
  }

  function paintMenu() {
    if (!menu || !menu.firstChild) return;
    const theme = readTheme();
    for (const item of menu.querySelectorAll(".theme-option")) {
      const chosen = item.dataset.theme === theme;
      item.classList.toggle("selected", chosen);
      item.setAttribute("aria-checked", chosen ? "true" : "false");
    }

    /* There is nothing to dose on a theme that paints no poster, so the row is
       only offered by the one that does. */
    const row = menu.querySelector("#themeStrength");
    if (!row) return;
    row.hidden = theme !== ADAPTIVE;
    row.setAttribute("aria-label", T.tint_label);
    const strength = String(readStrength());
    for (const option of row.querySelectorAll(".theme-group-option")) {
      option.setAttribute("aria-pressed",
        option.dataset.level === strength ? "true" : "false");
    }
  }

  /* The menu lives in <body> rather than beside the button, so the top bar
     cannot clip it; that means placing it against the button's own rect.  The
     menu is fixed and the bar is not, so anything that moves one without the
     other -- a resize, a scroll -- has to place it again; both are bound with
     the button's own handlers below. */
  function placeMenu() {
    const rect = button.getBoundingClientRect();
    const bar = document.querySelector(".topbar");
    const below = bar ? Math.max(rect.bottom, bar.getBoundingClientRect().bottom)
                      : rect.bottom;
    menu.style.top = (below + 6) + "px";

    /* Hung from the button's left edge, opening rightwards -- but the button
       sits near the right of the bar, so on a narrow screen that runs the menu
       off the side.  Pull it back to the last position that still fits, and
       never past the left edge either. */
    menu.style.left = "0px";
    const width = menu.getBoundingClientRect().width;
    const rightmost = window.innerWidth - width - MENU_MARGIN;
    menu.style.left = Math.max(MENU_MARGIN, Math.min(rect.left, rightmost)) + "px";
  }

  function openMenu() {
    paintMenu();
    /* Shown before it is placed: placeMenu has to measure the menu to keep it
       on screen, and a display:none menu measures zero wide.  Both happen
       before the frame is painted, so it never appears at the wrong spot. */
    menu.classList.add("open");
    placeMenu();
    button.setAttribute("aria-expanded", "true");
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("keydown", onDocumentKey);
    document.addEventListener("pointermove", keepOpen);
    keepOpen();
  }

  function closeMenu() {
    if (!menu) return;
    menu.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onDocumentClick);
    document.removeEventListener("keydown", onDocumentKey);
    document.removeEventListener("pointermove", keepOpen);
    clearTimeout(idleTimer);
    idleTimer = 0;
  }

  /* Anything that shows someone is still there restarts the countdown. */
  function keepOpen() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(closeMenu, MENU_IDLE_MS);
  }

  function onDocumentClick(event) {
    /* A click on the button is the press that opened the menu; a click inside
       it is handled by the option's own listener.  Only an outside one closes
       it. */
    if (button.contains(event.target) || menu.contains(event.target)) {
      keepOpen();
      return;
    }
    closeMenu();
  }

  function onDocumentKey(event) {
    if (event.key === "Escape") closeMenu();
    else keepOpen();
  }

  /* --- the chrome -------------------------------------------------------- */

  /* Injected rather than repeated in the markup of both pages: the button and
     its menu belong to this file, the same way the toast and the token dialog
     belong to core.js. */
  function injectChrome() {
    const bar = document.querySelector(".topbar");
    const brand = bar && bar.querySelector(".brand");
    if (!bar || !brand) return;

    button = document.createElement("button");
    button.type = "button";
    button.id = "themeToggle";
    button.className = "iconbtn";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", "themeMenu");

    /* Painted, not drawn: this key takes the film's colour under the adaptive
       theme, and an <img> cannot be given one (see .ui-icon.painted). */
    icon = document.createElement("span");
    icon.className = "ui-icon painted";
    button.append(icon);
    brand.after(button);

    menu = document.createElement("ul");
    menu.id = "themeMenu";
    menu.className = "theme-menu";
    menu.setAttribute("role", "menu");
    menu.tabIndex = -1;
    document.body.append(menu);

    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;   /* left click / primary touch only */
      longPressed = false;
      clearTimeout(pressTimer);
      pressTimer = setTimeout(() => {
        pressTimer = 0;
        longPressed = true;
        if (navigator.vibrate) navigator.vibrate(15);
        openMenu();
      }, LONG_PRESS_MS);
    });

    for (const event of ["pointerup", "pointerleave", "pointercancel"]) {
      button.addEventListener(event, () => clearTimeout(pressTimer));
    }

    button.addEventListener("click", () => {
      /* The click that follows a long press must not also cycle the theme. */
      if (longPressed) { longPressed = false; return; }
      setTheme(nextTheme());
    });

    /* A long press reads as a right-click on some desktop browsers: suppress
       the native menu, and take the chance to open ours instead. */
    button.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openMenu();
    });

    window.addEventListener("resize", () => {
      if (menu.classList.contains("open")) placeMenu();
    });

    /* The bar travels with the page rather than staying pinned to the top, so
       an open menu has to be brought along with the button it hangs from --
       fixed, it would otherwise sit still while the button scrolled out from
       under it.  Passive: this only ever reads the layout. */
    window.addEventListener("scroll", () => {
      if (menu.classList.contains("open")) placeMenu();
    }, { passive: true });

    buildMenu();
    paintButton();
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
    document.addEventListener("DOMContentLoaded", injectChrome, { once: true });
  } else {
    injectChrome();
  }

  return {
    ADAPTIVE,
    theme: readTheme,
    strength: readStrength,

    /* The localized chrome, handed over by core.js once /api/hello answers.
       Both the button's label and the menu are built from it, so both are
       made again. */
    strings(source) {
      let changed = false;
      for (const key of Object.keys(T)) {
        if (source[key] && source[key] !== T[key]) { T[key] = source[key]; changed = true; }
      }
      if (!changed || !button) return;
      buildMenu();
      paintButton();
    }
  };

})();
