"""Live black-bar detection from the decoded picture.

CoreELEC publishes Dolby Vision Level 5 offsets as live
``Player.Process(...)`` InfoLabels.  Non-zero L5 values are authoritative;
when all four are zero, this module derives the same numbers from the picture
via the **borderprobe** helper (info.borderprobe).  HDR10, HDR10+, HLG and SDR
keep the original Main behaviour and are measured directly.  The helper opens
the playing file, seeks to the current position, decodes a few frames and scans
their luma plane for black rows/columns.

This replaces an earlier approach reading ``/dev/amvideocap0`` (Hyperion's
Amlogic grabber): cheap, but Amlogic-only, so nothing about it could be
developed or tested off the box, and its 320x180 scaled grab quantised a
2160-line frame's bars to 12 coded lines, needing extra damping to stop the
number flickering.  borderprobe measures the coded frame at full resolution
and does its own median/hysteresis, so what's left here is TinyPPI's own part:
holding the side bars to the thinnest ever seen, and standing in the RPU's
numbers until a measurement lands -- at which point the measurement is shown
outright, since borderprobe's hysteresis already keeps it from twitching.

Everything here is best-effort: a missing binary, an unopenable file, or a
picture too dark to judge all yield ``''``, and properties.py falls back to
the static RPU value.  Measuring happens on a sampler thread so the window
never blocks; a circuit breaker stops retries once the helper has failed
continuously for ten seconds (reopening the overlay clears it).

Every query decodes a full intra keyframe -- on a UHD remux the most expensive
frame in the GOP -- which is the whole cost of this feature.  It's kept in
proportion by a bounded decoder-thread count (``_PROBE_OPTIONS``), a cadence
that backs off once the framing has settled, and the sampler stopping once the
overlay stops reading while keeping only the open helper warm.  The one cost
paid up front is priming: the background service starts the sampler at
playback start, so the first overlay launch finds a measurement rather than a
placeholder.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import clean, info, parse_offsets
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

_L5_LABELS = tuple(
    f"Player.Process(video.dovi.l5.{edge}.offset)"
    for edge in ("left", "right", "top", "bottom")
)
_DOVI_PROFILE_LABEL = "Player.Process(video.dovi.profile)"


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def live_measurement_required() -> bool:
    """Return whether borderprobe may measure the current video.

    HDR10, HDR10+, HLG and SDR keep the original Main behaviour and are always
    eligible.  For Dolby Vision, the new live CoreELEC L5 InfoLabels are
    authoritative; an empty offset is treated as zero, and borderprobe is used
    when all four effective offsets are zero.
    """
    if not clean(info(_DOVI_PROFILE_LABEL)).strip():
        return True

    values = []
    for label in _L5_LABELS:
        raw = clean(info(label)).strip() or "0"
        try:
            values.append(int(raw))
        except ValueError:
            return False
    return tuple(values) == (0, 0, 0, 0)


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

    The sampler thread is left to notice on its own -- it stops once nothing
    has asked for a value, closing the helper on its way out.  Not called when
    the overlay merely opens; see retry_live_detection() for why that differs.
    """
    with _lock:
        _clear_locked()


def stop_live_detection() -> None:
    """Stop and forget a measurement superseded by live Dolby Vision L5."""
    with _lock:
        if not _path and _measurement is None:
            return
        _clear_locked()


def retry_live_detection() -> None:
    """Give detection a fresh chance for the file that is already playing.

    Called every time the overlay opens.  Clears the circuit breaker and
    failure clock, so a film detection had given up on gets another attempt,
    but deliberately keeps the measurement and helper process: those still
    describe the file still playing.  This used to call
    reset_live_detection(), which threw both away and made every launch pay
    the cold container open again.
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

    A fresh ``Addon()`` avoids cached settings, so toggling the option applies
    live (same trick as publish_channel_visibility) -- but constructing one
    costs a lookup plus a settings read, and this sits on a path walked several
    times a second by half a dozen callers.  The answer is cached for
    _SETTING_TTL: short enough to still apply live, long enough to turn ~15
    lookups a second into one.  Updating the addon mid-playback briefly
    unregisters our id; treat that window as "off" rather than crashing the
    polling loop, the way it once took the splash down.
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

    The helper process lives exactly as long as this thread does; it's opened
    here rather than by the caller because opening it is the slow part (a
    second or two on a networked file), and the overlay's poll must never wait
    for that.  The thread also outlives the overlay for the same reason: it
    stops *measuring* _IDLE_TIMEOUT after the last read, but holds the open
    helper until _KEEPALIVE_TIMEOUT so reopening the overlay resumes instantly.

    *generation* is the state generation this thread was started for; a clear
    bumps it, and every write below checks it, so a thread winding down from
    the previous file cannot publish into the new one's state.
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

            # Re-read the live DV L5 labels on every pass.  A scene-level L5
            # update must replace a borderprobe fallback without waiting for
            # the overlay's next property refresh.
            if not live_detection_enabled() or not live_measurement_required():
                with _lock:
                    if _generation == generation:
                        _clear_locked()
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
                             + " l ".join(str(v) for v in bars), xbmc.LOGINFO)

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

    Registering interest keeps the sampler measuring: it stops when nothing has
    claimed a reading for _IDLE_TIMEOUT.  Returns False when detection has
    given up on this file.  Call under the lock.
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
    hdrprobe is primed there: opening the container is the slow part, so doing
    it while the film gets going means the row has a real number the first time
    the overlay opens.  Returns True when a sampler was started; a no-op when
    detection is off, nothing is playing, or this file is already measured.
    The sampler is bound by the usual idle rules, so it doesn't leave anything
    running for a film whose overlay is never opened.
    """
    if not live_detection_enabled() or not live_measurement_required():
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

    Only ever one at a time, since a helper process isn't cheap to hold in
    duplicate.  A sampler left over from the previous file delays the new one
    until it notices it's stale at the top of its loop -- promptly when idling,
    after at most one query when measuring.
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

    Side bars don't come and go, unlike the top/bottom bars an IMAX sequence
    genuinely moves.  borderprobe already refuses to report a bar only one side
    supports (what a dark edge looks like), but a scene dark down *both* edges
    defeats that test -- only time tells those apart.  A dark edge can only add
    apparent bar, never remove a real one, so the thinnest value seen is
    trustworthy and this only ever shrinks.  Starts from the RPU's own value,
    settling the common case on the first poll.  Kept on the home window so it
    survives the overlay closing, like the rest of the per-file state.
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
        if declared is not None and any(declared):
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

    return " l ".join(str(value) for value in (side, side, bars[2], bars[3]))


def live_measurement_available() -> bool:
    """Return whether a measurement exists for the playing file.

    Lets a caller tell "the picture has no bars" from "nobody has looked" --
    both read as ``0 l 0 l 0 l 0``, and acting on the second would mark a whole
    film as IMAX on a value nothing ever measured.  Tied to the playing file,
    since live_l5_offsets() only clears the reading on a file change and
    returns early when detection is off.  A pure state read: it neither
    measures nor keeps the sampler alive.
    """
    if not live_measurement_required():
        return False

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
    if not live_detection_enabled() or not live_measurement_required():
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

    ``static`` is what the RPU reported (or dvinfo's placeholder/status label).
    The measurement wins whenever there is one, since it describes the picture
    actually on screen; ``static`` stands in only until the first measurement
    lands, or when detection is off or has given up.  Sides are pinned first by
    _hold_sides -- see there for why they're held differently from top/bottom.
    """
    measured = _hold_sides(static, live_l5_offsets())
    return measured or static


def live_l5_offsets() -> str:
    """Return the measured active-area offsets for the playing file as
    ``left l right l top l bottom`` in coded pixels.

    Returns ``''`` whenever there is nothing confident to show -- detection off,
    nothing playing, the helper gave up, or no measurement has arrived yet --
    which is the caller's signal to show the static RPU value.

    Never blocks: the reading is whatever the sampler thread last measured, and
    calling this is what keeps that thread alive.
    """
    if not live_detection_enabled():
        return ""
    if not live_measurement_required():
        stop_live_detection()
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
    return " l ".join(str(value) for value in reading)
