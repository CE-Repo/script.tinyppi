"""Deciding whether a film is IMAX material.

An IMAX sequence is not a ratio: a film shot for IMAX carries two framings and
switches between them, so 1.78:1 is IMAX in The Dark Knight but just the format
in a TV production. No single frame can tell those apart, so the film is
identified instead, from the name it plays under (an ``IMAX`` release name) or
from ``resources/data/imax_titles.txt`` plus the user's own copy under the
addon's profile folder.

The name is taken from the file and its folder and from what Kodi knows about
the item -- title, original title and year -- so a film streamed through an
addon, where the path is an opaque URL, is identified by its library entry
instead.  Each name is reduced to bare words (accents folded, ``&`` spelled
out, roman numerals and number words in figures) and cut where the release name
stops naming the film and starts describing the file, and a listed title has to
sit at the end of what remains.  That anchoring is what keeps a sequel apart
from the film it follows: *Aquaman and the Lost Kingdom* does not end in
*Aquaman*.  A year on a listed entry has to be the year of the item as well,
which is how a remake stays apart from its original.

A film that is not identified is never marked, since guessing from the picture
alone would claim IMAX for every ordinary 1.78:1 film.
"""

import os
import re
import unicodedata
from urllib.parse import unquote

import xbmc
import xbmcaddon
import xbmcvfs

_ADDON = xbmcaddon.Addon()

_TITLE_FILE = "imax_titles.txt"

# Marks a listed title as carrying the IMAX Enhanced certification rather than
# plain IMAX material, so the badge can say which.  Written after the title and
# before any comment:  ``Eternals @enhanced   # Disney+ only``
_ENHANCED_TAG = "@enhanced"

# Title -> [(year or None, is IMAX Enhanced)]; parsed once per instance.  A
# title can appear more than once when two films share it, which is why the
# years hang off the title rather than the other way round.
_titles: dict[str, tuple[tuple[int | None, bool], ...]] | None = None

# Last answer, kept per playing file so a badge asked for on every polling tick
# is only worked out once.  (path, names it was worked out from, IMAX,
# IMAX Enhanced).
_cache: tuple[str, tuple[str, ...], bool, bool] | None = None

# A year, as it appears in a release name or on a listed entry.
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Words that mean the release name has stopped naming the film and started
# describing the file.  Everything from the first of these onwards is dropped
# before a title is looked for, so "Dunkirk 2017 2160p UHD BluRay" is read as
# "Dunkirk" and a title cannot be matched against a codec.
_TAGS = frozenset("""
    uhd hd sd 4k 8k hdr hdr10 hdr10plus dv dovi hlg sdr imax remux bluray
    bd br bdrip brrip bdremux webrip webdl web hdtv pdtv dvdrip dvd dvd5 dvd9
    hddvd vhs cam ts tc r5 hdrip amzn nf dsnp atvp hmax mubi itunes stan hulu
    pcof hevc avc av1 xvid divx mpeg2 vc1 dts dtshd dtsx truehd atmos ddp dd
    ac3 eac3 aac flac opus mp3 lpcm dual multi dl german english french italian
    spanish japanese korean hindi truefrench vostfr ita eng ger fre spa jpn
    subbed dubbed extended unrated uncut uncensored directors director cut
    remastered restored edition theatrical open matte oar repack proper limited
    internal complete disc sample retail hybrid criterion anniversary
    season episode
""".split())

# The same, for tags built out of digits: 1080p, 2160i, x265, h264, 10bit, and
# the episode numbers that mark an item as television rather than a film.
_TAG_SHAPES = re.compile(
    r"^(?:\d{3,4}[pi]|[xh]26[3-5]|\d{1,2}bit|s\d{1,2}e\d{1,3}|\d{1,2}x\d{2})$")

# Spellings that name the same thing, applied to listed titles and to release
# names alike so both sides come out the same.  Roman numerals stop at what
# cannot be read as an ordinary word: "I", "V" and "X" stay letters, so
# "Batman v Superman" survives.
_ALIASES = {
    "ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8",
    "ix": "9", "xi": "11", "xii": "12",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "volume": "vol", "pt": "part", "chapter": "part",
}

# Folders that are part of a disc layout rather than a name; the film is named
# by whatever holds them.
_DISC_FOLDERS = frozenset({
    "bdmv", "stream", "playlist", "clipinf", "backup",
    "video_ts", "audio_ts", "hvdvd_ts",
})

# Disc images.  Kodi plays one by mounting it and handing out a path into the
# disc inside, so the name of the image is where the film is named.
_IMAGE_TYPES = frozenset({"iso", "img", "nrg", "mdf", "udf", "bin", "cue"})

# What may be dropped off the end of a name as a file type rather than kept as
# a word.  Only these, so a title cannot lose "The.Dark.Knight.2008.2160p" to
# an extension that was never there.
_FILE_TYPES = _IMAGE_TYPES | frozenset("""
    mkv mp4 m4v avi mov wmv webm flv ogm rmvb 3gp divx mpg mpeg m2v vob evo
    m2ts mts ts trp mpls ifo bdmv dat strm disc
""".split())

# Paths whose item is a broadcast rather than a release (see _playing_names).
_STREAM_PREFIXES = ("pvr://", "upnp://")


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _is_tag(token: str) -> bool:
    """Return whether *token* describes the file rather than the film."""
    return token in _TAGS or bool(_TAG_SHAPES.match(token)) or bool(_YEAR.match(token))


def _words(text: str) -> list[str]:
    """Split *text* on everything that is not a letter or a digit."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _unshuffle_article(text: str) -> str:
    """Put back an article a naming scheme has parked at the end.

    ``Dark Knight, The (2008)`` is how a sort-title reads, and only the words
    after the article say so: nothing but a year and the like may follow it.
    That is what keeps a comma inside a title, as in ``The Good, the Bad and
    the Ugly``, from being read as one.
    """
    match = re.match(r"^(.+?),\s*(the|a|an)\b(.*)$", text.strip(), flags=re.I)
    if not match or not all(_is_tag(word) for word in _words(match.group(3))):
        return text
    return f"{match.group(2)} {match.group(1)} {match.group(3)}"


def _tokens(text: str) -> list[str]:
    """Reduce a name to its bare words, so names differing only in spelling
    compare equal.

    Accents are folded onto their base letter (``Folie a Deux`` matches ``Folie
    à Deux``), ``&`` is spelled out, an article parked at the end by a library
    naming scheme is put back in front, punctuation becomes word breaks and the
    spellings in ``_ALIASES`` are settled.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _unshuffle_article(text.replace("&", " and "))
    return [_ALIASES.get(word, word) for word in _words(text)]


def _film_part(tokens: list[str]) -> list[str]:
    """Return the leading words that still name the film.

    Cut at the first word describing the file, never at the very first word, so
    a film named after a number (``1917``) keeps a name to match on.
    """
    for index, token in enumerate(tokens):
        if index and _is_tag(token):
            return tokens[:index]
    return tokens


def _year_of(tokens: list[str]) -> int | None:
    """Return the first year in *tokens*, or None when there is none."""
    for token in tokens:
        if _YEAR.match(token):
            return int(token)
    return None


def _read_titles(path: str) -> dict[str, list[tuple[int | None, bool]]]:
    """Return ``{title: [(year, is enhanced)]}`` from one file, empty when
    unreadable.

    A trailing year is taken off the title and kept as a condition on it, so
    ``Ghostbusters 2016`` matches the remake wherever the year sits in the
    release name and never the original.
    """
    try:
        with xbmcvfs.File(path) as handle:
            raw = handle.read()
    except Exception as exc:
        _log(f"IMAX: cannot read {path}: {exc}")
        return {}

    entries: dict[str, list[tuple[int | None, bool]]] = {}
    for line in (raw or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue

        is_enhanced = line.lower().endswith(_ENHANCED_TAG)
        if is_enhanced:
            line = line[:-len(_ENHANCED_TAG)].strip()

        tokens = _tokens(line)
        year = None
        # A year in last place is read as a condition rather than as part of
        # the name.  A title ending in a year of its own, Wonder Woman 1984,
        # comes out the same either way: a release name carries that year in
        # the same place, and the rest of it is cut off there too.
        if len(tokens) > 1 and _YEAR.match(tokens[-1]):
            year = int(tokens[-1])
            tokens = tokens[:-1]
        if not tokens:
            continue
        entries.setdefault(" ".join(tokens), []).append((year, is_enhanced))
    return entries


def _title_index() -> dict[str, tuple[tuple[int | None, bool], ...]]:
    """Return every known title, bundled list plus the user's own."""
    global _titles

    if _titles is None:
        bundled = os.path.join(
            _ADDON.getAddonInfo("path"), "resources", "data", _TITLE_FILE)
        personal = os.path.join(
            xbmcvfs.translatePath(_ADDON.getAddonInfo("profile")), _TITLE_FILE)
        merged = _read_titles(bundled)
        for title, listed in _read_titles(personal).items():
            merged.setdefault(title, []).extend(listed)
        _titles = {title: tuple(listed) for title, listed in merged.items()}
        enhanced = sum(1 for listed in _titles.values()
                       for _, is_enhanced in listed if is_enhanced)
        _log(f"IMAX: {len(_titles)} titles known, {enhanced} of them IMAX Enhanced")
    return _titles


def _playing_path() -> str:
    """Return the path of the playing file, or ''.

    Kodi hands out a path into whatever it opened, which for a disc image is a
    stream inside the mounted disc and the image's own path wrapped up and
    encoded inside that:

        bluray://udf%3a%2f%2f%252fFilme%252fDunkirk.iso%2f/BDMV/PLAYLIST/00800.mpls

    The encoding is undone here -- once per layer, since each wrapping encodes
    the one below it again -- so the path can be read as the folders it names.
    Any query string is dropped: an addon puts its own bookkeeping there.
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
    """Return the names a path holds the film under.

    The played file, and then the first thing above it that is a name rather
    than part of a disc layout -- for a disc image that is the image itself.
    An image is named after nothing at all often enough (VIDEO1.ISO, disc.iso)
    that the folder holding it is worth having as well.
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

    What the path names (see _path_names), since a release name lives on the
    file or on the folder holding it and, for a disc image, on the image, plus
    what Kodi knows about the item -- a film streamed through an addon has no
    name in its path at all, only a library entry.  Names are kept apart rather
    than run together, so a title has to end one of them rather than merely
    appear somewhere in the pile.
    """
    names: list[str] = _path_names(path.rstrip("/\\"))

    # An episode carries its own title, which is a film title often enough
    # (Nope, Him) to be worth leaving alone, and a live channel or a recording
    # carries the programme rather than a release name.  Both are left to what
    # the path says.
    is_episode = bool(xbmc.getInfoLabel("VideoPlayer.TVShowTitle").strip())
    if not is_episode and not path.lower().startswith(_STREAM_PREFIXES):
        year = xbmc.getInfoLabel("VideoPlayer.Year").strip()
        for label in ("VideoPlayer.Title", "VideoPlayer.OriginalTitle"):
            title = xbmc.getInfoLabel(label).strip()
            if title:
                names.append(f"{title} {year}" if year else title)

    return tuple(name for name in names if name)


def _classify(names: tuple[str, ...]) -> tuple[bool, bool]:
    """Return ``(is IMAX, is IMAX Enhanced)`` for the given names.

    A name saying so outright is taken at its word; otherwise every ending of
    the part that still names the film is looked up, which anchors a listed
    title to the end of the name and keeps a sequel from matching the film it
    follows.
    """
    index = _title_index()
    imax = enhanced = False

    for name in names:
        tokens = _tokens(name)
        if not tokens:
            continue

        for first, second in zip(tokens, tokens[1:] + [""]):
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


def _current() -> tuple[bool, bool]:
    """Return ``(is IMAX, is IMAX Enhanced)`` for what is playing.

    Worked out once per file: the answer names the film, not the framing of
    whatever is on screen this second.  It is worked out again when the names
    change, since Kodi fills in what it knows about an item a moment after
    playback starts, and an identification once made is kept for the rest of
    the file -- metadata coming and going must not make the badge blink.
    """
    global _cache

    path = _playing_path()
    names = _playing_names(path)

    if _cache is not None and _cache[0] == path:
        if _cache[1] == names:
            return _cache[2], _cache[3]
        imax, enhanced = _classify(names)
        imax, enhanced = imax or _cache[2], enhanced or _cache[3]
    else:
        imax, enhanced = _classify(names)

    _cache = (path, names, imax, enhanced)
    return imax, enhanced


def is_known_imax_title(name: str = "") -> bool:
    """Return whether what is playing is known to hold IMAX material.

    True when the name says ``IMAX`` outright, or matches an entry in the title
    lists.  A name given here is judged on its own, without touching the player.
    """
    if name:
        return _classify((name,))[0]
    return _current()[0]


def is_enhanced_title(name: str = "") -> bool:
    """Return whether what is playing is an IMAX Enhanced release.

    Recognised from the name saying so outright, or from an ``@enhanced`` tag on
    its entry in the title lists.  A film can hold IMAX material without the
    certification, so this is a narrower claim than is_known_imax_title().
    """
    if name:
        return _classify((name,))[1]
    return _current()[1]
