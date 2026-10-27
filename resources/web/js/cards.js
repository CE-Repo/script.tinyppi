// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* Where the cards stand on each tab, which of them are taken off it, and
   which tabs the bar offers at all -- the app's arranging, on the page.

   Part of the dashboard page: a classic script sharing the global scope
   of js/dashboard.js and its other parts (see index.html for the order).
   What it uses from them and what it gives them is listed below.

   Kept per tab and by the card's own name -- its id, or its group's for the
   readings on the live tab -- never by its heading, which is translated.  The
   order is stored as it was left and only ever applied to the cards a tab has
   at the time (see arrangeCards), so a card that comes and goes with what is
   playing keeps its place for when it comes back.

   The cards are moved by their CSS order rather than in the document: the
   readings are put back in the snapshot's order on every snapshot (see
   renderGroups in js/dashboard.js), and a card moved in the document would be
   moved back under the reader a second later.  A grid lays out by order, so
   the page draws them where the reader put them whatever the document says.

   The order is this browser's own, in its storage, as the theme is: one
   device's arrangement is not another's, and the app keeps its own too. */

/* global el, HIDEABLE_TABS, hiddenTabs, setTabHidden, T */
/* exported arrangeCards, cardsStrings, moveCard */

const CARDS_KEY = "tinyppi.cards";

/* Where each tab's cards are, as the grids that lay them out.  The live tab
   has two: the cards under what is playing, and the readings beside them; a
   card is moved among the others in its own grid. */
const CARD_GRIDS = {
  live: () => [document.getElementById("live"), el.groups],
  metadata: () => [document.getElementById("tab-metadata")],
  films: () => [document.getElementById("tab-films")],
  series: () => [document.getElementById("tab-series")],
  history: () => [document.getElementById("tab-history")]
};

/* What is playing stays at the top of the live tab whatever else is moved,
   as it does in the app. */
const FIXED_CARDS = new Set(["nowCard"]);

/* How long a press on a heading is held before it opens the arranging. */
const ARRANGE_HOLD_MS = 500;

let cardLayout = readLayout();
let arranging = null;      /* the tab whose cards are being arranged         */

/* What this browser was left with, or nothing moved where storage is empty,
   blocked or holds something that is not a layout. */
function readLayout() {
  try {
    const stored = Object(JSON.parse(localStorage.getItem(CARDS_KEY)));
    return { orders: Object(stored.orders), hidden: new Set([].concat(stored.hidden || [])) };
  } catch (_) {
    return { orders: {}, hidden: new Set() };
  }
}

function writeLayout() {
  try {
    localStorage.setItem(CARDS_KEY, JSON.stringify({
      orders: cardLayout.orders, hidden: [...cardLayout.hidden]
    }));
  } catch (_) {}
}

/* Whether anything on any tab has been moved or taken off. */
function cardsArranged() {
  return cardLayout.hidden.size > 0 ||
    Object.values(cardLayout.orders).some((order) => order.length > 0);
}

/* --- the order ------------------------------------------------------------ */

/* The cards *present* in the order *stored* puts them in.  *present* is in
   the order the tab draws them by default; the cards named in *stored* come
   first in that order, and any card not named there is slotted in straight
   after the card it follows by default, or at the top where it follows
   nothing.  The app's own rule (see arrangeCards in CardLayout.kt). */
function arrangeCards(stored, present) {
  const distinct = [...new Set(present)];
  if (!stored.length) return distinct;
  const here = new Set(distinct);
  const named = new Set(stored);
  const result = [...new Set(stored.filter((id) => here.has(id)))];
  distinct.forEach((id, index) => {
    if (named.has(id)) return;
    const before = distinct.slice(0, index).filter((other) => result.includes(other));
    const after = before[before.length - 1];
    result.splice(after === undefined ? 0 : result.indexOf(after) + 1, 0, id);
  });
  return result;
}

/* The order to store once *id* has moved *by* places among the cards
   *present*, or null where it cannot move that way.  Cards stored but not on
   the tab now are kept, after the ones that are. */
function moveCard(stored, present, id, by) {
  const order = arrangeCards(stored, present);
  const from = order.indexOf(id);
  const to = from + by;
  if (from < 0 || to < 0 || to >= order.length) return null;
  order.splice(to, 0, order.splice(from, 1)[0]);
  return order.concat(stored.filter((other) => !order.includes(other)));
}

/* --- the cards on a tab --------------------------------------------------- */

/* Every card on these tabs has an id but the readings, which have their
   group's. */
function cardId(card) {
  return card.id || "group." + card.dataset.group;
}

/* A card the reader can move: not an idle card, not this file's own, and not
   what is playing. */
function arrangeable(node) {
  return node.classList.contains("card") && !node.classList.contains("idlecard") &&
    !node.classList.contains("arrangecard") && !FIXED_CARDS.has(node.id);
}

/* Whether a card is there to be drawn now, whatever the reader made of it. */
function cardPresent(card) {
  return !card.classList.contains("hidden") && !card.hidden;
}

/* Every card on *name*, as {id, card, grid}, in the document's order. */
function tabCards(name) {
  const found = [];
  CARD_GRIDS[name]().forEach((grid, index) => {
    for (const card of grid.children) {
      if (arrangeable(card)) found.push({ id: cardId(card), card, grid: index });
    }
  });
  return found;
}

const hiddenKey = (name, id) => name + "/" + id;

function cardHidden(name, id) {
  return cardLayout.hidden.has(hiddenKey(name, id));
}

/* What a card is called on the arranging list: its heading -- the first
   thing in it, before any count -- or, on a card with nothing to call it yet,
   its name. */
function cardLabel(card) {
  const heading = card.querySelector(":scope > .panel-toggle");
  const named = heading ? heading.firstElementChild || heading
    : card.querySelector(".plotopentitle, .lasthead .k");
  return named.textContent.trim() || cardId(card);
}

/* Put every card on *name* where the reader left it, and off the tab if they
   took it off. */
function applyCards(name) {
  const cards = tabCards(name);
  const order = arrangeCards(cardLayout.orders[name] || [], cards.map((entry) => entry.id));
  for (const { id, card } of cards) {
    card.style.order = String(order.indexOf(id) + 1);
    card.classList.toggle("userhidden", cardHidden(name, id));
  }
  showAllHidden(name, cards);
  if (arranging === name) drawArranger();
}

function applyAll() {
  for (const name of Object.keys(CARD_GRIDS)) applyCards(name);
}

/* A tab whose every card has been taken off says so, with the way back to
   them -- there is no heading left on it to be pressed.  Not on the live
   tab, where what is playing stays whatever is taken off. */
function showAllHidden(name, cards) {
  if (name === "live") return;
  const panel = document.getElementById("tab-" + name);
  let note = panel.querySelector(":scope > .allhidden");
  const present = cards.filter((entry) => cardPresent(entry.card));
  const all = present.length > 0 && present.every((entry) => cardHidden(name, entry.id));
  if (!all) {
    if (note) note.remove();
    return;
  }
  if (!note) {
    note = document.createElement("section");
    note.className = "card arrangecard allhidden";
    const line = document.createElement("p");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "setbtn";
    button.addEventListener("click", () => editCards(name));
    note.append(line, button);
    panel.prepend(note);
  }
  note.querySelector("p").textContent = T.cards_all_hidden;
  note.querySelector("button").textContent = T.cards_edit;
}

/* --- arranging ------------------------------------------------------------ */

function editCards(name) {
  if (arranging && arranging !== name) doneCards();
  arranging = name;
  const panel = document.getElementById("tab-" + name);
  panel.classList.add("arranging");
  drawArranger();
  window.scrollTo(0, 0);
}

function doneCards() {
  const panel = document.getElementById("tab-" + arranging);
  panel.classList.remove("arranging");
  panel.querySelector(":scope > .arranger").remove();
  arranging = null;
}

function resetCards(name) {
  delete cardLayout.orders[name];
  for (const key of [...cardLayout.hidden]) {
    if (key.startsWith(name + "/")) cardLayout.hidden.delete(key);
  }
  writeLayout();
  applyCards(name);
  drawCardSettings();
}

/* Every card on the tab back where it started, and every one back on it,
   on every tab. */
function resetAllCards() {
  cardLayout = { orders: {}, hidden: new Set() };
  writeLayout();
  applyAll();
  drawCardSettings();
}

function moveCardBy(name, id, by) {
  const present = tabCards(name).filter((entry) => cardPresent(entry.card))
    .map((entry) => entry.id);
  const moved = moveCard(cardLayout.orders[name] || [], present, id, by);
  if (!moved) return;
  cardLayout.orders[name] = moved;
  writeLayout();
  applyCards(name);
  drawCardSettings();
}

function setCardHidden(name, id, hidden) {
  const key = hiddenKey(name, id);
  if (hidden) cardLayout.hidden.add(key);
  else cardLayout.hidden.delete(key);
  writeLayout();
  applyCards(name);
  drawCardSettings();
}

/* The tab opened for arranging: a card saying what this is, with the way to
   put everything back and the way out, and under it every card on the tab
   as a row -- its name, the arrows that move it, and the eye that takes it
   off or puts it back.  Rows rather than the cards themselves, as in the
   app: a wall of five hundred posters between two arrows would put the next
   card a long way down.  A card taken off is still listed, faded. */
function drawArranger() {
  const name = arranging;
  const panel = document.getElementById("tab-" + name);
  let arranger = panel.querySelector(":scope > .arranger");
  if (!arranger) {
    arranger = document.createElement("section");
    arranger.className = "card arrangecard arranger";
    panel.prepend(arranger);
  }

  const head = document.createElement("div");
  head.className = "arrangehead";
  const title = document.createElement("h2");
  title.className = "sethead";
  title.textContent = T.cards_edit;
  const hint = document.createElement("p");
  hint.className = "setnote";
  hint.textContent = T.cards_edit_hint;
  const keys = document.createElement("div");
  keys.className = "arrangekeys";
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "setbtn arrangereset";
  reset.textContent = T.cards_reset;
  reset.addEventListener("click", () => resetCards(name));
  const done = document.createElement("button");
  done.type = "button";
  done.className = "setbtn arrangedone";
  done.textContent = T.cards_done;
  done.addEventListener("click", doneCards);
  keys.append(reset, done);
  head.append(title, hint, keys);

  const cards = tabCards(name).filter((entry) => cardPresent(entry.card));
  const byId = new Map(cards.map((entry) => [entry.id, entry]));
  const order = arrangeCards(cardLayout.orders[name] || [], cards.map((entry) => entry.id));
  const list = document.createElement("div");
  list.className = "arrangelist";
  order.forEach((id, index) => {
    const entry = byId.get(id);
    const hidden = cardHidden(name, id);
    /* A card moves among the others in its own grid; on the live tab the
       readings and the cards under what is playing are two. */
    const before = byId.get(order[index - 1]);
    const after = byId.get(order[index + 1]);
    const row = document.createElement("div");
    row.className = "arrangerow" + (hidden ? " off" : "");
    row.dataset.card = id;
    const label = document.createElement("div");
    label.className = "arrangelabel";
    const said = document.createElement("span");
    said.textContent = cardLabel(entry.card);
    label.append(said);
    if (hidden) {
      const note = document.createElement("small");
      note.textContent = T.cards_hidden;
      label.append(note);
    }
    row.append(label,
      arrangeKey("up", T.cards_move_up, !before || before.grid !== entry.grid,
                 () => moveCardBy(name, id, -1)),
      arrangeKey("down", T.cards_move_down, !after || after.grid !== entry.grid,
                 () => moveCardBy(name, id, 1)),
      arrangeKey(hidden ? "show" : "hide", hidden ? T.cards_show : T.cards_hide, false,
                 () => setCardHidden(name, id, !hidden)));
    list.append(row);
  });
  arranger.replaceChildren(head, list);
}

function arrangeKey(kind, label, disabled, onPress) {
  const key = document.createElement("button");
  key.type = "button";
  key.className = "arrangekey arrange-" + kind;
  key.disabled = disabled;
  key.setAttribute("aria-label", label);
  key.title = label;
  key.addEventListener("click", onPress);
  return key;
}

/* A long press on a card's heading -- or a right click -- opens its tab for
   arranging, the way a long press does in the app.  Only on a heading, so a
   poster's own press (its details) is left alone. */
function arrangeTarget(event) {
  const heading = event.target.closest(".panel-toggle, .plotopen, .lasthead");
  const card = heading && heading.closest(".card");
  const panel = card && arrangeable(card) && card.closest(".tabpanel");
  return panel && CARD_GRIDS[panel.dataset.tab] ? panel.dataset.tab : null;
}

let holdTimer = 0;
let holdStart = null;
let held = false;

document.addEventListener("pointerdown", (event) => {
  held = false;
  if (event.button !== 0) return;
  const name = arrangeTarget(event);
  if (!name) return;
  holdStart = [event.clientX, event.clientY];
  clearTimeout(holdTimer);
  holdTimer = setTimeout(() => { held = true; editCards(name); }, ARRANGE_HOLD_MS);
});
document.addEventListener("pointermove", (event) => {
  if (holdStart && Math.hypot(event.clientX - holdStart[0], event.clientY - holdStart[1]) > 10) {
    clearTimeout(holdTimer);
  }
});
for (const type of ["pointerup", "pointercancel"]) {
  document.addEventListener(type, () => { clearTimeout(holdTimer); holdStart = null; });
}
/* The press that opened the arranging does not also fold the card or open
   what playing title the overview is about. */
document.addEventListener("click", (event) => {
  if (!held) return;
  held = false;
  event.preventDefault();
  event.stopPropagation();
}, true);
document.addEventListener("contextmenu", (event) => {
  const name = arrangeTarget(event);
  if (!name) return;
  event.preventDefault();
  clearTimeout(holdTimer);
  editCards(name);
});

/* --- the settings --------------------------------------------------------- */

/* Two cards on the settings tab, as the app has them: which tabs the bar
   offers, and the way to put every card back on every tab -- the one thing
   easier from here than from five tabs. */
const tabsCard = document.createElement("section");
tabsCard.className = "card setcard";
tabsCard.id = "tabsCard";
tabsCard.innerHTML =
  '<h2 class="sethead" id="tabsHead"></h2>' +
  '<div class="setbody"><p class="setnote" id="tabsNote"></p>' +
  '<div class="tabswitches" id="tabSwitches"></div></div>';
const cardsCard = document.createElement("section");
cardsCard.className = "card setcard";
cardsCard.id = "cardsCard";
cardsCard.innerHTML =
  '<h2 class="sethead" id="cardsHead"></h2>' +
  '<div class="setbody"><p class="setnote" id="cardsNote"></p>' +
  '<p class="setnote" id="cardsResetNote"></p>' +
  '<div class="setrow"><button class="setbtn" id="cardsReset" type="button"></button></div></div>';
document.getElementById("tab-settings").append(tabsCard, cardsCard);

const tabSwitches = document.getElementById("tabSwitches");
const cardsReset = document.getElementById("cardsReset");
cardsReset.addEventListener("click", resetAllCards);

function drawCardSettings() {
  cardsReset.disabled = !cardsArranged();
}

const TAB_NAMES = {
  metadata: () => T.tab_metadata, films: () => T.films,
  series: () => T.series, history: () => T.tab_history
};

function drawTabSwitches() {
  tabSwitches.replaceChildren(...HIDEABLE_TABS.map((name) => {
    const row = document.createElement("label");
    row.className = "setswitch";
    const said = document.createElement("span");
    said.textContent = TAB_NAMES[name]();
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.setAttribute("role", "switch");
    toggle.dataset.tab = name;
    toggle.checked = !hiddenTabs.has(name);
    toggle.addEventListener("change", () => setTabHidden(name, !toggle.checked));
    row.append(said, toggle);
    return row;
  }));
}

/* The words, once the box has said them in its language. */
function cardsStrings() {
  document.getElementById("tabsHead").textContent = T.settings_tabs;
  document.getElementById("tabsNote").textContent = T.settings_tabs_desc;
  document.getElementById("cardsHead").textContent = T.settings_cards;
  document.getElementById("cardsNote").textContent = T.settings_cards_desc;
  document.getElementById("cardsResetNote").textContent = T.settings_cards_reset_desc;
  cardsReset.textContent = T.settings_cards_reset;
  drawTabSwitches();
  applyAll();
}

/* Kept in place as the cards come and go: a snapshot adds the readings a beat
   after the poster, the shelves arrive when they have been read, and a card
   that comes back shows (or stays off) where the reader left it.  Once for
   everything that moved together: the observer hands over a whole snapshot's
   worth of changes at a time. */
const ownNode = (node) => node.nodeType === 1 && !!node.closest(".arrangecard");
const cardWatch = new MutationObserver((records) => {
  /* What this file draws itself -- the arranging list, the line on a tab
     with nothing left on it -- is no card coming or going, and redrawing for
     it would draw it again for ever. */
  const theirs = records.some((record) => !(ownNode(record.target) ||
    (record.type === "childList" &&
     [...record.addedNodes, ...record.removedNodes].every(ownNode) &&
     record.addedNodes.length + record.removedNodes.length > 0)));
  if (theirs) applyAll();
});
for (const name of Object.keys(CARD_GRIDS)) {
  for (const grid of CARD_GRIDS[name]()) {
    cardWatch.observe(grid, { childList: true, subtree: true,
                              attributeFilter: ["class", "hidden"] });
  }
}

drawCardSettings();
drawTabSwitches();
applyAll();
