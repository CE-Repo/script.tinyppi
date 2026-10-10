# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Decide whether the playing film is IMAX material.

IMAX is not an aspect ratio: 1.78:1 is IMAX in The Dark Knight but ordinary
in a TV production, and no single frame can tell them apart.  So the film is
identified by name instead: an ``IMAX`` release name, or an entry in
``resources/data/imax_titles.txt`` or the user's copy in the profile folder.

Names come from the file, its folder, and Kodi's title, original title and
year (so addon streams with opaque URLs are found via their library entry).
Each name is normalised (accents folded, ``&`` spelled out, roman numerals
and number words as figures) and cut where the release tags begin; a listed
title must match the end of what remains.  That keeps sequels apart
(*Aquaman and the Lost Kingdom* does not end in *Aquaman*), and a year on a
listed entry must match too, which keeps remakes apart.

Unidentified films are never marked: guessing from the picture would mark
every 1.78:1 film.
"""

import os
import re
import unicodedata
from urllib.parse import unquote

import xbmc
import xbmcvfs
from core import settings
from core.log import channel
from core.maps import IMAX_LOGO_MAP

_TITLE_FILE = "imax_titles.txt"

# Marks a listed title as IMAX Enhanced rather than plain IMAX.  Written
# after the title, before any comment: ``Eternals @enhanced   # Disney+ only``
_ENHANCED_TAG = "@enhanced"

# A year in a release name or on a listed entry.
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Words that describe the file rather than the film.  Everything from the
# first one on is dropped before matching, so "Dunkirk 2017 2160p UHD BluRay"
# reads as "Dunkirk".
_TAGS = frozenset("""
    uhd hd sd 4k 8k hdr hdr10 hdr10plus dv dovi hlg sdr imax remux bluray
    bd br bdrip brrip bdremux webrip webdl web hdtv pdtv dvdrip dvd dvd5 dvd9
    hddvd vhs cam ts tc r5 hdrip amzn nf dsnp atvp hmax mubi itunes stan hulu
    pcof hevc avc av1 xvid divx mpeg2 vc1 dts dtshd dtsx truehd atmos ddp dd
    ac3 eac3 aac flac opus mp3 lpcm dual multi dl german english french italian
    spanish japanese korean hindi truefrench vostfr ita eng ger fre spa jpn
    subbed dubbed extended unrated uncut uncensored directors director cut
    remastered restored edition theatrical open matte oar repack proper limited
    internal complete disc sample retail hybrid criterion anniversary ultimate
    collector collectors kinofassung
    season episode
""".split())

# The same for tags with digits: 1080p, x265, 10bit, and episode numbers.
_TAG_SHAPES = re.compile(
    r"^(?:\d{3,4}[pi]|[xh]26[3-5]|\d{1,2}bit|s\d{1,2}e\d{1,3}|\d{1,2}x\d{2})$")

# Equivalent spellings, applied to both listed titles and release names.
# "I", "V" and "X" stay letters, so "Batman v Superman" survives.
_ALIASES = {
    "ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8",
    "ix": "9", "xi": "11", "xii": "12",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "volume": "vol", "pt": "part", "chapter": "part",
}

# German letters that release names spell out ("Drachenzaehmen"); folding
# them like accents would not match.  ß has no base letter at all.
_SPELLED_OUT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})

# Disc-layout folders; the film is named by the folder above them.
_DISC_FOLDERS = frozenset({
    "bdmv", "stream", "playlist", "clipinf", "backup",
    "video_ts", "audio_ts", "hvdvd_ts",
})

# Disc images: Kodi plays a path inside the mounted image, so the film is
# named by the image file.
_IMAGE_TYPES = frozenset({"iso", "img", "nrg", "mdf", "udf", "bin", "cue"})

# Extensions that may be stripped from a name.  Only these, so a name like
# "The.Dark.Knight.2008.2160p" does not lose a word.
_FILE_TYPES = _IMAGE_TYPES | frozenset("""
    mkv mp4 m4v avi mov wmv webm flv ogm rmvb 3gp divx mpg mpeg m2v vob evo
    m2ts mts ts trp mpls ifo bdmv dat strm disc
""".split())

# Paths whose item is a broadcast rather than a release (see _playing_names).
_STREAM_PREFIXES = ("pvr://", "upnp://")


_log = channel("imax")


def _is_tag(token: str) -> bool:
    """Return whether *token* describes the file rather than the film."""
    return token in _TAGS or bool(_TAG_SHAPES.match(token)) or bool(_YEAR.match(token))


def _words(text: str) -> list[str]:
    """Split *text* on everything that is not a letter or a digit."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _unshuffle_article(text: str) -> str:
    """Move a trailing article back to the front.

    ``Dark Knight, The (2008)`` becomes ``The Dark Knight (2008)``.  Only tags
    may follow the article, so a comma inside a title (``The Good, the Bad
    and the Ugly``) is left alone.
    """
    match = re.match(r"^(.+?),\s*(the|a|an)\b(.*)$", text.strip(), flags=re.I)
    if not match or not all(_is_tag(word) for word in _words(match.group(3))):
        return text
    return f"{match.group(2)} {match.group(1)} {match.group(3)}"


def _tokens(text: str) -> list[str]:
    """Reduce a name to normalised words, so spelling variants compare equal.

    Umlauts and ß are spelled out (``Drachenzähmen`` = ``Drachenzaehmen``),
    other accents folded (``Folie à Deux`` = ``Folie a Deux``), ``&`` spelled
    out, a trailing article moved to the front, punctuation turned into word
    breaks, and ``_ALIASES`` applied.
    """
    # Compose first, so decomposed umlauts (macOS shares) are spelled out.
    text = unicodedata.normalize("NFC", text).translate(_SPELLED_OUT)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _unshuffle_article(text.replace("&", " and "))
    return [_ALIASES.get(word, word) for word in _words(text)]


def _film_part(tokens: list[str]) -> list[str]:
    """Return the leading words that name the film.

    Cut at the first tag, but never at the first word, so ``1917`` keeps a
    name.
    """
    for index, token in enumerate(tokens):
        if index and _is_tag(token):
            return tokens[:index]
    return tokens


def _year_of(tokens: list[str]) -> int | None:
    """Return the first year in *tokens*, or None."""
    for token in tokens:
        if _YEAR.match(token):
            return int(token)
    return None


def _read_titles(path: str) -> dict[str, list[tuple[int | None, bool]]]:
    """Return ``{title: [(year, is enhanced)]}`` from *path* ({} if unreadable).

    A trailing year becomes a condition, so ``Ghostbusters 2016`` matches the
    remake but not the original.
    """
    try:
        with xbmcvfs.File(path) as handle:
            raw = handle.read()
    except Exception as exc:
        _log(f"IMAX: cannot read {path}: {exc}")
        return {}

    entries: dict[str, list[tuple[int | None, bool]]] = {}
    for raw_line in (raw or "").splitlines():
        entry = raw_line.split("#", 1)[0].strip()
        if not entry:
            continue

        is_enhanced = entry.lower().endswith(_ENHANCED_TAG)
        if is_enhanced:
            entry = entry[:-len(_ENHANCED_TAG)].strip()

        tokens = _tokens(entry)
        year = None
        # A trailing year is a condition, not part of the name.  Titles ending
        # in a year (Wonder Woman 1984) still match: release names are cut at
        # the same place.
        if len(tokens) > 1 and _YEAR.match(tokens[-1]):
            year = int(tokens[-1])
            tokens = tokens[:-1]
        if not tokens:
            continue
        entries.setdefault(" ".join(tokens), []).append((year, is_enhanced))
    return entries


def _title_files() -> tuple[str, str]:
    """Return the paths of the bundled list and the user's own list."""
    addon = settings.addon()
    return (
        os.path.join(
            addon.getAddonInfo("path"), "resources", "data", _TITLE_FILE),
        os.path.join(
            xbmcvfs.translatePath(addon.getAddonInfo("profile")), _TITLE_FILE),
    )


def _title_stamp(paths: tuple[str, str]) -> tuple:
    """Return the on-disk stamp of both lists.

    Two stats, done only when the playing file changes (see ``_current``), so
    an added title applies without restarting Kodi.
    """
    stamp: list[tuple[float, int] | None] = []
    for path in paths:
        try:
            listing = os.stat(path)
            stamp.append((listing.st_mtime, listing.st_size))
        except OSError:
            stamp.append(None)
    return tuple(stamp)


class _TitleIndex:
    """All known titles from the bundled and the user's list.

    Title -> [(year or None, is IMAX Enhanced)]; several films can share a
    title.  The stamp is the (mtime, size) of both files, so an edited list
    is re-read without restarting Kodi (the service stays loaded all
    session).
    """

    def __init__(self) -> None:
        self._titles: dict[str, tuple[tuple[int | None, bool], ...]] | None = None
        self._stamp: tuple | None = None

    def get(self) -> dict[str, tuple[tuple[int | None, bool], ...]]:
        """Return the titles, re-reading the lists when either changed."""
        paths = _title_files()
        stamp = _title_stamp(paths)
        if self._titles is None or stamp != self._stamp:
            bundled, personal = paths
            merged = _read_titles(bundled)
            for title, listed in _read_titles(personal).items():
                merged.setdefault(title, []).extend(listed)
            self._titles = {title: tuple(listed)
                            for title, listed in merged.items()}
            self._stamp = stamp
            enhanced = sum(1 for listed in self._titles.values()
                           for _, is_enhanced in listed if is_enhanced)
            _log(f"IMAX: {len(self._titles)} titles known, "
                 f"{enhanced} of them IMAX Enhanced")
        return self._titles


_titles = _TitleIndex()


def _title_index() -> dict[str, tuple[tuple[int | None, bool], ...]]:
    """Return all known titles from the bundled and the user's list."""
    return _titles.get()


def playing_path() -> str:
    """Return the decoded path of the playing file, or ''.

    For a disc image Kodi reports a path inside the mounted disc, with the
    image path encoded once per layer:

        bluray://udf%3a%2f%2f%252fFilme%252fDunkirk.iso%2f/BDMV/PLAYLIST/00800.mpls

    Each layer is decoded so the folder names are readable.  Query strings
    (addon bookkeeping) are dropped.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""

    path = (path or "").split("?", 1)[0]
    for _ in range(4):
        plain = unquote(path)
        if plain == path:
            break
        path = plain
    return path


def _strip_type(part: str) -> str:
    """Return *part* without a trailing file type."""
    stem, extension = os.path.splitext(part)
    return stem if stem and extension[1:].lower() in _FILE_TYPES else part


def _is_image(part: str) -> bool:
    """Return whether *part* names a disc image rather than a folder."""
    return os.path.splitext(part)[1][1:].lower() in _IMAGE_TYPES


def _path_names(path: str) -> list[str]:
    """Return the names *path* gives the film.

    The file itself, the first folder above it that is not a disc-layout
    folder, and, for a disc image, also the folder holding the image (images
    are often named VIDEO1.ISO or disc.iso).
    """
    parts = [part for part in re.split(r"[\\/]+", path)
             if part and not part.endswith(":")]
    if not parts:
        return []

    names = [_strip_type(parts[-1])]

    index = len(parts) - 2
    while index >= 0 and parts[index].lower() in _DISC_FOLDERS:
        index -= 1
    if index >= 0:
        names.append(_strip_type(parts[index]))
        if _is_image(parts[index]) and index:
            names.append(_strip_type(parts[index - 1]))

    return names


def _playing_names(path: str) -> tuple[str, ...]:
    """Return every name the playing item can be identified by.

    The names from the path (see ``_path_names``) plus Kodi's title data,
    which is all an addon stream has.  Names are kept separate, so a title
    must end one of them rather than appear anywhere.
    """
    names: list[str] = _path_names(path.rstrip("/\\"))

    # Episode titles often equal film titles (Nope, Him), and live channels
    # and recordings carry a programme name; for both only the path counts.
    is_episode = bool(xbmc.getInfoLabel("VideoPlayer.TVShowTitle").strip())
    if not is_episode and not path.lower().startswith(_STREAM_PREFIXES):
        year = xbmc.getInfoLabel("VideoPlayer.Year").strip()
        for label in ("VideoPlayer.Title", "VideoPlayer.OriginalTitle"):
            title = xbmc.getInfoLabel(label).strip()
            if title:
                names.append(f"{title} {year}" if year else title)

    return tuple(name for name in names if name)


def _classify(names: tuple[str, ...]) -> tuple[bool, bool]:
    """Return ``(is IMAX, is IMAX Enhanced)`` for *names*.

    An explicit ``IMAX`` tag counts directly.  Otherwise every suffix of the
    film part is looked up, which anchors titles to the end of the name.
    """
    index = _title_index()
    imax = enhanced = False

    for name in names:
        tokens = _tokens(name)
        if not tokens:
            continue

        for first, second in zip(tokens, tokens[1:] + [""], strict=True):
            if first == "imax":
                imax = True
                enhanced = enhanced or second == "enhanced"

        year = _year_of(tokens)
        film = _film_part(tokens)
        for start in range(len(film)):
            listed = index.get(" ".join(film[start:]))
            if not listed:
                continue
            for entry_year, is_enhanced in listed:
                if entry_year is not None and entry_year != year:
                    continue
                imax = True
                enhanced = enhanced or is_enhanced
                _log(f"IMAX: '{name}' identified as {' '.join(film[start:])}"
                     f"{' (Enhanced)' if is_enhanced else ''}")

    return imax, enhanced


class _Verdict:
    """The last answer for the playing file, so the badge is not recomputed
    every tick: ``(path, names used, IMAX, IMAX Enhanced)``."""

    def __init__(self) -> None:
        self._last: tuple[str, tuple[str, ...], bool, bool] | None = None

    def current(self) -> tuple[bool, bool]:
        """Return ``(is IMAX, is IMAX Enhanced)`` for the playing file.

        Computed once per file, and again when the names change (Kodi fills
        in metadata shortly after playback starts).  A positive result is
        kept for the rest of the file so the badge does not blink.
        """
        path = playing_path()
        names = _playing_names(path)

        last = self._last
        if last is not None and last[0] == path:
            if last[1] == names:
                return last[2], last[3]
            imax, enhanced = _classify(names)
            imax, enhanced = imax or last[2], enhanced or last[3]
        else:
            imax, enhanced = _classify(names)

        self._last = (path, names, imax, enhanced)
        return imax, enhanced


_verdict = _Verdict()


def _current() -> tuple[bool, bool]:
    """Return ``(is IMAX, is IMAX Enhanced)`` for the playing file."""
    return _verdict.current()


def is_known_imax_title(name: str = "") -> bool:
    """Return whether the playing film (or *name*) is known IMAX material.

    True for an explicit ``IMAX`` tag or a match in the title lists.
    """
    if name:
        return _classify((name,))[0]
    return _current()[0]


def is_enhanced_title(name: str = "") -> bool:
    """Return whether the playing film (or *name*) is IMAX Enhanced.

    True for an explicit tag or an ``@enhanced`` entry in the title lists; a
    narrower claim than ``is_known_imax_title``.
    """
    if name:
        return _classify((name,))[1]
    return _current()[1]


# --- The combined IMAX logo ------------------------------------------------

# The skin's media folder with the splash graphics.
_MEDIA_PATH = os.path.join(
    settings.addon().getAddonInfo("path"), "resources", "skins", "Default", "media"
)

# Whether each combined logo is installed, by relative path (checked once).
_logo_installed: dict[str, bool] = {}


def imax_logo(hdr_token: str) -> str:
    """Return the combined IMAX logo for *hdr_token*, or ''.

    The logo files are optional; without one the plain logo is used.
    """
    rel_path = IMAX_LOGO_MAP.get(hdr_token, "")
    if not rel_path:
        return ""
    if rel_path not in _logo_installed:
        path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
        _logo_installed[rel_path] = os.path.exists(path)
    return rel_path if _logo_installed[rel_path] else ""
