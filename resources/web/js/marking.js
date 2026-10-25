// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The question a press on a film, show or episode asks: play, play from
   the start, mark as watched or unwatched, or show its details.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global continueStale, control, el, filmsStale, formatName, refreshEpisodes,
   requestContinue, requestFilms, requestSeries, runtime, seriesStale, T */
/* exported ask */

/* --- what a press asks ---------------------------------------------------- */

/* A press on a film, a series or an episode asks what is wanted of it: to
   play it (or, for a series, to open it -- a series is not a thing that can
   be played), or to have the box count it as seen or as unseen.  The last two
   are written into Kodi's own library (see ``set_watched`` in
   web/library.py); a series marked either way is every episode of it.

   Written and then read back rather than drawn here: the box drops what it
   holds the moment it has written, and the walls, the row and the open show
   are read again, so what they show is what the library now says. */

let asking = null;         /* what the open question is about              */

function ask(question) {
  if (!control || el.markDialog.open) return;
  asking = question;
  el.markTitle.textContent = question.title;
  el.markPlay.textContent = question.play;
  /* From the beginning, and forgetting where it got to, are answers only for
     a title that has got somewhere. */
  el.markRestart.hidden = !question.resumable;
  el.markClear.hidden = !question.resumable;
  el.markDialog.returnValue = "";
  el.markDialog.showModal();
}

el.markDialog.addEventListener("close", () => {
  const answer = el.markDialog.returnValue;
  const question = asking;
  asking = null;
  if (!question) return;
  if (answer === "play") question.onPlay(false);
  else if (answer === "restart") question.onPlay(true);
  else if (answer === "clear") clearResume(question.body);
  else if (answer === "details") showDetails(question);
  else if (answer === "watched" || answer === "unwatched") {
    setWatched(question.body, answer === "watched");
  }
});

/* Forget where a film or an episode got to, leaving it seen or unseen as it
   was: it leaves the row of things half-watched, and its bar leaves the wall. */
async function clearResume(body) {
  if (await post("/api/resume", body)) reread();
}

/* One of the library writes, answering whether the box took it and saying so
   where it did not. */
async function post(route, body) {
  try {
    const response = await fetch(route, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify(body)
    });
    if (response.status === 401) {
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
      return false;
    }
    if (!response.ok) {
      TinyPPI.toast(T.mark_failed, true);
      return false;
    }
    return true;
  } catch (_) {
    TinyPPI.toast(T.mark_failed, true);
    return false;
  }
}

async function setWatched(body, watched) {
  if (await post("/api/watched", Object.assign({ watched }, body))) reread();
}

/* Read everything the write may have moved, at once rather than on the next
   version the snapshot carries: the box has already dropped what it held, and
   the answer somebody just asked for should not wait on the producer's
   cadence to appear. */
function reread() {
  filmsStale();
  seriesStale();
  continueStale();
  requestFilms(true);
  requestSeries(true);
  requestContinue(true);
  refreshEpisodes();
}

/* --- a title's details ---------------------------------------------------- */

/* What the rating services are called, as the overview card names them;
   any other source an NFO brings is shown under its own name. */
const SOURCE_NAMES = {
  imdb: "IMDb", tmdb: "TMDb", trakt: "Trakt", tvdb: "TVDB", letterboxd: "Letterboxd",
  metacritic: "Metacritic", metacriticuser: "Metacritic", rottentomatoes: "Rotten Tomatoes",
  popcorn: "Popcornmeter", rogerebert: "Roger Ebert", myanimelist: "MyAnimeList",
  mdblist: "MDBList"
};

/* Everything the library holds about one title, read when it is asked for
   (see web/library/details.py) and drawn as text: the plot, the people and
   the ratings, which the walls have no room for. */
async function showDetails(question) {
  const [key] = Object.keys(question.body);
  let found;
  try {
    found = await TinyPPI.getJSON("/api/details?" + key + "=" +
                                  encodeURIComponent(question.body[key]));
  } catch (_) {
    TinyPPI.toast(T.details_failed, true);
    return;
  }
  el.detailsTitle.textContent = question.title;
  el.detailsMeta.textContent = [found.year ? String(found.year) : "", runtime(found.duration),
                                found.mpaa || ""].filter(Boolean).join(" \u00b7 ");
  const formats = document.createDocumentFragment();
  for (const name of ["video", "resolution", "audio"]) {
    if (!found[name]) continue;
    const chip = document.createElement("span");
    chip.className = "format";
    chip.textContent = name === "video" && found.dv_profile
      ? formatName("video", "dv/" + found.dv_profile) : formatName(name, found[name]);
    formats.append(chip);
  }
  el.detailsFormats.replaceChildren(formats);
  el.detailsTagline.textContent = found.tagline || "";
  el.detailsPlot.textContent = found.plot || "";
  el.detailsFacts.replaceChildren(...facts(found));
  el.detailsDialog.showModal();
}

/* The rows under the plot, each a heading and its names, left out where the
   library has nothing for it. */
function facts(found) {
  const cast = (found.cast || []).map((person) =>
    person.role ? person.name + " (" + person.role + ")" : person.name);
  if (found.cast_more) cast.push("\u2026");
  const ratings = (found.ratings || []).map((entry) =>
    (SOURCE_NAMES[entry.source] || entry.source) + " " + entry.rating.toFixed(1));
  if (found.userrating) ratings.push(T.my_rating + " " + found.userrating);
  if (found.top250) ratings.push(T.top250.replace("%s", found.top250));
  const rows = [
    [T.genre, found.genres], [T.director, found.directors], [T.writer, found.writers],
    [T.studio, found.studios], [T.ratings, ratings], [T.cast, cast]
  ];
  const nodes = [];
  for (const [heading, names] of rows) {
    if (!names || !names.length) continue;
    const term = document.createElement("dt");
    term.textContent = heading;
    const value = document.createElement("dd");
    value.textContent = names.join(", ");
    nodes.push(term, value);
  }
  return nodes;
}
