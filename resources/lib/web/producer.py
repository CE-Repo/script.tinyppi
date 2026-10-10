# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The snapshot producer.

One thread builds the snapshot every open dashboard receives, so five tabs
cost the same as one.
"""

import threading
import time

import xbmc
from core import settings
from core.log import channel
from web import library
from web.snapshot import SnapshotBuilder

# Rebuild interval while a page watches: smooth for the L1 chart, cheaper
# than the overlay's 100 ms.
PRODUCE_INTERVAL = 0.2

# Interval while no page watches: only the session history (sampled once a
# second, see SessionLog) and the end of playback are tracked.
_IDLE_INTERVAL = 1.0

# How long /api/state waits for a fresh snapshot when no stream is open.
_FRESH_TIMEOUT = 1.0


_log = channel("web", xbmc.LOGINFO)


class Producer(threading.Thread):
    """Build snapshots while a page watches and wake the waiting streams.

    Without watchers only the session history is kept up.
    """

    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__(name="TinyPPI-web-producer", daemon=True)
        # Not ``_stop``: that would shadow a Thread internal and break join().
        self._stopping  = stop_event
        self._builder   = SnapshotBuilder()
        self._condition = threading.Condition()
        self._snapshot: dict = {"seq": 0, "playing": False, "groups": [],
                                "metrics": {}, "library": 0}
        self._failed    = False
        # Open streams and pending fresh() requests; either makes a pass
        # build a snapshot.
        self._watchers  = 0
        self._requested = False
        # Ends the wait between passes early (new page, shutdown).
        self._nudge     = threading.Event()

    def wake(self) -> None:
        """Release all waiting streams (used on shutdown)."""
        self._nudge.set()
        with self._condition:
            self._condition.notify_all()

    def watch(self) -> int:
        """Register a stream and return the sequence number to wait past.

        So its first frame is a full snapshot built after it arrived.
        """
        with self._condition:
            self._watchers += 1
            seen = self._snapshot.get("seq", 0)
        self._nudge.set()
        return seen

    def unwatch(self) -> None:
        """Unregister an ended stream."""
        with self._condition:
            self._watchers = max(0, self._watchers - 1)

    def fresh(self) -> dict:
        """Return a current snapshot for a request outside any stream.

        With a stream open the held one is at most a pass old; otherwise a
        new one is requested and awaited briefly, falling back to the last.
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
        """Return the playing title's chart samples and events.

        Called from the request thread; the session has its own lock.
        """
        return self._builder.session.history()

    def wait_for(self, seen: int, timeout: float) -> dict | None:
        """Wait for a snapshot newer than *seen*; None on timeout or stop.

        The stop flag is checked under the lock before every wait, so a
        stream arriving just after stop() leaves at once instead of sleeping
        through the heartbeat interval (which used to delay shutdown).
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
                    # Deferred library drops still fall due.
                    library.revision()
            except Exception as exc:  # one bad pass must not end the loop
                self._log_failure(exc)
            else:
                self._log_recovery()
            self._nudge.wait(PRODUCE_INTERVAL if wanted else _IDLE_INTERVAL)
        with self._condition:
            self._condition.notify_all()

    def _publish(self) -> None:
        """Build a full snapshot and wake every waiting stream."""
        addon = settings.addon()
        snapshot = self._builder.build(
            allow_filename=addon.getSetting("filename") == "true",
            metadata=addon.getSetting("web_metadata") == "true",
            control=addon.getSetting("web_allow_control") == "true",
        )
        if snapshot is None:  # only built without detail, never here
            return
        # The library revision rides along so open pages learn about changes
        # (e.g. a film now watched).  Reading it also runs deferred drops; this
        # thread is the add-on's clock (see ``library.revision``).
        snapshot["library"] = library.revision()
        with self._condition:
            self._snapshot  = snapshot
            self._requested = False
            self._condition.notify_all()

    def _log_failure(self, exc: Exception) -> None:
        """Log a failed pass once until it recovers."""
        if self._failed:
            return
        self._failed = True
        _log(f"snapshot failed, continuing with the last one: {exc}",
             xbmc.LOGWARNING)

    def _log_recovery(self) -> None:
        """Log recovery after a failure and re-arm the failure log."""
        if not self._failed:
            return
        self._failed = False
        _log("snapshot recovered")
