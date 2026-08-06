"""Live black-bar detection from the Amlogic video capture node.

Dolby Vision Level 5 offsets live in the RPU and are read once per file by
dvinfo.py, so a title whose aspect ratio changes mid-playback (IMAX Enhanced
and friends) keeps showing the offsets of whatever shot hdrprobe happened to
see.  This module derives the same four numbers from the picture itself,
without touching an RPU: ``/dev/amvideocap0`` hands out a scaled copy of the
video plane -- the node Hyperion's Amlogic grabber uses -- the frame is scanned
for black rows and columns, and the bar thickness is scaled back to coded-frame
pixels so the values stay comparable with the RPU ones.

Only Dolby Vision streams are measured -- L5 means nothing for HDR10 or SDR, so
those cost no grab at all.

Everything here is best-effort.  A missing node, a kernel that refuses the
capture or a frame that is too dark to judge all yield ``''``, and properties.py
falls back to the static RPU value.  Grabbing happens on a sampler thread that
runs only while the overlay is reading, so nothing ever blocks the window; a
circuit breaker stops trying for the rest of the file once the node has failed
repeatedly, so a box without working capture pays a handful of failed opens and
nothing more.
"""

import os
import struct
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import clean, info

try:
    import fcntl
except ImportError:  # non-POSIX dev box; capture cannot work there anyway
    fcntl = None

_NODE = "/dev/amvideocap0"

# Grab size.  180 rows over a 2160-line frame quantise the bar thickness to
# 12 coded lines, which the median over the sample window mostly evens out;
# larger buffers cost scan time on every poll for no visible gain.
_GRAB_W, _GRAB_H = 320, 180

# A pixel counts as lit above this level (0-255), and a row or column stays
# "black" while fewer than 1/32 of its pixels are lit -- enough slack for
# compression noise in the bars without swallowing a genuine dim edge.
_BLACK_LEVEL = 26
_LIT_ALLOWANCE = 32

# Reject a reading whose bars would eat this much of an axis: at that point the
# frame is a dark scene rather than a letterboxed one.  2.76:1 in a 16:9 frame,
# the widest ratio in circulation, still only reaches 0.36.
_MAX_BAR_FRACTION = 0.45

# A frame must carry at least this share of lit pixels before its edges mean
# anything.  A black screen with a little sensor or compression noise spread
# across it has every edge reading "not black" and measures as no bars at all --
# and in IMAX titles a black screen is exactly where the aspect ratio changes,
# so that reading would land right when it does the most damage.  Below this
# share the frame is not judged at all and the previous value stands.
_MIN_LIT_FRACTION = 0.05

# Publish only after this many consecutive grabs agree to within the tolerance
# (in grab pixels).  Keeps the values still through cuts and dark shots.
_SAMPLE_WINDOW = 3
_EDGE_TOLERANCE = 2

# How far a measurement may sit from the RPU's own numbers and still count as
# describing the same framing, in grab pixels.  The RPU value is exact; a grab
# quantises a 4K frame to 12 coded lines and the paired-edge rule can shave off
# another, so a couple of grab pixels of disagreement say nothing about the
# picture.  A real change of framing is an order of magnitude larger -- an IMAX
# shot opening from 2.39:1 to 1.90:1 moves the bars by over 200 coded lines.
_STATIC_MATCH_TOLERANCE = 3

# Sampling runs on its own thread rather than on the overlay's one-second poll:
# at one sample per second the window alone costs three seconds before a change
# of aspect ratio shows up.  Four samples a second cut that to 0.75s, and the
# window still spans enough real time that a single dark shot cannot flip the
# value.  The thread stops once nothing has read a value for a while, so it
# lives exactly as long as the overlay is on screen.
_SAMPLE_INTERVAL = 0.25
_IDLE_TIMEOUT = 3.0

# Give up on the node after this many consecutive failures.
_FAILURE_LIMIT = 3

# How long the driver may wait for a frame, in milliseconds.  Well clear of a
# frame interval at 24 fps, and short enough that the grab in onInit cannot
# hold up the overlay opening.
_WAIT_MS = 120

# amvideocap ioctls, magic 'V' (see the kernel's amvideocap.h).
_IOC_WRITE = 1
_IOC_MAGIC = ord("V")


def _iow(number: int, size: int) -> int:
    return (_IOC_WRITE << 30) | (size << 16) | (_IOC_MAGIC << 8) | number


_SET_WIDTH = _iow(0x02, 4)
_SET_HEIGHT = _iow(0x03, 4)
_SET_WAIT_MS = _iow(0x05, 8)

# One byte per brightness level: 1 once the level clears the black point.
_LIT_TABLE = bytes(0 if level <= _BLACK_LEVEL else 1 for level in range(256))

_lock = threading.Lock()
_samples: list[tuple[int, int, int, int]] = []
_settled_reading: tuple[int, int, int, int] | None = None  # in grab pixels
_path = ""            # file the state above belongs to
_failures = 0
_disabled = False     # circuit breaker, cleared on the next file
_thread: threading.Thread | None = None
_last_request = 0.0   # monotonic clock of the last live_l5_offsets() call


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _clear_locked() -> None:
    """Drop the sampling state; call under the lock."""
    global _settled_reading, _path, _failures, _disabled

    _samples.clear()
    _settled_reading = None
    _path = ""
    _failures = 0
    _disabled = False


def reset_live_detection() -> None:
    """Drop all detection state; called on playback stop and on a file change.

    The sampler thread is left to notice on its own: it stops as soon as
    nothing has asked for a value, which happens the moment the overlay closes.
    """
    with _lock:
        _clear_locked()


def _enabled() -> bool:
    """Return whether live detection is switched on.

    A fresh ``Addon()`` avoids the cached settings, so toggling the option
    applies while the overlay stays open -- same trick as publish_channel_visibility.
    """
    return xbmcaddon.Addon().getSetting("l5_live_detect") == "true"


def _is_dolby_vision() -> bool:
    """Return whether the playing stream is Dolby Vision.

    L5 is a DV concept: measuring bars for an HDR10 or SDR stream would fill a
    field that means nothing there, and spend a grab per poll doing it.  The
    property is published by properties.publish_hdr_type() just before the L5
    block runs, and stays empty until hdrprobe has classified the stream, so
    nothing is measured before the format is known.  Mirrors properties._is_dv(),
    which cannot be imported here without a cycle.
    """
    return "dolby" in xbmcgui.Window(10000).getProperty("TinyPPI.HdrType").lower()


def _grab() -> bytes | None:
    """Return one BGR24 frame of the video plane at the grab size, or None."""
    if fcntl is None:
        return None

    try:
        handle = os.open(_NODE, os.O_RDWR)
    except OSError:
        return None

    try:
        fcntl.ioctl(handle, _SET_WIDTH, _GRAB_W)
        fcntl.ioctl(handle, _SET_HEIGHT, _GRAB_H)
        try:
            fcntl.ioctl(handle, _SET_WAIT_MS, struct.pack("Q", _WAIT_MS))
        except OSError:
            pass  # optional; older kernels do not carry this one

        wanted = _GRAB_W * _GRAB_H * 3
        chunks = []
        received = 0
        while received < wanted:
            chunk = os.read(handle, wanted - received)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
    except OSError as exc:
        _log(f"L5 live: capture failed: {exc}")
        return None
    finally:
        os.close(handle)

    return b"".join(chunks) if received == wanted else None


def _lit_map(frame: bytes) -> bytes:
    """One byte per pixel: 1 where the brightest channel clears the black point."""
    brightest = bytes(map(max, frame[0::3], frame[1::3], frame[2::3]))
    return brightest.translate(_LIT_TABLE)


def _leading_black(counts, allowance: int) -> int:
    """Return how many lines from the start of *counts* are still black."""
    black = 0
    for lit in counts:
        if lit > allowance:
            break
        black += 1
    return black


def _paired(near: int, far: int) -> tuple[int, int]:
    """Return the bar width both edges of an axis support.

    Letterboxing and pillarboxing are symmetric: a bar the encoder put there
    exists on both sides.  A bar found on one side only is a dark edge in the
    picture -- a night scene against the left frame border reads as black just
    as convincingly as a real pillarbox -- so the axis is held to whatever the
    weaker edge can back up.  This is what stops readings like ``103 | 0``.
    """
    agreed = min(near, far)
    return agreed, agreed


def _measure(lit: bytes) -> tuple[int, int, int, int] | None:
    """Return ``(left, right, top, bottom)`` in grab pixels, or None when the
    frame carries no usable picture (fade to black, or too dark to trust)."""
    rows = [sum(lit[y * _GRAB_W:(y + 1) * _GRAB_W]) for y in range(_GRAB_H)]
    if sum(rows) < _GRAB_W * _GRAB_H * _MIN_LIT_FRACTION:
        return None

    row_allowance = _GRAB_W // _LIT_ALLOWANCE
    top, bottom = _paired(
        _leading_black(rows, row_allowance),
        _leading_black(reversed(rows), row_allowance),
    )
    if top + bottom > _GRAB_H * _MAX_BAR_FRACTION:
        return None

    # Columns are judged inside the picture band only.  Counting the letterbox
    # rows would measure a column mostly against black that is already accounted
    # for, and scale the allowance against rows the picture never occupies.
    # Checking the vertical bars first also guarantees the band is not empty.
    band_start, band_end = top, _GRAB_H - bottom
    cols = [sum(lit[band_start * _GRAB_W + x:band_end * _GRAB_W:_GRAB_W])
            for x in range(_GRAB_W)]
    col_allowance = (band_end - band_start) // _LIT_ALLOWANCE

    left, right = _paired(
        _leading_black(cols, col_allowance),
        _leading_black(reversed(cols), col_allowance),
    )
    if left + right > _GRAB_W * _MAX_BAR_FRACTION:
        return None

    return left, right, top, bottom


def _coded_size() -> tuple[int, int] | None:
    """Return the coded frame size the offsets have to be expressed in."""
    try:
        width = int(clean(info("Player.Process(videowidth)")))
        height = int(clean(info("Player.Process(videoheight)")))
    except ValueError:
        return None
    return (width, height) if width > 0 and height > 0 else None


def _settled() -> tuple[int, int, int, int] | None:
    """Return the median sample once the window agrees on every edge, else None."""
    if len(_samples) < _SAMPLE_WINDOW:
        return None

    edges = list(zip(*_samples))
    if any(max(edge) - min(edge) > _EDGE_TOLERANCE for edge in edges):
        return None
    return tuple(sorted(edge)[len(edge) // 2] for edge in edges)


def _format(settled: tuple[int, int, int, int], coded: tuple[int, int]) -> str:
    """Scale a grab-pixel reading to coded pixels as ``L | R | T | B``."""
    coded_w, coded_h = coded
    left, right, top, bottom = settled
    return " | ".join(str(round(value * scale)) for value, scale in (
        (left,   coded_w / _GRAB_W),
        (right,  coded_w / _GRAB_W),
        (top,    coded_h / _GRAB_H),
        (bottom, coded_h / _GRAB_H),
    ))


def _sample_once() -> None:
    """Take one reading and fold it into the sample window.

    The grab and the scan both run outside the lock -- the grab can sit on the
    driver for a frame interval, and a reader must never wait that long.
    """
    global _settled_reading, _failures, _disabled

    frame = _grab()
    if frame is None:
        with _lock:
            _failures += 1
            if _failures >= _FAILURE_LIMIT:
                _disabled = True
                _settled_reading = None
                _log(f"L5 live: {_NODE} unusable, staying on the RPU value",
                     xbmc.LOGINFO)
        return

    with _lock:
        _failures = 0

    reading = _measure(_lit_map(frame))
    if reading is None:
        # Fade to black or a shot with no discernible edge: hold the last
        # confident value rather than flickering back to the static one.
        return

    with _lock:
        _samples.append(reading)
        del _samples[:-_SAMPLE_WINDOW]
        settled = _settled()
        if settled is not None:
            _settled_reading = settled


def _sampler() -> None:
    """Sample until the overlay stops reading, or the node gives up."""
    global _thread

    monitor = xbmc.Monitor()
    try:
        while True:
            with _lock:
                stop = _disabled or time.monotonic() - _last_request > _IDLE_TIMEOUT
            if stop:
                return
            _sample_once()
            if monitor.waitForAbort(_SAMPLE_INTERVAL):
                return
    finally:
        with _lock:
            _thread = None


def _ensure_sampler() -> None:
    """Start the sampler thread unless one is already running."""
    global _thread

    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_sampler, daemon=True)
        _thread.start()


def _parse(value: str) -> tuple[int, int, int, int] | None:
    """Return the four offsets in ``L | R | T | B``, or None for anything else
    (an empty field, or one of dvinfo's status labels)."""
    parts = value.split("|")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part.strip()) for part in parts)
    except ValueError:
        return None


def _prefer_static(static: str, measured: str) -> str:
    """Return the offsets to display, keeping the RPU's own numbers where they
    still describe the picture.

    The RPU is exact and the measurement is not, so replacing 276 with 288 for
    the same framing only makes the display worse.  The static value therefore
    stands until the measurement clearly departs from it -- which is what an
    aspect ratio change does -- and takes over again once the film returns to
    its base framing.
    """
    if not measured:
        return static

    wanted = _parse(static)
    got = _parse(measured)
    coded = _coded_size()
    if wanted is None or got is None or coded is None:
        # No usable pair to compare (static is still "Fetching...", say): the
        # measurement is the only real information available.
        return measured

    coded_w, coded_h = coded
    per_column = _STATIC_MATCH_TOLERANCE * coded_w / _GRAB_W
    per_row = _STATIC_MATCH_TOLERANCE * coded_h / _GRAB_H
    tolerances = (per_column, per_column, per_row, per_row)

    same_framing = all(
        abs(a - b) <= tolerance
        for a, b, tolerance in zip(wanted, got, tolerances)
    )
    return static if same_framing else measured


def live_detection_pending() -> bool:
    """Return whether a measurement is expected for this stream but has not
    settled yet, so the caller can show a placeholder rather than a value.

    A pure state read: it neither grabs a frame nor keeps the sampler alive --
    resolve_l5_offsets() does both, and must be called first in a poll.
    """
    if not _enabled() or not _is_dolby_vision():
        return False
    with _lock:
        return bool(_path) and not _disabled and _settled_reading is None


def resolve_l5_offsets(static: str) -> str:
    """Return the offsets to display for the playing file.

    ``static`` is what the RPU reported (or dvinfo's placeholder / status
    label).  It is preferred; the live measurement only overrides it once the
    picture stops matching it.
    """
    return _prefer_static(static, live_l5_offsets())


def live_l5_offsets() -> str:
    """Return the measured active-area offsets for the playing file as
    ``left | right | top | bottom`` in coded pixels.

    Returns ``''`` whenever there is nothing confident to show -- detection off,
    stream is not Dolby Vision, nothing playing, the capture node gave up, or
    the sampler has not settled on a reading yet -- which is the caller's signal
    to show the static RPU value.

    Never blocks: the reading is whatever the sampler thread last settled on,
    and calling this is what keeps that thread alive.  Scaling to coded pixels
    happens here, so a resolution change is picked up on the next poll.
    """
    global _path, _last_request

    if not _enabled() or not _is_dolby_vision():
        return ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""
    if not path:
        return ""

    coded = _coded_size()
    if coded is None:
        return ""

    with _lock:
        if path != _path:
            _clear_locked()
            _path = path
        if _disabled:
            return ""
        _last_request = time.monotonic()
        reading = _settled_reading

    _ensure_sampler()

    return _format(reading, coded) if reading is not None else ""
