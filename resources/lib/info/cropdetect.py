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
falls back to the static RPU value.  Grabs run inline on the overlay's
one-second poll; a circuit breaker stops trying for the rest of the file once
the node has failed repeatedly, so a box without working capture pays a handful
of failed opens and nothing more.
"""

import os
import struct
import threading

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

# Publish only after this many consecutive grabs agree to within the tolerance
# (in grab pixels).  Keeps the values still through cuts and dark shots.
_SAMPLE_WINDOW = 3
_EDGE_TOLERANCE = 2

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
_published = ""     # last value we were confident enough to show
_path = ""          # file the state above belongs to
_failures = 0
_disabled = False   # circuit breaker, cleared on the next file


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def reset_live_detection() -> None:
    """Drop all detection state; called on playback stop and on a file change."""
    global _published, _path, _failures, _disabled

    with _lock:
        _samples.clear()
        _published = ""
        _path = ""
        _failures = 0
        _disabled = False


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


def _measure(lit: bytes) -> tuple[int, int, int, int] | None:
    """Return ``(left, right, top, bottom)`` in grab pixels, or None when the
    frame carries no usable picture (fade to black, or too dark to trust)."""
    rows = [sum(lit[y * _GRAB_W:(y + 1) * _GRAB_W]) for y in range(_GRAB_H)]
    row_allowance = _GRAB_W // _LIT_ALLOWANCE
    if not any(count > row_allowance for count in rows):
        return None

    cols = [sum(lit[x::_GRAB_W]) for x in range(_GRAB_W)]
    col_allowance = _GRAB_H // _LIT_ALLOWANCE

    top = _leading_black(rows, row_allowance)
    bottom = _leading_black(reversed(rows), row_allowance)
    left = _leading_black(cols, col_allowance)
    right = _leading_black(reversed(cols), col_allowance)

    if (top + bottom > _GRAB_H * _MAX_BAR_FRACTION
            or left + right > _GRAB_W * _MAX_BAR_FRACTION):
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


def live_l5_offsets() -> tuple[str, str]:
    """Return ``(offsets, status)`` for the playing file.

    ``offsets`` is ``left | right | top | bottom`` in coded pixels, or ``''``
    when there is nothing confident to show yet.  ``status`` is:

    ``''``           detection off, stream is not Dolby Vision, nothing playing,
                     or the capture node gave up -- the caller shows the static
                     RPU value untouched.
    ``'computing'``  capture works, but no settled reading yet.
    ``'ready'``      ``offsets`` holds a measured value.

    Safe to call once per poll; one grab plus one scan of a 320x180 frame.
    """
    global _published, _path, _failures, _disabled

    if not _enabled() or not _is_dolby_vision():
        return "", ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return "", ""
    if not path:
        return "", ""

    coded = _coded_size()
    if coded is None:
        return "", ""

    with _lock:
        if path != _path:
            _samples.clear()
            _published = ""
            _path = path
            _failures = 0
            _disabled = False

        if _disabled:
            return "", ""

        frame = _grab()
        if frame is None:
            _failures += 1
            if _failures >= _FAILURE_LIMIT:
                _disabled = True
                _published = ""
                _log(f"L5 live: {_NODE} unusable, staying on the RPU value",
                     xbmc.LOGINFO)
                return "", ""
            return _published, _status()

        _failures = 0

        reading = _measure(_lit_map(frame))
        if reading is None:
            # Fade to black or a shot with no discernible edge: hold the last
            # confident value rather than flickering back to the static one.
            return _published, _status()

        _samples.append(reading)
        del _samples[:-_SAMPLE_WINDOW]

        settled = _settled()
        if settled is not None:
            _published = _format(settled, coded)

        return _published, _status()


def _status() -> str:
    """Return the status for the current state; call under the lock."""
    return "ready" if _published else "computing"
