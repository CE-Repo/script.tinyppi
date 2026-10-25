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

/* The id a details request named, and the address of one of the title's
   pictures by that id, or "" where it has none. */
function detailsArt(body, kind, tag) {
  if (!tag) return "";
  const [key] = Object.keys(body);
  return "/api/art?kind=" + kind + "&" + key + "=" + encodeURIComponent(body[key]) +
    "&v=" + encodeURIComponent(tag);
}

/* A picture of the details, or none: a picture the box cannot read leaves
   the space it would have filled, as a missing one does. */
function showPicture(image, url) {
  image.hidden = !url;
  if (url) image.src = url;
  else image.removeAttribute("src");
  image.onerror = () => {
    image.hidden = true;
    el.detailsHero.classList.toggle("bare", el.detailsBackdrop.hidden);
  };
}

/* Everything the library holds about one title, read when it is asked for
   (see web/library/details.py): under its backdrop -- a film's or a show's
   fanart, an episode's still -- the poster, the title and how long it runs
   with the file's formats; then the ratings, as the overview card draws the
   playing title's, the slogan and the plot, who made it and who is in it. */
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
  showPicture(el.detailsBackdrop,
              detailsArt(question.body, found.fanart ? "fanart" : "thumb",
                         found.fanart || found.thumb));
  showPicture(el.detailsPoster, detailsArt(question.body, "poster", found.poster));
  el.detailsHero.classList.toggle("bare", el.detailsBackdrop.hidden);
  el.detailsTitle.textContent = question.title;
  el.detailsMeta.textContent = [found.year ? String(found.year) : "", runtime(found.duration)]
    .filter(Boolean).join(" \u00b7 ");
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
  el.detailsRatings.replaceChildren(...TinyPPI.panels.shields(found));
  el.detailsTagline.textContent = found.tagline || "";
  el.detailsPlot.textContent = found.plot || "";
  el.detailsFacts.replaceChildren(...facts(found));
  el.detailsCast.replaceChildren(...castNodes(found));
  el.detailsDialog.showModal();
  el.detailsDialog.querySelector("form").scrollTop = 0;
}

/* The rows under the plot, each a heading and its names, left out where the
   library has nothing for it. */
function facts(found) {
  const rows = [
    [T.genre, found.genres], [T.director, found.directors], [T.writer, found.writers],
    [T.studio, found.studios]
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

/* The cast, under its heading: each a card of the name and, quieter under
   it, who they played; an ellipsis where the library holds more. */
function castNodes(found) {
  const cast = found.cast || [];
  if (!cast.length) return [];
  const heading = document.createElement("li");
  heading.className = "detailscasthead";
  heading.textContent = T.cast;
  const nodes = [heading];
  for (const person of cast) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = person.name;
    item.append(name);
    if (person.role) {
      const role = document.createElement("span");
      role.textContent = person.role;
      item.append(role);
    }
    nodes.push(item);
  }
  if (found.cast_more) {
    const more = document.createElement("li");
    more.className = "more";
    more.textContent = "\u2026";
    nodes.push(more);
  }
  return nodes;
}
