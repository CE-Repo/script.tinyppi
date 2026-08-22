# script.tinyppi

A CoreELEC addon that displays detailed playback information in a custom overlay window during video playback. It provides real-time data on video, audio, HDR, system resources, and more — with special support for **Amlogic** hardware (e.g. CoreELEC devices).

---

## Screenshots
<p align="center">
<img width="1200" alt="No Convert" src="https://github.com/user-attachments/assets/b083e2b2-bff2-40de-bdc4-361688e4df5c" />
</p>

<p align="center">
<img width="1200" alt="Convert" src="https://github.com/user-attachments/assets/0260625f-7d2e-4bf8-b07c-10547dfc0956" />
</p>

<p align="center">
<img width="1200" alt="VS10-Dialog" src="https://github.com/user-attachments/assets/d0a005fb-62bf-4277-93ee-4358f61cb172" />
</p>

---

## Installation

### Via Repository

1. Open **Settings → File Manager → Add Source**.
2. Enter the repository URL and confirm:
   ```
   https://ce-repo.github.io/repository.jamal2362/
   ```
3. Go to **Add-ons → Install from ZIP file** and select the source you just added.
4. Install the repository ZIP file.
5. Go to **Install from repository**, open the repository, select **TinyPPI** and install.

---

## Usage

### Assign a remote shortcut — Easy way (Keymap Editor)

1. Install the **Keymap Editor** addon.
2. Open it and select **Edit → Global → Add-ons**.
3. Select **Launch TinyPPI**.
4. Press the key or button you want to assign, then confirm.
5. Go back and select **Save**.

Pressing the assigned key/button will now launch or close TinyPPI in the Video OSD.

### Assign a remote shortcut — Manual (`gen.xml`)

Place the following in `Userdata/keymaps/gen.xml`, replacing `xxxxx` with your key name:

```xml
<keymap>
  <global>
    <keyboard>
      <xxxxx>RunAddon(script.tinyppi)</xxxxx>
    </keyboard>
  </global>
</keymap>
```

### Launch from another addon or autostart (Python)

```python
import xbmc
xbmc.executebuiltin('RunScript(script.tinyppi)')
```

### Launch via Kodi URL

```
plugin://script.tinyppi/
```

---

## Codec Logos

TinyPPI can display the current **video (HDR) and audio format** as stacked logos
directly on the video window during playback. The video/HDR logo sits on top, the
audio logo below it, on a rounded panel whose colors and opacity are fully themeable
in the add-on settings. The logos are re-resolved live, so switching the audio track
updates the audio logo on the fly.

You can enable the logos in three independent situations (**Settings → Codec Logos**):

- **On playback start** — shown for the first few seconds after a video starts
  (duration configurable).
- **While the Video OSD is open** — shown whenever the player OSD is visible.
- **While the TinyPPI overlay is open** — shown alongside the info overlay.

For each situation the horizontal/vertical position and the size can be adjusted
separately.

### Supported formats

**Video / HDR**

| Logo | Format |
|------|--------|
| SDR | Standard Dynamic Range |
| HDR10 | HDR10 |
| HDR10+ | HDR10+ |
| HLG | Hybrid Log-Gamma |
| Dolby Vision | Dolby Vision |

**Audio**

| Logo | Format |
|------|--------|
| AAC | AAC (incl. HE-AAC) |
| Dolby Digital | Dolby Digital (AC-3) |
| Dolby Digital Plus | Dolby Digital Plus (E-AC-3) |
| Dolby Digital Plus Atmos | Dolby Digital Plus with Dolby Atmos |
| Dolby TrueHD | Dolby TrueHD |
| Dolby TrueHD Atmos | Dolby TrueHD with Dolby Atmos |
| DTS | DTS |
| DTS 96/24 | DTS 96/24 |
| DTS-ES | DTS-ES |
| DTS-Express | DTS Express |
| DTS-HD HRA | DTS-HD High Resolution Audio |
| DTS-HD MA | DTS-HD Master Audio |
| DTS:X | DTS:X |
| IMAX | DTS:X IMAX Enhanced |
| FLAC | FLAC |
| PCM | PCM / LPCM |
| MP3 | MP3 |
| OPUS | Opus |

Formats without a matching logo simply omit the audio image.

---

## Channel Layout Graphic

TinyPPI can display a **speaker layout graphic** for the current audio track,
visualising how many channels the stream carries and where the active speakers
sit. The active speakers are highlighted against the full layout, so a 5.1 track
lights up its six positions while the remaining speaker slots stay dimmed.

The graphic can be enabled independently per output type
(**Settings → Channels**):

- **Channels in SDR** — show the layout while playing SDR content.
- **Channels in HDR10 / HLG / HDR10+** — show the layout while playing HDR content.
- **Channels in Dolby Vision** — show the layout while playing Dolby Vision content
  (drawn in its own panel above the main info box).

The colors of the background box, the speaker layout behind the active channels,
and the active channels themselves are all fully themeable in the add-on settings.

### Supported layouts

| Graphic | Layout |
|---------|--------|
| 1.0 | Mono |
| 2.0 | Stereo |
| 2.1 | Stereo + LFE |
| 3.1 | 3.1 surround |
| 4.1 | 4.1 surround |
| 5.1 | 5.1 surround |
| 5.1.2 | 5.1.2 with height channels (Atmos / DTS:X) |
| 6.1 | 6.1 surround |
| 7.1 | 7.1 surround |
| 7.1.2 | 7.1.2 with height channels (Atmos / DTS:X) |

The height variants (5.1.2 / 7.1.2) are selected automatically for Dolby Atmos
and DTS:X streams — Kodi reports only a channel count, so the extra height
channels are inferred from the codec. Channel counts without a matching graphic
simply omit the image.

---

## Dolby Vision Metadata View

Enable **Settings → Debug → Dolby Vision metadata view** first; it is off out of
the box, and while it is off **OK** on the overlay does nothing, exactly as
before.

With it on, pressing **OK** on the open TinyPPI overlay during a **Dolby
Vision** source switches to a debug view listing everything the stream's side
data carries — far more than the overlay itself has room for. Pressing **OK**
again switches back to the normal TinyPPI view; **Back** closes TinyPPI
altogether. Up/Down scroll through the list, which refreshes ten times a second,
so the per-frame blocks follow the picture. A reading that just moved is written
in the highlight colour and stays in it for **Settings → DV metadata → Changed
values → Highlight duration** (750 ms out of the box), so a change is readable
without slowing the refresh down; the overlay's own Dolby Vision readings have
the same pair of settings under **Settings → TinyPPI overlay → Changed values**.
On any other source **OK** keeps doing nothing: there is no Dolby Vision side
data to show.

The view is grouped by metadata block:

| Section | Contents |
|---------|----------|
| Stream | Kodi's own HDR type and detail, the side-data sections that arrived, the stream flags (`converted`, `rpu-removed`, …), the layer structure and the parser version |
| Configuration record | The dvcC / dvvC record: version, profile, compatibility ID, level, RPU / BL / EL presence, metadata compression |
| RPU | Guessed profile, CM version, DM compression, the DM metadata IDs, scene refresh flag and extension-block count, and the full RPU header (types, VDR profile / level / normalized IDC, the VDR sequence-info and DM-metadata presence flags, BL / EL / VDR bit depth, EL type, full range, resampling, residual and coefficient fields, previous-RPU reuse, the NAL prefix and the reserved field) |
| Composer | The reshaping metadata the decoder actually applies to the base layer: the mapping's colour space, chroma format and tile partitioning, then a section per component (Y, Cb, Cr) with its curve shape, its pivots and the coefficients of every segment — and, on the dual-layer profiles that carry one, the NLQ dequantization data |
| L1 | Frame luminance, min / max / average, as raw PQ codes and nits |
| Source master | The PQ range of the master the grade was made from, and its display diagonal |
| Colorimetry | The VDR DM signal description and the YCC → RGB / RGB → LMS matrices, in raw codes |
| L2 / L8 | Every trim pass, as raw 12-bit codes and on the Dolby UI scale, plus L8's secondary saturation / hue vectors on the streams that carry them and each pass's own block length |
| L3 | PQ offsets |
| L4 | Temporal stability: the anchor PQ and power |
| L5 | Active-area offsets (the black bars the RPU declares) |
| L6 | The RPU's own mastering display and MaxCLL / MaxFALL |
| L9 / L10 | Source primaries and the target displays the L8 trims are graded against, each with its block length |
| L11 | Content type, whitepoint, reference mode and the reserved bytes |
| L254 / L255 | The CM v4.0 marker block, and the debug run mode block on the rare stream that carries one |
| Static metadata | The MDCV / CLL SEIs — the stream's own HDR10 layer, shown apart from L6 |
| HDR10+ | The ST 2094-40 payload, when the stream carries one alongside Dolby Vision |

Blocks the stream does not carry are still listed, with their values shown as
`—`, so an absent block is visible rather than silently missing. Reading and
parsing is done by
[script.module.sidedata](https://github.com/matthane/script.module.sidedata);
the field names and units follow its own field reference.

Everything in the view is printed as the bitstream carries it, with one
exception: the composer's coefficients. The RPU splits each of them into an
integer and a fractional half that say nothing read apart, so they are shown
combined — `int + frac / 2 ** coefficient_log2_denom`, the arithmetic the RPU
syntax itself defines, with the denominator readable in the **RPU** section
above. The composer is also the one part of a parse TinyPPI asks for rather
than always builds: it runs to hundreds of coefficients, so it is read only
while this view is open and the overlay's own polling never pays for it.

---

## Web Dashboard

TinyPPI can serve everything the overlay shows to a browser on your phone or
laptop, so the readings can be followed **while the picture stays untouched**.
The dashboard is off out of the box; switch it on under **Settings →
Dashboard**, then open the address it names on any device on the same network:

```
http://<box-ip>:8099/
```

**Settings → Dashboard → Show address and token** prints that address together
with the access token, which is what you need standing in front of the TV with
a phone in your hand.

### What it shows

- **Now playing** — the poster, title, year and genre, the file name (when
  *Show file name* is on), elapsed time and progress.
- **The format logos the overlay draws** — the very files from the add-on's own
  skin, so a Dolby Vision Atmos title wears the same two badges on the phone as
  it does on the TV.
- **Metrics** — the frame rate with dropped frames called out beneath it, the
  frames lost across the whole title, and how often the output was switched.
  Only the add-on sees every frame, so the last two are figures a browser
  could not work out for itself.
- **A live luminance chart** — the Dolby Vision L1 peak and frame average on a
  logarithmic scale, over the last minute, the last ten, or the whole title:
  the add-on has been sampling since playback started, so a page opened halfway
  through a film gets the part it missed instead of starting from empty.
- **Buffer and frame drops** — the same three ranges, showing how full the
  cache ran and how many frames went missing while it did. The two belong on
  one chart because they are usually the same story, and unlike the luminance
  chart this one is drawn for **every source**: it is what to look at when a
  film stutters, whatever it was graded in.
- **Events** — a list with timestamps of the things worth knowing about: an
  output switched to or from Dolby Vision, a display mode change, the cache
  dipping, frames going missing. Every stutter is listed, down to a single
  lost frame and however briefly it lasted, with the worst second it reached;
  a stutter that goes on is one entry rather than five a second.
- **What the last title came to** — for ten minutes after the credits the page
  keeps the film that just ended: a card of its own with its peak, the frames
  it lost and how often the output was switched, and the events of that film
  still under it. The idle page is those cards centred as one column. Those
  figures are worth most once a film is over, which used to be exactly when
  they were thrown away.
- **The active picture area** the RPU declares (L5), drawn to scale inside the
  coded frame — the letterbox as the stream describes it, changing with the
  scene on an IMAX Enhanced title. It sits on the metadata window, with the
  blocks it is read from.
- **Every row of the overlay**, grouped as it is on screen: Video, Processing,
  Audio, HDR static metadata, Dolby Vision metadata and System. A reading that
  just moved is highlighted the same way the overlay highlights it.
- **A button to the Dolby Vision metadata view**, which opens in a **window of
  its own** (see below).
- **Copy report** hands the whole set over as plain text, ready to paste into a
  forum post — the rows, what the title added up to, and the events along the
  way. It works on the idle page too, where it writes the report of the title
  that just finished.

What a source cannot carry is left out rather than shown empty: the peak and
average tiles, the luminance chart, the active-area box and both metadata
sections come from the Dolby Vision RPU, so they appear for a Dolby Vision
title and not for any other, and the HDR static-metadata group is left out on
an SDR one. That is the same rule the overlay follows when it decides which
panels to draw.

The row labels come from Kodi's own string table, so the dashboard is in the
same language the overlay is. Nothing is loaded from the internet: the page is
served entirely by the add-on and works on a box with no outside connection.
On a phone it can be added to the home screen.

### What it costs to leave open

A second screen is left running for the length of a film, so the page is built
not to be felt while it is:

- **It connects as it loads.** The stream is opened in the same breath as the
  page rather than after the translations have been fetched, so the dashboard
  is live about as fast as it can draw.
- **Only what moved is sent.** A browser is given one whole snapshot when it
  connects and, five times a second after that, only the readings that actually
  changed — which on a title standing still is a few dozen bytes where the
  snapshot it replaces is tens of kilobytes.
- **A page nobody is looking at is not connected.** Lock the phone or switch
  tabs and the stream is dropped; come back and it is up again immediately.
  That is the battery on the phone and one of the add-on's six stream slots,
  neither spent on a page in a pocket.
- **The page itself is cached.** Its files are sent with a validator and
  compressed, so opening the dashboard a second time fetches almost nothing,
  and the poster is fetched once per film however often the page is reopened.
- **A full server says so.** Open the dashboard on a seventh device and it
  reports that rather than sitting on "Disconnected"; it takes the first slot
  that frees.

### Themes

The button beside the TinyPPI name in the top bar switches the page between
three themes, and every one of them is dark — this is watched in the room the
projector is in, so there is nothing here for a lit one. A press walks through
them; **holding the button down** (or right-clicking it) opens a menu to jump
straight to one:

- **Dark** — the plain one, and what a first visit gets.
- **Dark (adaptive)** — the same page, with the **now-playing card** taking
  its colour from the poster of whatever is on screen. The artwork is read
  region by region and the one colour that stands for it best is drawn across
  the card as a broad glow — strongest beside the poster, spent well before the
  foot, so the bottom of the card is the same plain panel every other one is
  whether the controls are folded out or away.
  How much of the colour survives is worked out per film against the contrast
  the card's text needs: a dark poster keeps nearly all of it, a bright one is
  held down as far as it has to be, and both end up equally readable. No other
  card is painted: the surfaces around the film stay exactly what they are on
  the plain dark theme, so the page has one coloured thing on it and everything
  else is the page.
  What the other cards do take is the film's accent, for the things read past
  rather than read — the card headings, a badge, a button, the luminance
  chart's own traces — while the readings themselves keep the plain text
  colour. A title with no poster looks exactly as it does on the plain dark
  theme; there was nothing to take a colour from. While this theme is on, the
  menu also carries how strongly it tints: **subtle**, **standard** or
  **strong**.
- **Midnight** — deeper and bluer, for a room with nothing else lit in it.

The choice is remembered in the browser, per device, and is applied before the
page is first drawn, so reopening the dashboard never flashes the wrong theme.
Both windows share it, and the phone's own status bar follows it. Nothing is
sent to the add-on: the theme is the browser's business, not the box's.

### The Dolby Vision metadata window

On a Dolby Vision title the dashboard shows a **Dolby Vision metadata view**
button. It opens a second window — `http://<box-ip>:8099/metadata`, which can
also be bookmarked on its own — listing every block the stream's side data
carries: the configuration record, the RPU from its header through L255, the
composer's reshaping curves, the trim passes and the static SEIs. It is the
same list the on-screen view shows,
built from the same rows, and it stays live: the per-frame blocks move with the
picture and a reading that just changed is highlighted, exactly as in the
overlay. On a wide screen it flows into two or three columns, never breaking a
section across them, and **Copy report** hands the whole list over as plain
text.

The button appears only where there is something to open. On any other source
the window says so rather than sitting empty.

It can be turned off entirely under **Settings → Dashboard** — it is the
largest thing the add-on sends, so on a slow network it is the first thing to
switch off.

### Switching VS10 from the browser

With **Allow VS10 switching from the dashboard** on (the default), the page
shows the output modes that apply to the playing source — the same set the
on-screen VS10 dialog offers, SDR sources included — and a tap applies one.
The switch is handed to the add-on's own `run_mode` entry point, so it takes
exactly the path a keymap shortcut takes, native VS10 actions included.

**HDR10+** and **HLG** are the two sources with no modes: neither is a VS10
input, so the driver has no group for either and the on-screen dialog draws
none — both are left with the player-process button alone. The dashboard
follows, and hides the whole VS10 card — output line included — for the length
of an HDR10+ or HLG stream. HDR10 keeps its three.

Switching **always** requires the access token, whatever reading is set to.

### The remote

The same setting turns on the transport row under the progress bar: play and
pause, ten seconds and a minute either way, stop, the volume and its mute, and
a picker each for the audio track and the subtitles. Tapping the progress bar
itself seeks there, and the arrow keys nudge it ten seconds when it has the
focus.

Every one of them goes through Kodi's own JSON-RPC into the running player, and
the page only offers what the player actually reports — a file with one audio
track shows no audio picker. Like the VS10 buttons, they need the access token,
and with **Allow VS10 switching from the dashboard** off the row is not drawn
at all.

Both the remote and the panels above it are on the metadata window too, so a
second screen left on either page can still be used to drive playback.

### Security

The dashboard is reachable by anything on the same network while it is on, so:

- It is **off by default** and has to be switched on deliberately.
- **Do not forward its port to the internet.** It is meant for a home network.
- The **access token** is required for every VS10 switch. Turn on **Require the
  token for reading too** if the network the box is on is shared — the page
  then asks for the token before it shows anything at all.
- **Generate a new token** replaces it and logs out every browser still holding
  the old one.
- The file name obeys the overlay's own *Show file name* setting: with it off,
  the path is not sent to the browser either.
- Only a fixed set of routes is served — no path is ever resolved against the
  filesystem.

Leave port 8080 alone; Kodi's own web server usually has it. 8099 is the
default here.

---

## Advanced Launch Arguments

TinyPPI supports additional arguments to open specific modes or apply VS10 output modes directly — without opening the overlay or the dialog first.

### Open the VS10 mode selection dialog

```
RunScript(script.tinyppi,dialog)
```

Opens the VS10 mode selection dialog instead of the main TinyPPI overlay.
It shows the modes that apply to the playing source; on an **HDR10+** or
an **HLG** stream — neither of which is a VS10 input — it draws no modes at
all and leaves the player-process button on its own.

### Apply a VS10 output mode directly

Use `run_mode` followed by the mode name to switch the VS10 output mode immediately. This is useful for keymap shortcuts or automation from other addons.

```
RunScript(script.tinyppi,run_mode,sdr8)
RunScript(script.tinyppi,run_mode,sdr10)
RunScript(script.tinyppi,run_mode,hdr10)
RunScript(script.tinyppi,run_mode,dv)
RunScript(script.tinyppi,run_mode,original_sdr)
RunScript(script.tinyppi,run_mode,original_hdr)
RunScript(script.tinyppi,run_mode,original_dv)
```

| Mode | Description |
|------|-------------|
| `original_sdr` | Pass through SDR content unchanged |
| `original_hdr` | Pass through HDR10 content unchanged |
| `original_dv` | Pass through Dolby Vision content unchanged |
| `hdr10` | Convert to HDR10 output |
| `dv` | Convert to Dolby Vision output |
| `sdr8` | Convert to SDR 8-bit output |
| `sdr10` | Convert to SDR 10-bit output |

#### Example: keymap shortcut for a direct mode switch

```xml
<keymap>
  <global>
    <keyboard>
      <xxxxx>RunScript(script.tinyppi,run_mode,hdr10)</xxxxx>
    </keyboard>
  </global>
</keymap>
```

#### Example: trigger from another addon (Python)

```python
import xbmc
xbmc.executebuiltin('RunScript(script.tinyppi,run_mode,dv)')
```

---

## Credits

TinyPPI builds on the work of the following projects — many thanks to their authors and contributors.

### script.module.sidedata

[**script.module.sidedata**](https://github.com/matthane/script.module.sidedata) by [matthane](https://github.com/matthane)

Parsers for the raw Dolby Vision and HDR payloads CoreELEC 22 publishes through
`Player.Process(video.sidedata)` — the Dolby Vision RPU and dvcC/dvvC
configuration record, the HDR10+ ST 2094-40 metadata and the static MDCV / CLL
SEIs. TinyPPI reads every DV/HDR value it shows through this module, so the
overlay follows the stream frame by frame instead of probing the file. RPU
parsing is done by quietvoid's [dovi_tool](https://github.com/quietvoid/dovi_tool)
(libdovi), HDR10+ parsing by FFmpeg's libavutil.

