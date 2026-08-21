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
  metricsCard: $("tiles"), eventsCard: $("eventsCard"), metaLink: $("metaLink"),
  copyBtn: $("copyBtn")
};

/* Keep VS10 by the playback card; the two optional summary cards belong at
   the page end, immediately ahead of the metadata link. */
$("nowCard").after(el.vs10Card);
el.metaLink.before(el.eventsCard);
el.eventsCard.before(el.metricsCard);

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
    /* The copy button goes with them: with nothing playing there is no report
       to write, and a button that answers a press with nothing is worse than
       one that is not there. */
    for (const id of ["vs10Card", "metaLink", "copyBtn"]) {
      $(id).classList.add("hidden");
    }
    el.groups.innerHTML = "";
    rowNodes.clear();
    groupNodes.clear();
    return;
  }

  el.idleCard.classList.add("hidden");
  el.copyBtn.classList.remove("hidden");

  renderVs10(next.vs10 || {});
  renderGroups(ordered(next.groups || []));
  /* The metadata list is a window of its own; this page only says whether
     there is one to open. */
  el.metaLink.classList.toggle("hidden", !(next.metadata && next.metadata.length));
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

function buildReport() {
  if (!state || !state.playing) return "";
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
  return lines.join("\n");
}

/* The clipboard, or a file named after the film where the browser will not
   give it the clipboard; both pages hand it over the same way (see
   TinyPPI.copyReport). */
el.copyBtn.addEventListener("click", () => {
  TinyPPI.copyReport(buildReport(), (state || {}).title);
});

/* --- boot --------------------------------------------------------------- */

function applyStrings(strings, hello) {
  $("idleTitle").textContent = strings.idle_title;
  $("idleText").textContent = strings.idle_text;
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
