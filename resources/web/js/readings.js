// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   What the live panels say, worked out from a snapshot: the format badges of
   the now-playing card and the wording of the history's events.

   Nothing here touches the page, so it is tested on its own
   (tests/web/readings.test.mjs); js/live-panels.js draws the results.
   Loaded after core.js, whose strings (TinyPPI.T) it reads.
=========================================================================== */

window.TinyPPIReadings = (function () {

  /* --- Format badges ----------------------------------------------------
     The same badges, read the same way, as the mobile app's now-playing card
     (util/SourceLabel.kt there): the picture -- how big the coded frame is,
     how it is graded and what it is converted to, and IMAX -- and the sound --
     the codec, what rides on it and how wide it is.

     Read out of the printed rows rather than off fields of their own, since
     the snapshot has none: the audio codec arrives as the row the overlay
     prints, and a Dolby Vision profile as a reading among the others.  Rows
     are found by id, not by label, because the labels are translated. */

  const AUDIO_GROUP = "audio";
  const AUDIO_CODEC_ROW = "audio.32238";
  const CHANNEL_LAYOUT = /^\d+\.\d+$/;

  /* Longest first, so "IMAX Enhanced" is found whole rather than as an IMAX
     with a spare word after it.  Brand names, which are not translated. */
  const MARKS = ["IMAX Enhanced", "IMAX", "Dolby Atmos", "Atmos",
                 "DTS:X", "DTS-X", "DTSX"];
  const SPELLINGS = { "DTSX": "DTS:X", "DTS-X": "DTS:X", "DOLBY ATMOS": "Atmos" };

  /* The standard widths themselves, widest first: a release is authored at
     one of these, and a coded width names the format where a height, which
     changes with the aspect ratio, would not. */
  const RESOLUTIONS = [[7680, "8K"], [4096, "DCI 4K"], [3840, "UHD"],
                       [2560, "QHD"], [1920, "FHD"], [1280, "HD"]];

  function grade(token) {
    const key = String(token || "").trim().toLowerCase();
    if (!key || key === "sdr") return "SDR";
    if (key.includes("dolby") || key.includes("dv")) return "Dolby Vision";
    if (key.includes("hdr10plus") || key.includes("hdr10+")) return "HDR10+";
    if (key.includes("hlg")) return "HLG";
    if (key.includes("hdr")) return "HDR10";
    return "SDR";
  }

  function marksIn(group) {
    let rest = (group.rows || [])
      .map((row) => (row.value || "") + " " + (row.detail || "")).join(" ");
    const found = [];
    for (const mark of MARKS) {
      const pattern = new RegExp(mark.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      if (!rest.match(pattern)) continue;
      found.push(SPELLINGS[mark.toUpperCase()] || mark);
      /* Taken out of the running text, so a longer name already found does
         not hand its own words to a shorter one after it. */
      rest = rest.replace(pattern, " ");
    }
    return found;
  }

  function resolutionBadge(frame) {
    const width = frame && frame.w > 0 && frame.h > 0 ? frame.w : 0;
    if (!width) return null;
    const hit = RESOLUTIONS.find(([from]) => width >= from);
    return hit ? hit[1] : "SD";
  }

  /* "P7.6 FEL", "P8.1" -- or null where nothing says. */
  function dolbyVisionSuffix(snapshot) {
    const readings = [];
    for (const group of snapshot.groups || []) {
      for (const row of group.rows || []) readings.push([row.label || "", row.value || ""]);
    }
    for (const row of snapshot.metadata || []) readings.push([row.name || "", row.value || ""]);

    let profile = null;
    for (const [name, value] of readings) {
      if (!/profile/i.test(name)) continue;
      const number = /\d+(\.\d+)?/.exec(value);
      if (number) { profile = number[0]; break; }
    }

    let layer = null;
    for (const [name, value] of readings) {
      const hit = /\b[FM]EL\b/i.exec(name + " " + value);
      if (hit) { layer = hit[0].toUpperCase(); break; }
    }
    if (!layer) {
      const affirmative = ["yes", "true", "1", "present", "ja", "on"];
      const enhanced = readings.some(([name, value]) => {
        if (value.replace(/ /g, "").toUpperCase().includes("+EL")) return true;
        const asks = /enhancement/i.test(name)
          || name.split(/[ .()]/).some((word) => word.toLowerCase() === "el");
        return asks && affirmative.includes(value.trim().toLowerCase());
      }) || (profile !== null && "47".includes(profile.charAt(0)));
      if (enhanced) layer = "EL";
    }

    if (profile && layer) return "P" + profile + " " + layer;
    if (profile) return "P" + profile;
    return layer;
  }

  function sourceBadge(snapshot) {
    const label = grade(snapshot.hdr_type);
    if (label !== "Dolby Vision") return label;
    const detail = dolbyVisionSuffix(snapshot);
    return detail ? "DV " + detail : "DV";
  }

  /* What the picture leaves as, where that is not what it came in as.  The
     VS10 output is read as well, for a backend whose output_type lags. */
  function conversionTarget(snapshot) {
    const source = String(snapshot.hdr_type || "sdr").toLowerCase();
    const output = String(snapshot.output_type || "");
    if (output && output.toLowerCase() !== source) return grade(output);
    const vs10 = String((snapshot.vs10 || {}).output || "").trim().toLowerCase();
    let target = null;
    if (vs10.includes("sdr")) target = "SDR";
    else if (vs10.includes("hdr10+") || vs10.includes("hdr10plus")) target = "HDR10+";
    else if (vs10.includes("hdr10")) target = "HDR10";
    else if (vs10.includes("hlg")) target = "HLG";
    return target && target !== grade(source) ? target : null;
  }

  function pictureBadges(snapshot) {
    const badges = [];
    const resolution = resolutionBadge((snapshot.metrics || {}).frame);
    if (resolution) badges.push(resolution);
    const target = conversionTarget(snapshot);
    badges.push(target ? sourceBadge(snapshot) + " → " + target : sourceBadge(snapshot));
    for (const group of snapshot.groups || []) {
      if (group.id !== AUDIO_GROUP) badges.push(...marksIn(group));
    }
    return [...new Set(badges)];
  }

  function soundBadges(snapshot) {
    const audio = (snapshot.groups || []).find((group) => group.id === AUDIO_GROUP);
    if (!audio || !(audio.rows || []).length) return [];
    const row = audio.rows.find((entry) => entry.id === AUDIO_CODEC_ROW) || audio.rows[0];
    /* A codec Kodi could not name is no badge. */
    const value = (row.value || "").trim();
    const words = value && value !== TinyPPI.T.na ? value.split(/\s+/) : [];
    const last = words[words.length - 1];
    const layout = last && CHANNEL_LAYOUT.test(last) ? last : null;
    const codec = (layout ? words.slice(0, -1) : words).join(" ");
    const badges = [];
    if (codec) badges.push(codec);
    badges.push(...marksIn(audio));
    if (layout) badges.push(layout);
    return [...new Set(badges)];
  }

  /* A fallback is kept beside every localized key.  The stream deliberately
     opens before /api/hello has returned, so the first history can be drawn
     while some translations are not here yet.  An event must still have a
     name during that short window instead of leaving a mysterious blank
     column behind. */
  const EVENT_LABEL = {
    vs10: ["vs10", "VS10 output"],
    mode: ["ev_mode", "Display mode"],
    audio: ["audio_track", "Audio track"],
    subtitle: ["subtitles", "Subtitles"],
    temperature: ["temperature", "Temperature"],
    cpu: ["processor", "Processor"],
    fps: ["fps", "FPS"]
  };
  const SWITCH_EVENT_KINDS = new Set(["vs10", "mode", "audio", "subtitle"]);

  function historySwitches(history) {
    if (!history) return null;
    const total = Number(history.switches);
    if (Number.isFinite(total)) return total;
    /* Compatibility with a backend that was already running during the
       update: older history responses have no total, but their event rows
       still let the visible list and its figure agree. */
    return (history.events || []).filter((entry) =>
      SWITCH_EVENT_KINDS.has(entry.kind)).length;
  }

  function eventLabel(kind) {
    const label = EVENT_LABEL[kind];
    if (!label) return kind || "Event";
    return TinyPPI.T[label[0]] || label[1];
  }

  /* A transition names two whole VS10 output states -- "SDR BT.709" to
     "DV-LL BT.2020nc" is a realistic width.  The mobile layout gives every
     event a separate value line so transitions and short values align. */
  function isTransition(entry) {
    return entry.from !== undefined && entry.to !== undefined;
  }

  function eventText(entry) {
    const stateText = (value) => {
      if (value === "__off__") return TinyPPI.T.off;
      if (value === null || value === undefined) return TinyPPI.T.na;
      let text = String(value);
      if (entry.kind === "audio" || entry.kind === "subtitle") {
        /* Index and ISO language are useful for identifying a track inside
           the backend, but the event already says Audio track/Subtitles and
           the track name itself is the useful part for the reader. */
        text = text
          .replace(/^#\d+\s*(?:·\s*)?/, "")
          .replace(/^[A-Z]{2,3}\s*·\s*/i, "");
      }
      return text || TinyPPI.T.na;
    };
    if (isTransition(entry)) return stateText(entry.to);
    if (entry.kind === "temperature") return Math.round(entry.value) + " °C";
    if (entry.kind === "cpu" || String(entry.kind).startsWith("cache_")) {
      return Math.round(entry.value) + "%";
    }
    return entry.value === null || entry.value === undefined
      ? TinyPPI.T.na : String(entry.value);
  }

  /* Which way a transition went, for the arrow beside its value: 1 up, -1
     down, 0 for one that has no direction to show.  A frame rate is the event
     this is for -- 24 to 60 and back is a direction, where "SDR BT.709" to
     "DV-LL BT.2020nc" is not one at all.

     The kinds whose states really are numbers are named rather than left to
     Number(): a track named "5.1" giving way to one named "2.0" reads as a
     number to Number() and as a fall to nobody. */
  const TREND_KINDS = new Set(["fps"]);

  function eventTrend(entry) {
    if (!TREND_KINDS.has(entry.kind) || !isTransition(entry)) return 0;
    const from = Number(entry.from);
    const to   = Number(entry.to);
    if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) return 0;
    return to > from ? 1 : -1;
  }

  return {
    grade, marksIn, resolutionBadge, dolbyVisionSuffix, sourceBadge,
    conversionTarget, pictureBadges, soundBadges,
    historySwitches, eventLabel, isTransition, eventText, eventTrend
  };

})();
