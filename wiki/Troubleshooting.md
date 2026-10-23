# Troubleshooting

Start with [Reading the log](#reading-the-log) — almost every problem leaves a
line there — then look up your symptom below.

---

## Contents

- [Reading the log](#reading-the-log)
- [The overlay or dialog does not open](#the-overlay-or-dialog-does-not-open)
- [Error notifications](#error-notifications)
- [Dolby Vision / HDR rows show N/A](#dolby-vision--hdr-rows-show-na)
- [Overlay text is the wrong size or misaligned](#overlay-text-is-the-wrong-size-or-misaligned)
- [A VS10 switch does nothing or the picture looks wrong](#a-vs10-switch-does-nothing-or-the-picture-looks-wrong)
- [Codec logos do not appear](#codec-logos-do-not-appear)
- [The channel graphic does not appear](#the-channel-graphic-does-not-appear)
- [IMAX badge missing or wrong](#imax-badge-missing-or-wrong)
- [The web dashboard cannot be reached](#the-web-dashboard-cannot-be-reached)
- [The dashboard asks for a token / says wrong token](#the-dashboard-asks-for-a-token--says-wrong-token)
- [Too many connections](#too-many-connections)
- [Films or series tabs are missing](#films-or-series-tabs-are-missing)
- [Volume shows no level](#volume-shows-no-level)
- [Resetting TinyPPI](#resetting-tinyppi)
- [Reporting a bug](#reporting-a-bug)

---

## Reading the log

Kodi's log on CoreELEC is `/storage/.kodi/temp/kodi.log` (the previous
session's is `kodi.old.log`). Every TinyPPI line starts with `TinyPPI`,
optionally followed by an area in brackets:

```
TinyPPI: mode 'dv' set via VS10 Actions -> Action(vs10.dv)
TinyPPI [web]: dashboard listening on http://192.168.1.20:8099/
TinyPPI [service]: KodiMonitor started
```

| Area | Covers |
|---|---|
| *(none)* | Launches, overlay, VS10 switching |
| `[service]` | The background service and Kodi notifications |
| `[web]` | The dashboard server |
| `[library]` | The dashboard's film/series lists |
| `[splash]` | The codec logos |
| `[fonts]` | Font registration in the skin |

To filter them over SSH:

```bash
grep TinyPPI /storage/.kodi/temp/kodi.log
```

Many details are logged at **debug** level only. To see them, enable
**Settings → System → Logging → Enable debug logging**, reproduce the problem,
then read or upload the log (for example with the *Kodi Logfile Uploader*
add-on). Dashboard tokens are masked as `token=***` and share passwords as
`smb://***@…` in the log, so it is safe to share.

---

## The overlay or dialog does not open

Check, in this order:

1. **Is fullscreen video the active window?** TinyPPI opens only over
   fullscreen playback. From the add-on browser — with the video behind a
   menu — a launch silently does nothing. Use a key mapped as described in
   [Launching and Keymaps](Launching-and-Keymaps).
2. **Is something playing?** Paused is fine; stopped is not.
3. **Was it already open?** The launch key toggles: a second press closes it.
   A press while TinyPPI is still opening is dropped (*"open request dropped:
   TinyPPI is already opening"* at debug level).
4. **Did it just close?** For 0.2 s after closing, a new press is ignored, so a
   bouncing key does not reopen it.
5. **Is the key mapped correctly?** Test it with
   `RunScript(script.tinyppi)` from another add-on or JSON-RPC; if that works,
   the keymap is the problem. After editing a keymap file, restart Kodi.
6. **`NotifyAll` key does nothing?** `NotifyAll(script.tinyppi,open_overlay)`
   needs the service. Check that the add-on is enabled and look for
   `KodiMonitor started` in the log. `RunAddon(script.tinyppi)` works even
   without the service.
7. **Auto-hide** (**Settings → General**) set very short closes the overlay
   right after it opens.

---

## Error notifications

| Notification | Cause | Fix |
|---|---|---|
| *Only CoreELEC 22 or later is supported* | Not CoreELEC (no `/etc/coreelec`, no `coreelec` in `/etc/os-release`), or Kodi older than 22. | Use CoreELEC 22 or later. |
| *The CoreELEC version could not be detected* | Kodi's build version could not be parsed. | Report it with a log. |
| *720p skins are not supported* | The active skin has a `720p` folder. | Use a skin with a 1080i layout (Estuary, Arctic Fuse, Aeon Nox …). |
| *Invalid HEX color – using the default color* | The HEX code typed in a color picker was not 6 hex digits. | Enter e.g. `FF5733`. |

---

## Dolby Vision / HDR rows show N/A

- **Right after starting a title** the first RPU may not have been parsed yet;
  the rows fill in within a moment.
- **Missing parser.** Look for
  `DV: script.module.sidedata unavailable (…); DV/HDR metadata is not available`.
  Reinstall `script.module.sidedata` (1.6.0 or later) from the repository.
  The parser ships native libraries for **aarch64** only.
- **No side data.** All DV/HDR readings come from
  `Player.Process(video.sidedata)`, which only **CoreELEC 22 on Amlogic**
  publishes. Other Kodi builds show N/A everywhere.
- **The stream really has none.** An SDR file has no HDR metadata; an HDR10
  file without MaxCLL/MaxFALL SEIs has no CLL/FALL. The
  [metadata view](Dolby-Vision-Metadata-View) shows exactly what arrived in
  its **Stream** section.
- **Composer section empty** in the metadata view: the parser is older than
  1.6.0 (`include_mapping` missing). Update it.

---

## Overlay text is the wrong size or misaligned

The overlay uses two font sizes it registers in the active skin's `Font.xml`
(`font23_narrow`, 21 px, and `font32`, 32 px, both Kodi's own `arial.ttf`).
The service does this at start-up and after every skin load, then reloads the
skin once.

If the skin's `Font.xml` cannot be written — for example a **read-only skin
built into the system image** — the log says:

```
TinyPPI [fonts]: the font entries could not be registered in …/Font.xml; not trying again until the skin or its Font.xml changes
```

Kodi then draws the text in a fallback font. Use a skin installed from a
repository (which lives in the writable `/storage/.kodi/addons/`), or add the
two entries to the skin's `Font.xml` by hand:

```xml
<font>
  <name>font23_narrow</name>
  <filename>special://xbmc/media/Fonts/arial.ttf</filename>
  <size>21</size>
</font>
<font>
  <name>font32</name>
  <filename>special://xbmc/media/Fonts/arial.ttf</filename>
  <size>32</size>
</font>
```

After a **skin update** the entries are re-added automatically on the next
skin load.

---

## A VS10 switch does nothing or the picture looks wrong

See [VS10 Output Modes → Reading the log](VS10-Output-Modes#reading-the-log)
for the log lines of a switch.

| Symptom | Likely cause |
|---|---|
| `FAILED /sys/module/aml_media/…` in the log | The box has no Amlogic Dolby Vision driver (no VS10), or the kernel differs from CoreELEC 22's. VS10 switching is not possible on this hardware. |
| The dialog shows only **Player process info** | The source is HDR10+, HLG or a Dolby Vision + HDR10+ hybrid — VS10 does not take a mode for these. |
| Colors wrong / TV stays out of Dolby Vision after a switch | The display reset did not happen. Look for `did not move the driver's output mode -> no display reset`. Try the switch again, or stop and restart playback. |
| HDR10 → Dolby Vision lands on SDR | The switch is staged through SDR; if it was interrupted (playback stopped, 15 s exceeded) it stays on SDR. Press the mode again. |
| `run_mode` worked from a key, but not from the dashboard | The dashboard only accepts the modes it shows as buttons (no `sdr10`, `original_hlg`). |
| Dolby Vision output looks washed out on a Player-LED setup | TinyPPI reads CoreELEC's *Dolby Vision LED* setting to choose IPT or tunnelled IPT. Check **CoreELEC settings → Dolby Vision** matches your TV. |

---

## Codec logos do not appear

- At least one of **Show codec logos on playback start / in the video OSD / in
  the TinyPPI overlay** must be on.
- **Both logos on, but no panel?** With video *and* audio logo enabled, an
  audio codec without a logo (ALAC, WAV, WMA, AIFF …) hides the whole panel.
  Turn off **Show audio codec logo** for that situation to get the video logo
  alone.
- **On playback start** the logos wait for the output to settle before they
  appear, and only for **Display duration** seconds.
- **Looking in the wrong corner?** The default position is **top-left**
  (offsets 0 % / 0 %).
- Only videos get logos; music playback has none.

---

## The channel graphic does not appear

- It is enabled **per output type**: check the switch matching the source
  (**Channels in SDR / HDR10 / Dolby Vision**). During a VS10 conversion the
  *Converted output* settings decide which type applies.
- Channel counts without a graphic (for example 9 or 10 channels) show none.

---

## IMAX badge missing or wrong

See [IMAX Detection](IMAX-Detection). The log states how many titles were
loaded (`IMAX: N titles known, M of them IMAX Enhanced`). Add missing titles to
your own `imax_titles.txt`; for a wrong match, check that the entry is not too
short (add the year if it is a remake).

---

## The web dashboard cannot be reached

1. **Enabled?** **Settings → Dashboard → Enable web dashboard** must be on.
2. **Right address?** Use **Show address and token**. The page uses the box's
   IP and the configured port (`http://<box-ip>:8099/`), not Kodi's own web
   server port.
3. **Port taken?** The log says `cannot bind port 8099: [Errno 98] Address
   already in use`. Pick another port (1024–65535), and never 8080 if Kodi's web
   server uses it.
4. **Same network?** The phone must be on the same LAN/Wi-Fi, not on mobile
   data or a guest network isolated from the box.
5. **IPv4 or IPv6.** The server listens on both (on IPv4 only where IPv6 is
   unavailable). For an IPv6 address put it in brackets:
   `http://[fd00::20]:8099/`.
6. **Running?** Look for `dashboard listening on …` in the log.

---

## The dashboard asks for a token / says wrong token

- With **Require the token for reading too** on, the page asks before showing
  anything.
- Opened under a **non-home host name** (dynamic DNS, a custom domain), the
  page asks for the token even with that setting off — see
  [Dashboard Security](Dashboard-Security#trusted-host-names-dns-rebinding-protection).
- From a device **not on the home network** (a global IPv6 address the
  router lets through, a forwarded port), the page asks for the token too —
  see [Dashboard Security](Dashboard-Security#reading-without-the-token-home-network-only).
- A **bookmark with `?token=…`** from an older version no longer logs in: the
  token is only accepted in the page's own header now. Open the plain address
  and enter the token once.
- After **Generate a new token** every browser has to enter the new one (on the
  page's Settings tab).
- **Locked out?** After ten different wrong tokens within ten minutes the
  address is turned away for ten minutes, even with the right token. At home
  this only hits the device that guessed; wait it out.

---

## Too many connections

At most six live streams run at once. Pages in background tabs and locked
phones disconnect automatically, so this normally clears by itself; close old
tabs on other devices if it persists.

---

## Films or series tabs are missing

- **Show the film library** / **Show the series library** must be on.
- Both also need **Allow VS10 switching from the dashboard**: without control
  nothing could be played, so the shelves are not offered.
- An empty library shows *"No films in the video library"* /
  *"No series in the video library"*.
- *"The library could not be updated"* / *"Playback could not be started"*:
  check the log for `VideoLibrary…failed`.

---

## Volume shows no level

By design. The dashboard's volume keys send *volume up / down / mute* as remote
actions so a CEC amplifier can follow them. CEC has no absolute level, and the
level Kodi reports is its own mixer's, which may not move at all on such a
setup — so no figure is displayed.

---

## Resetting TinyPPI

| What | How |
|---|---|
| One color | Pick the tile marked **(Default)** and reset its Transparency. |
| All settings | Delete `/storage/.kodi/userdata/addon_data/script.tinyppi/settings.xml` and restart Kodi. This also creates a new dashboard token. |
| Logo cache | Delete `…/addon_data/script.tinyppi/scaled_images/` (rebuilt on demand). |
| Everything | Uninstall with *remove data*, then reinstall. |

---

## Reporting a bug

Open an issue at <https://github.com/CE-Repo/script.tinyppi/issues> with:

- TinyPPI version, CoreELEC version, box model and skin,
- what you did, what you expected and what happened,
- a **debug log** covering the problem,
- for metadata issues: the dashboard's **Copy report** (and the metadata list)
  for the title in question.
