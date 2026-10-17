// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The chapters on the progress bar: a dot where each chapter ahead of the
   position starts, the chapter playing named over the bar, the name of any
   dot under the pointer, and the dot a tap landed on (see hit).

   The bar behind the position is the part already seen and carries no dots,
   until a pointer comes onto it to seek -- a mouse over it, or anything
   holding it (see drag) -- and then every chapter is marked, those behind as
   well, so one already seen can be gone back to.

   The add-on sends the list once per title, already placed on the length and
   written the way the position is (see chapter_list in web/player.py), so
   nothing here is worked out from a clock.

   Loaded after core.js and before js/live-remote.js and js/live-panels.js.
   live-panels.js builds the card and hands this its nodes (create); the
   remote asks it whether a tap on the bar was a tap on a dot.

   Whether the dots are drawn at all is this device's own choice -- a switch
   on the settings tab, remembered in the browser like the folds are.
=========================================================================== */

window.TinyPPIChapters = (function () {

  const SHOW_KEY = "tinyppi.chapters";

  /* Dots nearer each other than this, in pixels, would read as one smudge on
     a phone; the later one is left out and the earlier answers for both. */
  const MIN_GAP = 6;

  /* How near a pointer has to come to a dot, in pixels, for it to count -- to
     be named, and for a drag to snap onto it. */
  const REACH = 8;

  /* The dots sit this far in from either end of the bar, so the first and
     the last are not cut in half by its rounded ends. */
  const INSET = 3;

  /* A finger cannot hover: a name shown by a tap stays up this long. */
  const TIP_HOLD = 2000;

  function storedShown() {
    try { return localStorage.getItem(SHOW_KEY) !== "0"; }
    catch (_) { return true; }
  }

  function storeShown(on) {
    try { localStorage.setItem(SHOW_KEY, on ? "1" : "0"); }
    catch (_) {}
  }

  /* The chapters in *el* (track, dots, now, tip, and the settings switch
     when the page has one). */
  function create(el) {
    let chapters = [];
    let current = 0;      /* the index of the chapter the position is in */
    let progress = 0;
    let peek = false;     /* a mouse is over the bar: every chapter shows   */
    let dragAt = null;    /* where a held pointer has the bar, or null      */
    let marks = [];       /* {chapter, node}, one per dot drawn            */
    let laidOut = null;   /* the dots and the width they were drawn for     */
    let wide = 0;         /* the bar's width, read when the layout is redone */
    let labelKey = "";
    let tipTimer = 0;
    let shown = storedShown();

    function width() {
      return el.track.getBoundingClientRect().width || 0;
    }

    /* Where a chapter's dot is, in pixels from the left of a bar *wide*. */
    function offset(chapter, wide) {
      return INSET + chapter.at / 100 * Math.max(0, wide - 2 * INSET);
    }

    /* The chapters to mark: those ahead of the position, or every one while a
       pointer is over the bar to seek with. */
    function marked() {
      return peek || dragAt !== null
        ? chapters : chapters.filter((entry) => entry.at > progress);
    }

    /* Where the bar stands: under a held pointer while there is one. */
    function position() {
      return dragAt === null ? progress : dragAt;
    }

    /* The dots, built again only when the chapters to mark or the bar's width
       changed -- which, as the film plays, is each time it passes one.  The
       first chapter of nearly every film starts at the very beginning, where
       there is no boundary to mark, so a chapter at 0 gets no dot.

       The width is read when the layout is asked to be redone (see relayout)
       rather than on every snapshot, which would lay the page out five times
       a second -- and for as long as it reads none, since a bar on a tab that
       is away has no width at all. */
    function layout() {
      if (laidOut === null || !wide) wide = width();
      const chosen = marked();
      const key = JSON.stringify(chosen) + "@" + Math.round(wide);
      if (laidOut === key) return;
      laidOut = key;
      el.dots.innerHTML = "";
      marks = [];
      let last = null;
      for (const chapter of chosen) {
        if (!(chapter.at > 0)) continue;
        if (last && wide && offset(chapter, wide) - offset(last.chapter, wide) < MIN_GAP) continue;
        const node = document.createElement("span");
        node.className = "chapter-dot";
        node.style.left = chapter.at + "%";
        el.dots.append(node);
        last = { chapter, node };
        marks.push(last);
      }
    }

    /* The dots behind the position, which only a pointer over the bar shows,
       in a light tone of the fill they stand on.  Run five times a second; a
       class that is already right is left alone. */
    function paint() {
      const at = position();
      for (const mark of marks) {
        mark.node.classList.toggle("played", mark.chapter.at <= at);
      }
    }

    /* The chapter a drag at *at* is in: the last one started by then. */
    function chapterAt(at) {
      let found = null;
      for (const entry of chapters) if (entry.at <= at) found = entry;
      return found;
    }

    /* "Chapter 3 of 12 · Arrival" over the bar: the one playing, or the one
       under a held pointer.  Nothing before the first chapter has begun, and
       nothing for a file without chapters. */
    function renderLabel() {
      const playing = dragAt === null
        ? chapters.find((entry) => entry.index === current) : chapterAt(dragAt);
      const chapter = shown ? playing : null;
      const total = chapters.length ? chapters[chapters.length - 1].index : 0;
      const counted = chapter
        ? TinyPPI.T.chapter_of.replace("%s", chapter.index).replace("%s", total) : "";
      const name = (chapter && chapter.name) || "";
      const key = counted + "\n" + name;
      if (key === labelKey) return;
      labelKey = key;
      el.now.innerHTML = "";
      el.now.classList.toggle("hidden", !counted);
      if (!counted) return;
      el.now.append(span("chapter-num", counted));
      if (name) el.now.append(span("chapter-name", " · " + name));
    }

    function span(className, text) {
      const node = document.createElement("span");
      node.className = className;
      node.textContent = text;
      return node;
    }

    function refresh() {
      el.dots.classList.toggle("hidden", !shown || !chapters.length);
      if (shown) {
        layout();
        paint();
      }
      renderLabel();
      if (!shown) hideTip();
    }

    /* --- the name under the pointer ------------------------------------- */

    /* The mark nearest *clientX*, if one is within reach. */
    function near(clientX) {
      if (!shown || !marks.length) return null;
      const box = el.track.getBoundingClientRect();
      if (!box.width) return null;
      const x = clientX - box.left;
      let best = null;
      let distance = REACH;
      for (const mark of marks) {
        const away = Math.abs(offset(mark.chapter, box.width) - x);
        if (away <= distance) {
          best = mark;
          distance = away;
        }
      }
      return best;
    }

    function tipText(chapter) {
      return [TinyPPI.T.chapter.replace("%s", chapter.index), chapter.name, chapter.time]
        .filter(Boolean).join(" · ");
    }

    /* Over the dot, kept on the card near either end: a name centred on a
       dot at 2 % would hang off the edge of the screen. */
    function showTip(mark, hold) {
      clearTimeout(tipTimer);
      const at = mark.chapter.at;
      el.tip.textContent = tipText(mark.chapter);
      el.tip.style.left = at + "%";
      el.tip.classList.toggle("start", at < 15);
      el.tip.classList.toggle("end", at > 85);
      el.tip.classList.remove("hidden");
      if (hold) tipTimer = setTimeout(hideTip, TIP_HOLD);
    }

    function hideTip() {
      clearTimeout(tipTimer);
      el.tip.classList.add("hidden");
    }

    /* A mouse over the bar is a mouse about to seek with it: every chapter is
       marked for as long as it stays, the ones already seen as well.  Not for
       a finger, which is on the bar only for the tap itself -- the dots it
       would bring up would be gone again before the tap had landed. */
    el.track.addEventListener("pointerenter", (event) => {
      if (event.pointerType === "touch") return;
      peek = true;
      refresh();
    });
    el.track.addEventListener("pointermove", (event) => {
      const mark = near(event.clientX);
      if (mark) showTip(mark, false);
      else hideTip();
    });
    el.track.addEventListener("pointerleave", () => {
      peek = false;
      hideTip();
      refresh();
    });
    /* A tap names the dot it landed on, whether or not the box takes orders:
       on a phone that is the only way to read one. */
    el.track.addEventListener("click", (event) => {
      const mark = near(event.clientX);
      if (mark) showTip(mark, true);
    });

    /* --- the switch on the settings tab ---------------------------------- */

    if (el.toggle) {
      el.toggle.checked = shown;
      el.toggle.addEventListener("change", () => {
        shown = el.toggle.checked;
        storeShown(shown);
        laidOut = null;
        refresh();
      });
    }

    /* Laid out again from scratch: the bar changed width, or a tab that was
       away (and so had no width at all) has come forward.  Called by the
       panels, which already wait out a burst of resizes for the chart. */
    function relayout() {
      laidOut = null;
      refresh();
    }

    return {
      /* The chapters of *snapshot*, with the bar at *percent*. */
      render(snapshot, percent) {
        chapters = Array.isArray(snapshot.chapters) ? snapshot.chapters : [];
        current = Number(snapshot.chapter) || 0;
        progress = percent;
        refresh();
      },
      /* A pointer holds the bar at *percent*, or has let go of it (null):
         every chapter is marked while it holds, and the label names the one
         under it (see dragTo in js/live-remote.js). */
      drag(percent) {
        dragAt = percent;
        refresh();
      },
      /* The dot a pointer at *clientX* is on, as {index, at}, or null: a drag
         snaps onto it and the remote jumps to it rather than to the spot. */
      hit(clientX) {
        const mark = near(clientX);
        return mark ? { index: mark.chapter.index, at: mark.chapter.at } : null;
      },
      /* The label and the names in the new language. */
      strings() {
        labelKey = "";
        renderLabel();
      },
      relayout,
      /* Put away when nothing plays. */
      reset() {
        chapters = [];
        current = 0;
        hideTip();
        refresh();
      }
    };
  }

  return { create };

})();
