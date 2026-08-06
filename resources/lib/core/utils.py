"""
utils.py – Generic Kodi API wrappers and shared window-state helpers.
"""

import xbmc

# Home-window (10000) properties describing the TinyPPI overlay state.
# Shared by overlay.py and mode_select.py.
PROP_RUNNING     = "TinyPPI.Running"
PROP_ACTIVE      = "TinyPPI.Active"
PROP_DIALOG_MODE = "TinyPPI.DialogMode"


def cond(condition: str) -> bool:
    """Return True when the given Kodi condition string is satisfied."""
    return xbmc.getCondVisibility(condition)


def info(label: str) -> str:
    """Return the current value of a Kodi InfoLabel (never None)."""
    return xbmc.getInfoLabel(label)


def clean(val) -> str:
    """Strip commas that Kodi inserts as thousands separators."""
    if val is None:
        return ""
    return str(val).replace(",", "")


def parse_offsets(value: str) -> tuple[int, int, int, int] | None:
    """Return the four L5 offsets from an ``L | R | T | B`` string.

    None for anything that is not four numbers: an empty field, the pending
    placeholder, or one of dvinfo's status labels.
    """
    parts = value.split("|")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part.strip()) for part in parts)
    except ValueError:
        return None


def coded_frame() -> tuple[int, int] | None:
    """Return the coded video frame size, or None when it is not known."""
    try:
        width = int(clean(info("Player.Process(videowidth)")))
        height = int(clean(info("Player.Process(videoheight)")))
    except ValueError:
        return None
    return (width, height) if width > 0 and height > 0 else None


def set_window_properties(window, values: tuple[tuple[str, str], ...]) -> None:
    """Publish a batch of Kodi window properties."""
    for name, value in values:
        window.setProperty(name, value)


def clear_overlay_state(home) -> None:
    """Clear the Home-window properties that mark TinyPPI as open."""
    for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE):
        home.clearProperty(prop)
