# Getting Started

A five-minute tour: open the overlay, read it, close it, and try the other
views.

---

## 1. Open the overlay

TinyPPI only opens while a **video is playing in fullscreen**. In any other
window a launch does nothing.

1. Start a film or an episode and let it go fullscreen.
2. Press the key or remote button you mapped to TinyPPI (see
   [Launching and Keymaps](Launching-and-Keymaps) — the Keymap Editor route
   takes a minute). The fullscreen video window has to be the active window
   when the key is pressed: started from the add-on browser, with the video
   running behind a menu, TinyPPI quietly does nothing.
3. The overlay appears over the lower left of the picture and refreshes ten
   times a second.

What opens is decided by **Settings → General → Launch mode**:
**TinyPPI** (the overlay, default) or **VS10 dialog**.

---

## 2. Read it

The overlay is grouped into panels. Which panels appear depends on the source:

| Source | Panels |
|---|---|
| **SDR** | Video · Processing · Audio · System |
| **HDR10 / HDR10+ / HLG** | the four above plus **HDR Static Metadata** |
| **Dolby Vision** | the four above plus **Dolby Vision** and **Metadata** |

A reading that has just changed is written in the **Changed values** color
(light blue by default) for 750 ms, so the live values — the L1 frame
luminance, the L5 active area, bitrates — stand out from the ones that stay put.

Every row is explained on [The TinyPPI Overlay](The-TinyPPI-Overlay).

---

## 3. Use the keys

| Key | On the overlay |
|---|---|
| **Back** / **Esc** | Close TinyPPI. |
| **OK** / **Enter** | On a Dolby Vision source: open the [Dolby Vision metadata view](Dolby-Vision-Metadata-View). Elsewhere: nothing. |
| **Arrow keys** | Only with **Settings → General → Move with the arrow keys** on: nudge the overlay 10 px per press. The move is not saved. |
| **The launch key again** | Toggles TinyPPI closed. |

The overlay also closes on its own when playback stops, when you leave
fullscreen video, or after **Settings → General → Auto-hide** seconds (off by
default).

---

## 4. Try the VS10 dialog

On an Amlogic box with Dolby Vision support the VS10 engine can convert the
picture: SDR to HDR10 or Dolby Vision, HDR10 to SDR or Dolby Vision, Dolby
Vision to SDR. To try it:

- set **Launch mode** to **VS10 dialog**, or
- map a second key to `RunScript(script.tinyppi,dialog)`.

The dialog offers the modes that make sense for the playing source plus a
**Player process info** button that opens the overlay. Details:
[VS10 Output Modes](VS10-Output-Modes).

---

## 5. Optional extras

| Want this? | Switch it on under |
|---|---|
| Codec logos for a few seconds when a video starts | **Settings → Codec logos → Show codec logos on playback start** |
| Codec logos whenever the player OSD is up | **Settings → Codec logos → Show codec logos in the video OSD** |
| A speaker diagram for the audio track | **Settings → Channels → Channels in SDR / HDR / Dolby Vision** |
| The file name in the overlay header | **Settings → General → Show file name** |
| All readings on your phone | **Settings → Dashboard → Enable web dashboard**, then **Show address and token** |

---

## 6. Make it yours

Every color and every opacity of the overlay, the metadata view, the VS10
dialog, the codec logos and the channel graphic can be changed — see
[Colors and Themes](Colors-and-Themes). The overlay can be moved with
**Settings → General → Horizontal offset (SDR only)** and **Vertical offset**.

---

**Next:** [Launching and Keymaps](Launching-and-Keymaps)
