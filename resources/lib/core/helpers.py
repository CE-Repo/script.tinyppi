# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""FPS sampling and formatting helpers for info.properties."""

import math
import re
from collections import deque

from core.utils import fps_drop_reading

_FPS_STANDARDS = (
    23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0, 100.0, 120.0,
)
_EXACT_FPS_LABELS = {23.976: "23.976", 29.97: "29.97", 59.94: "59.94"}
_FORMAT_FPS_TARGETS = (
    (23.976, 0.02),
    (29.97, 0.02),
    (59.94, 0.02),
    (60.0, 0.01),
)


def normalize_fps(fps_value: str | float) -> str:
    """Snap a raw FPS to the nearest broadcast standard within 0.5 Hz.

    Rates further from any standard are returned as a trimmed decimal.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return str(fps_value)
    if not math.isfinite(fps):  # no standard is nearest to NaN
        return str(fps_value)

    closest = min(_FPS_STANDARDS, key=lambda x: abs(x - fps))

    if abs(closest - fps) > 0.5:
        return f"{fps:.3f}".rstrip("0").rstrip(".")

    if closest in _EXACT_FPS_LABELS:
        return _EXACT_FPS_LABELS[closest]

    return str(int(closest)) if closest.is_integer() else str(closest)


def format_fps(fps_value: str | float) -> str:
    """Format a raw FPS for the video resolution string.

    Known rates (23.976, 29.97, 59.94, 60) are snapped to their canonical
    form; anything else is trimmed to three decimals.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(fps):  # "inf" / "nan" parse but are no rate
        return ""

    for target, tol in _FORMAT_FPS_TARGETS:
        if abs(fps - target) <= tol:
            fps = target
            break

    if fps == int(fps):
        return str(int(fps))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


# The video layer's count of the frames it has shown, one line among the
# driver's settings: `` media.video.toggle_count=1234``.  It rises by one for
# each new picture on screen and leaves out the frames the layer skipped.
TOGGLE_COUNT_PATH = "/sys/class/media-configs/video"
_TOGGLE_COUNT_RE = re.compile(r"media\.video\.toggle_count=(\d+)")


def read_toggle_count() -> int | None:
    """Return the frames the video layer has shown so far, or None."""
    try:
        with open(TOGGLE_COUNT_PATH, encoding="utf-8", errors="ignore") as f:
            match = _TOGGLE_COUNT_RE.search(f.read())
    except OSError:
        return None
    return int(match.group(1)) if match else None


# Passes the drop rate is judged over.
DROP_WINDOW = 5
# How quickly the tally follows the clocks drifting apart, as a share of the
# difference per reading: slow enough that a dropped frame, a step of a
# whole frame, is never taken for drift.
DRIFT_FOLLOW = 0.05


class FrameTally:
    """Count the frames that should have been shown but were not.

    As Kodi does: the time says how many frames were due, the video layer's
    count how many it showed; the difference was dropped.  Each reading is
    taken the moment a new picture appears (see info.fpsdrop), so the
    difference does not wander by a frame with the moment it is read: it
    stays put until a frame goes missing, then steps up by one.  The
    difference is taken as the median of the last three readings, so a step
    counts once two of them show it: a dropped frame stays missing, a
    reading taken a little late or early is outvoted.  The first three
    readings of a stretch count nothing: they set where the difference sits.

    Both are measured from the start of a stretch of steady playback (see
    ``restart``), so a reading's error never adds up over a film.  What the
    system clock and the player's clock drift apart is followed as
    ``_drift``, a fraction of a frame that moves slowly, and left out.  A
    frame shown twice makes up for a dropped one rather than counting
    against later drops.
    """

    def __init__(self) -> None:
        self._totals: deque[int] = deque(maxlen=DROP_WINDOW + 1)
        self._closed = 0          # frames dropped in earlier stretches
        self._counted = 0         # frames dropped in this stretch
        self._base: tuple[float, int] | None = None   # time, frames shown
        self._fps = 0.0
        self._rate = 0.0          # frames due per second; 0 until known
        self._drift = 0.0
        self._recent: deque[float] = deque(maxlen=3)   # the last differences

    @property
    def total(self) -> int:
        """Return the frames dropped since the last ``reset``."""
        return self._closed + self._counted

    @property
    def rate(self) -> int:
        """Return the frames dropped per reading over the window, rounded up."""
        if len(self._totals) < 2:
            return 0
        lost = self._totals[-1] - self._totals[0]
        return math.ceil(lost / (len(self._totals) - 1))

    def reset(self) -> None:
        """Start over, as for a new title."""
        self.restart()
        self._closed = 0

    def restart(self) -> None:
        """Start a new stretch, keeping the total: after a seek or a pause."""
        self._closed += self._counted
        self._counted = 0
        self._base = None
        self._rate = 0.0
        self._drift = 0.0
        self._recent.clear()
        self._totals.clear()

    def update(self, at: float, shown: int, fps: float) -> None:
        """Add a reading: when a new picture appeared, the frames shown so
        far and the video's frame rate."""
        base = self._base
        if base is None or fps != self._fps or shown < base[1]:
            # The first reading, another rate, or a count that started over.
            self.restart()
            self._base, self._fps = (at, shown), fps
            self._totals.append(self.total)
            return
        elapsed, frames = at - base[0], shown - base[1]
        if elapsed <= 0:
            return
        if not self._rate:
            # The first second tells whether the layer shows frames or the
            # fields of interlaced video, two to a frame.
            self._rate = fps * (2 if frames > 1.5 * fps * elapsed else 1)
        self._recent.append(self._rate * elapsed - frames)
        lost = sorted(self._recent)[len(self._recent) // 2]
        if len(self._recent) < (self._recent.maxlen or 0):
            # The first readings of a stretch set where the difference sits.
            self._drift = lost
            self._totals.append(self.total)
            return
        steps = round(lost - self._drift)
        self._counted = max(self._counted, steps)
        self._drift += DRIFT_FOLLOW * (lost - steps - self._drift)
        self._totals.append(self.total)


def fps_display_texts(video_fps: str | float) -> tuple[str, str, str]:
    """Return (info_text, output_fps_text, total_text) for the FPS row.

    *info_text* reads ``NNN - DDD`` (input - drop).  The input rate is the
    video's FPS rounded to a whole frame, the drop is the rate the service's
    drop watch publishes (see info.fpsdrop), and the output rate is the
    difference.  *total_text* is the frames lost since the title started, or
    '' when the video layer's frame count cannot be read.
    """
    try:
        in_fps = round(float(video_fps))
    except (TypeError, ValueError, OverflowError):  # OverflowError: "inf"
        in_fps = 0

    reading = fps_drop_reading() if in_fps else None
    drop, total = reading if reading else (0, None)
    return (f"{in_fps:03d} - {drop:03d}", str(max(0, in_fps - drop)),
            "" if total is None else str(total))
