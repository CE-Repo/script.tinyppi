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
  const DISCLOSURE_KEY = "tinyppi.disclosure.";

  /* Chrome strings, replaced by the localized set from /api/hello.  The
     English here is only what shows in the instant before that answers. */
  const T = {
    connected: "Connected", connecting: "Connecting…", offline: "Disconnected",
    menu: "Menu",
    metadata: "Dolby Vision metadata view", metadata_section: "Metadata",
    no_metadata: "No Dolby Vision metadata", no_metadata_text: "",
    idle_title: "Nothing is playing", idle_text: "",
    peak: "Peak", average: "Average", aspect: "Aspect ratio", fps: "FPS",
    drops: "Frame drops", switches: "Switches", metrics: "Metrics",
    player_cache: "Player cache", audio_track: "Audio track",
    warnings: "Warnings",
    cache_low: "Player cache below 90%", cache_recovered: "Player cache recovered",
    temperature: "Temperature", processor: "Processor", subtitles: "Subtitles", off: "Off",
    chart: "Frame luminance", active_area: "Active picture", vs10: "VS10 output",
    output: "Output", copy: "Copy report", copied: "Copied",
    controls: "Playback controls",
    token_title: "Access token", token_text: "", save: "Save", cancel: "Cancel",
    yes: "Yes", no: "No",
    token_bad: "Wrong or missing token", busy: "Too many connections",
    switching: "Switching…",
    switched: "Switched", switch_failed: "Switching failed",
    theme_dark: "Dark", theme_adaptive: "Dark (adaptive)",
    theme_midnight: "Midnight", theme_menu: "Choose a theme",
    theme_switch: "Switch to {name} (hold for the full list)",
    tint_label: "Intensity", tint_subtle: "Subtle", tint_standard: "Standard",
    tint_strong: "Strong",
    last_played: "Last played", summary: "Summary",
    events: "Events", events_empty: "No events yet",
    ev_mode: "Display mode",
    range_1m: "1 min", range_10m: "10 min", range_all: "All"
  };

  const $ = (id) => document.getElementById(id);

  function disclosureState(key, fallback) {
    try {
      const value = localStorage.getItem(DISCLOSURE_KEY + key);
      return value === null ? !!fallback : value === "1";
    } catch (_) {
      return !!fallback;
    }
  }

  function setDisclosureState(key, open) {
    try { localStorage.setItem(DISCLOSURE_KEY + key, open ? "1" : "0"); }
    catch (_) {}
  }

  function bindDisclosure(node, key, fallback) {
    node.open = disclosureState(key, fallback);
    node.addEventListener("toggle", () => setDisclosureState(key, node.open));
    return node;
  }

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let onState = null;
  let source = null;
  let retryAt = 1000;
  let retryTimer = 0;
  /* The last whole snapshot.  Everything after the first frame of a
     connection arrives as a delta measured against it (see _snapshot_delta in
     web/server.py), so it is what those are applied to. */
  let base = null;
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
      if (dialogEl.returnValue !== "ok") {
        /* Dismissed rather than answered.  Something has to stay pending, or
           a page whose token was only asked for by mistake never comes back. */
        if (!source) scheduleRetry(5000);
        return;
      }
      token = tokenInput.value.trim().toUpperCase();
      localStorage.setItem(TOKEN_KEY, token);
      /* The stream carries the token in its URL -- an EventSource cannot send
         a header -- so a new token means a new connection. */
      connect();
    });

    const button = $("tokenBtn");
    if (button) button.addEventListener("click", askToken);
    bindActionMenu();
  }

  /* The top bar keeps its less frequent actions behind one compact key.  The
     theme button is injected later by theme.js, but it lands inside this same
     inert container and therefore follows the state established here. */
  function bindActionMenu() {
    const holder = $("actionMenu");
    const items = $("actionMenuItems");
    const toggle = $("actionMenuToggle");
    if (!holder || !items || !toggle) return;
    let closeTimer = 0;

    /* The menu shuts itself this long after the last thing anyone did to it,
       rather than this long after it opened: a countdown from opening runs out
       under a finger that is still choosing.  The same idea, and the same
       shape, as the theme menu's own idle close (see js/theme.js). */
    const IDLE_MS = 3000;
    const ACTIVITY = ["pointermove", "pointerdown", "keydown", "focusin"];

    /* The theme menu counts as part of this one: it is opened from a button in
       here but hangs off <body> (see js/theme.js), so a pointer inside it is a
       pointer that has not left this menu. */
    function inside(node) {
      return holder.contains(node) ||
             !!(node && node.closest && node.closest(".theme-menu.open"));
    }

    function keepOpen(event) {
      if (event && !inside(event.target)) return;
      clearTimeout(closeTimer);
      closeTimer = setTimeout(() => setOpen(false), IDLE_MS);
    }

    function setOpen(open) {
      clearTimeout(closeTimer);
      closeTimer = 0;
      holder.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      items.setAttribute("aria-hidden", open ? "false" : "true");
      items.inert = !open;
      for (const kind of ACTIVITY) {
        if (open) document.addEventListener(kind, keepOpen, true);
        else document.removeEventListener(kind, keepOpen, true);
      }
      if (open) keepOpen();
    }

    toggle.addEventListener("click", () => {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("click", (event) => {
      if (!holder.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  function applyChromeStrings() {
    /* The theme button and its menu are built before this file runs and carry
       their own English until the localized set arrives; see js/theme.js. */
    if (window.TinyPPITheme) TinyPPITheme.strings(T);
    $("dlgTitle").textContent  = T.token_title;
    $("dlgText").textContent   = T.token_text;
    $("dlgOk").textContent     = T.save;
    $("dlgCancel").textContent = T.cancel;
    const tokenButton = $("tokenBtn");
    if (tokenButton) {
      tokenButton.title = T.token_title;
      tokenButton.setAttribute("aria-label", T.token_title);
    }
    const actionToggle = $("actionMenuToggle");
    if (actionToggle) {
      actionToggle.title = T.menu;
      actionToggle.setAttribute("aria-label", T.menu);
    }
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
    statusEl.title = text;
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

  /* Presence readings use neutral markers on the wire.  On screen they become
     local SVG images; reports get localized words so copied text remains
     meaningful outside the dashboard. */
  function renderValue(node, value) {
    const parts = String(value == null ? "" : value).split(/([✔✘])/);
    node.replaceChildren();
    for (const part of parts) {
      if (part !== "✔" && part !== "✘") {
        if (part) node.append(document.createTextNode(part));
        continue;
      }
      const yes = part === "✔";
      const word = yes ? (T.yes || "Yes") : (T.no || "No");
      const image = document.createElement("img");
      image.className = "presence-icon";
      image.src = yes ? "/icons/yes.svg" : "/icons/no.svg";
      image.alt = word;
      image.title = word;
      node.append(image);
    }
  }

  function plainValue(value) {
    return String(value == null ? "" : value)
      .replace(/✔/g, T.yes || "Yes")
      .replace(/✘/g, T.no || "No");
  }

  function askToken() {
    /* The stream and /api/hello can both find out that a token is wanted, and
       within a moment of each other; the first one to ask keeps the dialog. */
    if (!dialogEl || dialogEl.open) return;
    tokenInput.value = token;
    dialogEl.showModal();
    tokenInput.focus();
    tokenInput.select();
  }

  /* --- stream ----------------------------------------------------------- */

  function stopRetry() {
    clearTimeout(retryTimer);
    retryTimer = 0;
  }

  function scheduleRetry(delay) {
    stopRetry();
    /* Nothing is retried out of sight; coming back into it reconnects at once
       (see the visibility handler below). */
    if (document.hidden) return;
    retryTimer = setTimeout(connect, delay);
  }

  function backOff() {
    setStatus("down", T.offline);
    scheduleRetry(retryAt);
    retryAt = Math.min(retryAt * 2, 15000);
  }

  /* Close the stream and forget the state it was carrying: a fresh connection
     always opens with a whole snapshot, so nothing may be patched onto what an
     older one left behind. */
  function disconnect() {
    stopRetry();
    if (source) { source.close(); source = null; }
    base = null;
  }

  function frame(event) {
    try { return JSON.parse(event.data); }
    catch (_) { return null; }   /* skip a bad frame */
  }

  function deliver(snapshot) {
    setStatus("live", T.connected);
    if (!onState) return;
    try { onState(snapshot); }
    catch (_) { /* a page that throws must not take the stream with it */ }
  }

  /* --- delta frames ------------------------------------------------------ */

  /* What the add-on sends after the first frame is only what moved.  The two
     long lists are patched by row where the list itself still has the same
     shape, and replaced outright where it does not -- rows cannot be written
     into a card the page has not been told about yet. */
  function merge(snapshot, delta) {
    const next = Object.assign({}, snapshot, delta.set || {});
    for (const key of delta.del || []) delete next[key];
    next.seq = delta.seq;
    next.groups = mergeGroups(snapshot.groups, delta.groups);
    next.metadata = mergeRows(snapshot.metadata, delta.metadata);
    return next;
  }

  function mergeGroups(groups, patch) {
    if (patch === undefined) return groups;
    if (Array.isArray(patch)) return patch;
    const moved = new Map();
    for (const row of patch.rows || []) moved.set(row[0], row);
    if (!moved.size) return groups;
    return (groups || []).map((group) => ({
      ...group,
      rows: (group.rows || []).map((row) => {
        const change = moved.get(row.id);
        return change ? { ...row, value: change[1], detail: change[2] } : row;
      })
    }));
  }

  /* The metadata list is patched by position rather than by name: its rows
     have no ids, and the shape check on the other side is what guarantees the
     positions still mean the same thing. */
  function mergeRows(rows, patch) {
    if (patch === undefined) return rows;
    if (Array.isArray(patch)) return patch;
    const next = (rows || []).slice();
    for (const [at, value] of patch.rows || []) {
      const row = next[at];
      if (!row) continue;
      next[at] = Array.isArray(value)
        ? { ...row, cells: value } : { ...row, value: value };
    }
    return next;
  }

  /* A delta with nothing to apply it to: the connection is asked for a whole
     snapshot rather than left showing a page that has stopped moving. */
  function refetch() {
    getJSON("/api/state").then((snapshot) => {
      base = snapshot;
      deliver(snapshot);
    }).catch(() => { /* the error handler below has the connection */ });
  }

  /* --- connecting -------------------------------------------------------- */

  function connect() {
    disconnect();
    if (document.hidden) return;
    setStatus("wait", T.connecting);
    source = new EventSource(withToken("/api/stream"));

    source.addEventListener("open", () => {
      retryAt = 1000;
      setStatus("live", T.connected);
    });

    source.addEventListener("state", (event) => {
      const snapshot = frame(event);
      if (!snapshot) return;
      base = snapshot;
      deliver(snapshot);
    });

    source.addEventListener("delta", (event) => {
      const delta = frame(event);
      if (!delta) return;
      if (!base) { refetch(); return; }
      base = merge(base, delta);
      deliver(base);
    });

    source.addEventListener("bye", () => {
      /* The add-on is shutting the server down; stop hammering it. */
      disconnect();
      setStatus("down", T.offline);
      scheduleRetry(5000);
    });

    source.addEventListener("error", () => {
      setStatus("down", T.offline);
      /* EventSource retries on its own while the connection is merely down.
         A closed one is the end of it, and says nothing about why. */
      if (!source || source.readyState !== EventSource.CLOSED) return;
      disconnect();
      probe();
    });
  }

  /* One request answers everything a closed stream leaves open: whether the
     add-on wants a token, whether it is simply carrying as many streams as it
     will, and whether it is there at all. */
  function probe() {
    fetch(withToken("/api/state")).then((response) => {
      if (response.status === 401) {
        setStatus("down", T.token_bad);
        /* A first visit to a page that wants a token has not got one wrong;
           it has not been given one yet. */
        if (token) toast(T.token_bad, true);
        askToken();
        return;
      }
      return response.json().then((state) => {
        if (state && state.streams_full) {
          /* Another tab, or this phone before it was locked.  A slot comes
             back as soon as one of them lets go, which is worth waiting a
             moment for rather than backing away from. */
          setStatus("wait", T.busy);
          scheduleRetry(1500);
          return;
        }
        backOff();
      });
    }).catch(backOff);
  }

  /* A page in a pocket is a page nobody is reading: it costs a phone five
     snapshots a second and holds one of the add-on's few stream slots.  So it
     is dropped when the page goes out of sight and taken up again the moment
     it comes back -- immediately, rather than on whatever retry was pending,
     because coming back to a dashboard should not mean waiting for one. */
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      disconnect();
      setStatus("wait", T.connecting);
      return;
    }
    retryAt = 1000;
    connect();
  });

  /* Leaving the page frees its slot at once rather than when the add-on next
     writes into a socket nobody is listening on.  A page restored from the
     back/forward cache was never unloaded, so it reconnects here. */
  window.addEventListener("pagehide", disconnect);
  window.addEventListener("pageshow", () => {
    if (!source && !document.hidden) connect();
  });

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
    return (head.length < pad ? head.padEnd(pad) : head + "  ") + plainValue(value);
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

    /* The stream is opened before anything is translated, not after:
       /api/hello is a round trip of its own, and waiting on it would leave the
       page blank for as long as it takes.  The chrome carries its English for
       the moment that lasts, and a page that needs a token is told so by the
       stream itself (see probe). */
    connect();

    try {
      const hello = await (await fetch("/api/hello")).json();
      Object.assign(T, hello.strings || {});
      applyChromeStrings();
      if (options.onStrings) options.onStrings(T, hello);
      if (hello.auth_read && !token) askToken();
    } catch (_) { /* the stream's own retry will report the outage */ }
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
    T, $, boot, toast, setStatus, fmtNits, prettyHdr, renderValue, plainValue, askToken,
    copyReport, reportLine, command, getJSON, withToken,
    disclosureState, setDisclosureState, bindDisclosure,
    get token() { return token; }
  };

})();
