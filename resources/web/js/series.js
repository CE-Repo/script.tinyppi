// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* The series library tab: the shelf of shows, one show's seasons and
   episodes, and starting an episode.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below. */

/* global selectTab, showDetails, slideIn, tintDialog, bindTitle, continueStale, el, FILMS_RETRY_MS, FILMS_START_MS, newest,
   ratingBadge, runtime, shelfTools, T */
/* exported openShowDetails, episodeCode, episodeReleasing, hideSeries, refreshEpisodes,
   releaseSeries, requestSeries, seriesOffered, seriesStale, seriesTools,
   startingEpisode */

/* --- the series library -------------------------------------------------- */

/* The same shelf as the films, with one floor more.

   A series is not a thing that can be put on -- an episode is -- so a press on
   a poster does not start anything: its details offer to open it, and opening
   it brings up a dialog of its seasons, each folded away with its episodes in
   it.  A press on one of those opens the episode's details over the dialog,
   and playing it closes both and goes to the live tab.  The wall stays where
   it was underneath, so closing the dialog is the way back to it.

   The episodes of a show are asked for when the show is opened and not before.
   A house with ninety series in it would otherwise be sent every episode of
   all of them to draw a wall of ninety posters, and it is the wall that is
   being looked at. */

let shows = [];            /* what the box last said its shelf holds      */
let seriesTag = "";        /* that list's own tag, unchanged lists skipped */
let seriesBusy = false;    /* a request for the shelf is in flight        */
let seriesRead = false;    /* the shelf has been read since it last moved */
let seriesShown = false;   /* the shelf has been read at least once       */
let seriesOffered = true;  /* until the box says it offers no series      */
let seriesNextTry = 0;     /* not before this, after a failure            */
let openShow = null;       /* the show whose seasons the dialog shows     */
let episodesBusy = false;  /* a request for one show's episodes           */
let startingEpisode = 0;   /* the episode a press is waiting on           */
let episodeReleasing = 0;  /* the timer that gives the list back          */
let episodesPutOff = false; /* the open show waits to be read again        */
let showTiles = new Map(); /* each show's tile on the wall of everything  */
let openedFrom = null;     /* the details the open show was opened from   */
let showQuestions = new Map(); /* each show's details question, by its id */
let episodeCount = 0;      /* how many episodes the open show has          */

/* The order and the genre over the wall of every show, as on the films. */
const seriesTools = shelfTools(el.seriesTools, {
  shelf: "series",
  sorts: ["title", "year", "rating", "added"],
  filters: ["genre"],
  onChange: arrangeSeries
});

/* Called from the other parts of the page once the series shelf may have moved: the
   next request reads it again. */
function seriesStale() {
  seriesRead = false;
}

function requestSeries(force) {
  if (seriesBusy || !seriesOffered) return;
  if (startingEpisode) return;   /* as with the films (see requestFilms in js/films.js) */
  if (!force && seriesRead) return;
  if (Date.now() < seriesNextTry) return;
  seriesBusy = true;
  loadSeries().finally(() => { seriesBusy = false; });
}

async function loadSeries() {
  /* As with the films: read as the request goes out, so that a move announced
     while it is out still stands afterwards. */
  seriesRead = true;
  try {
    const answer = await TinyPPI.getJSON("/api/series");
    /* Nor built under an episode pressed while the box was answering: a
       shelf without the open show would close it under the press. */
    if (startingEpisode) {
      seriesRead = false;
      return;
    }
    seriesShown = true;
    seriesNextTry = 0;
    const list = Array.isArray(answer.shows) ? answer.shows : [];
    if (!el.seriesGrid.children.length || (answer.tag || "") !== seriesTag) {
      seriesTag = answer.tag || "";
      shows = list;
      buildSeries();
    }
    el.seriesCard.classList.remove("hidden");
    el.seriesBox.classList.remove("hidden");
    el.recentSeriesCard.classList.toggle("hidden",
                                         !el.recentSeriesRow.children.length);
    el.unseenSeriesCard.classList.toggle("hidden",
                                         !el.unseenSeriesGrid.children.length);
  } catch (error) {
    seriesRead = false;
    seriesNextTry = Date.now() + FILMS_RETRY_MS;
    /* 403: no series on offer -- switched off in the add-on's settings, or a
       box that will not be told what to play.  A settled answer rather than a
       failure, so it is not asked again. */
    if (String((error || {}).message) === "403") seriesOffered = false;
    if (!seriesShown) hideSeries();
  }
}

function buildSeries() {
  const wall = document.createDocumentFragment();
  const unseen = document.createDocumentFragment();
  let waiting = 0;
  showTiles = new Map();
  showQuestions = new Map();
  for (const show of shows) {
    const tile = showTile(show);
    showTiles.set(show, tile);
    wall.append(tile);
    /* A show with an episode still waiting.  One the library has no episode
       count for is left off: nothing says there is anything in it to see. */
    if (!show.watched && show.unseen) {
      unseen.append(showTile(show));
      waiting += 1;
    }
  }
  el.seriesGrid.replaceChildren(wall);
  el.unseenSeriesGrid.replaceChildren(unseen);
  el.unseenSeriesGrid.scrollLeft = 0;
  /* A show on this row is one that gained an episode lately (a show's date is
     its newest episode's, see _SHOW_PROPERTIES in web/library.py); it opens
     the same dialog of seasons the walls do. */
  const recent = document.createDocumentFragment();
  for (const show of newest(shows)) recent.append(showTile(show));
  el.recentSeriesRow.replaceChildren(recent);
  el.recentSeriesRow.scrollLeft = 0;
  el.unseenSeriesCount.textContent = waiting ? String(waiting) : "";
  /* The count in the heading, and whatever the search box is narrowing it
     to, the way the film wall does after it is built. */
  seriesTools.fill(shows);
  arrangeSeries();
  /* A shelf that has just been read again is a shelf that may no longer hold
     the show somebody has open, and where it does not the dialog closes.
     Where it does, it is left open: the shelf is read again every time an
     episode ends, and a dialog that closed under whoever was choosing the
     next one each time would be a dialog nobody could watch a series from. */
  if (!openShow) return;
  const still = shows.find((show) => show.id === openShow.id);
  if (!still) {
    closeShow();
    return;
  }
  /* The tile it was opened from has been built again, so what the dialog's
     heading names is the show as the shelf now has it. */
  openShow = still;
  drawSeasonsHead();
}

/* Both series walls off the page, for a box with no series to offer. */
function hideSeries() {
  el.seriesCard.classList.add("hidden");
  el.seriesBox.classList.add("hidden");
  el.recentSeriesCard.classList.add("hidden");
  el.unseenSeriesCard.classList.add("hidden");
}

function showTile(show) {
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
    image.src =
      "/api/art?kind=poster&tvshowid=" + encodeURIComponent(show.id) +
      "&v=" + encodeURIComponent(show.poster);
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
     instead: its seasons, and the episodes in them, are what can be.  The
     question is kept with the show, so leaving the seasons goes back to the
     details they were opened from. */
  const question = {
    watched: !!show.watched, title: show.title, body: { tvshowid: show.id },
    play: T.series_open, onPlay: () => openShowView(show, question), stays: true
  };
  showQuestions.set(show.id, question);
  bindTitle(tile, question);
  return tile;
}

/* The details of the show with *id*, in place of the episode's details that
   asked for them, on the series tab -- where its seasons open from.  Nothing
   for a show the shelf does not hold. */
function openShowDetails(id) {
  const question = showQuestions.get(id);
  if (!question) return;
  selectTab("series");
  showDetails(question, true);
}

/* The wall in the chosen order, as the film wall is (see arrangeFilms in
   js/films.js). */
function arrangeSeries() {
  el.seriesGrid.append(...seriesTools.order(shows).map((show) => showTiles.get(show)));
  applySeriesSearch();
}

function applySeriesSearch() {
  const needle = el.seriesSearch.value.trim().toLowerCase();
  let shown = 0;
  for (const [show, tile] of showTiles) {
    const match = (!needle || tile.dataset.key.includes(needle)) && seriesTools.matches(show);
    tile.hidden = !match;
    if (match) shown += 1;
  }
  el.seriesSearchClear.classList.toggle("hidden", el.seriesSearch.value === "");
  el.seriesCount.textContent = shown === shows.length
    ? String(shows.length) : shown + " / " + shows.length;
  el.seriesEmpty.textContent = shows.length && seriesTools.filtering()
    ? T.filter_empty : T.series_empty;
  el.seriesEmpty.classList.toggle("hidden", shown > 0);
}

/* --- one show ------------------------------------------------------------ */

async function openShowView(show, from) {
  if (episodesBusy || startingEpisode) return;
  episodesBusy = true;
  try {
    const answer = await TinyPPI.getJSON(
      "/api/episodes?tvshowid=" + encodeURIComponent(show.id));
    openShow = show;
    openedFrom = from;
    buildEpisodes(Array.isArray(answer.episodes) ? answer.episodes : []);
    /* Over the show's page, where it is still open, and at least as tall, so
       nothing of it shows round the seasons as they slide in. */
    el.seasonsDialog.style.minHeight = el.detailsDialog.open
      ? el.detailsDialog.offsetHeight + "px" : "";
    if (!el.seasonsDialog.open) slideIn(el.seasonsDialog);
    el.seasonsDialog.querySelector("form").scrollTop = 0;
  } catch (_) {
    /* A shelf that has moved under the page -- the show scanned away while
       this was open -- reads the same as a box that cannot answer, and the
       shelf is read again either way. */
    seriesRead = false;
    TinyPPI.toast(T.series_failed, true);
  } finally {
    episodesBusy = false;
  }
  readEpisodesPutOff();
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
  /* Something already reading, or opening a show, which may have asked
     before the move it is sent for: read once more when it is back. */
  if (episodesBusy) {
    episodesPutOff = true;
    return;
  }
  const show = openShow;
  if (!show) return;
  /* A press waiting on an episode, which is a list about to be rebuilt under
     the row showing the press: read once the press is over instead (see
     releaseSeries). */
  if (startingEpisode) {
    episodesPutOff = true;
    return;
  }
  /* The dialog was closed under a started episode: nobody is looking at the
     show any more, so it is let go rather than read. */
  if (!el.seasonsDialog.open) {
    closeShow();
    return;
  }
  episodesBusy = true;
  try {
    const answer = await TinyPPI.getJSON(
      "/api/episodes?tvshowid=" + encodeURIComponent(show.id));
    /* Somebody may have left the show -- or opened another one -- while the
       box was answering, and what came back is then about a card that is no
       longer on the screen.  By id and not by identity: a shelf read again in
       the meantime hands the card a fresh object for the same show. */
    if (!openShow || openShow.id !== show.id) return;
    /* An episode pressed while the box was answering: as above. */
    if (startingEpisode) {
      episodesPutOff = true;
      return;
    }
    buildEpisodes(Array.isArray(answer.episodes) ? answer.episodes : [],
                  unfoldedSeasons());
  } catch (_) {
    /* The show may have been scanned away under the card.  The shelf is read
       again either way, and that is what takes the card back to the wall. */
    seriesRead = false;
  } finally {
    episodesBusy = false;
  }
  readEpisodesPutOff();
}

/* The read a move asked for while another was out, unless a press is now
   waiting on an episode (releaseSeries reads it then). */
function readEpisodesPutOff() {
  if (episodesPutOff && !startingEpisode) {
    episodesPutOff = false;
    refreshEpisodes();
  }
}

/* Which seasons are open in the dialog right now, by number. */
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
  episodeCount = list.length;
  drawSeasonsHead();
}

/* The head of the dialog, as a title's details have theirs: the open show's
   backdrop and poster, its name, and under it its year and how many
   episodes it has.  The page takes its colour off the poster as the details
   do (see tintDialog in js/marking.js). */
function drawSeasonsHead() {
  const show = openShow;
  seasonPicture(el.seasonsBackdrop, "fanart", show.fanart);
  seasonPicture(el.seasonsPoster, "poster", show.poster);
  el.seasonsHero.classList.toggle("bare", el.seasonsBackdrop.hidden);
  el.seriesOpen.textContent = show.title;
  el.seasonsCount.textContent = [show.year ? String(show.year) : "",
    episodeCount ? T.series_episodes.replace("%s", episodeCount) : ""]
    .filter(Boolean).join(" · ");
  tintDialog(el.seasonsDialog, [el.seasonsPoster, el.seasonsBackdrop]);
}

/* One of the show's pictures, or none: one the box cannot read leaves the
   space it would have filled, as a missing one does. */
function seasonPicture(image, kind, tag) {
  image.hidden = !tag;
  if (tag) {
    image.src = "/api/art?kind=" + kind + "&tvshowid=" + encodeURIComponent(openShow.id) +
      "&v=" + encodeURIComponent(tag);
  } else {
    image.removeAttribute("src");
  }
  image.onerror = () => {
    image.hidden = true;
    el.seasonsHero.classList.toggle("bare", el.seasonsBackdrop.hidden);
  };
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
    image.src =
      "/api/art?kind=thumb&episodeid=" + encodeURIComponent(episode.id) +
      "&v=" + encodeURIComponent(episode.thumb);
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
  bindTitle(row, {
    watched: !!episode.watched, title: [code, episode.title].filter(Boolean).join(" \u00b7 "),
    body: { episodeid: episode.id },
    play: episode.resume ? T.films_resume : T.films_play,
    resumable: !!episode.resume,
    onPlay: (fromStart) => startEpisode(episode, row, fromStart)
  });
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

/* The dialog closed, by its key, by Escape or by the page: the show is no
   longer open, and nothing is read for it again. */
function closeShow() {
  openShow = null;
  openedFrom = null;
  el.episodeList.replaceChildren();
  el.seasonsCount.textContent = "";
  if (el.seasonsDialog.open) el.seasonsDialog.close();
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
      /* Closed rather than let go: the rows stay as they are, pressed, until
         the episode is on (see releaseSeries), and the show is let go the
         next time it would be read (see refreshEpisodes). */
      el.seasonsDialog.close();
      selectTab("live");
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
  if (episodesPutOff) {
    episodesPutOff = false;
    refreshEpisodes();
  }
}

el.seriesSearch.addEventListener("input", () => {
  el.seriesCard.open = true;
  applySeriesSearch();
});
el.seriesSearchClear.addEventListener("click", () => {
  el.seriesSearch.value = "";
  applySeriesSearch();
  el.seriesSearch.focus();
});
/* Closed by the reader -- its key, Escape, back, a pull down or a click
   beside it, sliding out as it goes (see slideOut in js/marking.js) -- the
   seasons give way to the show's details they were opened over.  Not while
   an episode is starting: that is the press closing the dialog itself, and
   the rows it is waiting on are still wanted. */
el.seasonsDialog.addEventListener("close", () => {
  if (!openShow || startingEpisode) return;
  const back = openedFrom;
  closeShow();
  /* Usually the show's page is still open under the seasons, and simply
     shows again as they slide away; where an episode's took its place, the
     show's is put back -- drawn from what was read of it, at once. */
  if (!el.detailsDialog.open) showDetails(back);
});
