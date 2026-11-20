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
# driver's settings: `` video.toggle_count=1234`` (the node's name without
# its path; a full ``media.video.`` path is read as well).  It rises by one
# for each new picture on screen.
TOGGLE_COUNT_PATH = "/sys/class/media-configs/video"
_TOGGLE_COUNT_RE = re.compile(r"\bvideo\.toggle_count=(\d+)")

# The hardware decoder's statistics, with the frames it has put out so far:
# ``  frame count : 688`` (the first channel's, the video's).
DECODER_STATUS_PATH = "/sys/class/vdec/vdec_status"
_DECODED_COUNT_RE = re.compile(r"frame count\s*:\s*(\d+)")


def _read_number(path: str, pattern: re.Pattern[str]) -> int | None:
    """Return the number *pattern* finds in the file at *path*, or None."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            match = pattern.search(f.read())
    except OSError:
        return None
    return int(match.group(1)) if match else None


def read_toggle_count() -> int | None:
    """Return the frames the video layer has shown so far, or None."""
    return _read_number(TOGGLE_COUNT_PATH, _TOGGLE_COUNT_RE)


def read_decoded_count() -> int | None:
    """Return the frames the hardware decoder has put out so far, or None."""
    return _read_number(DECODER_STATUS_PATH, _DECODED_COUNT_RE)


# Readings the drop rate is judged over.
DROP_WINDOW = 5
# Readings the backlog is judged over: a change counts once it holds for
# more than half of them.
BACKLOG_WINDOW = 5
# Frames the decoder puts out before the tally judges how many pictures the
# layer shows for each.
PROBE_FRAMES = 24


class FrameTally:
    """Count the frames the video layer dropped.

    Each reading holds the frames the decoder has put out and the pictures
    the layer has shown.  A frame the decoder put out and the layer never
    showed was dropped.  The difference between the two, the backlog, is
    the frames waiting in the queue plus the frames dropped: it stays level
    while nothing is dropped and rises by one for each drop.

    The stream's time stamps are not used: an encoder may leave out a
    picture that repeats the one before (VC-1's skipped pictures, in still
    or black scenes), which the time stamps step over though the decoder
    never makes a frame of it.  Such a picture is no drop.

    The queue fills and empties by a frame or two from one reading to the
    next, so the backlog is judged by the middle of the last few readings,
    and a drop counts some readings after it happened.  The first readings
    of a stretch set the level; the backlog falling well below it (the
    decoder counting its frames late) sets a new one.

    Interlaced video may be shown as two pictures a frame, its fields, or be
    decoded as two fields a picture; the first readings tell, and skipped
    fields count as the frames they belong to (a lone field as one).
    """

    def __init__(self) -> None:
        self._totals: deque[int] = deque(maxlen=DROP_WINDOW + 1)
        self._closed = 0          # frames dropped in earlier stretches
        self._dropped = 0         # backlog units dropped in this stretch
        self._start: tuple[int, int] | None = None   # decoded, shown at its start
        self._last: tuple[int, int] | None = None    # the last reading
        self._fps = 0.0
        # Backlog units each decoded frame and each picture shown weigh;
        # None until the first readings tell.
        self._weights: tuple[int, int] | None = None
        self._backlog: deque[int] = deque(maxlen=BACKLOG_WINDOW)
        self._level: int | None = None

    @property
    def _per_frame(self) -> int:
        """Return the backlog units a dropped frame adds."""
        return max(self._weights) if self._weights else 1

    @property
    def _counted(self) -> int:
        return math.ceil(self._dropped / self._per_frame)

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
        self._dropped = 0
        self._start = self._last = None
        self._weights = None
        self._backlog.clear()
        self._level = None
        self._totals.clear()

    def update(self, decoded: int, shown: int, fps: float) -> None:
        """Add a reading: the frames the decoder has put out, the pictures
        the layer has shown and the video's frame rate."""
        last, start = self._last, self._start
        if (last is None or start is None or fps != self._fps
                or decoded < last[0] or shown < last[1]):
            # The first reading, another rate, or a count that started over.
            self.restart()
            self._start = self._last = (decoded, shown)
            self._fps = fps
            self._totals.append(self.total)
            return
        self._last = (decoded, shown)
        made, pictures = decoded - start[0], shown - start[1]
        if self._weights is None:
            if made < PROBE_FRAMES:
                return
            ratio = pictures / made
            # Two pictures a frame (fields shown), two frames a picture
            # (fields decoded), or one each.
            self._weights = (2, 1) if ratio > 1.5 else (1, 2) if ratio < 0.75 else (1, 1)
        self._backlog.append(made * self._weights[0] - pictures * self._weights[1])
        self._judge()
        self._totals.append(self.total)

    def _judge(self) -> None:
        """Count the rise of the backlog's middle over its level."""
        if len(self._backlog) < BACKLOG_WINDOW:
            return
        middle = sorted(self._backlog)[BACKLOG_WINDOW // 2]
        if self._level is None:
            # The queue's fullest: a frame more waiting is no drop.
            self._level = max(self._backlog)
        elif middle > self._level:
            self._dropped += middle - self._level
            self._level = middle
        elif middle < self._level - self._per_frame:
            # Shown more than decoded, for good: a new level, once the
            # queue's next readings tell it.
            self._backlog.clear()
            self._level = None


def fps_display_texts(video_fps: str | float) -> tuple[str, str, str]:
    """Return (info_text, output_fps_text, total_text) for the FPS row.

    *info_text* reads ``NNN - DDD`` (input - drop).  The input rate is the
    video's FPS rounded to a whole frame, the drop is the rate the service's
    drop watch publishes (see info.fpsdrop), and the output rate is the
    difference.  *total_text* is the frames lost since the title started, or
    '' when the video layer cannot be read.
    """
    try:
        in_fps = round(float(video_fps))
    except (TypeError, ValueError, OverflowError):  # OverflowError: "inf"
        in_fps = 0

    reading = fps_drop_reading() if in_fps else None
    drop, total = reading if reading else (0, None)
    return (f"{in_fps:03d} - {drop:03d}", str(max(0, in_fps - drop)),
            "" if total is None else str(total))
