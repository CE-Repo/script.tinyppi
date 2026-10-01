# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's own files: which routes name them, and the cache that
serves them."""

import gzip
import os
import threading

from core import settings

# What a browser may keep, and for how long.
#
# The static files are the add-on's own and change only when it is updated, so
# they are sent with a validator rather than an age: the browser asks whether
# its copy is still good and is answered with an empty 304, which over a
# kept-alive connection is a few dozen bytes instead of the whole page.  An age
# would be faster still and would leave a phone holding yesterday's dashboard
# after an update.
STATIC_CACHE = "no-cache"

# Bodies worth compressing, and the size below which it is not worth the CPU.
# Only text: the icons are already small and the JPEGs are already compressed.
_COMPRESSIBLE = ("text/", "application/manifest+json", "application/json",
                 "image/svg+xml")
MIN_COMPRESS = 600

# The folders of resources/web whose files are served under their own names,
# and the type each kind of file goes out as.  A file of any other kind, a
# hidden one or one in a folder below these is not served at all.
_SERVED_FOLDERS = ("css", "js", "icons")
_SERVED_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js":  "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
_HTML = "text/html; charset=utf-8"


def _addon_root() -> str:
    return settings.addon().getAddonInfo("path")


def routes() -> dict[str, tuple[str, str]]:
    """Route -> (absolute path, content type).

    Built once per server so a request can never name a file of its own: an
    unknown route is a 404, not a lookup.  The table is still a fixed one --
    it is only written out by listing the add-on's own folders when the
    server starts rather than by hand, so a new icon or stylesheet is served
    the moment it ships instead of answering 404 until somebody remembers the
    line it needed here.
    """
    root = _addon_root()
    web = os.path.join(root, "resources", "web")
    index = (os.path.join(web, "index.html"), _HTML)
    table = {
        "/":                     index,
        "/index.html":           index,
        # The Dolby Vision metadata list, once a window of its own and now a
        # tab of the dashboard.  The old address is the same page, which
        # opens on that tab (see tabFromAddress in js/dashboard.js), so a
        # bookmark of either spelling still lands on the list.
        "/metadata":             index,
        "/metadata.html":        index,
        "/manifest.webmanifest": (os.path.join(web, "manifest.webmanifest"),
                                  "application/manifest+json"),
        "/icon.png":             (os.path.join(root, "icon.png"), "image/png"),
        "/fanart.png":           (os.path.join(root, "fanart.png"), "image/png"),
    }
    for folder in _SERVED_FOLDERS:
        directory = os.path.join(web, folder)
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            content_type = _SERVED_TYPES.get(os.path.splitext(name)[1].lower())
            path = os.path.join(directory, name)
            if content_type is None or name.startswith(".") or not os.path.isfile(path):
                continue
            table[f"/{folder}/{name}"] = (path, content_type)
    return table


class StaticFiles:
    """The route table's files, read and compressed once.

    A page opening asks for a dozen of them at once, and every one of those
    reads would otherwise come off the box's own flash while the browser waits.
    Each file is read on its first request and kept with its compressed twin
    and a validator; the size and modification time are checked on every
    request, so a file replaced under a running server is picked up rather than
    served from yesterday.

    Shared by every request thread, hence the lock -- held only around the
    dictionary, never around a read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[tuple, tuple]] = {}

    def get(self, path: str, content_type: str) -> tuple | None:
        """``(body, gzipped_or_None, etag)`` for a file, or None when it is
        gone."""
        try:
            stat = os.stat(path)
        except OSError:
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)

        with self._lock:
            held = self._files.get(path)
        if held is not None and held[0] == stamp:
            return held[1]

        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            return None

        packed = None
        if len(body) >= MIN_COMPRESS and content_type.startswith(_COMPRESSIBLE):
            packed = gzip.compress(body, 6)
            # A file that grows under compression is sent as it is.
            if len(packed) >= len(body):
                packed = None
        # The modification time and the size: the files are the add-on's, and
        # an update rewrites every one of them.
        entry = (body, packed, f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"')

        with self._lock:
            self._files[path] = (stamp, entry)
        return entry
