# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Count the frames the video driver drops, all through playback.

One thread in the service reads the driver's frame counters
(``/sys/class/video/fps_info``) once a second while a video plays, has
``core.helpers.DropCounter`` smooth them and publishes the drop rate and the
frames lost since the title started as a Home-window property.  The FPS row
of the overlay and the dashboard reads it in whichever interpreter they run,
so the total covers the whole title, not only the time a view was open.

When a title starts, after a seek and when playback resumes, the picture
takes a moment to settle and the driver's counters read losses that are
none, so for ``SETTLE_SECONDS`` nothing is counted: the rate reads 0 and the
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
announcement reaches the service later still, while the counters already
show the seek's disruption.  So each reading is held back for one pass and
counted only if no sign of a seek has come by then: the row lags the driver
by a second, and a seek's first second is never counted.

Off Amlogic hardware the counters do not exist: the property stays empty and
the row shows no drop and no total.
"""

import threading
import time

import xbmc
from core.helpers import DropCounter, read_fps_sysfs
from core.log import channel
from core.utils import PROP_FPS_DROP, home_window

# The driver updates its counters once a second.
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


def _play_time() -> float | None:
    """Return the play time in seconds, or None when nothing plays."""
    try:
        return xbmc.Player().getTime()
    except RuntimeError:
        return None


class FpsDropWatch(threading.Thread):
    """Read, count and publish until ``stop`` is called."""

    def __init__(self) -> None:
        super().__init__(name="TinyPPI-fps", daemon=True)
        self._stopping = threading.Event()
        self._counter = DropCounter()
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
        self._held_back: tuple[int, int] | None = None

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
            self._counter.reset()
            self._source = source
            self._clock = None
            self.settle()
        if not source:
            self._publish("")
            return
        if self._held():
            return
        reading = read_fps_sysfs()
        if reading is None:
            self._held_back = None
            self._publish("")
            return
        counted, self._held_back = self._held_back, reading
        if counted is not None:
            if counted[0] != counted[1]:
                _log(f"in {counted[0]}, out {counted[1]}")
            self._counter.update(*counted)
        self._publish(f"{self._counter.rate}|{self._counter.total}")

    def _held(self) -> bool:
        """Return whether this pass counts nothing: holding, or settling."""
        holding = xbmc.getCondVisibility(_HOLDING)
        if (self._jumped(holding) or xbmc.getCondVisibility("Player.Seeking")
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
            self._counter.settle()
            self._publish(f"0|{self._counter.total}")
            return True
        return False

    def _jumped(self, holding: bool) -> bool:
        """Return whether the play time jumped since the last pass: a seek."""
        now, played = time.monotonic(), _play_time()
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
