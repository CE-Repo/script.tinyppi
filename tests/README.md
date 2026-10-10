# Tests

Two suites: unit tests that run anywhere in seconds, and an end-to-end
suite that drives a real Kodi 22.

## Unit tests

The add-on's code runs outside Kodi: `tests/stubs` stands in for `xbmc`,
`xbmcgui`, `xbmcaddon` and `xbmcvfs`.

```
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests
```

The same checks CI runs on every push (`.github/workflows/ci.yml`):

```
ruff check .                 # lint (settings in pyproject.toml)
mypy                         # types, with Kodistubs for Kodi's modules
python3 -m pytest --cov=resources/lib tests/unit   # fails below the floor in pyproject.toml
npm ci && npm run lint       # ESLint for resources/web/js
npm test                     # the dashboard's scripts in jsdom (tests/web)
npm run test:browser         # the dashboard in Chromium against the real server (tests/browser)
```

CI also runs the official `kodi-addon-checker` on the add-on without its
development files.

| File | Covers |
|---|---|
| `unit/test_library.py` | The dashboard's library cache: one query for concurrent readers, no stale list after a drop, a scan's burst of notifications as one drop, the drops after playback stops, episodes, the continue row, marking |
| `unit/test_vs10_switcher.py` | VS10 switches from the dashboard: the last tap wins, a failed switch does not stop the next, the modes offered per source |
| `unit/test_vs10_driver.py` | VS10 switching against a simulated Dolby Vision driver (sysfs nodes as files): the write order per mode, TV-LED and Player-LED, bypass releasing the core first, HDR10 <-> DV through SDR, display resets only when the output moved, native actions preferred and their fallback, failed writes reported |
| `unit/test_server.py` | The HTTP server: the fixed routes, security headers, the token for writing and for untrusted host names, the guessing lockout, the connection caps, tokens and ports, IPv6 and IPv4 on one socket |
| `unit/test_routes.py` | What the write and library routes accept: bad bodies and lengths, unknown routes, control off, no token, commands and modes, a shelf's own setting, `watched` only as a boolean, library errors as 503, listings by ETag, artwork kinds and ids |
| `unit/test_player.py` | The transport commands: only listed actions, seek and track values checked (no NaN, infinity, booleans or out-of-range values reach Kodi), seeking live TV against the broadcast, volume as remote input, chapters; track labels, player state, the EPG times |
| `unit/test_access.py` | Which host names count as the home network; the lockout table; client addresses (IPv4-mapped as IPv4, IPv6 per /64) |
| `unit/test_snapshot.py` | The snapshot: nothing playing, a playing title (times, frame, groups with N/A for empty rows), the file-name setting, the session-only pass, the last title kept, metadata only for DV, controls on the static interval, row and label helpers, artwork; the producer: idle passes, snapshots for watchers with the library revision, settings handed on, failures logged once, waits ending on stop |
| `unit/test_delta.py` | Delta frames of the event stream, applied as `js/core.js` applies them |
| `unit/test_artwork.py` | Artwork sources (Kodi's texture cache first) and types (from the bytes) |
| `unit/test_settings_definition.py` | `resources/settings.xml` against the five languages, the code and the skin: texts, defaults, dependencies, action buttons, colour defaults and their translated names, opacity sliders, every setting read, every colour property used |
| `unit/test_settings_logic.py` | The settings that only act with Dolby Vision or on Amlogic hardware, checked on their code paths; every colour setting reaching its skin property; the colour picker (HEX tile first, then the default, then the rest of the palette; colour names numbered per family; every family light to dark, its neighbours alike in saturation; every tile distinct; older stored colours keep their colour) |
| `unit/test_properties.py` | The language codes of the audio and subtitle rows: unmapped codes as reported, untagged tracks as UNK, no audio track as N/A; the audio rows read N/A without a codec |
| `unit/test_modules.py` | Every module imports; the small state holders behave |
| `unit/test_imax.py` | IMAX by name: listed titles at the end of the film part, years on remakes, spelling variants, the IMAX tag, Enhanced, names from paths and Kodi's titles |
| `unit/test_mediasource.py` | The media source row: release types, containers, sizes, streaming protocols, PVR, discs, addon links never stat'd |
| `unit/test_dvinfo.py` | Dolby Vision and HDR fields from parsed side data: profiles, layers, L1/L5/L6, HDR10 and HDR10+, number formats, EL tag colours |
| `unit/test_dvmetadata.py` | The DV metadata view's rows: scene and static sections, trim tables per target display, the composer's curves and coefficients, value formatting |
| `unit/test_display.py` | The DRM display reset against a simulated device: HDMI first, the master descriptor, the cached ids and the negative cache |
| `unit/test_session.py` | The dashboard's history of the playing title: the sample clock, events for changed readings, track changes held back until settled, warnings once per crossing, frame-rate events, a new title, the finished title kept for the idle page |
| `unit/test_monitor.py` | The service's notifications: library drops, view handover (acknowledged, withdrawn, failing), fonts on a skin load, one splash at a time, dashboard settings, the start-up warm-up |
| `unit/test_helpers.py` | Frame-rate formatting and drops; the VS10 dialog's layouts: files, positions on screen, the branch per stream type |
| `unit/test_images.py` | PNG decoding (every filter, colour type and indexed bit depth), scaling in premultiplied alpha, the texture cache and its pruning |
| `unit/test_fonts.py` | Font.xml: the resolution folders (never outside the skin), entries inserted in every fontset with the file's own layout, the ready and failed marks |
| `unit/test_splash_logos.py` | What the codec-logo splash shows: the logo per output mode, conversions told from the output, the DV layer pill, IMAX logos only when installed, audio known before Kodi names the codec |
| `web/core.test.mjs` | The dashboard's connection in jsdom: whole snapshots, delta frames as `web/delta.py` writes them, a delta without a base, bad frames, the token in the stream address and the command header, the token dialog, `bye`, the localized strings, value formatting, folded cards |
| `web/colour.test.mjs` | The cover tint's colour arithmetic: the sRGB curve, WCAG contrast, OKLab reference values, OKLCh round trips, chroma pulled into the gamut with lightness and hue kept |
| `web/readings.test.mjs` | The now-playing card's format badges (grade, resolution by coded width, IMAX/Atmos/DTS:X marks, the DV profile and layer, conversions) and the history's events (names with fallbacks, values, trends, switch totals) |
| `browser/dashboard.test.mjs` | The dashboard in Chromium against the real server with Kodi faked (`browser/serve.py`): the stream, the format badges, the film wall and its search, the question a press asks and what marking sends, cancelling, a show's seasons, the history's wording, every tab, no script errors |

## Kodi 22 suite

`tests/kodi` runs TinyPPI in Kodi 22 under Xvfb and checks it from outside:
over JSON-RPC, over the dashboard's HTTP API, through a small helper add-on
inside Kodi (settings, Home-window properties), and on screenshots.

| Run | Covers |
|---|---|
| `run_scan.py` | A library scan with an open films tab ends in about one re-read (with `BASELINE_REF`, beside the same run on older code) |
| `run_functional.py` | Service, dashboard API and headers, access control, playback from the dashboard, the overlay (launch, toggle, handover), the VS10 dialog, codec logos, the remote (pause, seek, tracks, subtitles, chapters, volume), VS10 switching, watched / unwatched / resume, connection caps, the guessing lockout, the settings dialogs, the page in Chromium, a clean shutdown |
| `run_settings.py` | Every setting with an effect on a desktop Kodi, set live and measured: all colours and opacities, overlay, VS10 dialog, channel graphic, codec logos in all three modes, dashboard |
| `run_settings_dialog.py` | Every category of the settings dialog opens, without errors |

What it cannot cover: an Amlogic driver (the VS10 sysfs writes fail and are
reported apart as expected), Dolby Vision side data (stock Kodi does not
publish it, and `script.module.sidedata` parses on aarch64 only), and the
output format the codec logos show.  Those want a CoreELEC box.

### What it needs

- Kodi 22 for X11.  Ubuntu 24.04 has no package; `build_kodi.sh` builds it
  from source into `/opt/kodi` (as root, about an hour).
- Xvfb, ImageMagick, ffmpeg with libx264 and libx265 (installed by
  `build_kodi.sh`).
- Python 3 with Pillow.
- Optional: Node.js with the `playwright` package for the browser check
  (skipped without it).
- An `/etc/coreelec` folder.  The overlay and the VS10 dialog open on
  CoreELEC only; this makes a desktop Kodi pass.  Use a throwaway machine
  or container.

### In CI

`.github/workflows/kodi.yml` runs the suite on a GitHub runner once a week
and on request (Actions -> "Kodi 22 suite" -> Run workflow).  The first run
builds Kodi (about an hour); later ones restore it from the cache.  The
results and screenshots are kept as the `kodi-suite` artifact.

### Running it

```
sudo tests/kodi/build_kodi.sh        # once
sudo mkdir -p /etc/coreelec          # once, on a test machine only
tests/kodi/run_all.sh
```

`run_all.sh` makes the test media and a Kodi profile template (once), then
runs every suite on fresh profiles and exits non-zero on a failure.  The
runs can also be started on their own, e.g. `python3 tests/kodi/run_settings.py splash`.

| Variable | Default | |
|---|---|---|
| `KODI_TEST_ROOT` | `/opt/kodi-test` | Media, profiles, screenshots, results (`results/*.json`) |
| `KODI_BIN` | `/opt/kodi/bin/kodi` | The Kodi to test |
| `KODI_TEST_DISPLAY` | `:99` | The Xvfb display |
| `BASELINE_REF` | (none) | A git ref to compare the scan run against, e.g. `main` |
| `PYTHON` | `python3` | The Python `run_all.sh` uses (needs Pillow) |

Kodi's web server is switched on in the test profiles (port 8080, user
`kodi`, password `kodi`) and the dashboard runs on 8099; keep both ports free.
