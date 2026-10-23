# VS10 Output Modes

Dolby Vision-capable Amlogic chips contain Dolby's **VS10** engine, which can
convert the decoded picture before it leaves the box: SDR up to HDR10 or Dolby
Vision, HDR10 down to SDR or up to Dolby Vision, Dolby Vision down to SDR.
TinyPPI offers these conversions for the playing title through the **VS10
dialog**, through direct `run_mode` commands, and from the
[web dashboard](Web-Dashboard).

![VS10 dialog](https://github.com/user-attachments/assets/d0a005fb-62bf-4277-93ee-4358f61cb172)

---

## Contents

- [Opening the dialog](#opening-the-dialog)
- [Which modes are offered](#which-modes-are-offered)
- [Dialog layouts](#dialog-layouts)
- [Position and colors](#position-and-colors)
- [Direct switching with run_mode](#direct-switching-with-run_mode)
- [How a switch is applied](#how-a-switch-is-applied)
- [Reading the log](#reading-the-log)

---

## Opening the dialog

- `RunScript(script.tinyppi,dialog)` from a key, or
- `NotifyAll(script.tinyppi,open_dialog)` (fastest), or
- **Settings → General → Launch mode → VS10 dialog**, so the normal TinyPPI
  key opens the dialog instead of the overlay.

The dialog has the same requirements as the overlay: CoreELEC 22+, fullscreen
video, something playing. Pressing the key again closes it.

| Key | Action |
|---|---|
| **Up / Down** (or **Left / Right** in the bar) | Move between the buttons |
| **Left / Right** *(single-button layout)* | Step to the previous / next choice (wraps around) |
| **OK** | Apply the mode on the focused button, or open the overlay from **Player process info** |
| **Back**, **Esc**, **Stop** | Close the dialog without switching |

The chosen mode is applied **after** the dialog has closed and the video window
has settled (250 ms), because Kodi drops actions sent while a dialog is
closing.

---

## Which modes are offered

The first button is always **Player process info**, which opens the TinyPPI
overlay. The other buttons depend on the source:

| Source | Buttons | Mode applied |
|---|---|---|
| **SDR** | Original · SDR → HDR10 · SDR → Dolby Vision | `original_sdr` · `hdr10` · `dv` |
| **HDR10** | HDR10 (Original) · HDR10 → SDR · HDR10 → Dolby Vision | `original_hdr` · `sdr8` · `dv` |
| **Dolby Vision** | Dolby Vision (Original) · Dolby Vision → SDR | `original_dv` · `sdr8` |
| **HDR10+** | *(none — Player process info only)* | — |
| **HLG** | *(none — Player process info only)* | — |
| **Dolby Vision + HDR10+ hybrid** | *(none — Player process info only)* | — |

Why some sources have no modes:

- **HDR10+** and **HLG** are not VS10 inputs; the driver has no mode group for
  either.
- A **Dolby Vision grade that also carries an HDR10+ (ST 2094-40) payload**
  reads as Dolby Vision, but the driver does not take a VS10 mode while the
  HDR10+ payload rides along. Rather than offer a switch that does nothing, the
  dialog and the dashboard offer none. (A stream whose HDR10+ Kodi has
  stripped for a display without HDR10+ support keeps its modes — what was
  removed is no longer in what the decoder sees.)

The dialog keeps re-detecting the source twice a second while it is open. If
the detection finishes after the dialog appeared, the buttons change in place,
and the panel keeps its size so nothing jumps.

---

## Dialog layouts

Pick one under **Settings → VS10 dialog → Layout → Dialog layout**:

| Layout | Panel size | What it looks like |
|---|---|---|
| **Single button** *(default)* | 700 × 216 | One button showing the current choice; **Left/Right** step through the choices. Made for remotes that have little more than a direction pad and OK. |
| **Bar** | 1702 × 206 | The choices side by side in a low, wide panel that leaves most of the picture visible. |
| **Dialog** | 471 × 546 | The original layout: the choices stacked in a tall panel. |

All three draw the same choices for the same source.

---

## Position and colors

**Settings → VS10 dialog → Dialog position:**

| Setting | Default | Range |
|---|---|---|
| **Vertical position** | 100 % (resting on the bottom margin) | 0 % = top margin … 100 % = bottom margin |
| **Horizontal position** | 50 % (centred) | 0 % = left margin … 100 % = right margin |

Every layout keeps a 50 px margin to the screen edge. The panel is hidden until
it has been placed, so it never jumps into position.

**Colors** (each with its own opacity): global background, background, header
title, header icon, separator line, **Button text** (unfocused buttons),
**Selection** (focused button background) and **Selection text** (focused
button text, black by default). See [Colors and Themes](Colors-and-Themes).

---

## Direct switching with `run_mode`

`run_mode` applies a mode immediately, without opening any window — ideal for
keymaps and automation:

```
RunScript(script.tinyppi,run_mode,<mode>)
```

| Mode | Output | Notes |
|---|---|---|
| `original_sdr` | Source passed through (VS10 bypass) | For SDR sources. |
| `original_hdr` | HDR10 | HDR10 passthrough. |
| `original_dv` | Dolby Vision | Alias of `dv`. |
| `original_hlg` | VS10 off | Restores *follow source* with Dolby Vision disabled — the state Kodi leaves for HLG. Not offered in the dialog; useful to clear a leftover mode. |
| `dv` | Dolby Vision | Player-LED boxes get IPT, TV-LED boxes tunnelled IPT (see below). |
| `hdr10` | HDR10 | |
| `sdr10` | SDR, 10-bit | |
| `sdr8` | SDR, 8-bit | What the dialog's **→ SDR** buttons use. |

`run_mode` applies a mode even where the dialog offers none (for example on a
Dolby Vision + HDR10+ hybrid). It then logs a warning that the driver may not
take it.

---

## How a switch is applied

### 1. Native VS10 actions first

Newer CoreELEC builds contain native `vs10.*` actions (`vs10.original`,
`vs10.dv`, `vs10.hdr10`, `vs10.sdr`). TinyPPI detects them once per session by
asking Kodi for the setting `coreelec.amlogic.dolbyvision.vs10.dv`, which
arrived together with them.

When they exist and a video plays, TinyPPI sends the action and watches the
Dolby Vision driver for up to 500 ms. If the driver state changed, the switch
is done. If it did not — or no video plays — TinyPPI falls back to its own
path.

`sdr8` has no native action (`vs10.sdr` always means 10-bit SDR), so it always
takes TinyPPI's own path, which keeps 8-bit and 10-bit SDR distinct.

### 2. TinyPPI's own path (sysfs)

TinyPPI writes the same Amlogic Dolby Vision driver nodes CoreELEC's Kodi
writes when it opens or closes a decoder:

| Node | Role |
|---|---|
| `/sys/module/aml_media/parameters/dolby_vision_enable` | `Y` / `N` — Dolby Vision core on or off |
| `/sys/module/aml_media/parameters/dolby_vision_policy` | `1` follow source, `2` force output |
| `/sys/class/amdolby_vision/dv_mode` | The output mode to force (see below) |
| `/sys/module/aml_media/parameters/dolby_vision_ll_policy` | Low-latency policy: `0` for tunnelled IPT (TV-LED), `1` for IPT (Player-LED) |
| `/sys/module/aml_media/parameters/dolby_vision_mode` | *Read only:* the output the driver is actually sending |
| `/sys/module/aml_media/parameters/dolby_vision_status` | *Read only:* whether the core is still running |

`dv_mode` values: `0` bypass · `1` Dolby Vision IPT (Player-LED) · `2` Dolby
Vision tunnelled IPT (TV-LED) · `3` HDR10 · `4` SDR10 · `5` SDR8.

The order of the writes matters: Dolby Vision is enabled before the policy
forces an output; for bypass the policy goes back to *follow source*, the core
is allowed to stop, and only then is Dolby Vision disabled. Writing
`enable=N` into a live core left the display half-switched.

### 3. Player-LED or TV-LED

For a Dolby Vision output TinyPPI reads Kodi's
`coreelec.amlogic.dolbyvisionled` setting (0 = TV-LED, 1 = Player-LED) and
picks tunnelled IPT or plain IPT accordingly, setting the matching low-latency
policy. If the setting cannot be read, the driver's current low-latency policy
is used; failing that, TV-LED (CoreELEC's default).

### 4. HDR10 ↔ Dolby Vision goes through SDR

The driver cannot move directly between an HDR10 and a Dolby Vision output.
When such a switch is requested during playback, TinyPPI makes **two complete
switches** — first to SDR10, then, once the Dolby Vision core is down and after
a 250 ms pause, to the requested mode — exactly as if you had pressed SDR and
then the mode by hand. A staged switch is bounded at 15 s.

### 5. Display reset

Kodi only re-negotiates the HDMI output when the stream's own HDR type changes.
A VS10 switch during playback bypasses that, so the TV would stay on the old
format with wrong colors (most visibly in Player-LED mode). After a switch
TinyPPI waits for the driver to confirm the new output and then sets the
Amlogic `UPDATE` property on the HDMI connector through DRM — the same step
Kodi uses to re-apply the current mode.

- Switches made through sysfs always get the reset.
- Switches made through native actions get it only when they cross the Dolby
  Vision line (the actions handle the rest themselves).
- The reset needs CoreELEC 22's kernel (5.15); elsewhere it is a harmless
  no-op, and the switch itself never fails because of it.

### 6. From the dashboard

A switch requested from the [web dashboard](Web-Dashboard) takes exactly the
same path as `run_mode`. A switch takes a few seconds; taps that arrive in the
meantime are not queued up — the last one wins, so three quick taps end in the
mode tapped last rather than three switches in a row.

---

## Reading the log

Every switch is logged (see [Troubleshooting](Troubleshooting#reading-the-log)).
Typical lines:

```
TinyPPI: native VS10 Actions available -> preferred during playback, with sysfs fallback if they don't take effect
TinyPPI: mode 'dv' set via VS10 Actions -> Action(vs10.dv)
TinyPPI: 'sdr8' has no native VS10 action -> using built-in TinyPPI VS10 (sysfs) to keep the exact output
TinyPPI: /sys/class/amdolby_vision/dv_mode = 5
TinyPPI: mode 'sdr8' set via built-in TinyPPI VS10 (sysfs)
TinyPPI: 'dv' cannot be reached from the output now on the wire in one switch -> going through SDR first
```

Warning signs:

| Line | Meaning |
|---|---|
| `FAILED /sys/...: [Errno …]` and `mode '…' NOT set via built-in TinyPPI VS10 (sysfs)` | The driver node was not writable — usually not an Amlogic Dolby Vision box, or an unsupported kernel. |
| `VS10 Action(…) had no effect on the DV driver -> falling back …` | The native action did nothing; the sysfs path was used instead. |
| `'…' did not move the driver's output mode -> no display reset` | The driver did not confirm the change within 1 s. |
| `'…' is being applied to a Dolby Vision title that also carries HDR10+ …` | A `run_mode` on a hybrid grade; the output may not change. |
