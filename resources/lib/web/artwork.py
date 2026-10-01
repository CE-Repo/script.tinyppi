# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Artwork for the dashboard: the playing title's poster and fanart, and the
pictures on the library shelves, read through Kodi's own VFS."""

import os
import re
import threading
from urllib.parse import quote, unquote

import xbmc
import xbmcvfs

from core.log import channel
from web.snapshot import art_path

# The artwork kinds the page may ask for, and how big one may be before it is
# treated as something other than a poster.
# ``thumb`` is an episode's own still, which no playing title has: the
# poster of what is on is the show's, and the still belongs to the row in
# the series card's episode list (see web/library.py).
KINDS = ("poster", "fanart", "thumb")
_MAX_ART = 8 * 1024 * 1024

# Artwork is the exception: its address carries a tag that changes with the
# picture (see snapshot._art_tags), so the answer to one address can never go
# out of date and a poster is fetched once per film however often the page is
# reopened.
CACHE = "private, max-age=604800, immutable"

# Artwork comes from wherever the library points, so its type is read off the
# name; anything unrecognised is sent as the JPEG that a poster almost always
# is, and the browser corrects itself from the bytes.
_ART_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}
_ART_FALLBACK_TYPE = "image/jpeg"

# The user name and password in a source address -- smb://user:secret@nas/ --
# which a library on a share often carries in every path it holds, and which
# has no more business in that same debug log than the token has.
_USERINFO_IN_URL = re.compile(r"(://)[^/@\s]*@")

_log = channel("web", xbmc.LOGINFO)


def unwrap_image_url(path: str) -> str:
    """The real file behind a Kodi ``image://`` address.

    Kodi wraps art in a texture URL -- ``image://`` plus the source, percent
    encoded, plus a trailing slash.  The wrapper is a name for its own texture
    cache and not something the file system knows, so it is unwrapped back to
    the path or URL the library actually points at.
    """
    if not path.startswith("image://"):
        return path
    inner = unquote(path[len("image://"):])
    return inner[:-1] if inner.endswith("/") else inner


def art_sources(path: str) -> tuple[str, ...]:
    """Every address one shelf picture can be read from, smallest first.

    A poster the library scraped is a thousand pixels wide and often two, and
    the tile it is drawn in on a phone is a hundred and twenty.  Every one of
    those pixels crosses the network and is then decoded, and a wall of them is
    what a phone feels as a stutter while it is being scrolled.

    Kodi already keeps a smaller copy of everything it has ever drawn -- that
    is what its texture cache is for -- so the wall is read out of that: the
    plain ``image://`` wrapper, which a poster goes into capped at 1280x720 and
    fanart at 1920x1080.  The unwrapped original is kept as the way back, and
    is what answers on a box whose cache has just been cleared.

    Not ``?size=thumb``, which this asked for first until it turned out to be
    the reason a wall took so long to fill.  The cache is keyed by the whole
    address, options and all, so that is a different entry from the plain one
    -- and one that has never existed, where the plain one was made the first
    time Kodi drew the poster in its own window.  Asking for it made the box
    build a second thumbnail cache for the entire collection a poster at a
    time, and for a library whose art is scraped rather than local, building
    one means fetching the original off the internet again.  A third of the
    pixels is not worth a download per tile.
    """
    if path.startswith("image://"):
        # Kodi's own wrapper already: the address its texture cache is under.
        return (path, unwrap_image_url(path))
    # A file the library points at directly.  Wrapped here so the cache
    # answers for it too, and the file itself kept as the way back.
    return ("image://" + quote(path, safe="") + "/", path)


def redacted(path: str) -> str:
    """``path`` with any user name and password taken out, for the log."""
    return _USERINFO_IN_URL.sub(r"\1***@", path)


def art_type(path: str) -> str:
    return _ART_TYPES.get(os.path.splitext(path)[1].lower(), _ART_FALLBACK_TYPE)


def image_type(data: bytes, fallback: str) -> str:
    """What the bytes actually are, rather than what the address suggested.

    The address is no longer a promise: what comes back from the texture cache
    is whatever Kodi chose to store the picture as, which is not always what
    the library scraped it as -- a PNG with nothing transparent in it is kept
    as a JPEG.  A browser handed the wrong type draws nothing at all.
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
    """Read an artwork file through Kodi's own VFS, or None.

    Kodi's VFS rather than ``open``: art lives wherever the library put it,
    which is as often a share or a URL as it is a local file, and only Kodi
    knows how to reach all three.
    """
    handle = None
    try:
        handle = xbmcvfs.File(path)
        data = bytes(handle.readBytes(_MAX_ART))
    except Exception:
        return None
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
    return data or None


class PlayingArtwork:
    """The poster and the fanart of what is playing, kept between requests:
    every open tab asks for the same poster, and it can be a megabyte off a
    share."""

    def __init__(self) -> None:
        self._art: dict[str, tuple[str, bytes, str]] = {}
        self._lock = threading.Lock()

    def get(self, kind: str) -> tuple[bytes, str] | None:
        """The artwork bytes and type for ``kind``, or None when there is none.

        Read once per picture rather than once per request: the film only
        changes with the film.  The read happens outside the lock, so a poster
        coming off a slow share holds nothing else up -- two requests racing
        for the same new picture read it twice and agree on the answer.
        """
        path = art_path(kind)
        if not path:
            return None

        with self._lock:
            cached = self._art.get(kind)
            if cached is not None and cached[0] == path:
                return cached[1], cached[2]

        source = unwrap_image_url(path)
        data = read_art(source)
        if data is None and source != path:
            data = read_art(path)   # an address only Kodi's VFS understands
        if data is None:
            return None

        content_type = art_type(source)
        with self._lock:
            self._art[kind] = (path, data, content_type)
        return data, content_type


def shelf_picture(path: str) -> tuple[bytes, str] | None:
    """One picture off one of the library shelves, read small and not kept.

    Small because of what it is for: these are the tiles on the idle page,
    drawn a hundred and twenty pixels wide, and the file behind one is the
    poster the library scraped at full size.  Kodi's own smaller copy is
    asked for first and the original only last (see ``art_sources``).

    Nothing is held here, unlike the playing title's own artwork: the
    browser keeps these far better than this could, and now has a great
    deal less of each to keep.
    """
    if not path:
        return None
    fallback = art_type(unwrap_image_url(path))
    for attempt, source in enumerate(art_sources(path)):
        data = read_art(source)
        if data is None:
            continue
        if attempt:
            # The cache had nothing, so this is the original going out at
            # whatever size the scraper fetched it.  One line per picture
            # in a debug log is what says a box is serving a wall the slow
            # way -- a cache that has just been cleared, or artwork Kodi
            # has never drawn.
            _log(f"no cached texture for {redacted(source)}, sending "
                 "the original", xbmc.LOGDEBUG)
        return data, image_type(data, fallback)
    return None
