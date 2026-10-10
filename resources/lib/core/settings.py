# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""One cached settings handle per interpreter.

Each ``xbmcaddon.Addon()`` loads its own copy of the settings on first read,
which parses the whole ~100 KB ``resources/settings.xml``.  Creating a fresh
handle for every read (to see changes made mid-session) cost that load
several times a second in the dashboard, the splash and the overlay.

Kodi rewrites the stored values file whenever a setting changes, so the
handle is kept and only replaced when that file's stamp changes: one stat per
call instead of one load, and changes are still seen on the next call.

Callers can compare the returned handle with the previous one (``is not``) to
detect a settings change.
"""

import os
import threading

import xbmcaddon
import xbmcvfs
from core.constants import PROFILE_DIR

# The file holding this add-on's stored setting values.
_VALUES_FILE = f"{PROFILE_DIR}/settings.xml"


class _Handle:
    """The settings handle and the stamp of the values file it was read at."""

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._path   = ""
        self._handle: xbmcaddon.Addon | None = None
        self._stamp: tuple | None = None

    def _values_stamp(self) -> tuple | None:
        """Return the values file's stamp, or None while it does not exist."""
        try:
            stat = os.stat(self._path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def get(self) -> xbmcaddon.Addon:
        if not self._path:
            self._path = xbmcvfs.translatePath(_VALUES_FILE)
        stamp = self._values_stamp()
        with self._lock:
            if self._handle is None or stamp != self._stamp:
                self._handle = xbmcaddon.Addon()
                self._stamp  = stamp
            return self._handle


_current = _Handle()


def addon() -> xbmcaddon.Addon:
    """Return a handle with the settings currently in force.

    Raises what ``xbmcaddon.Addon()`` raises when a new handle is needed,
    e.g. while an update briefly unregisters the add-on.
    """
    return _current.get()
