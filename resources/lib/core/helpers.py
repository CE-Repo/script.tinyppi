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


def read_fps_sysfs() -> tuple[int, int] | None:
    """Read /sys/class/video/fps_info as (input_fps, output_fps), or None."""
    try:
        with open("/sys/class/video/fps_info", encoding="utf-8", errors="ignore") as f:
            raw = f.read().strip()
    except OSError:
        return None

    in_m  = re.search(r"input_fps:0x([0-9a-fA-F]+)", raw)
    out_m = re.search(r"output_fps:0x([0-9a-fA-F]+)", raw)
    if not in_m or not out_m:
        return None

    return int(in_m.group(1), 16), int(out_m.group(1), 16)


# The driver counts the frames in and out once a second, in two windows that
# are slightly out of step: a steady 24 FPS can read 24 / 23 one second and
# 24 / 25 the next.  Those readings cancel out over a few seconds; frames
# that are really lost do not.  So the drop rate is the net loss over the
# last DROP_WINDOW readings, and a loss counts once it reaches
# DROP_THRESHOLD frames.
DROP_WINDOW = 5
DROP_THRESHOLD = 2


class DropCounter:
    """Turn the driver's per-second readings into a drop rate and a total.

    ``rate`` is the frames lost per second over the last ``DROP_WINDOW``
    readings, ``total`` the frames lost since the last ``reset``.  A lone
    frame that the next readings do not make up for is not counted on its
    own: it is held for ``DROP_WINDOW`` readings and counted only with a
    second one.
    """

    def __init__(self) -> None:
        self._window: deque[int] = deque(maxlen=DROP_WINDOW)
        self._pending = 0     # frames lost but not yet counted
        self._quiet = 0       # readings since the last loss
        self.total = 0

    def reset(self) -> None:
        """Start over, as for a new title."""
        self.settle()
        self.total = 0

    def settle(self) -> None:
        """Forget the readings since the last count, keeping the total.

        For a seek: what the window holds is from before it, and a lone
        frame waiting for a second one is not carried past it.
        """
        self._window.clear()
        self._pending = 0
        self._quiet = 0

    def update(self, in_fps: int, out_fps: int) -> None:
        """Add one second's reading of the frames in and out."""
        lost = in_fps - out_fps
        self._window.append(lost)
        self._pending = max(0, self._pending + lost)
        self._quiet = 0 if lost > 0 else self._quiet + 1
        if self._pending >= DROP_THRESHOLD:
            self.total += self._pending
            self._pending = 0
        elif self._quiet >= DROP_WINDOW:
            self._pending = 0          # jitter the readings never made up for

    @property
    def rate(self) -> int:
        """Return the frames lost per second over the window, rounded up."""
        lost = sum(self._window)
        if lost < DROP_THRESHOLD:
            return 0
        return math.ceil(lost / len(self._window))


def fps_display_texts(video_fps: str | float) -> tuple[str, str, str]:
    """Return (info_text, output_fps_text, total_text) for the FPS row.

    *info_text* reads ``NNN - DDD`` (input - drop).  The input rate is the
    video's FPS rounded to a whole frame, the drop is the rate the service's
    drop watch publishes (see info.fpsdrop), and the output rate is the
    difference.  *total_text* is the frames lost since the title started, or
    '' when the driver's counters cannot be read.
    """
    try:
        in_fps = round(float(video_fps))
    except (TypeError, ValueError, OverflowError):  # OverflowError: "inf"
        in_fps = 0

    reading = fps_drop_reading() if in_fps else None
    drop, total = reading if reading else (0, None)
    return (f"{in_fps:03d} - {drop:03d}", str(max(0, in_fps - drop)),
            "" if total is None else str(total))
