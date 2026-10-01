# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Writing a file so that nobody ever reads half of it.

A set-top box is switched off at the wall as often as it is shut down, and a
file being rewritten when that happens is left truncated.  For most of what
the add-on writes that only costs a cache entry; for the skin's Font.xml it
costs the whole skin, which then no longer loads at all.  So nothing is
rewritten in place: the new content goes into a file of its own beside the
target, is flushed to the storage, and only then takes the target's name --
a rename the file system carries out whole or not at all.
"""

import os
import stat
import threading


def temp_path(path: str) -> str:
    """The name a new version of ``path`` is written under before it replaces
    it: unique per process and thread, so two writers never share one, and
    ending in ``.tmp`` so a leftover one is recognisable as such."""
    return f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"


def atomic_write(path: str, data: bytes) -> None:
    """Replace ``path`` with ``data`` in one step.

    A file that already exists keeps its permission bits; a new one is created
    the way ``open`` would create it.  Raises ``OSError`` when the write fails,
    leaving ``path`` exactly as it was and no temporary file behind.
    """
    tmp = temp_path(path)
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass  # no file to take them from, or none that may be changed
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
