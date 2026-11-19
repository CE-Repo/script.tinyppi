# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Count the frames the video driver drops, all through playback.

One thread in the service reads the driver's frame counters
(``/sys/class/video/fps_info``) once a second while a video plays, has
``core.helpers.DropCounter`` smooth them and publishes the drop rate and the
frames lost since the title started as a Home-window property.  The FPS row
of the overlay and the dashboard reads it in whichever interpreter they run,
so the total covers the whole title, not only the time a view was open.

After a seek, and when playback resumes from a pause, the picture takes a
moment to settle and the driver's counters read losses that are none, so
for ``SETTLE_SECONDS`` nothing is counted: the rate reads 0 and the total
stays as it was.  The service's monitor reports both (``Player.OnSeek``,
``Player.OnResume``) the moment Kodi announces them; a seek still under way
when a pass runs (``Player.Seeking``), or a pause the last pass saw that is
over, starts the wait as well.

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

# Seconds after a seek or a resume in which nothing is counted, while the
# picture settles.
SETTLE_SECONDS = 3.0

_log = channel("fps")


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
        # seek or a resume.
        self._settle_until = 0.0
        # Whether the last pass found the player paused.
        self._paused = False

    def stop(self) -> None:
        """End the thread after its current pass."""
        self._stopping.set()

    def settle(self) -> None:
        """Count nothing for ``SETTLE_SECONDS``: the player seeked or resumed.

        Called from Kodi's notification thread; the next pass applies it.
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
            # Another title, or none: start over.
            self._counter.reset()
            self._source = source
        if not source:
            self._paused = False
            self._publish("")
            return
        if self._held():
            return
        reading = read_fps_sysfs()
        if reading is None:
            self._publish("")
            return
        self._counter.update(*reading)
        self._publish(f"{self._counter.rate}|{self._counter.total}")

    def _held(self) -> bool:
        """Return whether this pass counts nothing: paused, or settling."""
        paused = xbmc.getCondVisibility("Player.Paused")
        if xbmc.getCondVisibility("Player.Seeking") or (self._paused and not paused):
            self.settle()
        self._paused = paused
        if paused:
            # A paused player moves no frames; what was counted stays.
            return True
        if time.monotonic() < self._settle_until:
            # Settling after a seek or a resume: no rate, nothing added.
            self._counter.settle()
            self._publish(f"0|{self._counter.total}")
            return True
        return False

    def _publish(self, value: str) -> None:
        """Write the property when it changes."""
        if value == self._published:
            return
        self._published = value
        home_window().setProperty(PROP_FPS_DROP, value)
