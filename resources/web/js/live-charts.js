// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The luminance chart of the live panels, and the history it is drawn from.

   The last minute is sampled here, one L1 reading per snapshot; the longer
   ranges come from the add-on, which has been sampling since the film
   started (/api/history).  That answer carries the title's events as well,
   so it is fetched here and handed on to whoever made the chart.

   js/live-panels.js builds the card and hands this its nodes (create).
   Loaded after core.js and before js/live-panels.js.
=========================================================================== */

window.TinyPPICharts = (function () {

  /* How much of the past the live buffer holds, in seconds.  It is what the
     one-minute range draws; the longer ones come from the add-on, which has
     been sampling since the film started. */
  const HISTORY_SECONDS = 60;

  /* How often a longer range is fetched again while it is on screen. */
  const HISTORY_REFRESH = 5000;

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
      dim:     colour("--dim", "#5d6875")
    };
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

  /* A chart of its own for the nodes in *el* (chartCard, chart, ranges).
     *onHistory* is told each history the add-on answers with. */
  function create(el, onHistory) {

    let live = [];        /* {t, max, avg} for the last HISTORY_SECONDS       */
    let past = null;      /* the add-on's own history, when a range needs it  */
    let pastAt = 0;       /* when that arrived, to age it as time goes on     */
    let pastSeq = -1;     /* the event count it was fetched at                */
    let fetching = false;
    let lastTry = 0;      /* when one was last attempted, failures included   */
    let range = HISTORY_SECONDS;

    /* Every chart on the page reads the same range buttons.  There is one
       chart, the luminance one on the metadata tab. */
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
       on a slow tick while a long range is on screen.  What else the page
       shows of the answer -- the events, the count of switches -- is the
       caller's to draw (*onHistory*), before the chart is. */
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
        onHistory(data);
        drawCharts();
      }).catch(() => { /* the stream's own retry reports an outage */ })
        .finally(() => { fetching = false; });
    }

    /* Both luminance sources reduced to the same shape: how long ago, and what
       was read.  A sample without the required L1 value is left out rather than
       drawn as zero, which keeps non-Dolby-Vision titles out of this chart. */
    function series(required) {
      const now = Date.now() / 1000;
      const known = (value) => value !== null && value !== undefined;
      if (range === HISTORY_SECONDS) {
        const points = [];
        for (const point of live) {
          if (!known(point[required])) continue;
          points.push({
            age: now - point.t, max: point.max, avg: point.avg
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
          avg: known(past.avg[index]) ? past.avg[index] : past.max[index]
        });
      }
      return points;
    }

    /* --- what each page charts -------------------------------------------- */

    /* One live L1 sample per metadata snapshot. */
    function recordSample(metrics) {
      const l1 = metrics.l1 || {};
      live.push({
        t: Date.now() / 1000,
        max: (l1.max === null || l1.max === undefined) ? null : l1.max,
        avg: (l1.avg === null || l1.avg === undefined) ? l1.max : l1.avg
      });
      const now = Date.now() / 1000;
      while (live.length && now - live[0].t > HISTORY_SECONDS) live.shift();
    }

    function renderCharts(metrics) {
      recordSample(metrics);

      /* The luminance chart needs an RPU to read. */
      const l1 = metrics.l1 || {};
      const has = l1.max !== null && l1.max !== undefined;
      if (!has) {
        el.chartCard.classList.add("hidden");
        return;
      }
      el.chartCard.classList.remove("hidden");
      buildRanges(el.ranges);

      if (range !== HISTORY_SECONDS) fetchHistory(false);
      drawCharts();
    }

    /* How far back the drawing goes: whichever range is on, and for the whole
       title as far back as the samples themselves. */
    function windowFor(points) {
      return range || Math.max(HISTORY_SECONDS, points[0].age);
    }

    /* A chart on a tab that is not in front has no size, and prepare() leaves
       it alone; the tab draws it again when it comes forward (see draw). */
    function drawCharts() {
      drawLuminance();
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

    /* The charts' colours come from the card they are drawn in, which the
       adaptive theme repaints from the poster.  A canvas cannot notice that on
       its own, so js/cover-tint.js says when it has happened. */
    document.addEventListener("tinyppi-tint", () => drawCharts());

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

    /* The range buttons, named again in the reader's language. */
    function strings(T) {
      for (const bar of rangeBars) {
        for (const button of bar.children) {
          button.textContent = T[button.dataset.key] || button.dataset.key;
        }
      }
    }

    /* The last minute, dropped once the title has ended. */
    function clear() {
      live = [];
    }

    /* The history, dropped once the ended title's is no longer kept. */
    function forget() {
      past = null;
      pastSeq = -1;
    }

    return {
      render: renderCharts, draw: drawCharts, fetch: fetchHistory, peak, strings, clear, forget,
      history: () => past, seq: () => pastSeq
    };
  }

  return { create };

})();
