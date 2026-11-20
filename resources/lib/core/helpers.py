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

# The video layer's state, with the time stamp of the picture on screen:
# ``cur vpts=118791180``, in 90 kHz ticks.  The driver lists it only while a
# frame waits in its queue.
VIDEO_STATES_PATH = "/sys/class/video/vframe_states"
_VIDEO_PTS_RE = re.compile(r"cur vpts=(-?\d+)")

# Time stamps count 90 000 ticks a second in 32 bits, and wrap.
PTS_CLOCK = 90_000
PTS_WRAP = 1 << 32


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


def read_video_pts() -> int | None:
    """Return the time stamp of the picture on screen (90 kHz), or None."""
    return _read_number(VIDEO_STATES_PATH, _VIDEO_PTS_RE)


# The hardware decoder's statistics, with the frames it has put out so far:
# ``  frame count : 688`` (the first channel's, the video's).
DECODER_STATUS_PATH = "/sys/class/vdec/vdec_status"
_DECODED_COUNT_RE = re.compile(r"frame count\s*:\s*(\d+)")


def read_decoded_count() -> int | None:
    """Return the frames the hardware decoder has put out so far, or None."""
    return _read_number(DECODER_STATUS_PATH, _DECODED_COUNT_RE)


# Readings the drop rate is judged over.
DROP_WINDOW = 5
# A reading whose time stamp moves on by more than this many seconds' worth
# of frames is a jump in the stream, not dropped frames.
MAX_JUMP_SECONDS = 2.0
# Between two readings the decoder must have put out at least this share of
# the frames the time stamp went past, or the stream left pictures out.
DECODED_SHARE = 0.85


class FrameTally:
    """Count the frames the video layer skipped.

    Each reading holds the time stamp of the picture on screen and the
    count of pictures shown.  Between two readings the time stamp says how
    many frames of the film went by, the count how many of them were shown;
    the rest were skipped.  A picture that stays on screen longer moves
    neither, so a stall is no drop.  Both are exact counts, so no clock and
    no smoothing is needed.

    An encoder may leave out pictures that repeat the one before (VC-1
    does, in black or still scenes): the time stamp goes past them, but
    there was never a frame to show.  The decoder's count of the frames it
    put out tells: where it falls short of the frames the time stamp went
    past (by more than the queue's ups and downs), the stream left pictures
    out and the stretch between the two readings is not judged.  The
    decoder's count alone cannot tell a drop, as the queue between decoder
    and layer fills by a dozen frames when frames are small and empties
    after.

    Interlaced video may be shown as two pictures a frame, its fields, or be
    decoded as two fields a frame; the first readings tell, and skipped
    fields count as the frames they belong to (a lone field as one).  A time
    stamp that goes back or leaps ahead is a jump in the stream: the tally
    takes it as a new starting point.
    """

    def __init__(self) -> None:
        self._totals: deque[int] = deque(maxlen=DROP_WINDOW + 1)
        self._closed = 0          # frames dropped in earlier stretches
        self._counted = 0         # frames dropped in this stretch
        # The last reading: time stamp, pictures shown, frames decoded.
        self._last: tuple[int, int, int] | None = None
        self._fps = 0.0
        self._step = 0.0          # ticks from one picture to the next; 0 until known
        self._fields = 1          # pictures a frame: 2 for interlaced fields
        self._decoded_fields = 1  # decoded counts a frame: 2 for fields

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
        self._last = None
        self._step = 0.0
        self._totals.clear()

    def update(self, pts: int, shown: int, decoded: int, fps: float) -> None:
        """Add a reading: the time stamp on screen, the pictures shown so far,
        the frames the decoder has put out and the video's frame rate."""
        last = self._last
        if (last is None or fps != self._fps or shown < last[1]
                or decoded < last[2]):
            # The first reading, another rate, or a count that started over.
            self.restart()
            self._last, self._fps = (pts, shown, decoded), fps
            self._totals.append(self.total)
            return
        ticks, pictures = (pts - last[0]) % PTS_WRAP, shown - last[1]
        made = decoded - last[2]
        self._last = (pts, shown, decoded)
        if ticks > MAX_JUMP_SECONDS * PTS_CLOCK + PTS_CLOCK * pictures / fps:
            # Back in time (a huge forward step after the wrap) or far ahead.
            self._step = 0.0
            return
        if self._step or self._learn(ticks, pictures, made):
            self._judge(ticks, pictures, made)
            self._totals.append(self.total)

    def _learn(self, ticks: int, pictures: int, made: int) -> bool:
        """Learn the pictures a frame from the first step; False without one."""
        if not pictures:
            return False
        frames = ticks * self._fps / PTS_CLOCK
        # Interlaced video shown or decoded as fields counts twice.
        self._fields = 2 if pictures > 1.5 * frames else 1
        self._decoded_fields = 2 if made > 1.5 * frames else 1
        self._step = PTS_CLOCK / self._fps / self._fields
        return True

    def _judge(self, ticks: int, pictures: int, made: int) -> None:
        """Count the frames skipped in a step, unless the stream left some out."""
        frames = ticks * self._fps / PTS_CLOCK
        if made / self._decoded_fields < DECODED_SHARE * frames:
            # Pictures the stream left out: nothing to judge.
            return
        skipped = round(ticks / self._step) - pictures
        self._counted += max(0, math.ceil(skipped / self._fields))


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
