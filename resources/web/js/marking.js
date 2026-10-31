// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* Details and library actions for a film, show or episode.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global continueStale, control, el, filmQuestion, filmsStale, formatName, openShowDetails,
   refreshEpisodes, requestContinue, requestFilms, requestSeries, runtime, seriesStale,
   showQuestion, T */
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
/* How many details reads are out.  The box may wait a few seconds on
   MDBList, WhatsOn and TMDb before it answers (see web/library/details.py),
   and the page says it is on its way rather than sitting still (see
   .detailsloading in css/dashboard.css). */
let detailsLoading = 0;

/* Keep what a details read answered, letting go of the answers too old to be
   drawn again, so a long visit does not hold every title it ever opened. */
function keepDetails(address, found) {
  const now = Date.now();
  for (const [held, kept] of detailsRead) {
    if (now - kept.at >= DETAILS_KEEP_MS) detailsRead.delete(held);
  }
  detailsRead.set(address, { found, at: now });
}

function waitingForDetails(by) {
  detailsLoading += by;
  document.documentElement.classList.toggle("detailsloading", detailsLoading > 0);
}

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

/* How long a page takes to slide in or out, or to turn to the next (see
   .away and .turning in css/dashboard.css) -- as long as the app's take. */
const SLIDE_MS = 380;
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
   pictures by that id, or "" where it has none.  Without an id, the playing
   title's (see showSnapshotDetails). */
function detailsArt(body, kind, tag) {
  if (!tag) return "";
  const [key] = Object.keys(body);
  const named = key ? "&" + key + "=" + encodeURIComponent(body[key]) : "";
  return "/api/art?kind=" + kind + named + "&v=" + encodeURIComponent(tag);
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
async function showDetails(question, replace, turn) {
  /* A show's page under its seasons (see stays) gives way to an episode's. */
  if (detailing && !replace && !detailing.stays) return;
  clearTimeout(sliding.get(el.detailsDialog));
  sliding.delete(el.detailsDialog);
  el.detailsDialog.classList.remove("away");
  detailing = question;
  const [key] = Object.keys(question.body);
  const address = "/api/details?" + key + "=" + encodeURIComponent(question.body[key]);
  const kept = detailsRead.get(address);
  let found = question.found ||
    (kept && Date.now() - kept.at < DETAILS_KEEP_MS ? kept.found : null);
  if (!found) {
    waitingForDetails(1);
    try {
      found = await TinyPPI.getJSON(address);
      keepDetails(address, found);
    } catch (_) {
      TinyPPI.toast(T.details_failed, true);
      found = {};
    } finally {
      waitingForDetails(-1);
    }
  }
  if (detailing !== question) return;
  if (turn) turnPage(turn);
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
  el.detailsRatings.replaceChildren(...TinyPPI.panels.ratingGroups(found));
  el.detailsDescriptionTitle.textContent = T.description;
  el.detailsDescription.hidden = !(found.tagline || found.plot);
  el.detailsTagline.textContent = found.tagline || "";
  el.detailsPlot.textContent = found.plot || "";
  el.detailsFacts.replaceChildren(...TinyPPI.panels.facts(found));
  el.detailsCast.replaceChildren(...TinyPPI.panels.cast(found));
  el.detailsRelated.replaceChildren(...TinyPPI.panels.related(found, openRelated));
  tintDialog(el.detailsDialog, [el.detailsPoster, el.detailsBackdrop]);
  /* Library entries expose their actions here; the currently playing title
     opened from the overview is informational. */
  question.watched = found.watched ?? !!question.watched;
  question.resumable = found.resume === undefined ? !!question.resumable : found.resume > 0;
  if (question.onPlay && key !== "tvshowid") question.play = question.resumable ? T.films_resume : T.films_play;
  el.detailsPlay.dataset.kind = key || "";
  el.detailsError.hidden = true;
  renderDetailsActions(question);
  el.detailsDialog.returnValue = "";
  /* Open under a show's seasons, the page is shut and shown again, which is
     what puts it in front of them (see the close below, which lets that
     pass). */
  if (el.detailsDialog.open && !replace) el.detailsDialog.close();
  if (!el.detailsDialog.open) slideIn(el.detailsDialog);
  /* A page gone back to is where it was left; any other starts at its top. */
  el.detailsDialog.querySelector("form").scrollTop = turn === "back" ? question.scroll || 0 : 0;
}

/* The page turning away, while one title's page gives way to another's. */
let turning = null;

/* One title's page turning to another's, as the app's pages do: going
   *forward* -- to a title the page leads on to -- the new page slides in
   from the side over the old one, which moves a quarter of the way and
   dims; going *back*, the page on top slides away over the one under it.
   The old page is a copy left standing over the dialog for the turn (see
   .pageghost in css/dashboard.css), at the place it was scrolled to, while
   the dialog itself already holds the new one. */
function turnPage(direction) {
  endTurn();
  const form = el.detailsDialog.querySelector("form");
  const ghost = form.cloneNode(true);
  for (const node of [ghost, ...ghost.querySelectorAll("[id]")]) node.removeAttribute("id");
  ghost.classList.add("pageghost");
  ghost.inert = true;
  ghost.setAttribute("aria-hidden", "true");
  el.detailsDialog.append(ghost);
  ghost.scrollTop = form.scrollTop;
  el.detailsDialog.classList.add("turning", "turn" + direction);
  turning = { ghost, timer: setTimeout(endTurn, SLIDE_MS) };
}

function endTurn() {
  if (!turning) return;
  clearTimeout(turning.timer);
  turning.ghost.remove();
  el.detailsDialog.classList.remove("turning", "turnforward", "turnback");
  turning = null;
}

/* A title of the library another title's page leads on to (see related in
   js/live-panels.js): its own page in place of this one, with the actions
   its shelf gives it -- a show's on the series tab, where its seasons open
   (see openShowDetails) -- or, where its shelf has not been drawn, its page
   alone. */
function openRelated(item) {
  /* Where the page was scrolled to, for coming back to it. */
  detailing.scroll = el.detailsDialog.querySelector("form").scrollTop;
  detailsTrail.push(detailing);
  if (item.kind === "tvshow" && showQuestion(item.id)) {
    openShowDetails(item.id, "forward");
    return;
  }
  const key = item.kind === "tvshow" ? "tvshowid" : "movieid";
  const question = key === "movieid" ? filmQuestion(item.id) : undefined;
  showDetails(question || { title: item.title, body: { [key]: item.id } }, true, "forward");
}

/* The pages the open page was led on to from (see openRelated), the last on
   top, so leaving a page led on to goes back to the one before it rather
   than closing the details; let go of once they close. */
const detailsTrail = [];

/* Back, Escape or the close key: the page the open one was led on to from,
   as it was, with its keys; on the first page, the details slide away. */
function leaveDetails() {
  const previous = detailsTrail.pop();
  if (previous) showDetails(previous, true, "back");
  else slideOut(el.detailsDialog);
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
  showDetails({ title: item.title, body: { [item.kind + "id"]: item.id }, playing: item.playing });

/* The details of a playing title the box hands out none for -- a broadcast,
   a file the library does not know -- drawn from what the snapshot says of
   it, with nothing to ask: the plot, the ratings and the credits, each of
   the cast with who they played, under the playing title's own pictures.
   No keys under the heading: it is already playing. */
function showSnapshotDetails({ title, media, art, playing }) {
  const roles = media.roles || [];
  const found = Object.assign({}, media, {
    cast: (media.cast || []).map((name, index) => ({ name, role: roles[index] || "" })),
    poster: art.poster || "", fanart: art.fanart || ""
  });
  showDetails({ title, body: {}, found, playing });
}
TinyPPI.openSnapshotDetails = showSnapshotDetails;

/* The playing title's details, opened from the overview card, go once it is
   no longer playing: stopped, or another title started in its place.
   Details opened from a shelf carry no *playing* and are left alone; a page
   still being read is let go of, so it never opens (see showDetails). */
TinyPPI.notePlaying = (snapshot) => {
  const question = detailing;
  if (!question || !question.playing) return;
  if (TinyPPI.panels.playingKey(snapshot) === question.playing) return;
  if (el.detailsDialog.open) slideOut(el.detailsDialog);
  else detailing = null;
};

/* Every way a reader leaves a page slides it out: its key, Escape and the
   phone's back gesture (the dialog's cancel), and
   -- on a desktop, where the page stands in the middle of the screen -- a
   click beside it.  The first three, on a title's page led on to from
   another, go back to that one instead (see leaveDetails); a click beside
   the page closes it, whatever it was led on to from. */
for (const [dialog, key, leave] of [[el.detailsDialog, el.detailsX, leaveDetails],
                                    [el.seasonsDialog, el.seasonsX, () => slideOut(el.seasonsDialog)]]) {
  key.addEventListener("click", (event) => {
    event.preventDefault();
    leave();
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    leave();
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
  detailsTrail.length = 0;
  endTurn();
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
