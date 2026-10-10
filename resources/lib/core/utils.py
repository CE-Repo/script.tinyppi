# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Kodi API wrappers and shared window-state helpers."""

import re
import threading
import time
from collections.abc import Collection, Hashable, Iterable
from typing import TypeVar

import xbmc
import xbmcgui
from core import settings
from core.constants import HOME_WINDOW_ID
from core.log import log
from core.protocols import PropertyTarget

_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Separators between readings in a composite value: a pipe in the metadata
# view, a lowercase ``l`` in the compact overlay (clearer in its narrow font),
# and runs of spaces in the wide trim tables.
_READING_GAP_RE = re.compile(r"(\s{2,}|\s+[|l]\s+)")

# Home-window (10000) properties for the overlay state, shared by overlay.py
# and mode_select.py.
PROP_RUNNING     = "TinyPPI.Running"
PROP_ACTIVE      = "TinyPPI.Active"
PROP_DIALOG_MODE = "TinyPPI.DialogMode"

# The output type the overlay layout follows (see
# info.publish.publish_hdr_type).
PROP_EFFECTIVE_HDR_TYPE = "TinyPPI.EffectiveHdrType"

# Whether the stream carries HDR10+ metadata.  A Dolby Vision title with an
# ST 2094-40 payload next to its RPU is a hybrid grade the driver cannot
# convert with VS10 (issue #71), so the dialog and dashboard hide the modes.
PROP_HDR10PLUS_PRESENT = "TinyPPI.Hdr10PlusPresent"


# Per-pass read caches, one per thread (the overlay and the metadata view
# refresh from different threads).  ``None`` outside a pass, where every read
# goes straight to Kodi.
_reads = threading.local()


class read_pass:
    """Read each InfoLabel and condition at most once per pass.

    One refresh computes about sixty readings from some forty InfoLabels, many
    of them shared.  Every read takes the lock of Kodi's info manager, which is
    costly on a box decoding 4K, and readings within one pass should describe
    the same moment anyway.

    The pass also shares one Home-window handle (see ``home_window``).  Passes
    nest: an inner pass uses the outer one's cache.  Nothing is kept after the
    outermost pass ends.
    """

    __slots__ = ("_outer",)

    def __enter__(self) -> "read_pass":
        self._outer = getattr(_reads, "info", None)
        if self._outer is None:
            _reads.info = {}
            _reads.cond = {}
            _reads.home = None
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._outer is None:
            _reads.info = None
            _reads.cond = None
            _reads.home = None


def home_window() -> xbmcgui.Window:
    """Return the Home window (10000), where TinyPPI publishes its state.

    A window lookup takes Kodi's GUI lock, so inside a ``read_pass`` one
    handle is shared.  It is never kept beyond the pass: Kodi recreates its
    windows when the skin reloads.
    """
    if getattr(_reads, "info", None) is None:
        return xbmcgui.Window(HOME_WINDOW_ID)
    home = getattr(_reads, "home", None)
    if home is None:
        home = _reads.home = xbmcgui.Window(HOME_WINDOW_ID)
    return home


def cond(condition: str) -> bool:
    """Return True when the Kodi condition *condition* is met."""
    cache = getattr(_reads, "cond", None)
    if cache is None:
        return xbmc.getCondVisibility(condition)
    try:
        return cache[condition]
    except KeyError:
        value = cache[condition] = xbmc.getCondVisibility(condition)
        return value


def effective_hdr_type() -> str:
    """Return the HDR type the overlay layout follows.

    This is the effective type, not the source: a stream VS10 converts to SDR
    uses the SDR layout.
    """
    return home_window().getProperty(PROP_EFFECTIVE_HDR_TYPE)


def is_effective_dv() -> bool:
    """Return whether the layout follows the Dolby Vision branch.

    Mirrors the skin's own condition; kept in one place so callers cannot
    drift apart.
    """
    return "dolby" in effective_hdr_type().lower()


def info(label: str) -> str:
    """Return the current value of a Kodi InfoLabel (never None).

    Served from the current ``read_pass`` when one is open.
    """
    cache = getattr(_reads, "info", None)
    if cache is None:
        return _known(label, xbmc.getInfoLabel(label))
    try:
        return cache[label]
    except KeyError:
        value = cache[label] = _known(label, xbmc.getInfoLabel(label))
        return value


def _known(label: str, value: str) -> str:
    """Return *value*, or '' when Kodi does not know *label*.

    Kodi answers an InfoLabel it does not know with the label's own text, so
    a CoreELEC-only label on another build, or one a CoreELEC release renamed,
    would otherwise show up as ``Player.Process(amlogic...)`` on screen.
    """
    return "" if value == label else value


# How often ``localized`` checks Kodi's language, in seconds.
_LANGUAGE_RECHECK = 1.0

class _Strings:
    """This add-on's strings, read once per language.

    Cached because the dashboard and the N/A checks ask for the same ones
    several times a second.  The cache is dropped when Kodi's language
    changes, which is checked at most once a second.
    """

    def __init__(self) -> None:
        self._texts: dict[int, str] = {}
        self._language: str | None = None
        self._checked = float("-inf")

    def get(self, string_id: int) -> str:
        now = time.monotonic()
        if now - self._checked >= _LANGUAGE_RECHECK:
            self._checked = now
            language = xbmc.getLanguage()
            if language != self._language:
                self._texts.clear()
                self._language = language
        text = self._texts.get(string_id)
        if text is None:
            text = settings.addon().getLocalizedString(string_id)
            self._texts[string_id] = text
        return text


_strings = _Strings()


def localized(string_id: int) -> str:
    """Return this add-on's string *string_id* in Kodi's language."""
    return _strings.get(string_id)


def clean(val: object) -> str:
    """Strip the commas Kodi inserts as thousands separators."""
    if val is None:
        return ""
    return str(val).replace(",", "")


# Default highlight duration for a changed reading, matching the 750 ms
# default of the highlight duration settings.
DEFAULT_HIGHLIGHT_HOLD = 0.75

# Deadline key for the whole value, used when parts cannot be compared
# individually (see ``_changed_parts``).
_WHOLE = -1

# A reading: one string, or a list of cells (the metadata view's rows).
Reading = TypeVar("Reading", str, list[str])


def _colored(text: str, color: str) -> str:
    """Wrap non-empty *text* in Kodi color markup."""
    return f"[COLOR={color}]{text}[/COLOR]" if text else text


def _changed_parts(previous: object, current: str | list[str]) -> list[int]:
    """Return the indices of the parts of *current* that differ from *previous*.

    Strings are split on the reading separators, so one moving number does
    not mark its neighbours; the indices refer to that split.  Lists are
    compared cell by cell.  Returns ``[_WHOLE]`` when the values cannot be
    lined up (different number of readings, or a change of shape).
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
    # Odd indices are the separators kept by the split; only readings count.
    return [index for index, part in enumerate(parts)
            if not index % 2 and part != before[index]]


def _colored_parts(value: Reading, parts: Collection[int], color: str) -> Reading:
    """Return *value* with the parts listed in *parts* colored.

    Stale indices from a value of another shape are harmless: whatever set
    them also set ``_WHOLE`` with a deadline at least as late, so the whole
    value is lit while they are live.
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
    """Color readings that changed and keep them colored for *hold* seconds.

    The views poll ten times a second, so a highlight lasting one tick would
    be too short to notice.  A change therefore stamps a deadline on the
    reading, and every tick until then draws it highlighted.  Each part of a
    composite reading has its own deadline, so a part that changes again does
    not cut its neighbour's highlight short.
    """

    def __init__(self, hold: float = DEFAULT_HIGHLIGHT_HOLD) -> None:
        self._hold = max(0.0, hold)
        # Per key: the last plain value, and the highlight deadline per part.
        # Separate dicts, so a key with nothing lit costs a single entry.
        self._values: dict[Hashable, str | list[str]] = {}
        self._until: dict[Hashable, dict[int, float]] = {}

    def mark(self, key: Hashable, value: Reading, color: str,
             now: float | None = None) -> Reading:
        """Record *value* under *key* and return it with its changes colored.

        A value without history is returned plain, so a freshly opened view
        does not light everything.  An empty *color* disables highlighting
        for now, but the value is still recorded.

        *now* is a ``time.monotonic`` value; pass one per pass so all
        readings in it share a deadline.
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

    def retain(self, keys: Iterable[Hashable]) -> None:
        """Forget every key not in *keys*.

        For views whose rows come and go (the metadata view), so the history
        does not grow for the life of the view.
        """
        keep = set(keys)
        for store in (self._values, self._until):
            for key in [key for key in store if key not in keep]:
                del store[key]


def highlight_hold(setting_id: str) -> float:
    """Return the highlight duration in seconds from setting *setting_id*.

    The setting holds milliseconds and is read through ``core.settings``, so
    a change applies to the next view opened.  Missing or invalid values fall
    back to ``DEFAULT_HIGHLIGHT_HOLD``.
    """
    try:
        milliseconds = settings.addon().getSettingInt(setting_id)
    except Exception:  # missing or not an integer (Kodi raises TypeError)
        milliseconds = 0
    return milliseconds / 1000.0 if milliseconds > 0 else DEFAULT_HIGHLIGHT_HOLD


def parse_offsets(value: str) -> tuple[int, int, int, int] | None:
    """Return the four L5 offsets from an ``L | R | T | B`` string.

    None for anything that is not four numbers, such as an empty field or a
    status label from dvinfo.
    """
    parts = value.split("|")
    if len(parts) != 4:
        return None
    try:
        left, right, top, bottom = (int(part.strip()) for part in parts)
    except ValueError:
        return None
    return left, right, top, bottom


def coded_frame() -> tuple[int, int] | None:
    """Return the coded video frame size, or None when unknown."""
    try:
        width = int(clean(info("Player.Process(videowidth)")))
        height = int(clean(info("Player.Process(videoheight)")))
    except ValueError:
        return None
    return (width, height) if width > 0 and height > 0 else None


def first_float(raw: str) -> float | None:
    """Return the first decimal number in *raw*, or None."""
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
    reports its container's ratio.  Scaling that ratio by the bars gives the
    visible ratio and keeps any non-square pixel aspect.

    None when the frame, the bars or Kodi's ratio are unknown, or when the
    bars leave no picture.
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


def set_window_properties(window: PropertyTarget, values: tuple[tuple[str, str], ...]) -> None:
    """Publish a batch of window properties."""
    for name, value in values:
        window.setProperty(name, value)


def set_changed_properties(window: PropertyTarget, published: dict[str, str],
                           values: tuple[tuple[str, str], ...]) -> None:
    """Publish only the values that differ from *published*.

    *published* is the caller's record of what the window holds; only the
    entries written here are updated in it, so it stays accurate when other
    code (e.g. a highlight) writes the same keys and updates it too.
    """
    for name, value in values:
        if published.get(name) != value:
            window.setProperty(name, value)
            published[name] = value


# --- Refresh thread --------------------------------------------------------

# How long join_refresh_thread waits: well past one tick, so a live thread
# always finishes, while a wedged one cannot block the hand-over for good.
_JOIN_TIMEOUT = 1.0


def join_refresh_thread(thread: threading.Thread | None) -> None:
    """Wait for a view's refresh thread to stop.

    The loop checks the view's running flag only between ticks, so it can
    outlive doModal() by one tick, still writing to a closing window and
    touching the side-data hold state the next view reads
    (``info.dvmetadata._held``).  Logs a warning if the thread is still
    alive after the timeout.
    """
    if thread is None:
        return

    thread.join(_JOIN_TIMEOUT)
    if thread.is_alive():
        log(
            f"refresh thread still running after "
            f"{_JOIN_TIMEOUT}s, handing over anyway",
            xbmc.LOGWARNING,
        )


def log_refresh_failure(view: str, exc: Exception) -> None:
    """Log a failed refresh of *view* (e.g. ``'overlay'``).

    The caller gates this with a once-per-view flag, so a persistent fault
    leaves one trace instead of one per tick.
    """
    log(
        f"{view} refresh failed, continuing with the last "
        f"values: {exc}",
        xbmc.LOGWARNING,
    )


def clear_overlay_state(home: PropertyTarget) -> None:

    """Clear the Home-window properties that mark TinyPPI as open."""
    for prop in (PROP_RUNNING, PROP_ACTIVE, PROP_DIALOG_MODE):
        home.clearProperty(prop)
