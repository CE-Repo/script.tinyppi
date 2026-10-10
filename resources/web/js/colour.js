// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   Colour arithmetic for the cover tint (js/cover-tint.js).

   sRGB for what the browser paints, OKLab for everything that has to keep a
   colour recognisable while its lightness moves.  Colours are [r, g, b]
   arrays of 0-255.  Nothing here touches the page, so it is tested on its own
   (tests/web/colour.test.mjs).
=========================================================================== */

window.TinyPPIColour = (function () {

  function srgbToLinear(channel) {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function linearToSrgb(value) {
    const c = value <= 0.0031308
      ? value * 12.92
      : 1.055 * Math.pow(Math.max(value, 0), 1 / 2.4) - 0.055;
    return Math.max(0, Math.min(255, Math.round(c * 255)));
  }

  function luminance(rgb) {
    return 0.2126 * srgbToLinear(rgb[0]) +
           0.7152 * srgbToLinear(rgb[1]) +
           0.0722 * srgbToLinear(rgb[2]);
  }

  function contrast(a, b) {
    const first = luminance(a);
    const second = luminance(b);
    return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
  }

  function rgbToOklab(rgb) {
    const lr = srgbToLinear(rgb[0]), lg = srgbToLinear(rgb[1]), lb = srgbToLinear(rgb[2]);
    const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
    const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
    const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
    return [
      0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    ];
  }

  /* The linear-light sRGB an OKLab colour would need, which for a colour
     outside the gamut is a channel below 0 or above 1 -- which is what
     oklchToRgb tests. */
  function oklabToLinearRgb(L, a, b) {
    const lRoot = L + 0.3963377774 * a + 0.2158037573 * b;
    const mRoot = L - 0.1055613458 * a - 0.0638541728 * b;
    const sRoot = L - 0.0894841775 * a - 1.2914855480 * b;
    const l = lRoot ** 3, m = mRoot ** 3, s = sRoot ** 3;
    return [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    ];
  }

  function rgbToOklch(rgb) {
    const lab = rgbToOklab(rgb);
    return [lab[0], Math.hypot(lab[1], lab[2]),
            (Math.atan2(lab[2], lab[1]) * 180 / Math.PI + 360) % 360];
  }

  function inGamut(channels) {
    return channels.every((c) => c >= -0.001 && c <= 1.001);
  }

  /* An OKLCh colour as sRGB, with the chroma pulled in until it fits.

     Lightness and hue are what the caller asked for and are never touched --
     clamping the channels instead would shift both.  Only the chroma gives
     way, which is the one part of the colour that has no room left at that
     lightness. */
  function oklchToRgb(lightness, chroma, hue) {
    const rad = hue * Math.PI / 180;
    const at = (c) => oklabToLinearRgb(lightness, c * Math.cos(rad), c * Math.sin(rad));

    let fits = chroma;
    if (!inGamut(at(chroma))) {
      let low = 0, high = chroma;
      for (let i = 0; i < 16; i++) {
        const mid = (low + high) / 2;
        if (inGamut(at(mid))) low = mid; else high = mid;
      }
      fits = low;
    }
    return at(fits).map(linearToSrgb);
  }

  /* Two colours laid over one another the way the browser composites them: in
     sRGB, straight down the channels.  Used to work out what a scrim over a
     poster over the card's own colour actually ends up as. */
  function composite(top, bottom, alpha) {
    return top.map((c, i) => Math.round(c * alpha + bottom[i] * (1 - alpha)));
  }

  return {
    srgbToLinear, linearToSrgb, luminance, contrast, rgbToOklab,
    oklabToLinearRgb, rgbToOklch, inGamut, oklchToRgb, composite
  };

})();
