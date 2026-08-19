"use strict";

/* ===========================================================================
   The live connection both dashboard pages sit on.

   One EventSource carries the snapshot the add-on's producer builds, so a page
   never polls.  Everything to do with reaching the add-on lives here -- the
   access token, the reconnect, the status light, the toast and the token
   dialog -- and a page supplies only what it does with a snapshot once it
   arrives.

   A page calls TinyPPI.boot({onState, onStrings}) and gets called back; it
   never touches the EventSource itself.
=========================================================================== */

window.TinyPPI = (function () {

  const TOKEN_KEY = "tinyppi.token";

  /* Chrome strings, replaced by the localized set from /api/hello.  The
     English here is only what shows in the instant before that answers. */
  const T = {
    connected: "Connected", connecting: "Connecting…", offline: "Disconnected",
    metadata: "Dolby Vision metadata view",
    no_metadata: "No Dolby Vision metadata", no_metadata_text: "",
    idle_title: "Nothing is playing", idle_text: "",
    peak: "Peak", average: "Average", aspect: "Aspect ratio", fps: "FPS",
    chart: "Frame luminance", active_area: "Active picture", vs10: "VS10 output",
    output: "Output", copy: "Copy report", copied: "Copied", awake: "Keep awake",
    token_title: "Access token", token_text: "", save: "Save", cancel: "Cancel",
    token_bad: "Wrong or missing token", switching: "Switching…",
    switched: "Switched", switch_failed: "Switching failed"
  };

  const $ = (id) => document.getElementById(id);

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let onState = null;
  let source = null;
  let retryAt = 1000;
  let statusEl = null;
  let statusText = null;
  let toastEl = null;
  let dialogEl = null;
  let tokenInput = null;

  /* --- chrome ----------------------------------------------------------- */

  /* The toast and the token dialog are injected rather than repeated in the
     markup of every page: they belong to this module, and a page that forgets
     to copy them would lose the way back in after a token change. */
  function injectChrome() {
    const holder = document.createElement("div");
    holder.innerHTML =
      '<div id="toast" role="status" aria-live="polite"></div>' +
      '<dialog id="tokenDialog"><form method="dialog">' +
      '<h3 id="dlgTitle"></h3><p id="dlgText"></p>' +
      '<input id="tokenInput" autocomplete="off" autocapitalize="characters" ' +
      'spellcheck="false" maxlength="32" aria-labelledby="dlgTitle">' +
      '<div class="dlgrow"><button value="cancel" id="dlgCancel" type="submit"></button>' +
      '<button value="ok" id="dlgOk" type="submit"></button></div>' +
      '</form></dialog>';
    while (holder.firstChild) document.body.append(holder.firstChild);

    toastEl    = $("toast");
    dialogEl   = $("tokenDialog");
    tokenInput = $("tokenInput");

    dialogEl.addEventListener("close", () => {
      if (dialogEl.returnValue !== "ok") return;
      token = tokenInput.value.trim().toUpperCase();
      localStorage.setItem(TOKEN_KEY, token);
      /* The stream carries the token in its URL -- an EventSource cannot send
         a header -- so a new token means a new connection. */
      connect();
    });

    const button = $("tokenBtn");
    if (button) button.addEventListener("click", askToken);
  }

  function applyChromeStrings() {
    $("dlgTitle").textContent  = T.token_title;
    $("dlgText").textContent   = T.token_text;
    $("dlgOk").textContent     = T.save;
    $("dlgCancel").textContent = T.cancel;
  }

  /* --- helpers ---------------------------------------------------------- */

  function withToken(url) {
    return token
      ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token)
      : url;
  }

  let toastTimer = 0;
  function toast(message, bad) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.toggle("bad", !!bad);
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2600);
  }

  function setStatus(kind, text) {
    if (!statusEl) return;
    statusEl.dataset.state = kind;
    statusText.textContent = text;
  }

  function fmtNits(value) {
    if (value === null || value === undefined) return "—";
    if (value >= 1000) return Math.round(value).toLocaleString();
    if (value >= 100)  return value.toFixed(0);
    if (value >= 10)   return value.toFixed(1);
    if (value >= 1)    return value.toFixed(2);
    return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }

  /* The add-on publishes these as boolean-parser-safe tokens (hdr10plus for
     HDR10+, dolbyvision for Dolby Vision) and writes none at all for SDR;
     print them the way they are written everywhere else. */
  function prettyHdr(value) {
    const map = {
      sdr: "SDR", hdr10: "HDR10", hdr10plus: "HDR10+", hlg: "HLG",
      dolbyvision: "Dolby Vision"
    };
    const key = String(value || "sdr").toLowerCase().replace(/[^a-z0-9+]/g, "");
    return map[key] || value;
  }

  function askToken() {
    tokenInput.value = token;
    dialogEl.showModal();
    tokenInput.focus();
    tokenInput.select();
  }

  /* --- stream ----------------------------------------------------------- */

  function connect() {
    if (source) { source.close(); source = null; }
    setStatus("wait", T.connecting);
    source = new EventSource(withToken("/api/stream"));

    source.addEventListener("open", () => {
      retryAt = 1000;
      setStatus("live", T.connected);
    });

    source.addEventListener("state", (event) => {
      setStatus("live", T.connected);
      try {
        if (onState) onState(JSON.parse(event.data));
      } catch (_) { /* skip a bad frame */ }
    });

    source.addEventListener("bye", () => {
      /* The add-on is shutting the server down; stop hammering it. */
      source.close();
      source = null;
      setStatus("down", T.offline);
      setTimeout(connect, 5000);
    });

    source.addEventListener("error", () => {
      setStatus("down", T.offline);
      /* EventSource retries on its own, but a 401 closes it for good: check
         whether the server is asking for a token before giving up on it. */
      if (!source || source.readyState !== EventSource.CLOSED) return;
      source = null;
      const again = () => {
        setTimeout(connect, retryAt);
        retryAt = Math.min(retryAt * 2, 15000);
      };
      fetch(withToken("/api/state")).then((response) => {
        if (response.status === 401) { toast(T.token_bad, true); askToken(); return; }
        again();
      }).catch(again);
    });
  }

  /* --- boot ------------------------------------------------------------- */

  async function boot(options) {
    options = options || {};
    onState = options.onState || null;

    statusEl   = $("status");
    statusText = $("statusText");
    injectChrome();
    applyChromeStrings();
    if (options.onStrings) options.onStrings(T);

    try {
      const hello = await (await fetch("/api/hello")).json();
      Object.assign(T, hello.strings || {});
      applyChromeStrings();
      if (options.onStrings) options.onStrings(T, hello);
      if (hello.auth_read && !token) { askToken(); return; }
    } catch (_) { /* the stream's own retry will report the outage */ }

    connect();
  }

  return {
    T, $, boot, toast, setStatus, fmtNits, prettyHdr, askToken,
    get token() { return token; }
  };

})();


/* ===========================================================================
   The live panels, for whichever page asks for them.

   What is playing, the four figures worth a glance, and the last minute of
   frame luminance -- the dashboard opens on them, and the metadata window
   shows the same three, so a second screen left on that page still says what
   the film is doing.

   Here rather than in a file of its own for the same reason the toast and the
   token dialog are: the pages reach this server through an allowlist of
   routes built when the service starts (see web/server.py _static_routes), so
   a new file is a file the running add-on has no route to until Kodi is
   restarted, while this one is already served.

   A page opts in by putting <div id="live"></div> where the panels belong;
   the markup and the drawing are here, the styling is in style.css.  It then
   hands the snapshot on through TinyPPI.panels.update() and the localized
   strings through .strings().
=========================================================================== */

(function () {

  const host = document.getElementById("live");
  if (!host) return;

  /* How much of the past the chart holds, in seconds.  The heading names the
     same span, so the two move together. */
  const HISTORY_SECONDS = 60;

  host.innerHTML =
    '<section class="card" id="nowCard">' +
      '<div class="now">' +
        '<div class="badges" id="badges"></div>' +
        '<h1 id="title">—</h1>' +
        '<p class="file mono hidden" id="file"></p>' +
        '<div class="progress">' +
          '<div class="track"><i id="bar"></i></div>' +
          '<div class="times mono">' +
            '<span id="tElapsed">--:--</span><span id="tTotal">--:--</span>' +
          '</div>' +
        '</div>' +
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
      '<h2 id="chartTitle"></h2>' +
      '<div class="chartwrap">' +
        '<canvas id="chart" role="img"></canvas>' +
        '<div class="legend">' +
          '<span><i class="swatch band"></i>Max</span>' +
          '<span><i class="swatch avg"></i>Ø</span>' +
          '<span id="chartScale" style="margin-left:auto"></span>' +
        '</div>' +
      '</div>' +
    '</section>';

  const $ = (id) => document.getElementById(id);

  const el = {
    nowCard: $("nowCard"), badges: $("badges"), title: $("title"), file: $("file"),
    bar: $("bar"), tElapsed: $("tElapsed"), tTotal: $("tTotal"),
    tiles: $("tiles"), tPeak: $("tPeak"), tAvg: $("tAvg"),
    vPeak: $("vPeak"), vAvg: $("vAvg"), vAr: $("vAr"),
    vFps: $("vFps"), uFps: $("uFps"),
    chartCard: $("chartCard"), chart: $("chart")
  };

  let history = [];   /* {t, min, max, avg}, the last HISTORY_SECONDS of them */

  /* --- what is playing -------------------------------------------------- */

  function renderNow(snapshot) {
    el.title.textContent = snapshot.title || "—";
    if (snapshot.filename) {
      el.file.textContent = snapshot.filename;
      el.file.classList.remove("hidden");
    } else {
      el.file.classList.add("hidden");
    }

    /* An empty source type is SDR, not "unknown": the add-on publishes a token
       only for the HDR formats (see publish_hdr_type), which is the same thing
       the VS10 buttons branch on. */
    const badges = [{ text: TinyPPI.prettyHdr(snapshot.hdr_type || "sdr"), alt: false }];
    if (snapshot.effective && snapshot.effective !== snapshot.hdr_type) {
      badges.push({ text: "→ " + TinyPPI.prettyHdr(snapshot.effective), alt: true });
    }
    if (snapshot.paused) badges.push({ text: "❚❚", alt: true });
    el.badges.innerHTML = "";
    for (const badge of badges) {
      const node = document.createElement("span");
      node.className = badge.alt ? "badge alt" : "badge";
      node.textContent = badge.text;
      el.badges.appendChild(node);
    }

    const progress = (snapshot.metrics || {}).progress;
    el.bar.style.width = (progress === null || progress === undefined ? 0 : progress) + "%";
    el.tElapsed.textContent = snapshot.time || "--:--";
    el.tTotal.textContent = snapshot.duration || "--:--";
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

  /* --- the last minute -------------------------------------------------- */

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

  function renderChart(metrics) {
    const l1 = metrics.l1 || {};
    if (l1.max === null || l1.max === undefined) {
      el.chartCard.classList.add("hidden");
      return;
    }
    el.chartCard.classList.remove("hidden");

    const now = Date.now() / 1000;
    history.push({ t: now, min: l1.min || 0, max: l1.max || 0, avg: l1.avg || 0 });
    while (history.length && now - history[0].t > HISTORY_SECONDS) history.shift();

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

    if (history.length < 2) return;

    const now = Date.now() / 1000;
    const x = (t) => padLeft + plotW * (1 - Math.min(1, (now - t) / HISTORY_SECONDS));

    /* Peak, as an area down to the floor.  The min of an L1 block sits near
       zero on almost every frame, so a min-max band would be full height and
       say nothing; the peak against the average is where the grade shows. */
    ctx.beginPath();
    ctx.moveTo(x(history[0].t), padTop + plotH);
    for (const point of history) ctx.lineTo(x(point.t), y(point.max));
    ctx.lineTo(x(history[history.length - 1].t), padTop + plotH);
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
      history.forEach((point, index) => {
        const px = x(point.t), py = y(point[key]);
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
    $("kPeak").textContent = T.peak;
    $("kAvg").textContent = T.average;
    $("kAr").textContent = T.aspect;
    $("kFps").textContent = T.fps;
    $("chartTitle").textContent = T.chart;
    $("chartScale").textContent = "nits · log";
  }

  /* Everything the three show comes out of one snapshot, and a snapshot that
     says nothing is playing takes them off the page rather than leaving the
     last frame of a film that has ended standing there. */
  function update(snapshot) {
    if (!snapshot || !snapshot.playing) {
      el.nowCard.classList.add("hidden");
      el.tiles.classList.add("hidden");
      el.chartCard.classList.add("hidden");
      history = [];
      return;
    }
    el.nowCard.classList.remove("hidden");
    renderNow(snapshot);
    renderTiles(snapshot.metrics || {});
    renderChart(snapshot.metrics || {});
  }

  window.TinyPPI.panels = { strings, update };

})();
