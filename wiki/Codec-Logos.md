# Codec Logos

TinyPPI can show the **video (HDR) format** and the **audio format** of the
playing title as a stack of logos directly on the picture, on a rounded panel
whose colors, size and position are all configurable. The logos are
re-resolved live: switch the audio track and the audio logo changes with it.

---

## When the logos appear

There are three independent situations, each switched on separately under
**Settings → Codec logos**, and each with its **own** copy of every setting
below (position, size, order, colors):

| Situation | Master switch | Default | Shown |
|---|---|---|---|
| **On playback start** | **Show codec logos on playback start** | Off | For **Display duration** seconds (1–30, default 8) after a video starts. |
| **Video OSD** | **Show codec logos in the video OSD** | Off | Whenever the on-screen playback controls are visible. |
| **TinyPPI overlay** | **Show codec logos in the TinyPPI overlay** | Off | While the TinyPPI overlay is open (not the VS10 dialog or the metadata view). |

The logos are drawn as image controls inside Kodi's fullscreen video window
itself, not as a dialog on top of it, so the remote keeps controlling playback
while they are visible. They fade in and out.

The background service starts the logo controller on every playback start
(`Player.OnAVStart`) when at least one situation is enabled. Enabling one in
the middle of a video takes effect immediately as well.

---

## The logo stack

```
┌──────────────┐  ●  ← conversion dot (while VS10 converts)
│  DOLBY       │
│  VISION      │  ← video / HDR logo (output format)
│ ──────────── │  ← divider
│  DOLBY       │
│  ATMOS       │  ← audio logo
└────[ FEL ]───┘  ← Dolby Vision layer pill (bottom or top edge)
```

| Setting | Options | Effect |
|---|---|---|
| **Logo order** | *Video on top, audio below* (default) · *Audio on top, video below* | Which logo sits on top. |
| **Show video codec logo** | On (default) / Off | Turn off to show the audio logo alone. |
| **Show audio codec logo** | On (default) / Off | Turn off to show the video logo alone. |
| **Dolby Vision pill position** | *Bottom edge* (default) · *Top edge* | Which edge of the panel the layer pill sits on. |

Rules:

- With **both** logos switched on, the panel is all-or-nothing: an audio codec
  without a logo (see the list below) hides the whole panel rather than
  showing a lone video logo.
- A video **without any audio track** shows its video logo on its own.
- The **video logo follows the HDMI output**, read from the Amlogic driver: a
  Dolby Vision title converted to SDR by VS10 shows the SDR logo, with the
  **conversion dot** in the panel's top-right corner telling you a conversion
  is active.
- The **Dolby Vision pill** appears whenever the output is Dolby Vision:
  **FEL** (forest green) or **MEL** (tangerine) for a source with that
  enhancement layer, and a neutral pill (white at 20 %) for any other profile
  or a non-Dolby-Vision source converted to Dolby Vision.
- For a film recognised as **IMAX** (see [IMAX Detection](IMAX-Detection)) the
  HDR10, HDR10+ and Dolby Vision logos are replaced by their combined IMAX
  versions.
- The logos wait for the output to settle at playback start, so they do not
  flash the wrong format while the TV is still switching.

---

## Position and size

| Setting | Range | Default |
|---|---|---|
| **Horizontal offset** | 0 % (left edge) … 100 % (right edge) | 0 % |
| **Vertical offset** | 0 % (top edge) … 100 % (bottom edge) | 0 % |
| **Size (%)** | 80 … 130 | 100 |

With the defaults the panel sits in the **top-left** corner, inset from the
edges. Move it to the top-right with *Horizontal offset* = 100 %. The offsets
are kept when the size changes, and the panel never touches the screen edge.

Logo images are scaled down to their exact on-screen size once (a box filter
in premultiplied alpha, which looks noticeably cleaner than Kodi's own
resampling) and cached in `addon_data/script.tinyppi/scaled_images/`. The cache
survives restarts and updates and is tidied automatically.

---

## Colors

Each situation has its own colors, each with an opacity slider:

| Element | Default | Opacity |
|---|---|---|
| **Background color** (panel) | Charcoal | 98 % |
| **Video logo** | White | 100 % |
| **Audio logo** | White | 100 % |
| **Divider** | White | 35 % |
| **Conversion indicator** (dot) | Forest | 100 % |
| **FEL indicator** (pill) | Forest | 100 % |
| **MEL indicator** (pill) | Tangerine | 100 % |
| **Other Dolby Vision** (pill) | White | 20 % |

The logos are white artwork tinted with the chosen color, so a color applies
cleanly to any logo. See [Colors and Themes](Colors-and-Themes).

---

## Supported formats

### Video / HDR

| Logo | Format | IMAX variant |
|---|---|---|
| SDR | Standard Dynamic Range | — |
| HDR10 | HDR10 | HDR10 + IMAX |
| HDR10+ | HDR10+ | HDR10+ + IMAX |
| HLG | Hybrid Log-Gamma | — |
| Dolby Vision | Dolby Vision | Dolby Vision + IMAX |

### Audio

| Logo | Format | Kodi codec id(s) |
|---|---|---|
| AAC | AAC | `aac` |
| AAC-LC | AAC Low Complexity | `aac_lc` |
| AAC LATM | AAC in LATM/LOAS | `aac_latm` |
| AAC-LTP | AAC Long Term Prediction | `aac_ltp` |
| AAC-SSR | AAC Scalable Sample Rate | `aac_ssr` |
| HE-AAC | High-Efficiency AAC | `he_aac` |
| HE-AAC v2 | High-Efficiency AAC v2 | `he_aac_v2` |
| Dolby Digital | Dolby Digital (AC-3) | `ac3`, `dolbydigital` |
| Dolby Digital Plus | Dolby Digital Plus (E-AC-3) | `eac3` |
| Dolby Digital Plus Atmos | DD+ with Dolby Atmos | `eac3_ddp_atmos` |
| Dolby TrueHD | Dolby TrueHD | `truehd` |
| Dolby TrueHD Atmos | TrueHD with Dolby Atmos | `truehd_atmos` |
| DTS | DTS | `dts`, `dca` |
| DTS 96/24 | DTS 96/24 | `dts_96_24` |
| DTS-ES | DTS-ES | `dts_es` |
| DTS Express | DTS Express | `dts_express` |
| DTS-HD HRA | DTS-HD High Resolution Audio | `dtshd_hra` |
| DTS-HD MA | DTS-HD Master Audio | `dtshd_ma`, `dtshd` |
| DTS:X | DTS:X | `dtshd_ma_x` |
| IMAX | DTS:X IMAX Enhanced | `dtshd_ma_x_imax` |
| FLAC | FLAC | `flac` |
| PCM | PCM / LPCM | `pcm`, `pcm_bluray`, `pcm_s16le`, `pcm_s24le` |
| MP1 / MP2 / MP3 | MPEG audio | `mp1`, `mp2`, `mp3`, `mp3float` |
| OGG | Ogg Vorbis | `ogg` |
| OPUS | Opus | `opus` |
| VORBIS | Vorbis | `vorbis` |

Codecs without a logo — ALAC, WAV, WavPack, APE, WMA, AIFF and anything
unlisted — show no audio logo.

> The Dolby, DTS and IMAX logos are trademarks of their respective owners and
> are used only to identify the format a stream carries.
