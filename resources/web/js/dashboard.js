"use strict";

/* ===========================================================================
   TinyPPI second-screen dashboard.

   Everything printed here comes from the snapshot TinyPPI.boot delivers; the
   labels come translated with it, out of Kodi's own string table.  The
   connection itself lives in core.js, which this page shares with the
   metadata window.
=========================================================================== */

const $ = TinyPPI.$;
const T = TinyPPI.T;

const el = {
  version: $("version"), idleCard: $("idleCard"),
  vs10Card: $("vs10Card"), vs10Out: $("vs10Out"), modes: $("modes"),
  groups: $("groups"),
  metricsCard: $("tiles"), healthCard: $("healthCard"),
  eventsCard: $("eventsCard"), metaLink: $("metaLink"),
  copyBtn: $("copyBtn"),
  lastBox: $("lastBox"), lastTitle: $("lastTitle"), lastTiles: $("lastTiles")
};

/* Keep VS10 by the playback card; the optional summary cards belong at the
   page end, immediately ahead of the metadata link, in the order they are
   read: the figures, what they did over the film, and what happened. */
$("nowCard").after(el.vs10Card);
el.metaLink.before(el.eventsCard);
el.eventsCard.before(el.metricsCard);
el.eventsCard.before(el.healthCard);

let state = null;
let control = false;
let rowNodes = new Map();  /* row id -> {element, key, value, last}     */
let groupNodes = new Map();
let pending = null;        /* the VS10 mode a button is waiting on      */

/* Only the two per-frame L1 summaries use the transient change colour. */
const FLASH_ROWS = new Set(["metadata.32375", "metadata.32376"]);
const DEFAULT_OPEN_GROUPS = new Set([
  "video", "audio", "processing", "dv", "system", "metadata"
]);

TinyPPI.bindDisclosure(el.vs10Card, "dashboard.vs10", false);

/* --- render ------------------------------------------------------------- */

function render(next) {
  state = next;
  control = !!next.control;

  /* The common live module draws what is playing and the summary tiles.  Its
     L1 chart is reserved for the metadata window. */
  TinyPPI.panels.update(next);

  if (!next.playing) {
    el.idleCard.classList.remove("hidden");
    for (const id of ["vs10Card", "metaLink"]) {
      $(id).classList.add("hidden");
    }
    el.groups.innerHTML = "";
    rowNodes.clear();
    groupNodes.clear();
    renderLast(next.last);
    /* The button goes with the report: there is one for as long as the title
       that just ended is still held, and none at all once it is let go -- a
       button that answers a press with nothing is worse than one that is not
       there. */
    el.copyBtn.classList.toggle("hidden", !next.last || !next.last.title);
    return;
  }

  el.idleCard.classList.add("hidden");
  el.lastBox.classList.add("hidden");
  el.copyBtn.classList.remove("hidden");

  renderVs10(next.vs10 || {});
  renderGroups(ordered(next.groups || []));
  /* The metadata list is a window of its own; this page only says whether
     there is one to open. */
  el.metaLink.classList.toggle("hidden", !(next.metadata && next.metadata.length));
}

/* --- the title that just ended ------------------------------------------ */

/* The add-on holds a finished session for ten minutes (see SessionLog.end in
   web/snapshot.py), which is the window in which someone walks over to the
   phone and asks what that film actually did.  What it did is three figures
   and the events beneath them; the event list is the same card that was there
   while it played, and stays where it was. */
function renderLast(last) {
  if (!last || !last.title) {
    el.lastBox.classList.add("hidden");
    return;
  }
  el.lastBox.classList.remove("hidden");
  el.lastTitle.textContent = last.title;

  const tiles = [];
  if (last.peak !== null && last.peak !== undefined) {
    tiles.push([T.peak, TinyPPI.fmtNits(last.peak), "nits"]);
  }
  tiles.push([T.drops, String(last.drops || 0), ""]);
  tiles.push([T.switches, String(last.switches || 0), ""]);

  el.lastTiles.replaceChildren();
  for (const [label, value, unit] of tiles) {
    const tile = document.createElement("div");
    tile.className = "tile";
    const key = document.createElement("span");
    key.className = "k";
    key.textContent = label;
    const wrap = document.createElement("span");
    wrap.className = "vwrap";
    const reading = document.createElement("span");
    reading.className = "v mono";
    reading.textContent = value;
    const suffix = document.createElement("span");
    suffix.className = "u";
    suffix.textContent = unit;
    wrap.append(reading, suffix);
    tile.append(key, wrap);
    el.lastTiles.append(tile);
  }
}

/* --- VS10 --------------------------------------------------------------- */

function renderVs10(vs10) {
  const options = vs10.options || [];
  if (!control || !options.length) {
    el.vs10Card.classList.add("hidden");
    return;
  }
  el.vs10Card.classList.remove("hidden");
  el.vs10Out.textContent = vs10.output || "—";

  const signature = options.map((option) => option.mode).join("|");
  if (el.modes.dataset.signature !== signature) {
    el.modes.dataset.signature = signature;
    el.modes.innerHTML = "";
    for (const option of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mode";
      button.dataset.mode = option.mode;
      button.textContent = option.label;
      button.addEventListener("click", () => switchMode(option.mode, button));
      el.modes.appendChild(button);
    }
  }
}

async function switchMode(mode, button) {
  if (pending) return;
  pending = mode;
  for (const node of el.modes.children) node.disabled = true;
  button.classList.add("busy");
  TinyPPI.toast(T.switching);
  try {
    const response = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TinyPPI-Token": TinyPPI.token },
      body: JSON.stringify({ mode })
    });
    if (response.status === 401) {
      TinyPPI.toast(T.token_bad, true);
      TinyPPI.askToken();
    } else if (!response.ok) {
      TinyPPI.toast(T.switch_failed, true);
    } else {
      TinyPPI.toast(T.switched);
    }
  } catch (_) {
    TinyPPI.toast(T.switch_failed, true);
  } finally {
    /* The driver needs a moment to settle before the next snapshot shows the
       new output; keep the buttons locked until then rather than inviting a
       second press into the middle of the switch. */
    setTimeout(() => {
      pending = null;
      button.classList.remove("busy");
      for (const node of el.modes.children) node.disabled = false;
    }, 1200);
  }
}

/* --- detail groups ------------------------------------------------------ */

/* The order the cards are laid out in, by the group ids the snapshot carries.
   The snapshot names them in an order of its own (web/snapshot.py _GROUPS),
   but that one lives in the service, which reads its code once when Kodi
   starts -- so the layout is decided here instead, where reloading the page
   is enough to change it.  A group not named here keeps its place, after the
   ones that are.

   Read in pairs, because the cards stand two to a row: picture beside sound,
   what was done to it beside what it declares itself to be, the machine
   beside the numbers.  Each pair is also two blocks of roughly one length,
   which is what keeps the rows from ending ragged.  The static HDR card is
   last because it only appears at all on an HDR title that is not Dolby
   Vision -- where the two cards after it are absent (see snapshot.py). */
const GROUP_ORDER =
  ["video", "audio", "processing", "dv", "system", "metadata", "hdr"];

function ordered(groups) {
  const rank = (group) => {
    const at = GROUP_ORDER.indexOf(group.id);
    return at === -1 ? GROUP_ORDER.length : at;
  };
  return [...groups].sort((first, second) => rank(first) - rank(second));
}

function renderGroups(groups) {
  const seen = new Set();

  groups.forEach((group, index) => {
    seen.add(group.id);
    let card = groupNodes.get(group.id);
    if (!card) {
      card = document.createElement("details");
      card.className = "card";
      TinyPPI.bindDisclosure(
        card, "dashboard.group." + group.id, DEFAULT_OPEN_GROUPS.has(group.id)
      );
      const heading = document.createElement("summary");
      heading.className = "panel-toggle";
      heading.textContent = group.title;
      const rows = document.createElement("div");
      rows.className = "rows";
      card.append(heading, rows);
      card.dataset.group = group.id;
      groupNodes.set(group.id, card);
    }
    /* Placed on every pass, not just when the card is made: the groups do not
       all arrive with the first snapshot -- the system readings settle after
       playback has run for a moment, the HDR blocks once the source is known
       -- and a card merely appended would keep whatever place it was late to,
       rather than the one the snapshot gives it. */
    const at = el.groups.children[index];
    if (at !== card) el.groups.insertBefore(card, at || null);
    renderRows(card.querySelector(".rows"), group);
  });

  for (const [id, card] of groupNodes) {
    if (!seen.has(id)) { card.remove(); groupNodes.delete(id); }
  }
}

function renderRows(container, group) {
  const wanted = group.rows.map((row) => row.id);
  const seen = new Set(wanted);

  group.rows.forEach((row, index) => {
    let node = rowNodes.get(row.id);
    if (!node) {
      const element = document.createElement("div");
      element.className = "row";
      const key = document.createElement("span");
      key.className = "k";
      const value = document.createElement("span");
      value.className = "v mono";
      element.append(key, value);
      node = { element, key, value, last: null, timer: 0 };
      rowNodes.set(row.id, node);
    }
    /* Keep the DOM in the order the snapshot names, so a row that appears
       mid-title lands where it belongs instead of at the end. */
    const at = container.children[index];
    if (at !== node.element) container.insertBefore(node.element, at || null);

    node.key.textContent = row.label;
    const text = row.detail ? row.value + "  " : row.value;
    if (node.last !== row.value + "\n" + row.detail) {
      if (node.last !== null && FLASH_ROWS.has(row.id)) flash(node);
      node.last = row.value + "\n" + row.detail;
      TinyPPI.renderValue(node.value, text);
      if (row.detail) {
        const detail = document.createElement("span");
        detail.className = "d";
        detail.textContent = row.detail;
        node.value.append(detail);
      }
    }
  });

  for (const [id, node] of rowNodes) {
    if (id.startsWith(group.id + ".") && !seen.has(id)) {
      node.element.remove();
      rowNodes.delete(id);
    }
  }
}

/* A changed L1 summary flashes briefly, then fades back to the normal colour. */
function flash(node) {
  node.element.classList.add("changed");
  clearTimeout(node.timer);
  node.timer = setTimeout(() => node.element.classList.remove("changed"), 750);
}

/* --- report ------------------------------------------------------------- */

function reportValue(row) {
  const value = TinyPPI.plainValue(row.value);
  const detail = row.detail ? TinyPPI.plainValue(row.detail) : "";
  if (!/[✔✘]/.test(row.value || "")) {
    return value + (detail ? "  " + detail : "");
  }

  /* The left report column already names both fields, so the right column
     only carries their values in the same order. */
  const parts = value.split(/\s*[|/]\s*/);
  if (detail) {
    const cleanDetail = detail.replace(/^\((.*)\)$/, "$1");
    parts.push(cleanDetail);
  }
  return parts.join(" | ");
}

/* What the title added up to, and what happened along the way.  Both come
   from the session the add-on has been keeping since playback started, so a
   report written a minute in and one written at the credits differ by exactly
   what happened in between -- and one written after the credits still has all
   of it (see renderLast). */
function summaryLines(session, peak) {
  const lines = [];
  if (peak !== null && peak !== undefined) {
    lines.push(TinyPPI.reportLine(T.peak, TinyPPI.fmtNits(peak) + " nits"));
  }
  lines.push(TinyPPI.reportLine(T.drops, String((session || {}).drops || 0)));
  lines.push(TinyPPI.reportLine(T.switches, String((session || {}).switches || 0)));
  return ["[" + T.summary + "]", ...lines, ""];
}

function eventLines() {
  const events = TinyPPI.panels.events();
  if (!events.length) return [];
  const lines = ["[" + T.events + "]"];
  for (const event of events) {
    lines.push(TinyPPI.reportLine(
      (event.pos ? event.pos + "  " : "") + event.label, event.text));
  }
  lines.push("");
  return lines;
}

function buildReport() {
  if (!state) return "";
  const peak = TinyPPI.panels.peak();
  if (!state.playing) {
    /* Nothing is playing, so the report is of the title that was: its heading,
       its figures and its events, with no rows to print between them. */
    const last = state.last;
    if (!last || !last.title) return "";
    return ["TinyPPI", last.title, "",
            ...summaryLines(last, last.peak === undefined ? peak : last.peak),
            ...eventLines()].join("\n");
  }

  const lines = ["TinyPPI"];
  if (state.title) lines.push(state.title);
  if (state.filename) lines.push(state.filename);
  lines.push("");
  for (const group of ordered(state.groups || [])) {
    lines.push("[" + group.title + "]");
    for (const row of group.rows) {
      lines.push(TinyPPI.reportLine(row.label, reportValue(row)));
    }
    lines.push("");
  }
  lines.push(...summaryLines(state.session, peak));
  lines.push(...eventLines());
  return lines.join("\n");
}

/* The clipboard, or a file named after the film where the browser will not
   give it the clipboard; both pages hand it over the same way (see
   TinyPPI.copyReport). */
el.copyBtn.addEventListener("click", () => {
  const title = (state || {}).playing
    ? state.title : ((state || {}).last || {}).title;
  TinyPPI.copyReport(buildReport(), title);
});

/* --- boot --------------------------------------------------------------- */

function applyStrings(strings, hello) {
  $("idleTitle").textContent = strings.idle_title;
  $("idleText").textContent = strings.idle_text;
  $("lastLabel").textContent = strings.last_played;
  TinyPPI.panels.strings(strings);
  $("vs10Title").textContent = strings.vs10;
  $("vs10OutLabel").textContent = strings.output;
  $("metaLinkText").textContent = strings.metadata;
  el.copyBtn.setAttribute("aria-label", strings.copy);
  el.copyBtn.title = strings.copy;
  if (hello) {
    el.version.textContent = "v" + hello.version;
  }
}

TinyPPI.boot({ onState: render, onStrings: applyStrings });
