// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* Details and library actions for a film, show or episode.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global continueStale, control, el, filmsStale, formatName, refreshEpisodes,
   requestContinue, requestFilms, requestSeries, runtime, seriesStale, T */
/* exported bindTitle, showDetails, slideIn, tintDialog */

/* The currently opened title, including a details request still loading. */
let detailing = null;
/* What the library said about each title asked about lately, by its
   address, so a page gone back to is drawn at once rather than after the box
   answers again.  Only for a minute: the ratings MDBList and WhatsOn were too
   slow to give the first time are in the answer after that (see
   web/library/details.py), and a page kept for longer would never show them.
   Forgotten at once whenever the library is written to (see reread). */
const detailsRead = new Map();
const DETAILS_KEEP_MS = 60000;

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
  detailsRead.clear();
  filmsStale();
  seriesStale();
  continueStale();
  requestFilms(true);
  requestSeries(true);
  requestContinue(true);
  refreshEpisodes();
}

/* --- a title's details ---------------------------------------------------- */

/* How long a page takes to slide in or out (see .away in css/dashboard.css). */
const SLIDE_MS = 250;
/* The pages sliding out, each with the timer it closes on. */
const sliding = new Map();

/* A page -- a title's details, a show's seasons -- slides in from the side
   as it opens and back out as it is left, the way one page of the app gives
   way to the next.  Laid out off to the side first, so taking the mark away
   slides it in rather than putting it straight where it ends. */
function slideIn(dialog) {
  /* One shown again while it was still sliding out stays. */
  clearTimeout(sliding.get(dialog));
  sliding.delete(dialog);
  if (!dialog.open) {
    dialog.classList.add("away");
    dialog.showModal();
    dialog.getBoundingClientRect();
  }
  dialog.classList.remove("away");
}

function slideOut(dialog) {
  if (sliding.has(dialog)) return;
  dialog.classList.add("away");
  sliding.set(dialog, setTimeout(() => {
    sliding.delete(dialog);
    dialog.close();
    dialog.classList.remove("away");
  }, SLIDE_MS));
}

/* How far a page is pulled down from its top before it is let go of. */
const PULL_CLOSE_PX = 100;

/* A pull down from the top of a dialog closes it, the way a page is flicked
   away on a phone and the app's own pages are: the details, and a show's
   seasons.  Only from the top -- further down, the same gesture is the page
   scrolling back up. */
function pullToClose(dialog, leave) {
  const page = dialog.querySelector("form");
  let from = null;
  dialog.addEventListener("touchstart", (event) => {
    from = page.scrollTop <= 0 ? event.touches[0].clientY : null;
  }, { passive: true });
  dialog.addEventListener("touchend", (event) => {
    const start = from;
    from = null;
    if (start !== null && event.changedTouches[0].clientY - start > PULL_CLOSE_PX) leave();
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
  /* A show's page under its seasons (see stays) gives way to an episode's. */
  if (detailing && !replace && !detailing.stays) return;
  clearTimeout(sliding.get(el.detailsDialog));
  sliding.delete(el.detailsDialog);
  el.detailsDialog.classList.remove("away");
  detailing = question;
  const [key] = Object.keys(question.body);
  const address = "/api/details?" + key + "=" + encodeURIComponent(question.body[key]);
  const kept = detailsRead.get(address);
  let found = kept && Date.now() - kept.at < DETAILS_KEEP_MS ? kept.found : null;
  if (!found) {
    try {
      found = await TinyPPI.getJSON(address);
      detailsRead.set(address, { found, at: Date.now() });
    } catch (_) {
      TinyPPI.toast(T.details_failed, true);
      found = {};
    }
  }
  if (detailing !== question) return;
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
  tintDialog(el.detailsDialog, [el.detailsPoster, el.detailsBackdrop]);
  /* Library entries expose their actions here; the currently playing title
     opened from the overview is informational. */
  question.watched = found.watched ?? !!question.watched;
  question.resumable = found.resume === undefined ? !!question.resumable : found.resume > 0;
  if (question.onPlay && key !== "tvshowid") question.play = question.resumable ? T.films_resume : T.films_play;
  el.detailsPlay.dataset.kind = key;
  el.detailsError.hidden = true;
  renderDetailsActions(question);
  el.detailsDialog.returnValue = "";
  /* Open under a show's seasons, the page is shut and shown again, which is
     what puts it in front of them (see the close below, which lets that
     pass). */
  if (el.detailsDialog.open && !replace) el.detailsDialog.close();
  if (!el.detailsDialog.open) slideIn(el.detailsDialog);
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
      el.detailsDialog.close();
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
   the theme's own.  *dialog* is the page, *pictures* what it may be read
   off, first choice first: the details, and a show's seasons. */
function tintDialog(dialog, pictures) {
  dialog.classList.remove("tinted");
  dialog.style.removeProperty("--cover-accent-rgb");
  const picture = pictures.find((image) => !image.hidden);
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

/* Every way a reader leaves a page slides it out: its key, Escape and the
   phone's back gesture (the dialog's cancel), and
   -- on a desktop, where the page stands in the middle of the screen -- a
   click beside it. */
for (const [dialog, key] of [[el.detailsDialog, el.detailsX], [el.seasonsDialog, el.seasonsX]]) {
  key.addEventListener("click", (event) => {
    event.preventDefault();
    slideOut(dialog);
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    slideOut(dialog);
  });
  /* Only a press that began beside the page as well: a row of cards
     dragged until the pointer is let go out there is no click beside it. */
  let pressedBeside = false;
  dialog.addEventListener("pointerdown", (event) => { pressedBeside = event.target === dialog; });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && pressedBeside) slideOut(dialog);
  });
  if (dialog === el.seasonsDialog) pullToClose(dialog, () => slideOut(dialog));
}

el.detailsDialog.querySelector("form").addEventListener("scroll", () => {
  for (const tip of el.detailsRatings.querySelectorAll(".rating-tip")) tip.hidePopover();
});

/* A question that *stays* -- a show's, whose seasons open over its page --
   is answered without the page being put away, so leaving the seasons finds
   it where it was. */
el.detailsPlay.addEventListener("click", (event) => {
  const question = detailing;
  if (!question || !question.stays || question.busy) return;
  event.preventDefault();
  question.onPlay(false);
});

el.detailsDialog.addEventListener("close", () => {
  /* Shut only to be shown again in front (see showDetails): nothing was
     answered. */
  if (el.detailsDialog.open) return;
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
