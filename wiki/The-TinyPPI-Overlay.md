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
| **Aspect ratio** | `2.39:1 (IMAX)` | The aspect ratio of the **visible picture**. Kodi reports the coded frame (a letterboxed 2.39 film reads 1.78); when the Dolby Vision RPU declares the black bars (L5), TinyPPI computes the ratio inside them and snaps it to the nearest standard ratio within 2 %. Detail: `IMAX` or `IMAX Enhanced` for a recognised film (see [IMAX Detection](IMAX-Detection)). |
| **Decoder** | `AML-H.265 (HW)` | Decoder family (`AML-` Amlogic hardware decoder, `FF-` FFmpeg) and codec, with `HW`/`SW` as detail. |
| **Decode method** | `Hardware` | Whether the video is decoded in hardware or software. |

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
| **L5 Active Area** | `0 l 0 l 276 l 276` | The active-area offsets (left, right, top, bottom) the RPU declares — the black bars. With **Show L5 offsets icon** on, an `lrtb` icon marks the order. Changes on IMAX titles whose framing opens up. |

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

All readings of one refresh are taken in a single pass, and a window property
is only written when its value actually changed, so an idle refresh costs
almost nothing. If a refresh fails it is logged once and retried on the next
tick; the overlay never freezes on a stale picture.
