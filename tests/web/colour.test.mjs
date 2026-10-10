// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The cover tint's colour arithmetic (resources/web/js/colour.js).

import assert from "node:assert/strict";
import { test } from "node:test";
import { bare } from "./harness.mjs";

const colour = bare("colour.js").TinyPPIColour;
const { contrast, luminance, rgbToOklch, oklchToRgb, composite,
        srgbToLinear, linearToSrgb, inGamut, rgbToOklab, oklabToLinearRgb } = colour;

const close = (actual, expected, tolerance, message) =>
  assert.ok(Math.abs(actual - expected) <= tolerance,
            `${message || ""} ${actual} is not within ${tolerance} of ${expected}`);

test("the sRGB transfer curve round-trips every channel value", () => {
  for (let value = 0; value <= 255; value++) {
    assert.equal(linearToSrgb(srgbToLinear(value)), value);
  }
  assert.equal(linearToSrgb(-0.5), 0);
  assert.equal(linearToSrgb(2), 255);
});

test("luminance and contrast follow WCAG", () => {
  close(luminance([255, 255, 255]), 1, 1e-9);
  close(luminance([0, 0, 0]), 0, 1e-9);
  close(contrast([0, 0, 0], [255, 255, 255]), 21, 1e-9);
  close(contrast([255, 255, 255], [0, 0, 0]), 21, 1e-9, "symmetric:");
  close(contrast([119, 119, 119], [255, 255, 255]), 4.48, 0.01);   // the classic #777
  assert.equal(contrast([40, 80, 120], [40, 80, 120]), 1);
});

test("OKLab of the reference colours", () => {
  const white = rgbToOklab([255, 255, 255]);
  close(white[0], 1, 1e-4); close(white[1], 0, 1e-4); close(white[2], 0, 1e-4);
  const red = rgbToOklch([255, 0, 0]);
  close(red[0], 0.628, 1e-3); close(red[1], 0.2577, 1e-3); close(red[2], 29.23, 0.05);
});

test("OKLCh round-trips colours inside the gamut", () => {
  for (const rgb of [[255, 0, 0], [12, 200, 90], [30, 30, 200], [128, 128, 128], [250, 240, 10]]) {
    const [l, c, h] = rgbToOklch(rgb);
    const back = oklchToRgb(l, c, h);
    back.forEach((channel, i) => close(channel, rgb[i], 1, `channel ${i} of ${rgb}:`));
  }
});

test("too much chroma gives way, lightness and hue do not", () => {
  for (const hue of [0, 60, 140, 220, 300]) {
    for (const lightness of [0.2, 0.5, 0.85]) {
      const rgb = oklchToRgb(lightness, 0.5, hue);           // far outside sRGB
      rgb.forEach((channel) => assert.ok(channel >= 0 && channel <= 255));
      const [l, c, h] = rgbToOklch(rgb);
      close(l, lightness, 0.01, `lightness at hue ${hue}:`);
      // Dark colours have only a few 8-bit steps per channel, so rounding
      // alone moves their hue by several degrees.
      const allowed = lightness < 0.3 ? 10 : 1;
      const drift = Math.abs(((h - hue + 540) % 360) - 180);
      assert.ok(c > 0.03 && drift < allowed, `hue ${hue} at ${lightness} drifted to ${h}`);
    }
  }
});

test("the gamut check allows rounding only", () => {
  assert.equal(inGamut([0, 0.5, 1]), true);
  assert.equal(inGamut([-0.0005, 1.0005, 0.2]), true);
  assert.equal(inGamut([-0.01, 0.5, 0.5]), false);
  assert.equal(inGamut(oklabToLinearRgb(0.6, 0.3, 0)), false);
});

test("compositing is a straight mix per channel", () => {
  assert.deepEqual(Array.from(composite([0, 0, 0], [200, 100, 50], 0.5)), [100, 50, 25]);
  assert.deepEqual(Array.from(composite([10, 20, 30], [200, 100, 50], 1)), [10, 20, 30]);
  assert.deepEqual(Array.from(composite([10, 20, 30], [200, 100, 50], 0)), [200, 100, 50]);
});
