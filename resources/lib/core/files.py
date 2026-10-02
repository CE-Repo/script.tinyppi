# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Atomic file writes.

Set-top boxes are often switched off at the wall, which leaves a file that
was being rewritten truncated.  For a cache entry that is harmless; for the
skin's Font.xml it breaks the whole skin.  So nothing is rewritten in place:
the new content goes to a temporary file next to the target, is flushed to
storage, and then renamed over the target in one step.
"""

import os
import stat
import threading


def temp_path(path: str) -> str:
    """Return the temporary name a new version of *path* is written under.

    Unique per process and thread, and ending in ``.tmp`` so a leftover file
    is recognisable.
    """
    return f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"


def atomic_write(path: str, data: bytes) -> None:
    """Replace *path* with *data* in one step.

    An existing file keeps its permission bits.  Raises ``OSError`` on
    failure, leaving *path* unchanged and no temporary file behind.
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
            pass  # no existing file, or its mode cannot be copied
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
