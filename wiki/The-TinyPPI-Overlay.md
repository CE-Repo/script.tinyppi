# The TinyPPI Overlay

The overlay is TinyPPI's main view: a panel over the fullscreen picture that
lists what the player, the Amlogic driver and the stream's side data report,
refreshed ten times a second.

![Overlay](https://github.com/user-attachments/assets/b083e2b2-bff2-40de-bdc4-361688e4df5c)

---

## Contents

- [Opening, closing and keys](#opening-closing-and-keys)
- [Layouts](#layouts)
- [Panel: Video](#panel-video)
- [Panel: Processing](#panel-processing)
- [Panel: Audio](#panel-audio)
- [Panel: System](#panel-system)
- [Panel: HDR Static Metadata](#panel-hdr-static-metadata)
- [Panel: Dolby Vision](#panel-dolby-vision)
- [Panel: Metadata](#panel-metadata)
- [Highlighted values](#highlighted-values)
- [N/A and empty values](#na-and-empty-values)
- [The overlay during a VS10 conversion](#the-overlay-during-a-vs10-conversion)
- [Position](#position)
- [Header, file name and background](#header-file-name-and-background)
- [How often values are read](#how-often-values-are-read)

---

## Opening, closing and keys

The overlay opens from a key or remote button during **fullscreen video
playback** (see [Launching and Keymaps](Launching-and-Keymaps)).

| Key | Action |
|---|---|
| **Back**, **Esc** | Close TinyPPI. |
| **OK** | On a Dolby Vision source with **Settings → DV metadata → Dolby Vision metadata view** on: switch to the [Dolby Vision metadata view](Dolby-Vision-Metadata-View). Otherwise nothing. |
| **Arrows** | With **Settings → General → Move with the arrow keys** on: move the overlay 10 px per press (kept on screen, not saved). Otherwise nothing. |
| **Launch key again** | Close TinyPPI (toggle). |

The overlay closes by itself when:

- playback stops,
- the fullscreen video window is left,
- **Settings → General → Auto-hide** is set (1–30 s) and that time has passed.

Key presses in the first 0.3 s after opening are ignored, so the press that
opened the overlay never closes it again.

---

## Layouts

The panel's shape follows the source:

| Source | Layout |
|---|---|
| **SDR**, no channel graphic | A narrow box on the left: Video · Processing · Audio · System. |
| **SDR** with the [channel graphic](Channel-Layout-Graphic) | The wide box, with the speaker layout on the right. |
| **HDR10 / HDR10+ / HLG** | The wide box, with the **HDR Static Metadata** panel (and the channel graphic, if enabled) on the right. |
| **Dolby Vision** | The wide box with the **Dolby Vision** and **Metadata** panels on the right. With the channel graphic on, the speaker layout gets a separate panel *above* the main box. |

The HDR type is detected while the overlay is already open, so on the first
frames of a title the layout may switch once from SDR to the right one.

---

## Panel: Video

| Row | Example | Source and meaning |
|---|---|---|
| **Display output** | `2160p 23.976Hz` | The HDMI output mode the Amlogic driver is sending (`Player.Process(amlogic.displaymode)`). |
| **Video stream** | `3840x2160p 23.976FPS` | The decoded stream: width × height, scan type and frame rate. |
| **Pixel format** | `10-bit (YUV 4:2:2)` | The output pixel format of the Amlogic video path (`amlogic.pixformat`). The detail `(DV Tunnel)` appears when the Dolby Vision driver runs tunnelled IPT (`dolby_vision_mode` = 1) over an 8-bit RGB link — the TV-LED Dolby Vision carriage. |
| **Bit depth** | `12-bit` | The *source* bit depth: 12-bit for a Dolby Vision full enhancement layer (FEL), 10-bit for any other HDR format, 8-bit for SDR. |
| **Aspect ratio** | `2.39:1 (IMAX)` | The aspect ratio of the **visible picture**. Kodi reports the coded frame (a letterboxed 2.39 film reads 1.78); TinyPPI computes the ratio inside the black bars and snaps it to the nearest standard ratio within 2 %. The bars come from the Dolby Vision RPU (L5), or, with **Measure the aspect ratio from the picture** on, from the picture itself for every format (see [Measured aspect ratio](#measured-aspect-ratio)). Detail: the format's common name when the ratio is a standard one — `4:3` (1.33), `Academy` (1.37), `European widescreen` (1.66), `16:9` (1.78), `Cinema widescreen` (1.85), `Univisium` (2.00), `70 mm` (2.20), `Scope` (2.35 and 2.39), `CinemaScope` (2.55), `Ultra Panavision` (2.76) — or, in its place, `IMAX` or `IMAX Enhanced` for a recognised film (see [IMAX Detection](IMAX-Detection)), lit in the *Changed values* color [while an IMAX scene plays](#the-imax-mark-during-an-imax-scene). |
| **Decoder** | `AML-H.265 (HW)` | Decoder family (`AML-` Amlogic hardware decoder, `FF-` FFmpeg) and codec, with `HW`/`SW` as detail. |
| **Decode method** | `Hardware` | Whether the video is decoded in hardware or software. |

### Measured aspect ratio

Dolby Vision declares its black bars in the RPU (L5). Everything else —
HDR10, HDR10+, HLG, SDR — carries no such information, so a letterboxed film
reads as its 16:9 frame. TinyPPI therefore finds the bars in the picture
itself, **for every format, Dolby Vision with L5 included**. This is always
on and has no setting:

- A small frame of the video (480 pixels wide, without OSD, subtitles or the
  overlay) is captured **twenty times a second, all through playback**, whether or
  not the overlay is open.
- A frame only counts when the picture's edges are plainly lit and the bars
  on both sides are the same size. The bars of one axis are enough: a
  scene that is dark on one side still shows its bars above and below, as
  long as the picture is seen across three quarters of the width.
  **Three frames in a row** have to agree
  before the reading changes, so a change of framing shows after about a
  sixth of a second.
- **A framing the title has shown before returns on less proof.** A film
  with IMAX scenes keeps going back to the same bars. Once they have been
  confirmed, a later frame shows them again when they are black and the
  picture is lit right at *one* of them — a shot with a dark top or bottom
  no longer holds the change back.
- **After a taller picture, black where the bars were is enough.** While an
  IMAX scene fills the frame and a later frame shows picture but nothing
  where the title's previous bars were, the reading goes back to that
  previous framing. A dark IMAX shot that leaves those areas black
  therefore reads as the regular framing until something lights them again;
  a completely black frame changes nothing.
- **Bars a captured line apart are shown as equal.** The picture is centred,
  so a bar edge that falls inside a line of the small capture (276 rows of a
  UHD film are 34.5 lines) is split evenly: `0 | 0 | 276 | 276`, not
  `0 | 0 | 280 | 272`.
- **A title card, a logo or credits on black are not a picture.** Lit
  content with black on all four sides is ignored (a film is letterboxed or
  pillarboxed, not both), and so is a band no film is shaped like (wider
  than about 2.85:1 or narrower than 1.15:1).
- **Only ratios films are made in count**: the full frame, or bars that
  leave 1.33, 1.37, 1.43, 1.66, 1.78, 1.85, 1.90, 2.00, 2.20, 2.35, 2.39,
  2.55 or 2.76:1 (within 2 %). Anything else — 2.62:1, say — is ignored
  however long it lasts, and the last confirmed value stands.
- **A title that opens on black** is measured from its black: a bar is one
  flat value, while a film's black usually carries grain or sits a little
  above it. Until a title has its first confirmed bars, a dark frame whose
  outermost lines are flat counts too, if it makes a standard film ratio
  and lasts a second. Where the film's black is as flat as its bars, the
  reading still waits for the first bright scene.
- Later on, **a dark scene proves nothing**: black bars cannot be told from dark
  picture. The last confirmed value stands until a brighter frame confirms
  or replaces it — the reading holds rather than guesses. The same goes for a
  subtitle burned into a bar.
- The measured bars come first, ahead of L5. Until bright frames have
  confirmed them — at the start of a title — the row shows the ratio from
  L5 where there is one, and Kodi's otherwise.
- In Dolby Vision this means that a change of framing during a dark scene
  shows only once a brighter frame confirms it, where L5 alone would show
  it at once.

**This needs a CoreELEC build that can capture the video** from the Amlogic
video layer — at the time of writing the
[canary builds](https://github.com/ce-canary/canary). On any other build the
add-on notices once per session that no capture is available, logs
`this Kodi build cannot capture the video`, and the row shows the ratio
from L5 where present, Kodi's otherwise.

The active-area row prefers L5: bars the RPU declares are always shown as
**L5 Active Area**. Only where L5 is `0 | 0 | 0 | 0`, and with **Measure the
active area from the picture** on (the default), the row reads **Active Area**
and shows the measured bars; without a measurement (another build, or nothing
confirmed yet) or with the setting off it stays **L5 Active Area**. The
letterbox on the web dashboard does the same.

---

## Panel: Processing

| Row | Example | Source and meaning |
|---|---|---|
| **Input** | `Dolby Vision Profile 7.6 FEL` | The source format. Dolby Vision shows its profile and compatibility ID with an **FEL**/**MEL** tag (colored by the *FEL tag* / *MEL tag* colors); HDR10+ shows its profile (`HDR10+ Profile B`); otherwise `HDR10`, `HLG` or `SDR`. |
| **Converting** | ✔ `→  HDR10` / ✘ | Whether the VS10 engine is converting the source right now, and to what (`→ DV Profile 8.1`, `→ HDR10`, `→ SDR`). Green check = conversion active, red cross = passthrough. Read from the driver's EOTF field, so it is correct whether the switch came from TinyPPI, a keymap or CoreELEC's own settings. |
| **Bitrate** | `48.3 Mb/s (52.1)` | Average video bitrate, with the live bitrate as detail. |
| **Mode** | `DV` / `HDR10` / `SDR` | First field of `amlogic.eoft_gamut`: the transfer the HDMI output is signalling. |
| **Color gamut** | `BT2020` | Second field of `amlogic.eoft_gamut`: the color space signalled to the display. |
| **Media source** | `Remux · MKV · 42GB` | Where the video comes from — release type (`Remux`, `UHD BD`, `BD`, `WEB-DL`, `WEBRip`, `WEB`, `HDTV`, `DVD`, read from the file and folder name), container and file size. For live TV and streams it names the transport (`PVR`, `HLS`, `DASH`, `RTMP`, `RTSP`) or the protocol (`HTTP`, `SMB`, `NFS`). Add-on streams are never probed for their size. |
| **Playback time** | `01:12:44 / 02:28:03 (49%)` | Position, duration and progress. For live TV and radio it follows the current EPG event (elapsed / duration / progress); without EPG data it reads **Live TV**. An internet stream without a duration reads **Livestream**. |

---

## Panel: Audio

| Row | Example | Source and meaning |
|---|---|---|
| **Audio codec** | `Dolby TrueHD 7.1 (Atmos)` | Codec name and channel layout. The detail is `(Atmos)` for TrueHD/DD+ Atmos and `(IMAX Enhanced)` for DTS:X IMAX. |
| **Audio resolution** | `24-bit / 48 kHz` | Bit depth and sample rate of the track. |
| **Input** | `FL, FR, FC, LFE, BL, BR, SL, SR` | The speaker positions the track's channel count stands for. |
| **Output** | `Passthrough` | `Passthrough` when the bitstream goes to the receiver untouched; otherwise the channel layout of Kodi's audio sink, or `Decoding` when Kodi decodes without reporting a sink layout. |
| **Bitrate** | `3.4 Mb/s (4.1)` | Average audio bitrate with the live value as detail. |
| **Audio language** | `ger \| Deutsch` | Short code and native name of the selected audio track's language. |
| **Subtitle language** | `eng \| English (PGS)` | Short code, native name and format of the selected subtitle, or **Disabled**. |

---

## Panel: System

| Row | Example | Meaning |
|---|---|---|
| **In / drop / out** | `024 - 000 = 24 FPS` | Input frame rate, frames dropped by the video driver, and the resulting output rate. |
| **Processor** | `34% \| 12 \| 08 \| 15 \| 10` | Average CPU load, then the load of each core. |
| **Temperature** | `61 °C` + bar | CPU temperature with a bar scaled to 0–110 °C (32–230 °F). |
| **Memory usage** | `42%` + bar | System memory in use. |
| **Player cache** | `100%` + bar | How full Kodi's read-ahead cache is. |
| **Video queue / data** | `95% \| 60%` | Fill level of the video decoder queue (packets / data). |
| **Audio queue / data** | `90% \| 40%` | Fill level of the audio queue (packets / data). |

---

## Panel: HDR Static Metadata

Shown for HDR10, HDR10+ and HLG sources.

| Row | Example | Meaning |
|---|---|---|
| **HDR10 MDL** | `0.0001 l 1000 cd/m²` | Mastering display luminance (min / max) from the stream's MDCV SEI. |
| **HDR10 CLL/FALL** | `1046 l 312 cd/m²` | MaxCLL (brightest pixel) and MaxFALL (brightest frame average) from the CLL SEI. |

The unit follows **Settings → General → Brightness unit** (`cd/m²`, `nits` or
hidden). Multi-part values are separated by a small `l`, which reads better
than a pipe in the overlay's narrow font.

---

## Panel: Dolby Vision

Shown for Dolby Vision sources. Values come from the dvcC/dvvC configuration
record and the RPU.

| Row | Example | Meaning |
|---|---|---|
| **CM Version** | `CMv4.0` | The content-mapping version of the RPU's display-management data (`CMv2.9` or `CMv4.0`). |
| **Structure** | `DT-DL` | Layer structure: `ST-SL` single track single layer, `ST-DL` single track dual layer, `DT-DL` dual track dual layer. |
| **Version** | `1.0` | Version of the configuration record. |
| **Profile** | `7.6 FEL` | Dolby Vision profile and compatibility ID, with the enhancement-layer type tag. |
| **RPU / BL** | ✔ \| ✔ | Whether the stream carries an RPU and a base layer. |
| **EL / Type** | ✔ `(FEL)` | Whether it carries an enhancement layer, and its type: **FEL** (full enhancement layer, 12-bit reconstruction) or **MEL** (minimal enhancement layer). |

The values describe the **source as the file carries it**. CoreELEC captures
the side data before its own bitstream conversion (for example profile 7 → 8),
so a profile 7 FEL disc still reads as 7.6 FEL.

---

## Panel: Metadata

Shown for Dolby Vision sources, next to the Dolby Vision panel.

| Row | Example | Meaning |
|---|---|---|
| **HDR10 MDL** | `0.0001 l 1000 cd/m²` | The static mastering display of the HDR10 base layer (MDCV SEI). |
| **HDR10 CLL/FALL** | `1046 l 312 cd/m²` | The static MaxCLL / MaxFALL of the base layer (CLL SEI). |
| **RPU MDL** | `0.005 l 4000 cd/m²` | The mastering display as the RPU describes it: the source range when the RPU carries one, otherwise its L6 block (the label then reads **L6 MDL**). |
| **RPU MaxCLL/FALL** | `1000 l 400 cd/m²` | MaxCLL / MaxFALL from the RPU's L6 block (label **L6 MaxCLL/FALL**). |
| **L1 Lum Min/Max/Ø** | `0.01 l 812 l 96 cd/m²` | The current frame's minimum, maximum and average luminance (L1), converted to nits. Changes with every scene. |
| **L1 PQ Min/Max/Ø** | `62 l 3076 l 1795 12-bit` | The same L1 values as raw 12-bit PQ codes. |
| **Active Area** / **L5 Active Area** | `0 l 0 l 276 l 276` | The active-area offsets (left, right, top, bottom) — the black bars. **L5 Active Area**: what the RPU declares, always shown when it declares bars. **Active Area**: measured from the picture, only where L5 is all zeros (canary builds, **Measure the active area from the picture** on). With **Show L5 offsets icon** on, an `lrtb` icon marks the order. Changes on IMAX titles whose framing opens up. |

---

## Highlighted values

A reading that just changed is drawn in the **Changed values** color (light
blue by default) and stays in it for **Highlight duration** milliseconds
(750 ms by default, 100–3000 ms). The highlight applies to the Dolby Vision
and Metadata panels — CM version, structure, version, profile, L1, L5, RPU MDL,
L6 and the HDR10 rows inside the DV panel — where it separates the live,
per-frame readings from the static ones.

The readings themselves are polled every 100 ms whatever the highlight duration
is, so no change is missed; a short duration only makes it harder to see.

Both settings live under **Settings → TinyPPI overlay → Changed values**; the
metadata view has its own pair under **Settings → DV metadata**.

### The IMAX mark during an IMAX scene

The `(IMAX)` / `(IMAX Enhanced)` mark behind the aspect ratio uses the same
color, but not the duration: it is lit **for as long as an IMAX scene
lasts** and returns to the accent color when the film goes back to its
regular framing.

- TinyPPI follows the aspect ratio all through playback, overlay open or
  not, and remembers the **widest** one the title has shown for at least
  one second — the film's regular framing (2.39:1, say). A ratio that is
  not a standard film ratio has to last three seconds, so a stray reading
  during a fade or a studio logo is not taken for it.
- While the picture is clearly taller than that (1.78:1 or 1.90:1 against
  2.39:1), the mark is lit.
- A film that never changes its framing has no IMAX scene and the mark stays
  in the accent color. So does a film that opens with an IMAX scene, until
  it has shown its regular framing once.
- The aspect ratio comes from the [measured bars](#measured-aspect-ratio)
  or from L5; without either it never changes and the mark is never lit.
- The [web dashboard](Web-Dashboard) lights the mark in its **Aspect
  ratio** row the same way.

---

## N/A and empty values

- **N/A** means the reading exists for this kind of source but the player did
  not report it (for example the Dolby Vision fields before the first RPU has
  been parsed, or on a stream without side data).
- Panels that do not apply to the source are not drawn at all — there is no
  Dolby Vision panel for HDR10, and no HDR panel for SDR.
- On builds without `Player.Process(video.sidedata)` (anything but CoreELEC 22
  on Amlogic) every Dolby Vision/HDR field falls back to N/A.

---

## The overlay during a VS10 conversion

When the VS10 engine converts the picture, the overlay normally keeps the
**source** layout — a Dolby Vision title converted to SDR still shows its
Dolby Vision panels, because the side data still describes the Dolby Vision
stream. Two settings under **Settings → General → Converted output** change
that:

| Setting | Default | Turned off |
|---|---|---|
| **Keep the HDR/DV area when converting to SDR** | On | During a conversion to SDR the overlay uses the SDR layout. |
| **Keep the Dolby Vision area when converting to HDR10** | On | During Dolby Vision → HDR10 the HDR Static Metadata panel replaces the Dolby Vision panels. |

The **Converting** row and the [codec logos'](Codec-Logos) conversion dot show
the conversion either way.

---

## Position

| Setting | Effect |
|---|---|
| **Horizontal offset (SDR only)** | Moves the narrow SDR box to the right, up to about 31 % of the screen width. The wide layouts always stay at the left edge. |
| **Vertical offset** | Moves the overlay up, up to about 28 % of the screen height (less where the box would leave the screen). |
| **Move with the arrow keys** | Lets the arrows nudge the open overlay by 10 px per press. The nudge is clamped to the screen and forgotten on close. |
| **Horizontal offset of the channel box** *(Channels)* | Slides the separate Dolby Vision speaker panel from the right (100 %) to the left edge (0 %). |

---

## Header, file name and background

- The header shows Kodi's own *Player process info* label and a chart icon.
- **Settings → General → Show file name** adds the playing file's name under
  the header (colored by the *File name* color). The same setting decides
  whether the [web dashboard](Web-Dashboard) receives the path.
- **Global background** is a full-screen color laid over the picture behind
  the overlay — off (0 %) by default; raise it to dim the picture.
- **Background** is the panel itself (98 % by default). At **0 %** the header
  title, header icon and separator lines are hidden too, leaving only the
  readings floating on the picture.

Every color is listed in [Colors and Themes](Colors-and-Themes).

---

## How often values are read

| What | Interval |
|---|---|
| Scene readings (L1, L5, bitrates, FPS, queues, changed-value highlight, layout) | every 100 ms |
| Per-title facts and CPU statistics | every 1 s |
| Side data parsing | only when the payload changes, shared by all readers |
| Black bars measured from the picture | every 50 ms while a video plays, overlay open or not |

All readings of one refresh are taken in a single pass, and a window property
is only written when its value actually changed, so an idle refresh costs
almost nothing. If a refresh fails it is logged once and retried on the next
tick; the overlay never freezes on a stale picture.
