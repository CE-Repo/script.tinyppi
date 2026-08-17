"""
utils.py – Generic Kodi API wrappers and shared window-state helpers.
"""

import re
import time

import xbmc
import xbmcaddon
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


# How long a reading that moved keeps the highlight color when the caller
# names no duration of its own: one second, which is how long a change used to
# stay lit back when the views polled once a second.
DEFAULT_HIGHLIGHT_HOLD = 1.0

# Deadline key standing for the whole value rather than one part of it, used
# for the values that cannot be compared part by part (see _changed_parts).
_WHOLE = -1


def _colored(text: str, color: str) -> str:
    """Wrap non-empty *text* in Kodi color markup."""
    return f"[COLOR={color}]{text}[/COLOR]" if text else text


def _changed_parts(previous, current) -> list:
    """Which parts of *current* read differently than they did in *previous*.

    Strings are split on the separators between readings, so one moving number
    in a composite value does not report its neighbours as changed; the
    returned indices are into that split, which ``_colored_parts`` rebuilds the
    string from.  Lists are compared cell by cell, for the metadata view's
    fixed-column tables.

    ``[_WHOLE]`` when the two cannot be lined up part by part at all -- a
    different number of readings, or a value that changed shape from a table
    row to a plain one -- which marks the value changed as a whole, the way
    the part-by-part comparison could not.
    """
    if isinstance(current, list):
        before = previous if isinstance(previous, list) else []
        return [index for index, cell in enumerate(current)
                if index >= len(before) or before[index] != cell]
    if not isinstance(previous, str):
        return [_WHOLE]
    parts  = _READING_GAP_RE.split(current)
    before = _READING_GAP_RE.split(previous)
    if len(parts) != len(before):
        return [_WHOLE]
    # Odd indices are the separators the split kept; only the readings between
    # them are compared, and only they are ever colored.
    return [index for index, part in enumerate(parts)
            if not index % 2 and part != before[index]]


def _colored_parts(value, parts, color: str):
    """Return *value* with the parts named in *parts* color-marked.

    Indices left over from a value of a different shape cannot color the wrong
    reading: whatever set them also set ``_WHOLE`` at a deadline no earlier
    than theirs (see ``_changed_parts``), so while any of them is still live
    the whole value is lit anyway.
    """
    if not parts:
        return value
    whole = _WHOLE in parts
    if isinstance(value, list):
        return [_colored(cell, color) if whole or index in parts else cell
                for index, cell in enumerate(value)]
    if whole:
        return _colored(value, color)
    return "".join(
        _colored(part, color) if index in parts else part
        for index, part in enumerate(_READING_GAP_RE.split(value))
    )


class ChangeHighlighter:
    """Color the readings that moved, and keep them colored for *hold* seconds.

    The views poll their readings ten times a second, which is the cadence the
    Dolby Vision blocks themselves move at.  A highlight that lasts exactly one
    such tick, though, is a tenth of a second on screen -- over before the eye
    that noticed it can land on it.  So what a tick decides here is not whether
    a reading is colored but whether it *just changed*: a change stamps a
    deadline on the reading, and every tick up to that deadline draws it in the
    highlight color, however many ticks that takes.  The polling stays as fast
    as it was; the blink lasts as long as *hold* says.

    Which is also why the deadlines live here rather than in the callers: a
    caller that only ever compares this tick's value against the last one can
    light a reading for a single tick and no longer.

    Each part of a composite reading carries its own deadline, so a value that
    moves again halfway through does not cut its neighbour's highlight short.
    """

    def __init__(self, hold: float = DEFAULT_HIGHLIGHT_HOLD) -> None:
        self._hold = max(0.0, hold)
        # Per key: the last plain value seen, and the deadline every part of it
        # still being highlighted is lit until.  Kept apart so a key with
        # nothing lit costs one dict entry rather than two.
        self._values: dict = {}
        self._until: dict  = {}

    def mark(self, key, value, color: str, now: float = None):
        """Record *value* under *key* and return it with its changes lit.

        A value without history is returned plain: there is nothing to compare
        it against yet, and a view that lit every reading the moment it opened
        would say everything changed at once.  So is every value when *color*
        is empty, which is how a caller says the highlight does not apply right
        now -- the value is still remembered, so the reading has its history
        ready for whenever it does apply again.

        *now* comes from ``time.monotonic``; pass one taken once for a whole
        pass over many keys, so every reading in it shares a deadline.
        """
        now      = time.monotonic() if now is None else now
        previous = self._values.get(key)
        self._values[key] = value

        if not color:
            self._until.pop(key, None)
            return value

        deadlines = self._until.get(key, {})
        if previous is not None and previous != value:
            deadline = now + self._hold
            for part in _changed_parts(previous, value):
                deadlines[part] = deadline
        deadlines = {part: until for part, until in deadlines.items()
                     if until > now}
        if deadlines:
            self._until[key] = deadlines
        else:
            self._until.pop(key, None)
        return _colored_parts(value, deadlines, color)

    def retain(self, keys) -> None:
        """Forget every key that is not in *keys*.

        For callers whose set of readings changes under them -- the metadata
        view's rows come and go with the frame -- so the history does not grow
        for the life of the view.  A key that goes away and comes back is a
        reading without history again, which is the same thing the view says
        of it: it was not on screen to have moved.
        """
        keep = set(keys)
        for store in (self._values, self._until):
            for key in [key for key in store if key not in keep]:
                del store[key]


def highlight_hold(setting_id: str) -> float:
    """Seconds a changed reading stays lit, from the milliseconds *setting_id*
    is set to.

    Read through a fresh ``Addon()`` so a duration changed mid-session applies
    to the next view opened rather than to the next Kodi start.  Anything the
    setting cannot answer with -- a profile written before it existed, a value
    the slider could not have produced -- reads as DEFAULT_HIGHLIGHT_HOLD: a
    missing setting should cost the viewer's choice of duration, not the
    highlighting itself.
    """
    try:
        milliseconds = xbmcaddon.Addon().getSettingInt(setting_id)
    except Exception:
        milliseconds = 0
    return milliseconds / 1000.0 if milliseconds > 0 else DEFAULT_HIGHLIGHT_HOLD


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
