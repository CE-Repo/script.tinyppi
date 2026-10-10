# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Tagged logging into Kodi's log.

Every line starts with the add-on's tag, optionally followed by an area in
brackets, so the add-on's output is easy to filter:

    TinyPPI: mode 'dv' set via VS10 Actions -> Action(vs10.dv)
    TinyPPI [web]: dashboard listening on http://192.168.1.20:8099/

``log`` writes lines without an area; ``channel`` builds a module's ``_log``.
"""

from collections.abc import Callable

import xbmc

_TAG = "TinyPPI"

# Set True locally to log debug messages at INFO in a non-debug Kodi log.
FORCE_DEBUG = False


def _write(line: str, level: int) -> None:
    if level == xbmc.LOGDEBUG and FORCE_DEBUG:
        level = xbmc.LOGINFO
    xbmc.log(line, level)


def log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    """Write one line tagged with the add-on only."""
    _write(f"{_TAG}: {message}", level)


def channel(area: str, default: int = xbmc.LOGDEBUG) -> Callable[..., None]:

    """Return a log function that tags its lines with *area*.

    *default* is the level used when a call passes none.
    """
    prefix = f"{_TAG} [{area}]: "

    def write(message: str, level: int = default) -> None:
        _write(prefix + message, level)

    return write
