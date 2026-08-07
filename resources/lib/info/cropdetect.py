"""Live black-bar detection from the decoded picture.

Dolby Vision Level 5 offsets live in the RPU and are read once per file by
dvinfo.py, so a title whose aspect ratio changes mid-playback (IMAX Enhanced
and friends) keeps showing the offsets of whatever shot hdrprobe happened to
see.  This module derives the same four numbers from the picture itself,
without touching an RPU.

The measurement comes from the **borderprobe** helper (info.borderprobe): it
opens the playing file, seeks to the current position, decodes a few frames and
scans their luma plane for black rows and columns, reporting the bar thickness
in coded pixels.  Every stream is measured, whatever its HDR format.  The bars
feed the aspect ratio row, which is drawn for all of them and can otherwise
only report the container's ratio -- an HDR10 film at 1.90:1 inside a 16:9
frame would read as 1.78:1 for its whole runtime.

## Why not the capture node any more

This used to read ``/dev/amvideocap0``, the scaled copy of the video plane that
Hyperion's Amlogic grabber uses.  That was very cheap and showed exactly what
was on screen, and it had one fatal property: it exists on Amlogic and nowhere
else, so nothing about this file could be developed, tested or reproduced off
the box.  It also read a 320x180 scaled grab, which quantised a 2160-line
frame's bars to 12 coded lines and needed a sample window, a settle test and a
"has it really moved" damper on top just to stop the displayed number
flickering between 276 and 288 on a film that never changed.

borderprobe measures the coded frame at full resolution, so the bar edge it
reports is the bar edge, and it does its own multi-frame median and hysteresis
where the pixels are.  All of that machinery is therefore gone from here, and
what is left is the part that was always TinyPPI's own: deciding when a
measurement should override the RPU's exact numbers.

Everything here is still best-effort.  A missing binary, a file the helper
cannot open, or a picture too dark to judge all yield ``''``, and properties.py
falls back to the static RPU value.  Measuring happens on a sampler thread that
runs only while the overlay is reading, so nothing ever blocks the window; a
circuit breaker stops trying for the rest of the file once the helper has
failed repeatedly, so a box without a working binary pays a handful of failed
starts and nothing more.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import parse_offsets
from info import borderprobe

# One measurement per second, which is the rate the overlay refreshes at and
# the rate the helper was designed around.  The old capture path sampled four
# times a second only because it needed three agreeing grabs before it could
# publish anything; borderprobe samples several frames inside a single query,
# so the window is gone and with it the reason to poll faster than the display
# changes.
_SAMPLE_INTERVAL = 1.0

# Stop sampling once nothing has read a value for this long: the sampler exists
# to serve the overlay, and the overlay closing is what ends it.
_IDLE_TIMEOUT = 3.0

# Give up on the helper after this many consecutive failures.
_FAILURE_LIMIT = 3

# How far a measurement may sit from the RPU's own numbers and still count as
# describing the same framing, in coded pixels.  The RPU value is exact and the
# measurement is very nearly so, but a bar edge that falls inside a coding
# block can legitimately be read a pixel or two either way.  A real change of
# framing is an order of magnitude larger -- an IMAX shot opening from 2.39:1
# to 1.90:1 moves the bars by over two hundred coded lines.
_STATIC_MATCH_TOLERANCE = 8

_lock = threading.Lock()
_measurement: tuple[int, int, int, int] | None = None
_path = ""            # file the state above belongs to
_failures = 0
_disabled = False     # circuit breaker, cleared on the next file
_thread: threading.Thread | None = None
_last_request = 0.0   # monotonic clock of the last live_l5_offsets() call

_SIDES_PATH_PROPERTY = "TinyPPI.Sides.Path"
_SIDES_PROPERTY = "TinyPPI.Sides.Min"


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _clear_locked() -> None:
    """Drop the sampling state; call under the lock."""
    global _measurement, _path, _failures, _disabled

    _measurement = None
    _path = ""
    _failures = 0
    _disabled = False

    window = xbmcgui.Window(10000)
    window.clearProperty(_SIDES_PATH_PROPERTY)
    window.clearProperty(_SIDES_PROPERTY)


def reset_live_detection() -> None:
    """Drop all detection state; called on playback stop and on a file change.

    The sampler thread is left to notice on its own: it stops as soon as
    nothing has asked for a value, which happens the moment the overlay closes,
    and it closes the helper process on its way out.
    """
    with _lock:
        _clear_locked()


def live_detection_enabled() -> bool:
    """Return whether live detection is switched on.

    A fresh ``Addon()`` avoids the cached settings, so toggling the option
    applies while the overlay stays open -- same trick as
    publish_channel_visibility.

    Updating the addon mid-playback unregisters our id for a moment, and this
    runs on the overlay's poll: treat that window as "off" rather than letting
    it take the polling loop down, the way it once took the splash down.
    """
    try:
        return xbmcaddon.Addon().getSetting("l5_live_detect") == "true"
    except (RuntimeError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Sampler
# --------------------------------------------------------------------------- #

def _sampler(source: str) -> None:
    """Measure *source* once a second until the overlay stops reading.

    The helper process lives exactly as long as this thread does.  It is opened
    here rather than by the caller because opening it is the slow part -- on a
    file across the network it can take a second or two while libavformat pulls
    the index -- and the overlay's poll must never wait for that.
    """
    global _thread, _measurement, _failures, _disabled

    monitor = xbmc.Monitor()
    probe = None

    try:
        probe = borderprobe.open_probe(source)
        if probe is None:
            with _lock:
                _disabled = True
            return

        while True:
            with _lock:
                idle = time.monotonic() - _last_request > _IDLE_TIMEOUT
                stale = _path != source
                if _disabled or idle or stale:
                    return

            try:
                seconds = xbmc.Player().getTime()
            except RuntimeError:
                return  # playback ended under us

            try:
                bars = probe.measure(seconds)
            except borderprobe.BorderProbeError as exc:
                with _lock:
                    _failures += 1
                    give_up = _failures >= _FAILURE_LIMIT
                    if give_up:
                        _disabled = True
                        _measurement = None
                        _log(f"L5 live: borderprobe unusable ({exc}), "
                             "staying on the RPU value", xbmc.LOGINFO)
                if give_up:
                    return

                # A broken helper cannot recover on its own; start a new one.
                # The failure count deliberately survives this: a helper that
                # dies on every measurement can be restarted every time, so
                # counting only the restarts that *fail* would never reach the
                # limit and the breaker would never trip.
                probe.close()
                probe = borderprobe.open_probe(source)
                if probe is None:
                    with _lock:
                        _disabled = True
                    return
            else:
                with _lock:
                    _failures = 0
                    # None means the helper had nothing for this position -- a
                    # fade to black, a shot too dark to judge.  Hold the last
                    # confident value rather than flickering back to the static
                    # one.
                    if bars is not None:
                        _measurement = bars

            if monitor.waitForAbort(_SAMPLE_INTERVAL):
                return
    finally:
        if probe is not None:
            probe.close()
        with _lock:
            _thread = None


def _ensure_sampler(source: str) -> None:
    """Start the sampler thread unless one is already running."""
    global _thread

    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_sampler, args=(source,), daemon=True)
        _thread.start()


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #

def _prefer_static(static: str, measured: str) -> str:
    """Return the offsets to display, keeping the RPU's own numbers where they
    still describe the picture.

    The RPU is exact and the measurement is not quite, so replacing 276 with
    277 for the same framing only makes the display worse.  The static value
    therefore stands until the measurement clearly departs from it -- which is
    what an aspect ratio change does -- and takes over again once the film
    returns to its base framing.
    """
    if not measured:
        return static

    wanted = parse_offsets(static)
    got = parse_offsets(measured)
    if wanted is None or got is None:
        # No usable pair to compare (static is still "Fetching...", say): the
        # measurement is the only real information available.
        return measured

    same_framing = all(
        abs(a - b) <= _STATIC_MATCH_TOLERANCE for a, b in zip(wanted, got)
    )
    return static if same_framing else measured


def _hold_sides(static: str, measured: str) -> str:
    """Return the measurement with its side bars pinned to the thinnest known.

    Side bars do not come and go.  A film is pillarboxed or it is not, unlike
    the top and bottom bars an IMAX sequence genuinely moves.  borderprobe
    already refuses to report a bar that only one side of the frame supports,
    which is what a dark edge in the picture looks like -- but a scene that is
    dark down *both* edges defeats that test, because the two sides agree.
    Only time tells those apart, and this is where time is available.

    A dark edge can only ever add apparent bar, never remove real one, so the
    thinnest value seen is the trustworthy one and this only ever shrinks.  It
    starts from what the RPU declares, which settles the common case on the
    very first poll instead of after the first bright scene.

    Kept on the home window so it survives the overlay being closed, like the
    rest of the per-file state.
    """
    bars = parse_offsets(measured)
    if bars is None:
        return measured

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return measured

    window = xbmcgui.Window(10000)
    known = None
    if window.getProperty(_SIDES_PATH_PROPERTY) == path:
        try:
            known = int(window.getProperty(_SIDES_PROPERTY))
        except ValueError:
            known = None
    if known is None:
        declared = parse_offsets(static)
        if declared is not None:
            known = min(declared[0], declared[1])

    side = min(bars[0], bars[1])
    if known is not None:
        side = min(side, known)

    window.setProperty(_SIDES_PATH_PROPERTY, path)
    window.setProperty(_SIDES_PROPERTY, str(side))

    return " | ".join(str(value) for value in (side, side, bars[2], bars[3]))


def live_measurement_available() -> bool:
    """Return whether a measurement exists for the playing file.

    Lets a caller tell "the picture has no bars" from "nobody has looked".  Both
    read as ``0 | 0 | 0 | 0``, and acting on the second would mark a whole film
    as IMAX on the strength of a value nothing ever measured.

    Tied to the playing file: the reading is only cleared on a file change by
    live_l5_offsets(), which returns early when detection is off, so without
    this check a reading from the previous film could still answer for this one.

    A pure state read: it does not start a measurement and does not keep the
    sampler alive.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return False

    with _lock:
        return _measurement is not None and path == _path


def live_detection_pending() -> bool:
    """Return whether a measurement is expected for this stream but has not
    arrived yet, so the caller can show a placeholder rather than a value.

    A pure state read: it neither measures nor keeps the sampler alive --
    resolve_l5_offsets() does both, and must be called first in a poll.
    """
    if not live_detection_enabled():
        return False
    with _lock:
        return bool(_path) and not _disabled and _measurement is None


def resolve_l5_offsets(static: str) -> str:
    """Return the offsets to display for the playing file.

    ``static`` is what the RPU reported (or dvinfo's placeholder / status
    label).  It is preferred; the live measurement only overrides it once the
    picture stops matching it -- and only ever on the top and bottom bars, the
    sides being pinned by _hold_sides before the comparison.
    """
    return _prefer_static(static, _hold_sides(static, live_l5_offsets()))


def live_l5_offsets() -> str:
    """Return the measured active-area offsets for the playing file as
    ``left | right | top | bottom`` in coded pixels.

    Returns ``''`` whenever there is nothing confident to show -- detection off,
    nothing playing, the helper gave up, or no measurement has arrived yet --
    which is the caller's signal to show the static RPU value.

    Never blocks: the reading is whatever the sampler thread last measured, and
    calling this is what keeps that thread alive.
    """
    global _path, _last_request

    if not live_detection_enabled():
        return ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""
    if not path:
        return ""

    with _lock:
        if path != _path:
            _clear_locked()
            _path = path
        if _disabled:
            return ""
        _last_request = time.monotonic()
        reading = _measurement

    _ensure_sampler(path)

    if reading is None:
        return ""
    return " | ".join(str(value) for value in reading)
