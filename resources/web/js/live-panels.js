"use strict";

/* ===========================================================================
   The live panels, for whichever page asks for them.

   What is playing -- with its poster and the format logos -- the four figures
   worth a glance, the luminance chart, what the whole title has done so far,
   and the transport row.  The dashboard opens on them and the metadata window
   shows the same, so a second screen left on either page says what the film is
   doing.

   This component is shared by both pages and loaded after core.js.

   A page opts in by putting <div id="live"></div> where the panels belong;
   the markup and the drawing are here, the styling is in live-panels.css.  It
   then hands the snapshot on through TinyPPI.panels.update() and the localized
   strings through .strings().
=========================================================================== */

(function () {

  const host = document.getElementById("live");
  if (!host) return;
  const metadataPage = document.body.classList.contains("metadata-page");
  const pageState = metadataPage ? "metadata" : "dashboard";

  /* How much of the past the live buffer holds, in seconds.  It is what the
     one-minute range draws; the longer ones come from the add-on, which has
     been sampling since the film started. */
  const HISTORY_SECONDS = 60;

  /* How often a longer range is fetched again while it is on screen. */
  const HISTORY_REFRESH = 5000;

  host.innerHTML =
    '<section class="card hero" id="nowCard">' +
      '<div class="art hidden" id="artBox"><img id="poster" alt=""></div>' +
      '<div class="now">' +
        '<div class="badges" id="badges"></div>' +
        '<h1 id="title">—</h1>' +
        '<p class="meta" id="meta"></p>' +
        '<p class="file mono hidden" id="file"></p>' +
        '<div class="logos" id="logos"></div>' +
      '</div>' +
      /* The bar and the buttons take a row of their own under both, so
         they have the whole card to lay out in however narrow the poster
         leaves the column beside it. */
      '<div class="foot">' +
        '<div class="progress">' +
          '<div class="track" id="track" role="slider" tabindex="0" ' +
            'aria-valuemin="0" aria-valuemax="100"><i id="bar"></i></div>' +
          '<div class="times mono">' +
            '<span id="tElapsed">--:--</span><span id="tTotal">--:--</span>' +
          '</div>' +
        '</div>' +
        '<div class="control-drawer" id="controlDrawer">' +
          '<div class="control-body">' +
            '<div class="transport hidden" id="transport"></div>' +
            '<div class="tracks hidden" id="tracks"></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</section>' +
    '<details class="card hidden" id="tiles">' +
      '<summary class="panel-toggle"><span id="tilesTitle"></span></summary>' +
      '<div class="tilegrid">' +
        '<div class="tile"><span class="k" id="kFps"></span>' +
          '<span class="vwrap"><span class="v mono" id="vFps">—</span><span class="u" id="uFps"></span></span></div>' +
        '<div class="tile"><span class="k" id="kDrops"></span>' +
          '<span class="vwrap"><span class="v mono" id="vDrops">0</span><span class="u"></span></span></div>' +
        '<div class="tile"><span class="k" id="kSwitches"></span>' +
          '<span class="vwrap"><span class="v mono" id="vSwitches">0</span><span class="u"></span></span></div>' +
      '</div>' +
    '</details>' +
    '<details class="card hidden" id="chartCard">' +
      '<summary class="panel-toggle"><span id="chartTitle"></span></summary>' +
      '<div class="chart-options">' +
        '<div class="ranges" id="ranges"></div>' +
      '</div>' +
      '<div class="chartwrap">' +
        '<canvas id="chart" class="chart" role="img"></canvas>' +
        '<div class="legend">' +
          '<span><i class="swatch band"></i>Max</span>' +
          '<span><i class="swatch avg"></i>Ø</span>' +
          '<span id="chartScale" style="margin-left:auto"></span>' +
        '</div>' +
      '</div>' +
    '</details>' +
    '<details class="card hidden" id="healthCard">' +
      '<summary class="panel-toggle"><span id="healthTitle"></span></summary>' +
      '<div class="chart-options">' +
        '<div class="ranges" id="healthRanges"></div>' +
      '</div>' +
      '<div class="chartwrap">' +
        '<canvas id="healthChart" class="chart" role="img"></canvas>' +
        '<div class="legend">' +
          '<span><i class="swatch band"></i><span id="cacheLegend"></span></span>' +
          '<span><i class="swatch drops"></i><span id="dropsLegend"></span></span>' +
          '<span id="healthScale" style="margin-left:auto"></span>' +
        '</div>' +
      '</div>' +
    '</details>' +
    '<details class="card hidden" id="eventsCard">' +
      '<summary class="panel-toggle"><span id="eventsTitle"></span></summary>' +
      '<div class="events" id="events"></div>' +
    '</details>';

  const $ = (id) => document.getElementById(id);

  const controlToggle = document.createElement("button");
  controlToggle.type = "button";
  controlToggle.id = "controlToggle";
  controlToggle.className = "iconbtn control-toggle hidden";
  controlToggle.setAttribute("aria-expanded", "false");
  controlToggle.setAttribute("aria-controls", "controlDrawer");
  /* A span, where every other icon on the page is an <img>: this one takes the
     accent, and an <img> cannot be given a colour -- the file is a white
     stroke.  It is painted instead, the same drawing masking the colour in
     rather than being shown as it stands (see .control-chevron in
     live-panels.css).  The colour has to be worked out at runtime under the
     adaptive theme, so a second file in the accent is no use here. */
  const controlChevron = document.createElement("span");
  controlChevron.className = "ui-icon control-chevron";
  controlChevron.setAttribute("aria-hidden", "true");
  controlToggle.append(controlChevron);
  $("nowCard").append(controlToggle);

  const el = {
    nowCard: $("nowCard"), badges: $("badges"), title: $("title"),
    meta: $("meta"), file: $("file"), logos: $("logos"),
    artBox: $("artBox"), poster: $("poster"),
    track: $("track"), bar: $("bar"), tElapsed: $("tElapsed"), tTotal: $("tTotal"),
    controlDrawer: $("controlDrawer"), controlToggle,
    transport: $("transport"), tracks: $("tracks"),
    tiles: $("tiles"), vSwitches: $("vSwitches"), vDrops: $("vDrops"),
    vFps: $("vFps"), uFps: $("uFps"),
    chartCard: $("chartCard"), chart: $("chart"), ranges: $("ranges"),
    healthCard: $("healthCard"), healthChart: $("healthChart"),
    healthRanges: $("healthRanges"), healthScale: $("healthScale"),
    eventsCard: $("eventsCard"), events: $("events")
  };

  let live = [];        /* {t, max, avg} for the last HISTORY_SECONDS       */
  let past = null;      /* the add-on's own history, when a range needs it  */
  let pastAt = 0;       /* when that arrived, to age it as time goes on     */
  let pastSeq = -1;     /* the event count it was fetched at                */
  let fetching = false;
  let lastTry = 0;      /* when one was last attempted, failures included   */
  let range = HISTORY_SECONDS;
  let control = false;
  let posterTag = "";
  let volumeHeld = 0;   /* while a finger is on the slider, leave it alone  */
  let trackKey = "";
  let idleFetched = false;  /* the ended title's events, asked for once      */
  const controlStateKey = pageState + ".controls";

  function setControlsOpen(open, remember) {
    el.controlDrawer.classList.toggle("open", open);
    el.controlToggle.setAttribute("aria-expanded", String(open));
    if (remember !== false) TinyPPI.setDisclosureState(controlStateKey, open);
  }

  el.controlToggle.addEventListener("click", () => {
    setControlsOpen(el.controlToggle.getAttribute("aria-expanded") !== "true");
  });
  setControlsOpen(TinyPPI.disclosureState(controlStateKey, false), false);
  TinyPPI.bindDisclosure(el.tiles, pageState + ".metrics", false);
  TinyPPI.bindDisclosure(el.chartCard, pageState + ".l1", false);
  TinyPPI.bindDisclosure(el.healthCard, pageState + ".health", false);
  TinyPPI.bindDisclosure(el.eventsCard, pageState + ".events", false);

  /* --- what is playing -------------------------------------------------- */

  function renderNow(snapshot) {
    el.title.textContent = snapshot.title || "—";

    const media = snapshot.media || {};
    const parts = [];
    if (media.show) {
      parts.push(media.season && media.episode
        ? media.show + " · " + media.season + "×" +
          String(media.episode).padStart(2, "0")
        : media.show);
    }
    if (media.year) parts.push(media.year);
    if (media.genre) parts.push(media.genre);
    el.meta.textContent = parts.join("  ·  ");

    if (snapshot.filename) {
      el.file.textContent = snapshot.filename;
      el.file.classList.remove("hidden");
    } else {
      el.file.classList.add("hidden");
    }

    renderArt(snapshot.art || {});
    renderBadges(snapshot);
    renderLogos(snapshot.logos || {});

    const progress = (snapshot.metrics || {}).progress;
    const percent = (progress === null || progress === undefined) ? 0 : progress;
    el.bar.style.width = percent + "%";
    el.track.setAttribute("aria-valuenow", Math.round(percent));
    el.tElapsed.textContent = snapshot.time || "--:--";
    el.tTotal.textContent = snapshot.duration || "--:--";
  }

  /* The poster is fetched once per film: the add-on sends a tag that changes
     only when the picture does, and it hangs on the address, so the browser
     asks again exactly then.

     It is handed to the tint as well as to the page.  On the adaptive theme
     that is what the now-playing card is painted with; every other theme
     ignores it, so the call is made whichever one is in force -- the theme can
     change long after the film did (see js/cover-tint.js). */
  function renderArt(art) {
    const tag = art.poster || "";
    if (tag === posterTag) return;
    posterTag = tag;
    if (!tag) {
      el.artBox.classList.add("hidden");
      el.poster.removeAttribute("src");
      tint("");
      return;
    }
    const url = TinyPPI.withToken("/api/art?kind=poster&v=" + tag);
    el.poster.src = url;
    el.artBox.classList.remove("hidden");
    tint(url);
  }

  function tint(url) {
    if (window.TinyPPICover) TinyPPICover.show(el.nowCard, url, el.poster);
  }

  /* A film with no poster is not an error; the frame just goes away, and the
     card goes back to the plain panel colour with it. */
  el.poster.addEventListener("error", () => {
    el.artBox.classList.add("hidden");
    tint("");
  });

  function renderBadges(snapshot) {
    /* An empty source type is SDR, not "unknown": the add-on publishes a token
       only for the HDR formats (see publish_hdr_type), which is the same thing
       the VS10 buttons branch on. */
    const badges = [{ text: TinyPPI.prettyHdr(snapshot.hdr_type || "sdr"), alt: false }];
    /* The output, not "effective": that one names the overlay's layout and is
       built to stay on the source type, so it matched the source through every
       conversion and this badge never appeared.  Both sides are empty for SDR,
       so a film neither converted nor converted from compares equal and shows
       the one badge it should. */
    if (snapshot.output_type !== undefined
        && snapshot.output_type !== snapshot.hdr_type) {
      badges.push({
        text: "→ " + TinyPPI.prettyHdr(snapshot.output_type || "sdr"),
        alt: true
      });
    }
    if (snapshot.paused) badges.push({ icon: "pause", alt: true });
    el.badges.innerHTML = "";
    for (const badge of badges) {
      const node = document.createElement("span");
      node.className = badge.alt ? "badge alt" : "badge";
      if (badge.icon) node.appendChild(uiIcon(badge.icon));
      else node.textContent = badge.text;
      el.badges.appendChild(node);
    }
  }

  /* The very files the overlay draws, served from the add-on's own skin (see
     web/server.py _media_routes).  They are white on transparent and tinted
     on the TV, so the page inverts them for a light theme rather than shipping
     a second set. */
  function renderLogos(logos) {
    const wanted = [logos.video, logos.audio].filter(Boolean);
    if (el.logos.dataset.signature !== wanted.join("|")) {
      el.logos.dataset.signature = wanted.join("|");
      el.logos.innerHTML = "";
      for (const name of wanted) {
        const image = document.createElement("img");
        image.className = "logo";
        image.src = "/media/" + name;
        image.alt = "";
        image.addEventListener("error", () => image.remove());
        el.logos.appendChild(image);
      }
    }
  }

  function uiIcon(name) {
    const image = document.createElement("img");
    image.className = "ui-icon";
    image.src = "/icons/" + name + ".svg";
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    return image;
  }

  function setButtonIcon(node, name) {
    if (node.dataset.icon === name) return;
    node.dataset.icon = name;
    node.replaceChildren(uiIcon(name));
  }

  /* --- the remote ------------------------------------------------------- */

  /* Built once, the first time a snapshot says the add-on will take orders.
     Everything goes through TinyPPI.command, which carries the token and says
     whether the player did it. */
  function buildTransport() {
    if (el.transport.dataset.built) return;
    el.transport.dataset.built = "1";

    const button = (label, title, handler, className) => {
      const node = document.createElement("button");
      node.type = "button";
      node.className = "tbtn" + (className ? " " + className : "");
      node.textContent = label;
      node.title = title || label;
      if (title) node.setAttribute("aria-label", title);
      node.addEventListener("click", handler);
      return node;
    };

    const imageButton = (name, title, handler, className) => {
      const node = button("", title, handler, className);
      setButtonIcon(node, name);
      return node;
    };

    /* CSS keeps these as two full-width rows: seek and playback first, then
       stop, the volume slider and mute at the far right. */
    const keys = document.createElement("div");
    keys.className = "tkeys";
    keys.append(
      button("−10m", "", () => TinyPPI.command("seek", -600)),
      button("−1m", "", () => TinyPPI.command("seek", -60)),
      button("−10s", "", () => TinyPPI.command("seek", -10)),
      /* The icon says what pressing it does, so it follows the player: pause
         while it plays, play while it is paused. */
      imageButton("pause", TinyPPI.T.playpause,
                  () => TinyPPI.command("playpause"), "primary"),
      button("+10s", "", () => TinyPPI.command("seek", 10)),
      button("+1m", "", () => TinyPPI.command("seek", 60)),
      button("+10m", "", () => TinyPPI.command("seek", 600))
    );

    const rest = document.createElement("div");
    rest.className = "tvol";
    rest.append(imageButton("stop", TinyPPI.T.stop,
                            () => TinyPPI.command("stop")));

    const mute = imageButton("volume", TinyPPI.T.mute,
                             () => TinyPPI.command("mute"), "mute");
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = 0;
    slider.max = 100;
    slider.className = "volume";
    slider.id = "volume";
    slider.setAttribute("aria-label", TinyPPI.T.volume);
    /* Whatever the input already reads, so a slider the add-on has not
       reported a level for looks exactly as it did before it was drawn here. */
    setVolume(slider, slider.value);
    slider.addEventListener("input", () => {
      volumeHeld = Date.now();
      setVolume(slider, Number(slider.value));
      TinyPPI.command("volume", Number(slider.value));
    });
    rest.append(slider, mute);
    el.transport.append(keys, rest);

    /* A tap anywhere on the bar seeks there, and the arrow keys do the same,
       so the bar is not a control only a finger can reach. */
    el.track.addEventListener("click", (event) => {
      if (!control) return;
      const box = el.track.getBoundingClientRect();
      if (!box.width) return;
      const where = Math.min(100, Math.max(0,
        (event.clientX - box.left) / box.width * 100));
      el.bar.style.width = where + "%";
      TinyPPI.command("seek_percent", where);
    });
    el.track.addEventListener("keydown", (event) => {
      if (!control) return;
      if (event.key === "ArrowLeft") TinyPPI.command("seek", -10);
      else if (event.key === "ArrowRight") TinyPPI.command("seek", 10);
      else return;
      event.preventDefault();
    });
  }

  /* How far the slider has run, on the slider itself.

     The bar is drawn rather than left to the browser (see .volume in
     live-panels.css), and WebKit has no pseudo-element for the part that has
     run -- so the value has to reach the stylesheet as well as the input.
     Firefox fills its own and ignores this. */
  function setVolume(slider, value) {
    slider.value = value;
    slider.style.setProperty("--vol", Number(value) + "%");
  }

  function renderTransport(snapshot) {
    const hadControl = control;
    control = !!snapshot.control;
    const controls = snapshot.controls || {};
    if (!control) {
      setControlsOpen(false, false);
      el.controlToggle.classList.add("hidden");
      el.transport.classList.add("hidden");
      el.tracks.classList.add("hidden");
      el.track.classList.remove("seekable");
      return;
    }
    buildTransport();
    if (!hadControl) {
      setControlsOpen(TinyPPI.disclosureState(controlStateKey, false), false);
    }
    el.controlToggle.classList.remove("hidden");
    el.transport.classList.remove("hidden");
    el.track.classList.add("seekable");

    const play = el.transport.querySelector(".tbtn.primary");
    if (play) setButtonIcon(play, snapshot.paused ? "play" : "pause");

    const slider = $("volume");
    const mute = el.transport.querySelector(".mute");
    if (slider && controls.volume !== null && controls.volume !== undefined) {
      /* Not while a finger is on it: the snapshot is a fifth of a second
         behind, and writing it back would drag the handle out from under. */
      if (Date.now() - volumeHeld > 1500) setVolume(slider, controls.volume);
    }
    if (mute) {
      mute.classList.toggle("on", !!controls.muted);
      setButtonIcon(mute, controls.muted ? "volume-muted" : "volume");
    }
    renderTracks(controls);
  }

  /* One picker per kind, rebuilt only when the tracks themselves change --
     a select rebuilt five times a second could never be opened. */
  function renderTracks(controls) {
    const audio = controls.audio || [];
    const subs = controls.subtitle || [];
    if (audio.length < 2 && !subs.length) {
      el.tracks.classList.add("hidden");
      return;
    }
    el.tracks.classList.remove("hidden");

    const key = JSON.stringify([audio, subs]);
    if (trackKey !== key) {
      trackKey = key;
      el.tracks.innerHTML = "";
      if (audio.length > 1) {
        el.tracks.append(picker("audio", TinyPPI.T.audio_track, audio, false));
      }
      if (subs.length) {
        el.tracks.append(picker("subtitle", TinyPPI.T.subtitles, subs, true));
      }
    }

    const audioPick = $("pick-audio");
    if (audioPick) audioPick.value = String(controls.audio_current);
    const subPick = $("pick-subtitle");
    if (subPick) {
      subPick.value = controls.subtitle_on
        ? String(controls.subtitle_current) : "-1";
    }
  }

  function picker(kind, label, options, withOff) {
    const wrap = document.createElement("label");
    wrap.className = "pick";
    const caption = document.createElement("span");
    caption.textContent = label;
    const select = document.createElement("select");
    select.id = "pick-" + kind;
    if (withOff) select.append(new Option(TinyPPI.T.off, "-1"));
    for (const option of options) {
      select.append(new Option(option.label, String(option.index)));
    }
    select.addEventListener("change", () => {
      TinyPPI.command(kind, Number(select.value));
    });
    wrap.append(caption, select);
    return wrap;
  }

  /* --- the four figures ------------------------------------------------- */

  function renderTiles(metrics, session) {
    if (metadataPage) {
      el.tiles.classList.add("hidden");
      return;
    }
    el.tiles.classList.remove("hidden");
    const totals = session || {};
    el.vSwitches.textContent = String(totals.switches || 0);
    el.vDrops.textContent = String(totals.drops || 0);
    el.vFps.textContent  = metrics.fps_in
      ? metrics.fps_in.toFixed(3).replace(/0+$/, "").replace(/[.]$/, "") : "—";
    /* Empty rather than a space, so the line goes away with it -- see
       .tile .u:empty in live-panels.css. */
    el.uFps.textContent  = metrics.fps_drop ? "▼ " + metrics.fps_drop : "";
  }

  const EVENT_LABEL = {
    vs10: () => TinyPPI.T.vs10,
    mode: () => TinyPPI.T.ev_mode,
    cache: () => TinyPPI.T.ev_cache,
    /* The word the tile uses, so a stutter is called the same thing wherever
       it is read. */
    drops: () => TinyPPI.T.drops
  };

  /* A transition names two whole VS10 output states -- "SDR BT.709" to
     "DV-LL BT.2020nc" is a realistic width.  The mobile layout gives every
     event a separate value line so transitions and short values align. */
  function isTransition(entry) {
    return entry.from !== undefined && entry.to !== undefined;
  }

  function eventText(entry) {
    if (isTransition(entry)) return entry.from + " → " + entry.to;
    if (entry.kind === "cache") return Math.round(entry.value) + "%";
    /* Frames lost in the worst second of the stutter, so the figure carries
       its unit: it is a rate, not a count of what the whole title lost. */
    if (entry.kind === "drops") return entry.value + " FPS";
    return String(entry.value);
  }

  function renderEvents(events) {
    if (!events || !events.length) {
      el.events.className = "events empty";
      el.events.textContent = TinyPPI.T.events_empty;
      return;
    }
    el.events.className = "events";
    el.events.innerHTML = "";
    /* Newest first: what just happened is what a glance is looking for. */
    for (const entry of events.slice().reverse()) {
      const shift = isTransition(entry);
      const row = document.createElement("div");
      if (entry.kind === "mode") {
        row.className = "event drops";
      } else {
        row.className = "event " + entry.kind + (shift ? " shift" : "");
      }
      const when = document.createElement("span");
      when.className = "at mono";
      when.textContent = entry.pos || "";
      const what = document.createElement("span");
      what.className = "what";
      what.textContent = (EVENT_LABEL[entry.kind] || (() => entry.kind))();
      const detail = document.createElement("span");
      detail.className = "detail mono";
      detail.textContent = eventText(entry);
      row.append(when, what, detail);
      el.events.append(row);
    }
  }

  /* --- the charts ------------------------------------------------------- */

  /* Luminance spans four decades, from a black frame to a specular highlight,
     so the y axis is logarithmic: a linear one would flatten everything below
     a hundred nits into the baseline. */
  const MIN_NITS = 0.01;
  const MAX_NITS = 10000;
  const logScale = (value) => {
    const clamped = Math.min(MAX_NITS, Math.max(MIN_NITS, value));
    return (Math.log10(clamped) - Math.log10(MIN_NITS)) /
           (Math.log10(MAX_NITS) - Math.log10(MIN_NITS));
  };

  /* Every chart on the page reads the same range buttons, because a page only
     ever shows one chart: the luminance one belongs to the metadata window and
     the playback one to the dashboard. */
  const rangeBars = [];

  function buildRanges(container) {
    if (container.dataset.built) return;
    container.dataset.built = "1";
    rangeBars.push(container);
    const spans = [[60, "range_1m"], [600, "range_10m"], [0, "range_all"]];
    for (const [seconds, key] of spans) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "range";
      button.dataset.range = String(seconds);
      button.dataset.key = key;
      button.textContent = TinyPPI.T[key] || key;
      button.addEventListener("click", () => {
        range = seconds;
        markRange();
        if (seconds !== HISTORY_SECONDS) fetchHistory(true);
        drawCharts();
      });
      container.append(button);
    }
    markRange();
  }

  function markRange() {
    for (const bar of rangeBars) {
      for (const button of bar.children) {
        button.classList.toggle("on", Number(button.dataset.range) === range);
      }
    }
  }

  /* The add-on has been sampling since the film started, so a page that opens
     halfway through asks for what it missed instead of drawing from the moment
     it arrived.  Fetched on connect, again whenever the event count moves, and
     on a slow tick while a long range is on screen. */
  function fetchHistory(force) {
    const now = Date.now();
    if (fetching) return;
    /* Never faster than once a second, however urgent the reason: a fetch
       that keeps failing leaves the event count unmatched, and every snapshot
       after it would otherwise be a fresh reason to try again. */
    if (now - lastTry < 1000) return;
    if (!force && now - pastAt < HISTORY_REFRESH) return;
    lastTry = now;
    fetching = true;
    TinyPPI.getJSON("/api/history").then((data) => {
      past = data;
      pastAt = Date.now();
      pastSeq = data.seq;
      if (!metadataPage) {
        renderEvents(data.events);
        el.eventsCard.classList.remove("hidden");
      }
      drawCharts();
    }).catch(() => { /* the stream's own retry reports an outage */ })
      .finally(() => { fetching = false; });
  }

  /* Both sources reduced to the same shape: how long ago, and what was read.
     ``required`` is the reading the chart cannot draw without -- a sample with
     nothing in that field is left out rather than drawn as a zero, which is
     what keeps an HDR10 title out of the luminance chart and keeps its cache
     in the playback one. */
  function series(required) {
    const now = Date.now() / 1000;
    const known = (value) => value !== null && value !== undefined;
    if (range === HISTORY_SECONDS) {
      const points = [];
      for (const point of live) {
        if (!known(point[required])) continue;
        points.push({
          age: now - point.t, max: point.max, avg: point.avg,
          drop: point.drop, cache: point.cache
        });
      }
      return points;
    }
    if (!past || !past.t || !past.t.length) return [];
    /* The add-on counts from the start of the film and the page from the
       moment the answer arrived; the drift is what puts the two on one axis. */
    const drift = now - pastAt / 1000;
    const points = [];
    for (let index = 0; index < past.t.length; index++) {
      const column = past[required];
      if (!column || !known(column[index])) continue;
      points.push({
        age: (past.now - past.t[index]) + drift,
        max: past.max[index],
        avg: known(past.avg[index]) ? past.avg[index] : past.max[index],
        drop: past.drop ? past.drop[index] : 0,
        cache: past.cache ? past.cache[index] : null
      });
    }
    return points;
  }

  /* --- what each page charts -------------------------------------------- */

  /* One live sample per snapshot, whatever the page draws from it: the two
     charts read the same buffer, and the readings a source cannot carry are
     left as they arrive rather than turned into zeroes here. */
  function recordSample(metrics) {
    const l1 = metrics.l1 || {};
    live.push({
      t: Date.now() / 1000,
      max: (l1.max === null || l1.max === undefined) ? null : l1.max,
      avg: (l1.avg === null || l1.avg === undefined) ? l1.max : l1.avg,
      drop: metrics.fps_drop || 0,
      cache: (metrics.cache === null || metrics.cache === undefined)
        ? null : metrics.cache
    });
    const now = Date.now() / 1000;
    while (live.length && now - live[0].t > HISTORY_SECONDS) live.shift();
  }

  function renderCharts(metrics) {
    recordSample(metrics);

    const card = metadataPage ? el.chartCard : el.healthCard;
    const ranges = metadataPage ? el.ranges : el.healthRanges;
    /* The luminance chart needs an RPU to read; the playback one needs only a
       player, so it is drawn for every source there is. */
    const l1 = metrics.l1 || {};
    const has = metadataPage
      ? (l1.max !== null && l1.max !== undefined)
      : true;
    if (!has) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    buildRanges(ranges);

    if (range !== HISTORY_SECONDS) fetchHistory(false);
    drawCharts();
  }

  /* --- drawing ----------------------------------------------------------- */

  /* The canvas sized to its box and the theme's palette read off it.  Read off
     the canvas rather than off <html>: custom properties inherit, so this is
     the theme's palette on every theme -- and the film's own accent on the
     adaptive one, where the card the chart sits in has taken the poster's
     colour (see css/theme.css). */
  function prepare(canvas) {
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return null;
    if (canvas.width !== Math.round(width * ratio) ||
        canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const style = getComputedStyle(canvas);
    const colour = (name, fallback) =>
      style.getPropertyValue(name).trim() || fallback;
    return {
      ctx, width, height,
      accent:  colour("--accent", "#4fc3f7"),
      accent2: colour("--accent-2", "#82b1ff"),
      line:    colour("--line", "#242c36"),
      dim:     colour("--dim", "#5d6875"),
      bad:     colour("--bad", "#ff5252")
    };
  }

  /* How far back the drawing goes: whichever range is on, and for the whole
     title as far back as the samples themselves. */
  function windowFor(points) {
    return range || Math.max(HISTORY_SECONDS, points[0].age);
  }

  function trace(ctx, points, x, y, key, colour, thickness, dash) {
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    points.forEach((point, index) => {
      const px = x(point.age), py = y(point[key]);
      index === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    });
    ctx.strokeStyle = colour;
    ctx.lineWidth = thickness;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.setLineDash([]);
  }

  /* An area under a trace, fading out towards the floor. */
  function area(ctx, points, x, y, key, colour, floor, alpha) {
    ctx.beginPath();
    ctx.moveTo(x(points[0].age), floor);
    for (const point of points) ctx.lineTo(x(point.age), y(point[key]));
    ctx.lineTo(x(points[points.length - 1].age), floor);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, y(Infinity), 0, floor);
    fill.addColorStop(0, colour);
    fill.addColorStop(1, "transparent");
    ctx.globalAlpha = alpha;
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function drawCharts() {
    if (metadataPage) drawLuminance();
    else drawHealth();
  }

  function drawLuminance() {
    const set = prepare(el.chart);
    if (!set) return;
    const { ctx, width, height } = set;

    const padLeft = 34, padRight = 6, padTop = 8, padBottom = 6;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;
    const y = (nits) => padTop + plotH * (1 - logScale(nits));

    /* Gridlines, one per decade. */
    ctx.strokeStyle = set.line;
    ctx.fillStyle = set.dim;
    ctx.lineWidth = 1;
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const tick of [0.1, 1, 10, 100, 1000, 10000]) {
      const ty = Math.round(y(tick)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padLeft, ty);
      ctx.lineTo(width - padRight, ty);
      ctx.stroke();
      ctx.fillText(tick >= 1000 ? (tick / 1000) + "k" : String(tick), padLeft - 6, ty);
    }

    const points = series("max");
    if (points.length < 2) return;
    const span = windowFor(points);
    const x = (age) => padLeft + plotW * (1 - Math.min(1, age / span));

    /* Peak, as an area down to the floor.  The min of an L1 block sits near
       zero on almost every frame, so a min-max band would be full height and
       say nothing; the peak against the average is where the grade shows. */
    area(ctx, points, x, y, "max", set.accent, padTop + plotH, 0.28);
    /* The peak is the solid line the fill belongs to; the average is dashed, so
       the two never read as one band even where they run close together. */
    trace(ctx, points, x, y, "max", set.accent, 1.7);
    trace(ctx, points, x, y, "avg", set.accent2, 1.5, [4, 3]);
  }

  /* What every source can say about itself: how full the cache ran and how
     many frames went missing while it did.  The two belong on one chart
     because they are usually the same story -- a buffer that empties is what a
     run of dropped frames comes out of -- and they are the reason to look at a
     dashboard at all when a film stutters. */
  function drawHealth() {
    const set = prepare(el.healthChart);
    if (!set) return;
    const { ctx, width, height } = set;

    const points = series("drop");
    const padLeft = 30, padTop = 8, padBottom = 6;
    /* Room on the right for the drop scale, and none where nothing was ever
       dropped and the axis is not drawn. */
    const worst = points.reduce((most, point) => Math.max(most, point.drop || 0), 0);
    const padRight = worst ? 30 : 8;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const cacheY = (percent) =>
      padTop + plotH * (1 - Math.min(100, Math.max(0, percent)) / 100);
    const top = Math.max(4, worst);
    const dropY = (count) => padTop + plotH * (1 - Math.min(1, count / top));

    ctx.strokeStyle = set.line;
    ctx.fillStyle = set.dim;
    ctx.lineWidth = 1;
    ctx.font = "10px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    for (const tick of [0, 25, 50, 75, 100]) {
      const ty = Math.round(cacheY(tick)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padLeft, ty);
      ctx.lineTo(width - padRight, ty);
      ctx.stroke();
      ctx.textAlign = "right";
      if (tick % 50 === 0) ctx.fillText(tick + "%", padLeft - 6, ty);
    }
    /* The right-hand axis carries the frames, and only the two figures worth
       naming: none, and the worst second there was. */
    if (worst) {
      ctx.textAlign = "left";
      ctx.fillStyle = set.bad;
      ctx.fillText(String(top), width - padRight + 6, Math.round(dropY(top)) + 0.5);
      ctx.fillStyle = set.dim;
      ctx.fillText("0", width - padRight + 6, Math.round(dropY(0)) + 0.5);
    }

    if (points.length < 2) return;
    const span = windowFor(points);
    const x = (age) => padLeft + plotW * (1 - Math.min(1, age / span));

    const cached = points.filter(
      (point) => point.cache !== null && point.cache !== undefined);
    if (cached.length > 1) {
      area(ctx, cached, x, cacheY, "cache", set.accent, padTop + plotH, 0.22);
      trace(ctx, cached, x, cacheY, "cache", set.accent, 1.6);
    }
    if (worst) trace(ctx, points, x, dropY, "drop", set.bad, 1.6);
  }

  /* The charts' colours come from the card they are drawn in, which the
     adaptive theme repaints from the poster.  A canvas cannot notice that on
     its own, so js/cover-tint.js says when it has happened. */
  document.addEventListener("tinyppi-tint", () => drawCharts());

  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawCharts, 120);
  });

  /* --- what a page calls ------------------------------------------------ */

  function strings(T) {
    $("tilesTitle").textContent = T.metrics;
    el.controlToggle.setAttribute("aria-label", T.controls);
    el.controlToggle.title = T.controls;
    $("kSwitches").textContent = T.switches;
    $("kDrops").textContent = T.drops;
    $("kFps").textContent = T.fps;
    $("chartTitle").textContent = T.chart;
    $("chartScale").textContent = "nits · log";
    $("healthTitle").textContent = T.health;
    $("cacheLegend").textContent = T.cache;
    $("dropsLegend").textContent = T.drops_fps;
    el.healthScale.textContent = "% · " + T.fps;
    $("eventsTitle").textContent = T.events;
    for (const bar of rangeBars) {
      for (const button of bar.children) {
        button.textContent = T[button.dataset.key] || button.dataset.key;
      }
    }
  }

  /* Everything the panels show comes out of one snapshot, and a snapshot that
     says nothing is playing takes them off the page rather than leaving the
     last frame of a film that has ended standing there. */
  function update(snapshot) {
    if (!snapshot || !snapshot.playing) {
      const cards = [el.nowCard, el.tiles, el.chartCard, el.healthCard];
      for (const node of cards) node.classList.add("hidden");
      live = [];
      posterTag = "";
      trackKey = "";
      setControlsOpen(false, false);
      /* The title that has just ended keeps its samples and its events for a
         while (see SessionLog.end in web/snapshot.py).  While it does, the
         list stays where it was rather than emptying the moment the credits
         stop -- which is the minute the figures are worth most. */
      const last = snapshot && snapshot.last;
      if (!last || !last.events) {
        el.eventsCard.classList.add("hidden");
        past = null;
        pastSeq = -1;
        idleFetched = false;
        return;
      }
      if (!idleFetched) {
        idleFetched = true;
        fetchHistory(true);
      }
      return;
    }
    idleFetched = false;
    el.nowCard.classList.remove("hidden");
    renderNow(snapshot);
    renderTransport(snapshot);
    renderTiles(snapshot.metrics || {}, snapshot.session);
    renderCharts(snapshot.metrics || {});

    /* The event list travels apart from the snapshot -- it would otherwise be
       sent five times a second to say nothing.  The count in the summary is
       what says there is something new to fetch. */
    const session = snapshot.session || {};
    if (session.seq !== undefined && session.seq !== pastSeq) fetchHistory(true);
  }

  /* The event list as something other than a page can print: the report on
     the dashboard writes the same entries into plain text (see buildReport in
     js/dashboard.js), and the history they come from is fetched here. */
  function events() {
    return ((past && past.events) || []).map((entry) => ({
      pos:   entry.pos || "",
      label: (EVENT_LABEL[entry.kind] || (() => entry.kind))(),
      text:  eventText(entry)
    }));
  }

  /* The highest L1 peak in the samples the page holds, or null where the
     source carried no luminance to sample. */
  function peak() {
    const column = (past && past.max) || [];
    let highest = null;
    for (const value of column) {
      if (value === null || value === undefined) continue;
      if (highest === null || value > highest) highest = value;
    }
    return highest;
  }

  window.TinyPPI.panels = { strings, update, events, peak };

})();
