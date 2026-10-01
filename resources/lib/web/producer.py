# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The snapshot producer: one thread that builds what every open dashboard is
sent, so five open tabs cost what one costs -- the alternative, polling per
request, would run the whole side-data pass once per client per tick."""

import threading
import time

import xbmc

from core import settings
from core.log import channel
from web import library
from web.snapshot import SnapshotBuilder

# How often the producer rebuilds the snapshot.  Five a second is well inside
# what a browser can paint and keeps the L1 luminance chart moving with the
# picture; the overlay's own 100ms cadence would only spend it on the wire.
PRODUCE_INTERVAL = 0.2

# How often it runs while no page is watching.  Nothing is built for anyone
# then; the pass only keeps the playing title's history (see SessionLog, whose
# chart samples once a second and whose watched readings mostly move on the
# same one-second clock) and notices playback ending.  The dashboard used to
# rebuild the whole snapshot five times a second around the clock instead,
# with or without a phone to send it to.
_IDLE_INTERVAL = 1.0

# How long an /api/state request waits for a snapshot built for it, when no
# stream has kept one current.
_FRESH_TIMEOUT = 1.0


_log = channel("web", xbmc.LOGINFO)


class Producer(threading.Thread):
    """Builds the snapshot while a page is watching and wakes the streams
    waiting on it; keeps only the session going while none is."""

    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__(name="TinyPPI-web-producer", daemon=True)
        # Not ``_stop``: that name is one of Thread's own internals, and
        # shadowing it makes the thread impossible to join -- which is
        # exactly what the shutdown has to be able to do.
        self._stopping  = stop_event
        self._builder   = SnapshotBuilder()
        self._condition = threading.Condition()
        self._snapshot: dict = {"seq": 0, "playing": False, "groups": [],
                                "metrics": {}, "library": 0}
        self._failed    = False
        # Open streams, and whether a request asked for a snapshot of its own
        # (see fresh); either one is what makes a pass build one.
        self._watchers  = 0
        self._requested = False
        # Cuts the wait between passes short: a page arriving should not sit
        # out the rest of an idle second, nor a shutdown.
        self._nudge     = threading.Event()

    def wake(self) -> None:
        """Release every waiting stream at once, used on shutdown."""
        self._nudge.set()
        with self._condition:
            self._condition.notify_all()

    def watch(self) -> int:
        """Register a stream, and return the sequence number it should wait
        past: the first frame it sends is built after it arrived, at full
        detail, rather than whatever an idle second left behind."""
        with self._condition:
            self._watchers += 1
            seen = self._snapshot.get("seq", 0)
        self._nudge.set()
        return seen

    def unwatch(self) -> None:
        """Unregister a stream that has ended."""
        with self._condition:
            self._watchers = max(0, self._watchers - 1)

    def fresh(self) -> dict:
        """The snapshot as it is now, for a request outside any stream.

        While a stream is open the held one is at most a pass old.  With none
        open nothing has been built for a while, so one is asked for and
        waited on -- briefly: a producer that cannot deliver in time still
        answers with the last one it built.
        """
        with self._condition:
            if self._watchers:
                return self._snapshot
            seen = self._snapshot.get("seq", 0)
            self._requested = True
        self._nudge.set()
        return self.wait_for(seen, _FRESH_TIMEOUT) or self.snapshot

    @property
    def snapshot(self) -> dict:
        with self._condition:
            return self._snapshot

    def history(self) -> dict:
        """The playing title's chart samples and events.

        Reached straight from the request thread: the session keeps a lock of
        its own, which is cheaper than holding up the producer for a list that
        is only asked for when a page opens or an event lands.
        """
        return self._builder.session.history()

    def wait_for(self, seen: int, timeout: float) -> dict | None:
        """Block until a snapshot newer than ``seen`` exists, or the timeout
        runs out (then None, and the caller sends a heartbeat).

        The stop flag is read inside the lock and before every wait, so a
        stream that arrives here just after stop() has notified the condition
        leaves at once instead of sleeping out the heartbeat interval.  That
        race is what used to leave threads running fifteen seconds into a
        shutdown Kodi allows five for.
        """
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._snapshot.get("seq", 0) > seen:
                    return self._snapshot
                if self._stopping.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def run(self) -> None:
        monitor = xbmc.Monitor()
        while not self._stopping.is_set() and not monitor.abortRequested():
            self._nudge.clear()
            with self._condition:
                wanted = bool(self._watchers or self._requested)
            try:
                if wanted:
                    self._publish()
                else:
                    self._builder.build(detail=False)
                    # The deferred drops still fall due while nobody watches.
                    library.revision()
            except Exception as exc:  # never let one bad pass end the stream
                self._log_failure(exc)
            else:
                self._log_recovery()
            self._nudge.wait(PRODUCE_INTERVAL if wanted else _IDLE_INTERVAL)
        with self._condition:
            self._condition.notify_all()

    def _publish(self) -> None:
        """Build a full snapshot and hand it to every stream waiting on one."""
        addon = settings.addon()
        snapshot = self._builder.build(
            allow_filename=addon.getSetting("filename") == "true",
            metadata=addon.getSetting("web_metadata") == "true",
            control=addon.getSetting("web_allow_control") == "true",
        )
        # Which version of the two shelves a client asking now would be handed.
        # It rides out with every snapshot because that is the one thing
        # already going to every screen in the house: a page that drew a film
        # as unwatched an hour ago has no other way of hearing that it has
        # since been watched, and reloading the page is not an answer.  Reading
        # it here also runs whatever deferred drop the last stop asked for --
        # this thread is the clock the add-on does not otherwise have (see
        # ``library.revision``).
        snapshot["library"] = library.revision()
        with self._condition:
            self._snapshot  = snapshot
            self._requested = False
            self._condition.notify_all()

    def _log_failure(self, exc: Exception) -> None:
        """Log a failed pass once, so a persistent fault leaves one line in
        the log rather than five a second."""
        if self._failed:
            return
        self._failed = True
        _log(f"snapshot failed, continuing with the last one: {exc}",
             xbmc.LOGWARNING)

    def _log_recovery(self) -> None:
        """Note the first good pass after a failed one, and arm the failure
        line again: a fault that clears and comes back later -- or a
        different one -- is worth a line of its own, not silence for the rest
        of the session."""
        if not self._failed:
            return
        self._failed = False
        _log("snapshot recovered")
