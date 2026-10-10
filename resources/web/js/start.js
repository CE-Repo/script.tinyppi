// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* Starts the page: the localized strings, the first tab, and the stream.
   Loaded last, once every other part of the page is defined.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global $, el, offerShelves, render, selectTab, storedTab, tabFromAddress */

/* --- boot --------------------------------------------------------------- */

function applyStrings(strings, hello) {
  $("idleTitle").textContent = strings.idle_title;
  $("idleText").textContent = strings.idle_text;
  $("lastLabel").textContent = strings.last_played;
  /* The same words as the idle card on the live tab: the history is empty for
     exactly as long as nothing has played. */
  $("historyIdleTitle").textContent = strings.events_empty;
  $("historyIdleText").textContent = strings.idle_text;
  $("continueFilmsLabel").textContent = strings.continue;
  $("continueSeriesLabel").textContent = strings.continue;
  /* The bar is icons alone; each key says what it is to a screen reader and
     under a pointer. */
  const names = {
    live: strings.tab_live, metadata: strings.tab_metadata,
    films: strings.films, series: strings.series,
    history: strings.tab_history, settings: strings.tab_settings
  };
  for (const button of el.tabBar.querySelectorAll(".tab")) {
    const name = names[button.dataset.tab] || "";
    button.setAttribute("aria-label", name);
    button.title = name;
  }
  $("themeHead").textContent = strings.theme_menu;
  $("tokenHead").textContent = strings.token_title;
  $("tokenNote").textContent = strings.token_text;
  $("tokenBtnText").textContent = strings.token_enter;
  $("reportHead").textContent = strings.copy;
  $("copyBtnText").textContent = strings.report_live;
  $("copyMetaBtnText").textContent = strings.tab_metadata;
  $("filmsLabel").textContent = strings.films;
  el.filmsEmpty.textContent = strings.films_empty;
  el.filmSearch.placeholder = strings.films_search;
  el.filmSearch.setAttribute("aria-label", strings.films_search);
  for (const cross of [el.filmSearchClear, el.seriesSearchClear]) {
    cross.setAttribute("aria-label", strings.search_clear);
    cross.title = strings.search_clear;
  }
  $("seriesLabel").textContent = strings.series;
  $("unseenFilmsLabel").textContent = strings.films_unseen;
  $("recentFilmsLabel").textContent = strings.recent;
  $("recentSeriesLabel").textContent = strings.recent;
  $("unseenSeriesLabel").textContent = strings.series_unseen_shows;
  el.markRestart.textContent = strings.play_from_start;
  el.markClear.textContent = strings.resume_clear;
  el.markWatched.textContent = strings.mark_watched;
  el.markUnwatched.textContent = strings.mark_unwatched;
  el.markCancel.textContent = strings.cancel;
  $("seriesBackText").textContent = strings.series_back;
  el.seriesBack.setAttribute("aria-label", strings.series_back);
  el.seriesEmpty.textContent = strings.series_empty;
  el.seriesSearch.placeholder = strings.series_search;
  el.seriesSearch.setAttribute("aria-label", strings.series_search);
  TinyPPI.panels.strings(strings);
  TinyPPI.metadata.strings(strings);
  $("vs10Title").textContent = strings.vs10;
  $("vs10OutLabel").textContent = strings.output;
  if (hello) {
    el.version.textContent = "v" + hello.version;
    offerShelves(hello);
  }
}

/* The tab to open on: the one the address names, else the one this device
   was last left on, else what is playing. */
selectTab(tabFromAddress() || storedTab() || "live");
TinyPPI.boot({ onState: render, onStrings: applyStrings });
