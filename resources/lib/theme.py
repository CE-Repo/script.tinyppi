"""
theme.py – Color theme engine for the TinyPPI overlay.

Maps the user's color choices from the add-on settings onto ARGB hex strings
and publishes them as Home-window (10000) properties.  The skin consumes them
via ``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]`` so colors can be
changed from the settings without editing any skin XML.
"""

import json
import os
import re

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# Palette for text-based elements (title, description, output, progress bar).
# The index matches the <option> order in resources/settings.xml.
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

# Palette for inline detail accents (the dimmed values shown in parentheses).
# Same hues as _TEXT_COLORS but at alpha B3 (~70%) so they stay subtle.
# The index matches the <option> order in resources/settings.xml.
_ACCENT_COLORS = (
    "B3EDEDED",  # 0  White (default)
    "B3E0E0E0",  # 1  Light gray
    "B3FF8A80",  # 2  Red
    "B3FFCC80",  # 3  Orange
    "B3FFFF8D",  # 4  Yellow
    "B3B9F6CA",  # 5  Green
    "B384FFFF",  # 6  Cyan
    "B382B1FF",  # 7  Blue
    "B3E1BEE7",  # 8  Purple
    "B3FF80AB",  # 9  Pink
    "B3FF8A65",  # 10 Coral
    "B3FFAB91",  # 11 Salmon
    "B3FFD54F",  # 12 Amber
    "B3FFE082",  # 13 Gold
    "B3CCFF90",  # 14 Lime
    "B3A7FFEB",  # 15 Mint
    "B380CBC4",  # 16 Teal
    "B380D8FF",  # 17 Sky blue
    "B340C4FF",  # 18 Azure
    "B38C9EFF",  # 19 Indigo
    "B3B388FF",  # 20 Violet
    "B3D1C4E9",  # 21 Lavender
    "B3EA80FC",  # 22 Magenta
    "B3F48FB1",  # 23 Fuchsia
    "B3F06292",  # 24 Rose
    "B3FF5252",  # 25 Crimson
    "B3BCAAA4",  # 26 Brown
    "B3DCE775",  # 27 Olive
    "B3B0BEC5",  # 28 Slate
    "B3CFD8DC",  # 29 Silver
    "B3FFCCBC",  # 30 Peach
    "B3FFB74D",  # 31 Tangerine
    "B3E4C441",  # 32 Mustard
    "B3E6EE9C",  # 33 Chartreuse
    "B381C784",  # 34 Forest
    "B369F0AE",  # 35 Emerald
    "B3B2FF59",  # 36 Spring
    "B318FFFF",  # 37 Aqua
    "B364FFDA",  # 38 Turquoise
    "B34FC3F7",  # 39 Cerulean
    "B3536DFE",  # 40 Cobalt
    "B3B39DDB",  # 41 Periwinkle
    "B3CE93D8",  # 42 Plum
    "B3BA68C8",  # 43 Orchid
    "B3FF4081",  # 44 Raspberry
    "B3FF5C8D",  # 45 Watermelon
    "B3FF6E40",  # 46 Scarlet
    "B3D7CCC8",  # 47 Sand
    "B3C5E1A5",  # 48 Pistachio
    "B390A4AE",  # 49 Cadet
)

# Palette for the separator lines (very faint dividers, alpha 26 ~ 15%).
# Same hues as _TEXT_COLORS but heavily dimmed so the lines stay subtle.
# The index matches the <option> order in resources/settings.xml.
_LINE_COLORS = (
    "26808080",  # 0  White (default)
    "26E0E0E0",  # 1  Light gray
    "26FF8A80",  # 2  Red
    "26FFCC80",  # 3  Orange
    "26FFFF8D",  # 4  Yellow
    "26B9F6CA",  # 5  Green
    "2684FFFF",  # 6  Cyan
    "2682B1FF",  # 7  Blue
    "26E1BEE7",  # 8  Purple
    "26FF80AB",  # 9  Pink
    "26FF8A65",  # 10 Coral
    "26FFAB91",  # 11 Salmon
    "26FFD54F",  # 12 Amber
    "26FFE082",  # 13 Gold
    "26CCFF90",  # 14 Lime
    "26A7FFEB",  # 15 Mint
    "2680CBC4",  # 16 Teal
    "2680D8FF",  # 17 Sky blue
    "2640C4FF",  # 18 Azure
    "268C9EFF",  # 19 Indigo
    "26B388FF",  # 20 Violet
    "26D1C4E9",  # 21 Lavender
    "26EA80FC",  # 22 Magenta
    "26F48FB1",  # 23 Fuchsia
    "26F06292",  # 24 Rose
    "26FF5252",  # 25 Crimson
    "26BCAAA4",  # 26 Brown
    "26DCE775",  # 27 Olive
    "26B0BEC5",  # 28 Slate
    "26CFD8DC",  # 29 Silver
    "26FFCCBC",  # 30 Peach
    "26FFB74D",  # 31 Tangerine
    "26E4C441",  # 32 Mustard
    "26E6EE9C",  # 33 Chartreuse
    "2681C784",  # 34 Forest
    "2669F0AE",  # 35 Emerald
    "26B2FF59",  # 36 Spring
    "2618FFFF",  # 37 Aqua
    "2664FFDA",  # 38 Turquoise
    "264FC3F7",  # 39 Cerulean
    "26536DFE",  # 40 Cobalt
    "26B39DDB",  # 41 Periwinkle
    "26CE93D8",  # 42 Plum
    "26BA68C8",  # 43 Orchid
    "26FF4081",  # 44 Raspberry
    "26FF5C8D",  # 45 Watermelon
    "26FF6E40",  # 46 Scarlet
    "26D7CCC8",  # 47 Sand
    "26C5E1A5",  # 48 Pistachio
    "2690A4AE",  # 49 Cadet
)

# Palette for the Modern background (semi-transparent dark shades, alpha FA).
# The index matches the <option> order in resources/settings.xml.
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


# Brightness unit labels for the L6 metadata values.
# The index matches the <option> order of ``unit_type`` in resources/settings.xml.
# An empty string means the unit is hidden.
_UNIT_LABELS = (
    "cd/m²",  # 0  cd/m² (default)
    "nits",   # 1  nits
    "",       # 2  Hidden
)


# All color settings managed on the Theme category, used by reset_colors().
# Their <default> in resources/settings.xml is 0, so resetting means "0".
_COLOR_SETTINGS = (
    "background_color",
    "title_color",
    "filename_color",
    "header_color",
    "icon_color",
    "chart_color",
    "description_color",
    "output_color",
    "fps_color",
    "progress_color",
    "accent_color",
    "unit_color",
    "line_color",
)


# Setting value (option) that marks a color as a user-defined custom HEX value.
# The integer color setting is set to this option so the list shows
# "Benutzerdefiniert"; the actual 8-digit ARGB hex is stored in the JSON file
# below (Kodi rejects control-less storage settings, so the hex cannot live in
# settings.xml).
_CUSTOM_INDEX = "999"

# Custom HEX colors, keyed by setting id (each value an 8-digit ARGB hex string),
# persisted as a JSON file in the add-on profile directory.
_CUSTOM_FILE = "special://profile/addon_data/script.tinyppi/custom_colors.json"

# Alpha channel prepended to a 6-digit custom HEX, keyed by setting id.
# Anything not listed uses full opacity (FF) so the 6-digit input becomes an
# 8-digit ARGB value internally.
_CUSTOM_ALPHA = {
    "background_color": "FA",  # Modern background shades
    "accent_color":     "B3",  # dimmed detail accents (~70%)
    "line_color":       "26",  # faint separator lines (~15%)
}
_DEFAULT_ALPHA = "FF"

_HEX6_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
_HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")

# Suffix of the per-color "HEX color" action button (see resources/settings.xml).
# The button is a string setting whose value Kodi renders as the row's label2.
# We store a self-contained swatch + HEX string there so the settings dialog can
# preview the chosen color (a full-opacity ● dot followed by the 6-digit HEX)
# without depending on the Home-window properties, which are only live while the
# overlay is open.
_CUSTOM_BTN_SUFFIX = "_custom_btn"


def _custom_btn_label(raw6: str) -> str:
    """Return the ``label2`` markup previewing a 6-digit HEX color."""
    return "[COLOR=FF{0}]●[/COLOR] #{0}".format(raw6)


def _load_custom() -> dict:
    """Return the stored custom colors mapping, or an empty dict."""
    try:
        path = xbmcvfs.translatePath(_CUSTOM_FILE)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception:  # pragma: no cover - corrupt/unreadable file → ignore
        pass
    return {}


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


def _setting_value(addon, setting_id: str, overrides) -> str:
    """Return a setting value, allowing fresh writes to bypass Kodi's cache."""
    if overrides and setting_id in overrides:
        return str(overrides[setting_id])
    return addon.getSetting(setting_id)


def _resolve(palette: tuple, addon, setting_id: str, custom: dict, overrides=None) -> str:
    """
    Resolve a color setting to an ARGB hex string.

    When the setting holds the custom marker (option 999), the stored 8-digit
    ARGB hex from ``custom`` is used.  An invalid or missing custom value falls
    back to the palette default (index 0).
    """
    value = _setting_value(addon, setting_id, overrides)
    if value == _CUSTOM_INDEX:
        stored = str(custom.get(setting_id, "")).strip().upper()
        if _HEX8_RE.match(stored):
            return stored
        return palette[0]
    return _pick(palette, value)


def apply_theme(home, addon=None, overrides=None, custom=None) -> None:
    """
    Read the color settings and publish them as Home-window properties.

    Call this before opening the overlay so the skin can resolve every color
    via ``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]``.
    """
    addon = addon or xbmcaddon.Addon()
    custom = _load_custom() if custom is None else custom

    home.setProperty("TinyPPI.TitleColor",       _resolve(_TEXT_COLORS, addon, "title_color", custom, overrides))
    home.setProperty("TinyPPI.FilenameColor",    _resolve(_TEXT_COLORS, addon, "filename_color", custom, overrides))
    home.setProperty("TinyPPI.IconColor",        _resolve(_TEXT_COLORS, addon, "icon_color", custom, overrides))
    home.setProperty("TinyPPI.HeaderColor",      _resolve(_TEXT_COLORS, addon, "header_color", custom, overrides))
    home.setProperty("TinyPPI.ChartColor",       _resolve(_TEXT_COLORS, addon, "chart_color", custom, overrides))
    home.setProperty("TinyPPI.DescriptionColor", _resolve(_TEXT_COLORS, addon, "description_color", custom, overrides))
    home.setProperty("TinyPPI.OutputColor",      _resolve(_TEXT_COLORS, addon, "output_color", custom, overrides))
    home.setProperty("TinyPPI.ProgressColor",    _resolve(_TEXT_COLORS, addon, "progress_color", custom, overrides))
    home.setProperty("TinyPPI.FpsColor",         _resolve(_TEXT_COLORS, addon, "fps_color", custom, overrides))
    home.setProperty("TinyPPI.UnitColor",        _resolve(_TEXT_COLORS, addon, "unit_color", custom, overrides))
    home.setProperty("TinyPPI.UnitLabel",        _pick(_UNIT_LABELS, _setting_value(addon, "unit_type", overrides)))
    home.setProperty("TinyPPI.AccentColor",      _resolve(_ACCENT_COLORS, addon, "accent_color", custom, overrides))
    home.setProperty("TinyPPI.BackgroundColor",  _resolve(_BACKGROUND_COLORS, addon, "background_color", custom, overrides))
    home.setProperty("TinyPPI.LineColor",        _resolve(_LINE_COLORS, addon, "line_color", custom, overrides))


def reset_colors(addon=None) -> None:
    """
    Reset every Theme color setting back to its default (index 0) and confirm
    with a notification.  Invoked from the settings dialog via
    ``RunScript(script.tinyppi,reset_colors)``.
    """
    addon = addon or xbmcaddon.Addon()

    for setting_id in _COLOR_SETTINGS:
        addon.setSetting(setting_id, "0")
        addon.setSetting(setting_id + _CUSTOM_BTN_SUFFIX, "")  # clear swatch preview

    _save_custom({})  # drop every stored custom HEX value

    # Re-publish properties so an overlay that is already open updates too.
    overrides = {setting_id: "0" for setting_id in _COLOR_SETTINGS}
    try:
        apply_theme(xbmcgui.Window(10000), addon, overrides=overrides, custom={})
    except Exception:  # pragma: no cover - best effort, never block the reset
        pass

    xbmcgui.Dialog().notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(32148),
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )


def custom_color(setting_id, addon=None) -> None:
    """
    Prompt for a custom 6-digit HEX color via the on-screen keyboard and store
    it for ``setting_id``.

    On confirmation the input is validated:

    - Valid  → the per-setting alpha channel is prepended (yielding an 8-digit
      ARGB hex), saved to the custom-colors JSON file, and the color setting is
      switched to the custom marker (option 999) so the list shows
      "Benutzerdefiniert".
    - Invalid → an error notification is shown and the color falls back to the
      default (index 0).

    Cancelling the keyboard leaves the current selection untouched.  Invoked
    from the settings dialog via ``RunScript(script.tinyppi,custom_color,<id>)``.
    The triggering button closes the dialog so the marker survives.
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
        # Invalid input → notify and fall back to the default color.
        custom.pop(setting_id, None)
        _save_custom(custom)
        addon.setSetting(setting_id, "0")
        addon.setSetting(setting_id + _CUSTOM_BTN_SUFFIX, "")
        setting_value = "0"
        xbmcgui.Dialog().notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(32244),
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
        xbmcgui.Dialog().notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(32245),
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )

    # Re-publish properties so an overlay that is already open updates too.
    try:
        apply_theme(
            xbmcgui.Window(10000),
            addon,
            overrides={setting_id: setting_value},
            custom=custom,
        )
    except Exception:  # pragma: no cover - best effort, never block the change
        pass
