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

  /* --- the report ------------------------------------------------------- */

  /* A film title as a file name: what a file system might object to taken
     out, and the spaces closed up, so the download arrives under a name the
     viewer can find again rather than one their browser had to rescue. */
  function fileSafe(title) {
    return String(title)
      .replace(/[\\\/:*?"<>|]+/g, "")
      .trim()
      .replace(/\s+/g, "_")
      .replace(/_{2,}/g, "_")
      .replace(/^[._]+|[._]+$/g, "");
  }

  /* Which column a reading starts in, counted from the left edge of the line,
     one-based.  Fixed rather than fitted to the longest name of whatever
     section is being written, so that every value in a saved report stands in
     the same column and the file can be read down its right-hand side. */
  const REPORT_COLUMN = 30;

  /* One line of a report: two spaces, the name, and the reading in the column
     above.  A name too long for that keeps its two spaces and pushes its own
     reading out rather than losing the gap between the two. */
  function reportLine(label, value) {
    const head = "  " + String(label);
    const pad  = REPORT_COLUMN - 1;
    return (head.length < pad ? head.padEnd(pad) : head + "  ") + value;
  }

  /* Hand *report* to the viewer as TinyPPI_<title>_<tail>.txt, with either
     part left out when there is none -- *tail* is what tells one page's report
     from the other's when both are saved for the same film.

     The clipboard where the browser allows it, a file where it does not:
     clipboard access needs a secure context, which plain http over a LAN is
     not, and failing there silently would look like a button that does
     nothing.  Both pages copy the same way, so they copy from here.  */
  function copyReport(report, title, tail) {
    if (!report) return;
    const named = fileSafe(title || "");
    const name = "TinyPPI" + (named ? "_" + named : "") + (tail ? "_" + tail : "");
    return Promise.resolve()
      .then(() => navigator.clipboard.writeText(report))
      .then(() => toast(T.copied))
      .catch(() => {
        const url = URL.createObjectURL(new Blob([report], { type: "text/plain" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = name + ".txt";
        /* In the document before it is clicked and out again after: a click on
           an anchor no document holds is ignored outright by some browsers.
           The address it points at is dropped a moment later rather than at
           once, because revoking it in the same breath as the click can leave
           the download reaching for a blob that is already gone. */
        link.style.display = "none";
        document.body.append(link);
        link.click();
        setTimeout(() => {
          link.remove();
          URL.revokeObjectURL(url);
        }, 2000);
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

  /* --- commands --------------------------------------------------------- */

  /* One transport command to the add-on.  Resolves to true when the player
     did it, false when it would not -- a page that shows a button is the page
     that has to say whether the button worked. */
  async function command(action, value) {
    try {
      const response = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "X-TinyPPI-Token": token },
        body: JSON.stringify({ action, value })
      });
      if (response.status === 401) { toast(T.token_bad, true); askToken(); return false; }
      return response.ok;
    } catch (_) {
      return false;
    }
  }

  /* Whatever the stream and the images need: the token travels in the URL for
     everything a browser cannot put a header on. */
  async function getJSON(url) {
    const response = await fetch(withToken(url));
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  return {
    T, $, boot, toast, setStatus, fmtNits, prettyHdr, askToken,
    copyReport, reportLine, command, getJSON, withToken,
    get token() { return token; }
  };

})();


/* ===========================================================================
   The live panels, for whichever page asks for them.

   What is playing -- with its poster, the logos the overlay draws for the
   format, and the speaker layout -- the four figures worth a glance, the
   luminance chart, what the whole title has done so far, and the transport
   row.  The dashboard opens on them and the metadata window shows the same,
   so a second screen left on either page says what the film is doing.

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
      '<div class="channels hidden" id="channels">' +
        '<img class="layer" id="chLayer" alt=""><img class="active" id="chActive" alt="">' +
      '</div>' +
      /* The bar and the buttons take a row of their own under all three, so
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
        '<div class="transport hidden" id="transport"></div>' +
        '<div class="tracks hidden" id="tracks"></div>' +
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
    channels: $("channels"), chLayer: $("chLayer"), chActive: $("chActive"),
    track: $("track"), bar: $("bar"), tElapsed: $("tElapsed"), tTotal: $("tTotal"),
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
    if (snapshot.paused) badges.push({ text: "❚❚", alt: true });
    el.badges.innerHTML = "";
    for (const badge of badges) {
      const node = document.createElement("span");
      node.className = badge.alt ? "badge alt" : "badge";
      node.textContent = badge.text;
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

    if (!logos.channels) {
      el.channels.classList.add("hidden");
      return;
    }
    if (el.chActive.dataset.name !== logos.channels) {
      el.chActive.dataset.name = logos.channels;
      el.chActive.src = "/media/" + logos.channels;
      el.chLayer.src = logos.layer ? "/media/" + logos.layer : "";
    }
    el.channels.classList.remove("hidden");
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
      node.addEventListener("click", handler);
      return node;
    };

    /* Two rows of their own rather than one that wraps: five even keys, then
       stop, mute and the slider.  A wrapping row leaves whatever did not fit
       stranded on a line of its own, which on a phone is most of them. */
    const keys = document.createElement("div");
    keys.className = "tkeys";
    keys.append(
      button("−1m", "", () => TinyPPI.command("seek", -60)),
      button("−10s", "", () => TinyPPI.command("seek", -10)),
      /* The label says what pressing it does, so it follows the player:
         ❚❚ while it plays, ▶ while it is paused. */
      button("❚❚", TinyPPI.T.playpause,
             () => TinyPPI.command("playpause"), "primary"),
      button("+10s", "", () => TinyPPI.command("seek", 10)),
      button("+1m", "", () => TinyPPI.command("seek", 60))
    );

    const rest = document.createElement("div");
    rest.className = "tvol";
    rest.append(button("⏹", TinyPPI.T.stop, () => TinyPPI.command("stop")));

    const mute = button("🔊", TinyPPI.T.mute, () => TinyPPI.command("mute"), "mute");
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
    rest.append(mute, slider);
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
      el.transport.classList.add("hidden");
      el.tracks.classList.add("hidden");
      el.track.classList.remove("seekable");
      return;
    }
    buildTransport();
    el.transport.classList.remove("hidden");
    el.track.classList.add("seekable");

    const play = el.transport.querySelector(".tbtn.primary");
    if (play) play.textContent = snapshot.paused ? "▶" : "❚❚";

    const slider = $("volume");
    const mute = el.transport.querySelector(".mute");
    if (slider && controls.volume !== null && controls.volume !== undefined) {
      /* Not while a finger is on it: the snapshot is a fifth of a second
         behind, and writing it back would drag the handle out from under. */
      if (Date.now() - volumeHeld > 1500) slider.value = controls.volume;
    }
    if (mute) {
      mute.classList.toggle("on", !!controls.muted);
      mute.textContent = controls.muted ? "🔇" : "🔊";
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

  function eventText(entry) {
    if (entry.from !== undefined && entry.to !== undefined) {
      return entry.from + "  →  " + entry.to;
    }
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
      const row = document.createElement("div");
      row.className = "event " + entry.kind;
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
      renderEvents(data.events);
      el.eventsCard.classList.remove("hidden");
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
