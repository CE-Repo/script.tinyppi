# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Measure the black bars of the playing video, all through playback.

One thread in the service captures a small frame of the video twenty times a
second (``xbmc.RenderCapture``), has ``info.bars`` measure it and publishes
the confirmed bars as a Home-window property, in coded pixels and in the
RPU's ``L | R | T | B`` notation.  ``info.properties`` reads it for the
aspect ratio, ahead of the bars Dolby Vision declares in L5, in whichever
interpreter the overlay runs.  The L5 readings themselves are not touched.

It runs whenever a video plays, whether or not a view is open, so the reading
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
from core.log import channel
from core.utils import PROP_MEASURED_BARS, coded_frame, home_window
from info.bars import (
    CONFIRM_SECONDS,
    DARK_CONFIRM_SECONDS,
    Bars,
    BarTracker,
    Lines,
    bars_of,
    capture_size,
    crops,
    format_offsets,
    has_bars,
    line_counts,
    measure_dark,
    picture_ratio,
    scaled,
    shows_again,
)
from info.framing import FOLLOW_INTERVAL, FramingWatch
from info.properties import is_standard_ar

# Seconds from one frame to the next: twenty a second.  A change of framing
# shows ``bars.CONFIRM_SECONDS`` after it was first seen, about a sixth of a
# second after it happened.
SCAN_INTERVAL = 0.05
# The shortest pause between two passes, so a slow pass leaves the
# interpreter to Kodi's other add-ons.
_MIN_PAUSE    = 0.005

# How long one frame may take.  Kodi builds without the capture changes hold
# the interpreter lock for this long, stalling every Python add-on.
_FRAME_TIMEOUT_MS = 300

# Frames in a row that may fail before the scanner backs off, and for how
# long.  A new title tries again at once.
_FAILURE_LIMIT = 10
_RETRY_AFTER   = 60.0


_log = channel("bars")


def _known(measured: Bars | None, size: tuple[int, int]) -> Bars | None:
    """Return *measured* when it is a framing films are made in, else None.

    That is the full frame or bars that leave a standard ratio.  Anything
    else is a title card, a fade or a logo far more often than a picture,
    so it proves nothing.
    """
    if measured is None or not has_bars(measured):
        return measured
    return measured if is_standard_ar(picture_ratio(measured, size)) else None


def _dark_bars(image: bytearray, size: tuple[int, int]) -> Bars | None:
    """Return the bars of a dark frame at the start of a title.

    A film that opens on black would show nothing until its first bright
    scene.  The dark measurement is the weaker proof, so it only counts
    when it makes a standard film ratio.
    """
    return _known(measure_dark(image, *size), size)


class BarScanner(threading.Thread):
    """Capture, measure and publish until ``stop`` is called."""

    def __init__(self) -> None:
        super().__init__(name="TinyPPI-bars", daemon=True)
        self._stopping = threading.Event()
        self._tracker = BarTracker()
        # Rides along on this thread: the widest framing of the title, for
        # the IMAX mark (see info.framing).  It needs no capture.
        # It keeps its own, slower pace.
        self._framing = FramingWatch()
        self._framing_due = 0.0
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
        pause = SCAN_INTERVAL
        while not self._stopping.wait(pause):
            started = time.monotonic()
            try:
                self._scan()
                self._follow_framing()
            except Exception as exc:
                self._report(str(exc))
            # The pass's own time counts towards the interval.
            pause = max(_MIN_PAUSE, SCAN_INTERVAL - (time.monotonic() - started))
        self._idle()
        self._framing.clear()

    def _follow_framing(self) -> None:
        """Run the framing watch when its next pass is due."""
        now = time.monotonic()
        if now >= self._framing_due:
            self._framing_due = now + FOLLOW_INTERVAL
            self._framing.follow()

    def _report(self, error: str) -> None:
        """Log a failing pass once, not on every pass."""
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

        size = (width, height)
        measured, hold = self._measure(image, size)
        self._tracker.update(measured, time.monotonic(), hold)
        self._publish_bars(size)

    def _measure(self, image: bytearray, size: tuple[int, int]) -> tuple[Bars | None, float]:
        """Return the bars a frame shows and how long they have to last."""
        lines = line_counts(image, *size)
        measured = _known(bars_of(lines, *size), size)
        if measured is not None:
            return measured, CONFIRM_SECONDS
        returned = self._returned(lines, size)
        if returned is not None:
            return returned, CONFIRM_SECONDS
        if self._tracker.bars is None:
            return _dark_bars(image, size), DARK_CONFIRM_SECONDS
        return None, CONFIRM_SECONDS

    def _returned(self, lines: Lines, size: tuple[int, int]) -> Bars | None:
        """Return the earlier framing of the title a frame is back at, or None.

        A framing the title has shown before needs less proof: a lit edge
        at its bars.  After a taller picture (an IMAX scene) not even that:
        once nothing shows where the bars were, the last such framing is
        taken, as the taller picture is no longer seen.
        """
        earlier = self._tracker.earlier()
        for bars in earlier:
            if shows_again(lines, *size, bars):
                return bars
        current = self._tracker.bars
        for bars in earlier:
            if current is not None and crops(bars, current) \
                    and shows_again(lines, *size, bars, lit_edge=False):
                return bars
        return None

    def _wanted(self) -> bool:
        """Return whether there is a picture to measure.

        Every video is measured, Dolby Vision with L5 included.
        """
        return self._supported and xbmc.getCondVisibility("Player.HasVideo")

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
