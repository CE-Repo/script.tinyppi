# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Color theme engine.

Maps the user's color settings onto ARGB hex strings and publishes them as
Home-window (10000) properties, consumed by the skin via
``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]``.
"""

import json
import os
import re

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# Palette for text-based elements; index matches the settings.xml <option> order.
_TEXT_COLORS = (
    "FFEDEDED",  # 0  White
    "FFE0E0E0",  # 1  Light gray
    "FFFF8A80",  # 2  Red
    "FFFFCC80",  # 3  Orange
    "FFFFFF8D",  # 4  Yellow
    "FFB9F6CA",  # 5  Green
    "FF84FFFF",  # 6  Cyan
    "FF82B1FF",  # 7  Blue
    "FFE1BEE7",  # 8  Purple
    "FFFF80AB",  # 9  Pink
    "FFFF8A65",  # 10 Coral
    "FFFFAB91",  # 11 Salmon
    "FFFFD54F",  # 12 Amber
    "FFFFE082",  # 13 Gold
    "FFCCFF90",  # 14 Lime
    "FFA7FFEB",  # 15 Mint
    "FF80CBC4",  # 16 Teal
    "FF80D8FF",  # 17 Sky blue
    "FF40C4FF",  # 18 Azure
    "FF8C9EFF",  # 19 Indigo
    "FFB388FF",  # 20 Violet
    "FFD1C4E9",  # 21 Lavender
    "FFEA80FC",  # 22 Magenta
    "FFF48FB1",  # 23 Fuchsia
    "FFF06292",  # 24 Rose
    "FFFF5252",  # 25 Crimson
    "FFBCAAA4",  # 26 Brown
    "FFDCE775",  # 27 Olive
    "FFB0BEC5",  # 28 Slate
    "FFCFD8DC",  # 29 Silver
    "FFFFCCBC",  # 30 Peach
    "FFFFB74D",  # 31 Tangerine
    "FFE4C441",  # 32 Mustard
    "FFE6EE9C",  # 33 Chartreuse
    "FF81C784",  # 34 Forest
    "FF69F0AE",  # 35 Emerald
    "FFB2FF59",  # 36 Spring
    "FF18FFFF",  # 37 Aqua
    "FF64FFDA",  # 38 Turquoise
    "FF4FC3F7",  # 39 Cerulean
    "FF536DFE",  # 40 Cobalt
    "FFB39DDB",  # 41 Periwinkle
    "FFCE93D8",  # 42 Plum
    "FFBA68C8",  # 43 Orchid
    "FFFF4081",  # 44 Raspberry
    "FFFF5C8D",  # 45 Watermelon
    "FFFF6E40",  # 46 Scarlet
    "FFD7CCC8",  # 47 Sand
    "FFC5E1A5",  # 48 Pistachio
    "FF90A4AE",  # 49 Cadet
)

# VS10 dialog focused-button highlight (texturefocus); index 0 is pure white.
_DIALOG_FOCUS_COLORS = ("FFFFFFFF",) + _TEXT_COLORS[1:]

# VS10 dialog focused-button text (focusedcolor); black default and white lead.
_DIALOG_FOCUS_TEXT_COLORS = (
    "FF000000",  # 0  Black (default)
    "FFFFFFFF",  # 1  White
) + _TEXT_COLORS[1:]

# Channel layout graphic and its active channels; index 0 is pure white, so the
# defaults reproduce the skin's untinted look.
_CHANNEL_COLORS = ("FFFFFFFF",) + _TEXT_COLORS[1:]

# Inline detail accents: _TEXT_COLORS hues at alpha B3 (~70%).
_ACCENT_COLORS = tuple("B3" + color[2:] for color in _TEXT_COLORS)

# Separator lines: _TEXT_COLORS hues at alpha 26 (~15%); index 0 keeps the
# neutral gray default.
_LINE_COLORS = ("26808080",) + tuple(
    "26" + color[2:] for color in _TEXT_COLORS[1:]
)

# Modern background: semi-transparent dark shades (alpha FA).
_BACKGROUND_COLORS = (
    "FA15181A",  # 0  Charcoal (default)
    "E6000000",  # 1  Black
    "FA1A0E0E",  # 2  Dark red
    "FA1A130A",  # 3  Dark orange
    "FA1A180A",  # 4  Dark yellow
    "FA0E1A0E",  # 5  Dark green
    "FA0A1A1A",  # 6  Dark cyan
    "FA0E121A",  # 7  Dark blue
    "FA140E1A",  # 8  Dark purple
    "FA242424",  # 9  Dark gray
    "FA0A1A18",  # 10 Dark teal
    "FA0A151A",  # 11 Dark sky
    "FA10121F",  # 12 Dark indigo
    "FA17101F",  # 13 Dark violet
    "FA1A0E1A",  # 14 Dark magenta
    "FA1F0E16",  # 15 Dark pink
    "FA1F0E12",  # 16 Dark rose
    "FA1A130F",  # 17 Dark brown
    "FA15170A",  # 18 Dark olive
    "FA121A0A",  # 19 Dark lime
    "FA0A1A14",  # 20 Dark mint
    "FA0A171F",  # 21 Dark azure
    "FA12171A",  # 22 Dark slate
    "FA0A0E1A",  # 23 Dark navy
    "FA1F0A0A",  # 24 Dark maroon
    "FA0D0D14",  # 25 Midnight
    "FA1A1410",  # 26 Espresso
    "FA121212",  # 27 Onyx
    "FA1C1C1E",  # 28 Graphite
    "FA1A1D20",  # 29 Steel
    "FA1F1410",  # 30 Dark peach
    "FA1F1608",  # 31 Dark tangerine
    "FA1C1808",  # 32 Dark mustard
    "FA181C0A",  # 33 Dark chartreuse
    "FA0E1A10",  # 34 Dark forest
    "FA0A1A12",  # 35 Dark emerald
    "FA101C0A",  # 36 Dark spring
    "FA0A1C1C",  # 37 Dark aqua
    "FA0A1C18",  # 38 Dark turquoise
    "FA0A161F",  # 39 Dark cerulean
    "FA0E1020",  # 40 Dark cobalt
    "FA15101F",  # 41 Dark periwinkle
    "FA1A0F1C",  # 42 Dark plum
    "FA180E1A",  # 43 Dark orchid
    "FA1F0A14",  # 44 Dark raspberry
    "FA1F0A12",  # 45 Dark watermelon
    "FA1F0E0A",  # 46 Dark scarlet
    "FA1A1714",  # 47 Dark sand
    "FA141A0E",  # 48 Dark pistachio
    "FA12171A",  # 49 Dark cadet
)


# Brightness unit labels for the L6 metadata values ("" = hidden).
_UNIT_LABELS = (
    "cd/m²",  # 0  cd/m² (default)
    "nits",   # 1  nits
    "",       # 2  Hidden
)


# Setting option marking a color as a custom HEX value; the actual 8-digit ARGB
# hex is stored in the JSON file below (Kodi rejects control-less storage settings).
_CUSTOM_INDEX = "999"

# Palette index each color setting falls back to when its custom HEX is cleared
# or invalid.  Mirrors <default> in settings.xml; unlisted settings default to 0.
_DEFAULT_COLOR_INDEX = {
    "convert_yes_color": "34",  # Forest
    "convert_no_color":  "25",  # Crimson
    "fel_color":         "34",  # Forest
    "mel_color":         "31",  # Tangerine
    "output_changed_color": "7",  # Light blue
    "metadata_changed_color": "7",  # Light blue
    "splash_start_convert_dot_color":   "34",  # Forest
    "splash_osd_convert_dot_color":     "34",  # Forest
    "splash_tinyppi_convert_dot_color": "34",  # Forest
    "splash_start_fel_color":   "34",  # Forest
    "splash_osd_fel_color":     "34",  # Forest
    "splash_tinyppi_fel_color": "34",  # Forest
    "splash_start_mel_color":   "31",  # Tangerine
    "splash_osd_mel_color":     "31",  # Tangerine
    "splash_tinyppi_mel_color": "31",  # Tangerine
}

# Custom HEX colors (8-digit ARGB), keyed by setting id, persisted as JSON in
# the add-on profile directory.
_CUSTOM_FILE = "special://profile/addon_data/script.tinyppi/custom_colors.json"

# Alpha prepended to a 6-digit custom HEX, keyed by setting id (default FF).
_CUSTOM_ALPHA = {
    "background_color":        "FA",  # Modern background shades
    "dialog_background_color": "FA",  # VS10 dialog panel background shades
    "dialog_global_background_color": "FA",  # VS10 dialog full-screen background shades
    "global_background_color": "FA",  # full-screen global background shades
    "channel_background_color": "FA",  # DV channel panel background shades
    "channel_layout_color":     "54",  # speaker layout graphic (~33%)
    "accent_color":            "B3",  # dimmed detail accents (~70%)
    "line_color":              "26",  # faint separator lines (~15%)
    "dialog_line_color":       "26",  # faint VS10 dialog separator lines (~15%)
    # The metadata view's own shades, matching the elements they stand in for.
    "metadata_global_background_color": "FA",
    "metadata_background_color":        "FA",
    "metadata_line_color":              "26",
    "metadata_focus_color":             "26",
}
_DEFAULT_ALPHA = "FF"

_HEX6_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
_HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")

# Suffix of the per-color "HEX color" action button.  Its value (a ● swatch +
# HEX) is rendered as the row's label2 so the settings dialog can preview the
# chosen color without the Home-window properties (live only while the overlay
# is open).
_CUSTOM_BTN_SUFFIX = "_custom_btn"


def _custom_btn_label(raw6: str) -> str:
    """Return the ``label2`` markup previewing a 6-digit HEX color."""
    return f"[COLOR=FF{raw6}]●[/COLOR] #{raw6}"


def _notify(addon, message_id: int, icon: str, duration: int) -> None:
    """Show a localized TinyPPI settings notification."""
    xbmcgui.Dialog().notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(message_id),
        icon,
        duration,
    )


# Last (mtime, size) read and the mapping it yielded.  apply_theme() runs on
# the splash controller's four-times-a-second poll, so without this every one
# of those re-read and re-parsed the JSON off disk; keying on the stamp keeps a
# colour written by custom_color() picked up on the very next call.
_custom_cache: tuple[tuple, dict] | None = None


def _load_custom() -> dict:
    """Return the stored custom colors mapping, or an empty dict."""
    global _custom_cache

    try:
        stat = os.stat(xbmcvfs.translatePath(_CUSTOM_FILE))
    except OSError:  # no file yet -> no custom colors
        _custom_cache = None
        return {}

    stamp = (stat.st_mtime, stat.st_size)
    if _custom_cache is not None and _custom_cache[0] == stamp:
        # Copied out: callers (custom_color) mutate what they get back.
        return dict(_custom_cache[1])

    try:
        with open(xbmcvfs.translatePath(_CUSTOM_FILE), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # corrupt/unreadable file -> ignore
        return {}
    if not isinstance(data, dict):
        return {}

    _custom_cache = (stamp, data)
    return dict(data)


def _save_custom(data: dict) -> None:
    """Persist the custom colors mapping to the profile directory."""
    path = xbmcvfs.translatePath(_CUSTOM_FILE)
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _pick(palette: tuple, value: str) -> str:
    """Return ``palette[value]``, falling back to index 0 on bad input."""
    try:
        return palette[int(value)]
    except (ValueError, TypeError, IndexError):
        return palette[0]


# Fallback opacity (percent) when a setting is missing or invalid.
_DEFAULT_OPACITY = 100

# Per-element opacity defaults (percent), keyed by color setting id, reproducing
# each element's palette alpha.  Unlisted elements use _DEFAULT_OPACITY (100 %).
_DEFAULT_OPACITIES = {
    "background_color":        98,  # FA – Modern panel background
    "dialog_background_color": 98,  # FA – VS10 dialog panel background
    "dialog_global_background_color": 0,  # off until the user raises the slider
    "global_background_color":  0,  # off until the user raises the slider
    "channel_background_color": 98,  # FA – DV channel panel background
    "channel_layout_color":     33,  # 54 – speaker layout graphic
    "accent_color":            70,  # B3 – dimmed inline detail accents
    "line_color":              15,  # 26 – faint separator lines
    "metadata_global_background_color": 0,
    "metadata_background_color":    98,
    "metadata_line_color":          15,
    "metadata_focus_color":         15,
    "dialog_line_color":       15,  # 26 – faint VS10 dialog separator lines
    # Per-context codec-logo panel (FA – Charcoal) and divider (59 – faint).
    "splash_start_bg_color":        98,
    "splash_start_divider_color":   35,
    "splash_osd_bg_color":          98,
    "splash_osd_divider_color":     35,
    "splash_tinyppi_bg_color":      98,
    "splash_tinyppi_divider_color": 35,
    # Dolby Vision layer-indicator pill: FEL/MEL fully opaque, any other DV
    # profile faint, out of the box.
    "splash_start_fel_color":   100,
    "splash_start_mel_color":   100,
    "splash_start_dv_color":    20,
    "splash_osd_fel_color":     100,
    "splash_osd_mel_color":     100,
    "splash_osd_dv_color":      20,
    "splash_tinyppi_fel_color": 100,
    "splash_tinyppi_mel_color": 100,
    "splash_tinyppi_dv_color":  20,
}


def _opacity_setting(color_setting_id: str) -> str:
    """Return the opacity slider id paired with a ``*_color`` setting."""
    return color_setting_id[: -len("_color")] + "_opacity"


def _opacity_alpha(addon, setting_id, default, overrides=None) -> str:
    """Return the 2-digit hex alpha for a 0–100 % opacity slider (``default``
    percent when missing/invalid)."""
    try:
        percent = int(_setting_value(addon, setting_id, overrides))
    except (ValueError, TypeError):
        percent = default
    percent = max(0, min(100, percent))
    # Round half up so defaults reproduce the palette alpha exactly (70 % -> B3).
    return f"{int(percent * 255 / 100 + 0.5):02X}"


def _setting_value(addon, setting_id: str, overrides) -> str:
    """Return a setting value, allowing fresh writes to bypass Kodi's cache."""
    if overrides and setting_id in overrides:
        return str(overrides[setting_id])
    return addon.getSetting(setting_id)


def _resolve(palette: tuple, addon, setting_id: str, custom: dict, overrides=None) -> str:
    """Resolve a color setting to an ARGB hex string.

    The custom marker (999) uses the stored 8-digit hex from ``custom``, falling
    back to the palette default when it is invalid or missing.
    """
    value = _setting_value(addon, setting_id, overrides)
    if value == _CUSTOM_INDEX:
        stored = str(custom.get(setting_id, "")).strip().upper()
        if _HEX8_RE.match(stored):
            return stored
        return _pick(palette, _DEFAULT_COLOR_INDEX.get(setting_id, "0"))
    if not value:
        # Unset -- a setting newer than the profile that stores it.  Reads as
        # the default settings.xml gives it rather than as palette index 0,
        # which for a text color is white: the metadata view's highlight would
        # come out the same color as the values it has to stand out from.
        value = _DEFAULT_COLOR_INDEX.get(setting_id, "0")
    return _pick(palette, value)


_THEME_PROPERTIES = (
    ("TinyPPI.TitleColor",            _TEXT_COLORS, "title_color"),
    ("TinyPPI.FilenameColor",         _TEXT_COLORS, "filename_color"),
    ("TinyPPI.IconColor",             _TEXT_COLORS, "icon_color"),
    ("TinyPPI.HeaderColor",           _TEXT_COLORS, "header_color"),
    ("TinyPPI.HeaderIconColor",       _TEXT_COLORS, "header_icon_color"),
    ("TinyPPI.DescriptionColor",      _TEXT_COLORS, "description_color"),
    ("TinyPPI.OutputColor",           _TEXT_COLORS, "output_color"),
    ("TinyPPI.OutputChangedColor",    _TEXT_COLORS, "output_changed_color"),
    ("TinyPPI.ProgressColor",         _TEXT_COLORS, "progress_color"),
    ("TinyPPI.FpsColor",              _TEXT_COLORS, "fps_color"),
    ("TinyPPI.UnitColor",             _TEXT_COLORS, "unit_color"),
    ("TinyPPI.AccentColor",           _ACCENT_COLORS, "accent_color"),
    ("TinyPPI.ConvertYesColor",       _TEXT_COLORS, "convert_yes_color"),
    ("TinyPPI.ConvertNoColor",        _TEXT_COLORS, "convert_no_color"),
    ("TinyPPI.FelColor",              _TEXT_COLORS, "fel_color"),
    ("TinyPPI.MelColor",              _TEXT_COLORS, "mel_color"),
    ("TinyPPI.BackgroundColor",       _BACKGROUND_COLORS, "background_color"),
    ("TinyPPI.DialogBackgroundColor", _BACKGROUND_COLORS, "dialog_background_color"),
    ("TinyPPI.DialogGlobalBackgroundColor", _BACKGROUND_COLORS, "dialog_global_background_color"),
    ("TinyPPI.GlobalBackgroundColor", _BACKGROUND_COLORS, "global_background_color"),
    # Codec logos: an independent bg / video / audio / divider colour per context
    # (playback start, video OSD, TinyPPI overlay).
    ("TinyPPI.SplashStartBgColor",        _BACKGROUND_COLORS, "splash_start_bg_color"),
    ("TinyPPI.SplashStartVideoColor",     _TEXT_COLORS,       "splash_start_video_color"),
    ("TinyPPI.SplashStartAudioColor",     _TEXT_COLORS,       "splash_start_audio_color"),
    ("TinyPPI.SplashStartDividerColor",   _TEXT_COLORS,       "splash_start_divider_color"),
    ("TinyPPI.SplashStartConvertDotColor", _TEXT_COLORS,      "splash_start_convert_dot_color"),
    # Dolby Vision layer-indicator pill: one colour per FEL / MEL / other-profile
    # bucket, independent per context like the rest of the codec-logo tints.
    ("TinyPPI.SplashStartFelColor", _TEXT_COLORS, "splash_start_fel_color"),
    ("TinyPPI.SplashStartMelColor", _TEXT_COLORS, "splash_start_mel_color"),
    ("TinyPPI.SplashStartDvColor",  _TEXT_COLORS, "splash_start_dv_color"),
    ("TinyPPI.SplashOsdBgColor",          _BACKGROUND_COLORS, "splash_osd_bg_color"),
    ("TinyPPI.SplashOsdVideoColor",       _TEXT_COLORS,       "splash_osd_video_color"),
    ("TinyPPI.SplashOsdAudioColor",       _TEXT_COLORS,       "splash_osd_audio_color"),
    ("TinyPPI.SplashOsdDividerColor",     _TEXT_COLORS,       "splash_osd_divider_color"),
    ("TinyPPI.SplashOsdConvertDotColor",  _TEXT_COLORS,       "splash_osd_convert_dot_color"),
    ("TinyPPI.SplashOsdFelColor", _TEXT_COLORS, "splash_osd_fel_color"),
    ("TinyPPI.SplashOsdMelColor", _TEXT_COLORS, "splash_osd_mel_color"),
    ("TinyPPI.SplashOsdDvColor",  _TEXT_COLORS, "splash_osd_dv_color"),
    ("TinyPPI.SplashTinyppiBgColor",      _BACKGROUND_COLORS, "splash_tinyppi_bg_color"),
    ("TinyPPI.SplashTinyppiVideoColor",   _TEXT_COLORS,       "splash_tinyppi_video_color"),
    ("TinyPPI.SplashTinyppiAudioColor",   _TEXT_COLORS,       "splash_tinyppi_audio_color"),
    ("TinyPPI.SplashTinyppiDividerColor", _TEXT_COLORS,       "splash_tinyppi_divider_color"),
    ("TinyPPI.SplashTinyppiConvertDotColor", _TEXT_COLORS,    "splash_tinyppi_convert_dot_color"),
    ("TinyPPI.SplashTinyppiFelColor", _TEXT_COLORS, "splash_tinyppi_fel_color"),
    ("TinyPPI.SplashTinyppiMelColor", _TEXT_COLORS, "splash_tinyppi_mel_color"),
    ("TinyPPI.SplashTinyppiDvColor",  _TEXT_COLORS, "splash_tinyppi_dv_color"),
    # Channel layout: the DV panel background, the speaker layout graphic behind
    # the channels, and the active channels themselves.
    ("TinyPPI.ChannelBackgroundColor", _BACKGROUND_COLORS, "channel_background_color"),
    ("TinyPPI.ChannelLayoutColor",     _CHANNEL_COLORS,    "channel_layout_color"),
    ("TinyPPI.ChannelIconColor",       _CHANNEL_COLORS,    "channel_icon_color"),
    # Dolby Vision metadata view.  It draws nothing the overlay draws, so it
    # carries its own colour per element rather than borrowing the overlay's:
    # a view for reading a bitstream wants a different balance from one laid
    # over a film.
    ("TinyPPI.MetadataChangedColor",     _TEXT_COLORS, "metadata_changed_color"),
    ("TinyPPI.MetadataGlobalBackgroundColor",  _BACKGROUND_COLORS, "metadata_global_background_color"),
    ("TinyPPI.MetadataBackgroundColor",        _BACKGROUND_COLORS, "metadata_background_color"),
    ("TinyPPI.MetadataHeaderColor",            _TEXT_COLORS, "metadata_header_color"),
    ("TinyPPI.MetadataHeaderIconColor",        _TEXT_COLORS, "metadata_header_icon_color"),
    ("TinyPPI.MetadataTitleColor",             _TEXT_COLORS, "metadata_title_color"),
    ("TinyPPI.MetadataColumnColor",            _TEXT_COLORS, "metadata_column_color"),
    ("TinyPPI.MetadataNameColor",              _TEXT_COLORS, "metadata_name_color"),
    ("TinyPPI.MetadataValueColor",             _TEXT_COLORS, "metadata_value_color"),
    ("TinyPPI.MetadataLineColor",              _LINE_COLORS, "metadata_line_color"),
    ("TinyPPI.MetadataFocusColor",             _LINE_COLORS, "metadata_focus_color"),
    ("TinyPPI.MetadataScrollbarColor",         _TEXT_COLORS, "metadata_scrollbar_color"),
    ("TinyPPI.MetadataHintColor",              _TEXT_COLORS, "metadata_hint_color"),
    ("TinyPPI.LineColor",             _LINE_COLORS, "line_color"),
    ("TinyPPI.DialogHeaderColor",     _TEXT_COLORS, "dialog_header_color"),
    ("TinyPPI.DialogHeaderIconColor", _TEXT_COLORS, "dialog_header_icon_color"),
    ("TinyPPI.DialogLineColor",       _LINE_COLORS, "dialog_line_color"),
    ("TinyPPI.DialogFocusColor",      _DIALOG_FOCUS_COLORS, "dialog_focus_color"),
    (
        "TinyPPI.DialogFocusTextColor",
        _DIALOG_FOCUS_TEXT_COLORS,
        "dialog_focus_text_color",
    ),
)


def apply_theme(home, addon=None, overrides=None, custom=None) -> None:
    """Read the color settings and publish them as Home-window properties.

    Call before opening the overlay so the skin can resolve every color.
    """
    addon = addon or xbmcaddon.Addon()
    custom = _load_custom() if custom is None else custom

    for property_name, palette, setting_id in _THEME_PROPERTIES:
        value = _resolve(palette, addon, setting_id, custom, overrides)
        # The per-element opacity slider overrides the palette/custom alpha, so
        # the chosen HEX only supplies the RGB channels.
        alpha = _opacity_alpha(
            addon,
            _opacity_setting(setting_id),
            _DEFAULT_OPACITIES.get(setting_id, _DEFAULT_OPACITY),
            overrides,
        )
        home.setProperty(property_name, alpha + value[2:])

    home.setProperty(
        "TinyPPI.UnitLabel",
        _pick(_UNIT_LABELS, _setting_value(addon, "unit_type", overrides)),
    )


def custom_color(setting_id, addon=None) -> None:
    """Prompt for a custom 6-digit HEX color and store it for ``setting_id``.

    Valid input gets the per-setting alpha prepended, is saved to the JSON file,
    and switches the setting to the custom marker (999).  Invalid input notifies
    and falls back to the default.  Cancelling leaves the selection untouched.
    Invoked via ``RunScript(script.tinyppi,custom_color,<id>)``.
    """
    addon = addon or xbmcaddon.Addon()

    if not setting_id:
        return

    keyboard = xbmc.Keyboard("", addon.getLocalizedString(32243))
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return

    raw = keyboard.getText().strip().lstrip("#").upper()

    custom = _load_custom()

    if not _HEX6_RE.match(raw):
        # Invalid -> notify and fall back to this element's default color.
        fallback = _DEFAULT_COLOR_INDEX.get(setting_id, "0")
        custom.pop(setting_id, None)
        _save_custom(custom)
        addon.setSetting(setting_id, fallback)
        addon.setSetting(setting_id + _CUSTOM_BTN_SUFFIX, "")
        setting_value = fallback
        _notify(
            addon,
            32244,
            xbmcgui.NOTIFICATION_ERROR,
            4000,
        )
    else:
        alpha = _CUSTOM_ALPHA.get(setting_id, _DEFAULT_ALPHA)
        custom[setting_id] = alpha + raw
        _save_custom(custom)
        addon.setSetting(setting_id, _CUSTOM_INDEX)
        addon.setSetting(setting_id + _CUSTOM_BTN_SUFFIX, _custom_btn_label(raw))
        setting_value = _CUSTOM_INDEX
        _notify(
            addon,
            32245,
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )

    # Re-publish properties so an already-open overlay updates too.
    try:
        apply_theme(
            xbmcgui.Window(10000),
            addon,
            overrides={setting_id: setting_value},
            custom=custom,
        )
    except Exception:  # best effort, never block the change
        pass
