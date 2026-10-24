# Architecture

How TinyPPI is put together — for contributors, skinners and anyone curious
about what runs on the box. For the build and test workflow see
[Development and Testing](Development-and-Testing).

---

## Contents

- [Overview](#overview)
- [Repository layout](#repository-layout)
- [Processes and threads](#processes-and-threads)
- [Launch handover](#launch-handover)
- [Data flow of a reading](#data-flow-of-a-reading)
- [Home-window properties](#home-window-properties)
- [Kodi notifications handled](#kodi-notifications-handled)
- [The web dashboard](#the-web-dashboard)
- [Settings handle](#settings-handle)
- [Caches on disk](#caches-on-disk)
- [Shutdown](#shutdown)

---

## Overview

`addon.xml` declares two extension points:

| Extension point | Library | Role |
|---|---|---|
| `xbmc.service` | `resources/lib/service/monitor.py` | Long-lived background service, started with Kodi |
| `xbmc.python.script` | `main.py` | The launchable script (`RunAddon` / `RunScript`) |

Dependencies: `xbmc.python` 3.1.0 and `script.module.sidedata` 1.6.0.

The views are Kodi `WindowXMLDialog`s drawn from skin XML files in
`resources/skins/Default/1080i/`. Python computes the readings and publishes
them as **window properties**; the skin files only lay them out.

---

## Repository layout

```
script.tinyppi/
├── addon.xml                  Add-on manifest (version, dependencies, news)
├── main.py                    Script entry point: argument dispatch, handover
├── icon.png, fanart.png       Branding (see LICENSE-ASSETS)
├── LICENSE, LICENSE-ASSETS, NOTICE
├── wiki/                      Source of the GitHub wiki (published by .github/workflows/wiki.yml)
├── pyproject.toml             Tooling only: ruff, mypy, pytest, coverage
├── requirements-dev.txt       Pinned Python development tools
├── package.json               Tooling only: ESLint and the dashboard tests
├── .github/                   CI workflow and Dependabot
├── resources/
│   ├── settings.xml           Settings definition (7 categories)
│   ├── data/                  IMAX title list, language names
│   ├── language/              strings.po for en_gb, de_de, ar_sa, hu_hu, zh_cn
│   ├── lib/
│   │   ├── core/              Shared building blocks
│   │   ├── info/              Reading and interpreting player data
│   │   ├── service/           The background service
│   │   ├── ui/                The Kodi windows
│   │   └── web/               The dashboard server
│   ├── skins/Default/
│   │   ├── 1080i/             Window XML files
│   │   └── media/             Logos, channel graphics, icons, backgrounds
│   └── web/                   The dashboard page (HTML, CSS, JS, icons)
├── tests/                     Unit (Python), web (jsdom), browser (Chromium), Kodi 22 suite
└── tools/                     Generators for the VS10 dialog skins and media
```

### `resources/lib/core/`

| Module | Purpose |
|---|---|
| `constants.py` | Names shared everywhere, free of Kodi imports (add-on id, Home window id, handover property names, notification messages). |
| `settings.py` | One cached `xbmcaddon.Addon` handle per interpreter, renewed only when the stored settings file changes (one `stat` per call instead of a ~100 KB XML parse). |
| `log.py` | Tagged logging: `TinyPPI: …` and `TinyPPI [area]: …`. `FORCE_DEBUG` raises debug lines to INFO for local testing; `redacted()` takes share credentials out of paths before they are logged. |
| `utils.py` | Home-window helpers, InfoLabel reads (`info`, `cond`) inside a `read_pass`, change-only property writes, the `ChangeHighlighter`, offset parsing, the effective HDR type. |
| `helpers.py` | Frame-rate formatting and the FPS drop counter. |
| `maps.py` | Lookup tables: video/audio/subtitle codec names, codec logos, HDR logos, IMAX logos, channel layouts and speaker labels. Language names come from `resources/data/languages.json`. |
| `memo.py` | `KeyedMemo`, a one-entry cache keyed by its input. |
| `protocols.py` | Structural types shared by Kodi windows and their stand-ins (`PropertyTarget`). |
| `images.py` | PNG scaler (box filter, premultiplied alpha) with an on-disk cache of display-sized textures. |
| `display.py` | The HDMI display reset after a VS10 switch: sets the Amlogic `UPDATE` connector property via DRM ioctls from inside Kodi's process. |
| `vs10.py` | VS10 output modes (`set_mode`): native-action probing, sysfs sequences, staged switches. |
| `vs10_kodi.py` | What Kodi tells `vs10.py` before a switch: native `vs10.*` actions, the Dolby Vision LED setting, whether a video plays, DV + HDR10+ hybrids. |
| `files.py` | Atomic file writes. |

### `resources/lib/info/`

| Module | Purpose |
|---|---|
| `dvinfo.py` | Reads `Player.Process(video.sidedata)` and parses it with `script.module.sidedata` (only when the payload changes, results held briefly so ~20 getters cost one parse). |
| `dvfields.py` | The overlay's Dolby Vision / HDR fields derived from the parse result. |
| `dvmetadata.py` | The row model of the metadata view: walks the parse result into `(kind, name, value)` rows; holds blocks omitted under DM compression (*Cached*). |
| `dvlevels.py` | The metadata view's per-block sections (L1 … L255). |
| `dvcomposer.py` | The composer's rows (RPU data mapping: curves, polynomial and MMR coefficients). |
| `dvformat.py` | Row kinds and value formatting for the metadata view. |
| `properties.py` | Computes every overlay reading, one function per row: video, HDR, audio, subtitles and system. |
| `publish.py` | Publishes the readings as window properties: `publish_scene_properties` (every tick), `update_static_properties` (slow tick), `publish_properties` (before showing). |
| `mediasource.py` | The *Media source* row: release type, container and size, or the stream transport. |
| `imax.py` | IMAX / IMAX Enhanced detection by release name and title lists. |

### `resources/lib/ui/`

| Module | Purpose |
|---|---|
| `overlay.py` | The overlay dialog, its 100 ms update loop, positioning, and the entry points `open_tinyppi()` / `open_dialog_mode()` with their pre-flight checks. |
| `mode_select.py` | The VS10 dialog window (the switching itself is in `core/vs10.py`). |
| `dialog_layout.py` | Geometry and button branches of the three dialog layouts — shared with `tools/gen_dialog_skins.py`. |
| `dvmetadata.py` | The metadata view windows (list and single section). |
| `splash.py` | The codec-logo controller: image controls added to the fullscreen video window. |
| `splash_logos.py` | What the splash shows: the logos for the current output and audio, the DV layer pill, conversions. |
| `splash_panel.py` | The splash's panel: logos stacked on a rounded, tinted background. |
| `splash_settings.py` | The splash's settings, read in one go per settings change. |
| `theme.py` | The color picker, legacy color migration, and publishing the theme as Home properties. |
| `palette.py` | The color palettes, in the order the picker shows them. |
| `fonts.py` | Registers the overlay's font sizes in the active skin's `Font.xml`. |
| `webinfo.py` | The two dashboard buttons of the settings dialog (address/token, new token). |

### `resources/lib/web/`

| Module | Purpose |
|---|---|
| `server.py` | `WebDashboard` lifecycle (start/stop/reconfigure from settings), the threading HTTP server on IPv6 and IPv4, connection caps, token generation, port handling. |
| `routes.py` | The request handler: fixed route tables, authentication (token header, read session cookie), security headers, the SSE stream. |
| `access.py` | Who counts as the home network, client addresses (IPv6 per /64 beyond it), the wrong-token lockout and trusted host names. |
| `producer.py` | One thread building the snapshot for all streams (200 ms while watched, 1 s history-only otherwise). |
| `snapshot.py` | Builds a snapshot from the overlay's own readings, with the overview's plot, credits and ratings. |
| `ratings.py` | The playing title's ratings from the library over JSON-RPC: per source, the reader's own, the age rating (read for its board and level) and the IMDb Top 250 place. |
| `mdblist.py` | MDBList's ratings for a film (with an API key) and the IMDb Top 250 chart, each fetched off the snapshot's thread and cached. |
| `whatson.py` | Rotten Tomatoes' Certified Fresh and Verified Hot for a film from WhatsOn (a key optional), and its ratings where MDBList and the library lack them, off the snapshot's thread and cached. |
| `rows.py` | The dashboard's cards and rows, as the overlay shows them. |
| `session.py` | The playing title's history: chart samples, events, counters. |
| `player.py` | The playing video over JSON-RPC: tracks, volume, chapters, live-TV times and the remote's commands. |
| `vs10.py` | The VS10 modes offered on the dashboard and the switcher that applies them one at a time. |
| `delta.py` | Delta frames between snapshots. |
| `payloads.py` | The shapes the dashboard sends (snapshots, delta frames, history) as `TypedDict`s. |
| `library/` | The film and series library: `cache.py` (cached lists, revision, coalesced drops), `films.py`, `series.py`, `progress.py` (continue watching), `marks.py` (watched / resume writes), `common.py` (JSON-RPC and row helpers), `entries.py` (list shapes). |
| `artwork.py` | Artwork from Kodi's texture cache first, content type from the bytes. |
| `static.py` | The page's files, with ETags and gzip. |
| `strings.py` | The UI strings sent to the page, in Kodi's current language. |
| `values.py` | Text and id helpers shared by snapshot, player and library: plain library text, name lists. |

### `resources/web/`

| File | Purpose |
|---|---|
| `index.html` | The single page (all tabs). |
| `js/core.js` | Connection, token (header only) and read session, SSE stream and delta application, foldable panels. |
| `js/dashboard.js` | Tabs, the bar, dialogs, VS10 buttons, reports. |
| `js/start.js` | Starts the page: localized strings, the first tab, the stream. |
| `js/live-panels.js` | The now-playing card, the overview (plot, credits, rating shields, folding), figures, chart and events. |
| `js/live-remote.js` | The remote on the now-playing card: transport row and track pickers. |
| `js/readings.js` | Format badges and the wording of the history's events. |
| `js/films.js` | The film wall, its rows and search. |
| `js/series.js` | The series shelf, a show's seasons and episodes. |
| `js/continue.js` | The continue-watching rows. |
| `js/marking.js` | The question a press on a title asks (play, from the start, watched / unwatched). |
| `js/metadata.js` | The Dolby Vision metadata list. |
| `js/theme.js` | Theme selection and persistence. |
| `js/cover-tint.js` | Poster color extraction for *Dark (adaptive)*. |
| `js/colour.js` | Color arithmetic for the tint (sRGB, OKLab, contrast). |
| `css/*.css` | Base, theme, dashboard, live panels, metadata. |
| `manifest.webmanifest` | Add-to-home-screen metadata. |

### Skin files (`resources/skins/Default/1080i/`)

| File | View |
|---|---|
| `script-tinyppi-main.xml` | The overlay |
| `script-tinyppi-dv-metadata.xml` | The Dolby Vision metadata view |
| `script-tinyppi-dialog.xml` | VS10 dialog, *Dialog* layout (maintained by hand) |
| `script-tinyppi-dialog-bar.xml` | VS10 dialog, *Bar* layout (generated) |
| `script-tinyppi-dialog-single.xml` | VS10 dialog, *Single button* layout (generated) |

---

## Processes and threads

Kodi runs each add-on invocation in its own Python interpreter.

| Interpreter | Lifetime | Runs |
|---|---|---|
| **Service** (`monitor.py`) | whole Kodi session | `KodiMonitor`, views handed over by launches, the codec-logo controller, the web dashboard |
| **Script** (`main.py`) | one launch | argument dispatch; normally just the handover |

Threads inside the service:

| Thread | Interval | Work |
|---|---|---|
| Kodi notification thread | event-driven | `onNotification`, `onSettingsChanged` |
| Warm-up | once, 5 s after start | font registration, importing the views, pruning the logo cache |
| View thread | while a view is open | the modal overlay / dialog |
| Overlay update loop | 100 ms (static facts 1 s) | readings, highlight, positioning |
| VS10 dialog HDR loop | 500 ms | source re-detection, branch switching |
| Metadata view refresh | 100 ms | rows and highlights |
| Splash controller | 250 ms (format 1 s) | codec logos |
| Font install | after a skin load (+1 s) | `Font.xml` entries |
| Dashboard producer | 200 ms watched / 1 s idle | snapshots, session history |
| HTTP request threads | per connection | routes, SSE streams |
| VS10 mode switcher | per request | applies dashboard switches one at a time |

---

## Launch handover

Importing the overlay modules in a fresh interpreter costs noticeable time.
The service has them loaded, so `main.py` asks it to open the view:

1. The service sets `TinyPPI.Service = 1` on the Home window at start.
2. A launch writes a unique token (`view:pid:time`) into `TinyPPI.OpenRequest`
   and sends `NotifyAll(script.tinyppi,open_overlay)` (or `open_dialog`).
3. The service's monitor receives `Other.open_overlay` from sender
   `script.tinyppi`, copies the request token to `TinyPPI.OpenAck`, clears the
   request and runs the view on its own thread.
4. The launch polls `TinyPPI.OpenAck` every 10 ms for up to 750 ms. On a match
   it exits; otherwise it writes `-` (withdrawn) into the request — so a late
   service does not open a second view — and opens the view itself.

A keymap can send step 2's `NotifyAll` directly and skip the script entirely.

---

## Data flow of a reading

```
Kodi InfoLabels / Player.Process(...)      Amlogic sysfs (dv mode, fps drop)
Player.Process(video.sidedata) ──► script.module.sidedata ──► info/dvinfo.py
                    │
                    ▼
        info/properties.py  (format, map, unit, highlight)
        info/publish.py
                    │  window properties, written only when changed
                    ▼
        skin XML labels ($INFO[Window().Property(...)])  ──►  overlay on screen
                    │
                    └──► web/snapshot.py, web/rows.py (same publishers into a PropertySink)
                              │
                              ▼
                      producer ──► SSE state / delta ──► browser
```

All reads of one refresh happen inside a `read_pass`, so each InfoLabel is read
once per pass even when several rows use it.

---

## Home-window properties

TinyPPI publishes its state on the Home window (id 10000). Skins and other
add-ons may read them.

**State**

| Property | Meaning |
|---|---|
| `TinyPPI.Service` | `1` while the service runs. |
| `TinyPPI.OpenRequest` / `TinyPPI.OpenAck` | Launch handover. |
| `TinyPPI.Running` | `true` while a TinyPPI view is open. |
| `TinyPPI.Active` | `true` while the overlay itself is visible. |
| `TinyPPI.DialogMode` | `true` while the VS10 dialog is open. |
| `TinyPPI.DialogPlaced` | `1` once the VS10 dialog panel has been positioned. |
| `TinyPPI.HdrType` | Source format: empty (SDR), `hdr10`, `hdr10plus`, `hlg`, `dolbyvision`. |
| `TinyPPI.EffectiveHdrType` | The type the layout follows (differs during VS10 conversion). |
| `TinyPPI.Hdr10PlusPresent` | `1` for a Dolby Vision source carrying HDR10+. |
| `TinyPPI.ShowChannelIcon` | `1` when the channel graphic is enabled for the current type. |
| `TinyPPI.Filename`, `TinyPPI.ShowL5Icon`, `TinyPPI.ShowLine`, `TinyPPI.ShowHeaderTitle`, `TinyPPI.ShowHeaderIcon` | Overlay content switches. |
| `TinyPPI.UnitLabel` | The brightness unit text. |
| `TinyPPI.MetadataSectionView` | Set while the metadata view shows a single section. |
| `TinyPPI.SplashActive`, `TinyPPI.SplashVisible`, `TinyPPI.SplashStartVisible`, `TinyPPI.SplashOsdVisible`, `TinyPPI.SplashTinyPPIVisible`, `TinyPPI.SplashConverting` … | Codec-logo controller state. |
| `TinyPPI.FontsReady` / `TinyPPI.FontsFailed` | Font registration marks. |

**Colors** — one `AARRGGBB` property per color setting, for example:

`TinyPPI.BackgroundColor`, `TinyPPI.GlobalBackgroundColor`, `TinyPPI.TitleColor`,
`TinyPPI.HeaderColor`, `TinyPPI.DescriptionColor`, `TinyPPI.OutputColor`,
`TinyPPI.OutputChangedColor`, `TinyPPI.FilenameColor`, `TinyPPI.FpsColor`,
`TinyPPI.UnitColor`, `TinyPPI.AccentColor`, `TinyPPI.IconColor`,
`TinyPPI.HeaderIconColor`, `TinyPPI.ProgressColor`, `TinyPPI.LineColor`,
`TinyPPI.ConvertYesColor`, `TinyPPI.ConvertNoColor`, `TinyPPI.FelColor`,
`TinyPPI.MelColor`, `TinyPPI.Metadata…Color` (12), `TinyPPI.Dialog…Color` (8),
`TinyPPI.Channel…Color` (3) and `TinyPPI.Splash{Start,Osd,Tinyppi}{Bg,Video,Audio,Divider,ConvertDot,Fel,Mel,Dv}Color`.

---

## Kodi notifications handled

| Notification | Reaction |
|---|---|
| `Other.open_overlay` / `Other.open_dialog` (sender `script.tinyppi`) | Open the view in the service. |
| `GUI.OnSkinLoaded` | Re-register the fonts (on a thread, after 1 s). |
| `Player.OnAVStart` | Start the codec-logo controller if any situation is enabled. |
| `VideoLibrary.OnUpdate` / `OnRemove` | Mark the dashboard lists changed; drops are coalesced (2 s quiet, at most 10 s). |
| `VideoLibrary.OnScanFinished` / `OnCleanFinished` | Drop the dashboard lists at once. |
| `Player.OnStop` | Expect a resume point / play count write shortly; drop the lists after it settles. |
| `onSettingsChanged` | Start the splash if newly enabled; start, stop or reconfigure the dashboard. |

---

## The web dashboard

- `WebDashboard.apply_settings()` starts, stops or restarts the server when the
  port or token changes, and updates the other settings in place.
- The server is a `ThreadingHTTPServer` on one dual-stack socket (`[::]:<port>`,
  IPv6 and IPv4; `0.0.0.0` where IPv6 is unavailable) with per-address (16;
  beyond the home network per IPv6 /64) and total (48) connection caps and
  six SSE stream slots.
- The token is only read from the `X-TinyPPI-Token` header; the stream and
  pictures use a read session cookie bought with it (`POST /api/session`).
- One `Producer` thread builds snapshots only while a stream watches or a
  `/api/state` request waits; otherwise it only samples the session history
  once a second.
- Snapshots carry a `library` revision; the page re-reads its shelves when it
  changes. Library lists are cached in memory with ETags and invalidated by
  the notifications above.

Details: [Web Dashboard](Web-Dashboard), [Dashboard HTTP API](Dashboard-HTTP-API),
[Dashboard Security](Dashboard-Security).

---

## Settings handle

`xbmcaddon.Addon()` parses the whole settings definition on first read. The
service lives all session, so a handle kept forever would never see changes,
and a fresh one per read would cost a parse several times a second.
`core.settings.addon()` keeps one handle and replaces it only when the stamp
(mtime, size, inode) of `addon_data/script.tinyppi/settings.xml` changes.

---

## Caches on disk

| Path | Content | Invalidation |
|---|---|---|
| `addon_data/script.tinyppi/scaled_images/` | Codec logos scaled to their on-screen size | Named after source content, target size and scaler version; stale files pruned by the warm-up after updates. |

Everything else (library lists, side-data parses, title index, size stats) is
held in memory only.

---

## Shutdown

After the service script returns, Kodi waits — without a timeout — for every
interpreter thread, and raises `SystemExit` after five seconds. The service
therefore:

1. clears `TinyPPI.Service` (no more handovers),
2. stops the dashboard with a single 3 s deadline for all threads, hanging up
   idle keep-alive connections and sending open streams a `bye` frame,
3. exits — nothing may outlive the script.
