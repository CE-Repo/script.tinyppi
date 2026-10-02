# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's static files: the route table and a file cache."""

import gzip
import os
import threading

from core import settings

# Static files carry a validator rather than a max-age: revalidation costs an
# empty 304, and an update is never hidden behind a cached copy.
STATIC_CACHE = "no-cache"

# Compressible types (text only) and the minimum size worth compressing.
_COMPRESSIBLE = ("text/", "application/manifest+json", "application/json",
                 "image/svg+xml")
MIN_COMPRESS = 600

# Folders of resources/web served by file name, and the served types.  Other
# types, hidden files and subfolders are never served.
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
    """Return the route table: route -> (absolute path, content type).

    Built once per server from the add-on's own folders, so a request can
    never name a file itself (unknown routes are 404), and new files are
    served without editing a list.
    """
    root = _addon_root()
    web = os.path.join(root, "resources", "web")
    index = (os.path.join(web, "index.html"), _HTML)
    table = {
        "/":                     index,
        "/index.html":           index,
        # Old address of the metadata page, now a tab of the same page (see
        # tabFromAddress in js/dashboard.js); kept for bookmarks.
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
    """Cache of the static files, read and compressed once.

    Each file is kept with its gzip version and a validator; size and mtime
    are checked on every request, so replaced files are picked up.  The
    lock guards only the dict, never a read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[tuple, tuple]] = {}

    def get(self, path: str, content_type: str) -> tuple | None:
        """Return ``(body, gzipped or None, etag)``, or None when missing."""
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
            # Not worth it if it does not shrink.
            if len(packed) >= len(body):
                packed = None
        # ETag from mtime and size: an update rewrites every file.
        entry = (body, packed, f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"')

        with self._lock:
            self._files[path] = (stamp, entry)
        return entry
