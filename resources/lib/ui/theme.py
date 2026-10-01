# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Color theme engine.

Maps the user's color settings onto ARGB hex strings and publishes them as
Home-window (10000) properties, consumed by the skin via
``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]``.

Each color is chosen in Kodi's own color picker, opened on the add-on's palette
from the setting's row (see ``pick_color``).
"""

import json
import os
import re
from typing import NamedTuple

import xbmc
import xbmcgui
import xbmcvfs
from core import settings
from core.constants import ADDON_ID, PROFILE_DIR
from core.utils import home_window

# Palette for text-based elements; index matches _TEXT_LABELS.
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

# The strings naming each palette's colors, index for index.
_TEXT_LABELS = (
    *range(32120, 32130), *range(32150, 32170), *range(32200, 32220),
)
_BACKGROUND_LABELS = (
    *range(32130, 32140), *range(32170, 32190), *range(32220, 32240),
)
# Black (default) and white lead, as in _DIALOG_FOCUS_TEXT_COLORS: the
# background palette's black and the text palette's white, by name.
_DIALOG_FOCUS_TEXT_LABELS = (32131, 32120) + _TEXT_LABELS[1:]

# What the picker draws a background as, and the dot its row shows: a brighter
# stand-in for each shade, index for index.  The shades themselves are all but
# black, and a picker full of black tiles would offer nothing to choose between.
_BACKGROUND_SWATCHES = (
    "FF2A2E33", "FF000000", "FF3A1414", "FF3A2A12", "FF3A360F",
    "FF123A12", "FF0F3A3A", "FF12203A", "FF26123A", "FF444444",
    "FF0F3A36", "FF0F2A3A", "FF1E2240", "FF2E1E40", "FF3A1E3A",
    "FF3A1E2C", "FF3A1E24", "FF3A2A1E", "FF2A2E12", "FF223A12",
    "FF123A28", "FF12303A", "FF222E33", "FF12182E", "FF3A1212",
    "FF1A1A2A", "FF2E2418", "FF1E1E1E", "FF2C2C30", "FF2E343A",
    "FF3E2820", "FF3E2C10", "FF383010", "FF303814", "FF1C3420",
    "FF143424", "FF203814", "FF143838", "FF143830", "FF142C3E",
    "FF1C2040", "FF2A2040", "FF341E38", "FF301C34", "FF3E1428",
    "FF3E1424", "FF3E1C14", "FF342E28", "FF28341C", "FF242E34",
)


# Brightness unit labels for the L6 metadata values ("" = hidden).
_UNIT_LABELS = (
    "cd/m²",  # 0  cd/m² (default)
    "nits",   # 1  nits
    "",       # 2  Hidden
)


# Palette index each color setting starts out on.  Mirrors <default> in
# settings.xml; unlisted settings start on 0.
_DEFAULT_COLOR_INDEX = {
    "convert_yes_color": 34,  # Forest
    "convert_no_color":  25,  # Crimson
    "fel_color":         34,  # Forest
    "mel_color":         31,  # Tangerine
    "output_changed_color": 7,  # Light blue
    "metadata_changed_color": 7,  # Light blue
    "splash_start_convert_dot_color":   34,  # Forest
    "splash_osd_convert_dot_color":     34,  # Forest
    "splash_tinyppi_convert_dot_color": 34,  # Forest
    "splash_start_fel_color":   34,  # Forest
    "splash_osd_fel_color":     34,  # Forest
    "splash_tinyppi_fel_color": 34,  # Forest
    "splash_start_mel_color":   31,  # Tangerine
    "splash_osd_mel_color":     31,  # Tangerine
    "splash_tinyppi_mel_color": 31,  # Tangerine
}

# How a color setting stores its choice.  The value is also what the settings
# list shows on the setting's row, so it is written to read as one: a swatch,
# then a reference to the string naming the palette color -- which the list
# resolves in whatever language Kodi is set to -- or the HEX color's code:
#
#     [COLOR=FF82B1FF]●[/COLOR] $ADDON[script.tinyppi 32127]
#     [COLOR=FF5733AA]●[/COLOR] #5733AA
#
# The setting's own default -- and only that color -- carries "(Default)"
# after its name, a string of its own referenced the same way, so no color
# needs a second string for it.  The row says which color is set without the
# settings carrying fifty options per color, which is what used to make
# settings.xml some 360 KB, parsed in full by every ``xbmcaddon.Addon()`` (see
# core.settings).
_STORED_RE     = re.compile(r"^\[COLOR=[0-9A-Fa-f]{8}\]●\[/COLOR\] (.*)$")
_NAME_REF      = "$ADDON[" + ADDON_ID + " {}]"
_NAME_REF_RE   = re.compile(r"\$ADDON\[" + re.escape(ADDON_ID) + r" (\d+)\]")
_DEFAULT_LABEL = 32589  # (Default)
_DEFAULT_MARK  = " " + _NAME_REF.format(_DEFAULT_LABEL)

# How the settings stored a color before the picker: the palette index, or 999
# for a HEX color whose ARGB was kept in a JSON file beside them.  Read only to
# carry a profile over (see migrate_legacy_colors) and until that has run.
_LEGACY_CUSTOM      = "999"
_LEGACY_CUSTOM_FILE = f"{PROFILE_DIR}/custom_colors.json"

# The picker's last tile, which asks for a HEX color instead of being one.
#
# The picker hands back the second label of the tile that was pressed, exactly
# as it was given, so the tile is told apart from the palette by that label
# alone: in lower case, where every palette tile's is in upper case.  It shows
# the HEX color in force, or nothing at all -- fully transparent -- while the
# setting is on a palette color.
_HEX_TILE_LABEL = 32241  # HEX color
_HEX_TILE_EMPTY = "00000000"

_HEX6_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
_HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def _notify(addon, message_id: int, icon: str, duration: int) -> None:
    """Show a localized TinyPPI settings notification."""
    xbmcgui.Dialog().notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(message_id),
        icon,
        duration,
    )


def _load_legacy_custom() -> dict:
    """Return the HEX colors the settings kept before the picker, keyed by
    setting id, or an empty dict when there are none."""
    try:
        with open(xbmcvfs.translatePath(_LEGACY_CUSTOM_FILE),
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):  # no file, or none worth reading
        return {}
    return data if isinstance(data, dict) else {}


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


class _ColorSetting(NamedTuple):
    """What one color setting can be set to."""

    palette: tuple   # the ARGB each palette choice publishes
    labels: tuple    # the string naming each choice, index for index
    swatches: tuple  # the ARGB each choice is drawn as, index for index
    index_of: dict   # label id -> index, for reading a stored choice back
    default: int     # the index the setting starts out on


def _encode(spec: _ColorSetting, index: int, rgb: str = "") -> str:
    """Return the stored value choosing palette color ``index``, or the 6-digit
    HEX color ``rgb`` when one is given."""
    if rgb:
        return f"[COLOR=FF{rgb}]●[/COLOR] #{rgb}"
    name = _NAME_REF.format(spec.labels[index])
    mark = _DEFAULT_MARK if index == spec.default else ""
    return f"[COLOR={spec.swatches[index]}]●[/COLOR] {name}{mark}"


def _decode(spec: _ColorSetting, value: str, legacy_hex: str = "") -> tuple[int, str]:
    """Return what a stored value chooses: ``(index, "")`` for a palette color,
    ``(-1, "RRGGBB")`` for a HEX one.

    Anything that cannot be read is the setting's default rather than palette
    index 0, which for a text color is white: an unset highlight would come out
    the same color as the values it has to stand out from.  ``legacy_hex`` is
    what the old JSON file holds for the setting, needed only while its value
    still reads 999.
    """
    match = _STORED_RE.match(value)
    if match:
        text = match.group(1)
        if text.startswith("#") and _HEX6_RE.match(text[1:]):
            return -1, text[1:].upper()

    # Read by the first string it names, the color's own: the swatch in front
    # of it and the "(Default)" after it are only there to be seen.
    match = _NAME_REF_RE.search(value)
    if match:
        index = spec.index_of.get(int(match.group(1)))
        return (spec.default if index is None else index), ""

    if value == _LEGACY_CUSTOM:
        stored = str(legacy_hex).strip().upper()
        if _HEX8_RE.match(stored):
            return -1, stored[2:]
        return spec.default, ""
    if value.isdigit() and int(value) < len(spec.palette):
        return int(value), ""
    return spec.default, ""


def _resolve(spec: _ColorSetting, value: str, legacy_hex: str = "") -> str:
    """Resolve a stored color value to an ARGB hex string."""
    index, rgb = _decode(spec, value, legacy_hex)
    return spec.palette[index] if index >= 0 else "FF" + rgb


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
    # The dialog's buttons carry their own unfocused text colour rather than
    # borrowing the overlay's description colour, so the one can be set
    # without moving the other.
    ("TinyPPI.DialogTextColor",       _TEXT_COLORS, "dialog_text_color"),
    ("TinyPPI.DialogFocusColor",      _DIALOG_FOCUS_COLORS, "dialog_focus_color"),
    (
        "TinyPPI.DialogFocusTextColor",
        _DIALOG_FOCUS_TEXT_COLORS,
        "dialog_focus_text_color",
    ),
)


def _color_setting(palette: tuple, setting_id: str) -> _ColorSetting:
    """Describe one color setting: its palette, the names and swatches it is
    offered with, and where it starts out."""
    if palette is _BACKGROUND_COLORS:
        labels, swatches = _BACKGROUND_LABELS, _BACKGROUND_SWATCHES
    elif palette is _DIALOG_FOCUS_TEXT_COLORS:
        labels, swatches = _DIALOG_FOCUS_TEXT_LABELS, _DIALOG_FOCUS_TEXT_COLORS
    else:
        # Every other palette is a text color's hues under another alpha, or
        # with a lead of its own that is still offered as the white it is.
        labels, swatches = _TEXT_LABELS, _TEXT_COLORS
    index_of = {label: index for index, label in enumerate(labels)}
    return _ColorSetting(palette, labels, swatches, index_of,
                         _DEFAULT_COLOR_INDEX.get(setting_id, 0))


# Every color setting by id, built once from the table above.
_COLOR_SETTINGS = {
    setting_id: _color_setting(palette, setting_id)
    for _property, palette, setting_id in _THEME_PROPERTIES
}


def apply_theme(home, addon=None, overrides=None) -> None:
    """Read the color settings and publish them as Home-window properties.

    Call before opening the overlay so the skin can resolve every color.
    """
    addon = addon or settings.addon()

    values = [
        (property_name, setting_id, _setting_value(addon, setting_id, overrides))
        for property_name, _palette, setting_id in _THEME_PROPERTIES
    ]
    # Only a profile the migration has not reached yet still points into the
    # old JSON file, so it is read only then rather than on every pass -- this
    # runs on the splash controller's four-times-a-second poll.
    legacy = (_load_legacy_custom()
              if any(value == _LEGACY_CUSTOM for _name, _id, value in values)
              else {})

    for property_name, setting_id, value in values:
        color = _resolve(_COLOR_SETTINGS[setting_id], value,
                         legacy.get(setting_id, ""))
        # The per-element opacity slider overrides the palette alpha, so the
        # chosen color only supplies the RGB channels.
        alpha = _opacity_alpha(
            addon,
            _opacity_setting(setting_id),
            _DEFAULT_OPACITIES.get(setting_id, _DEFAULT_OPACITY),
            overrides,
        )
        home.setProperty(property_name, alpha + color[2:])

    home.setProperty(
        "TinyPPI.UnitLabel",
        _pick(_UNIT_LABELS, _setting_value(addon, "unit_type", overrides)),
    )


def _ask_hex(addon, spec: _ColorSetting, current_rgb: str) -> str | None:
    """Ask for a 6-digit HEX color and return the value storing it.

    Starts from the color in force, so a shade can be nudged rather than typed
    out again.  None when the keyboard is cancelled; an invalid entry falls back
    to the setting's default, and says so.
    """
    keyboard = xbmc.Keyboard(current_rgb, addon.getLocalizedString(32243))
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None

    raw = keyboard.getText().strip().lstrip("#").upper()
    if not _HEX6_RE.match(raw):
        _notify(addon, 32244, xbmcgui.NOTIFICATION_ERROR, 4000)
        return _encode(spec, spec.default)

    _notify(addon, 32245, xbmcgui.NOTIFICATION_INFO, 3000)
    return _encode(spec, -1, raw)


def pick_color(setting_id: str, heading_id: str = "") -> None:
    """Offer a color setting's palette in Kodi's color picker and store the pick.

    Invoked from the setting's own row, via
    ``RunScript(script.tinyppi,pick_color,<setting id>,<label id>)``, the label
    being the setting's own to head the picker with.

    The picker draws the palette with the names and swatches the setting's row
    shows, plus a last tile that asks for a HEX color instead.  Cancelling it,
    or the keyboard behind that tile, leaves the setting as it was.
    """
    spec = _COLOR_SETTINGS.get(setting_id)
    if spec is None:
        return
    addon = settings.addon()

    value = addon.getSetting(setting_id)
    legacy_hex = (_load_legacy_custom().get(setting_id, "")
                  if value == _LEGACY_CUSTOM else "")
    index, rgb = _decode(spec, value, legacy_hex)

    default_mark = addon.getLocalizedString(_DEFAULT_LABEL)
    tiles = []
    for position, label_id in enumerate(spec.labels):
        name = addon.getLocalizedString(label_id)
        if position == spec.default:
            name = f"{name} {default_mark}"
        tiles.append(xbmcgui.ListItem(name, spec.swatches[position],
                                      offscreen=True))
    hex_tile = ("ff" + rgb.lower()) if rgb else _HEX_TILE_EMPTY
    tiles.append(xbmcgui.ListItem(addon.getLocalizedString(_HEX_TILE_LABEL),
                                  hex_tile, offscreen=True))

    heading = (addon.getLocalizedString(int(heading_id))
               if heading_id.isdigit() else "")
    chosen = xbmcgui.Dialog().colorpicker(
        heading, hex_tile if rgb else spec.swatches[index], colorlist=tiles,
    )
    if not chosen:
        return

    if chosen == hex_tile:
        current = rgb or spec.palette[index][2:]
        new_value = _ask_hex(addon, spec, current)
        if new_value is None:
            return
    elif chosen in spec.swatches:
        new_value = _encode(spec, spec.swatches.index(chosen))
    else:
        return

    addon.setSetting(setting_id, new_value)

    # Re-publish so an already-open overlay updates too.  The settings dialog
    # keeps the new value to itself until it is closed, so it is handed over
    # rather than read back.
    try:
        apply_theme(home_window(), addon, overrides={setting_id: new_value})
    except Exception:  # best effort, never block the change
        pass


def migrate_legacy_colors(addon=None) -> int:
    """Bring every color setting's stored value into the form it is written in.

    Kodi moves a value saved as the default over to the new default by itself,
    so what is left is a color somebody chose in an older form -- the palette
    index the option lists stored, or the 999 that pointed into the JSON file --
    and either would show on the setting's row as the bare number.  Each is
    rewritten once, here, and the JSON file is removed once nothing reads it
    any more.  A value already in its form is left alone, so from then on this
    only reads.

    Returns how many settings were rewritten.
    """
    addon = addon or settings.addon()

    legacy = None
    moved = 0
    for setting_id, spec in _COLOR_SETTINGS.items():
        value = addon.getSetting(setting_id)
        if value == _LEGACY_CUSTOM and legacy is None:
            legacy = _load_legacy_custom()
        stored = _encode(spec, *_decode(spec, value,
                                        (legacy or {}).get(setting_id, "")))
        if stored == value:
            continue
        addon.setSetting(setting_id, stored)
        moved += 1

    # Reached only once every setting above has been written.
    try:
        os.remove(xbmcvfs.translatePath(_LEGACY_CUSTOM_FILE))
    except OSError:
        pass  # none left, or there never was one
    return moved
