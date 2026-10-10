# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing title's history for the dashboard: samples, events, counters."""

import threading
import time


class SessionLog:
    """History of the playing title: chart samples, events and counters.

    Kept by the producer, so a page opened mid-film gets the full chart.
    Reset for a new title.  Written by the producer and read by request
    threads, so all access goes through the lock.
    """

    #: Seconds between chart samples (enough for an hour-wide chart).
    SAMPLE_INTERVAL = 1.0
    #: One hour of samples; longer films keep the last hour.
    MAX_SAMPLES = 3600
    #: Maximum events kept; the oldest are dropped.
    MAX_EVENTS = 60

    #: How long a track reading must be stable before it counts.  Index
    #: (JSON-RPC) and label (InfoLabels) may update in different ticks; the
    #: event keeps the time the change was first seen.
    TRACK_SETTLE = 1.5

    TEMP_HIGH   = 75.0
    CPU_FULL    = 100.0
    SWITCH_KINDS = frozenset(("vs10", "mode", "audio", "subtitle"))
    WARNING_KINDS = frozenset(("temperature", "cpu"))
    #: How long a finished title's figures are kept after playback stops.
    RETAIN_SECONDS = 600.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset("")

    def reset(self, key: str, title: str = "") -> None:
        """Start a new session for *key* (title and source)."""
        self._key       = key
        self._title     = title
        self._position  = ""
        self._ended     = 0.0
        self._started   = time.monotonic()
        self._samples: list[tuple] = []
        self._events:  list[dict]  = []
        self._seq       = 0
        self._sampled   = 0.0
        self._switches  = 0
        self._warnings  = 0
        # (identity, display label) per watched reading.
        self._watched: dict[str, tuple[str, str]] = {}
        # Changed but not yet settled readings (see _settle).
        self._pending: dict[str, tuple] = {}
        self._temperature_hot = False
        self._cpu_full = False
        self._fps: int | None = None

    # --- Writing -----------------------------------------------------------

    def end(self) -> None:
        """Mark the session as ended after playback stopped.

        The figures stay for ``RETAIN_SECONDS`` (or until the next title)
        for the idle page.  Cheap to call on every idle pass.
        """
        with self._lock:
            if not (self._key or self._samples or self._events):
                return
            if not self._ended:
                self._ended = time.monotonic()
                return
            if time.monotonic() - self._ended >= self.RETAIN_SECONDS:
                self.reset("")

    def observe(self, title: str, source: str, metrics: dict, watched: dict,
                position: str) -> None:
        """Add one pass to the session; chart samples use their own interval.

        Sessions are told apart by title and *source* (the file), since titles
        repeat and lengths of live streams grow.
        """
        with self._lock:
            key = f"{title}\n{source}"
            if self._ended or self._is_another_title(title, source, key):
                self.reset(key, title)
            self._position = position
            now = time.monotonic()
            self._note_changes(watched, now, position)
            self._watch_levels(metrics, now, position)
            if now - self._sampled < self.SAMPLE_INTERVAL:
                return
            self._sampled = now
            self._sample(metrics, now)

    def _is_another_title(self, title: str, source: str, key: str) -> bool:
        """Return whether this pass belongs to a different title.

        A half-empty reading is a player winding down, not a new title, so
        the finished title's figures are kept (see ``last``).  Without a
        source, a changed title is enough.
        """
        if not self._key:
            return True            # nothing is being tracked yet
        if key == self._key:
            return False
        if title and source:
            return True            # a whole reading, and a different one
        return bool(title) and title != self._title

    def _note_changes(self, watched: dict, now: float, position: str) -> None:
        """Record events for readings that changed since the last pass.

        Runs on every producer pass (short switches would be missed on the
        sample clock).  The first pass only records the initial values.
        """
        for name, value in watched.items():
            at, at_position = now, position
            if isinstance(value, dict):
                # Two-part reading: wait until settled (see _settle), dated
                # from the first change.
                identity = str(value.get("id") or "").strip()
                label = str(value.get("label") or identity).strip()
                if not identity:
                    continue
                settled = self._settle(name, (identity, label), now, position)
                if settled is None:
                    continue
                at, at_position = settled
            else:
                identity = str(value or "").strip()
                label = identity
                if not identity:
                    continue
            previous = self._watched.get(name)
            self._watched[name] = (identity, label)
            if previous is None or previous[0] == identity:
                continue
            self._add_event(at, at_position, name,
                            {"from": previous[1], "to": label})

    def _settle(self, name: str, current: tuple[str, str], now: float,
                position: str) -> tuple[float, str] | None:
        """Hold a two-part reading back until stable for ``TRACK_SETTLE``.

        Returns the time and position of the first change once settled, else
        None.  Only settled values are committed, so ``from`` is always right.
        """
        if current == self._watched.get(name):
            self._pending.pop(name, None)
            return None
        pending = self._pending.get(name)
        if pending is None:
            self._pending[name] = (current, now, now, position)
            return None
        reading, since, first, first_position = pending
        if reading != current:
            # Changed again: restart the wait, keep the first change time.
            self._pending[name] = (current, now, first, first_position)
            return None
        if now - since < self.TRACK_SETTLE:
            return None
        del self._pending[name]
        return first, first_position

    def _watch_levels(self, metrics: dict, now: float, position: str) -> None:
        """Track warning levels and the frame rate on every pass."""
        temperature = metrics.get("cpu_temp")
        if temperature is not None:
            self._watch_temperature(temperature, now, position)
        cpu = metrics.get("cpu")
        if cpu is not None:
            self._watch_cpu(cpu, now, position)
        fps = metrics.get("fps_in")
        if fps is not None:
            self._watch_fps(fps, now, position)

    def _sample(self, metrics: dict, now: float) -> None:
        """Add one chart sample."""
        level = metrics.get("l1") or {}
        peak  = level.get("max")
        mean  = level.get("avg")
        self._samples.append((
            round(now - self._started, 1), peak, mean,
        ))
        if len(self._samples) > self.MAX_SAMPLES:
            del self._samples[:len(self._samples) - self.MAX_SAMPLES]

    def _watch_temperature(self, temperature: float, now: float,
                           position: str) -> None:
        hot = temperature >= self.TEMP_HIGH
        if hot and not self._temperature_hot:
            self._add_event(now, position, "temperature", {"value": temperature})
        self._temperature_hot = hot

    def _watch_cpu(self, cpu: float, now: float, position: str) -> None:
        full = cpu >= self.CPU_FULL
        if full and not self._cpu_full:
            self._add_event(now, position, "cpu", {"value": cpu})
        self._cpu_full = full

    def _watch_fps(self, fps: float, now: float, position: str) -> None:
        """Record an event when the input frame rate changes.

        The input rate, not the output (which drops with every lost frame).
        Recorded as a transition (see ``eventTrend`` in js/live-panels.js)
        but not counted as a switch: the display mode change is already
        counted.
        """
        try:
            rate = int(round(float(fps)))
        except (TypeError, ValueError):
            return
        if rate <= 0:
            # Not a real rate (not playing yet, or unsettled).
            return
        previous = self._fps
        self._fps = rate
        if previous is None or previous == rate:
            return
        self._add_event(now, position, "fps", {"from": previous, "to": rate})

    def _add_event(self, now: float, position: str, kind: str,
                   detail: dict) -> dict:
        """Add an event, update the counters, and return the event."""
        self._seq += 1
        # Counters change only here, so every event is counted.
        if kind in self.SWITCH_KINDS:
            self._switches += 1
        if kind in self.WARNING_KINDS:
            self._warnings += 1
        event = {
            "t": round(now - self._started, 1),
            "pos": position,
            "kind": kind,
            **detail,
        }
        self._events.append(event)
        if len(self._events) > self.MAX_EVENTS:
            del self._events[:len(self._events) - self.MAX_EVENTS]
        return event

    # --- Reading -----------------------------------------------------------

    def summary(self) -> dict:
        """Return the small per-snapshot summary: counters and event ``seq``.

        A changed ``seq`` tells the page to fetch the history again.
        """
        with self._lock:
            return {
                "seq":      self._seq,
                "switches": self._switches,
                "warnings": self._warnings,
            }

    def last(self) -> dict:
        """Return the finished title's summary for the idle page, or {}."""
        with self._lock:
            if not self._ended or not self._key:
                return {}
            ago = time.monotonic() - self._ended
            if ago >= self.RETAIN_SECONDS:
                return {}
            peaks = [sample[1] for sample in self._samples if sample[1] is not None]
            return {
                "title":    self._title,
                "position": self._position,
                "ago":      int(ago),
                "switches": self._switches,
                "warnings": self._warnings,
                "peak":     max(peaks) if peaks else None,
                "events":   len(self._events),
            }

    def history(self) -> dict:
        """Return the full chart and event list.

        One array per series (compact for 3600 samples); ``now`` is the
        session age, so the page needs no synchronised clock.
        """
        with self._lock:
            return {
                "now":    round(time.monotonic() - self._started, 1),
                "step":   self.SAMPLE_INTERVAL,
                "t":      [sample[0] for sample in self._samples],
                "max":    [sample[1] for sample in self._samples],
                "avg":    [sample[2] for sample in self._samples],
                "events": list(self._events),
                "seq":    self._seq,
                "switches": self._switches,
            }
