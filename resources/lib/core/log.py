# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""One way into Kodi's log.

Every line the add-on writes starts with the same tag, and a module with an
area of its own names it in brackets, so the add-on's whole output is found
with one search and narrowed down with a second:

    TinyPPI: mode 'dv' set via VS10 Actions -> Action(vs10.dv)
    TinyPPI [web]: dashboard listening on http://192.168.1.20:8099/

``log`` writes untagged lines; ``channel`` builds a module's own ``_log``.
"""

import xbmc

_TAG = "TinyPPI"

# Set True locally to promote debug messages to INFO in a non-debug Kodi log.
FORCE_DEBUG = False


def _write(line: str, level: int) -> None:
    if level == xbmc.LOGDEBUG and FORCE_DEBUG:
        level = xbmc.LOGINFO
    xbmc.log(line, level)


def log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    """Write one line, tagged with the add-on alone."""
    _write(f"{_TAG}: {message}", level)


def channel(area: str, default: int = xbmc.LOGDEBUG):
    """Return a log function whose lines name ``area`` and whose level, when a
    call gives none, is ``default``."""
    prefix = f"{_TAG} [{area}]: "

    def write(message: str, level: int = default) -> None:
        _write(prefix + message, level)

    return write
