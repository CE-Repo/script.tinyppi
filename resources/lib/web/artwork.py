# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dashboard artwork: the playing title's poster and fanart, and the shelf
pictures, read through Kodi's VFS."""

import contextlib
import os
import re
import threading
from urllib.parse import quote, unquote

import xbmc
import xbmcvfs
from core.log import channel
from web.snapshot import art_path

# Artwork kinds the page may request, and the maximum size.  ``thumb`` is an
# episode still, used by the series episode list (see web/library.py).
KINDS = ("poster", "fanart", "thumb")
_MAX_ART = 8 * 1024 * 1024

# Artwork URLs carry a tag that changes with the picture (see
# snapshot._art_tags), so responses can be cached as immutable.
CACHE = "private, max-age=604800, immutable"

# Content type by extension; unknown types are sent as JPEG.
_ART_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}
_ART_FALLBACK_TYPE = "image/jpeg"

# Credentials in a source URL (smb://user:secret@nas/), removed from logs.
_USERINFO_IN_URL = re.compile(r"(://)[^/@\s]*@")

_log = channel("web", xbmc.LOGINFO)


def unwrap_image_url(path: str) -> str:
    """Return the source behind a Kodi ``image://`` texture URL.

    The wrapper is ``image://`` plus the percent-encoded source and a
    trailing slash.
    """
    if not path.startswith("image://"):
        return path
    inner = unquote(path[len("image://"):])
    return inner[:-1] if inner.endswith("/") else inner


def art_sources(path: str) -> tuple[str, ...]:
    """Return the addresses a shelf picture can be read from, smallest first.

    Scraped posters are far larger than a phone tile, so Kodi's texture
    cache copy (the plain ``image://`` URL, capped at 1280x720 for posters)
    comes first and the original second (e.g. after a cache clear).

    Not ``?size=thumb``: the cache is keyed by the full URL, so that entry
    usually does not exist and Kodi would build (and for scraped art,
    re-download) a second cache for the whole library.
    """
    if path.startswith("image://"):
        # Already a texture URL.
        return (path, unwrap_image_url(path))
    # A plain file: wrap it for the cache, keep the file as fallback.
    return ("image://" + quote(path, safe="") + "/", path)


def redacted(path: str) -> str:
    """Return *path* with credentials removed, for logging."""
    return _USERINFO_IN_URL.sub(r"\1***@", path)


def art_type(path: str) -> str:
    return _ART_TYPES.get(os.path.splitext(path)[1].lower(), _ART_FALLBACK_TYPE)


def image_type(data: bytes, fallback: str) -> str:
    """Return the image type from the bytes, else *fallback*.

    The texture cache may store a picture in another format (an opaque PNG
    becomes a JPEG), and a wrong type makes the browser draw nothing.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def read_art(path: str) -> bytes | None:
    """Return an artwork file's bytes via Kodi's VFS, or None.

    The VFS reaches local files, shares and URLs alike.
    """
    handle = None
    try:
        handle = xbmcvfs.File(path)
        data = bytes(handle.readBytes(_MAX_ART))
    except Exception as exc:  # the VFS raises RuntimeError or worse for a bad path
        _log(f"artwork {path} unreadable: {exc}", xbmc.LOGDEBUG)
        return None
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.close()
    return data or None


class PlayingArtwork:
    """Cache of the playing title's poster and fanart.

    Every open tab requests the same pictures, which may be large.
    """

    def __init__(self) -> None:
        self._art: dict[str, tuple[str, bytes, str]] = {}
        self._lock = threading.Lock()

    def get(self, kind: str) -> tuple[bytes, str] | None:
        """Return the bytes and type of artwork *kind*, or None.

        Read once per picture, outside the lock, so a slow share blocks
        nothing else (racing requests just read it twice).  Kodi's cached
        copy comes first, like on the shelves (see ``shelf_picture``): a
        scraped original is large, and on a box without internet it cannot
        be read at all.
        """
        path = art_path(kind)
        if not path:
            return None

        with self._lock:
            cached = self._art.get(kind)
            if cached is not None and cached[0] == path:
                return cached[1], cached[2]

        found = shelf_picture(path)
        if found is None:
            return None
        data, content_type = found
        with self._lock:
            self._art[kind] = (path, data, content_type)
        return found


def shelf_picture(path: str) -> tuple[bytes, str] | None:
    """Return one picture (bytes, type), preferring Kodi's cached copy.

    Not cached here; the browser caches them (see ``art_sources``).
    """
    if not path:
        return None
    fallback = art_type(unwrap_image_url(path))
    for attempt, source in enumerate(art_sources(path)):
        data = read_art(source)
        if data is None:
            continue
        if attempt:
            # No cached copy, so the full-size original goes out; logged
            # to diagnose slow walls.
            _log(f"no cached texture for {redacted(source)}, sending "
                 "the original", xbmc.LOGDEBUG)
        return data, image_type(data, fallback)
    return None
