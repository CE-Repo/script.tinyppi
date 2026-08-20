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
        '<details class="control-drawer hidden" id="controlDrawer">' +
          '<summary><span id="controlLabel"></span></summary>' +
          '<div class="control-body">' +
            '<div class="transport hidden" id="transport"></div>' +
            '<div class="tracks hidden" id="tracks"></div>' +
          '</div>' +
        '</details>' +
      '</div>' +
    '</section>' +
    '<section class="tiles hidden" id="tiles">' +
      '<div class="tile" id="tPeak"><span class="k" id="kPeak"></span>' +
        '<span class="v mono" id="vPeak">—</span><span class="u">nits</span></div>' +
      '<div class="tile" id="tAvg"><span class="k" id="kAvg"></span>' +
        '<span class="v mono" id="vAvg">—</span><span class="u">nits</span></div>' +
      '<div class="tile"><span class="k" id="kAr"></span>' +
        '<span class="v mono" id="vAr">—</span><span class="u">&nbsp;</span></div>' +
      '<div class="tile"><span class="k" id="kFps"></span>' +
        '<span class="v mono" id="vFps">—</span><span class="u" id="uFps">&nbsp;</span></div>' +
    '</section>' +
    '<section class="card hidden" id="chartCard">' +
      '<div class="cardhead">' +
        '<h2 id="chartTitle"></h2>' +
        '<div class="ranges" id="ranges"></div>' +
      '</div>' +
      '<div class="chartwrap">' +
        '<canvas id="chart" role="img"></canvas>' +
        '<div class="legend">' +
          '<span><i class="swatch band"></i>Max</span>' +
          '<span><i class="swatch avg"></i>Ø</span>' +
          '<span id="chartScale" style="margin-left:auto"></span>' +
        '</div>' +
      '</div>' +
    '</section>' +
    '<section class="card hidden" id="sessionCard">' +
      '<h2 id="sessionTitle"></h2>' +
      '<div class="stats" id="stats"></div>' +
    '</section>' +
    '<section class="card hidden" id="eventsCard">' +
      '<h2 id="eventsTitle"></h2>' +
      '<div class="events" id="events"></div>' +
    '</section>';

  const $ = (id) => document.getElementById(id);

  const el = {
    nowCard: $("nowCard"), badges: $("badges"), title: $("title"),
    meta: $("meta"), file: $("file"), logos: $("logos"),
    artBox: $("artBox"), poster: $("poster"),
    track: $("track"), bar: $("bar"), tElapsed: $("tElapsed"), tTotal: $("tTotal"),
    controlDrawer: $("controlDrawer"), controlLabel: $("controlLabel"),
    transport: $("transport"), tracks: $("tracks"),
    tiles: $("tiles"), tPeak: $("tPeak"), tAvg: $("tAvg"),
    vPeak: $("vPeak"), vAvg: $("vAvg"), vAr: $("vAr"),
    vFps: $("vFps"), uFps: $("uFps"),
    chartCard: $("chartCard"), chart: $("chart"), ranges: $("ranges"),
    sessionCard: $("sessionCard"), stats: $("stats"),
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
     asks again exactly then. */
  function renderArt(art) {
    const tag = art.poster || "";
    if (tag === posterTag) return;
    posterTag = tag;
    if (!tag) {
      el.artBox.classList.add("hidden");
      el.poster.removeAttribute("src");
      return;
    }
    el.poster.src = TinyPPI.withToken("/api/art?kind=poster&v=" + tag);
    el.artBox.classList.remove("hidden");
  }

  /* A film with no poster is not an error; the frame just goes away. */
  el.poster.addEventListener("error", () => {
    el.artBox.classList.add("hidden");
  });

  function renderBadges(snapshot) {
    /* An empty source type is SDR, not "unknown": the add-on publishes a token
       only for the HDR formats (see publish_hdr_type), which is the same thing
       the VS10 buttons branch on. */
    const badges = [{ text: TinyPPI.prettyHdr(snapshot.hdr_type || "sdr"), alt: false }];
    if (snapshot.effective && snapshot.effective !== snapshot.hdr_type) {
      badges.push({ text: "→ " + TinyPPI.prettyHdr(snapshot.effective), alt: true });
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
    slider.addEventListener("input", () => {
      volumeHeld = Date.now();
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

  function renderTransport(snapshot) {
    control = !!snapshot.control;
    const controls = snapshot.controls || {};
    if (!control) {
      el.controlDrawer.open = false;
      el.controlDrawer.classList.add("hidden");
      el.transport.classList.add("hidden");
      el.tracks.classList.add("hidden");
      el.track.classList.remove("seekable");
      return;
    }
    buildTransport();
    el.controlDrawer.classList.remove("hidden");
    el.transport.classList.remove("hidden");
    el.track.classList.add("seekable");

    const play = el.transport.querySelector(".tbtn.primary");
    if (play) setButtonIcon(play, snapshot.paused ? "play" : "pause");

    const slider = $("volume");
    const mute = el.transport.querySelector(".mute");
    if (slider && controls.volume !== null && controls.volume !== undefined) {
      /* Not while a finger is on it: the snapshot is a fifth of a second
         behind, and writing it back would drag the handle out from under. */
      if (Date.now() - volumeHeld > 1500) slider.value = controls.volume;
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

  function renderTiles(metrics) {
    el.tiles.classList.remove("hidden");
    const l1 = metrics.l1 || {};
    /* Peak and average come from the Dolby Vision L1 block and from nowhere
       else, so on any other source the two tiles are left out entirely rather
       than shown holding a dash. */
    const hasL1 = l1.max !== null && l1.max !== undefined;
    el.tPeak.classList.toggle("hidden", !hasL1);
    el.tAvg.classList.toggle("hidden", !hasL1);
    el.vPeak.textContent = TinyPPI.fmtNits(l1.max);
    el.vAvg.textContent  = TinyPPI.fmtNits(l1.avg);
    el.vAr.textContent   = metrics.aspect ? metrics.aspect.toFixed(2) + ":1" : "—";
    el.vFps.textContent  = metrics.fps_in
      ? metrics.fps_in.toFixed(3).replace(/0+$/, "").replace(/[.]$/, "") : "—";
    el.uFps.textContent  = metrics.fps_drop ? "▼ " + metrics.fps_drop : " ";
  }

  /* --- what the whole title has done ------------------------------------ */

  function renderSession(session) {
    if (metadataPage) {
      el.sessionCard.classList.add("hidden");
      return;
    }
    if (!session || !session.samples) {
      el.sessionCard.classList.add("hidden");
      return;
    }
    el.sessionCard.classList.remove("hidden");
    const T = TinyPPI.T;
    const nits = (value) =>
      (value === null || value === undefined) ? "—" : TinyPPI.fmtNits(value);
    const stats = [
      [T.peak, nits(session.peak), "nits"],
      [T.average, nits(session.avg), "nits"],
      [T.drops, String(session.drops || 0), ""],
      [T.cache_min, (session.cache_min === null || session.cache_min === undefined)
        ? "—" : Math.round(session.cache_min) + "%", ""],
      [T.switches, String(session.switches || 0), ""]
    ];

    /* Only the numbers are written on every pass; the frames stay put. */
    if (el.stats.children.length !== stats.length) {
      el.stats.innerHTML = "";
      for (let index = 0; index < stats.length; index++) {
        const tile = document.createElement("div");
        tile.className = "stat";
        const key = document.createElement("span");
        key.className = "k";
        const value = document.createElement("span");
        value.className = "v mono";
        const unit = document.createElement("span");
        unit.className = "u";
        tile.append(key, value, unit);
        el.stats.append(tile);
      }
    }
    stats.forEach(([name, value, unit], index) => {
      const tile = el.stats.children[index];
      tile.children[0].textContent = name;
      tile.children[1].textContent = value;
      tile.children[2].textContent = unit;
    });
  }

  const EVENT_LABEL = {
    vs10: () => TinyPPI.T.vs10,
    mode: () => TinyPPI.T.ev_mode,
    cache: () => TinyPPI.T.ev_cache,
    drops: () => TinyPPI.T.ev_drops
  };

  /* A transition names two whole VS10 output states -- "SDR BT.709" to
     "DV-LL BT.2020nc" is a realistic width -- while cache and drop events
     carry one short number.  The two need different room, so the row itself
     comes in two shapes (see .event.shift in live-panels.css): a transition never
     shares its line with the label, a value always does. */
  function isTransition(entry) {
    return entry.from !== undefined && entry.to !== undefined;
  }

  function eventText(entry) {
    if (isTransition(entry)) return entry.from + " → " + entry.to;
    if (entry.kind === "cache") return Math.round(entry.value) + "%";
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
      row.className = "event " + entry.kind + (shift ? " shift" : "");
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

  /* --- the chart -------------------------------------------------------- */

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

  function buildRanges() {
    if (el.ranges.dataset.built) return;
    el.ranges.dataset.built = "1";
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
        drawChart();
      });
      el.ranges.append(button);
    }
    markRange();
  }

  function markRange() {
    for (const button of el.ranges.children) {
      button.classList.toggle("on", Number(button.dataset.range) === range);
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
      drawChart();
    }).catch(() => { /* the stream's own retry reports an outage */ })
      .finally(() => { fetching = false; });
  }

  /* Both sources reduced to the same shape: how long ago, and what it was. */
  function series() {
    const now = Date.now() / 1000;
    if (range === HISTORY_SECONDS) {
      return live.map((point) => ({
        age: now - point.t, max: point.max, avg: point.avg
      }));
    }
    if (!past || !past.t || !past.t.length) return [];
    /* The add-on counts from the start of the film and the page from the
       moment the answer arrived; the drift is what puts the two on one axis. */
    const drift = now - pastAt / 1000;
    const points = [];
    for (let index = 0; index < past.t.length; index++) {
      if (past.max[index] === null || past.max[index] === undefined) continue;
      points.push({
        age: (past.now - past.t[index]) + drift,
        max: past.max[index],
        avg: past.avg[index] === null || past.avg[index] === undefined
          ? past.max[index] : past.avg[index]
      });
    }
    return points;
  }

  function renderChart(metrics) {
    if (!metadataPage) {
      el.chartCard.classList.add("hidden");
      return;
    }
    const l1 = metrics.l1 || {};
    if (l1.max === null || l1.max === undefined) {
      el.chartCard.classList.add("hidden");
      return;
    }
    el.chartCard.classList.remove("hidden");
    buildRanges();

    const now = Date.now() / 1000;
    live.push({ t: now, min: l1.min || 0, max: l1.max || 0, avg: l1.avg || 0 });
    while (live.length && now - live[0].t > HISTORY_SECONDS) live.shift();

    if (range !== HISTORY_SECONDS) fetchHistory(false);
    drawChart();
  }

  function drawChart() {
    const canvas = el.chart;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    if (canvas.width !== Math.round(width * ratio) ||
        canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }

    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const style = getComputedStyle(document.documentElement);
    const accent  = style.getPropertyValue("--accent").trim() || "#4fc3f7";
    const line    = style.getPropertyValue("--line").trim() || "#242c36";
    const accent2 = style.getPropertyValue("--accent-2").trim() || "#82b1ff";
    const dim     = style.getPropertyValue("--dim").trim() || "#5d6875";

    const padLeft = 34, padRight = 6, padTop = 8, padBottom = 6;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;
    const y = (nits) => padTop + plotH * (1 - logScale(nits));

    /* Gridlines, one per decade. */
    ctx.strokeStyle = line;
    ctx.fillStyle = dim;
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

    const points = series();
    if (points.length < 2) return;

    /* The window is whichever range is on, and for the whole title it is as
       far back as the samples go. */
    const span = range || Math.max(HISTORY_SECONDS, points[0].age);
    const x = (age) => padLeft + plotW * (1 - Math.min(1, age / span));

    /* Peak, as an area down to the floor.  The min of an L1 block sits near
       zero on almost every frame, so a min-max band would be full height and
       say nothing; the peak against the average is where the grade shows. */
    ctx.beginPath();
    ctx.moveTo(x(points[0].age), padTop + plotH);
    for (const point of points) ctx.lineTo(x(point.age), y(point.max));
    ctx.lineTo(x(points[points.length - 1].age), padTop + plotH);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    fill.addColorStop(0, accent);
    fill.addColorStop(1, "transparent");
    ctx.globalAlpha = 0.28;
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.globalAlpha = 1;

    const trace = (key, color, thickness, dash) => {
      ctx.setLineDash(dash || []);
      ctx.beginPath();
      points.forEach((point, index) => {
        const px = x(point.age), py = y(point[key]);
        index === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = thickness;
      ctx.lineJoin = "round";
      ctx.stroke();
      ctx.setLineDash([]);
    };

    /* The peak is the solid line the fill belongs to; the average is dashed, so
       the two never read as one band even where they run close together. */
    trace("max", accent, 1.7);
    trace("avg", accent2, 1.5, [4, 3]);
  }

  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawChart, 120);
  });

  /* --- what a page calls ------------------------------------------------ */

  function strings(T) {
    el.controlLabel.textContent = T.controls;
    $("kPeak").textContent = T.peak;
    $("kAvg").textContent = T.average;
    $("kAr").textContent = T.aspect;
    $("kFps").textContent = T.fps;
    $("chartTitle").textContent = T.chart;
    $("chartScale").textContent = "nits · log";
    $("sessionTitle").textContent = T.session;
    $("eventsTitle").textContent = T.events;
    for (const button of el.ranges.children) {
      button.textContent = T[button.dataset.key] || button.dataset.key;
    }
  }

  /* Everything the panels show comes out of one snapshot, and a snapshot that
     says nothing is playing takes them off the page rather than leaving the
     last frame of a film that has ended standing there. */
  function update(snapshot) {
    if (!snapshot || !snapshot.playing) {
      const cards = [el.nowCard, el.tiles, el.chartCard,
                     el.sessionCard, el.eventsCard];
      for (const node of cards) node.classList.add("hidden");
      live = [];
      past = null;
      pastSeq = -1;
      posterTag = "";
      trackKey = "";
      el.controlDrawer.open = false;
      return;
    }
    el.nowCard.classList.remove("hidden");
    renderNow(snapshot);
    renderTransport(snapshot);
    renderTiles(snapshot.metrics || {});
    renderChart(snapshot.metrics || {});
    renderSession(snapshot.session);

    /* The event list travels apart from the snapshot -- it would otherwise be
       sent five times a second to say nothing.  The count in the summary is
       what says there is something new to fetch. */
    const session = snapshot.session || {};
    if (session.seq !== undefined && session.seq !== pastSeq) fetchHistory(true);
  }

  window.TinyPPI.panels = { strings, update };

})();
