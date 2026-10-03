# Tests

Two suites: unit tests that run anywhere in seconds, and an end-to-end
suite that drives a real Kodi 22.

## Unit tests

The add-on's code runs outside Kodi: `tests/stubs` stands in for `xbmc`,
`xbmcgui`, `xbmcaddon` and `xbmcvfs`.

```
python3 -m pip install pytest
python3 -m pytest tests
```

| File | Covers |
|---|---|
| `unit/test_library.py` | The dashboard's library cache: one query for concurrent readers, no stale list after a drop, a scan's burst of notifications as one drop, the drops after playback stops, episodes, the continue row, marking |
| `unit/test_vs10_switcher.py` | VS10 switches from the dashboard: the last tap wins, a failed switch does not stop the next, the modes offered per source |
| `unit/test_server.py` | The HTTP server: the fixed routes, security headers, the token for writing and for untrusted host names, the guessing lockout, the connection caps, tokens and ports |
| `unit/test_access.py` | Which host names count as the home network; the lockout table |
| `unit/test_delta.py` | Delta frames of the event stream, applied as `js/core.js` applies them |
| `unit/test_artwork.py` | Artwork sources (Kodi's texture cache first) and types (from the bytes) |
| `unit/test_settings_definition.py` | `resources/settings.xml` against the five languages, the code and the skin: texts, defaults, dependencies, action buttons, colour defaults and their translated names, opacity sliders, every setting read, every colour property used |
| `unit/test_settings_logic.py` | The settings that only act with Dolby Vision or on Amlogic hardware, checked on their code paths; every colour setting reaching its skin property; the colour picker (HEX tile first, then the default, then the rest of the palette; colour names numbered per family; every family light to dark, its neighbours alike in saturation; every tile distinct; older stored colours keep their colour) |
| `unit/test_properties.py` | The language codes of the audio and subtitle rows: unmapped codes as reported, untagged tracks as UNK, no audio track as N/A; the audio rows read N/A without a codec |
| `unit/test_modules.py` | Every module imports; the small state holders behave |

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
