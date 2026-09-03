// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   The colours the poster is made of, as the surface every card is painted
   with.

   Two areas take them, and they are not painted alike.  The now-playing card
   has the poster standing in it, so it gets a broad glow in the artwork's
   representative colour, strongest beside the poster and fading gently into
   the panel.  Every other card gets that accent as a flat colour because
   there is no artwork in those to arrange anything around.  The hero stays
   the loudest thing on the page that way, and the rest of it agrees with what
   is playing without competing.

   Only the adaptive theme reads any of this; every other one ignores it and
   the card keeps the plain panel colour.  Three things decide what comes out,
   and each is a step of its own:

     where a colour is taken from  the poster is read region by region, then a
                                   representative accent is chosen from those
                                   regions (see regionalPalette/accentBase).
     how far it may be taken       the lightness is set in OKLab, which leaves
                                   the hue alone and keeps the colour from
                                   washing out on the way down (see tintColor).
     how much of it survives       the scrim is solved for this poster against
                                   the contrast the text on it needs, instead
                                   of being one fixed value for every one
                                   (see solveScrim).

   live-panels.js hands the poster over whenever the film changes; the theme
   and its strength are watched here, since either can change without it.
=========================================================================== */

window.TinyPPICover = (function () {

  /* The poster is only read for its colours, so it is sampled small: a few
     thousand pixels are plenty to find what a picture is mostly made of. */
  const SAMPLE_MAX = 48;

  /* Colours are counted in buckets this many bits per channel wide, so shades
     of the same thing land together instead of each counting for itself. */
  const BUCKET_BITS = 5;

  /* How far apart two picked colours have to be (summed per-channel distance,
     of a possible 765) to count as different ones.  Two neighbouring parts of
     a poster are often the same colour; the second then takes its runner-up,
     so the gradient has something to fade between. */
  const MIN_DISTANCE = 48;

  /* The five regions a poster is read in, as fractions of its frame: the four
     quadrants and the centre.  The order is the order the stops are placed in,
     which is what ties the gradient to the artwork's own composition -- a
     sunset along the top of the poster ends up along the top of the card. */
  const REGIONS = [
    [0, 0, 0.5, 0.5],
    [0.5, 0, 1, 0.5],
    [0, 0.5, 0.5, 1],
    [0.5, 0.5, 1, 1],
    [0.25, 0.25, 0.75, 0.75]
  ];

  /* Below this much chroma a colour is a grey, and a grey has no colour to
     keep. */
  const GREY_CHROMA = 0.012;

  /* Colours lose chroma on the way down -- a poster's bright sky is a
     saturated blue at full lightness and a dull one at a fifth of it.  These
     take it back: the floor gives a near-grey enough tint to read as one, the
     gain restores what the darkening cost.  Both are held inside the sRGB
     gamut by oklchToRgb. */
  const MIN_CHROMA = 0.055;
  const CHROMA_GAIN = 1.35;

  /* What the scrim is made of, and how much of it there may be.  The colour is
     the page's own near-black; only how much of it is laid on is decided per
     poster. */
  const SCRIM_RGB = [11, 13, 16];
  const SCRIM_MIN = 0.10;
  const SCRIM_MAX = 0.92;

  /* The contrast the surface under the card's text has to leave -- far above
     the 4.5:1 the text itself would need, because a title and a filename are
     read at a glance from across the room. */
  const TEXT_RATIO = 11;

  /* What the quietest marks on that surface are lifted to: the metadata line
     and the filename, which are the first things to run out of margin once the
     card is carrying a colour. */
  const MARK_RATIO = 6;

  /* The accent the card's own marks take -- its badges, its progress bar and
     the frame around the poster.  A surface has to stay dark enough for the
     text on it; a mark sits on that surface and has to stand off it, at one
     predictable strength whatever the poster is.  Its lightness and chroma are
     kept inside this deliberately restrained range and then lifted only as far
     as the surface it landed on makes necessary. */
  const ACCENT_MIN_LIGHTNESS = 0.52;
  const ACCENT_MAX_LIGHTNESS = 0.64;
  const ACCENT_MIN_CHROMA = 0.065;
  const ACCENT_MAX_CHROMA = 0.16;
  const ACCENT_RATIO = 4.5;
  const MIN_ACCENT_CHROMA = 0.035;
  const ACCENT_FAMILY_SPAN = 36;

  /* How strong the tint is, as picked in the theme menu.  Even the loudest
     keeps most of the card's plain surface: the poster is a quiet cue for what
     is playing, not a coloured wash behind it. */
  const STRENGTH_LEVELS = [
    { mix: 0.5, lightness: 0,     chroma: 1 },
    { mix: 1,   lightness: 0,     chroma: 1 },
    { mix: 1.5, lightness: 0.065, chroma: 1.55 }
  ];
  const DEFAULT_STRENGTH = 1;

  const ADAPTIVE = "dark-adaptive";

  /* Every property this file may put on the card, so nothing is left behind
     when there is no poster to paint. */
  const PAINTED = ["--cover-gradient", "--cover-accent-rgb", "--muted", "--dim"];

  /* The two of those that mean something to every theme rather than only to
     the one that measured them: the quietest text colours are read wherever
     they are set.  They are lifted against the adaptive theme's tinted
     surface, so they may only sit on the card while that theme is painting --
     on any other one they would be a colour picked for a surface that is not
     there.  The rest is read by css/theme.css alone, which is why a poster
     that is already known can be handed over on every theme. */
  const THEME_BOUND = ["--muted", "--dim"];

  /* ============================================================
     Colour space
     ------------------------------------------------------------
     sRGB for what the browser paints, OKLab for everything that
     has to keep a colour recognisable while its lightness moves.
     ============================================================ */

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

  /* ============================================================
     Reading the poster
     ============================================================ */

  function bucketize(pixels, width, height, box) {
    const buckets = new Map();
    const shift = 8 - BUCKET_BITS;
    const left = Math.floor(box[0] * width);
    const right = Math.max(left + 1, Math.ceil(box[2] * width));
    const top = Math.floor(box[1] * height);
    const bottom = Math.max(top + 1, Math.ceil(box[3] * height));

    for (let y = top; y < bottom; y++) {
      for (let x = left; x < right; x++) {
        const i = (y * width + x) * 4;
        if (pixels[i + 3] < 128) continue;
        const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
        const key = ((r >> shift) << (BUCKET_BITS * 2)) |
                    ((g >> shift) << BUCKET_BITS) |
                    (b >> shift);
        const bucket = buckets.get(key);
        if (bucket) {
          bucket.r += r; bucket.g += g; bucket.b += b; bucket.n++;
        } else {
          buckets.set(key, { r, g, b, n: 1 });
        }
      }
    }
    return buckets;
  }

  const average = (bucket) => [bucket.r / bucket.n, bucket.g / bucket.n, bucket.b / bucket.n];

  /* The colours of one region of the sample, most prominent first.

     Frequency alone picks the greys and near-blacks that fill the margins of
     most posters, so each bucket's weight is scaled by how saturated it is and
     by a mild luminance preference: a smaller patch of real colour beats a
     large flat backdrop, without excluding the dark tones that give a poster
     its mood. */
  function rankRegion(pixels, width, height, box) {
    const ranked = [];
    bucketize(pixels, width, height, box).forEach((bucket) => {
      const rgb = average(bucket).map(Math.round);
      const max = Math.max(rgb[0], rgb[1], rgb[2]);
      const min = Math.min(rgb[0], rgb[1], rgb[2]);
      const saturation = max === 0 ? 0 : (max - min) / max;
      const luma = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
      const guard = luma < 0.04 ? 0.35 : luma > 0.92 ? 0.45 : 1;
      ranked.push({ rgb, weight: bucket.n * (0.28 + saturation * 1.35) * guard });
    });
    ranked.sort((a, b) => b.weight - a.weight);
    return ranked;
  }

  /* One colour per region, kept as a representative pool for the artwork.

     A region whose strongest colour has already been taken by another one
     hands over its runner-up instead: neighbouring parts of a poster are often
     the same colour, and a varied pool makes the accent fallback more useful.
     A region with nothing else to offer keeps its colour anyway -- a poster
     that really is one colour should look like one. */
  function regionalPalette(pixels, width, height) {
    const picked = [];
    for (const region of REGIONS) {
      const ranked = rankRegion(pixels, width, height, region);
      if (!ranked.length) continue;
      const distinct = ranked.find((candidate) => picked.every((had) =>
        Math.abs(had[0] - candidate.rgb[0]) +
        Math.abs(had[1] - candidate.rgb[1]) +
        Math.abs(had[2] - candidate.rgb[2]) >= MIN_DISTANCE));
      picked.push((distinct || ranked[0]).rgb);
    }
    return picked;
  }

  /* The colour that makes the most useful accent.

     Area still matters most, so a small bright logo cannot take over a poster.
     Unlike the regional pool above, though, greys are skipped outright and very
     bright buckets are discounted: what is wanted is the poster's substantial,
     darker colour field rather than a sky or a white title treatment. */
  function accentSource(pixels, width, height) {
    const candidates = [];
    bucketize(pixels, width, height, [0, 0, 1, 1]).forEach((bucket) => {
      const rgb = average(bucket);
      const lch = rgbToOklch(rgb);
      if (lch[1] < MIN_ACCENT_CHROMA) return;
      candidates.push({ rgb, n: bucket.n, lightness: lch[0], chroma: lch[1], hue: lch[2] });
    });

    let best = null;
    for (const candidate of candidates) {
      /* Adjacent buckets often hold different shades of the same actual
         colour.  Count that hue family together before judging how important
         it is, so quantisation cannot split one large field into a collection
         of apparently insignificant colours. */
      const family = candidates.reduce((area, other) => {
        const distance = Math.abs(((candidate.hue - other.hue + 540) % 360) - 180);
        if (distance >= ACCENT_FAMILY_SPAN) return area;
        return area + other.n * (1 - distance / ACCENT_FAMILY_SPAN);
      }, 0);

      const shadowGuard = candidate.lightness < 0.18
        ? 0.35 + candidate.lightness / 0.18 * 0.65
        : 1;
      const highlightPenalty = candidate.lightness <= 0.48
        ? 1
        : Math.max(0.25, 1 - (candidate.lightness - 0.48) * 1.7);
      const chromaWeight = 0.72 +
        Math.min(candidate.chroma / ACCENT_MAX_CHROMA, 1) * 0.28;
      const score = (family + candidate.n * 0.35) *
                    shadowGuard * highlightPenalty * chromaWeight;
      if (!best || score > best.score) best = { rgb: candidate.rgb, score };
    }
    return best && best.rgb.map(Math.round);
  }

  function sampleSize(image) {
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) return { width: SAMPLE_MAX, height: SAMPLE_MAX };
    const scale = Math.min(1, SAMPLE_MAX / Math.max(width, height));
    return {
      width: Math.max(1, Math.round(width * scale)),
      height: Math.max(1, Math.round(height * scale))
    };
  }

  /* How much of the poster is held at once while it is read.  It is taken in
     strips rather than whole: a 4K image as a single canvas is thirty-odd
     megabytes, which is a lot to ask of a phone for something read once.  Each
     strip is copied at its own size, so this changes nothing about the answer
     -- only the peak. */
  const STRIP_PIXELS = 1 << 20;

  /* The sample, averaged down from the poster's own pixels rather than by the
     canvas.

     drawImage's downscale is not the same on every device -- browsers differ
     over it and some hand it to the GPU -- so the 48 px sample came out a
     little different on a phone than on a desktop.  A little is enough: where
     a poster's two strongest colours score close together (a red title over a
     cyan field, say) the accent can fall to either of them, and the same film
     then wears a different colour on each screen.

     Averaging here makes the reduction integer arithmetic over every source
     pixel, which comes out the same everywhere.  Each source pixel lands in
     exactly one cell, so it is a true area average.  Transparent pixels are
     left out the way bucketize leaves them out, and a cell that collected none
     stays clear so it is skipped there too. */
  function reduce(image, width, height, size) {
    const cells = size.width * size.height;
    const sums = new Uint32Array(cells * 4);        // r, g, b, and the count
    const strip = Math.max(1, Math.min(height, Math.floor(STRIP_PIXELS / width)));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = strip;
    const context = canvas.getContext("2d", { willReadFrequently: true });

    for (let top = 0; top < height; top += strip) {
      const rows = Math.min(strip, height - top);
      context.clearRect(0, 0, width, rows);
      /* Source rectangle to destination rectangle at the same size: a copy,
         never a scale, so nothing here is left to the browser's resampler. */
      context.drawImage(image, 0, top, width, rows, 0, 0, width, rows);
      const pixels = context.getImageData(0, 0, width, rows).data;

      for (let y = 0; y < rows; y++) {
        const row = (((top + y) * size.height / height) | 0) * size.width;
        for (let x = 0; x < width; x++) {
          const i = (y * width + x) * 4;
          if (pixels[i + 3] < 128) continue;
          const o = (row + ((x * size.width / width) | 0)) * 4;
          sums[o]     += pixels[i];
          sums[o + 1] += pixels[i + 1];
          sums[o + 2] += pixels[i + 2];
          sums[o + 3] += 1;
        }
      }
    }

    const out = new Uint8ClampedArray(cells * 4);
    for (let cell = 0; cell < cells; cell++) {
      const o = cell * 4;
      const n = sums[o + 3];
      if (!n) continue;
      out[o]     = Math.round(sums[o] / n);
      out[o + 1] = Math.round(sums[o + 1] / n);
      out[o + 2] = Math.round(sums[o + 2] / n);
      out[o + 3] = 255;
    }
    return out;
  }

  function paletteFromImage(image) {
    try {
      const width = image.naturalWidth || image.width;
      const height = image.naturalHeight || image.height;
      if (!width || !height) return null;

      const size = sampleSize(image);
      const pixels = reduce(image, width, height, size);

      const palette = regionalPalette(pixels, size.width, size.height);
      if (palette.length < 2) return null;
      palette.accent = accentSource(pixels, size.width, size.height);
      return palette;
    } catch (_) {
      /* No canvas, or a poster served from somewhere that taints it.  The
         add-on serves its own, so this is the browser saying no. */
      return null;
    }
  }

  /* ============================================================
     Taking a colour to where it may be painted
     ============================================================ */

  /* One poster colour at the lightness a surface is allowed, hue intact.

     The lightness is *set* rather than scaled: scaling all three channels by
     one factor keeps their ratios but not the colour, which is how five
     different posters end up as the same slate.  In OKLab the lightness moves
     on its own, and the chroma is taken back up afterwards to what the
     darkening cost, as far as the gamut at that lightness allows.

     A poster with no colour at all -- a black and white one -- is left grey.
     Forcing chroma on it would invent a tint the artwork never had. */
  function tintColor(rgb, lightness, chromaGain) {
    const lch = rgbToOklch(rgb);
    if (lch[1] < GREY_CHROMA) return oklchToRgb(lightness, 0, lch[2]);
    return oklchToRgb(lightness,
                      Math.max(lch[1], MIN_CHROMA) * CHROMA_GAIN * chromaGain,
                      lch[2]);
  }

  /* How much scrim this poster needs, rather than how much every poster gets.

     The tinted surface is at its lightest where its lightest stop is painted
     solid, so that is what the text has to stay readable against.  The answer
     is the smallest amount of scrim that gets there: a dark poster keeps
     almost all of its colour, a bright one is held down as far as it has to
     be, and both end up at the same contrast instead of at the same opacity. */
  function solveScrim(brightest, text) {
    const readableAt = (alpha) =>
      contrast(text, composite(SCRIM_RGB, brightest, alpha)) >= TEXT_RATIO;

    if (readableAt(SCRIM_MIN)) return SCRIM_MIN;
    let low = SCRIM_MIN, high = SCRIM_MAX;
    for (let i = 0; i < 18; i++) {
      const mid = (low + high) / 2;
      if (readableAt(mid)) high = mid; else low = mid;
    }
    return Math.min(SCRIM_MAX, high);
  }

  /* One mark lifted off the surface it sits on, hue intact.  The colour keeps
     its hue, only its lightness climbs, and it climbs exactly as far as the
     surface in front of it makes necessary.  A mark already clear of the
     surface is handed back untouched. */
  function liftAgainst(rgb, surface, ratio) {
    if (contrast(rgb, surface) >= ratio) return rgb;
    const lch = rgbToOklch(rgb);
    for (let L = lch[0]; L <= 0.99; L += 0.01) {
      const candidate = oklchToRgb(L, lch[1], lch[2]);
      if (contrast(candidate, surface) >= ratio) return candidate;
    }
    return [255, 255, 255];
  }

  /* The poster's colour as a mark rather than as a surface. */
  /* Which colour of the poster the accent family comes from -- the mark and,
     on every card but the now-playing one, the surface itself.  Both take it
     from here so a card and the marks on it are the same colour taken to two
     different places, rather than two colours that happen to be near. */
  function accentBase(palette) {
    let best = palette.accent || palette[0];
    let chroma = rgbToOklch(best)[1];

    /* A large black, white or grey area must not hide a clearly coloured part
       of the poster -- a dark backdrop with a yellow title is common. */
    if (chroma < MIN_ACCENT_CHROMA) {
      for (const rgb of palette) {
        const other = rgbToOklch(rgb)[1];
        if (other > chroma) { best = rgb; chroma = other; }
      }
    }
    return best;
  }

  function accentColor(palette, surface) {
    const best = accentBase(palette);
    const bestChroma = rgbToOklch(best)[1];
    const source = rgbToOklch(best);
    const lightness = Math.max(ACCENT_MIN_LIGHTNESS,
      Math.min(ACCENT_MAX_LIGHTNESS, source[0] + 0.08));

    const accent = bestChroma < GREY_CHROMA
      ? oklchToRgb(lightness, 0, 0)
      : oklchToRgb(lightness,
          Math.max(ACCENT_MIN_CHROMA, Math.min(ACCENT_MAX_CHROMA, source[1] * 1.08)),
          source[2]);

    return liftAgainst(accent, surface, ACCENT_RATIO);
  }

  /* ============================================================
     The gradients
     ============================================================ */

  const rgbText = (c) => "rgb(" + c[0] + ", " + c[1] + ", " + c[2] + ")";
  const rgbaText = (c, a) => "rgba(" + c[0] + ", " + c[1] + ", " + c[2] + ", " + a + ")";
  const deepen = (rgb, amount) => rgb.map((c) => Math.round(c * amount));

  /* The now-playing card gets one continuous colour field rather than a stack
     of horizontal poster-colour bands.  The wide glow starts along the top,
     reaches across the artwork and title, then disappears gradually towards
     the controls below.  Two much quieter layers keep the result from looking
     like a flat top-to-bottom fill while staying in the same colour family. */
  function heroGradient(color, scrim) {
    const held = composite(SCRIM_RGB, color, scrim);
    const deep = deepen(held, 0.72);

    return [
      "radial-gradient(ellipse 155% 105% at 38% 0%, " +
        rgbaText(held, 0.86) + " 0%, " +
        rgbaText(held, 0.56) + " 36%, " +
        rgbaText(deep, 0.20) + " 68%, " +
        rgbaText(deep, 0) + " 94%)",
      "radial-gradient(ellipse 120% 72% at 100% 34%, " +
        rgbaText(held, 0.18) + " 0%, " +
        rgbaText(deep, 0.07) + " 58%, " +
        rgbaText(deep, 0) + " 86%)",
      "linear-gradient(180deg, " +
        rgbaText(deep, 0.18) + " 0%, " +
        rgbaText(deep, 0.07) + " 68%, " +
        rgbaText(deep, 0) + " 100%)"
    ].join(", ");
  }

  /* ============================================================
     What the theme in force allows
     ============================================================ */

  function adaptive() {
    return document.documentElement.getAttribute("data-theme") === ADAPTIVE;
  }

  function strengthLevel() {
    const raw = parseInt(
      document.documentElement.getAttribute("data-cover-strength"), 10);
    return STRENGTH_LEVELS[
      Number.isInteger(raw) && raw >= 0 && raw < STRENGTH_LEVELS.length
        ? raw : DEFAULT_STRENGTH];
  }

  /* The theme's own colours are read off the page rather than repeated here,
     so a token that changes in base.css changes here with it.  They are looked
     up once per theme; the cache is dropped whenever the theme is. */
  let tokens = { theme: null, values: new Map() };

  function parseColor(value) {
    const text = (value || "").trim();
    const hex = /^#([\da-f]{3}|[\da-f]{6})$/i.exec(text);
    if (hex) {
      const digits = hex[1].length === 3
        ? hex[1].replace(/./g, (c) => c + c) : hex[1];
      return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16));
    }
    const parts = /^rgba?\(([^)]+)\)$/i.exec(text);
    if (parts) {
      const channels = parts[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat);
      if (channels.length >= 3) return channels.slice(0, 3).map(Math.round);
    }
    return null;
  }

  function themeColor(token, fallback) {
    const theme = document.documentElement.getAttribute("data-theme") || "";
    if (tokens.theme !== theme) tokens = { theme, values: new Map() };
    if (tokens.values.has(token)) return tokens.values.get(token);
    const value = parseColor(
      getComputedStyle(document.documentElement).getPropertyValue(token)) || fallback;
    tokens.values.set(token, value);
    return value;
  }

  /* ============================================================
     Painting a card
     ============================================================ */

  /* Everything one poster contributes to one of the two areas, as property
     values.  Worked out once per poster, area and strength and kept: the
     answer does not change while those stay what they are, and the theme's own
     share is dropped along with the token cache when the theme changes. */
  const derived = new Map();

  function paintValues(palette, key, variant) {
    const raw = document.documentElement.getAttribute("data-cover-strength");
    const cacheKey = key && (key + "|" + variant + "|" + raw);
    if (cacheKey && derived.has(cacheKey)) return derived.get(cacheKey);

    const base = themeColor("--panel", [20, 24, 29]);
    const values = variant === "panel"
      ? { "--cover-accent-rgb": accentColor(palette, base).join(", ") }
      : heroValues(palette, base);

    if (cacheKey) derived.set(cacheKey, values);
    return values;
  }

  /* The now-playing card: one representative cover colour, normalised to the
     selected strength.  The unblended colour is the brightest the glow could
     reach, so solving contrast against it is deliberately conservative. */
  function heroValues(palette, base) {
    const level = strengthLevel();
    const text = themeColor("--text", [232, 236, 241]);

    const source = accentBase(palette);
    const tinted = tintColor(source, 0.34 + level.lightness, level.chroma);
    const color = level.mix < 1 ? composite(tinted, base, level.mix) : tinted;

    const peak = color;
    const scrim = solveScrim(peak, text);
    /* What the text will actually sit on -- which is what everything below is
       measured against. */
    const surface = composite(SCRIM_RGB, peak, scrim);

    return {
      "--cover-gradient": heroGradient(color, scrim),
      "--cover-accent-rgb": accentColor(palette, surface).join(", "),
      /* The two quietest text colours in the card.  The theme picks them
         against one known surface; here they sit on whatever the poster
         happened to be, so they are lifted to the level every other mark is
         held to rather than being given a second fixed value.  Only this card
         needs it: every other one is the plain panel the theme already chose
         them against. */
      "--muted": rgbText(liftAgainst(themeColor("--muted", [139, 151, 166]),
                                     surface, MARK_RATIO)),
      "--dim": rgbText(liftAgainst(themeColor("--dim", [93, 104, 117]),
                                   surface, MARK_RATIO))
    };
  }

  function clear(element) {
    for (const property of PAINTED) element.style.removeProperty(property);
  }

  function paint(element, palette, key, variant) {
    if (!element) return;
    if (!palette) { clear(element); return; }
    const values = paintValues(palette, key, variant);
    const painting = adaptive();
    for (const property of PAINTED) {
      if (property in values && (painting || !THEME_BOUND.includes(property))) {
        element.style.setProperty(property, values[property]);
      } else {
        element.style.removeProperty(property);
      }
    }
  }

  /* Resolves once the poster can be read: true when it has pixels, false when
     it never will. */
  function ready(image) {
    if (image.complete) return Promise.resolve(image.naturalWidth > 0);
    return new Promise((resolve) => {
      image.addEventListener("load", () => resolve(image.naturalWidth > 0), { once: true });
      image.addEventListener("error", () => resolve(false), { once: true });
    });
  }

  /* Reading a poster costs an image decode and a canvas read, so each one is
     read once and what it yielded is kept.  A stored null records "nothing to
     paint for this one", which stops an unreadable poster being retried every
     time the theme changes. */
  const palettes = new Map();

  function readCover(url, image) {
    if (palettes.has(url)) return Promise.resolve(palettes.get(url));
    return ready(image).then((ok) => {
      const palette = ok ? paletteFromImage(image) : null;
      palettes.set(url, palette);
      return palette;
    });
  }

  /* The poster being painted from, and the card the hero variant goes on.  The
     theme can change long after the film did, so both are kept rather than
     only passed through.

     The quiet variant is not given an element: it goes on <main>, and every
     card inside inherits it (see css/theme.css).  One property per page
     therefore paints all of them, and the now-playing card overrides the three
     it cares about on itself. */
  let current = { hero: null, url: "", image: null };

  const panelHost = () => document.querySelector("main");

  /* The chrome that sits outside <main> and so inherits nothing painted there:
     the bar across the top, and the theme menu, which hangs from <body> so the
     bar cannot clip it.  Both take the quiet variant, which carries the accent
     alone -- the lifted text colours belong to the tinted card and are not
     wanted out here, where the theme's own surface is what they would sit on
     (see paintValues).

     Read again on each paint rather than kept: the menu is built by
     js/theme.js after this file has loaded.  Both survive being rebuilt --
     buildMenu replaces the menu's children, never the menu itself. */
  const chromeHosts = () => [
    document.querySelector(".topbar"),
    document.getElementById("themeMenu")
  ];

  function paintBoth(palette, key) {
    paint(current.hero, palette, key, "hero");
    paint(panelHost(), palette, key, "panel");
    for (const host of chromeHosts()) paint(host, palette, key, "panel");
    /* Anything drawn rather than styled has to be told: the luminance chart
       takes its colours from the card it sits in, and a canvas does not
       repaint itself when a custom property under it changes. */
    document.dispatchEvent(new CustomEvent("tinyppi-tint"));
  }

  function repaint() {
    const host = panelHost();
    if (!current.hero && !host) return;
    if (!current.url) { paintBoth(null); return; }

    /* Already known: paint it now rather than a frame later, so switching back
       to this theme does not flash the plain cards first. */
    const known = palettes.get(current.url);
    if (known !== undefined) { paintBoth(known, current.url); return; }

    paintBoth(null);
    /* Reading a poster nothing has read yet is left to the theme that actually
       paints it: no other one would show anything for the work. */
    if (!adaptive()) return;

    const url = current.url;
    readCover(url, current.image).then((palette) => {
      if (current.url !== url) return;
      paintBoth(palette, url);
    });
  }

  /* How far a poster may be taken is the theme's call and the strength's, so
     the cards are painted again whenever either changes -- and switching *to*
     the adaptive theme is the moment a poster nothing has read yet is read. */
  if (typeof MutationObserver === "function") {
    new MutationObserver(() => {
      tokens = { theme: null, values: new Map() };
      derived.clear();
      repaint();
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "data-cover-strength"]
    });
  }

  return {
    /* What is playing now, from live-panels.js: the now-playing card, the
       address the poster came from and the <img> already showing it -- reading
       the picture the page has anyway is the difference between one decode and
       two.  An empty address is a film with no poster, or none playing. */
    show(element, url, image) {
      current = { hero: element || null, url: url || "", image: image || null };
      repaint();
    }
  };

})();
