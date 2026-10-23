# Channel Layout Graphic

TinyPPI can draw a **speaker layout** for the current audio track inside the
overlay: the full speaker arrangement is drawn dimmed, and the positions the
track actually carries light up. A 5.1 track lights its six positions while the
remaining slots stay dark.

---

## Switching it on

The graphic is enabled per **output type** under **Settings → Channels**, all
off by default:

| Setting | Shows the graphic while playing |
|---|---|
| **Channels in SDR** | SDR content |
| **Channels in HDR10 / HLG / HDR10+** | HDR10, HLG or HDR10+ content |
| **Channels in Dolby Vision** | Dolby Vision content |

The type is the one the overlay layout follows, so during a VS10 conversion
the *Converted output* settings decide which switch applies (see
[The TinyPPI Overlay](The-TinyPPI-Overlay#the-overlay-during-a-vs10-conversion)).
The switches are re-read on every refresh, so a change applies to an overlay
that is already open.

---

## Where it is drawn

| Output | Placement |
|---|---|
| **SDR** | The overlay switches to its wide box, with the speaker layout on the right. |
| **HDR10 / HLG / HDR10+** | On the right of the wide box, next to the HDR Static Metadata panel. |
| **Dolby Vision** | In a **panel of its own above the main box**, because the Dolby Vision and Metadata panels already fill the right side. **Horizontal offset of the channel box** slides that panel from its default position on the right (100 %) to the left edge (0 %). |

The graphics ship pre-scaled for both box sizes (495 × 298 and 400 × 241), so
Kodi never resamples them.

---

## Supported layouts

| Graphic | Layout | Channels |
|---|---|---|
| 1.0 | Mono | 1 |
| 2.0 | Stereo | 2 |
| 2.1 | Stereo + LFE | 3 |
| 3.1 | 3.1 surround | 4 |
| 4.1 | 4.1 surround | 5 |
| 5.1 | 5.1 surround | 6 |
| 5.1.2 | 5.1 with two height channels | 6 (Atmos / DTS:X) |
| 6.1 | 6.1 surround | 7 |
| 7.1 | 7.1 surround | 8 |
| 7.1.2 | 7.1 with two height channels | 8 (Atmos / DTS:X) |

Kodi reports only a **channel count**, so the height variants are inferred from
the codec: for **Dolby TrueHD Atmos**, **Dolby Digital Plus Atmos**, **DTS:X**
and **DTS:X IMAX Enhanced**, six channels are drawn as 5.1.2 and eight as
7.1.2. Channel counts without a matching graphic simply show no image.

---

## Colors

Under **Settings → Channels**, each with its own opacity:

| Setting | Default | What it colors |
|---|---|---|
| **Background** | Charcoal, 98 % | The box behind the graphic in Dolby Vision (the separate panel). |
| **Layout** | White, 33 % | The full speaker arrangement behind the active channels. |
| **Channels** | White, 100 % | The active channels. |

The palette for **Layout** and **Channels** starts with pure white, the
untinted look of the artwork. See [Colors and Themes](Colors-and-Themes).

---

## Related

- The **Input** row of the overlay's Audio panel names the same positions as
  text (`FL, FR, FC, LFE, BL, BR, SL, SR`).
- The **Audio codec** row shows the layout as a number (`7.1`) and the
  `(Atmos)` / `(IMAX Enhanced)` detail.
