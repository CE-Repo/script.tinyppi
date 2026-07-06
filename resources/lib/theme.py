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

# Palette for the focused button highlight in the VS10 dialog (texturefocus).
# Same hues as _TEXT_COLORS but index 0 is pure white to match the original
# default.  The index matches the <option> order in resources/settings.xml.
_DIALOG_FOCUS_COLORS = ("FFFFFFFF",) + _TEXT_COLORS[1:]

# Palette for the focused button text in the VS10 dialog (focusedcolor).
# Black (the original default) and pure white lead, followed by the full hue
# set from _TEXT_COLORS (its near-white index 0 is dropped in favour of the
# pure white above).  The index matches the <option> order of
# ``dialog_focus_text_color`` in resources/settings.xml.
_DIALOG_FOCUS_TEXT_COLORS = (
    "FF000000",  # 0  Black (default)
    "FFFFFFFF",  # 1  White
) + _TEXT_COLORS[1:]

# Palette for inline detail accents (the dimmed values shown in parentheses).
# Same hues as _TEXT_COLORS but at alpha B3 (~70%) so they stay subtle.
# The index matches the <option> order in resources/settings.xml.
_ACCENT_COLORS = tuple("B3" + color[2:] for color in _TEXT_COLORS)

# Palette for the separator lines (very faint dividers, alpha 26 ~ 15%).
# Same hues as _TEXT_COLORS but heavily dimmed so the lines stay subtle,
# except index 0 which keeps the original neutral gray default.
# The index matches the <option> order in resources/settings.xml.
_LINE_COLORS = ("26808080",) + tuple(
    "26" + color[2:] for color in _TEXT_COLORS[1:]
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
    "background_color":        "FA",  # Modern background shades
    "global_background_color": "FA",  # full-screen global background shades
    "accent_color":            "B3",  # dimmed detail accents (~70%)
    "line_color":              "26",  # faint separator lines (~15%)
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


def _notify(addon, message_id: int, icon: str, duration: int) -> None:
    """Show a localized TinyPPI settings notification."""
    xbmcgui.Dialog().notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(message_id),
        icon,
        duration,
    )


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


# Fallback opacity (percent) used when a setting is missing or invalid: full
# opacity for text-based elements.
_DEFAULT_OPACITY = 100

# Per-element opacity defaults (percent), keyed by color setting id.  Each value
# reproduces the alpha baked into that element's palette so the out-of-the-box
# look is unchanged until the user moves the slider.  Elements not listed use
# ``_DEFAULT_OPACITY`` (100 %, alpha FF).
_DEFAULT_OPACITIES = {
    "background_color":        98,  # FA – Modern panel background
    "global_background_color":  0,  # off until the user raises the slider
    "accent_color":            70,  # B3 – dimmed inline detail accents
    "line_color":              15,  # 26 – faint separator lines
}


def _opacity_setting(color_setting_id: str) -> str:
    """Return the opacity slider id paired with a ``*_color`` setting."""
    return color_setting_id[: -len("_color")] + "_opacity"


def _opacity_alpha(addon, setting_id, default, overrides=None) -> str:
    """
    Return the 2-digit hex alpha for a configured opacity slider.

    The referenced setting is a 0–100 % slider: 100 % is fully opaque (FF) and
    0 % is fully transparent (00).  ``default`` (percent) is used when the
    setting is missing or invalid.
    """
    try:
        percent = int(_setting_value(addon, setting_id, overrides))
    except (ValueError, TypeError):
        percent = default
    percent = max(0, min(100, percent))
    # Round half up so the per-element defaults reproduce the palette's native
    # alpha exactly (e.g. 70 % → B3 for the accent, 15 % → 26 for the lines).
    return "{:02X}".format(int(percent * 255 / 100 + 0.5))


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


_THEME_PROPERTIES = (
    ("TinyPPI.TitleColor",           _TEXT_COLORS, "title_color"),
    ("TinyPPI.FilenameColor",        _TEXT_COLORS, "filename_color"),
    ("TinyPPI.IconColor",            _TEXT_COLORS, "icon_color"),
    ("TinyPPI.HeaderColor",          _TEXT_COLORS, "header_color"),
    ("TinyPPI.HeaderIconColor",      _TEXT_COLORS, "header_icon_color"),
    ("TinyPPI.DescriptionColor",     _TEXT_COLORS, "description_color"),
    ("TinyPPI.OutputColor",          _TEXT_COLORS, "output_color"),
    ("TinyPPI.ProgressColor",        _TEXT_COLORS, "progress_color"),
    ("TinyPPI.FpsColor",             _TEXT_COLORS, "fps_color"),
    ("TinyPPI.UnitColor",            _TEXT_COLORS, "unit_color"),
    ("TinyPPI.AccentColor",          _ACCENT_COLORS, "accent_color"),
    ("TinyPPI.BackgroundColor",      _BACKGROUND_COLORS, "background_color"),
    ("TinyPPI.GlobalBackgroundColor", _BACKGROUND_COLORS, "global_background_color"),
    ("TinyPPI.LineColor",            _LINE_COLORS, "line_color"),
    ("TinyPPI.DialogFocusColor",     _DIALOG_FOCUS_COLORS, "dialog_focus_color"),
    (
        "TinyPPI.DialogFocusTextColor",
        _DIALOG_FOCUS_TEXT_COLORS,
        "dialog_focus_text_color",
    ),
)


def apply_theme(home, addon=None, overrides=None, custom=None) -> None:
    """
    Read the color settings and publish them as Home-window properties.

    Call this before opening the overlay so the skin can resolve every color
    via ``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]``.
    """
    addon = addon or xbmcaddon.Addon()
    custom = _load_custom() if custom is None else custom

    for property_name, palette, setting_id in _THEME_PROPERTIES:
        value = _resolve(palette, addon, setting_id, custom, overrides)
        # Every element has its own opacity slider; its alpha overrides the
        # palette/custom alpha so the chosen HEX only supplies the RGB channels.
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
