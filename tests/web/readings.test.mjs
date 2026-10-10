// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The now-playing card's format badges and the history's event wording
// (resources/web/js/readings.js).

import assert from "node:assert/strict";
import { after, test } from "node:test";
import { bare } from "./harness.mjs";

const window = bare("core.js", "readings.js");
after(() => window.close());
const R = window.TinyPPIReadings;
const plain = (value) => JSON.parse(JSON.stringify(value));

const audio = (value, detail = "") => ({
  id: "audio", rows: [{ id: "audio.32238", label: "Codec", value, detail }]
});

test("grades from the published HDR type", () => {
  for (const [token, label] of [
    ["", "SDR"], ["sdr", "SDR"], ["dolbyvision", "Dolby Vision"], ["DV", "Dolby Vision"],
    ["hdr10plus", "HDR10+"], ["HDR10+", "HDR10+"], ["hlg", "HLG"], ["hdr10", "HDR10"],
    [null, "SDR"], ["unknown", "SDR"],
  ]) assert.equal(R.grade(token), label, String(token));
});

test("resolution badges by coded width", () => {
  for (const [frame, badge] of [
    [{ w: 3840, h: 1600 }, "UHD"], [{ w: 4096, h: 2160 }, "DCI 4K"], [{ w: 1920, h: 800 }, "FHD"],
    [{ w: 1280, h: 720 }, "HD"], [{ w: 720, h: 576 }, "SD"], [{ w: 7680, h: 4320 }, "8K"],
    [null, null], [{ w: 0, h: 0 }, null], [{ w: 3840, h: 0 }, null],
  ]) assert.equal(R.resolutionBadge(frame), badge, JSON.stringify(frame));
});

test("marks are found whole and spelled one way", () => {
  assert.deepEqual(plain(R.marksIn(audio("TrueHD Dolby Atmos 7.1"))), ["Atmos"]);
  assert.deepEqual(plain(R.marksIn(audio("DTS-HD MA", "DTSX"))), ["DTS:X"]);
  assert.deepEqual(plain(R.marksIn({ rows: [{ value: "IMAX Enhanced" }] })), ["IMAX Enhanced"]);
  assert.deepEqual(plain(R.marksIn({ rows: [] })), []);
});

test("the Dolby Vision profile and layer", () => {
  const dv = (rows, metadata = []) => ({ hdr_type: "dolbyvision",
    groups: [{ id: "dv", rows }], metadata });
  assert.equal(R.sourceBadge(dv([{ label: "Profile", value: "7.6" },
                                   { label: "Layer", value: "FEL" }])), "DV P7.6 FEL");
  assert.equal(R.sourceBadge(dv([{ label: "Profile", value: "8.1" }])), "DV P8.1");
  assert.equal(R.sourceBadge(dv([{ label: "Profile", value: "7" }])), "DV P7 EL");     // P7 has one
  assert.equal(R.sourceBadge(dv([{ label: "EL present", value: "yes" }])), "DV EL");
  assert.equal(R.sourceBadge(dv([], [{ name: "Profile", value: "5" }])), "DV P5");
  assert.equal(R.sourceBadge(dv([])), "DV");
  assert.equal(R.sourceBadge({ hdr_type: "hdr10" }), "HDR10");
});

test("a conversion shows where the picture goes", () => {
  assert.equal(R.conversionTarget({ hdr_type: "hdr10", output_type: "dolbyvision" }), "Dolby Vision");
  assert.equal(R.conversionTarget({ hdr_type: "hdr10", output_type: "hdr10" }), null);
  assert.equal(R.conversionTarget({ hdr_type: "dolbyvision", vs10: { output: "SDR BT709" } }), "SDR");
  assert.equal(R.conversionTarget({ hdr_type: "", vs10: { output: "SDR" } }), null);
  assert.equal(R.conversionTarget({}), null);
});

test("picture and sound badges", () => {
  const snapshot = {
    hdr_type: "hdr10", output_type: "dolbyvision", metrics: { frame: { w: 3840, h: 2160 } },
    groups: [{ id: "video", rows: [{ value: "IMAX" }] }, audio("TrueHD Atmos 7.1")],
  };
  assert.deepEqual(plain(R.pictureBadges(snapshot)), ["UHD", "HDR10 → Dolby Vision", "IMAX"]);
  assert.deepEqual(plain(R.soundBadges(snapshot)), ["TrueHD Atmos", "Atmos", "7.1"]);
  assert.deepEqual(plain(R.soundBadges({ groups: [audio("N/A")] })), []);
  assert.deepEqual(plain(R.soundBadges({ groups: [] })), []);
  assert.deepEqual(plain(R.soundBadges({ groups: [audio("AAC")] })), ["AAC"]);
});

test("events: names, values and trends", () => {
  assert.equal(R.eventLabel("mode"), "Display mode");
  assert.equal(R.eventLabel("cache_low"), "cache_low");
  assert.equal(R.eventLabel(undefined), "Event");
  const saved = window.TinyPPI.T.ev_mode;
  window.TinyPPI.T.ev_mode = "Anzeigemodus";
  try {
    assert.equal(R.eventLabel("mode"), "Anzeigemodus");
  } finally {
    window.TinyPPI.T.ev_mode = saved;
  }

  assert.equal(R.eventText({ kind: "audio", from: "#1 · ENG · English", to: "#2 · GER · Deutsch" }), "Deutsch");
  assert.equal(R.eventText({ kind: "subtitle", from: "x", to: "__off__" }), "Off");
  assert.equal(R.eventText({ kind: "mode", from: "a", to: null }), "N/A");
  assert.equal(R.eventText({ kind: "temperature", value: 76.6 }), "77 °C");
  assert.equal(R.eventText({ kind: "cpu", value: 99.5 }), "100%");
  assert.equal(R.eventText({ kind: "other" }), "N/A");

  assert.equal(R.eventTrend({ kind: "fps", from: 24, to: 60 }), 1);
  assert.equal(R.eventTrend({ kind: "fps", from: 60, to: 24 }), -1);
  assert.equal(R.eventTrend({ kind: "fps", from: 24, to: 24 }), 0);
  assert.equal(R.eventTrend({ kind: "audio", from: "5.1", to: "2.0" }), 0);   // not a number
  assert.equal(R.eventTrend({ kind: "fps", value: 24 }), 0);
});

test("switch totals, from the add-on or counted", () => {
  assert.equal(R.historySwitches(null), null);
  assert.equal(R.historySwitches({ switches: 4, events: [] }), 4);
  assert.equal(R.historySwitches({ events: [{ kind: "vs10" }, { kind: "fps" }, { kind: "audio" }] }), 2);
});

test("rows and lists the snapshot leaves out count as empty", () => {
  assert.deepEqual(plain(R.marksIn({})), []);
  assert.deepEqual(plain(R.marksIn({ rows: [{ detail: "Dolby Atmos" }, {}] })), ["Atmos"]);
  // A Dolby Vision snapshot with nothing to read still names its grade.
  assert.equal(R.sourceBadge({ hdr_type: "dolbyvision" }), "DV");
  assert.equal(R.sourceBadge({ hdr_type: "dolbyvision",
    groups: [{ id: "video" }, { id: "dv", rows: [{ value: "8.1" }, { label: "Profile" }] }],
    metadata: [{ value: "FEL" }, { name: "Profile" }] }), "DV FEL");
  assert.equal(R.dolbyVisionSuffix({ metadata: [{ name: "DV profile", value: "dvhe.08.06" }] }), "P08.06");
  assert.equal(R.dolbyVisionSuffix({}), null);
});

test("an enhancement layer is read from a '+ EL' reading or a yes beside its name", () => {
  const dv = (rows) => ({ hdr_type: "dolbyvision", groups: [{ id: "dv", rows }] });
  assert.equal(R.sourceBadge(dv([{ label: "Layers", value: "BL + EL" }])), "DV EL");
  assert.equal(R.sourceBadge(dv([{ label: "Enhancement layer", value: " Present " }])), "DV EL");
  assert.equal(R.sourceBadge(dv([{ label: "Layer (EL)", value: "ja" }])), "DV EL");
  assert.equal(R.sourceBadge(dv([{ label: "EL present", value: "no" }])), "DV");
  assert.equal(R.sourceBadge(dv([{ label: "Profile", value: "4" }])), "DV P4 EL");   // P4 has one too
  assert.equal(R.sourceBadge(dv([{ label: "Profile", value: "MEL" }, { label: "Profile", value: "n/a" }])),
               "DV MEL");
});

test("the VS10 output names the target where output_type does not", () => {
  const vs10 = (hdr_type, output) => R.conversionTarget({ hdr_type, vs10: { output } });
  assert.equal(vs10("dolbyvision", "HDR10+ BT2020"), "HDR10+");
  assert.equal(vs10("dolbyvision", "hdr10plus"), "HDR10+");
  assert.equal(vs10("dolbyvision", " HDR10 BT.2020 "), "HDR10");
  assert.equal(vs10("sdr", "HLG"), "HLG");
  assert.equal(vs10("hlg", "HLG"), null);                 // already that
  assert.equal(vs10("dolbyvision", "DV-LL BT.2020nc"), null);
  assert.equal(R.conversionTarget({ output_type: "hdr10" }), "HDR10");   // from SDR
});

test("picture badges without a frame, groups or conversion", () => {
  assert.deepEqual(plain(R.pictureBadges({})), ["SDR"]);
  assert.deepEqual(plain(R.pictureBadges({ hdr_type: "hdr10", metrics: {} })), ["HDR10"]);
  assert.deepEqual(plain(R.pictureBadges({ hdr_type: "hlg", metrics: { frame: { w: 2560, h: 1440 } },
    groups: [{ id: "video", rows: [{ value: "IMAX Enhanced" }] }, { id: "audio", rows: [{ value: "IMAX" }] }] })),
  ["QHD", "HLG", "IMAX Enhanced"]);     // the audio group's marks are the sound's
});

test("sound badges take the codec row, or the first row where it is missing", () => {
  assert.deepEqual(plain(R.soundBadges({})), []);
  assert.deepEqual(plain(R.soundBadges({ groups: [{ id: "audio" }] })), []);
  assert.deepEqual(plain(R.soundBadges({ groups: [{ id: "audio", rows: [
    { id: "audio.other", value: "DTS-HD MA 5.1", detail: "DTS:X" },
    { id: "audio.lang", value: "English" }] }] })), ["DTS-HD MA", "DTS:X", "5.1"]);
  assert.deepEqual(plain(R.soundBadges({ groups: [{ id: "audio", rows: [{ id: "audio.32238", detail: "Atmos" }] }] })),
                   ["Atmos"]);
  // A layout alone is no codec.
  assert.deepEqual(plain(R.soundBadges({ groups: [audio("2.0")] })), ["2.0"]);
});

test("event names fall back to English until the strings arrive", () => {
  const saved = window.TinyPPI.T.fps;
  window.TinyPPI.T.fps = "";
  try {
    assert.equal(R.eventLabel("fps"), "FPS");
  } finally {
    window.TinyPPI.T.fps = saved;
  }
  assert.equal(R.eventLabel("vs10"), window.TinyPPI.T.vs10);
  assert.equal(R.eventLabel("subtitle"), "Subtitles");
});

test("event values: track names, empty states, cache and plain readings", () => {
  assert.equal(R.eventText({ kind: "subtitle", from: "__off__", to: "#3 · FRE · Français" }), "Français");
  assert.equal(R.eventText({ kind: "audio", from: "x", to: "#2" }), "N/A");     // nothing but the index
  assert.equal(R.eventText({ kind: "audio", from: "x", to: "Commentary" }), "Commentary");
  assert.equal(R.eventText({ kind: "vs10", from: "SDR", to: "" }), "N/A");
  assert.equal(R.eventText({ kind: "vs10", from: "SDR BT.709", to: "#1 · DV-LL" }), "#1 · DV-LL");   // kept whole
  assert.equal(R.eventText({ kind: "cache_low", value: 12.4 }), "12%");
  assert.equal(R.eventText({ kind: "bitrate", value: 0 }), "0");
  assert.equal(R.eventText({ kind: "bitrate", value: "38 Mb/s" }), "38 Mb/s");
  assert.equal(R.eventText({ kind: "bitrate", value: null }), "N/A");
  assert.equal(R.isTransition({ from: null, to: "x" }), true);
  assert.equal(R.isTransition({ to: "x" }), false);
});

test("counted switches without any events are none", () => {
  assert.equal(R.historySwitches({}), 0);
  assert.equal(R.historySwitches({ switches: "3", events: [{ kind: "mode" }] }), 3);
});
