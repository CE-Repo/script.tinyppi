# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""One settings handle per interpreter, renewed only when the settings change.

Kodi gives every ``xbmcaddon.Addon()`` a copy of the settings of its own, and
loads it on the first read: the whole ``resources/settings.xml`` definition --
some 360 KB of XML, every setting with its control, constraints and
dependencies -- is parsed and built up, and the stored values are read over
it.  Code that had to see a change made in the settings dialog mid-session
used to build a fresh ``Addon()`` for every read to get it, and so paid that
load every time: five times a second in the dashboard's producer, four times a
second in the codec-logo splash, twice a second in the overlay's static pass.

The stored values live in one file, which Kodi rewrites whenever a setting
changes -- on leaving the settings dialog and on every ``setSetting()``.  So
the handle is kept, and replaced only when that file's stamp moves: one stat
per call instead of one load, and a change is still seen on the very next call.

A caller that derives something from the settings can compare the handle it
got last time against this one (``is not``) to learn whether they changed.
"""

import os
import threading

import xbmcaddon
import xbmcvfs

# Where Kodi keeps the values this add-on's settings are set to.
_VALUES_FILE = "special://profile/addon_data/script.tinyppi/settings.xml"

_lock   = threading.Lock()
_path   = ""
_handle = None
_stamp  = None


def _values_stamp() -> tuple | None:
    """The values file as it is on disk right now, or None while it does not
    exist (a profile that has never saved a setting)."""
    try:
        stat = os.stat(_path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def addon() -> xbmcaddon.Addon:
    """Return a handle whose settings are the ones in force right now.

    Raises what ``xbmcaddon.Addon()`` raises when a new handle has to be made;
    an update that briefly unregisters the add-on is the one time it does.
    """
    global _path, _handle, _stamp

    if not _path:
        _path = xbmcvfs.translatePath(_VALUES_FILE)
    stamp = _values_stamp()
    with _lock:
        if _handle is None or stamp != _stamp:
            _handle = xbmcaddon.Addon()
            _stamp  = stamp
        return _handle
