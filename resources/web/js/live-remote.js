// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The remote on the now-playing card: the drawer and the key that opens it,
   the transport row, the fine adjustments and the track pickers.

   Loaded after core.js and js/live-chapters.js and before js/live-panels.js,
   which builds the card and hands the remote its nodes (create); the icons
   are shared with the rest of the card (icon, setIcon).
=========================================================================== */

window.TinyPPIRemote = (function () {

  /* How far a press moves each offset: Kodi's own step for the subtitles, and
     two of its 25 ms steps for the sound, which would otherwise take forty
     presses to move a second.  Kodi's ranges bound them (see web/player.py). */
  const OFFSETS = {
    audio_delay: { step: 0.05, limit: 10, label: "audio_offset" },
    subtitle_delay: { step: 0.1, limit: 60, label: "subtitle_offset" }
  };
  /* How long a pressed value stands against the snapshots: the box reads the
     offsets on its one-second cadence, and a snapshot from before the press
     would put the old value back under the thumb for a moment. */
  const HOLD_MS = 2000;

  /* An offset as the stepper writes it: milliseconds below a second, seconds
     with two decimals above, always signed so that "early" and "late" cannot
     be mistaken for one another. */
  function offsetText(seconds) {
    const ms = Math.round(seconds * 1000);
    if (ms === 0) return "0 ms";
    const sign = ms > 0 ? "+" : "\u2212";
    const size = Math.abs(ms);
    return sign + (size < 1000 ? size + " ms" : (size / 1000).toFixed(2) + " s");
  }

  function uiIcon(name) {
    const image = document.createElement("img");
    image.className = "ui-icon";
    image.src = "/icons/" + name + ".svg";
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    return image;
  }

  /* The icon only, and not whatever else the key holds: the mute key carries
     the volume reading beside its icon, and replacing the key's contents
     outright would take the reading with it. */
  function setButtonIcon(node, name) {
    if (node.dataset.icon === name) return;
    node.dataset.icon = name;
    const drawn = node.querySelector(".ui-icon");
    if (drawn) drawn.replaceWith(uiIcon(name));
    else node.prepend(uiIcon(name));
  }

  /* Where *percent* of *duration* falls, written the way the box writes the
     position beside it: hh:mm:ss for a title of an hour or more, mm:ss below.
     Empty for a length that is no clock. */
  function clockAt(percent, duration) {
    const parts = duration.split(":").map(Number);
    if (parts.length < 2 || !parts.every(Number.isFinite)) return "";
    const at = Math.round(parts.reduce((sum, part) => sum * 60 + part, 0) * percent / 100);
    const two = (number) => String(number).padStart(2, "0");
    const hours = Math.floor(at / 3600);
    const minutes = Math.floor(at % 3600 / 60);
    const tail = ":" + two(at % 60);
    return parts.length > 2 ? two(hours) + ":" + two(minutes) + tail : two(hours * 60 + minutes) + tail;
  }

  /* The remote in *el* (nowCard, drawer, transport, tracks, track, bar, the
     elapsed clock under it, and the chapter dots on the bar from
     js/live-chapters.js); *pageState* is what the drawer's state is
     remembered under. */
  function create(el, pageState) {
    const controlToggle = document.createElement("button");
    controlToggle.type = "button";
    controlToggle.id = "controlToggle";
    controlToggle.className = "iconbtn control-toggle hidden";
    controlToggle.setAttribute("aria-expanded", "false");
    controlToggle.setAttribute("aria-controls", "controlDrawer");
    /* A span, where every other icon on the page is an <img>: this one takes
       the accent, and an <img> cannot be given a colour -- the file is a white
       stroke.  It is painted instead, the same drawing masking the colour in
       rather than being shown as it stands (see .control-chevron in
       live-panels.css).  The colour has to be worked out at runtime under the
       adaptive theme, so a second file in the accent is no use here. */
    const controlChevron = document.createElement("span");
    controlChevron.className = "ui-icon control-chevron";
    controlChevron.setAttribute("aria-hidden", "true");
    controlToggle.append(controlChevron);
    el.nowCard.append(controlToggle);

    let control = false;
    let chapterCount = 0;
    let trackKey = "";
    let duration = "";    /* the title's length, for the clock a drag shows   */
    const offsets = { audio_delay: null, subtitle_delay: null };
    const heldUntil = { audio_delay: 0, subtitle_delay: 0 };
    let drag = null;      /* {id, where, chapter} while a pointer holds the bar */
    const controlStateKey = pageState + ".controls";

    function setControlsOpen(open, remember) {
      el.drawer.classList.toggle("open", open);
      controlToggle.setAttribute("aria-expanded", String(open));
      if (remember !== false) TinyPPI.setDisclosureState(controlStateKey, open);
    }

    controlToggle.addEventListener("click", () => {
      setControlsOpen(controlToggle.getAttribute("aria-expanded") !== "true");
    });
    setControlsOpen(TinyPPI.disclosureState(controlStateKey, false), false);

    /* --- the remote ------------------------------------------------------- */

    /* Built once, the first time a snapshot says the add-on will take orders.
       Everything goes through TinyPPI.command, which carries the token and says
       whether the player did it. */
    function buildTransport() {
      if (el.transport.dataset.built) return;
      el.transport.dataset.built = "1";

      const button = (label, handler, className) => {
        const node = document.createElement("button");
        node.type = "button";
        node.className = "tbtn" + (className ? " " + className : "");
        node.textContent = label;
        node.title = label;
        node.addEventListener("click", handler);
        return node;
      };

      /* Named by the key rather than by the string behind it, because the row is
         built the first time a snapshot says the add-on takes orders -- which
         can be before /api/hello has answered.  The name is put on from the key
         here and again whenever the strings change (see labelControls). */
      const imageButton = (name, key, handler, className) => {
        const node = button("", handler, className);
        node.dataset.label = key;
        setButtonIcon(node, name);
        return node;
      };

      /* CSS keeps these as two full-width rows: the jumps on their own first,
         then everything that is not a jump.  Six of one kind and nothing else,
         three back and three forward, so the row reads as one scale rather than
         as two halves either side of something bigger. */
      const keys = document.createElement("div");
      keys.className = "tkeys";
      keys.append(
        button("−10m", () => TinyPPI.command("seek", -600)),
        button("−1m", () => TinyPPI.command("seek", -60)),
        button("−10s", () => TinyPPI.command("seek", -10)),
        button("+10s", () => TinyPPI.command("seek", 10)),
        button("+1m", () => TinyPPI.command("seek", 60)),
        button("+10m", () => TinyPPI.command("seek", 600))
      );

      /* Everything that is not a jump, in the order it is used: a chapter back,
         play, the three volume keys, stop, a chapter on.

         The volume steps rather than slides, and there is a reason it has to.  A
         slider could only ever have set Kodi's own mixer: a box that passes
         volume on over CEC leaves that number where it is and sends the
         amplifier a command instead, and it does that from the input path,
         which an absolute level never reaches and a step always does.  So these
         three work a soundbar where a slider could not -- at the cost of the
         level itself, which CEC has no command for and which is therefore not
         shown at all.

         Each step carries a speaker beside its sign.  A bare + in a row whose
         other keys are marked "+10s" is a key that has to be worked out; the
         speaker says which kind of louder it means before it is read. */
      const stepButton = (sign, key) => {
        const node = button("", () => TinyPPI.command(key), "vol");
        node.dataset.label = key;
        node.append(uiIcon("volume"));
        const mark = document.createElement("span");
        mark.className = "sign";
        mark.textContent = sign;
        node.append(mark);
        return node;
      };

      const rest = document.createElement("div");
      rest.className = "tvol";
      rest.append(
        imageButton("chapter-previous", "chapter_previous",
                    () => TinyPPI.command("chapter_previous"), "chapter"),
        /* The icon says what pressing it does, so it follows the player: pause
           while it plays, play while it is paused.

           Drawn like every other key in the row and not in the accent.  Picked
           out, it was the one lit thing on a row of outlines -- which reads as
           the key that is currently doing something rather than as the key worth
           reaching for, and what it is doing is already written on it. */
        imageButton("pause", "playpause",
                    () => TinyPPI.command("playpause"), "play"),
        stepButton("−", "volume_down"),
        imageButton("volume", "mute", () => TinyPPI.command("mute"), "mute"),
        stepButton("+", "volume_up"),
        imageButton("stop", "stop", () => TinyPPI.command("stop")),
        imageButton("chapter-next", "chapter_next",
                    () => TinyPPI.command("chapter_next"), "chapter")
      );
      el.transport.append(keys, rest, fineRow());
      labelControls();

      /* The bar is held and dragged -- by a finger, or a mouse with its button
         down -- and the box is told where it was let go; a tap is the
         shortest such drag.  While it is held every chapter is marked and the
         drag snaps onto a dot it comes close to, and a jump to a dot goes to
         where that chapter starts: the box looks the time up in its own list,
         which a spot worked out from a few pixels would miss by seconds either
         way.  The arrow keys do the same as a drag, so the bar is not a
         control only a pointer can reach.

         The pointer is captured, so a drag that strays off the thin bar is
         still the bar's; the stylesheet leaves a finger's vertical swipe to
         the page, and a swipe the browser takes for a scroll cancels the drag
         rather than seeking. */
      el.track.addEventListener("pointerdown", (event) => {
        if (!control || event.button !== 0) return;
        if (!el.track.getBoundingClientRect().width) return;
        drag = { id: event.pointerId };
        if (el.track.setPointerCapture) el.track.setPointerCapture(event.pointerId);
        el.track.classList.add("dragging");
        dragTo(event);
      });
      el.track.addEventListener("pointermove", (event) => {
        if (drag && event.pointerId === drag.id) dragTo(event);
      });
      el.track.addEventListener("pointerup", (event) => {
        if (!drag || event.pointerId !== drag.id) return;
        dragTo(event);
        const { chapter, where } = drag;
        endDrag();
        if (chapter) TinyPPI.command("chapter_goto", chapter.index);
        else TinyPPI.command("seek_percent", where);
      });
      el.track.addEventListener("pointercancel", (event) => {
        if (drag && event.pointerId === drag.id) endDrag();
      });
      /* Page Up and Page Down go a chapter back and on, the way they go a page
         back and on through a document -- on a file that has chapters to go
         to; on one that has not, they are left to scroll the page. */
      el.track.addEventListener("keydown", (event) => {
        if (!control) return;
        if (event.key === "ArrowLeft") TinyPPI.command("seek", -10);
        else if (event.key === "ArrowRight") TinyPPI.command("seek", 10);
        else if (event.key === "PageUp" && chapterCount > 1) TinyPPI.command("chapter_previous");
        else if (event.key === "PageDown" && chapterCount > 1) TinyPPI.command("chapter_next");
        else return;
        event.preventDefault();
      });
    }

    /* The fine adjustments, a row of their own under the keys: the two
       offsets, each a value between a step back and a step on (the value
       itself puts it back to nothing).  Built with the row;
       what they show comes from the snapshots (see renderFine). */
    function fineRow() {
      const fine = document.createElement("div");
      fine.className = "tfine";
      for (const kind of Object.keys(OFFSETS)) fine.append(stepper(kind));
      return fine;
    }

    function stepper(kind) {
      const { step, label } = OFFSETS[kind];
      const wrap = document.createElement("div");
      wrap.className = "fine hidden";
      wrap.dataset.kind = kind;
      const caption = document.createElement("span");
      caption.className = "finelabel";
      caption.dataset.text = label;
      const key = (sign, by) => {
        const node = document.createElement("button");
        node.type = "button";
        node.className = "tbtn finestep";
        node.textContent = sign;
        node.addEventListener("click", () => setOffset(kind, offsets[kind] + by));
        return node;
      };
      const value = document.createElement("button");
      value.type = "button";
      value.className = "tbtn finevalue mono";
      value.dataset.label = "offset_reset";
      value.addEventListener("click", () => setOffset(kind, 0));
      wrap.append(caption, key("\u2212", -step), value, key("+", step));
      return wrap;
    }

    /* Shown at once and sent; the snapshots catch up within the hold. */
    function setOffset(kind, seconds) {
      if (offsets[kind] === null) return;
      const { limit } = OFFSETS[kind];
      const next = Math.min(limit, Math.max(-limit, Math.round(seconds * 1000) / 1000));
      offsets[kind] = next;
      heldUntil[kind] = Date.now() + HOLD_MS;
      showOffset(kind);
      TinyPPI.command(kind, next);
    }

    function showOffset(kind) {
      const wrap = el.transport.querySelector('.fine[data-kind="' + kind + '"]');
      wrap.querySelector(".finevalue").textContent = offsetText(offsets[kind]);
    }

    /* An offset Kodi does not report (an older add-on, nothing playing) has
       no stepper; the subtitles' only while there are subtitles to move. */
    function renderFine(controls) {
      for (const kind of Object.keys(OFFSETS)) {
        if (Date.now() >= heldUntil[kind]) {
          const reported = controls[kind];
          offsets[kind] = typeof reported === "number" ? reported : null;
        }
        const wrap = el.transport.querySelector('.fine[data-kind="' + kind + '"]');
        const shown = offsets[kind] !== null &&
          (kind !== "subtitle_delay" || !!controls.subtitle_on);
        wrap.classList.toggle("hidden", !shown);
        if (offsets[kind] !== null) showOffset(kind);
      }
    }

    /* The bar under a held pointer: the fill, the clock under it and the
       chapter over it follow the pointer rather than the player -- a bar
       dragged half an hour on while the clock insists on the old position is
       a bar nobody can aim -- and come back to the player once it lets go. */
    function dragTo(event) {
      const box = el.track.getBoundingClientRect();
      const raw = Math.min(100, Math.max(0, (event.clientX - box.left) / box.width * 100));
      el.chapters.drag(raw);
      const chapter = el.chapters.hit(event.clientX);
      drag.chapter = chapter;
      drag.where = chapter ? chapter.at : raw;
      if (chapter) el.chapters.drag(drag.where);
      el.bar.style.width = drag.where + "%";
      const clock = clockAt(drag.where, duration);
      if (clock) el.elapsed.textContent = clock;
    }

    function endDrag() {
      drag = null;
      el.track.classList.remove("dragging");
      el.chapters.drag(null);
    }

    /* Names the controls that have no writing on them, and the two that carry
       nothing but a sign.  Called when the row is built and again when the strings
       arrive, because the two can happen in either order -- the stream opens
       before /api/hello is asked (see boot in js/core.js), so on a fresh page
       the first snapshot usually builds this row while the English fallbacks
       are still all there is. */
    function labelControls() {
      for (const node of el.transport.querySelectorAll("[data-label]")) {
        const name = TinyPPI.T[node.dataset.label];
        if (!name) continue;
        node.setAttribute("aria-label", name);
        if (node.tagName === "BUTTON") node.title = name;
      }
      for (const node of el.transport.querySelectorAll("[data-text]")) {
        node.textContent = TinyPPI.T[node.dataset.text] || "";
      }
    }

    function renderTransport(snapshot) {
      const hadControl = control;
      control = !!snapshot.control;
      duration = snapshot.duration || "";
      const controls = snapshot.controls || {};
      if (!control) {
        if (drag) endDrag();
        setControlsOpen(false, false);
        controlToggle.classList.add("hidden");
        el.transport.classList.add("hidden");
        el.tracks.classList.add("hidden");
        el.track.classList.remove("seekable");
        return;
      }
      buildTransport();
      if (!hadControl) {
        setControlsOpen(TinyPPI.disclosureState(controlStateKey, false), false);
      }
      controlToggle.classList.remove("hidden");
      el.transport.classList.remove("hidden");
      el.track.classList.add("seekable");

      const play = el.transport.querySelector(".tbtn.play");
      if (play) setButtonIcon(play, snapshot.paused ? "play" : "pause");

      /* A file with no chapters has nowhere for these to go, and the add-on
         refuses them rather than seeking instead -- so they are turned off here
         rather than left to fail.  Dimmed and kept in place: a row that loses
         two keys when the film changes is a row whose buttons move out from
         under the thumb that was aiming at one. */
      chapterCount = Number(controls.chapters) || 0;
      for (const key of el.transport.querySelectorAll(".tbtn.chapter")) {
        key.disabled = chapterCount < 2;
      }

      const mute = el.transport.querySelector(".mute");
      if (mute) {
        mute.classList.toggle("on", !!controls.muted);
        setButtonIcon(mute, controls.muted ? "volume-muted" : "volume");
      }
      renderFine(controls);
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

      const audioPick = document.getElementById("pick-audio");
      if (audioPick) audioPick.value = String(controls.audio_current);
      const subPick = document.getElementById("pick-subtitle");
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

    return {
      render: renderTransport,
      /* Where a held pointer has the bar, or null: while it is held the
         snapshots leave the fill and the clock to it (see renderNow in
         js/live-panels.js). */
      held() {
        return drag ? drag.where : null;
      },
      /* The toggle's name, the keys' names, and the pickers marked stale so
         the next snapshot builds them in the new language. */
      strings(T) {
        controlToggle.setAttribute("aria-label", T.controls);
        controlToggle.title = T.controls;
        labelControls();
        trackKey = "";
      },
      /* Put away when nothing plays. */
      reset() {
        trackKey = "";
        setControlsOpen(false, false);
      }
    };
  }

  return { create, icon: uiIcon, setIcon: setButtonIcon };

})();
