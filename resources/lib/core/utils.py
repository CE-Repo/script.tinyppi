"""
utils.py – Generic Kodi API wrappers and shared window-state helpers.
"""

import re

import xbmc
import xbmcgui

_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Separators between individual readings in a composite value.  The metadata
# view uses a pipe; the compact overlay swaps it for a lowercase ``l`` because
# that glyph reads more clearly in its narrow font.  Runs of spaces separate
# the wide trim-table values.
_READING_GAP_RE = re.compile(r"(\s{2,}|\s+[|l]\s+)")

# Home-window (10000) properties describing the TinyPPI overlay state.
# Shared by overlay.py and mode_select.py.
PROP_RUNNING     = "TinyPPI.Running"
PROP_ACTIVE      = "TinyPPI.Active"
PROP_DIALOG_MODE = "TinyPPI.DialogMode"

# The output type the overlay's layout follows, published by
# info.properties.publish_hdr_type.
PROP_EFFECTIVE_HDR_TYPE = "TinyPPI.EffectiveHdrType"


def cond(condition: str) -> bool:
    """Return True when the given Kodi condition string is satisfied."""
    return xbmc.getCondVisibility(condition)


def effective_hdr_type() -> str:
    """Return the HDR type the overlay's layout follows.

    The effective type, not the source: a stream VS10 converts to SDR is drawn
    in the SDR layout, so this is what the boxes and panels are sized against.
    """
    return xbmcgui.Window(10000).getProperty(PROP_EFFECTIVE_HDR_TYPE)


def is_effective_dv() -> bool:
    """Return whether the layout follows the Dolby Vision branch.

    Mirrors the skin's own condition, which puts the channel graphics in the
    smaller panel and the Dolby Vision panels on screen.  Answered in one place
    rather than restated per caller, so the copies cannot drift apart.
    """
    return "dolby" in effective_hdr_type().lower()


def info(label: str) -> str:
    """Return the current value of a Kodi InfoLabel (never None)."""
    return xbmc.getInfoLabel(label)


def clean(val) -> str:
    """Strip commas that Kodi inserts as thousands separators."""
    if val is None:
        return ""
    return str(val).replace(",", "")


def highlight_changes(previous, current, color: str):
    """Return *current* with readings changed from *previous* color-marked.

    Strings containing several readings are compared part by part, so one
    moving number does not light up its whole row.  Lists are compared cell by
    cell for the metadata view's fixed-column tables.  A value without history
    is left plain because there is nothing to compare it with yet.
    """
    if previous is None or previous == current or not color:
        return current
    if isinstance(current, list):
        return [
            cell if index < len(previous) and previous[index] == cell
            else _colored(cell, color)
            for index, cell in enumerate(current)
        ]

    parts = _READING_GAP_RE.split(current)
    before = _READING_GAP_RE.split(previous)
    if len(parts) != len(before):
        return _colored(current, color)
    return "".join(
        part if index % 2 or part == before[index]
        else _colored(part, color)
        for index, part in enumerate(parts)
    )


def _colored(text: str, color: str) -> str:
    """Wrap non-empty *text* in Kodi color markup."""
    return f"[COLOR={color}]{text}[/COLOR]" if text else text


def parse_offsets(value: str) -> tuple[int, int, int, int] | None:
    """Return the four L5 offsets from an ``L | R | T | B`` string.

    None for anything that is not four numbers: an empty field, or one of
    dvinfo's status labels.
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


def first_float(raw: str) -> float | None:
    """Return the first decimal number found in *raw*, or None."""
    match = _DECIMAL_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except (TypeError, ValueError):
        return None


def picture_aspect_ratio(offsets: str) -> float | None:
    """Return the display aspect ratio of the picture inside the black bars.

    Kodi's ``videodar`` describes the coded frame, so a letterboxed picture
    reports its container's ratio rather than its own; scaling that by the bars
    gives the ratio actually on screen.  Scaling rather than dividing the
    picture's own dimensions carries any non-square pixel aspect through
    unchanged.

    None when the frame, the bars or Kodi's own ratio are unknown, or when the
    bars would leave no picture at all.
    """
    bars = parse_offsets(offsets)
    coded = coded_frame()
    coded_dar = first_float(clean(info("Player.Process(videodar)")))
    if bars is None or coded is None or coded_dar is None:
        return None

    left, right, top, bottom = bars
    coded_w, coded_h = coded
    picture_w = coded_w - left - right
    picture_h = coded_h - top - bottom
    if picture_w <= 0 or picture_h <= 0:
        return None

    return coded_dar * (picture_w / coded_w) * (coded_h / picture_h)


def set_window_properties(window, values: tuple[tuple[str, str], ...]) -> None:
    """Publish a batch of Kodi window properties."""
    for name, value in values:
        window.setProperty(name, value)


def set_changed_properties(window, published: dict, values: tuple[tuple[str, str], ...]) -> None:
    """Publish only the values that differ from what ``published`` last recorded.

    ``published`` is the caller's own tracking dict, kept for the life of
    whatever polls this window; only the entries actually written here are
    updated in it, so it stays an accurate record of what the window holds
    even when something else (a highlight overwrite, say) also writes to the
    same keys and updates the same dict.
    """
    for name, value in values:
        if published.get(name) != value:
            window.setProperty(name, value)
            published[name] = value


def clear_overlay_state(home) -> None:
    """Clear the Home-window properties that mark TinyPPI as open."""
    for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE):
        home.clearProperty(prop)
