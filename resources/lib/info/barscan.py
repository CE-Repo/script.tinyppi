# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Measure the black bars of the playing video, all through playback.

One thread in the service captures a small frame of the video twice a
second (``xbmc.RenderCapture``), has ``info.bars`` measure it and publishes
the confirmed bars as a Home-window property, in coded pixels and in the
RPU's ``L | R | T | B`` notation.  ``info.properties`` reads it for the
aspect ratio wherever Dolby Vision declares no bars of its own, in whichever
interpreter the overlay runs.

It runs while a video plays, whether or not a view is open, so the reading
is right the moment the overlay opens and a dark scene has a confirmed value
to fall back on.

The capture only delivers video on CoreELEC builds that serve it from the
Amlogic video layer (the canary builds).  Elsewhere the scanner finds that
out once and stays idle: the property is never set and the aspect ratio is
Kodi's, as before.
"""

import threading
import time

import xbmc
from core import settings
from core.log import channel
from core.utils import PROP_MEASURED_BARS, coded_frame, declared_bars, home_window
from info.bars import BarTracker, capture_size, format_offsets, measure, scaled
from info.dvinfo import get_l5_offsets
from info.framing import FramingWatch

# Seconds between two frames.  The reading follows a change of framing
# within about a second (``bars.CONFIRM_FRAMES`` frames have to agree).
SCAN_INTERVAL = 0.5

# How long one frame may take.  Kodi builds without the capture changes hold
# the interpreter lock for this long, stalling every Python add-on.
_FRAME_TIMEOUT_MS = 300

# Frames in a row that may fail before the scanner backs off, and for how
# long.  A new title tries again at once.
_FAILURE_LIMIT = 3
_RETRY_AFTER   = 60.0

_SETTING = "measure_aspect_ratio"


_log = channel("bars")


class BarScanner(threading.Thread):
    """Capture, measure and publish until ``stop`` is called."""

    def __init__(self) -> None:
        super().__init__(name="TinyPPI-bars", daemon=True)
        self._stopping = threading.Event()
        self._tracker = BarTracker()
        # Rides along on this thread: the widest framing of the title, for
        # the IMAX mark (see info.framing).  It needs no capture.
        self._framing = FramingWatch()
        self._capture: xbmc.RenderCapture | None = None
        # False once this Kodi build has shown that it cannot capture video.
        self._supported = True
        self._failures = 0
        self._retry_at = 0.0
        # The title being measured, and what the property holds (None: not
        # known, so the first pass clears what an earlier session left).
        self._source = ""
        self._published: str | None = None
        self._last_error = ""

    def stop(self) -> None:
        """End the thread after its current pass."""
        self._stopping.set()

    def run(self) -> None:
        self._idle()
        while not self._stopping.wait(SCAN_INTERVAL):
            try:
                self._scan()
                self._framing.follow()
            except Exception as exc:
                self._report(str(exc))
        self._idle()
        self._framing.clear()

    def _report(self, error: str) -> None:
        """Log a failing pass once, not twice a second."""
        if error != self._last_error:
            self._last_error = error
            _log(f"measuring failed: {error}", xbmc.LOGWARNING)

    # --- One pass -----------------------------------------------------------

    def _scan(self) -> None:
        if not self._wanted():
            self._idle()
            return
        self._follow_title()
        if xbmc.getCondVisibility("Player.Paused") or time.monotonic() < self._retry_at:
            return

        capture = self._capture
        if capture is None:
            capture = self._capture = xbmc.RenderCapture()
        width, height = capture_size(capture.getAspectRatio())
        image = self._grab(capture, width, height)
        if image is None:
            return

        self._tracker.update(measure(image, width, height))
        self._publish_bars((width, height))

    def _wanted(self) -> bool:
        """Return whether there is a picture to measure and a use for it.

        Not while Dolby Vision declares its bars: they are exact and need
        no capture.
        """
        if not self._supported or not settings.addon().getSettingBool(_SETTING):
            return False
        if not xbmc.getCondVisibility("Player.HasVideo"):
            return False
        return declared_bars(get_l5_offsets()) is None

    def _follow_title(self) -> None:
        """Start over when another title plays."""
        source = xbmc.getInfoLabel("Player.FilenameAndPath")
        if source != self._source:
            self._idle()
            self._source = source

    def _idle(self) -> None:
        """Drop the capture and everything measured."""
        self._tracker.reset()
        self._capture = None
        self._failures = 0
        self._retry_at = 0.0
        self._source = ""
        self._publish("")

    # --- Capturing ----------------------------------------------------------

    def _grab(self, capture: xbmc.RenderCapture, width: int, height: int) -> bytearray | None:
        """Return one BGRA frame of the video, or None when there is none."""
        try:
            # ``composite`` came with the capture changes that also made the
            # Amlogic video layer capturable, so a Kodi that does not know
            # it cannot deliver a frame either.
            capture.capture(width, height, composite=False)
        except TypeError:
            self._supported = False
            _log("this Kodi build cannot capture the video; the aspect ratio "
                 "is shown as Kodi reports it", xbmc.LOGINFO)
            return None

        image = capture.getImage(_FRAME_TIMEOUT_MS)
        if len(image) != width * height * 4:
            self._failed()
            return None
        self._failures = 0
        return image

    def _failed(self) -> None:
        """Count a missing frame; back off once they keep missing."""
        self._failures += 1
        if self._failures < _FAILURE_LIMIT:
            return
        self._retry_at = time.monotonic() + _RETRY_AFTER
        if self._failures == _FAILURE_LIMIT:
            _log(f"no frames from the video capture; trying again every "
                 f"{_RETRY_AFTER:.0f} s", xbmc.LOGINFO)

    # --- Publishing ---------------------------------------------------------

    def _publish_bars(self, captured: tuple[int, int]) -> None:
        """Publish the confirmed bars in coded pixels."""
        bars  = self._tracker.bars
        coded = coded_frame()
        if bars is None or coded is None:
            return
        self._publish(format_offsets(scaled(bars, captured, coded)))

    def _publish(self, value: str) -> None:
        """Write the property when it changes."""
        if value == self._published:
            return
        self._published = value
        home_window().setProperty(PROP_MEASURED_BARS, value)
        _log(f"bars: {value or 'none'}")
