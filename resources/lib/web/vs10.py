# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 modes offered on the dashboard and the switches it requests."""

import threading

import xbmc
from core.log import channel
from core.utils import info

# Modes per source type, as in the on-screen dialog (see ui.dialog_layout).
# Format names are not translated, like in the dialog.
_VS10_OPTIONS = {
    "sdr": (
        ("original_sdr", "Original"),
        ("hdr10",        "SDR → HDR10"),
        ("dv",           "SDR → Dolby Vision"),
    ),
    "hdr10": (
        ("original_hdr", "HDR10 (Original)"),
        ("sdr8",         "HDR10 → SDR"),
        ("dv",           "HDR10 → Dolby Vision"),
    ),
    "dolby vision": (
        ("original_dv",  "Dolby Vision (Original)"),
        ("sdr8",         "Dolby Vision → SDR"),
    ),
}


def _is_hdr10_plus(key: str) -> bool:
    """Return whether the source token is HDR10+ (either spelling)."""
    return "hdr10plus" in key or "hdr10+" in key


def _has_no_modes(key: str, hdr10plus: bool = False) -> bool:
    """Return whether the source has no VS10 modes.

    HDR10+ and HLG are no VS10 inputs; *hdr10plus* covers DV + HDR10+
    hybrids (from ``TinyPPI.Hdr10PlusPresent``), which read as DV.
    """
    return hdr10plus or _is_hdr10_plus(key) or "hlg" in key


def _options_for(source: str, playing: bool = True,
                 hdr10plus: bool = False) -> tuple:
    """Return the mode buttons for *source*.

    None for sources without modes (see ``_has_no_modes``) or when nothing
    plays; the page then hides the VS10 card.  An empty source is SDR.
    """
    if not playing:
        return ()
    key = (source or "").strip().lower()
    if _has_no_modes(key, hdr10plus):
        return ()
    if "dolby" in key:
        return _VS10_OPTIONS["dolby vision"]
    if "hdr10" in key:
        return _VS10_OPTIONS["hdr10"]
    return _VS10_OPTIONS["sdr"]


def vs10_state(source: str, playing: bool = True,
               hdr10plus: bool = False) -> dict:
    """Return the VS10 buttons for the source and the current output."""
    return {
        "options": [{"mode": mode, "label": label}
                    for mode, label in _options_for(source, playing, hdr10plus)],
        "output":  info("Player.Process(amlogic.eoft_gamut)").split(",")[0].strip(),
    }


# Modes the dashboard accepts: exactly the buttons above.
_KNOWN_MODES = frozenset(
    mode for options in _VS10_OPTIONS.values() for mode, _ in options
)


_log = channel("web")


class _ModeSwitcher:
    """Apply VS10 modes one at a time, the latest request winning.

    A switch takes seconds (display resets, sometimes a stage through SDR).
    Requests arriving meanwhile replace each other, so quick taps on three
    buttons end in the last mode instead of three switches in a row.  Runs
    on a service thread (no ``RunScript``), so the request is not held
    during the driver's settling delays.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # The mode to apply next, and whether a worker is applying modes.
        self._wanted: str | None = None
        self._running = False

    def request(self, mode: str) -> None:
        """Queue *mode*, replacing any mode still waiting."""
        with self._lock:
            if self._wanted is not None:
                _log(f"VS10 mode '{self._wanted}' replaced by '{mode}' "
                     "before it started", xbmc.LOGDEBUG)
            self._wanted = mode
            if self._running:
                return
            self._running = True
        try:
            threading.Thread(target=self._work, name="TinyPPI-vs10",
                             daemon=True).start()
        except RuntimeError as exc:
            with self._lock:
                self._running = False
                self._wanted = None
            _log(f"VS10 mode '{mode}' could not be started: {exc}",
                 xbmc.LOGERROR)

    def _next(self, monitor: xbmc.Monitor) -> str | None:
        """Take the waiting mode, or end the worker (None)."""
        with self._lock:
            mode = self._wanted
            self._wanted = None
            # No new switch during shutdown (it would delay Kodi).
            if mode is None or monitor.abortRequested():
                self._running = False
                return None
            return mode

    def _work(self) -> None:
        monitor = xbmc.Monitor()
        while (mode := self._next(monitor)) is not None:
            try:
                from core.vs10 import set_mode
                set_mode(mode)
            except Exception as exc:  # a switch must not break the service
                _log(f"VS10 mode '{mode}' failed: {exc}", xbmc.LOGERROR)


_switcher = _ModeSwitcher()


def apply_mode(mode: str) -> bool:
    """Start switching to VS10 *mode*; False for modes not offered."""
    if mode not in _KNOWN_MODES:
        return False
    _switcher.request(mode)
    return True
