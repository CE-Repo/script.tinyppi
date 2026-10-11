// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The remote on the now-playing card: the drawer and the key that opens it,
   the transport row and the track pickers.

   Loaded after core.js and before js/live-panels.js, which builds the card
   and hands the remote its nodes (create); the icons are shared with the
   rest of the card (icon, setIcon).
=========================================================================== */

window.TinyPPIRemote = (function () {

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

  /* The remote in *el* (nowCard, drawer, transport, tracks, track, bar);
     *pageState* is what the drawer's state is remembered under. */
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
    let trackKey = "";
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
      el.transport.append(keys, rest);
      labelControls();

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
    }

    function renderTransport(snapshot) {
      const hadControl = control;
      control = !!snapshot.control;
      const controls = snapshot.controls || {};
      if (!control) {
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
      const chapters = Number(controls.chapters) || 0;
      for (const key of el.transport.querySelectorAll(".tbtn.chapter")) {
        key.disabled = chapters < 2;
      }

      const mute = el.transport.querySelector(".mute");
      if (mute) {
        mute.classList.toggle("on", !!controls.muted);
        setButtonIcon(mute, controls.muted ? "volume-muted" : "volume");
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
