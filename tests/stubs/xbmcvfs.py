# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-in for Kodi's ``xbmcvfs`` module, on the local filesystem.

``special://`` paths map into a scratch folder (``TINYPPI_TEST_HOME``).
"""

import os
import tempfile

HOME = os.environ.get("TINYPPI_TEST_HOME") or os.path.join(tempfile.gettempdir(), "tinyppi-test-home")


def translatePath(path):
    if path.startswith("special://"):
        return os.path.join(HOME, path[len("special://"):])
    return path


def exists(path):
    return os.path.exists(translatePath(path))


class File:
    def __init__(self, path, mode="r"):
        self._handle = open(translatePath(path), "rb")

    def read(self):
        return self._handle.read().decode("utf-8", "replace")

    def readBytes(self, size=-1):
        return bytearray(self._handle.read(size if size and size > 0 else -1))

    def close(self):
        self._handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Stat:
    def __init__(self, path):
        self._stat = os.stat(translatePath(path))

    def st_size(self):
        return self._stat.st_size

    def st_mtime(self):
        return int(self._stat.st_mtime)
