"""
theme.py – Color theme engine for the TinyPPI overlay.

Maps the user's color choices from the add-on settings onto ARGB hex strings
and publishes them as Home-window (10000) properties.  The skin consumes them
via ``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]`` so colors can be
changed from the settings without editing any skin XML.
"""

import xbmcaddon

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
)

# Palette for inline detail accents (the dimmed values shown in parentheses).
# Same hues as _TEXT_COLORS but at alpha B3 (~70%) so they stay subtle.
# The index matches the <option> order in resources/settings.xml.
_ACCENT_COLORS = (
    "B3FF80AB",  # 0  White (default)
    "B3E0E0E0",  # 1  Light gray
    "B3FF8A80",  # 2  Red
    "B3FFCC80",  # 3  Orange
    "B3FFFF8D",  # 4  Yellow
    "B3B9F6CA",  # 5  Green
    "B384FFFF",  # 6  Cyan
    "B382B1FF",  # 7  Blue
    "B3E1BEE7",  # 8  Purple
    "B3FF80AB",  # 9  Pink
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
)


def _pick(palette: tuple, value: str) -> str:
    """Return ``palette[value]``, falling back to index 0 on bad input."""
    try:
        return palette[int(value)]
    except (ValueError, TypeError, IndexError):
        return palette[0]


def apply_theme(home, addon=None) -> None:
    """
    Read the color settings and publish them as Home-window properties.

    Call this before opening the overlay so the skin can resolve every color
    via ``$INFO[Window(10000).Property(TinyPPI.<Name>Color)]``.
    """
    addon = addon or xbmcaddon.Addon()

    home.setProperty("TinyPPI.TitleColor",       _pick(_TEXT_COLORS, addon.getSetting("title_color")))
    home.setProperty("TinyPPI.DescriptionColor", _pick(_TEXT_COLORS, addon.getSetting("description_color")))
    home.setProperty("TinyPPI.OutputColor",      _pick(_TEXT_COLORS, addon.getSetting("output_color")))
    home.setProperty("TinyPPI.ProgressColor",    _pick(_TEXT_COLORS, addon.getSetting("progress_color")))
    home.setProperty("TinyPPI.AccentColor",      _pick(_ACCENT_COLORS, addon.getSetting("accent_color")))
    home.setProperty("TinyPPI.BackgroundColor",  _pick(_BACKGROUND_COLORS, addon.getSetting("background_color")))
