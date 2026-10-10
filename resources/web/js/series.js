// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The series library tab: the shelf of shows, one show's seasons and
   episodes, and starting an episode.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global ask, continueStale, el, FILMS_RETRY_MS, FILMS_START_MS, newest,
   ratingBadge, runtime, T */
/* exported episodeCode, episodeReleasing, hideSeries, refreshEpisodes,
   releaseSeries, requestSeries, seriesOffered, seriesStale, startingEpisode */

/* --- the series library -------------------------------------------------- */

/* The same shelf as the films, with one floor more.

   A series is not a thing that can be put on -- an episode is -- so a press on
   a poster does not start anything: the wall gives way to that show's
   episodes, and a press on one of those starts it.  The way back out is a
   button at the top of the card, where it is one press away however far down
   a forty-episode show somebody has scrolled.

   The episodes of a show are asked for when the show is opened and not before.
   A house with ninety series in it would otherwise be sent every episode of
   all of them to draw a wall of ninety posters, and it is the wall that is
   being looked at. */

let shows = [];            /* what the box last said its shelf holds      */
let seriesTag = "";        /* that list's own tag, unchanged lists skipped */
let seriesBusy = false;    /* a request for the shelf is in flight        */
let seriesRead = false;    /* the shelf has been read at least once       */
let seriesOffered = true;  /* until the box says it offers no series      */
let seriesNextTry = 0;     /* not before this, after a failure            */
let openShow = null;       /* the show whose episodes are on the card     */
let episodesBusy = false;  /* a request for one show's episodes           */
let startingEpisode = 0;   /* the episode a press is waiting on           */
let episodeReleasing = 0;  /* the timer that gives the list back          */

/* Called from the other parts of the page once the series shelf may have moved: the
   next request reads it again. */
function seriesStale() {
  seriesRead = false;
}

function requestSeries(force) {
  if (seriesBusy || !seriesOffered) return;
  if (startingEpisode) return;   /* as above, for the episode being waited on */
  if (!force && seriesRead) return;
  if (Date.now() < seriesNextTry) return;
  seriesBusy = true;
  loadSeries().finally(() => { seriesBusy = false; });
}

async function loadSeries() {
  try {
    const answer = await TinyPPI.getJSON("/api/series");
    seriesRead = true;
    seriesNextTry = 0;
    const list = Array.isArray(answer.shows) ? answer.shows : [];
    if (!el.seriesGrid.children.length || (answer.tag || "") !== seriesTag) {
      seriesTag = answer.tag || "";
      shows = list;
      buildSeries();
    }
    el.seriesCard.classList.remove("hidden");
    el.recentSeriesCard.classList.toggle("hidden",
                                         !el.recentSeriesRow.children.length);
    el.unseenSeriesCard.classList.toggle("hidden",
                                         !el.unseenSeriesGrid.children.length);
    /* Away only inside a show, where there is no wall to narrow. */
    el.seriesBox.classList.toggle("hidden", openShow !== null);
  } catch (error) {
    seriesNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: no series on offer -- switched off in the add-on's settings, or a
       box that will not be told what to play.  A settled answer rather than a
       failure, so it is not asked again. */
    if (String((error || {}).message) === "403") seriesOffered = false;
    if (!seriesRead) hideSeries();
  }
}

function buildSeries() {
  const wall = document.createDocumentFragment();
  const unseen = document.createDocumentFragment();
  let waiting = 0;
  for (const show of shows) {
    wall.append(showTile(show, openShowView));
    /* A show with an episode still waiting.  One the library has no episode
       count for is left off: nothing says there is anything in it to see. */
    if (!show.watched && show.unseen) {
      unseen.append(showTile(show, openFromUnseen));
      waiting += 1;
    }
  }
  el.seriesGrid.replaceChildren(wall);
  el.unseenSeriesGrid.replaceChildren(unseen);
  el.unseenSeriesGrid.scrollLeft = 0;
  /* A show on this row is one that gained an episode lately (a show's date is
     its newest episode's, see _SHOW_PROPERTIES in web/library.py); it opens
     in the series card, the way one on the unwatched wall does. */
  const recent = document.createDocumentFragment();
  for (const show of newest(shows)) recent.append(showTile(show, openFromUnseen));
  el.recentSeriesRow.replaceChildren(recent);
  el.recentSeriesRow.scrollLeft = 0;
  el.unseenSeriesCount.textContent = waiting ? String(waiting) : "";
  /* The count in the heading, and whatever the search box is narrowing it
     to, the way the film wall does after it is built.  Inside a show the
     heading counts that show's episodes instead, and is left alone. */
  applySeriesSearch();
  /* A shelf that has just been read again is a shelf that may no longer hold
     the show somebody was inside, and where it does not the card comes back to
     the wall.  Where it does, they are left where they were: the shelf is read
     again every time an episode ends now, and a card that threw whoever was
     watching a series back out to the wall each time would be a card nobody
     could watch a series from. */
  if (!openShow) return;
  const still = shows.find((show) => show.id === openShow.id);
  if (!still) {
    closeShow();
    return;
  }
  /* The tile it was opened from has been built again, so what the card's
     heading names is the show as the shelf now has it. */
  openShow = still;
  el.seriesOpen.textContent = still.title;
}

/* Both series walls off the page, for a box with no series to offer. */
function hideSeries() {
  el.seriesCard.classList.add("hidden");
  el.recentSeriesCard.classList.add("hidden");
  el.unseenSeriesCard.classList.add("hidden");
}

/* A show opened from the wall of unwatched ones opens in the series card
   further down the same tab, where its episodes are listed -- one list of
   episodes on the page, and one way back out of it -- and that card is
   unfolded and brought into view, because the press happened somewhere
   else. */
async function openFromUnseen(show) {
  await openShowView(show);
  if (!openShow || openShow.id !== show.id) return;
  el.seriesCard.open = true;
  el.seriesCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showTile(show, onOpen) {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "film";
  tile.dataset.key = (show.title + " " + (show.year || "")).toLowerCase();

  const frame = document.createElement("div");
  frame.className = "filmposter";
  if (show.poster) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = "";
    image.src = TinyPPI.withToken(
      "/api/art?kind=poster&tvshowid=" + encodeURIComponent(show.id) +
      "&v=" + encodeURIComponent(show.poster));
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  const rated = ratingBadge(show);
  if (rated) frame.append(rated);
  if (show.watched) {
    const seen = document.createElement("span");
    seen.className = "filmseen";
    seen.setAttribute("role", "img");
    seen.setAttribute("aria-label", T.films_watched);
    seen.title = T.films_watched;
    frame.append(seen);
  } else if (show.unseen) {
    /* How many episodes are still waiting, in the corner a watched film wears
       its tick in.  The one number a shelf of series is scanned for: what
       there is left to see, rather than how long the show is. */
    const waiting = document.createElement("span");
    waiting.className = "seriesnew";
    waiting.textContent = String(show.unseen);
    waiting.setAttribute("role", "img");
    waiting.setAttribute("aria-label", show.unseen + " " + T.series_unseen);
    waiting.title = T.series_unseen;
    frame.append(waiting);
  }

  const title = document.createElement("div");
  title.className = "filmtitle";
  title.textContent = show.title;
  tile.append(frame, title);
  if (show.year) {
    const year = document.createElement("div");
    year.className = "filmyear";
    year.textContent = String(show.year);
    tile.append(year);
  }

  /* A series is not a thing that can be played, so the first answer opens it
     instead: its episodes are what can be. */
  tile.addEventListener("click", () => ask({
    title: show.title, body: { tvshowid: show.id },
    play: T.series_open, onPlay: () => onOpen(show)
  }));
  return tile;
}

function applySeriesSearch() {
  const needle = el.seriesSearch.value.trim().toLowerCase();
  let shown = 0;
  for (const tile of el.seriesGrid.children) {
    const match = !needle || tile.dataset.key.includes(needle);
    tile.hidden = !match;
    if (match) shown += 1;
  }
  el.seriesSearchClear.classList.toggle("hidden", el.seriesSearch.value === "");
  if (openShow === null) {
    el.seriesCount.textContent = shown === shows.length
      ? String(shows.length) : shown + " / " + shows.length;
    el.seriesEmpty.classList.toggle("hidden", shown > 0);
  }
}

/* --- one show ------------------------------------------------------------ */

async function openShowView(show) {
  if (episodesBusy || startingEpisode) return;
  episodesBusy = true;
  try {
    const answer = await TinyPPI.getJSON(
      "/api/episodes?tvshowid=" + encodeURIComponent(show.id));
    openShow = show;
    buildEpisodes(Array.isArray(answer.episodes) ? answer.episodes : []);
    el.seriesGrid.classList.add("hidden");
    el.seriesSearch.classList.add("hidden");
    el.episodeList.classList.remove("hidden");
    el.seriesBack.classList.remove("hidden");
    el.seriesOpen.classList.remove("hidden");
    el.seriesOpen.textContent = show.title;
    /* The line about an empty shelf belongs to the wall, and the wall is not
       what is being looked at. */
    el.seriesEmpty.classList.add("hidden");
  } catch (_) {
    /* A shelf that has moved under the page -- the show scanned away while
       this was open -- reads the same as a box that cannot answer, and the
       shelf is read again either way. */
    seriesRead = false;
    TinyPPI.toast(T.series_failed, true);
  } finally {
    episodesBusy = false;
  }
}

/* Read the open show's episodes again, in place.

   What sends the page here is the box saying its library moved while somebody
   is inside a show, which is what an episode ending looks like from here: the
   row for it carries a resume bar and a watched tick, and both have just
   changed.  Without this the row would go on saying the episode was never
   watched for as long as the card stayed open.

   The folds go back as they were.  A list rebuilt with every season shut under
   somebody who had just opened one is a list that threw away where they were
   looking, which over a nine-season show is most of the card. */
async function refreshEpisodes() {
  const show = openShow;
  /* Nothing to read, something already reading, or a press waiting on an
     episode -- which is a list about to be rebuilt under the row showing the
     press.  The next version the box announces reads it again. */
  if (!show || episodesBusy || startingEpisode) return;
  episodesBusy = true;
  try {
    const answer = await TinyPPI.getJSON(
      "/api/episodes?tvshowid=" + encodeURIComponent(show.id));
    /* Somebody may have left the show -- or opened another one -- while the
       box was answering, and what came back is then about a card that is no
       longer on the screen.  By id and not by identity: a shelf read again in
       the meantime hands the card a fresh object for the same show. */
    if (!openShow || openShow.id !== show.id) return;
    buildEpisodes(Array.isArray(answer.episodes) ? answer.episodes : [],
                  unfoldedSeasons());
  } catch (_) {
    /* The show may have been scanned away under the card.  The shelf is read
       again either way, and that is what takes the card back to the wall. */
    seriesRead = false;
  } finally {
    episodesBusy = false;
  }
}

/* Which seasons are open on the card right now, by number. */
function unfoldedSeasons() {
  const open = new Set();
  for (const fold of el.episodeList.querySelectorAll(".seasonfold[open]")) {
    open.add(fold.dataset.season);
  }
  return open;
}

/* A show as its seasons, each folded away under its own heading.

   Shut to begin with, all of them: a series that has run for nine years is
   several hundred rows, and a list that opens on all of them is a list whose
   first screen is the middle of season one.  Shut, the whole show is a dozen
   lines -- which season, and how many episodes are in it -- and the one being
   looked for is one press away.

   It also costs nothing to draw: a still inside a shut fold is never fetched,
   so opening a show asks the box for the pictures of one season rather than of
   nine. */
function buildEpisodes(list, unfolded) {
  const rows = document.createDocumentFragment();
  const many = new Map();
  for (const episode of list) {
    const number = seasonOf(episode);
    many.set(number, (many.get(number) || 0) + 1);
  }

  const runs = new Map();
  for (const episode of list) {
    const number = seasonOf(episode);
    runs.set(number, (runs.get(number) || 0) + (episode.duration || 0));
  }

  let season = null;
  let fold = null;          /* where this season's rows go, or null outside one */
  for (const episode of list) {
    const number = seasonOf(episode);
    if (number !== season) {
      season = number;
      /* An episode the library files under no season at all goes under no
         heading, and so into no fold either: there is nothing to call it, and
         a fold with no name on it is a row that hides things. */
      fold = number >= 0
        ? seasonFold(number, many.get(number), runs.get(number), rows,
                     !!unfolded && unfolded.has(String(number))) : null;
    }
    (fold || rows).append(episodeRow(episode));
  }
  el.episodeList.replaceChildren(rows);
  el.seriesCount.textContent = String(list.length);
}

function seasonOf(episode) {
  return typeof episode.season === "number" ? episode.season : -1;
}

/* One season's fold, added to the list; what comes back is where its episodes
   go. */
function seasonFold(number, count, seconds, into, open) {
  const fold = document.createElement("details");
  fold.className = "seasonfold";
  /* Which season this is, so a list read again can put back the folds that
     were open before it (see refreshEpisodes). */
  fold.dataset.season = String(number);
  fold.open = !!open;

  const heading = document.createElement("summary");
  heading.className = "season";
  const name = document.createElement("span");
  name.textContent = number === 0
    ? T.series_specials : T.series_season.replace("%s", number);
  const total = document.createElement("span");
  total.className = "seasoncount mono";
  /* How many, and how long that is altogether -- which folded away is the
     whole of what the season still has to say, and the one thing somebody
     weighing an evening against a season wants to know. */
  const runs = runtime(seconds);
  total.textContent = runs ? count + " \u00b7 " + runs : String(count);
  heading.append(name, total);

  const body = document.createElement("div");
  body.className = "seasonepisodes";
  fold.append(heading, body);
  into.append(fold);
  return body;
}

function episodeRow(episode) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "episode";

  const frame = document.createElement("div");
  frame.className = "episodestill";
  if (episode.thumb) {
    const image = document.createElement("img");
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = "";
    image.src = TinyPPI.withToken(
      "/api/art?kind=thumb&episodeid=" + encodeURIComponent(episode.id) +
      "&v=" + encodeURIComponent(episode.thumb));
    image.addEventListener("error", () => image.remove());
    frame.append(image);
  }
  if (episode.watched) {
    const seen = document.createElement("span");
    seen.className = "filmseen";
    seen.setAttribute("role", "img");
    seen.setAttribute("aria-label", T.films_watched);
    seen.title = T.films_watched;
    frame.append(seen);
  }
  if (episode.resume && episode.duration) {
    const bar = document.createElement("div");
    bar.className = "filmresume";
    bar.title = T.films_resume;
    const done = document.createElement("span");
    const at = Math.min(100, Math.max(2, (episode.resume / episode.duration) * 100));
    done.style.width = at.toFixed(1) + "%";
    bar.append(done);
    frame.append(bar);
  }

  const meta = document.createElement("div");
  meta.className = "episodemeta";
  const code = episodeCode(episode);
  /* Which episode it is and how long it runs, on the one line: both are what
     somebody choosing between two of them is weighing, and a row that put
     them on separate lines would be twice as tall for it. */
  const numbered = [code, runtime(episode.duration)].filter(Boolean)
    .join(" \u00b7 ");
  if (numbered) {
    const number = document.createElement("div");
    number.className = "episodenumber mono";
    number.textContent = numbered;
    meta.append(number);
  }
  const title = document.createElement("div");
  title.className = "episodetitle";
  /* An episode the library has no name for is called by its number, which is
     the only name it has ever had. */
  title.textContent = episode.title || code;
  meta.append(title);

  row.append(frame, meta);
  row.addEventListener("click", () => ask({
    title: [code, episode.title].filter(Boolean).join(" \u00b7 "),
    body: { episodeid: episode.id },
    play: episode.resume ? T.films_resume : T.films_play,
    resumable: !!episode.resume,
    onPlay: (fromStart) => startEpisode(episode, row, fromStart)
  }));
  return row;
}

/* S01E04, or E04 where the library knows the number but not the season. */
function episodeCode(episode) {
  const pad = (value) => (value < 10 ? "0" + value : String(value));
  const season = typeof episode.season === "number" && episode.season > 0
    ? "S" + pad(episode.season) : "";
  const number = typeof episode.episode === "number" && episode.episode >= 0
    ? "E" + pad(episode.episode) : "";
  return season + number;
}

function closeShow() {
  openShow = null;
  el.episodeList.replaceChildren();
  el.episodeList.classList.add("hidden");
  el.seriesBack.classList.add("hidden");
  el.seriesOpen.classList.add("hidden");
  el.seriesGrid.classList.remove("hidden");
  el.seriesBox.classList.remove("hidden");
  applySeriesSearch();
}

async function startEpisode(episode, row, fromStart) {
  if (startingEpisode) return;
  startingEpisode = episode.id;
  row.classList.add("busy");
  for (const node of el.episodeList.querySelectorAll(".episode")) {
    node.disabled = true;
  }
  TinyPPI.toast(T.films_starting);

  let failed = false;
  try {
    const response = await fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify(fromStart ? { episodeid: episode.id, resume: false }
                                     : { episodeid: episode.id })
    });
    if (response.status === 401) {
      failed = true;
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      failed = true;
      TinyPPI.toast(T.films_failed, true);
    } else {
      /* What has been watched is about to move, on this episode and on the
         count its show's tile wears: the shelf is read again. */
      seriesRead = false;
      continueStale();
    }
  } catch (_) {
    failed = true;
    TinyPPI.toast(T.films_failed, true);
  }

  if (failed) {
    releaseSeries();
    return;
  }
  clearTimeout(episodeReleasing);
  episodeReleasing = setTimeout(releaseSeries, FILMS_START_MS);
}

function releaseSeries() {
  clearTimeout(episodeReleasing);
  episodeReleasing = 0;
  startingEpisode = 0;
  for (const row of el.episodeList.querySelectorAll(".episode")) {
    row.disabled = false;
    row.classList.remove("busy");
  }
}

el.seriesSearch.addEventListener("input", applySeriesSearch);
el.seriesSearchClear.addEventListener("click", () => {
  el.seriesSearch.value = "";
  applySeriesSearch();
  el.seriesSearch.focus();
});
el.seriesBack.addEventListener("click", closeShow);
