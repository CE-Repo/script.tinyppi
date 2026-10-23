# Launching and Keymaps

TinyPPI is meant to be opened from a remote button during playback. This page
lists every way to launch it, every command it understands, and how to map
them to keys.

---

## The short version

| You want | Use |
|---|---|
| Open/close the overlay (or what **Launch mode** says) | `RunAddon(script.tinyppi)` |
| Open/close the overlay, fastest | `NotifyAll(script.tinyppi,open_overlay)` |
| Open/close the VS10 dialog, fastest | `NotifyAll(script.tinyppi,open_dialog)` |
| Open the VS10 dialog | `RunScript(script.tinyppi,dialog)` |
| Switch the VS10 output directly | `RunScript(script.tinyppi,run_mode,<mode>)` |

Every one of them **toggles**: pressed again while TinyPPI is open, it closes
it.

---

## Assign a remote button with the Keymap Editor (easiest)

1. Install the **Keymap Editor** add-on (`script.keymap`) from the official
   Kodi repository.
2. Open it and choose **Edit → Global → Add-ons**.
3. Select **Launch TinyPPI**.
4. Press the key or remote button you want to use, then confirm.
5. Go back and choose **Save**.

The button now opens and closes TinyPPI during fullscreen playback. What it
opens follows **Settings → General → Launch mode**.

---

## Write the keymap by hand

Keymaps live in `userdata/keymaps/` (on CoreELEC
`/storage/.kodi/userdata/keymaps/`). Any file name ending in `.xml` works; the
Keymap Editor uses `gen.xml`. Restart Kodi (or run the builtin
`Action(reloadkeymaps)`) after editing.

### Keyboard key

Replace `xxxxx` with a Kodi key name such as `f1`, `i` or `p`:

```xml
<keymap>
  <global>
    <keyboard>
      <xxxxx>RunAddon(script.tinyppi)</xxxxx>
    </keyboard>
  </global>
</keymap>
```

### Remote buttons (CEC or IR)

A typical layout: the **red** button opens the overlay, the **green** one the
VS10 dialog. Putting them under `<FullscreenVideo>` instead of `<global>`
leaves the buttons free for other uses in the menus:

```xml
<keymap>
  <FullscreenVideo>
    <remote>
      <red>NotifyAll(script.tinyppi,open_overlay)</red>
      <green>NotifyAll(script.tinyppi,open_dialog)</green>
    </remote>
  </FullscreenVideo>
</keymap>
```

### One key per VS10 mode

```xml
<keymap>
  <FullscreenVideo>
    <keyboard>
      <f5>RunScript(script.tinyppi,run_mode,original_dv)</f5>
      <f6>RunScript(script.tinyppi,run_mode,hdr10)</f6>
      <f7>RunScript(script.tinyppi,run_mode,sdr10)</f7>
    </keyboard>
  </FullscreenVideo>
</keymap>
```

---

## The fastest shortcut: `NotifyAll`

Every `RunAddon` / `RunScript` call starts a fresh Python interpreter, and Kodi
builds one each time. TinyPPI's background service is already running with
everything loaded, so a launch only asks the service to open the view — and
the service answers within a few milliseconds.

A keymap can skip the script entirely and talk to the service directly:

```xml
<xxxxx>NotifyAll(script.tinyppi,open_overlay)</xxxxx>
<xxxxx>NotifyAll(script.tinyppi,open_dialog)</xxxxx>
```

| Message | Opens |
|---|---|
| `open_overlay` | The TinyPPI overlay |
| `open_dialog` | The VS10 dialog |

`NotifyAll` needs the service, which runs whenever the add-on is enabled. If
it ever does not answer, a key mapped to `NotifyAll` does nothing, while
`RunAddon(script.tinyppi)` falls back to opening the view in its own script
after 750 ms (and writes *"the service did not answer – opening in this script
instead"* to the log).

---

## Command reference

All commands are passed as script arguments:
`RunScript(script.tinyppi,<command>[,<argument>…])`.

| Command | Arguments | What it does |
|---|---|---|
| *(none)* | — | Opens what **Launch mode** says: the overlay (`0`, default) or the VS10 dialog (`1`). Same as `RunAddon(script.tinyppi)`. |
| `overlay` | — | Opens (or closes) the TinyPPI overlay, regardless of **Launch mode**. |
| `dialog` | — | Opens (or closes) the VS10 dialog, regardless of **Launch mode**. |
| `run_mode` | `<mode>` | Switches the VS10 output mode immediately, without opening anything. See the mode list below. |
| `splash` | — | Runs the codec-logo controller once (normally the service does this on every playback start). |
| `web_info` | — | Shows the dashboard address and the access token (the **Show address and token** button in the settings). |
| `web_token` | — | Generates a new dashboard token and shows it (the **Generate a new token** button). Every browser holding the old token is logged out. |
| `pick_color` | `<setting id>[,<label id>]` | Opens the color picker for one color setting. Used by the settings dialog's color rows; there is no need to call it yourself. |

An unknown command opens the overlay.

### VS10 modes for `run_mode`

| Mode | Result |
|---|---|
| `original_sdr` | SDR passed through untouched (VS10 bypass). |
| `original_hdr` | HDR10 passed through as HDR10. |
| `original_dv` | Dolby Vision output (same as `dv`; the name reads better in a keymap for DV sources). |
| `original_hlg` | Turns VS10 off for an HLG source (HLG is not a VS10 input). Mainly useful to clear a leftover mode. |
| `dv` | Convert to Dolby Vision. |
| `hdr10` | Convert to HDR10. |
| `sdr10` | Convert to SDR, 10-bit. |
| `sdr8` | Convert to SDR, 8-bit. |

How these modes are applied, and which ones the dialog offers per source, is
explained on [VS10 Output Modes](VS10-Output-Modes).

---

## From another add-on or a script

```python
import xbmc

# Open the overlay
xbmc.executebuiltin('RunScript(script.tinyppi)')

# Open the VS10 dialog
xbmc.executebuiltin('RunScript(script.tinyppi,dialog)')

# Switch the output to Dolby Vision
xbmc.executebuiltin('RunScript(script.tinyppi,run_mode,dv)')

# Ask the running service directly (fastest)
xbmc.executebuiltin('NotifyAll(script.tinyppi,open_overlay)')
```

### Kodi URL

```
plugin://script.tinyppi/
```

---

## From home automation (JSON-RPC)

With Kodi's own web server or JSON-RPC over TCP enabled, the same commands can
be sent from another machine, for example from Home Assistant:

```json
{"jsonrpc": "2.0", "id": 1, "method": "Addons.ExecuteAddon",
 "params": {"addonid": "script.tinyppi", "params": ["run_mode", "hdr10"]}}
```

```json
{"jsonrpc": "2.0", "id": 1, "method": "JSONRPC.NotifyAll",
 "params": {"sender": "script.tinyppi", "message": "open_overlay"}}
```

> The [web dashboard](Web-Dashboard) also exposes VS10 switching and a remote
> over its own token-protected HTTP API — see
> [Dashboard HTTP API](Dashboard-HTTP-API).

---

## When a launch does nothing

TinyPPI checks a few things before it opens a view. If one fails it either
shows a notification or stays silent:

| Condition | Result |
|---|---|
| Not CoreELEC, or Kodi older than 22 | Notification *"Only CoreELEC 22 or later is supported"* |
| Kodi version unreadable | Notification *"The CoreELEC version could not be detected"* |
| The skin has a `720p` folder | Notification *"720p skins are not supported"* |
| Fullscreen video is not the active window | Nothing happens |
| Nothing is playing | Nothing happens |
| TinyPPI is already open | It closes (toggle) |
| A second press while TinyPPI is still opening | The press is dropped |

More in [Troubleshooting](Troubleshooting).
