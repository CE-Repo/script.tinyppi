"""Deciding whether a film is IMAX material.

An IMAX sequence is not a ratio: a film shot for IMAX carries two framings and
switches between them, so 1.78:1 is IMAX in The Dark Knight but just the format
in a TV production. No single frame can tell those apart, so the film is
identified instead, from its filename (an ``IMAX`` release name) or from
``resources/data/imax_titles.txt`` plus the user's own copy under the addon's
profile folder.

A film that is not identified is never marked, since guessing from the picture
alone would claim IMAX for every ordinary 1.78:1 film.
"""

import os
import re

import xbmc
import xbmcaddon
import xbmcvfs

_ADDON = xbmcaddon.Addon()

_TITLE_FILE = "imax_titles.txt"

# Marks a listed title as carrying the IMAX Enhanced certification rather than
# plain IMAX material, so the badge can say which.  Written after the title and
# before any comment:  ``Eternals @enhanced   # Disney+ only``
_ENHANCED_TAG = "@enhanced"

# (every known title, those certified IMAX Enhanced); parsed once per instance.
_titles: tuple[frozenset[str], frozenset[str]] | None = None


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _normalise(text: str) -> str:
    """Reduce a name to lowercase words separated by single spaces, so release
    names differing only in punctuation compare equal.  Padded so a match can
    be anchored on whole words."""
    return " %s " % re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _read_titles(path: str) -> tuple[set[str], set[str]]:
    """Return ``(titles, enhanced)`` from one file; both empty when unreadable.

    ``enhanced`` is the subset tagged with ``@enhanced`` and is also part of
    ``titles`` -- an IMAX Enhanced release is IMAX material either way.
    """
    try:
        with xbmcvfs.File(path) as handle:
            raw = handle.read()
    except Exception as exc:
        _log(f"IMAX: cannot read {path}: {exc}")
        return set(), set()

    titles: set[str] = set()
    enhanced: set[str] = set()
    for line in (raw or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue

        is_enhanced = line.lower().endswith(_ENHANCED_TAG)
        if is_enhanced:
            line = line[:-len(_ENHANCED_TAG)].strip()

        title = _normalise(line).strip()
        if not title:
            continue
        titles.add(title)
        if is_enhanced:
            enhanced.add(title)
    return titles, enhanced


def _title_lists() -> tuple[frozenset[str], frozenset[str]]:
    """Return every known title and the IMAX Enhanced subset, bundled list plus
    the user's own."""
    global _titles

    if _titles is None:
        bundled = os.path.join(
            _ADDON.getAddonInfo("path"), "resources", "data", _TITLE_FILE)
        personal = os.path.join(
            xbmcvfs.translatePath(_ADDON.getAddonInfo("profile")), _TITLE_FILE)
        known, enhanced = _read_titles(bundled)
        more, more_enhanced = _read_titles(personal)
        _titles = (frozenset(known | more), frozenset(enhanced | more_enhanced))
        _log(f"IMAX: {len(_titles[0])} titles known, "
             f"{len(_titles[1])} of them IMAX Enhanced")
    return _titles


def _playing_name() -> str:
    """Return the normalised name of the playing file and its folder.

    The folder is included because release names often live there rather than
    on the file itself.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""
    if not path:
        return ""

    folder, name = os.path.split(path.rstrip("/\\"))
    return _normalise("%s %s" % (os.path.basename(folder), os.path.splitext(name)[0]))


def is_known_imax_title(name: str = "") -> bool:
    """Return whether the playing file is known to hold IMAX material.

    True when the name says ``IMAX`` outright, or matches an entry in the title
    lists.
    """
    name = name or _playing_name()
    if not name:
        return False
    if " imax " in name:
        return True
    return any(title in name for title in _title_lists()[0])


def is_enhanced_title(name: str = "") -> bool:
    """Return whether the playing file is an IMAX Enhanced release.

    Recognised from the name saying so outright, or from an ``@enhanced`` tag on
    its entry in the title lists.  A film can hold IMAX material without the
    certification, so this is a narrower claim than is_known_imax_title().
    """
    name = name or _playing_name()
    if not name:
        return False
    if " imax enhanced " in name:
        return True
    return any(title in name for title in _title_lists()[1])
