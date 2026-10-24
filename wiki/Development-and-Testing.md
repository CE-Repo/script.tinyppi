# Development and Testing

How to work on TinyPPI: get the code onto a box, run the tests, regenerate
generated files, and prepare a release. For the code structure see
[Architecture](Architecture).

---

## Getting the code

```bash
git clone https://github.com/CE-Repo/script.tinyppi.git
cd script.tinyppi
```

Requirements on the development machine:

- **Python 3.14** — what Kodi 22 ships, and what ruff, mypy and CI target.
  The tools are pinned in `requirements-dev.txt`.
- **Node.js 22** for the dashboard's lint and tests (`package.json`).

`pyproject.toml` and `package.json` hold tooling only; Kodi installs the
add-on from `addon.xml`.

---

## Trying a change on a CoreELEC box

1. Copy the add-on folder to the box, replacing the installed copy:

   ```bash
   rsync -av --delete --exclude .git --exclude .github --exclude tests \
         --exclude tools --exclude wiki --exclude node_modules \
         ./ root@coreelec:/storage/.kodi/addons/script.tinyppi/
   ```

2. Restart Kodi (`systemctl restart kodi`) — the service and its cached modules
   only reload with a new interpreter. Script-only changes take effect on the
   next launch, but anything running in the service (overlay, splash,
   dashboard) needs the restart.
3. Watch the log:

   ```bash
   tail -f /storage/.kodi/temp/kodi.log | grep TinyPPI
   ```

Useful switches while developing:

| Switch | Where | Effect |
|---|---|---|
| `FORCE_DEBUG = True` | `resources/lib/core/log.py` | Writes TinyPPI's debug lines at INFO level, without enabling Kodi's debug log. |
| `_ALLOW_NON_COREELEC = True` | `resources/lib/ui/overlay.py` | Lets the overlay open on a non-CoreELEC Kodi (desktop testing). Never commit it. |

---

## Tests and checks

The add-on's code runs outside Kodi: `tests/stubs` stands in for `xbmc`,
`xbmcgui`, `xbmcaddon` and `xbmcvfs`. The dashboard's scripts are tested in
jsdom and, against the real server with Kodi faked, in Chromium.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests
```

These are the checks CI runs on every push and pull request
(`.github/workflows/ci.yml`); run them before you push:

```bash
ruff check .                  # lint (settings in pyproject.toml)
mypy                          # types, with Kodistubs for Kodi's modules
xenon --max-average A --max-modules B --max-absolute B resources/lib main.py   # complexity
python3 -m pytest tests/unit --cov    # fails below 100 % (pyproject.toml)
npm ci && npm run lint        # ESLint for resources/web/js
npm run coverage              # the dashboard's scripts in jsdom; fails below 100 % (package.json)
npx playwright install chromium   # once
npm run test:browser          # the dashboard in Chromium against the real server
```

CI also runs the official `kodi-addon-checker` (branch *piers*) on the add-on
as Kodi installs it: `git archive` leaves out every development file marked
`export-ignore` in `.gitattributes`. Dependabot keeps the pinned tools and
the CI actions up to date.

| What | Rule |
|---|---|
| Coverage | Every line and branch, Python and dashboard scripts alike (100 %). New code comes with its tests. |
| Types | Every function annotated; mypy with `disallow_untyped_defs` and `disallow_any_generics`. The dashboard's payloads are `TypedDict`s (`web/payloads.py`, `web/library/entries.py`). |
| Complexity | Average rank A; every module and every function B or better (xenon). |
| Lint | ruff (Python 3.14 target) and ESLint. |

| File | Covers |
|---|---|
| `unit/test_library.py` | The dashboard's library cache (`web/library/`): one query for concurrent readers, no stale list after a drop, a scan's burst of notifications as one drop, the drops after playback stops, episodes, the continue row, marking |
| `unit/test_vs10_switcher.py` | VS10 switches from the dashboard: the last tap wins, a failed switch does not stop the next, the modes offered per source |
| `unit/test_vs10_driver.py` | VS10 switching against a simulated Dolby Vision driver (sysfs nodes as files): the write order per mode, TV-LED and Player-LED, bypass releasing the core first, HDR10 <-> DV through SDR, display resets only when the output moved, native actions preferred and their fallback, failed writes reported |
| `unit/test_server.py` | The HTTP server: the fixed routes, security headers, the token for writing and for untrusted host names, the guessing lockout, the connection caps, tokens and ports, IPv6 and IPv4 on one socket |
| `unit/test_routes.py` | What the write and library routes accept: bad bodies and lengths, unknown routes, control off, no token, commands and modes, a shelf's own setting, `watched` only as a boolean, library errors as 503, listings by ETag, artwork kinds and ids, the read session cookie |
| `unit/test_player.py` | The transport commands: only listed actions, seek and track values checked (no NaN, infinity, booleans or out-of-range values reach Kodi), seeking live TV against the broadcast, volume as remote input, chapters; track labels, player state, the EPG times |
| `unit/test_access.py` | Which host names count as the home network, which clients do (private, link-local, the box's own IPv6 networks); the lockout table; client addresses (IPv4-mapped as IPv4, IPv6 per /64 beyond the home network) |
| `unit/test_snapshot.py` | The snapshot: nothing playing, a playing title (times, frame, groups with N/A for empty rows), the file-name setting, the session-only pass, the last title kept, metadata only for DV, controls on the static interval, row and label helpers, artwork; the producer: idle passes, snapshots for watchers with the library revision, settings handed on, failures logged once, waits ending on stop |
| `unit/test_delta.py` | Delta frames of the event stream, applied as `js/core.js` applies them |
| `unit/test_artwork.py` | Artwork sources (Kodi's texture cache first) and types (from the bytes) |
| `unit/test_settings_definition.py` | `resources/settings.xml` against the five languages, the code and the skin: texts, defaults, dependencies, action buttons, color defaults and their translated names, opacity sliders, every setting read, every color property used |
| `unit/test_settings_logic.py` | The settings that only act with Dolby Vision or on Amlogic hardware, checked on their code paths; every color setting reaching its skin property; the color picker (HEX tile first, then the default, then the rest of the palette; color names numbered per family; every family light to dark, its neighbours alike in saturation; every tile distinct; older stored colors keep their color) |
| `unit/test_properties.py` | The language codes of the audio and subtitle rows: unmapped codes as reported, untagged tracks as UNK, no audio track as N/A; the audio rows read N/A without a codec |
| `unit/test_modules.py` | Every module imports; the small state holders behave |
| `unit/test_imax.py` | IMAX by name: listed titles at the end of the film part, years on remakes, spelling variants, the IMAX tag, Enhanced, names from paths and Kodi's titles |
| `unit/test_mediasource.py` | The media source row: release types, containers, sizes, streaming protocols, PVR, discs, addon links never stat'd |
| `unit/test_dvinfo.py` | Dolby Vision and HDR fields from parsed side data (`info/dvinfo.py`, `dvfields.py`): profiles, layers, L1/L5/L6, HDR10 and HDR10+, number formats, EL tag colors |
| `unit/test_dvmetadata.py` | The DV metadata view's rows: scene and static sections, trim tables per target display, the composer's curves and coefficients, value formatting |
| `unit/test_display.py` | The DRM display reset against a simulated device: HDMI first, the master descriptor, the cached ids and the negative cache |
| `unit/test_session.py` | The dashboard's history of the playing title: the sample clock, events for changed readings, track changes held back until settled, warnings once per crossing, frame-rate events, a new title, the finished title kept for the idle page |
| `unit/test_monitor.py` | The service's notifications: library drops, view handover (acknowledged, withdrawn, failing), fonts on a skin load, one splash at a time, dashboard settings, the start-up warm-up |
| `unit/test_helpers.py` | Frame-rate formatting and drops; the VS10 dialog's layouts: files, positions on screen, the branch per stream type |
| `unit/test_images.py` | PNG decoding (every filter, color type and indexed bit depth), scaling in premultiplied alpha, the texture cache and its pruning |
| `unit/test_fonts.py` | Font.xml: the resolution folders (never outside the skin), entries inserted in every fontset with the file's own layout, the ready and failed marks |
| `unit/test_splash_logos.py` | What the codec-logo splash shows: the logo per output mode, conversions told from the output, the DV layer pill, IMAX logos only when installed, audio known before Kodi names the codec |
| `unit/test_main.py` | The entry point: a view handed to the running service (acknowledged, withdrawn, no service), the commands and their arguments, the launch-mode default |
| `unit/test_overlay.py` | The overlay: CoreELEC and Kodi checks, opening over fullscreen video, placement per layout and the arrow-key nudge, keys and closing, DV readings lit when they change, the update loop and its stop reasons, the entry points and their locks |
| `unit/test_dvmetadata_dialog.py` | The Dolby Vision metadata windows: rows painted per kind, the list filled and its viewport kept, sections and their keys, highlights, the window fitted to its rows, static rows rebuilt, the session between list and sections |
| `unit/test_mode_select.py` | The VS10 dialog: its layout and labels per stream, focus, keys, the mode chosen and applied after it closes |
| `unit/test_dialog_layout.py` | The VS10 dialog's layouts outside Kodi and their fallbacks |
| `unit/test_splash.py` | The codec-logo splash (`ui/splash.py`, `splash_panel.py`, `splash_settings.py`): logo stacks, panel pieces, offsets and scale, per-mode settings, colors and visibility, fades, and the controller (start window, OSD and overlay modes, audio and settings changes, badges, settling, Kodi stopping) |
| `unit/test_theme.py` | Publishing the color and opacity settings, the unit label, the color picker and its HEX tile, old storage forms rewritten |
| `unit/test_webinfo.py` | The dashboard's settings actions: the address shown, a new token created |
| `unit/test_utils.py` | Kodi read passes, localized strings, change highlights, offsets, the coded frame and picture ratio, property batches, the overlay state and its refresh thread |
| `unit/test_core_settings.py` | The cached settings handle |
| `unit/test_files.py` | Atomic file writes |
| `unit/test_log.py` | Tagged log lines, the debug switch, credentials taken out of logged paths |
| `unit/test_publish.py` | The overlay's readings written as window properties: scene and static passes, only changed values, the progress bars |
| `unit/test_producer.py` | Snapshots handed out without a running producer thread |
| `unit/test_library_queries.py` | The library's JSON-RPC queries and rows: films, series, episodes and the continue row, resume points (including NaN and Infinity), ratings, tags that follow every field sent, playing and marking, bad ids that ask Kodi nothing |
| `unit/test_static.py` | The dashboard's route table and static file cache |
| `unit/test_ratings.py` | The playing title's ratings from the library: sources and their order, the reader's own, the age rating read for its board and level, the Top 250 place, a film's IMDb and TMDb ids |
| `unit/test_awards.py` | The big awards a title won or was nominated for: their order, a title the list does not hold, junk and a list that cannot be read |
| `unit/test_mdblist.py` | MDBList's ratings (key refused, daily limit, failures, the cache) and the IMDb Top 250 chart, each asked for off the snapshot's thread, laid over the library's |
| `unit/test_whatson.py` | WhatsOn's Rotten Tomatoes ratings and certificates (limit spent, failures, the cache), filled in where missing and worn by the ratings shown |
| `unit/test_strings.py` | The dashboard's UI strings |
| `unit/test_values.py` | Text and id helpers shared by the dashboard |
| `unit/test_dvcomposer.py` | The composer's rows of the Dolby Vision metadata view: curves, polynomial and MMR coefficients |
| `unit/test_dvformat.py` | Value formatting for the metadata view: numbers, luminances, scaled values and coordinates, missing and non-finite values |
| `web/core.test.mjs` | The dashboard's connection in jsdom: whole snapshots, delta frames as `web/delta.py` writes them, a delta without a base, bad frames, the session the token buys before the stream, the token in headers only, the token dialog, `bye`, the localized strings, value formatting, folded cards |
| `web/color.test.mjs` | The cover tint's color arithmetic: the sRGB curve, WCAG contrast, OKLab reference values, OKLCh round trips, chroma pulled into the gamut with lightness and hue kept |
| `web/readings.test.mjs` | The now-playing card's format badges (grade, resolution by coded width, IMAX/Atmos/DTS:X marks, the DV profile and layer, conversions) and the history's events (names with fallbacks, values, trends, switch totals) |
| `web/dashboard.test.mjs` | The dashboard's frame: tabs and the bar, the settings tab, idle and playing cards, detail groups, VS10 switching and its lock, the library reads a snapshot sets off, the report |
| `web/start.test.mjs` | Starting the page: the first tab, the stream, the words before and after `/api/hello` (also an error answer) |
| `web/marking.test.mjs` | What a press on a film, show or episode asks and what each answer sends, the lists read again afterwards, failures and the token dialog |
| `web/films.test.mjs` | The film wall, its rows and search, when the list is read again (a move during a read, a failed read after one), starting a film and the wall waiting on it |
| `web/series.test.mjs` | The series shelf, an opened show with its seasons, the way back (search included), the open show read again (also after a move during a read or while it opens), starting an episode |
| `web/continue.test.mjs` | The continue-watching rows, when they are read again, resuming a title |
| `web/live-panels.test.mjs` | The now-playing card, the overview (plot, credits, rating shields and their tooltips, folding), the remote and its track pickers (`js/live-remote.js`), the figures, the event list and the luminance chart (canvas faked) |
| `web/metadata.test.mjs` | The Dolby Vision metadata tab: the idle and L5 cards, blocks and trim tables, readings lit when they move, the report |
| `web/theme.test.mjs` | The themes and the tint strength: before the first paint (the bar color too), the choice on the settings tab, what a press keeps |
| `web/cover-tint.test.mjs` | The adaptive theme's poster tint (canvas and images faked): the color a poster gives, where it is painted, contrast, one read per poster, a reused `<img>` |
| `browser/dashboard.test.mjs` | The dashboard in Chromium against the real server with Kodi faked (`browser/serve.py`), reading behind the token: the stream on its session cookie, no token in any address, the format badges, the film wall and its search, the question a press asks and what marking sends, cancelling, a show's seasons, the history's wording, every tab, no script errors |

The `conftest.py` fixture resets the stubs' settings, properties, InfoLabels,
conditions, log and JSON-RPC handler before every test.

---

## The Kodi 22 suite

`tests/kodi` runs TinyPPI in a real **Kodi 22** under **Xvfb** and checks it
from outside — over JSON-RPC, over the dashboard's HTTP API, through a small
helper add-on inside Kodi (settings, Home-window properties), and on
screenshots.

| Run | Covers |
|---|---|
| `run_scan.py` | A library scan with an open films tab ends in about one re-read (with `BASELINE_REF`, compared with the same run on older code) |
| `run_functional.py` | Service, dashboard API and headers, access control, playback from the dashboard, the overlay (launch, toggle, handover), the VS10 dialog, codec logos, the remote (pause, seek, tracks, subtitles, chapters, volume), VS10 switching, watched / unwatched / resume, connection caps, the guessing lockout, the settings dialogs, the page in Chromium, a clean shutdown |
| `run_settings.py` | Every setting with an effect on a desktop Kodi, set live and measured: all colors and opacities, overlay, VS10 dialog, channel graphic, codec logos in all three modes, dashboard |
| `run_settings_dialog.py` | Every category of the settings dialog opens without errors |

### What it needs

- Kodi 22 for X11. Ubuntu 24.04 has no package; `build_kodi.sh` builds it from
  source into `/opt/kodi` (as root, about an hour).
- Xvfb, ImageMagick, ffmpeg with libx264 and libx265 (installed by
  `build_kodi.sh`).
- Python 3 with Pillow.
- Optional: Node.js with the `playwright` package for the browser check
  (skipped without it).
- An `/etc/coreelec` folder: the overlay and the VS10 dialog open on CoreELEC
  only, and this makes a desktop Kodi pass. **Use a throwaway machine or
  container.**

It is **not part of CI**: it builds Kodi from source and wants a throwaway
machine, so it runs by hand, for example before a release.

### Running it

```bash
sudo tests/kodi/build_kodi.sh        # once
sudo mkdir -p /etc/coreelec          # once, on a test machine only
tests/kodi/run_all.sh
```

`run_all.sh` makes the test media and a Kodi profile template (once), then runs
every suite on fresh profiles and exits non-zero on a failure. Runs can also be
started on their own, e.g. `python3 tests/kodi/run_settings.py splash`.

| Variable | Default | Purpose |
|---|---|---|
| `KODI_TEST_ROOT` | `/opt/kodi-test` | Media, profiles, screenshots, results (`results/*.json`) |
| `KODI_BIN` | `/opt/kodi/bin/kodi` | The Kodi to test |
| `KODI_TEST_DISPLAY` | `:99` | The Xvfb display |
| `BASELINE_REF` | *(none)* | A git ref to compare the scan run against, e.g. `main` |
| `PYTHON` | `python3` | The Python `run_all.sh` uses (needs Pillow) |

Kodi's web server is switched on in the test profiles (port 8080, user `kodi`,
password `kodi`) and the dashboard runs on 8099; keep both ports free.

### What only a CoreELEC box can test

- the Amlogic driver (the VS10 sysfs writes fail on a desktop and are reported
  apart as expected),
- Dolby Vision side data (stock Kodi does not publish it, and
  `script.module.sidedata` parses on aarch64 only),
- the output format the codec logos show.

---

## Generated files

The *Bar* and *Single button* VS10 dialog layouts are generated from the shared
description in `resources/lib/ui/dialog_layout.py`; the *Dialog* layout is
maintained by hand.

```bash
python3 tools/gen_dialog_skins.py   # writes script-tinyppi-dialog-bar.xml and -single.xml
python3 tools/gen_dialog_media.py   # draws media/dialog/arrow-left.png and arrow-right.png
```

Run them from the repository root after changing `dialog_layout.py`, and commit
the results.

---

## Conventions

- Every source file starts with an SPDX header:
  ```python
  # SPDX-License-Identifier: AGPL-3.0-or-later
  # Copyright (c) 2026 U3knOwn
  ```
- Module and function docstrings explain *why*, not just *what*; comments are
  plain English sentences.
- Never let an exception escape into Kodi from the service: log it with the
  module's `channel()` logger and carry on. Catch the errors a call can
  actually raise; only the outermost fault barriers catch everything.
- Never log a token or share credentials: paths go through `log.redacted()`.
- No thread may outlive the service script, and no wait may be unbounded
  (Kodi waits for every thread at shutdown).
- Write window properties only when the value changed
  (`set_changed_properties`), and read InfoLabels inside a `read_pass`.
- New user-visible text goes into **all five** `strings.po` files, with the
  next free ID in the block of its area (see
  [Translations](Translations#how-the-ids-are-arranged));
  `test_settings_definition.py` enforces it for settings.
- New settings need a label, a help text, a default and, for colors, an
  opacity slider; the definition test checks this.

---

## Releasing

1. Bump `version` in `addon.xml`.
2. Replace the `<news>` entry in `addon.xml` — it holds the **latest version
   only**.
3. Make sure CI is green (and ideally run the Kodi 22 suite).
4. Commit as *"Bump version to x.y.z"*, tag, and publish the ZIP to the
   repository.

---

## Contributing

Issues and pull requests are welcome at
<https://github.com/CE-Repo/script.tinyppi>. CI must pass: please include tests
for every change (coverage stays at 100 %), keep pull requests focused, and
describe how you verified the change (unit tests, Kodi 22 suite, or on which
CoreELEC box).

---

## Editing this wiki

The wiki's pages live in the repository's `wiki/` folder. A push to `main`
that changes them publishes them here (`.github/workflows/wiki.yml`), and
replaces what is here: edit the pages in `wiki/` through a pull request, not
in the wiki itself.
