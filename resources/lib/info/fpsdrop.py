# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Count the frames the video driver drops, all through playback.

One thread in the service reads, once a second while a video plays, the
video layer's count of the frames it has shown (``toggle_count`` in
``/sys/class/media-configs/video``) and the video's frame rate.  It waits
for the count to move on, a few hundredths of a second at most, and notes
the time the new picture appeared.  ``core.helpers.FrameTally`` compares the
frames due in that time with those shown, as Kodi does for its own drop
count, and the thread publishes the drop rate and the frames lost since the
title started as a Home-window property.

The time is the system clock's: Kodi refreshes its play time only every
200 ms, five frames' worth, and the play time is used to tell a seek only.  The FPS row
of the overlay and the dashboard reads it in whichever interpreter they run,
so the total covers the whole title, not only the time a view was open.

When a title starts, after a seek and when playback resumes, the picture
takes a moment to settle and frames go missing that are no fault of the
playback, so for ``SETTLE_SECONDS`` nothing is counted: the rate reads 0 and the
total stays as it was.  Several signs start that wait, whichever comes
first:

* Kodi's announcements, passed on by the service's monitor
  (``Player.OnAVStart``, ``Player.OnSeek``, ``Player.OnResume``);
* another title playing;
* a seek under way (``Player.Seeking``), or the play time moving by more
  than the clock did: a seek Kodi has not announced yet;
* the end of a pause, of buffering or of fast forward / rewind, during which
  nothing is counted either.

Kodi announces a seek only once its player carries it out, and the
announcement reaches the service later still, while the frame count
already shows the seek's disruption.  So each reading is held back for one pass and
counted only if no sign of a seek has come by then: the row lags the driver
by a second, and a seek's first second is never counted.

Without the frame count (off Amlogic hardware, or a driver without it) the
property stays empty and the row shows no drop and no total.
"""

import threading
import time

import xbmc
from core.helpers import FrameTally, read_toggle_count
from core.log import channel
from core.utils import PROP_FPS_DROP, first_float, home_window

# Seconds from one pass to the next.
SAMPLE_INTERVAL = 1.0

# Seconds after a title starts, a seek or a resume in which nothing is
# counted, while the picture settles.
SETTLE_SECONDS = 3.0

# How far the play time may move apart from the clock between two passes
# before it counts as a seek, in seconds.
JUMP_TOLERANCE = 1.0

# A player that moves no frames at the normal pace: nothing is counted, and
# the wait starts once it plays again.
_HOLDING = "Player.Paused | Player.Caching | Player.Forwarding | Player.Rewinding"

_log = channel("fps")


# How long a pass waits for the next picture, and how often it looks.
FRAME_WAIT = 0.25
FRAME_POLL = 0.001

# One reading: when a picture appeared, the frames shown so far with it and
# the video's rate.
Reading = tuple[float, int, float]


def _play_time() -> float | None:
    """Return the play time in seconds, or None when nothing plays."""
    try:
        return xbmc.Player().getTime()
    except RuntimeError:
        return None


def _catch_frame() -> tuple[float, int] | None:
    """Wait for the next picture; return when it appeared and the count.

    None when the count cannot be read, or no picture came within
    ``FRAME_WAIT``.
    """
    first = read_toggle_count()
    if first is None:
        return None
    deadline = time.monotonic() + FRAME_WAIT
    while time.monotonic() < deadline:
        time.sleep(FRAME_POLL)
        shown = read_toggle_count()
        if shown != first:
            return (time.monotonic(), shown) if shown is not None else None
    return None


def _video_fps() -> float | None:
    """Return the video's frame rate as Kodi reports it, or None."""
    fps = first_float(xbmc.getInfoLabel("Player.Process(videofps)"))
    return fps if fps and fps > 0 else None


class FpsDropWatch(threading.Thread):
    """Read, count and publish until ``stop`` is called."""

    def __init__(self) -> None:
        super().__init__(name="TinyPPI-fps", daemon=True)
        self._stopping = threading.Event()
        self._tally = FrameTally()
        # The title being counted, and what the property holds (None: not
        # known, so the first pass clears what an earlier session left).
        self._source = ""
        self._published: str | None = None
        self._last_error = ""
        # Nothing is counted before this time (monotonic): the wait after a
        # start, a seek or a resume.
        self._settle_until = 0.0
        # Whether the last pass found the player holding (see _HOLDING).
        self._holding = False
        # The last pass's clock and play time, to tell a seek by its jump.
        self._clock: tuple[float, float] | None = None
        # The last reading, counted on the next pass unless a seek shows.
        self._held_back: Reading | None = None

    def stop(self) -> None:
        """End the thread after its current pass."""
        self._stopping.set()

    def settle(self) -> None:
        """Count nothing for ``SETTLE_SECONDS``: playback started, seeked or resumed.

        Called from Kodi's notification thread; the next pass applies it,
        the reading held back included.
        """
        self._settle_until = time.monotonic() + SETTLE_SECONDS

    def run(self) -> None:
        self._publish("")
        pause = SAMPLE_INTERVAL
        while not self._stopping.wait(pause):
            started = time.monotonic()
            try:
                self._sample()
            except Exception as exc:
                self._report(str(exc))
            # Kept in step with the driver's second, not drifting behind it.
            pause = max(0.0, SAMPLE_INTERVAL - (time.monotonic() - started))
        self._publish("")

    def _report(self, error: str) -> None:
        """Log a failing pass once, not on every pass."""
        if error != self._last_error:
            self._last_error = error
            _log(f"counting the dropped frames failed: {error}", xbmc.LOGWARNING)

    def _sample(self) -> None:
        playing = xbmc.getCondVisibility("Player.HasVideo")
        source = xbmc.getInfoLabel("Player.FilenameAndPath") if playing else ""
        if source != self._source:
            # Another title, or none: start over, once its picture settles.
            self._tally.reset()
            self._source = source
            self._clock = None
            self.settle()
        if not source:
            self._publish("")
            return
        played = _play_time()
        if self._held(played):
            return
        reading = self._read(played)
        if reading is None:
            self._held_back = None
            self._publish("")
            return
        counted, self._held_back = self._held_back, reading
        if counted is not None:
            before = self._tally.total
            self._tally.update(*counted)
            if self._tally.total > before:
                _log(f"{self._tally.total - before} frame(s) dropped near "
                     f"{played:.0f} s")
        self._publish(f"{self._tally.rate}|{self._tally.total}")

    @staticmethod
    def _read(played: float | None) -> Reading | None:
        """Return this pass's reading, or None when there is none to take."""
        fps = _video_fps()
        if played is None or fps is None:
            return None
        caught = _catch_frame()
        return None if caught is None else (*caught, fps)

    def _held(self, played: float | None) -> bool:
        """Return whether this pass counts nothing: holding, or settling."""
        holding = xbmc.getCondVisibility(_HOLDING)
        if (self._jumped(holding, played) or xbmc.getCondVisibility("Player.Seeking")
                or (self._holding and not holding)):
            self.settle()
        self._holding = holding
        if holding:
            # No frames at the normal pace; what was counted stays.
            self._held_back = None
            return True
        if time.monotonic() < self._settle_until:
            # Settling after a start, a seek or a resume: no rate, nothing
            # added, and the reading from before the sign is dropped.
            self._held_back = None
            self._tally.restart()
            self._publish(f"0|{self._tally.total}")
            return True
        return False

    def _jumped(self, holding: bool, played: float | None) -> bool:
        """Return whether the play time jumped since the last pass: a seek."""
        now = time.monotonic()
        last = self._clock
        if holding or played is None:
            self._clock = None
            return False
        self._clock = (now, played)
        if last is None:
            return False
        jumped = abs((played - last[1]) - (now - last[0])) > JUMP_TOLERANCE
        if jumped:
            _log(f"play time jumped by {played - last[1]:.1f} s: a seek")
        return jumped

    def _publish(self, value: str) -> None:
        """Write the property when it changes."""
        if value == self._published:
            return
        self._published = value
        home_window().setProperty(PROP_FPS_DROP, value)
