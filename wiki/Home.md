<p align="center">
  <img width="900" alt="TinyPPI" src="https://raw.githubusercontent.com/CE-Repo/script.tinyppi/main/fanart.png" />
</p>

# TinyPPI Wiki

**TinyPPI** (`script.tinyppi`) is a Kodi add-on for **CoreELEC** that shows
detailed, live playback information in its own overlay window while a video
plays. It reads what the player, the Amlogic video driver and the stream's own
side data report — video, audio, HDR10, HDR10+, HLG and **Dolby Vision**
metadata, system load and more — and draws it over the picture without
interrupting playback.

Around that overlay it adds a VS10 output-mode switcher, codec logos on the
picture, a speaker-layout graphic, a full Dolby Vision metadata debugger and a
**web dashboard** that mirrors everything to a phone or laptop on the same
network.

> **Current version:** 2.15.1 · **Platform:** CoreELEC 22 or later (Kodi 22, Amlogic) ·
> **License:** AGPL-3.0-or-later

---

## Feature overview

| Feature | What it does | Page |
|---|---|---|
| **TinyPPI overlay** | Live player-process information over fullscreen video: display mode, resolution, pixel format, bit depth, aspect ratio, decoder, VS10 conversion, bitrate, media source, audio codec and layout, languages, CPU, temperature, memory, caches, HDR10 static metadata and Dolby Vision metadata | [The TinyPPI Overlay](The-TinyPPI-Overlay) |
| **Dolby Vision metadata view** | A live debug list of every block the Dolby Vision side data carries — configuration record, RPU header, composer, L1 to L255, static SEIs, HDR10+ | [Dolby Vision Metadata View](Dolby-Vision-Metadata-View) |
| **VS10 dialog** | Switch the Amlogic VS10 engine's output (original, SDR, HDR10, Dolby Vision) for the playing title, in one of three dialog layouts | [VS10 Output Modes](VS10-Output-Modes) |
| **Codec logos** | Video/HDR and audio format logos stacked on the picture on playback start, in the video OSD or alongside the overlay | [Codec Logos](Codec-Logos) |
| **Channel layout graphic** | A speaker diagram that lights up the channels the audio track carries (1.0 to 7.1.2) | [Channel Layout Graphic](Channel-Layout-Graphic) |
| **IMAX detection** | Marks IMAX and IMAX Enhanced films by name, from a curated title list and your own additions | [IMAX Detection](IMAX-Detection) |
| **Themes and colors** | Every color and opacity of every view is configurable through Kodi's color picker or a HEX code | [Colors and Themes](Colors-and-Themes) |
| **Web dashboard** | All readings, a live luminance chart, events, a remote, VS10 switching and the film/series library in the browser | [Web Dashboard](Web-Dashboard) |

---

## Where to start

- **New here?** → [Installation](Installation), then [Getting Started](Getting-Started).
- **Want a remote button for it?** → [Launching and Keymaps](Launching-and-Keymaps).
- **What does a row in the overlay mean?** → [The TinyPPI Overlay](The-TinyPPI-Overlay).
- **Looking for one particular setting?** → [Settings Reference](Settings-Reference).
- **Something does not work?** → [Troubleshooting](Troubleshooting) and the [FAQ](FAQ).
- **Want to automate it or build on it?** → [Dashboard HTTP API](Dashboard-HTTP-API),
  [Architecture](Architecture) and [Development and Testing](Development-and-Testing).

---

## All pages

**User guide**

1. [Installation](Installation)
2. [Getting Started](Getting-Started)
3. [Launching and Keymaps](Launching-and-Keymaps)
4. [The TinyPPI Overlay](The-TinyPPI-Overlay)
5. [Dolby Vision Metadata View](Dolby-Vision-Metadata-View)
6. [VS10 Output Modes](VS10-Output-Modes)
7. [Codec Logos](Codec-Logos)
8. [Channel Layout Graphic](Channel-Layout-Graphic)
9. [IMAX Detection](IMAX-Detection)
10. [Colors and Themes](Colors-and-Themes)

**Web dashboard**

11. [Web Dashboard](Web-Dashboard)
12. [Dashboard Security](Dashboard-Security)
13. [Dashboard HTTP API](Dashboard-HTTP-API)

**Reference**

14. [Settings Reference](Settings-Reference)
15. [Troubleshooting](Troubleshooting)
16. [FAQ](FAQ)
17. [Glossary](Glossary)

**For developers**

18. [Architecture](Architecture)
19. [Development and Testing](Development-and-Testing)
20. [Translations](Translations)

**Project**

21. [License and Credits](License-and-Credits)

---

## Screenshots

| Overlay (no conversion) | Overlay (VS10 conversion) | VS10 dialog |
|---|---|---|
| ![No convert](https://github.com/user-attachments/assets/b083e2b2-bff2-40de-bdc4-361688e4df5c) | ![Convert](https://github.com/user-attachments/assets/0260625f-7d2e-4bf8-b07c-10547dfc0956) | ![VS10 dialog](https://github.com/user-attachments/assets/d0a005fb-62bf-4277-93ee-4358f61cb172) |

---

## Links

- Source code: <https://github.com/CE-Repo/script.tinyppi>
- Add-on repository: <https://ce-repo.github.io/repository.jamal2362/>
- Dolby Vision / HDR parser: [script.module.sidedata](https://github.com/matthane/script.module.sidedata)
