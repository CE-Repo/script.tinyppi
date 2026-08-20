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
    metadata: "Dolby Vision metadata view",
    no_metadata: "No Dolby Vision metadata", no_metadata_text: "",
    idle_title: "Nothing is playing", idle_text: "",
    peak: "Peak", average: "Average", aspect: "Aspect ratio", fps: "FPS",
    drops: "Frame drops", switches: "Output switches", metrics: "Metrics",
    chart: "Frame luminance", active_area: "Active picture", vs10: "VS10 output",
    output: "Output", copy: "Copy report", copied: "Copied", awake: "Keep awake",
    controls: "Playback controls",
    token_title: "Access token", token_text: "", save: "Save", cancel: "Cancel",
    yes: "Yes", no: "No",
    token_bad: "Wrong or missing token", switching: "Switching…",
    switched: "Switched", switch_failed: "Switching failed"
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
    const tokenButton = $("tokenBtn");
    if (tokenButton) {
      tokenButton.title = T.token_title;
      tokenButton.setAttribute("aria-label", T.token_title);
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
    T, $, boot, toast, setStatus, fmtNits, prettyHdr, renderValue, plainValue, askToken,
    copyReport, reportLine, command, getJSON, withToken,
    disclosureState, setDisclosureState, bindDisclosure,
    get token() { return token; }
  };

})();
