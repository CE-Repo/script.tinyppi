// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// The adaptive theme's poster tint (resources/web/js/cover-tint.js): which
// colour a poster gives, how it is painted on the now-playing card, on <main>
// and on the bars outside it, what the text on it is held to, how the theme
// and its strength change that, and when a poster is read at all.
//
// jsdom has no 2D canvas and decodes no images, so both are faked here: a
// poster is an <img> carrying its own pixels, and the canvas copies them the
// way drawImage would.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";
import { bare, page as harnessPage, settle, source } from "./harness.mjs";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "resources", "web", "js");
const PAINTED = ["--cover-gradient", "--cover-accent-rgb", "--muted", "--dim"];
const SCRIM = [11, 13, 16];
const TEXT = [232, 236, 241];
const PANEL = [20, 24, 29];

const opened = [];
after(() => { for (const window of opened) window.close(); });

function page(options) {
  const view = harnessPage(options);
  opened.push(view.window);
  return view;
}

function load(dom, name) {
  new vm.Script(source(name), { filename: pathToFileURL(join(JS, name)).href })
    .runInContext(dom.getInternalVMContext());
}

/* A 2D canvas that copies a poster's pixels where drawImage is told to, and
   posters that carry them.  Every context asked for and every copy made is
   logged. */
function fakeCanvas(window) {
  const pixels = new WeakMap();
  const state = new WeakMap();
  const log = { contexts: 0, draws: [], refuse: false };
  window.HTMLCanvasElement.prototype.getContext = function (type, options) {
    log.contexts += 1;
    log.options = [type, { ...options }];
    const canvas = this;
    const buffer = new Uint8ClampedArray(canvas.width * canvas.height * 4);
    return {
      clearRect(x, y, w, h) { buffer.fill(0, y * canvas.width * 4, (y + h) * canvas.width * 4); },
      drawImage(image, sx, sy, sw, sh, dx, dy, dw, dh) {
        log.draws.push([sx, sy, sw, sh, dx, dy, dw, dh]);
        const { width, data } = pixels.get(image);
        for (let row = 0; row < sh; row++) {
          const from = ((sy + row) * width + sx) * 4;
          buffer.set(data.subarray(from, from + sw * 4), ((dy + row) * canvas.width + dx) * 4);
        }
      },
      getImageData(x, y, w, h) {
        if (log.refuse) throw new window.DOMException("tainted", "SecurityError");
        return { data: buffer.slice(y * canvas.width * 4, (y + h) * canvas.width * 4) };
      }
    };
  };

  /* A poster *width* by *height* whose pixel at x, y is at(x, y) -- [r, g, b]
     or [r, g, b, a].  *loading* leaves it to arrive later; *naturalHeight*
     and *boxHeight* stand in for an image that knows no height of its own. */
  function poster(width, height, at, { loading = false, naturalHeight = height, boxHeight = 0 } = {}) {
    const image = window.document.createElement("img");
    const data = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const colour = at(x, y);
        data.set([colour[0], colour[1], colour[2], colour[3] ?? 255], (y * width + x) * 4);
      }
    }
    pixels.set(image, { width, height, data });
    const status = { complete: !loading, naturalWidth: loading ? 0 : width, naturalHeight };
    state.set(image, status);
    Object.defineProperties(image, {
      complete: { get: () => status.complete },
      naturalWidth: { get: () => status.naturalWidth },
      naturalHeight: { get: () => status.naturalHeight },
      width: { get: () => width },
      height: { get: () => boxHeight }
    });
    return image;
  }

  /* The page moving an <img> on to another poster, *at* its pixels, which
     then has to load like any other. */
  function replace(image, src, at) {
    const { width, height } = pixels.get(image);
    const data = new Uint8ClampedArray(width * height * 4);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) data.set([...at(x, y), 255], (y * width + x) * 4);
    }
    pixels.set(image, { width, height, data });
    Object.assign(state.get(image), { complete: false, naturalWidth: 0 });
    image.src = src;
  }

  /* The browser finishing a poster that was still loading. */
  function arrive(image, { decoded = true, failed = false } = {}) {
    const status = state.get(image);
    status.complete = true;
    if (decoded && !failed) status.naturalWidth = pixels.get(image).width;
    image.dispatchEvent(new window.Event(failed ? "error" : "load"));
  }

  return { log, poster, replace, arrive };
}

/* A page wearing the adaptive theme, as a first visit does, with a
   now-playing card to paint. */
function tinted({ scripts = ["theme.js", "colour.js", "cover-tint.js"] } = {}) {
  const view = page({ scripts });
  const { window } = view;
  const { document } = window;
  const canvas = fakeCanvas(window);
  const card = document.createElement("article");
  card.className = "nowcard";
  document.getElementById("live").append(card);
  const tints = [];
  document.addEventListener("tinyppi-tint", () => tints.push(document.documentElement.dataset.theme));
  return {
    ...view, canvas, card, tints,
    main: document.querySelector("main"),
    chrome: [document.querySelector(".topbar"), document.querySelector(".tabbar")],
    C: window.TinyPPIColour,
    /* The <img> carries the address it is shown with, as the page's does. */
    async show(url, image, element = card) {
      if (image) image.src = url;
      window.TinyPPICover.show(element, url, image);
      await settle();
    },
    async set(name, value) {
      if (value === null) document.documentElement.removeAttribute(name);
      else document.documentElement.setAttribute(name, value);
      await settle();                                    // the observer's turn
    },
    token(name, value) { document.documentElement.style.setProperty(name, value); }
  };
}

/* What a card carries, property by property. */
function painted(element) {
  const out = {};
  for (const property of PAINTED) {
    const value = element.style.getPropertyValue(property);
    if (value) out[property] = value;
  }
  return out;
}

const triple = (text) => text.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
const accentOf = (element) => triple(element.style.getPropertyValue("--cover-accent-rgb"));
/* What the card's text sits on: the glow's first, most solid stop. */
const surfaceOf = (card) => triple(card.style.getPropertyValue("--cover-gradient").split("rgba(")[1]);
const hueGap = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

/* Posters, 96 x 144 like a 2:3 one sampled at 32 x 48. */
const BLUE = (x, y) => [30 + (x % 4) * 6, 60 + (y % 3) * 8, 160];
const RED = () => [200, 20, 20];
const YELLOW = () => [250, 230, 40];
const BLACK_AND_WHITE = (x, y) => (y < 48 ? [0, 0, 0] : y < 96 ? [255, 255, 255] : [128, 128, 128]);

test("an adaptive page glows in the poster's colour and wears its accent everywhere", async () => {
  const view = tinted();
  const { C, card, main, chrome, canvas } = view;
  await view.show("/api/art?kind=poster&id=7", canvas.poster(96, 144, BLUE));

  assert.deepEqual(Object.keys(painted(card)), PAINTED);
  assert.match(card.style.getPropertyValue("--cover-gradient"),
               /^radial-gradient\(ellipse 155% 105% at 38% 0%, rgba\(.+linear-gradient\(180deg, /);
  for (const host of [main, ...chrome]) {
    // The quiet variant: the accent alone, no glow and no text colours.
    assert.deepEqual(Object.keys(painted(host)), ["--cover-accent-rgb"]);
    assert.ok(C.contrast(accentOf(host), PANEL) >= 4.5, "the accent stands off the plain panel");
    assert.ok(hueGap(C.rgbToOklch(accentOf(host))[2], C.rgbToOklch([39, 68, 160])[2]) < 15);
  }

  const surface = surfaceOf(card);
  const poster = C.rgbToOklch([39, 68, 160]);
  assert.ok(hueGap(C.rgbToOklch(surface)[2], poster[2]) < 15, "the glow keeps the poster's hue");
  assert.ok(C.contrast(TEXT, surface) >= 11, "the text reads at a glance");
  assert.ok(C.contrast(accentOf(card), surface) >= 4.5, "the card's marks stand off it");
  for (const property of ["--muted", "--dim"]) {
    assert.ok(C.contrast(triple(card.style.getPropertyValue(property)), surface) >= 6, property);
  }
  // Painted plain while the poster was read, then in its colour.
  assert.deepEqual(view.tints, ["dark-adaptive", "dark-adaptive"]);
});

test("a poster is copied at its own size, never scaled by the canvas", async () => {
  const view = tinted();
  await view.show("/a", view.canvas.poster(96, 144, BLUE));
  assert.deepEqual(view.canvas.log.draws, [[0, 0, 96, 144, 0, 0, 96, 144]]);
  assert.deepEqual(view.canvas.log.options, ["2d", { willReadFrequently: true }]);
});

test("a large poster is read in strips and comes out as it would whole", async () => {
  const big = tinted();
  const halves = (height) => (x, y) => (y < height / 2 ? [210, 40, 30] : [20, 90, 200]);
  await big.show("/big", big.canvas.poster(4096, 300, halves(300)));
  // A megapixel at a time: 256 rows of 4096, then what is left.
  assert.deepEqual(big.canvas.log.draws, [[0, 0, 4096, 256, 0, 0, 4096, 256],
                                          [0, 256, 4096, 44, 0, 0, 4096, 44]]);
  // The same design already at the sample's size (48 x 4) is painted alike.
  const small = tinted();
  await small.show("/small", small.canvas.poster(48, 4, halves(4)));
  assert.deepEqual(painted(big.card), painted(small.card));
  assert.deepEqual(painted(big.main), painted(small.main));
});

test("a poster already read is not read again", async () => {
  const view = tinted();
  const { canvas } = view;
  await view.show("/one", canvas.poster(96, 144, BLUE));
  const first = painted(view.card);
  await view.show("/one", canvas.poster(96, 144, RED));  // the same address
  assert.equal(canvas.log.contexts, 1);
  assert.deepEqual(painted(view.card), first);
  assert.equal(view.tints.length, 3);                    // painted at once this time
  await view.show("/two", canvas.poster(96, 144, RED));
  assert.equal(canvas.log.contexts, 2);
  assert.notDeepEqual(painted(view.card), first);
});

test("a poster that really is one colour is painted in that colour", async () => {
  const view = tinted();
  const { C } = view;
  await view.show("/red", view.canvas.poster(96, 144, RED));
  const red = C.rgbToOklch([200, 20, 20])[2];
  assert.ok(hueGap(C.rgbToOklch(surfaceOf(view.card))[2], red) < 10);
  assert.ok(hueGap(C.rgbToOklch(accentOf(view.main))[2], red) < 10);
});

test("transparent pixels count for nothing, whatever colour they carry", async () => {
  const view = tinted();
  const { C } = view;
  // A green frame nobody can see around a red picture.
  const framed = (x, y) => (x < 24 || x >= 72 ? [0, 255, 0, 0] : y < 100 ? [200, 20, 20] : [0, 255, 0, 40]);
  await view.show("/framed", view.canvas.poster(96, 144, framed));
  const red = C.rgbToOklch([200, 20, 20])[2];
  assert.ok(hueGap(C.rgbToOklch(surfaceOf(view.card))[2], red) < 10);
  assert.ok(hueGap(C.rgbToOklch(accentOf(view.card))[2], red) < 15);
});

test("a poster with colour in only one corner has nothing to paint", async () => {
  const view = tinted();
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  const corner = (x, y) => (x >= 80 && y >= 120 ? [200, 20, 20] : [0, 0, 0, 0]);
  await view.show("/corner", view.canvas.poster(96, 144, corner));
  for (const host of [view.card, view.main, ...view.chrome]) assert.deepEqual(painted(host), {});
  // Remembered as nothing: a change of strength does not read it again.
  await view.set("data-cover-strength", "2");
  assert.equal(view.canvas.log.contexts, 2);
  assert.deepEqual(painted(view.card), {});
});

test("a black and white poster stays grey", async () => {
  const view = tinted();
  const { C } = view;
  await view.show("/bw", view.canvas.poster(96, 144, BLACK_AND_WHITE));
  for (const host of [view.card, view.main]) {
    const [r, g, b] = accentOf(host);
    assert.ok(r === g && g === b, `a grey accent, not ${r}, ${g}, ${b}`);
  }
  // Grey under the page's own near-black scrim, which is all the hue it has.
  const surface = surfaceOf(view.card);
  assert.ok(C.rgbToOklch(surface)[1] < 0.01, `no tint invented: ${surface}`);
  assert.ok(C.contrast(TEXT, surface) >= 11);
});

test("a nearly grey poster takes the faint colour it does have", async () => {
  const view = tinted();
  const { C } = view;
  // Grey on the left, a grey with a breath of red in it on the right.
  const faint = (x, y) => (y >= 72 ? [90, 90, 90] : x < 48 ? [100, 100, 100] : [118, 100, 100]);
  await view.show("/faint", view.canvas.poster(96, 144, faint));
  const red = C.rgbToOklch([200, 20, 20])[2];
  for (const host of [view.card, view.main]) {
    const accent = accentOf(host);
    assert.ok(accent[0] > accent[1] + 30 && accent[0] > accent[2] + 30, `a reddish accent: ${accent}`);
    assert.ok(hueGap(C.rgbToOklch(accent)[2], red) < 20);
  }
  const surface = surfaceOf(view.card);
  assert.ok(surface[0] > surface[2] + 20, `a reddish glow: ${surface}`);
});

test("a dark backdrop with a coloured title takes the title's colour", async () => {
  const view = tinted();
  const { C } = view;
  const titled = (x, y) => (y > 60 && y < 80 && x > 10 && x < 86 ? [240, 220, 20] : [5, 5, 8]);
  await view.show("/titled", view.canvas.poster(96, 144, titled));
  const yellow = C.rgbToOklch([240, 220, 20])[2];
  assert.ok(hueGap(C.rgbToOklch(accentOf(view.main))[2], yellow) < 10);
  assert.ok(hueGap(C.rgbToOklch(surfaceOf(view.card))[2], yellow) < 15);
});

test("the larger colour field wins over a bright title and a dark corner", async () => {
  const view = tinted();
  const { C } = view;
  // A teal field, a pale pink title across it and a deep red corner.
  const poster = (x, y) => (y < 20 ? [255, 200, 210] : x > 70 && y > 120 ? [40, 0, 0] : [20, 120, 130]);
  await view.show("/field", view.canvas.poster(96, 144, poster));
  const teal = C.rgbToOklch([20, 120, 130])[2];
  assert.ok(hueGap(C.rgbToOklch(accentOf(view.main))[2], teal) < 15);
  assert.ok(hueGap(C.rgbToOklch(surfaceOf(view.card))[2], teal) < 15);
});

test("the strength sets how strongly the card glows, and nonsense reads as standard", async () => {
  const view = tinted();
  const { C } = view;
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  const at = {};
  for (const level of ["0", "2", "9", "1"]) {
    await view.set("data-cover-strength", level);
    at[level] = painted(view.card);
    assert.ok(C.contrast(TEXT, surfaceOf(view.card)) >= 11, `readable at ${level}`);
  }
  assert.equal(view.canvas.log.contexts, 1);             // repainted, not read again
  assert.deepEqual(at["9"], at["1"]);
  assert.notDeepEqual(at["0"], at["1"]);
  assert.notDeepEqual(at["2"], at["1"]);
  const chroma = (values) => C.rgbToOklch(triple(values["--cover-gradient"].split("rgba(")[1]))[1];
  assert.ok(chroma(at["0"]) < chroma(at["1"]), "subtle keeps more of the plain panel");
  // The quiet variant does not change with the strength.
  const quiet = view.main.style.getPropertyValue("--cover-accent-rgb");
  await view.set("data-cover-strength", "0");
  assert.equal(view.main.style.getPropertyValue("--cover-accent-rgb"), quiet);
});

test("another theme leaves a poster nobody has read unread and the cards plain", async () => {
  const view = tinted();
  await view.set("data-theme", "midnight");
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  assert.equal(view.canvas.log.contexts, 0);
  for (const host of [view.card, view.main, ...view.chrome]) assert.deepEqual(painted(host), {});
  // Switching to the adaptive theme is the moment it is read.
  await view.set("data-theme", "dark-adaptive");
  assert.equal(view.canvas.log.contexts, 1);
  assert.deepEqual(Object.keys(painted(view.card)), PAINTED);
});

test("a poster already known keeps its colour on other themes, but not the lifted text colours", async () => {
  const view = tinted();
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  const adaptive = painted(view.card);
  await view.set("data-theme", "midnight");
  assert.deepEqual(painted(view.card), { "--cover-gradient": adaptive["--cover-gradient"],
                                         "--cover-accent-rgb": adaptive["--cover-accent-rgb"] });
  assert.deepEqual(Object.keys(painted(view.main)), ["--cover-accent-rgb"]);
  // No theme on the page at all is no adaptive theme either.
  await view.set("data-theme", null);
  assert.deepEqual(Object.keys(painted(view.card)), ["--cover-gradient", "--cover-accent-rgb"]);
  await view.set("data-theme", "dark-adaptive");
  assert.deepEqual(painted(view.card), adaptive);
  assert.equal(view.canvas.log.contexts, 1);
});

test("the theme keys on the settings tab repaint the cards", async () => {
  const view = tinted();
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  const { document } = view.window;
  document.querySelector('.theme-option[data-theme="dark"]').click();
  await settle();
  assert.equal(view.card.style.getPropertyValue("--muted"), "");
  assert.deepEqual(view.tints.slice(-1), ["dark"]);
  document.querySelector('.theme-option[data-theme="dark-adaptive"]').click();
  document.querySelector('.theme-group-option[data-level="0"]').click();
  await settle();
  assert.notEqual(view.card.style.getPropertyValue("--muted"), "");
});

test("no poster, or nothing playing, takes every painted colour off again", async () => {
  const view = tinted();
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  await view.show("", null);
  for (const host of [view.card, view.main, ...view.chrome]) assert.deepEqual(painted(host), {});

  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  view.window.TinyPPICover.show();                       // nothing at all
  await settle();
  for (const host of [view.main, ...view.chrome]) assert.deepEqual(painted(host), {});
  // The card that was let go is not touched again.
  assert.deepEqual(Object.keys(painted(view.card)), PAINTED);
});

test("a poster shown without its card still paints the rest of the page", async () => {
  const view = tinted();
  await view.show("/blue", view.canvas.poster(96, 144, BLUE), null);
  assert.deepEqual(painted(view.card), {});
  assert.deepEqual(Object.keys(painted(view.main)), ["--cover-accent-rgb"]);
});

test("a poster still loading is read once it arrives", async () => {
  const view = tinted();
  const image = view.canvas.poster(96, 144, BLUE, { loading: true });
  await view.show("/late", image);
  assert.deepEqual(painted(view.card), {});
  assert.equal(view.canvas.log.contexts, 0);
  view.canvas.arrive(image);
  await settle();
  assert.deepEqual(Object.keys(painted(view.card)), PAINTED);
});

test("a poster still loading is read once, however often the page repaints meanwhile", async () => {
  const view = tinted();
  const image = view.canvas.poster(96, 144, BLUE, { loading: true });
  await view.show("/late", image);
  await view.set("data-cover-strength", "0");
  await view.set("data-cover-strength", "2");
  await view.show("/late", image);
  view.canvas.arrive(image);
  await settle();
  assert.equal(view.canvas.log.contexts, 1);
  assert.deepEqual(Object.keys(painted(view.card)), PAINTED);
});

test("an <img> moved on to the next poster while loading keeps each poster's colour its own", async () => {
  const view = tinted();
  const { canvas } = view;
  const image = canvas.poster(96, 144, BLUE, { loading: true });
  await view.show("/blue", image);
  canvas.replace(image, "/red", RED);
  await view.show("/red", image);
  canvas.arrive(image);
  await settle();
  const red = accentOf(view.card);
  assert.ok(red[0] > red[2], `${red}`);
  assert.equal(canvas.log.contexts, 1);

  // Blue was never read, so it is read when it comes back, not painted red.
  await view.show("/blue", canvas.poster(96, 144, BLUE));
  assert.equal(canvas.log.contexts, 2);
  const blue = accentOf(view.card);
  assert.ok(blue[2] > blue[0], `${blue}`);
});

test("a poster that fails, or loads without pixels, paints nothing and is not tried again", async () => {
  for (const outcome of [{ failed: true }, { decoded: false }]) {
    const view = tinted();
    const image = view.canvas.poster(96, 144, BLUE, { loading: true });
    await view.show("/broken", image);
    view.canvas.arrive(image, outcome);
    await settle();
    assert.deepEqual(painted(view.card), {}, JSON.stringify(outcome));
    await view.set("data-cover-strength", "0");
    await view.show("/broken", image);
    assert.equal(view.canvas.log.contexts, 0);
    assert.deepEqual(painted(view.card), {});
  }
});

test("a poster replaced while it loaded is kept for later but not painted over its successor", async () => {
  const view = tinted();
  const late = view.canvas.poster(96, 144, BLUE, { loading: true });
  await view.show("/late", late);
  await view.show("/red", view.canvas.poster(96, 144, RED));
  const red = painted(view.card);
  view.canvas.arrive(late);
  await settle();
  assert.deepEqual(painted(view.card), red);
  const reads = view.canvas.log.contexts;
  await view.show("/late", late);                        // known by now
  assert.equal(view.canvas.log.contexts, reads);
  assert.notDeepEqual(painted(view.card), red);
});

test("an image without a height of its own is measured by its box, or not at all", async () => {
  const boxed = tinted();
  await boxed.show("/svg", boxed.canvas.poster(96, 144, BLUE, { naturalHeight: 0, boxHeight: 144 }));
  assert.deepEqual(Object.keys(painted(boxed.card)), PAINTED);
  assert.deepEqual(boxed.canvas.log.draws, [[0, 0, 96, 144, 0, 0, 96, 144]]);

  const unsized = tinted();
  await unsized.show("/svg", unsized.canvas.poster(96, 144, BLUE, { naturalHeight: 0 }));
  assert.deepEqual(painted(unsized.card), {});
  assert.equal(unsized.canvas.log.contexts, 0);
});

test("a canvas the browser will not let be read paints nothing", async () => {
  const view = tinted();
  view.canvas.log.refuse = true;
  await view.show("/tainted", view.canvas.poster(96, 144, BLUE));
  assert.deepEqual(painted(view.card), {});
  assert.deepEqual(painted(view.main), {});
});

test("the theme's text colours are read off the page, in any of its spellings", async () => {
  const cases = [
    [{ "--muted": "#abc", "--dim": "rgba(200, 210, 220, 0.5)" }, ["rgb(170, 187, 204)", "rgb(200, 210, 220)"]],
    [{ "--muted": "#AABBCC", "--dim": "rgb(200 210 220 / 50%)" }, ["rgb(170, 187, 204)", "rgb(200, 210, 220)"]]
  ];
  for (const [tokens, expected] of cases) {
    const view = tinted();
    for (const [name, value] of Object.entries(tokens)) view.token(name, value);
    await view.show("/blue", view.canvas.poster(96, 144, BLUE));
    // Already clear of the surface, so taken as they are.
    assert.deepEqual([view.card.style.getPropertyValue("--muted"),
                      view.card.style.getPropertyValue("--dim")], expected, JSON.stringify(tokens));
  }
  // What cannot be read as a colour is the built-in one.
  const plain = tinted();
  await plain.show("/blue", plain.canvas.poster(96, 144, BLUE));
  const odd = tinted();
  odd.token("--muted", "tomato");
  odd.token("--dim", "rgb(1, 2)");
  await odd.show("/blue", odd.canvas.poster(96, 144, BLUE));
  assert.deepEqual(painted(odd.card), painted(plain.card));
});

test("the theme's colours are looked up once per theme", async () => {
  const view = tinted();
  view.token("--muted", "#abc");
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  view.token("--muted", "#bcd");
  await view.show("/red", view.canvas.poster(96, 144, RED));
  assert.equal(view.card.style.getPropertyValue("--muted"), "rgb(170, 187, 204)");
  await view.set("data-theme", "midnight");
  await view.set("data-theme", "dark-adaptive");
  assert.equal(view.card.style.getPropertyValue("--muted"), "rgb(187, 204, 221)");
});

test("dark text the glow cannot be dark enough for gets as much scrim as there is", async () => {
  const view = tinted();
  view.token("--text", "#000");
  await view.show("/blue", view.canvas.poster(96, 144, BLUE));
  const surface = surfaceOf(view.card);
  surface.forEach((channel, i) => assert.ok(Math.abs(channel - SCRIM[i]) <= 12, `${surface} is all scrim`));
});

test("a glow is held down only as far as the text needs, a subtle dark one not at all", async () => {
  const view = tinted();
  const { C } = view;
  await view.show("/navy", view.canvas.poster(96, 144, () => [10, 20, 70]));
  // Solved for this poster: just past the contrast the text needs.
  const solved = C.contrast(TEXT, surfaceOf(view.card));
  assert.ok(solved >= 11 && solved < 11.5, `solved to ${solved}`);
  // Subtly tinted it is dark enough under the least scrim there is, and
  // keeps the colour the text could have spared.
  await view.set("data-cover-strength", "0");
  const least = C.contrast(TEXT, surfaceOf(view.card));
  assert.ok(least > 12, `left at ${least}`);
});

test("on a white panel no lighter accent can stand off it, so it is white", async () => {
  const view = tinted();
  view.token("--panel", "rgb(255, 255, 255)");
  await view.show("/yellow", view.canvas.poster(96, 144, YELLOW));
  assert.deepEqual(accentOf(view.main), [255, 255, 255]);
});

test("a bright poster's accent already stands off the panel and is kept as it is", async () => {
  const view = tinted();
  const { C } = view;
  await view.show("/yellow", view.canvas.poster(96, 144, YELLOW));
  const accent = accentOf(view.main);
  const lch = C.rgbToOklch(accent);
  assert.ok(Math.abs(lch[0] - 0.64) < 0.01, `held at the brightest an accent may be: ${lch[0]}`);
  assert.ok(C.contrast(accent, PANEL) >= 4.5);
});

test("without a MutationObserver a theme change is seen at the next poster", async () => {
  const view = page({ scripts: ["theme.js", "colour.js"] });
  view.window.MutationObserver = undefined;
  load(view.dom, "cover-tint.js");
  const canvas = fakeCanvas(view.window);
  const card = view.window.document.createElement("div");
  const image = canvas.poster(96, 144, BLUE);
  image.src = "/blue";
  view.window.TinyPPICover.show(card, "/blue", image);
  await settle();
  view.window.document.documentElement.setAttribute("data-theme", "midnight");
  await settle();
  assert.notEqual(card.style.getPropertyValue("--muted"), "");
  view.window.TinyPPICover.show(card, "/blue", image);
  assert.equal(card.style.getPropertyValue("--muted"), "");
});

test("a page with neither a card nor a main area has nothing to paint", async () => {
  const window = bare("colour.js", "cover-tint.js");
  opened.push(window);
  window.document.documentElement.setAttribute("data-theme", "dark-adaptive");
  const canvas = fakeCanvas(window);
  const tints = [];
  window.document.addEventListener("tinyppi-tint", () => tints.push(1));
  window.TinyPPICover.show(null, "/blue", canvas.poster(96, 144, BLUE));
  await settle();
  assert.deepEqual(tints, []);
  assert.equal(canvas.log.contexts, 0);
  // A card alone is painted, with no bars around it to take the accent.
  const card = window.document.createElement("div");
  const image = canvas.poster(96, 144, BLUE);
  image.src = "/blue";
  window.TinyPPICover.show(card, "/blue", image);
  await settle();
  assert.deepEqual(Object.keys(painted(card)), PAINTED);
  assert.equal(tints.length, 2);
});
