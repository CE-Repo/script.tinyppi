"""Live black-bar detection from the decoded picture.

Dolby Vision Level 5 offsets live in the RPU, and only a Dolby Vision title has
them at all: every other format states nothing about where the picture sits in
the frame.  Where the RPU is read from a probe (dvinfo.py's fallback path) it is
also read once per file, so a title whose aspect ratio changes mid-playback
(IMAX Enhanced and friends) keeps showing the offsets of whatever shot the probe
happened to see.  This module derives the same four numbers from the picture
itself, without touching an RPU.

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
what is left is the part that was always TinyPPI's own: holding the side bars
to the thinnest ever seen, and standing in the RPU's numbers until a
measurement has actually landed.

A measurement, once it lands, is what gets shown.  An earlier version kept the
RPU's own numbers whenever the two agreed to within a few pixels, on the
grounds that the RPU is exact and a measured bar edge is only nearly so; that
made the feature invisible on the many titles whose framing never changes,
where the measurement simply confirms the RPU.  Showing what was measured is
the honest answer to "what is on screen", and borderprobe's own hysteresis
already keeps the number from twitching between neighbouring pixels.

Everything here is still best-effort.  A missing binary, a file the helper
cannot open, or a picture too dark to judge all yield ``''``, and properties.py
falls back to the static RPU value.  Measuring happens on a sampler thread that
runs only while the overlay is reading, so nothing ever blocks the window;
retries keep going for as long as the overlay stays open, and a circuit
breaker only stops them once the helper has failed continuously for ten
seconds, so a box without a working binary still pays for that once and then
nothing more, while a file that is merely slow to start gets the time it
needs.  Reopening the overlay clears the breaker and starts the attempt over.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import parse_offsets
from info import borderprobe

# Twice a second.  What the display can actually follow is set by three delays
# in series: this interval, the up-to-one-GOP lag in measuring the keyframe at
# or before the current position (one second on a UHD remux), and how long the
# overlay takes to pick the reading up -- the last of which properties.py now
# closes to a third of a second.  Halving this halves the largest term left
# that TinyPPI controls, which is what an aspect-ratio change waits on before
# the row and the IMAX badge follow the picture.
#
# It is paid for by asking borderprobe for fewer frames per query (see
# _PROBE_OPTIONS), so the decoding cost per second is roughly what it was; the
# bytes pulled per second do rise, which is the trade for a file on a share.
_SAMPLE_INTERVAL = 0.5

# Stop sampling once nothing has read a value for this long: the sampler exists
# to serve the overlay, and the overlay closing is what ends it.
_IDLE_TIMEOUT = 3.0

# Say so once when the helper keeps answering "nothing measurable" this many
# times running.  That is not a failure -- it is the honest answer for a fade
# to black or a shot too dark to judge -- but a file that never gives anything
# else would otherwise measure nothing in complete silence.
_UNMEASURABLE_REPORT_AFTER = 5

# Give up on the helper only after it has failed continuously for this long.
# A single bad file (broken binary, unreadable stream) reaches this quickly and
# stops retrying for the rest of the playback; a file that is merely slow to
# seek at the start (a network share, a large remux) gets long enough to come
# good instead of being written off after a couple of one-second samples.
_FAILURE_TIMEOUT = 10.0

# How long the display waits for the first measurement before falling back to
# whatever the RPU declared.  The measurement is the value that will be shown,
# so until it lands the RPU's number is a stand-in, and the placeholder says so
# rather than showing a figure that is about to be replaced.  Long enough for a
# first seek into a large remux across the network, which is seconds, not
# milliseconds; after it the RPU value stands and the measurement still takes
# over the moment it arrives.
_PENDING_GRACE = 10.0

_lock = threading.Lock()
_measurement: tuple[int, int, int, int] | None = None
_path = ""            # file the state above belongs to
_pending_since: float | None = None  # monotonic clock of when this file's
                                      # first measurement was set in motion
_failure_since: float | None = None  # monotonic clock of the start of the
                                      # current unbroken run of failures
_disabled = False     # circuit breaker, cleared on the next file
_thread: threading.Thread | None = None
_last_request = 0.0   # monotonic clock of the last live_l5_offsets() call

_SIDES_PATH_PROPERTY = "TinyPPI.Sides.Path"
_SIDES_PROPERTY = "TinyPPI.Sides.Min"


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _clear_locked() -> None:
    """Drop the sampling state; call under the lock."""
    global _measurement, _path, _pending_since, _failure_since, _disabled

    _measurement = None
    _path = ""
    _pending_since = None
    _failure_since = None
    _disabled = False

    window = xbmcgui.Window(10000)
    window.clearProperty(_SIDES_PATH_PROPERTY)
    window.clearProperty(_SIDES_PROPERTY)


def reset_live_detection() -> None:
    """Drop all detection state; called on playback stop, on a file change, and
    every time the overlay opens, so a film that never got a measurement in an
    earlier session -- or that had detection give up -- gets a clean attempt.

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
    global _thread, _measurement, _failure_since, _disabled

    monitor = xbmc.Monitor()
    probe = None
    unmeasurable = 0   # consecutive "nothing measurable" answers

    if not borderprobe.binary_path():
        # The binary is either shipped or it is not; unlike a file that is slow
        # to open, retrying this every second for ten seconds cannot change the
        # answer, and binary_path() has already logged what it looked for.
        with _lock:
            _disabled = True
        return

    def _record_failure(exc: object) -> bool:
        """Note a failed attempt; return True once it has failed continuously
        for ``_FAILURE_TIMEOUT``.  Call under the lock."""
        global _failure_since, _disabled, _measurement

        now = time.monotonic()
        if _failure_since is None:
            _failure_since = now
        give_up = now - _failure_since >= _FAILURE_TIMEOUT
        if give_up:
            _disabled = True
            _measurement = None
            _log(f"L5 live: borderprobe unusable ({exc}), "
                 "staying on the RPU value", xbmc.LOGINFO)
        return give_up

    try:
        while True:
            with _lock:
                idle = time.monotonic() - _last_request > _IDLE_TIMEOUT
                stale = _path != source
                if _disabled or idle or stale:
                    return

            if probe is None:
                # Opening is retried every sample interval for as long as the
                # overlay keeps reading, rather than giving up the moment it
                # fails once: a file across the network can take a few tries
                # before libavformat has the index.
                probe = borderprobe.open_probe(source)
                if probe is None:
                    with _lock:
                        if _record_failure("helper failed to start"):
                            return
                    if monitor.waitForAbort(_SAMPLE_INTERVAL):
                        return
                    continue
                _log("L5 live: measuring the picture", xbmc.LOGINFO)

            try:
                seconds = xbmc.Player().getTime()
            except RuntimeError:
                return  # playback ended under us

            try:
                bars = probe.measure(seconds)
            except borderprobe.BorderProbeError as exc:
                # A broken helper cannot recover on its own; drop it here so
                # the top of the loop opens a fresh one next time round. The
                # failure clock deliberately survives the restart: a helper
                # that dies on every measurement could otherwise be restarted
                # forever without ever reaching the timeout.
                probe.close()
                probe = None
                with _lock:
                    if _record_failure(exc):
                        return
            else:
                with _lock:
                    _failure_since = None
                    # None means the helper had nothing for this position -- a
                    # fade to black, a shot too dark to judge.  Hold the last
                    # confident value rather than flickering back to the static
                    # one.
                    if bars is not None:
                        first = _measurement is None
                        _measurement = bars

                if bars is None:
                    unmeasurable += 1
                    if unmeasurable == _UNMEASURABLE_REPORT_AFTER:
                        _log(f"L5 live: nothing measurable in the picture "
                             f"({probe.last_none_reason}) after {unmeasurable} "
                             "tries; holding the static value", xbmc.LOGINFO)
                else:
                    unmeasurable = 0
                    if first:
                        _log("L5 live: measured "
                             + " | ".join(str(v) for v in bars), xbmc.LOGINFO)

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


def live_detection_settling() -> bool:
    """Return whether the first measurement for this file is still expected
    *soon* -- the window in which a caller should show the placeholder rather
    than a static value that is about to be replaced.

    Bounded by ``_PENDING_GRACE`` so a picture that never yields a measurement
    (dark throughout, say) hands the display back to the RPU instead of
    spinning for the rest of the film.

    A pure state read: it neither measures nor keeps the sampler alive.
    """
    if not live_detection_enabled():
        return False
    with _lock:
        if _disabled or _measurement is not None or _pending_since is None:
            return False
        return time.monotonic() - _pending_since < _PENDING_GRACE


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
    label).  The measurement wins whenever there is one: it describes the
    picture actually on screen, which is the point of the feature, and a title
    whose RPU already names the same framing loses nothing by being shown the
    number that was measured from it.  ``static`` therefore stands in only
    until the first measurement lands, and again when detection is switched
    off or has given up.

    The sides are pinned by _hold_sides first -- see there for why they are
    held differently from the top and bottom bars.
    """
    measured = _hold_sides(static, live_l5_offsets())
    return measured or static


def live_l5_offsets() -> str:
    """Return the measured active-area offsets for the playing file as
    ``left | right | top | bottom`` in coded pixels.

    Returns ``''`` whenever there is nothing confident to show -- detection off,
    nothing playing, the helper gave up, or no measurement has arrived yet --
    which is the caller's signal to show the static RPU value.

    Never blocks: the reading is whatever the sampler thread last measured, and
    calling this is what keeps that thread alive.
    """
    global _path, _pending_since, _last_request

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
            _pending_since = time.monotonic()
        if _disabled:
            return ""
        _last_request = time.monotonic()
        reading = _measurement

    _ensure_sampler(path)

    if reading is None:
        return ""
    return " | ".join(str(value) for value in reading)
