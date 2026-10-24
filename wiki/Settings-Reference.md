# Settings Reference

Every setting of TinyPPI, by category, with its **ID** (as stored in
`addon_data/script.tinyppi/settings.xml`), its **default** and what it does.
The labels are the English ones; the settings dialog is also available in
Arabic, German, Hungarian and Simplified Chinese.

All settings apply **without restarting Kodi**. An open overlay picks up color
changes immediately; position and layout settings apply the next time a view
opens, unless noted otherwise.

Color settings open Kodi's color picker; how that works, the palettes and the
HEX option are described on [Colors and Themes](Colors-and-Themes). Each color
comes with a **Transparency** (opacity) slider from 0 % to 100 %.

---

## Contents

1. [General](#general)
2. [TinyPPI overlay](#tinyppi-overlay)
3. [DV metadata](#dv-metadata)
4. [Codec logos](#codec-logos)
5. [VS10 dialog](#vs10-dialog)
6. [Channels](#channels)
7. [Dashboard](#dashboard)

---

## General

Launch behaviour, overlay content and position.

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Launch mode** | `launch_mode` | TinyPPI | `0` TinyPPI<br>`1` VS10 dialog | Choose what opens when the add-on is launched. |
| **Auto-hide** | `auto_hide` | 0 | 0 – 30 | Automatically hides the TinyPPI overlay after the selected time (in seconds). 0 = off. Does not apply to the VS10 dialog. |
| **Show file name** | `filename` | Off | On / Off | Show the currently playing file name in TinyPPI. |
| **Show L5 offsets icon** | `show_l5_icon` | On | On / Off | Show the L5 offsets icon (lrtb) next to the L5 values. |
| **Brightness unit** | `unit_type` | cd/m² | `0` cd/m²<br>`1` nits<br>`2` Hidden | Choose the unit shown for the L6 brightness values. |
| **Horizontal offset (SDR only)** | `offset_x` | 0 % | 0 – 100 % | Shifts the overlay to the right from its default position. 100% is the maximum shift that keeps the content on screen. |
| **Vertical offset** | `offset_y` | 0 % | 0 – 100 % | Shifts the overlay upwards from its default position. 100% is the maximum shift that keeps the content on screen. |
| **Move with the arrow keys** | `nudge_position` | Off | On / Off | Lets the arrow keys on the remote move the TinyPPI overlay around the screen while it is open. The move is not saved: the next launch starts from the position configured above. |
| **Keep the HDR/DV area when converting to SDR** | `keep_area_on_sdr` | On | On / Off | Keeps the HDR static-metadata and Dolby Vision panels on screen while VS10 converts the source to SDR. Turn off to draw the overlay in its SDR layout instead. |
| **Keep the Dolby Vision area when converting to HDR10** | `keep_dv_area_on_hdr10` | On | On / Off | Keeps the Dolby Vision panels on screen while VS10 converts a Dolby Vision source to HDR10. Turn off to show the HDR static-metadata panel instead. |

Notes:

- **Launch mode** only decides what a launch *without* arguments opens.
  `RunScript(script.tinyppi,overlay)` and `…,dialog` always open their view.
- **Brightness unit** affects every luminance row (HDR10, RPU / L6, L1);
  *Hidden* removes the units — including the `12-bit` after PQ codes — so all
  rows show a unit or none do.
- The **offsets** are explained on
  [The TinyPPI Overlay](The-TinyPPI-Overlay#position).

---

## TinyPPI overlay

The colors of the overlay. The category also holds the **Changed values**
highlight duration:

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Highlight duration** | `output_changed_duration` | 750 | 100 – 3000, step 50 | How long a reading that just changed stays in the highlight color, in milliseconds. The readings behind it are still read ten times a second whatever this is set to, so no change is missed; at 100 the highlight lasts a single refresh, which is too brief to follow. |

| Element | Color setting ID | Default color | Opacity setting ID | Default opacity | Description |
|---|---|---|---|---|---|
| **Global background** | `global_background_color` | Charcoal | `global_background_opacity` | 0 % | Color of the full-screen global background. |
| **Background** | `background_color` | Charcoal | `background_opacity` | 98 % | Background color of the overlay style. |
| **Title** | `title_color` | White | `title_opacity` | 100 % | Color of the section titles. |
| **Header title** | `header_color` | White | `header_opacity` | 100 % | Color of the overlay header label (Modern). |
| **Description** | `description_color` | White | `description_opacity` | 100 % | Color of the label descriptions. |
| **Output** | `output_color` | White | `output_opacity` | 100 % | Color of the output values. |
| **Changed values** | `output_changed_color` | Light blue | `output_changed_opacity` | 100 % | Color for the readings that just changed. A value that moved is written in this color until the highlight duration below runs out, so the live readings can be told from the ones that do not move. |
| **File name** | `filename_color` | White | `filename_opacity` | 100 % | Color of the playing file name. *(visible when `filename` = `true`)* |
| **FPS** | `fps_color` | White | `fps_opacity` | 100 % | Color of the In / drop / out FPS values. |
| **Unit (cd/m², nits)** | `unit_color` | White | `unit_opacity` | 100 % | Color of the cd/m² brightness unit. *(visible when `unit_type` ≠ `2`)* |
| **Detail** | `accent_color` | White | `accent_opacity` | 70 % | Color of the dimmed detail values shown in parentheses. |
| **Icon** | `icon_color` | White | `icon_opacity` | 100 % | Color of the section icons. |
| **Header icon** | `header_icon_color` | White | `header_icon_opacity` | 100 % | Color of the chart icon (Modern). |
| **Progress bar** | `progress_color` | White | `progress_opacity` | 100 % | Color of the progress bars. |
| **Separator line** | `line_color` | White | `line_opacity` | 15 % | Color of the separator lines. |
| **Conversion (yes)** | `convert_yes_color` | Forest | `convert_yes_opacity` | 100 % | Color of the check-circle icon shown when conversion is active. |
| **Conversion (no)** | `convert_no_color` | Crimson | `convert_no_opacity` | 100 % | Color of the cross-circle icon shown when conversion is inactive. |
| **FEL tag** | `fel_color` | Forest | `fel_opacity` | 100 % | Color of the FEL enhancement-layer tag in the input. |
| **MEL tag** | `mel_color` | Tangerine | `mel_opacity` | 100 % | Color of the MEL enhancement-layer tag in the input. |

See [The TinyPPI Overlay](The-TinyPPI-Overlay#highlighted-values) for what
"changed values" covers.

---

## DV metadata

The on-screen [Dolby Vision metadata view](Dolby-Vision-Metadata-View).

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Dolby Vision metadata view** | `dv_metadata_view` | On | On / Off | Lets OK open the Dolby Vision metadata view while the TinyPPI overlay is up and a Dolby Vision source is playing. It lists every block the stream's side data carries — the configuration record, the RPU from its header through L11, the trim passes and the static SEIs. OK opens the section under the cursor in a window of its own, Back returns to the TinyPPI overlay. On any other source OK does nothing. |
| **Highlight duration** | `metadata_changed_duration` | 750 | 100 – 3000, step 50 | How long a reading that just changed stays in the highlight color, in milliseconds. The readings behind it are still read ten times a second whatever this is set to, so no change is missed; at 100 the highlight lasts a single refresh, which is too brief to follow. |

| Element | Color setting ID | Default color | Opacity setting ID | Default opacity | Description |
|---|---|---|---|---|---|
| **Global background** | `metadata_global_background_color` | Charcoal | `metadata_global_background_opacity` | 0 % | Color laid over the whole screen behind the Dolby Vision metadata view. Raise its opacity to dim the picture behind it. |
| **Background** | `metadata_background_color` | Charcoal | `metadata_background_opacity` | 98 % | Background color of the metadata view itself. |
| **Header title** | `metadata_header_color` | White | `metadata_header_opacity` | 100 % | Color of the heading at the top of the metadata view. |
| **Header icon** | `metadata_header_icon_color` | White | `metadata_header_icon_opacity` | 100 % | Color of the Dolby Vision logo in the top right corner. |
| **Title** | `metadata_title_color` | White | `metadata_title_opacity` | 100 % | Color of the section headings, such as RPU or L2 — Trims. |
| **Column headings** | `metadata_column_color` | White | `metadata_column_opacity` | 100 % | Color of the column headings in the trim tables: Slope, Offset, Power and the rest. |
| **Description** | `metadata_name_color` | White | `metadata_name_opacity` | 100 % | Color of the field names down the left column. |
| **Output** | `metadata_value_color` | White | `metadata_value_opacity` | 100 % | Color of the readings. A value that just changed is written in the "Changed values" color instead, for as long as it keeps changing. |
| **Changed values** | `metadata_changed_color` | Light blue | `metadata_changed_opacity` | 100 % | Color for the readings that just changed. A value that moved is written in this color until the highlight duration below runs out, so the live readings can be told from the ones that do not move. |
| **Separator line** | `metadata_line_color` | White | `metadata_line_opacity` | 15 % | Color of the rules under the section headings and above and below the list. |
| **Selection** | `metadata_focus_color` | White | `metadata_focus_opacity` | 15 % | Color of the bar behind the row the selection is on. |
| **Scrollbar** | `metadata_scrollbar_color` | White | `metadata_scrollbar_opacity` | 100 % | Color of the scrollbar down the right-hand edge. |
| **Key hint** | `metadata_hint_color` | White | `metadata_hint_opacity` | 100 % | Color of the line at the bottom naming what the keys do. |

---

## Codec logos

The [codec logos](Codec-Logos). Three master switches enable the three
situations:

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Show codec logos on playback start** | `splash_enabled` | Off | On / Off | When a video starts, briefly shows the audio format and HDR/video format logos (top-left by default; see the offsets). |
| **Display duration (seconds)** | `splash_duration` | 8 | 1 – 30 | How long the format logos stay on screen before they disappear. *(visible when `splash_enabled` is on)* |
| **Show video codec logo** | `splash_start_show_video` | On | On / Off | Includes the HDR/video format logo in the stack. Turn it off to show the audio format logo on its own. *(visible when `splash_enabled` is on)* |
| **Show audio codec logo** | `splash_start_show_audio` | On | On / Off | Includes the audio format logo in the stack. Turn it off to show the HDR/video format logo on its own. *(visible when `splash_enabled` is on)* |
| **Logo order** | `splash_start_order` | Video on top, audio below | `0` Video on top, audio below<br>`1` Audio on top, video below | Which of the two logos sits on top of the stack. *(visible when `splash_enabled` is on)* |
| **Dolby Vision pill position** | `splash_start_pill_position` | Bottom edge | `0` Bottom edge<br>`1` Top edge | Which edge of the logo panel the Dolby Vision layer pill sits on. *(visible when `splash_enabled` is on)* |
| **Horizontal offset** | `splash_start_offset_x` | 0 % | 0 – 100 % | Moves the logos from the left edge (0%) to the right edge (100%) of the screen. *(visible when `splash_enabled` is on)* |
| **Vertical offset** | `splash_start_offset_y` | 0 % | 0 – 100 % | Moves the logos from the top edge (0%) to the bottom edge (100%) of the screen. *(visible when `splash_enabled` is on)* |
| **Size (%)** | `splash_start_scale` | 100 | 80 – 130 | Scales the format logos. 100% is the default size; lower values shrink them, higher values enlarge them. The horizontal and vertical offset are kept. *(visible when `splash_enabled` is on)* |
| **Show codec logos in the video OSD** | `splash_show_on_osd` | Off | On / Off | Also shows the format logos whenever the on-screen playback controls (video OSD) are visible. |
| **Show video codec logo** | `splash_osd_show_video` | On | On / Off | Includes the HDR/video format logo in the stack. Turn it off to show the audio format logo on its own. *(visible when `splash_show_on_osd` = `true`)* |
| **Show audio codec logo** | `splash_osd_show_audio` | On | On / Off | Includes the audio format logo in the stack. Turn it off to show the HDR/video format logo on its own. *(visible when `splash_show_on_osd` = `true`)* |
| **Logo order** | `splash_osd_order` | Video on top, audio below | `0` Video on top, audio below<br>`1` Audio on top, video below | Which of the two logos sits on top of the stack. *(visible when `splash_show_on_osd` = `true`)* |
| **Dolby Vision pill position** | `splash_osd_pill_position` | Bottom edge | `0` Bottom edge<br>`1` Top edge | Which edge of the logo panel the Dolby Vision layer pill sits on. *(visible when `splash_show_on_osd` = `true`)* |
| **Horizontal offset** | `splash_osd_offset_x` | 0 % | 0 – 100 % | Moves the logos from the left edge (0%) to the right edge (100%) of the screen. *(visible when `splash_show_on_osd` = `true`)* |
| **Vertical offset** | `splash_osd_offset_y` | 0 % | 0 – 100 % | Moves the logos from the top edge (0%) to the bottom edge (100%) of the screen. *(visible when `splash_show_on_osd` = `true`)* |
| **Size (%)** | `splash_osd_scale` | 100 | 80 – 130 | Scales the format logos. 100% is the default size; lower values shrink them, higher values enlarge them. The horizontal and vertical offset are kept. *(visible when `splash_show_on_osd` = `true`)* |
| **Show codec logos in the TinyPPI overlay** | `splash_show_on_tinyppi` | Off | On / Off | Also shows the format logos while the TinyPPI info overlay is open. |
| **Show video codec logo** | `splash_tinyppi_show_video` | On | On / Off | Includes the HDR/video format logo in the stack. Turn it off to show the audio format logo on its own. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Show audio codec logo** | `splash_tinyppi_show_audio` | On | On / Off | Includes the audio format logo in the stack. Turn it off to show the HDR/video format logo on its own. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Logo order** | `splash_tinyppi_order` | Video on top, audio below | `0` Video on top, audio below<br>`1` Audio on top, video below | Which of the two logos sits on top of the stack. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Dolby Vision pill position** | `splash_tinyppi_pill_position` | Bottom edge | `0` Bottom edge<br>`1` Top edge | Which edge of the logo panel the Dolby Vision layer pill sits on. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Horizontal offset** | `splash_tinyppi_offset_x` | 0 % | 0 – 100 % | Moves the logos from the left edge (0%) to the right edge (100%) of the screen. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Vertical offset** | `splash_tinyppi_offset_y` | 0 % | 0 – 100 % | Moves the logos from the top edge (0%) to the bottom edge (100%) of the screen. *(visible when `splash_show_on_tinyppi` = `true`)* |
| **Size (%)** | `splash_tinyppi_scale` | 100 | 80 – 130 | Scales the format logos. 100% is the default size; lower values shrink them, higher values enlarge them. The horizontal and vertical offset are kept. *(visible when `splash_show_on_tinyppi` = `true`)* |

Each situation then has its **own copy** of the following settings. Replace
`<mode>` with `start` (on playback start), `osd` (video OSD) or `tinyppi`
(TinyPPI overlay) — for example `splash_osd_scale`. The defaults are the same
for all three, and each group is only visible while its master switch is on.

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Show video codec logo** | `splash_<mode>_show_video` | On | On / Off | Includes the HDR/video format logo in the stack. Turn it off to show the audio format logo on its own. |
| **Show audio codec logo** | `splash_<mode>_show_audio` | On | On / Off | Includes the audio format logo in the stack. Turn it off to show the HDR/video format logo on its own. |
| **Logo order** | `splash_<mode>_order` | Video on top, audio below | `0` Video on top, audio below<br>`1` Audio on top, video below | Which of the two logos sits on top of the stack. |
| **Dolby Vision pill position** | `splash_<mode>_pill_position` | Bottom edge | `0` Bottom edge<br>`1` Top edge | Which edge of the logo panel the Dolby Vision layer pill sits on. |
| **Horizontal offset** | `splash_<mode>_offset_x` | 0 % | 0 – 100 % | Moves the logos from the left edge (0%) to the right edge (100%) of the screen. |
| **Vertical offset** | `splash_<mode>_offset_y` | 0 % | 0 – 100 % | Moves the logos from the top edge (0%) to the bottom edge (100%) of the screen. |
| **Size (%)** | `splash_<mode>_scale` | 100 | 80 – 130 | Scales the format logos. 100% is the default size; lower values shrink them, higher values enlarge them. The horizontal and vertical offset are kept. |

| Element | Color setting ID | Default color | Opacity setting ID | Default opacity | Description |
|---|---|---|---|---|---|
| **Background color** | `splash_<mode>_bg_color` | Charcoal | `splash_<mode>_bg_opacity` | 98 % | Color and transparency of the panel behind the logos. |
| **Video logo** | `splash_<mode>_video_color` | White | `splash_<mode>_video_opacity` | 100 % | Color and transparency of the HDR/video format logo. |
| **Audio logo** | `splash_<mode>_audio_color` | White | `splash_<mode>_audio_opacity` | 100 % | Color and transparency of the audio format logo. |
| **Divider** | `splash_<mode>_divider_color` | White | `splash_<mode>_divider_opacity` | 35 % | Color and transparency of the divider line between the two logos. |
| **Conversion indicator** | `splash_<mode>_convert_dot_color` | Forest | `splash_<mode>_convert_dot_opacity` | 100 % | Color of the dot shown on the video-format logo while a conversion is active. |
| **FEL indicator** | `splash_<mode>_fel_color` | Forest | `splash_<mode>_fel_opacity` | 100 % | Color of the pill shown on the splash logo when the source is Dolby Vision FEL. |
| **MEL indicator** | `splash_<mode>_mel_color` | Tangerine | `splash_<mode>_mel_opacity` | 100 % | Color of the pill shown on the splash logo when the source is Dolby Vision MEL. |
| **Other Dolby Vision** | `splash_<mode>_dv_color` | White | `splash_<mode>_dv_opacity` | 20 % | Color of the pill shown on the splash logo for any other Dolby Vision profile (no enhancement layer). |

---

## VS10 dialog

The [VS10 dialog](VS10-Output-Modes).

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Dialog layout** | `dialog_mode` | Single button | `2` Single button<br>`1` Bar<br>`0` Dialog | Which of the designs the VS10 dialog is drawn as. |
| **Vertical position** | `dialog_position_y` | 100 % | 0 – 100 % | Where the dialog sits between the top edge of the screen (0%) and the bottom one (100%). 50% leaves it in the middle, where it has always been. |
| **Horizontal position** | `dialog_position_x` | 50 % | 0 – 100 % | Where the dialog sits between the left edge of the screen (0%) and the right one (100%). 50% leaves it in the middle. |

| Element | Color setting ID | Default color | Opacity setting ID | Default opacity | Description |
|---|---|---|---|---|---|
| **Global background** | `dialog_global_background_color` | Charcoal | `dialog_global_background_opacity` | 0 % | Color of the full-screen global background. |
| **Background** | `dialog_background_color` | Charcoal | `dialog_background_opacity` | 98 % | Background color of the VS10 selection dialog panel. |
| **Header title** | `dialog_header_color` | White | `dialog_header_opacity` | 100 % | Color of the VS10 header label in the selection dialog. |
| **Header icon** | `dialog_header_icon_color` | White | `dialog_header_icon_opacity` | 100 % | Color of the chart icon in the VS10 selection dialog. |
| **Separator line** | `dialog_line_color` | White | `dialog_line_opacity` | 15 % | Color of the separator lines in the VS10 selection dialog. |
| **Button text** | `dialog_text_color` | White | `dialog_text_opacity` | 100 % | Text color of the buttons the remote is not sitting on in the VS10 dialog. |
| **Selection** | `dialog_focus_color` | White | `dialog_focus_opacity` | 100 % | Background color of the focused button in the VS10 dialog. |
| **Selection text** | `dialog_focus_text_color` | Black | `dialog_focus_text_opacity` | 100 % | Text color of the focused button in the VS10 dialog. |

The stored values of **Dialog layout** are `0` Dialog, `1` Bar, `2` Single
button; the list shows them in a different order, and an unknown value falls
back to Single button.

---

## Channels

The [channel layout graphic](Channel-Layout-Graphic).

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Channels in SDR** | `channels_sdr` | Off | On / Off | Show the channel layout graphic while playing SDR content. |
| **Channels in HDR10 / HLG / HDR10+** | `channels_hdr` | Off | On / Off | Show the channel layout graphic while playing HDR10, HLG or HDR10+ content. |
| **Channels in Dolby Vision** | `channels_dv` | Off | On / Off | Show the channel layout graphic while playing Dolby Vision content. |
| **Horizontal offset of the channel box** | `offset_x_dv` | 100 % | 0 – 100 % | Moves the channel box in Dolby Vision to the right. 0% places it at the left edge, 100% keeps it in its default position on the right. |

| Element | Color setting ID | Default color | Opacity setting ID | Default opacity | Description |
|---|---|---|---|---|---|
| **Background** | `channel_background_color` | Charcoal | `channel_background_opacity` | 98 % | Background color of the channel box shown in Dolby Vision. |
| **Layout** | `channel_layout_color` | White | `channel_layout_opacity` | 33 % | Color of the speaker layout graphic behind the active channels. |
| **Channels** | `channel_icon_color` | White | `channel_icon_opacity` | 100 % | Color of the active channels in the layout graphic. |

---

## Dashboard

The [web dashboard](Web-Dashboard). See also
[Dashboard Security](Dashboard-Security).

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **Enable web dashboard** | `web_enabled` | Off | On / Off | Serves the dashboard on this box's own address. Off by default; once it is on, anything on the same network can reach it, so do not forward its port to the internet. |
| **Port** | `web_port` | 8099 | 1024 – 65535 | The port the dashboard listens on. Leave 8080 alone - Kodi's own web server usually has it. *(enabled when `web_enabled` is on)* |
| **Show address and token** | `web_info` | — | button → `RunScript(script.tinyppi,web_info)` | Shows the address to open in a browser, together with the current token. *(enabled when `web_enabled` is on)* |
| **Access token** | `web_token` | (empty – generated on first use) |  | The key the dashboard asks for. Switching a VS10 mode from the browser always needs it; reading needs it only when the setting below says so. |
| **Generate a new token** | `web_token_new` | — | button → `RunScript(script.tinyppi,web_token)` | Replaces the token with a fresh one. Every browser still holding the old one is logged out. |
| **Show the Dolby Vision metadata view** | `web_metadata` | On | On / Off | Adds the full metadata list to the dashboard - every block the stream's side data carries, the same one the on-screen view shows. It is only built for a Dolby Vision source, and it is the largest thing the page sends, so turn it off on a slow network. *(enabled when `web_enabled` is on)* |
| **Show the film library** | `web_library` | On | On / Off | Offers the films in the video library on the dashboard (whether or not something is playing). A press starts one on the box. Also needs *Allow VS10 switching from the dashboard*. *(enabled when `web_enabled` is on)* |
| **Show the series library** | `web_series` | On | On / Off | Offers the series in the video library on the dashboard (whether or not something is playing). A press opens one and starts an episode on the box. Also needs *Allow VS10 switching from the dashboard*. *(enabled when `web_enabled` is on)* |
| **Require the token for reading too** | `web_auth_read` | Off | On / Off | Asks for the token before showing anything at all, not just before switching a mode. Turn this on when the box is on a shared network. |
| **Allow VS10 switching from the dashboard** | `web_allow_control` | On | On / Off | Shows the VS10 output modes for the playing source in the browser, so the mode can be switched from a phone. The token is required either way. |

**Ratings**

| Setting | ID | Default | Values | Description |
|---|---|---|---|---|
| **MDBList API key** | `web_mdblist_key` | (empty) | text (hidden) | With a free key from mdblist.com (Preferences → API), the overview card shows the ratings MDBList gathers for a film: IMDb, TMDb, Trakt, Letterboxd, Rotten Tomatoes, Metacritic and more. To ask, the film's IMDb or TMDb id is sent to MDBList. Left empty, the card shows the ratings Kodi's library holds. See [Ratings from MDBList](Web-Dashboard#ratings-from-mdblist). |
| **Fill in Rotten Tomatoes from WhatsOn** | `web_whatson` | On | On / Off | Where neither MDBList nor the library has Rotten Tomatoes' Tomatometer or Popcornmeter for a film, the overview card asks WhatsOn (whatson-api.onrender.com, free for non-commercial use, no key needed) for the missing one. To ask, the film's IMDb or TMDb id is sent to WhatsOn, once per film and only when a rating is missing. See [Rotten Tomatoes from WhatsOn](Web-Dashboard#rotten-tomatoes-from-whatson). |

Changes here are applied to the running server immediately: switching the
dashboard on or off, changing the port, or changing the token restarts or
reconfigures it without a Kodi restart.
