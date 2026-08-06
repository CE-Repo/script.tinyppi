"""Deciding whether the scene on screen is IMAX material.

An IMAX sequence is not a ratio.  A film shot for IMAX carries two framings and
switches between them, and the taller one is the IMAX material -- so 1.78:1 is
IMAX in The Dark Knight and merely the format in a television production.  No
single frame can tell those apart, so the film has to be identified first:

* **Filename** -- a release with ``IMAX`` in its name is telling us outright.
* **Title list** -- ``resources/data/imax_titles.txt``, plus anything the user
  adds in their own ``imax_titles.txt`` under the addon's profile folder, which
  an addon update will not overwrite.

Neither says anything about the scene currently running -- they identify the
film, not the moment.  Once the film is known, though, the scene follows from
the bars: a title that holds IMAX material shows it in its expanded framing, so
thin bars are the IMAX scenes and the letterboxed ones are not.

A film that is not identified is never marked.  That is deliberate: guessing
from the picture alone would claim IMAX for every ordinary 1.78:1 film.
"""

import os
import re

import xbmc
import xbmcaddon
import xbmcvfs
from core.utils import coded_frame, parse_offsets

_ADDON = xbmcaddon.Addon()

# For a title known to be IMAX, bars this thin (as a share of the coded height)
# are its expanded framing.  2.39:1 in a 16:9 frame sits at 0.26 and 2.20:1 at
# 0.19, both well clear; 1.90:1 reaches 0.06 and a full frame 0.
_EXPANDED_BAR_FRACTION = 0.12

_TITLE_FILE = "imax_titles.txt"
_titles: frozenset[str] | None = None       # parsed once per script instance


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _normalise(text: str) -> str:
    """Reduce a name to lowercase words separated by single spaces.

    Release names differ only in punctuation -- ``The.Dark.Knight.2008.2160p``
    against ``The Dark Knight (2008) UHD`` -- so everything that is not a letter
    or a digit becomes a gap, and both sides are compared in those terms.  The
    result is padded so a match can be anchored on whole words.
    """
    return " %s " % re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _read_titles(path: str) -> set[str]:
    """Return the normalised titles listed in one file, empty when unreadable."""
    try:
        with xbmcvfs.File(path) as handle:
            raw = handle.read()
    except Exception as exc:
        _log(f"IMAX: cannot read {path}: {exc}")
        return set()

    titles = set()
    for line in (raw or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            titles.add(_normalise(line).strip())
    return titles


def _title_list() -> frozenset[str]:
    """Return every known IMAX title, bundled list plus the user's own."""
    global _titles

    if _titles is None:
        bundled = os.path.join(
            _ADDON.getAddonInfo("path"), "resources", "data", _TITLE_FILE)
        personal = os.path.join(
            xbmcvfs.translatePath(_ADDON.getAddonInfo("profile")), _TITLE_FILE)
        _titles = frozenset(_read_titles(bundled) | _read_titles(personal))
        _log(f"IMAX: {len(_titles)} titles known")
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
    lists.  Says nothing about the scene currently on screen.
    """
    name = name or _playing_name()
    if not name:
        return False
    if " imax " in name:
        return True
    return any(title in name for title in _title_list())


def is_imax_scene(offsets: str) -> bool:
    """Return whether the scene on screen is IMAX material.

    Call once per poll with the offsets actually on display.  False for a
    placeholder, a status label, or any film that is not a known IMAX title.
    """
    if not is_known_imax_title():
        return False

    bars = parse_offsets(offsets)
    coded = coded_frame()
    if bars is None or coded is None:
        return False

    return bars[2] + bars[3] <= coded[1] * _EXPANDED_BAR_FRACTION
