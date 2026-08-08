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
falls back to the static RPU value.  Measuring happens on a sampler thread, so
nothing ever blocks the window; retries keep going for as long as the overlay
stays open, and a circuit breaker only stops them once the helper has failed
continuously for ten seconds, so a box without a working binary still pays for
that once and then nothing more, while a file that is merely slow to start gets
the time it needs.  Reopening the overlay clears the breaker and lets it try
again.

## What it costs, and when

Every query decodes a full intra keyframe of the coded picture, which on a UHD
remux is the most expensive frame in the GOP.  That is the whole cost of this
feature, and three things keep it in proportion:

* the helper decodes with a bounded number of threads, so a query cannot take
  the whole box for as long as it runs (see ``_PROBE_OPTIONS``);
* the cadence backs off once the framing has settled, which on the many films
  that never change framing is nearly all of the time;
* the sampler stops decoding as soon as the overlay stops reading, and keeps
  only the *open helper* warm after that, so reopening does not pay the
  container open again.

The one thing deliberately paid for up front is priming: the background service
starts the sampler at playback start, so the first launch of the overlay finds a
measurement rather than a placeholder.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import parse_offsets
from info import borderprobe

# How often to measure while the framing is still moving, and how often once it
# has stopped.  Every query decodes a full intra keyframe of the coded picture
# -- on a UHD remux the most expensive frame in the GOP -- so the sample rate is
# very nearly the whole cost of this feature, and the two cases want opposite
# things from it.
#
# While something is changing, a fast cadence is the point: an IMAX sequence
# opening up should reach the row and the badge quickly, and the delay before it
# does is this interval plus the up-to-one-GOP lag in measuring the keyframe at
# or before the current position plus however long the overlay takes to pick the
# reading up.
#
# Once the framing has held still for _SETTLE_AFTER readings in a row, though,
# the fast cadence buys nothing at all: the overwhelming majority of films never
# change framing, and re-measuring them twice a second only re-confirms a number
# that was already right.  Backing off to the slow cadence there is what takes
# this feature from costing a fifth of the box to costing a twentieth of it, and
# it costs only the worst-case delay in noticing the next change -- which is a
# transition that lasts minutes, spotted up to _SETTLE_INTERVAL later.
_SAMPLE_INTERVAL = 1.0
_SETTLE_INTERVAL = 3.0
_SETTLE_AFTER = 6

# The ceiling that does not depend on any of the above being right.
#
# The intervals are a guess about what a query costs, and a guess is a bad thing
# to have between a user's box and a decoder: the same query is milliseconds on
# a local file and seconds on a 4K remux over a busy share, and picking one
# number for both means picking a number that is wrong on one of them.  So the
# rate is not set by the interval alone.  Each query is timed, and the wait
# after it is stretched until the time spent measuring is at most this share of
# the time that has passed.
#
# With the helper capped at a single decoder thread (see _PROBE_OPTIONS), the
# wall time of a query is very nearly its CPU time, so this is a direct bound:
# the feature cannot cost more than about a seventh of one core, whatever the
# file, the network or the box.  A query that costs more simply happens less
# often -- a measurement every ten seconds still follows an IMAX transition,
# which lasts minutes, and it is what an expensive file can afford.
_MAX_DUTY = 0.15

# Report timings this often.  The first query is always reported, because the
# first one is the one that says whether this file is cheap or expensive, and
# what the answer is made of.
_STATS_EVERY = 25

# Stop measuring once nothing has read a value for this long: the sampler exists
# to serve the overlay, and the overlay closing is what should end the decoding.
_IDLE_TIMEOUT = 3.0

# ...but keep the helper process itself, and the measurement it has produced, for
# a good while longer.  Opening the container is far and away the slowest thing
# here -- seconds, on a large remux across the network, while libavformat pulls
# the index -- and closing the overlay for a moment and opening it again is the
# single most common thing a user does with it.  Paying the cold open every time
# is what made the row sit on its placeholder at every launch.
#
# Bounded rather than open-ended because a warm helper holds the decoder's
# picture buffers, which is roughly 190 MB on 4K HEVC (see _PROBE_OPTIONS in
# borderprobe.py).  A minute covers looking away and back; a film left running
# with the overlay closed gives the memory back.
_KEEPALIVE_TIMEOUT = 60.0

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

# Bumped every time the state is cleared.  A sampler carries the generation it
# was started for and checks it before writing anything, so a thread still
# winding down from the previous file cannot publish a measurement of that file
# as if it belonged to this one -- it holds no lock across a measurement, so
# without this the two overlap for exactly as long as one query takes.
_generation = 0

_SIDES_PATH_PROPERTY = "TinyPPI.Sides.Path"
_SIDES_PROPERTY = "TinyPPI.Sides.Min"

# (read at, value) for live_detection_enabled(); see there.  The initial stamp
# is -inf rather than 0 because time.monotonic() has no defined epoch: on a
# platform where it starts near zero, a 0 here would serve the placeholder False
# as though it had just been read.
_SETTING_TTL = 2.0
_setting_cache: tuple[float, bool] = (float("-inf"), False)


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _clear_locked() -> None:
    """Drop the sampling state; call under the lock."""
    global _measurement, _path, _pending_since, _failure_since, _disabled
    global _generation

    _measurement = None
    _path = ""
    _pending_since = None
    _failure_since = None
    _disabled = False
    _generation += 1

    window = xbmcgui.Window(10000)
    window.clearProperty(_SIDES_PATH_PROPERTY)
    window.clearProperty(_SIDES_PROPERTY)


def reset_live_detection() -> None:
    """Drop all detection state; called on playback stop and on a file change.

    The sampler thread is left to notice on its own: it stops as soon as
    nothing has asked for a value, and it closes the helper process on its way
    out.

    Not called when the overlay merely opens -- see retry_live_detection() for
    why that is a different thing.
    """
    with _lock:
        _clear_locked()


def retry_live_detection() -> None:
    """Give detection a fresh chance for the file that is already playing.

    Called every time the overlay opens.  What wants clearing there is the
    circuit breaker and the failure clock: a film that had detection give up --
    a helper that would not start, a stream it could not open -- should get
    another attempt rather than staying written off for the rest of playback,
    and the user opening the overlay again is as good a cue as any.

    What does *not* want clearing is the measurement and the helper process
    behind it.  This used to call reset_live_detection(), which threw both away
    on every launch and made each one pay the cold container open again -- the
    slowest part of the whole path, and the reason the row sat spinning at every
    launch.  A measurement of the file still playing is still true.
    """
    global _failure_since, _disabled, _pending_since

    with _lock:
        _failure_since = None
        if _disabled:
            _disabled = False
            # The breaker having tripped means the grace period ran out long
            # ago; restart it, or the retry we just allowed would have no
            # window in which to show its placeholder.
            _pending_since = time.monotonic()


def live_detection_enabled() -> bool:
    """Return whether live detection is switched on.

    A fresh ``Addon()`` avoids the cached settings, so toggling the option
    applies while the overlay stays open -- same trick as
    publish_channel_visibility.

    Constructing one is not free, though: it is a lookup in Kodi's addon manager
    plus a settings read, and this sits on a path the overlay walks several
    times a second through half a dozen callers.  The answer is therefore held
    for _SETTING_TTL, which is short enough that toggling the option still
    applies while the overlay stays open -- the point of the fresh Addon() --
    and long enough to turn some fifteen of those lookups a second into one.

    Updating the addon mid-playback unregisters our id for a moment, and this
    runs on the overlay's poll: treat that window as "off" rather than letting
    it take the polling loop down, the way it once took the splash down.
    """
    global _setting_cache

    now = time.monotonic()
    read_at, value = _setting_cache
    if now - read_at < _SETTING_TTL:
        return value

    try:
        value = xbmcaddon.Addon().getSetting("l5_live_detect") == "true"
    except (RuntimeError, TypeError):
        return False

    # One tuple assignment, so a reader either sees the old pair or the new one
    # and never a torn mix of the two; two threads refreshing at once just do
    # the same work twice, which is why this needs no lock of its own.
    _setting_cache = (now, value)
    return value


# --------------------------------------------------------------------------- #
# Sampler
# --------------------------------------------------------------------------- #

def _sampler(source: str, generation: int) -> None:
    """Measure *source* for as long as anything is interested in the answer.

    The helper process lives exactly as long as this thread does.  It is opened
    here rather than by the caller because opening it is the slow part -- on a
    file across the network it can take a second or two while libavformat pulls
    the index -- and the overlay's poll must never wait for that.

    Which is also why the thread outlives the overlay.  It stops *measuring*
    _IDLE_TIMEOUT after the last read, so a closed overlay decodes nothing, but
    it holds the open helper until _KEEPALIVE_TIMEOUT so that closing the
    overlay and opening it again resumes instantly instead of starting the whole
    container open over.

    *generation* is the state generation this thread was started for; a clear
    bumps it, and every write below checks it, so a thread still winding down
    from the previous file cannot publish into the new one's state.
    """
    global _thread, _measurement, _failure_since, _disabled

    monitor = xbmc.Monitor()
    probe = None
    unmeasurable = 0   # consecutive "nothing measurable" answers
    stable = 0         # consecutive readings that told us nothing new
    queries = 0        # completed measurements, for the timing report
    throttled = False  # whether the duty cycle has already been reported

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
                if _generation != generation or _disabled or _path != source:
                    return
                idle_for = time.monotonic() - _last_request

            if idle_for > _KEEPALIVE_TIMEOUT:
                return
            if idle_for > _IDLE_TIMEOUT:
                # Nobody is reading -- the overlay is closed.  Decode nothing,
                # but stay here holding the open helper, which is the whole
                # point of outliving the overlay.
                if monitor.waitForAbort(_SAMPLE_INTERVAL):
                    return
                continue

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

            before = (probe.reads_served, probe.bytes_served, probe.vfs_seconds)
            started = time.monotonic()
            try:
                bars = probe.measure(seconds)
            except borderprobe.BorderProbeError as exc:
                # A broken helper cannot recover on its own; drop it here so
                # the top of the loop opens a fresh one next time round. The
                # failure clock deliberately survives the restart: a helper
                # that dies on every measurement could otherwise be restarted
                # forever without ever reaching the timeout.
                elapsed = time.monotonic() - started
                probe.close()
                probe = None
                stable = 0   # nothing was confirmed, so keep retrying briskly
                with _lock:
                    if _generation != generation:
                        return
                    if _record_failure(exc):
                        return
            else:
                elapsed = time.monotonic() - started
                queries += 1
                if queries == 1 or queries % _STATS_EVERY == 0:
                    reads = probe.reads_served - before[0]
                    served = probe.bytes_served - before[1]
                    vfs = probe.vfs_seconds - before[2]
                    _log(
                        f"L5 live: query {queries} took {elapsed * 1000:.0f} ms, "
                        f"{vfs * 1000:.0f} ms of it serving {reads} reads "
                        f"({served / 1048576.0:.1f} MB) out of Kodi's VFS",
                        xbmc.LOGINFO,
                    )

                first = False
                changed = False
                with _lock:
                    if _generation != generation:
                        return
                    _failure_since = None
                    # None means the helper had nothing for this position -- a
                    # fade to black, a shot too dark to judge.  Hold the last
                    # confident value rather than flickering back to the static
                    # one.
                    if bars is not None:
                        first = _measurement is None
                        changed = bars != _measurement
                        _measurement = bars

                if bars is None:
                    unmeasurable += 1
                    # A picture that cannot be judged is not a picture that has
                    # changed.  Counting it as settled keeps a reel of dark
                    # scenes from holding the fast cadence for its whole length,
                    # measuring nothing at full price.
                    stable += 1
                    if unmeasurable == _UNMEASURABLE_REPORT_AFTER:
                        _log(f"L5 live: nothing measurable in the picture "
                             f"({probe.last_none_reason}) after {unmeasurable} "
                             "tries; holding the static value", xbmc.LOGINFO)
                else:
                    unmeasurable = 0
                    stable = 0 if changed else stable + 1
                    if first:
                        _log("L5 live: measured "
                             + " | ".join(str(v) for v in bars), xbmc.LOGINFO)

            # Fast while the framing is moving, slow once it has stopped; a
            # single changed reading puts it straight back on the fast cadence.
            settled = stable >= _SETTLE_AFTER
            wait = _SETTLE_INTERVAL if settled else _SAMPLE_INTERVAL

            # ...and then held to the duty cycle, which is what actually decides
            # the rate on a file where a query is expensive.  An interval is a
            # guess; this is measured.
            duty_wait = elapsed * (1.0 / _MAX_DUTY - 1.0)
            if duty_wait > wait:
                if not throttled:
                    throttled = True
                    _log(f"L5 live: a query costs {elapsed * 1000:.0f} ms here, "
                         f"so measuring every {duty_wait:.1f} s to stay within "
                         f"{_MAX_DUTY:.0%} of a core", xbmc.LOGINFO)
                wait = duty_wait

            if monitor.waitForAbort(wait):
                return
    finally:
        if probe is not None:
            probe.close()
        with _lock:
            # Only if it is still us: a later sampler may already have claimed
            # the slot, and clearing it then would let a third start alongside.
            if _thread is threading.current_thread():
                _thread = None


def _claim_locked(path: str) -> bool:
    """Adopt *path* as the file being measured and register interest in it.

    Registering interest is what keeps the sampler measuring: it stops when
    nothing has claimed a reading for _IDLE_TIMEOUT.  Returns False when
    detection has given up on this file, in which case there is nothing to wait
    for.  Call under the lock.
    """
    global _path, _pending_since, _last_request

    if path != _path:
        _clear_locked()
        _path = path
        _pending_since = time.monotonic()
    if _disabled:
        return False
    _last_request = time.monotonic()
    return True


def prime_live_detection() -> bool:
    """Start measuring the playing file before anything asks to see the result.

    Called from the background service at playback start, for the same reason
    hdrprobe is primed there: the slow part is opening the container, and doing
    it while the film gets going means the row has a real number in it the first
    time the overlay is opened, rather than a placeholder and a wait.

    Returns True when a sampler was started.  A no-op when detection is off,
    when nothing is playing, or when this file has already been measured.

    The sampler this starts is bound by the same idle rules as any other, so a
    film nobody ever opens the overlay on stops decoding after _IDLE_TIMEOUT and
    releases the helper after _KEEPALIVE_TIMEOUT.  Priming buys the first launch
    within that window; it does not leave anything running for the whole film.
    """
    if not live_detection_enabled():
        return False

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return False
    if not path:
        return False

    with _lock:
        if not _claim_locked(path):
            return False
        if _measurement is not None:
            return False

    _ensure_sampler(path)
    return True


def _ensure_sampler(source: str) -> None:
    """Start the sampler thread unless one is already running.

    Only ever one at a time: two would mean two helper processes, and a helper
    is not a cheap thing to hold in duplicate.  A sampler left over from the
    previous file therefore delays the new one until it notices it is stale,
    which it does at the top of its loop -- promptly when it is idling, and
    after at most one query when it is measuring.
    """
    global _thread

    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_sampler, args=(source, _generation), daemon=True)
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
    stored = window.getProperty(_SIDES_PATH_PROPERTY) == path
    if stored:
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

    # Only when it actually moves.  This runs on the overlay's fast refresh, and
    # on a settled film the answer is the same every time; a window property
    # write is not free on the skin side, which re-evaluates whatever is bound
    # to it.  The path is part of the test so a new file still records its own
    # value even when that value happens to match the previous file's.
    if not stored or side != known:
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
    if not live_detection_enabled():
        return ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""
    if not path:
        return ""

    with _lock:
        if not _claim_locked(path):
            return ""
        reading = _measurement

    _ensure_sampler(path)

    if reading is None:
        return ""
    return " | ".join(str(value) for value in reading)
