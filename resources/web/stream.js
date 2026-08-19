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
