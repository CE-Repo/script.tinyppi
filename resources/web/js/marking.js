// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* Details and library actions for a film, show or episode.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global continueStale, control, el, filmsStale, formatName, refreshEpisodes,
   requestContinue, requestFilms, requestSeries, runtime, seriesStale, T */
/* exported bindTitle, showDetails */

/* The currently opened title, including a details request still loading. */
let detailing = null;

/* Forget where a film or an episode got to, leaving it seen or unseen as it
   was: it leaves the row of things half-watched, and its bar leaves the wall. */
async function clearResume(body) {
  const ok = await post("/api/resume", body);
  if (ok) reread();
  return ok;
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
  const ok = await post("/api/watched", Object.assign({ watched }, body));
  if (ok) reread();
  return ok;
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

/* How far a page is pulled down from its top before it is let go of. */
const PULL_CLOSE_PX = 100;

/* A pull down from the top of a dialog closes it, the way a page is flicked
   away on a phone and the app's own pages are: the details, and a show's
   seasons.  Only from the top -- further down, the same gesture is the page
   scrolling back up. */
function pullToClose(dialog) {
  const page = dialog.querySelector("form");
  let from = null;
  dialog.addEventListener("touchstart", (event) => {
    from = page.scrollTop <= 0 ? event.touches[0].clientY : null;
  }, { passive: true });
  dialog.addEventListener("touchend", (event) => {
    const start = from;
    from = null;
    if (start !== null && event.changedTouches[0].clientY - start > PULL_CLOSE_PX) dialog.close();
  });
}

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
   playing title's, the slogan and the plot, who made it and who is in it.

   *replace* puts it in place of the details already open, in the same
   dialog -- an episode's give way to its show's (see the rows in
   js/continue.js) -- rather than being turned away as a second press is. */
async function showDetails(question, replace) {
  if (detailing && !replace) return;
  detailing = question;
  const [key] = Object.keys(question.body);
  let found;
  try {
    found = await TinyPPI.getJSON("/api/details?" + key + "=" +
                                  encodeURIComponent(question.body[key]));
  } catch (_) {
    TinyPPI.toast(T.details_failed, true);
    found = {};
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
  el.detailsFacts.replaceChildren(...TinyPPI.panels.facts(found));
  el.detailsCast.replaceChildren(...TinyPPI.panels.cast(found));
  tintDetails();
  /* Library entries expose their actions here; the currently playing title
     opened from the overview is informational. */
  question.watched = found.watched ?? !!question.watched;
  question.resumable = found.resume === undefined ? !!question.resumable : found.resume > 0;
  if (question.onPlay && key !== "tvshowid") question.play = question.resumable ? T.films_resume : T.films_play;
  el.detailsPlay.dataset.kind = key;
  el.detailsError.hidden = true;
  renderDetailsActions(question);
  el.detailsDialog.returnValue = "";
  if (!el.detailsDialog.open) el.detailsDialog.showModal();
  el.detailsDialog.querySelector("form").scrollTop = 0;
}

/* Actions are updated without rebuilding the page or moving its scroll position. */
function renderDetailsActions(question) {
  el.detailsActions.hidden = !control || !question.onPlay;
  el.detailsPlay.textContent = question.play || "";
  el.detailsRestart.hidden = !question.resumable;
  el.detailsClear.hidden = !question.resumable;
  el.detailsWatched.hidden = !!question.watched;
  el.detailsUnwatched.hidden = !question.watched;
  /* The way to the show an episode belongs to, where the question has one
     (see the rows in js/continue.js). */
  el.detailsShow.hidden = !question.onShow;
  for (const button of el.detailsActions.querySelectorAll("button")) button.disabled = !!question.busy;
}

for (const button of [el.detailsRestart, el.detailsClear, el.detailsWatched, el.detailsUnwatched]) {
  button.addEventListener("click", async () => {
    const question = detailing;
    if (!question || !question.onPlay || !control || question.busy || button.hidden) return;
    question.busy = true;
    el.detailsError.hidden = true;
    renderDetailsActions(question);
    if (button.value === "restart") {
      await question.onPlay(true);
    } else {
      const clearing = button.value === "clear";
      const watched = button.value === "watched";
      const ok = clearing ? await clearResume(question.body) : await setWatched(question.body, watched);
      if (ok) {
        if (clearing) {
          question.resumable = false;
          question.play = T.films_play;
        } else question.watched = watched;
      } else if (detailing === question) {
        el.detailsError.textContent = T.mark_failed;
        el.detailsError.hidden = false;
      }
    }
    question.busy = false;
    if (detailing === question) renderDetailsActions(question);
  });
}

/* The episode's show: its details in place of the episode's, on the series
   tab. */
el.detailsShow.addEventListener("click", () => {
  const question = detailing;
  if (question && question.onShow && !question.busy) question.onShow();
});

/* On the adaptive theme the page takes its accent from the title's own
   picture -- its poster, or an episode's still -- rather than from what is
   playing (see accent in js/cover-tint.js); a title without a colour wears
   the theme's own. */
function tintDetails() {
  const dialog = el.detailsDialog;
  dialog.classList.remove("tinted");
  dialog.style.removeProperty("--cover-accent-rgb");
  const picture = [el.detailsPoster, el.detailsBackdrop].find((image) => !image.hidden);
  const cover = window.TinyPPICover;
  if (!picture || !cover) return;
  const url = picture.getAttribute("src");
  cover.accent(url, picture).then((rgb) => {
    if (!rgb || picture.getAttribute("src") !== url) return;
    dialog.style.setProperty("--cover-accent-rgb", rgb.join(", "));
    dialog.classList.add("tinted");
  });
}

/* The overview card on the live tab opens the playing title's details (see
   renderPlot in js/live-panels.js). */
TinyPPI.openDetails = (item) =>
  showDetails({ title: item.title, body: { [item.kind + "id"]: item.id } });

pullToClose(el.detailsDialog);
pullToClose(el.seasonsDialog);

el.detailsDialog.querySelector("form").addEventListener("scroll", () => {
  for (const tip of el.detailsRatings.querySelectorAll(".rating-tip")) tip.hidePopover();
});

el.detailsDialog.addEventListener("close", () => {
  const answer = el.detailsDialog.returnValue;
  const question = detailing;
  detailing = null;
  if (!question || !question.onPlay || !control) return;
  if (answer === "play") question.onPlay(false);
});

/* Every way of opening a title leads to its details and actions. */
function bindTitle(tile, question) {
  let timer = null;
  let held = false;
  let start = null;
  const cancel = () => { clearTimeout(timer); timer = null; };
  tile.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    held = false;
    start = [event.clientX, event.clientY];
    timer = setTimeout(() => { held = true; showDetails(question); }, 500);
  });
  tile.addEventListener("pointermove", (event) => {
    if (start && Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 10) cancel();
  });
  for (const name of ["pointerup", "pointercancel", "pointerleave"]) tile.addEventListener(name, cancel);
  tile.addEventListener("contextmenu", (event) => { event.preventDefault(); cancel(); held = true; showDetails(question); });
  tile.addEventListener("click", () => {
    cancel();
    if (!held) showDetails(question);
    held = false;
  });
}
