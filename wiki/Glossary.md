# Glossary

Terms that appear in TinyPPI's overlay, settings and this wiki.

| Term | Meaning |
|---|---|
| **Amlogic** | The SoC maker whose chips power most CoreELEC boxes. TinyPPI reads the Amlogic video driver for display mode, pixel format and EOTF, and writes its Dolby Vision driver for VS10. |
| **Aspect ratio (visible)** | The ratio of the picture inside the black bars, computed from L5 offsets — unlike Kodi's value, which describes the coded frame. |
| **BL** | *Base layer* — the backward-compatible video layer of a Dolby Vision stream (HDR10, SDR or none). |
| **CLL / MaxCLL** | *Maximum Content Light Level* — the brightest pixel of the whole title, in cd/m². |
| **CM version** | *Content Mapping* version of the Dolby Vision display-management metadata: **CMv2.9** or **CMv4.0** (which adds L3, L8–L11). |
| **Composer** | The part of the RPU that tells the decoder how to reshape the base layer (and combine the enhancement layer) into the Dolby Vision picture. |
| **CoreELEC** | A Kodi-centric Linux distribution for Amlogic devices. TinyPPI needs version 22 or later. |
| **dvcC / dvvC** | The Dolby Vision *configuration record* in the container: version, profile, level, and which layers are present. |
| **DM compression** | Dolby Vision metadata compression: most frames omit unchanged blocks (L2, L8 …); TinyPPI holds the last one and marks it *Cached*. |
| **DT-DL / ST-DL / ST-SL** | Dolby Vision layer structures: *dual track dual layer*, *single track dual layer*, *single track single layer*. |
| **Effective HDR type** | The HDR type the overlay layout follows; differs from the source type during a VS10 conversion when the *Converted output* settings say so. |
| **EL** | *Enhancement layer* of a dual-layer Dolby Vision stream (profile 7). |
| **EOTF** | *Electro-Optical Transfer Function* — the transfer curve signalled to the display (SDR gamma, PQ for HDR10/DV, HLG). Shown as **Mode**. |
| **FALL / MaxFALL** | *Maximum Frame-Average Light Level* — the brightest frame average of the title, in cd/m². |
| **FEL** | *Full enhancement layer* — a profile 7 EL carrying real picture data; reconstructs a 12-bit picture. |
| **HDR10** | HDR with static metadata (MDCV, CLL) and the PQ transfer. |
| **HDR10+** | HDR with dynamic metadata (SMPTE ST 2094-40). Not a VS10 input. |
| **HLG** | *Hybrid Log-Gamma* — broadcast HDR without metadata. Not a VS10 input. |
| **Home window property** | A named value on Kodi's Home window (id 10000). TinyPPI publishes state and colors there for its skin files. |
| **IMAX Enhanced** | A certification for releases with IMAX's expanded aspect ratio and DTS:X IMAX audio. |
| **IPT / tunnelled IPT** | Dolby Vision output formats: IPT for *Player-LED*, IPT tunnelled in an 8-bit RGB link for *TV-LED* ("DV Tunnel"). |
| **L1** | RPU block with the frame's min / max / average luminance (PQ). Changes every scene. |
| **L2 / L8** | Trim passes: how the grade is adjusted for a target display (slope, offset, power, chroma, saturation …). L8 is the CMv4.0 version. |
| **L3** | PQ offsets to L1 (CMv4.0). |
| **L4** | Temporal stability metadata. |
| **L5** | Active area — the black bars (left, right, top, bottom offsets). |
| **L6** | Mastering display and MaxCLL/MaxFALL as carried in the RPU. |
| **L9 / L10** | Source primaries / target display definitions (CMv4.0). |
| **L11** | Content type, white point and reference mode. |
| **L254 / L255** | CMv4.0 marker block / debug run-mode block. |
| **MDCV / MDL** | *Mastering Display Colour Volume* — primaries and min/max luminance of the mastering display. TinyPPI shows the luminance as **MDL**. |
| **MEL** | *Minimal enhancement layer* — a profile 7 EL with (almost) no picture data. |
| **NLQ** | *Non-linear quantization* data the composer uses to merge the EL on dual-layer profiles. |
| **nits / cd/m²** | Units of luminance; 1 nit = 1 cd/m². |
| **Passthrough** | Audio sent to the receiver as an untouched bitstream. |
| **Player-LED / TV-LED** | Where Dolby Vision tone mapping happens: in the player (Player-LED, low-latency) or in the TV (TV-LED, the default). |
| **PPI** | *Player Process Info* — Kodi's name for its playback information view. |
| **PQ** | *Perceptual Quantizer* (SMPTE ST 2084) — the HDR10/Dolby Vision transfer curve. Raw PQ codes are 12-bit (0–4095). |
| **Profile** | Dolby Vision profile and compatibility ID, e.g. `5` (IPT single layer), `7.6` (dual layer, HDR10 BL), `8.1` (single layer, HDR10 BL), `8.4` (HLG BL). |
| **RPU** | *Reference Processing Unit* — the per-frame Dolby Vision metadata. |
| **SEI** | *Supplemental Enhancement Information* — metadata messages inside the video stream (MDCV, CLL, HDR10+). |
| **Side data** | The raw metadata payloads of the frame being decoded, published by CoreELEC 22 as `Player.Process(video.sidedata)`. |
| **Splash** | TinyPPI's internal name for the [codec logos](Codec-Logos). |
| **SSE** | *Server-Sent Events* — the one-way HTTP stream the dashboard uses for live updates. |
| **VS10** | Dolby's video engine in Dolby Vision-capable Amlogic chips; converts between SDR, HDR10 and Dolby Vision output. |
