# Installation

This page covers what TinyPPI needs, how to install and update it, and where it
keeps its data.

---

## Requirements

| Requirement | Details |
|---|---|
| **Operating system** | **CoreELEC 22 or later.** TinyPPI checks for `/etc/coreelec` (or a `coreelec` entry in `/etc/os-release`) and for a Kodi major version of 22 or higher before it opens a view. On anything else it shows *"Only CoreELEC 22 or later is supported"*. |
| **Kodi** | Kodi 22 (the add-on imports `xbmc.python` 3.1.0). |
| **Hardware** | An **Amlogic** device running CoreELEC. The Amlogic driver supplies the display mode, pixel format, EOTF/gamut and Dolby Vision state; VS10 switching writes to the Amlogic Dolby Vision driver. |
| **Skin** | A skin with a **1080i** layout (Estuary and most current skins). A skin that ships a `720p` folder is refused with *"720p skins are not supported"*. |
| **Dependency** | [`script.module.sidedata`](https://github.com/matthane/script.module.sidedata) **1.6.0 or later**. It parses the raw Dolby Vision / HDR side data CoreELEC 22 publishes. Kodi installs it together with TinyPPI as a declared dependency. |
| **Network** *(dashboard only)* | A phone, tablet or laptop on the same local network as the box. No internet access is needed. |

> **Why CoreELEC 22?** All Dolby Vision and HDR readings come from
> `Player.Process(video.sidedata)`, an InfoLabel CoreELEC 22 introduced. It
> carries the raw RPU, the dvcC/dvvC configuration record, the HDR10+ payload
> and the static SEIs of the frame being decoded, which is what lets the overlay
> follow the stream frame by frame instead of probing the file.

---

## Install from the repository (recommended)

1. In Kodi open **Settings → File manager → Add source**.
2. Enter the repository URL and give the source a name (for example `jamal2362`):
   ```
   https://ce-repo.github.io/repository.jamal2362/
   ```
3. Go to **Settings → Add-ons → Install from zip file** and pick the source you
   just added.
4. Install the repository ZIP file it contains.
5. Go to **Install from repository**, open the repository, choose
   **Program add-ons → TinyPPI** and select **Install**.
6. Confirm the dependency list (it includes `script.module.sidedata`).

Installing from the repository is what keeps TinyPPI updated: Kodi checks the
repository and installs new versions on its own, following your
**Settings → System → Add-ons → Updates** choice.

> If **Install from zip file** is greyed out or blocked, enable
> **Settings → System → Add-ons → Unknown sources** first.

---

## After installing

TinyPPI has two parts:

- A **background service** that starts with Kodi. It publishes the color theme,
  registers the overlay's fonts in the active skin, runs the codec-logo splash,
  owns the web dashboard and opens views quickly when asked to. It is running
  whenever the add-on is enabled.
- The **script** you launch (from a keymap, the add-on list or another add-on).
  It asks the service to open the overlay or the VS10 dialog; see
  [Launching and Keymaps](Launching-and-Keymaps).

Nothing has to be configured before first use. Start a video, switch to
fullscreen, and launch TinyPPI. The defaults are listed in the
[Settings Reference](Settings-Reference).

On first start after an update the service may print a few log lines such as
*"carried N color setting(s) over to the color picker"* (colors from versions
before 2.14.0 are converted once) or *"removed N outdated cached logo
texture(s)"*. Both are expected.

---

## Updating

- **From the repository:** automatic, or **Add-ons → My add-ons → Program
  add-ons → TinyPPI → Update**.
- Settings are kept across updates. Settings removed in a newer version are
  ignored, and color values from older versions are migrated.
- The **What's new** text in the add-on information shows the changes of the
  installed version only. Older versions are listed on the
  [Release History](Release-History) page.

---

## Uninstalling

**Add-ons → My add-ons → Program add-ons → TinyPPI → Uninstall.** Kodi asks
whether to remove the add-on's data as well. If you keep it, the data folder
below stays in place.

TinyPPI also adds two font entries (`font23_narrow` at 21 px and `font32` at
32 px, both using Kodi's own `arial.ttf`) to the active skin's `Font.xml`. They
are harmless when unused, and a skin update or reinstall replaces `Font.xml`
anyway.

---

## Where TinyPPI keeps its data

| Path (CoreELEC) | Contents |
|---|---|
| `/storage/.kodi/addons/script.tinyppi/` | The add-on itself. Replaced on every update, so do not edit files here. |
| `/storage/.kodi/userdata/addon_data/script.tinyppi/settings.xml` | Your settings, including the dashboard access token. |
| `/storage/.kodi/userdata/addon_data/script.tinyppi/imax_titles.txt` | *Optional.* Your own additions to the IMAX title list (see [IMAX Detection](IMAX-Detection)). Survives updates. |
| `/storage/.kodi/userdata/addon_data/script.tinyppi/scaled_images/` | Codec logos scaled down to their on-screen size. A cache: deleting it is safe, and it is rebuilt when needed. |
| `/storage/.kodi/temp/kodi.log` | Kodi's log. Every TinyPPI line starts with `TinyPPI` (see [Troubleshooting](Troubleshooting#reading-the-log)). |

On other Kodi installs the same folders live under Kodi's `userdata` directory
(`special://profile/addon_data/script.tinyppi/`).

---

**Next:** [Getting Started](Getting-Started)
