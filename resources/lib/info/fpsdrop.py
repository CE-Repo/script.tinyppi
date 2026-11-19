# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Count the frames the video driver drops, all through playback.

One thread in the service reads the driver's frame counters
(``/sys/class/video/fps_info``) once a second while a video plays, has
``core.helpers.DropCounter`` smooth them and publishes the drop rate and the
frames lost since the title started as a Home-window property.  The FPS row
of the overlay and the dashboard reads it in whichever interpreter they run,
so the total covers the whole title, not only the time a view was open.

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

    def stop(self) -> None:
        """End the thread after its current pass."""
        self._stopping.set()

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
            self._publish("")
            return
        # A paused or seeking player moves no frames; what was counted stays.
        if xbmc.getCondVisibility("Player.Paused | Player.Seeking"):
            return
        reading = read_fps_sysfs()
        if reading is None:
            self._publish("")
            return
        self._counter.update(*reading)
        self._publish(f"{self._counter.rate}|{self._counter.total}")

    def _publish(self, value: str) -> None:
        """Write the property when it changes."""
        if value == self._published:
            return
        self._published = value
        home_window().setProperty(PROP_FPS_DROP, value)
