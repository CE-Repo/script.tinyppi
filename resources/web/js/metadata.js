"use strict";

/* ===========================================================================
   The Dolby Vision metadata window.

   Fed by the same stream the dashboard sits on: the rows arrive as
   (kind, name, value) exactly as info.dvmetadata builds them for the
   on-screen view, and this page only lays them out.
=========================================================================== */

const $ = TinyPPI.$;
const T = TinyPPI.T;

const el = {
  version: $("version"), count: $("count"),
  listCard: $("listCard"), idleCard: $("idleCard"), metaRows: $("metaRows"),
  frameCard: $("frameCard"), frameActive: $("frameActive"), frameNote: $("frameNote"),
  copyBtn: $("copyBtn")
};

/* live-panels.js creates the L1 chart before this page starts.  Keep the L5
   active-picture card immediately ahead of it. */
$("chartCard").before(el.frameCard);
TinyPPI.bindDisclosure(el.frameCard, "metadata.l5", false);
TinyPPI.bindDisclosure(el.listCard, "metadata.details", true);

let state = null;
let signature = "";   /* the list's shape, so nodes are rebuilt only when it moves */
let live = [];        /* {node, index, field} for every reading that changes      */

/* --- render ------------------------------------------------------------- */

function render(next) {
  state = next;
  const rows = next.metadata || [];

  document.title = next.title
    ? next.title + " — " + T.metadata
    : "TinyPPI — " + T.metadata;
  /* What is playing, the summary figures and the L1 luminance chart come from
     the shared live module.  The L5 active-picture card stays on this page. */
  TinyPPI.panels.update(next);
  renderFrame(next.metrics || {});

  if (!rows.length) {
    el.listCard.classList.add("hidden");
    el.idleCard.classList.remove("hidden");
    /* Two different nothings: no film at all, or a film with no RPU behind it.
       Saying which is the difference between a window that looks broken and
       one that has answered. */
    $("idleTitle").textContent = next.playing ? T.no_metadata : T.idle_title;
    $("idleText").textContent  = next.playing ? T.no_metadata_text : T.idle_text;
    /* Nothing to list is nothing to copy, so the button goes with the list
       rather than staying behind to answer a press with nothing. */
    el.copyBtn.classList.add("hidden");
    el.count.textContent = "";
    signature = "";
    live = [];
    el.metaRows.textContent = "";
    return;
  }

  el.listCard.classList.remove("hidden");
  el.idleCard.classList.add("hidden");
  el.copyBtn.classList.remove("hidden");
  el.count.textContent = rows.filter((row) => row.kind !== "space").length;

  /* Rebuilding a hundred-odd nodes five times a second would fight the browser
     for no gain, and the list only changes shape when a block comes or goes.
     So the values are written in place and the nodes are rebuilt only when the
     shape itself moves. */
  const shape = rows
    .map((row) => row.kind + "\u001f" + row.name +
                  "\u001f" + (row.kind === "headings"
                    ? (row.cells || []).join("\u001d")
                    : (row.cells ? row.cells.length : "")))
    .join("\u001e");
  if (shape !== signature) {
    signature = shape;
    build(rows);
    return;
  }
  update(rows);
}

/* --- active picture ----------------------------------------------------- */

function renderFrame(metrics) {
  const bars = metrics.bars, frame = metrics.frame;
  if (!bars || !frame || !frame.w || !frame.h) {
    el.frameCard.classList.add("hidden");
    return;
  }
  el.frameCard.classList.remove("hidden");
  const [left, right, top, bottom] = bars;
  const box = el.frameActive.parentElement;
  box.style.aspectRatio = frame.w + " / " + frame.h;
  el.frameActive.style.inset =
    (top / frame.h * 100) + "% " + (right / frame.w * 100) + "% " +
    (bottom / frame.h * 100) + "% " + (left / frame.w * 100) + "%";
  el.frameNote.textContent =
    frame.w + "×" + frame.h + "   L " + left + "  R " + right +
    "  T " + top + "  B " + bottom;
}

function build(rows) {
  const frag = document.createDocumentFragment();
  el.metaRows.textContent = "";
  live = [];

  /* Each section and its rows go in a block of their own, so a multi-column
     layout breaks between sections and never through one. */
  let block = null;
  const open = () => {
    block = document.createElement("div");
    block.className = "mblock";
    frag.append(block);
  };

  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    if (row.kind === "space") continue;        /* the blocks space themselves */
    if (row.kind === "section" || !block) open();

    /* A trim table is several rows read as one thing, and it is turned on its
       side to fit a column, so it is taken whole. */
    if (row.kind === "headings") {
      index = table(block, rows, index);
      continue;
    }
    if (row.kind === "columns") continue;   /* taken by its own heading row */

    let node;
    if (row.kind === "section") {
      node = document.createElement("div");
      node.className = "msection";
      const name = document.createElement("span");
      name.textContent = row.name;
      const held = document.createElement("span");
      held.className = "state";
      /* A held block says so on its heading -- see info.dvmetadata._state. */
      TinyPPI.renderValue(held, row.value || "");
      node.append(name, held);
      live.push({ node: held, index, field: "value", last: row.value || "" });
    } else if (row.kind === "wide") {
      node = document.createElement("div");
      node.className = "mwide mono";
      TinyPPI.renderValue(node, row.value);
      live.push({ node, index, field: "value", last: row.value || "" });
    } else {
      node = document.createElement("div");
      node.className = "mrow";
      const key = document.createElement("span");
      key.className = "k";
      key.textContent = row.name;
      const value = document.createElement("span");
      value.className = "v mono";
      TinyPPI.renderValue(value, row.value);
      node.append(key, value);
      live.push({ node: value, index, field: "value", row: node,
                  last: row.value || "" });
    }
    block.append(node);
  }

  el.metaRows.append(frag);
}


/* --- trim tables --------------------------------------------------------- */

/* One trim table, from the heading row at *start* and the pass rows under it,
   appended to *block*.  Returns the index of the last row it took.

   The list arrives laid out for the television: a heading row naming the
   controls, then a row per pass.  Here it is turned on its side -- controls
   down the left, a column per pass -- because a row of the on-screen list is
   1195 px wide and a column of this page is a fifth of that, which is not
   enough for six to nine controls abreast.  Passes are few, one per target
   display, so the tall shape is the one that fits.

   More controls than the on-screen row holds arrive as a second table with
   the heading repeated -- a limit belonging to that row, not to this page --
   so a continuation is read back into the table it was cut from. */
function table(block, rows, start) {
  const legend   = rows[start].name;
  const passes   = [];      /* one per target display, across the top */
  const controls = [];      /* one per control, down the left side    */
  let last = start;

  for (let index = start; index < rows.length; ) {
    /* The pass rows belonging to this heading row. */
    const chunk = [];
    let scan = index + 1;
    while (scan < rows.length && rows[scan].kind === "columns") {
      chunk.push(scan);
      scan++;
    }
    if (!chunk.length) break;

    if (!passes.length) for (const source of chunk) passes.push(rows[source].name);
    (rows[index].cells || []).forEach((name, cell) => {
      controls.push({ name, cells: chunk.map((source) => ({ source, cell })) });
    });
    last = scan - 1;

    /* A continuation is the same legend over the same passes; anything else
       is a table of its own, and the caller walks into it. */
    let next = scan;
    while (next < rows.length && rows[next].kind === "space") next++;
    if (next >= rows.length || rows[next].kind !== "headings" ||
        rows[next].name !== legend) break;
    const after = rows.slice(next + 1, next + 1 + chunk.length);
    if (after.length !== chunk.length ||
        after.some((row, at) => row.kind !== "columns" ||
                                row.name !== rows[chunk[at]].name)) break;
    index = next;
  }

  if (!controls.length) return last;

  const wrap = document.createElement("div");
  wrap.className = "mtable";
  const grid = document.createElement("div");
  grid.className = "mgrid";
  grid.style.gridTemplateColumns =
    "minmax(var(--lead), auto) repeat(" + passes.length +
    ", minmax(var(--cell), 1fr))";

  const corner = document.createElement("span");
  corner.className = "corner";
  corner.textContent = legend;
  grid.append(corner);
  for (const name of passes) {
    const head = document.createElement("span");
    head.className = "head";
    head.textContent = name;
    grid.append(head);
  }
  const rule = document.createElement("span");
  rule.className = "rule";
  grid.append(rule);

  for (const control of controls) {
    const lead = document.createElement("span");
    lead.className = "lead";
    lead.textContent = control.name;
    grid.append(lead);
    for (const cell of control.cells) {
      const node = document.createElement("span");
      node.className = "mono";
      const value = (rows[cell.source].cells || [])[cell.cell] || "";
      TinyPPI.renderValue(node, value);
      grid.append(node);
      live.push({ node, index: cell.source, field: "cell", cell: cell.cell,
                  last: value });
    }
  }

  wrap.append(grid);
  block.append(wrap);
  return last;
}

function update(rows) {
  for (const entry of live) {
    const row = rows[entry.index];
    if (!row) continue;
    if (entry.field === "cell") {
      const cell = (row.cells || [])[entry.cell] || "";
      if (entry.last === cell) continue;
      entry.last = cell;
      TinyPPI.renderValue(entry.node, cell);
      /* A trim is the fastest-moving reading the view has, and on screen it
         is highlighted like any other; the cell itself lights up, since a
         whole table row of them lit at once would say less than the one
         control that actually moved. */
      flash(entry);
      continue;
    }
    const text = row.value || "";
    if (entry.last === text) continue;
    entry.last = text;
    TinyPPI.renderValue(entry.node, text);
    /* Mirrors the overlay's own highlight: a reading that moved is written in
       the change color and fades back. */
    if (entry.row) flash(entry);
  }
}

function flash(entry) {
  /* A name and its value are lit as a pair -- the row carries the class -- and
     a trim cell on its own. */
  const node = entry.row || entry.node;
  node.classList.add("changed");
  clearTimeout(entry.timer);
  entry.timer = setTimeout(() => node.classList.remove("changed"), 750);
}

/* --- report ------------------------------------------------------------- */

function buildReport() {
  if (!state || !(state.metadata || []).length) return "";
  const lines = ["TinyPPI — " + T.metadata];
  if (state.title) lines.push(state.title);
  if (state.filename) lines.push(state.filename);
  lines.push("");
  for (const row of state.metadata) {
    if (row.kind === "space") lines.push("");
    else if (row.kind === "section")
      lines.push("[" + row.name + (row.value ? " - " + TinyPPI.plainValue(row.value) : "") + "]");
    else if (row.kind === "wide") lines.push("  " + TinyPPI.plainValue(row.value));
    else if (row.cells) lines.push(TinyPPI.reportLine(row.name, row.cells.join("  ")));
    else lines.push(TinyPPI.reportLine(row.name, row.value));
  }
  return lines.join("\n");
}

/* The clipboard, or a file named after the film where the browser will not
   give it the clipboard; both pages hand it over the same way (see
   TinyPPI.copyReport). */
el.copyBtn.addEventListener("click", () => {
  /* Tailed "metadata" so this list and the dashboard's report can both be
     saved for the same film without one landing on the other. */
  TinyPPI.copyReport(buildReport(), (state || {}).title, "metadata");
});

/* --- boot --------------------------------------------------------------- */

function applyStrings(strings, hello) {
  TinyPPI.panels.strings(strings);
  $("frameTitle").textContent = strings.active_area;
  $("metadataTitle").textContent = strings.metadata_section;
  el.copyBtn.setAttribute("aria-label", strings.copy);
  el.copyBtn.title = strings.copy;
  if (hello) {
    el.version.textContent = "v" + hello.version;
  }
  document.title = "TinyPPI — " + strings.metadata;
}

TinyPPI.boot({ onState: render, onStrings: applyStrings });
