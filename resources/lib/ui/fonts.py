# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Register the overlay's font sizes in the active Kodi skin.

The overlay lays out against two specific sizes (21 for the metadata rows, 32
for the headers), so it registers them in the skin's Font.xml under its own
names.  Both name ``arial.ttf``, which Kodi distributes itself -- nothing is
copied into the skin, so there is no font file that can go missing or drift out
of sync with the entry that names it.

Nothing runs on import.  The service installs the entries at Kodi start and
again whenever a skin is loaded -- a skin switch, a skin update, or the reload
this triggers itself -- so by the time anyone presses the button the work is
long done.  ``ensure_fonts()`` is what the overlay calls on its way up, and it
answers out of the mark the install leaves behind (see PROP_FONTS_READY): one
window-property read and one stat per Font.xml already known, rather than a
search of the skin directory and a parse of every file.  That mark names the
files it was taken from, so a Font.xml replaced under a running Kodi -- by an
update that never announced itself, or by anything else -- is caught by the
next launch rather than waiting for a restart.

A skin drawn for more than one resolution has a Font.xml per resolution folder
(the ``<res folder=...>`` entries of its addon.xml), and Kodi reads the one of
the resolution in use; every one of them gets the entries.
"""

import os
import re
import threading
import traceback

import xbmc
import xbmcvfs
from core import settings
from core.files import atomic_write
from core.log import channel
from core.utils import home_window

# Kodi's own copy, named by its full path rather than as a bare "arial.ttf".
# A bare name is looked up in the skin's font directory first, and skins that
# ship an arial.ttf of their own -- a different typeface under the same name --
# would answer with it, so the overlay would render in whatever that skin
# happens to bundle.  A value carrying "://" passes CURL::IsFullPath, which
# makes Kodi take the path as given and skip the directory search entirely.
# Should this path ever fail to load, Kodi still substitutes its bare
# "arial.ttf" on its own, which is the behaviour this replaces.
_FONT_FILE = "special://xbmc/media/Fonts/arial.ttf"

# Only the sizes are the overlay's own; the headers ask for their weight with
# [B] markup in the skin XML, so no separate bold face is registered.
_REQUIRED_FONTS = (
    {"name": "font23_narrow", "filename": _FONT_FILE, "size": "21"},
    {"name": "font32",        "filename": _FONT_FILE, "size": "32"},
)

# Home-window (10000) property describing the Font.xml files that have been
# checked and found complete: the skin they belong to, the version of this addon
# that checked them (a TinyPPI update may want fonts the last one did not), the
# files themselves and what each looked like on disk.  Verifying all that from
# scratch costs a look through the skin directory plus a parse of every file,
# which is far too much to put in front of a window the viewer is waiting for;
# against this mark it costs one stat per file whose path is already known.
#
# Kodi drops Home-window properties when it exits, so a session always checks at
# least once.
PROP_FONTS_READY = "TinyPPI.FontsReady"

# The same description of a Font.xml the entries could not be put into: a skin
# installed read-only (the system skins on CoreELEC are), a file with no
# fontset in it, or no Font.xml at all.  Trying again cannot help until the skin
# or a file changes, and every try is the full search and parse plus an error in
# the log, on every launch -- so a failure is remembered as a success is, and
# lapses on the same terms.
PROP_FONTS_FAILED = "TinyPPI.FontsFailed"

# Held apart by a character no path or version carries.
_MARK_SEPARATOR = "\n"

# One install at a time.  Both callers are in the service now -- the warm-up at
# startup and the skin-load handler -- and they can land at the same moment
# when Kodi is still settling; two of these writing one Font.xml would not be.
_install_lock = threading.Lock()


_log = channel("fonts", xbmc.LOGINFO)


# The <res> entries of a skin's addon.xml, and the folder each one names.  A
# skin keeps its windows -- and its Font.xml -- in one folder per resolution it
# was drawn for, and Kodi reads Font.xml out of the folder of the resolution in
# use, falling back to the default one's (CSkinInfo::GetSkinPath).  Read as
# text for the same reason Font.xml is (see below), comments taken out first so
# a <res> somebody commented out is not mistaken for one in force.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_RES_RE     = re.compile(r"<res\b[^>]*>", re.IGNORECASE)
_FOLDER_RE  = re.compile(r"""\bfolder\s*=\s*(["'])(.*?)\1""")

# Folders the fallback walk below never looks into: they hold the skin's
# pictures and font files -- thousands of entries on a large skin -- and never
# its Font.xml.
_WALK_SKIP = frozenset({"media", "fonts"})


def _res_folders(skin_path: str) -> list[str]:
    """The resolution folders *skin_path* declares, as absolute paths inside it,
    in the order its addon.xml lists them; [] when it names none."""
    try:
        with open(os.path.join(skin_path, "addon.xml"), "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError as exc:
        _log(f"cannot read the skin's addon.xml: {exc}", xbmc.LOGWARNING)
        return []

    folders: list[str] = []
    for tag in _RES_RE.findall(_COMMENT_RE.sub("", text)):
        match = _FOLDER_RE.search(tag)
        if match is None or not match.group(2).strip():
            continue
        folder = os.path.normpath(os.path.join(skin_path, match.group(2).strip()))
        # A folder that climbs out of the skin is nothing this writes into.
        if os.path.commonpath((skin_path, folder)) != skin_path:
            continue
        if folder not in folders:
            folders.append(folder)
    return folders


def _font_xml_in(folder: str) -> str | None:
    """The Font.xml directly inside *folder*, or None.  Kodi asks for it under
    that exact name, which sorts ahead of any other spelling of it."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        if name.lower() == "font.xml" and os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return None


def _walk_for_font_xmls(skin_path: str) -> list[str]:
    """Every Font.xml anywhere in *skin_path*, for a skin whose addon.xml names
    no folder that holds one.  Sorted, so two runs agree on the order."""
    found = []
    for root, dirs, files in os.walk(skin_path):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d.lower() not in _WALK_SKIP]
        for fname in files:
            if fname.lower() == "font.xml":
                found.append(os.path.normpath(os.path.join(root, fname)))
    return sorted(found)


def _find_font_xmls(skin_path: str) -> list[str]:
    """Every Font.xml of *skin_path* that Kodi may load, or [] when it has none.

    One per resolution folder the skin declares, rather than whichever file a
    walk of the skin happened to reach first: a skin drawn for two resolutions
    carries a Font.xml in each, the order a directory is listed in is up to the
    file system, and an entry written into the other resolution's file is one
    Kodi never reads.  Kodi picks the folder by the resolution in use, which
    can change under a running skin, so every one of them gets the entries.
    """
    found = [path for path in map(_font_xml_in, _res_folders(skin_path)) if path]
    if not found:
        found = _walk_for_font_xmls(skin_path)
    if not found:
        _log(f"No Font.xml in: {skin_path}", xbmc.LOGWARNING)
    for path in found:
        _log(f"Font.xml found: {path}")
    return found


def _get_skin_path() -> str | None:
    """Return the directory of the skin in force, or None.

    Asked of Kodi rather than worked out: ``special://skin/`` is wherever the
    skin was loaded from -- the user's add-on directory or the system one --
    where piecing the system path together out of the working directory only
    found it on a Kodi that happened to be started from its own.
    """
    path = os.path.normpath(xbmcvfs.translatePath("special://skin/"))
    return path if os.path.isdir(path) else None


def _spec_entry(spec: dict) -> tuple[str, str, str]:
    """Return the ``(name, filename, size)`` a required font is looked up by."""
    return (spec["name"], spec["filename"], spec["size"])


# Font.xml is read and written as text rather than through an XML parser.
#
# For the writer that is what preserves the file byte-for-byte apart from the
# inserted entries: the original XML declaration, encoding, blank lines and
# line endings stay untouched, where ElementTree would rewrite all of these on
# re-serialisation.
#
# For the reader it means the check and the insert decide "is this font
# already here?" by the same rule, so they cannot disagree about a file, and
# it keeps a Font.xml this addon did not write away from a parser that expands
# the entity declarations an internal DTD may carry -- the XML external entity
# class of problem (CWE-611), which the stdlib parser is open to and which no
# reading of a skin file needs.
_FONTSET_RE = re.compile(r"(<fontset\b[^>]*>)(.*?)(</fontset>)", re.DOTALL)
_INCLUDE_RE = re.compile(r"<include\b.*?(?:/>|</include>)", re.DOTALL)
_ID_RE      = re.compile(r'\bid\s*=\s*"([^"]*)"')
# A whole <font> element with the indent it sits on, so removing one takes its
# line with it instead of leaving a blank.
_FONT_RE    = re.compile(r"[ \t]*<font>.*?</font>[ \t]*\r?\n?", re.DOTALL)


def _block_entry(block: str) -> tuple[str, str, str] | None:
    """Return the ``(name, filename, size)`` a <font> block declares, or None
    when it does not carry all three."""
    values = []
    for tag in ("name", "filename", "size"):
        match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", block, re.DOTALL)
        if match is None:
            return None
        values.append(match.group(1))
    return tuple(values)


def _fontset_entries(inner: str) -> set:
    """The ``(name, filename, size)`` triples *inner* (a fontset body) declares.

    Name, file and size have to meet inside one <font> block, which is why the
    blocks are read as triples rather than searched for the three values
    separately: matching them anywhere in the fontset would pair this addon's
    font name with an unrelated entry's font file -- names like ``font32`` are
    common in skins -- and skip an insert the overlay needs.

    Built once per fontset and asked about each required font in turn.  A skin
    Font.xml runs to a few hundred blocks across its fontsets, and the regex
    pass over them is the bulk of what checking costs, so it is not worth
    repeating per font.
    """
    entries = set()
    for block in _FONT_RE.findall(inner):
        entry = _block_entry(block)
        if entry is not None:
            entries.add(entry)
    return entries


def _read_font_xml(font_xml_path: str) -> str | None:
    """Return the text of Font.xml, or None when it cannot be read."""
    try:
        with open(font_xml_path, "rb") as fh:
            return fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _log(f"cannot read Font.xml: {exc}", xbmc.LOGERROR)
        return None


def _fontset_id(open_tag: str) -> str:
    """The id a <fontset> opening tag declares, for the log line naming it."""
    match = _ID_RE.search(open_tag)
    return match.group(1) if match else "?"


def fonts_already_installed(font_xml_path: str) -> bool:
    """Return True only when every required font is registered in Font.xml.

    Nothing is checked on disk: the file named is Kodi's own ``arial.ttf``,
    which it locates through its own search path, and substitutes for itself
    when it cannot.

    The size is part of a font's identity here, not just its name and file:
    ``arial.ttf`` and a name like ``font32`` are common enough in skins that a
    match on those two alone would report a font as present at a size the
    overlay never asked for, and its rows would be laid out against the wrong
    metrics.  That is _fontset_entries' rule, which is also the one
    _install_xml picks its inserts by.

    The caller locates the file (see _find_font_xmls): _install_fonts() does
    that once for the check and the insert together rather than once for each.
    """
    original = _read_font_xml(font_xml_path)
    if original is None:
        return False

    # Every fontset must carry all required fonts, not just the first.
    fontsets = _FONTSET_RE.findall(original)
    if not fontsets:
        return False

    for open_tag, inner, _close_tag in fontsets:
        entries = _fontset_entries(inner)
        for font_spec in _REQUIRED_FONTS:
            if _spec_entry(font_spec) not in entries:
                _log(f'XML entry missing: {font_spec["name"]} '
                     f'in fontset "{_fontset_id(open_tag)}"')
                return False

    return True


def _font_block(spec: dict, indent: str, nl: str) -> str:
    """Render a <font> element (leading newline included) at *indent*."""
    return (
        f"{nl}{indent}<font>"
        f"{nl}{indent}    <name>{spec['name']}</name>"
        f"{nl}{indent}    <filename>{spec['filename']}</filename>"
        f"{nl}{indent}    <size>{spec['size']}</size>"
        f"{nl}{indent}</font>"
    )


def _install_xml(font_xml_path: str) -> bool:
    """Insert missing font entries into every <fontset>; True if any written.

    Nothing already in the file is edited or removed -- the entries go in ahead
    of it, where Kodi reads them first.  Works purely on the file text so
    nothing outside the inserted <font> blocks is altered.
    """
    original = _read_font_xml(font_xml_path)
    if original is None:
        return False

    nl = "\r\n" if "\r\n" in original else "\n"
    modified = False

    def _process(match: "re.Match") -> str:
        nonlocal modified
        open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)
        fset_id = _fontset_id(open_tag)

        entries = _fontset_entries(inner)
        missing = [s for s in _REQUIRED_FONTS if _spec_entry(s) not in entries]
        if not missing:
            return match.group(0)

        # Insert right after the <include> element, which puts these at the top
        # of the fontset -- Kodi keeps the first <font> of a given name and never
        # opens the later ones, so entries an older version left behind, or a
        # skin's own font of the same name, lose to the one written here.  The
        # indent comes from the include line so it matches the formatting around
        # it.
        inc = _INCLUDE_RE.search(inner)
        if inc:
            insert_pos = inc.end()
            line_start = inner.rfind("\n", 0, inc.start()) + 1
            indent = re.match(r"[ \t]*", inner[line_start:inc.start()]).group(0)
        else:
            insert_pos = 0
            indent = "        "
        indent = indent or "        "

        blocks = "".join(_font_block(s, indent, nl) for s in missing)
        for spec in missing:
            _log(f'Font inserted: {spec["name"]} in fontset "{fset_id}"')
        modified = True
        return open_tag + inner[:insert_pos] + blocks + inner[insert_pos:] + close_tag

    updated = _FONTSET_RE.sub(_process, original)

    if modified:
        # Whole or not at all: a Font.xml cut short by a power cut is a skin
        # that no longer loads (see core.files).
        try:
            atomic_write(font_xml_path, updated.encode("utf-8"))
        except OSError as exc:
            _log(f"installxml: cannot write Font.xml: {exc}", xbmc.LOGERROR)
            return False
        _log(f"Font.xml written: {font_xml_path}")

    return modified


def _install_fonts() -> None:
    """Check the active skin's Font.xml files in full and fill in what they are
    missing.

    Marks them as checked (PROP_FONTS_READY) once the entries are known to be
    in place in every one, which is what lets ensure_fonts() skip all of this.
    A check that found no Font.xml, or one it could not read or write, marks
    them as failed instead (PROP_FONTS_FAILED), which ensure_fonts() skips just
    the same until the skin or one of the files changes.

    Called with _install_lock held.
    """
    home     = home_window()
    skin_dir = xbmc.getSkinDir()
    home.clearProperty(PROP_FONTS_READY)
    home.clearProperty(PROP_FONTS_FAILED)

    # Not remembered as a failure: finding the skin costs next to nothing, and
    # a skin that cannot be found now may simply not have finished loading.
    skin_path = _get_skin_path()
    if not skin_path:
        _log("Skin path not found", xbmc.LOGWARNING)
        return

    _log(f"Skin path: {skin_path}")

    # Located once and handed to both steps below: finding them is the most
    # expensive part of the whole check.
    font_xmls = _find_font_xmls(skin_path)
    if not font_xmls:
        _remember(home, skin_dir, (), PROP_FONTS_FAILED)
        return

    incomplete = [path for path in font_xmls if not fonts_already_installed(path)]
    if not incomplete:
        _log("All fonts already registered – skipping")
        _remember(home, skin_dir, font_xmls)
        return

    written = failed = 0
    for font_xml_path in incomplete:
        try:
            modified = _install_xml(font_xml_path)
        except Exception as exc:
            _log(f"Installation error: {exc}", xbmc.LOGERROR)
            _log(traceback.format_exc(), xbmc.LOGERROR)
            modified = False
        if modified:
            written += 1
        else:
            failed += 1
            _log(f"the font entries could not be registered in {font_xml_path}; "
                 "not trying again until the skin or its Font.xml changes",
                 xbmc.LOGWARNING)

    # Marked from the files as they now stand, after the writes.
    _remember(home, skin_dir, font_xmls,
              PROP_FONTS_FAILED if failed else PROP_FONTS_READY)
    if not written:
        return
    try:
        xbmc.executebuiltin("ReloadSkin(reload)")
    except Exception:
        pass


def _remember(home, skin_dir: str, font_xmls,
              prop: str = PROP_FONTS_READY) -> None:
    """Record what the check found for these Font.xml files, for
    ensure_fonts(): the entries in place (PROP_FONTS_READY) or out of reach
    (PROP_FONTS_FAILED)."""
    try:
        home.setProperty(prop, _mark(skin_dir, font_xmls))
    except OSError as exc:
        # Nothing to mark it by; the next launch checks again in full.
        _log(f"cannot stat Font.xml: {exc}", xbmc.LOGWARNING)


def _mark(skin_dir: str, font_xmls) -> str:
    """Describe the Font.xml files as they are right now, for either mark.

    No files at all stands for a skin that has no Font.xml to describe.  Raises
    OSError when a file it names is not there any more, which is one of the
    ways a mark stops matching.
    """
    parts = [skin_dir, settings.addon().getAddonInfo("version")]
    for font_xml_path in font_xmls:
        stat = os.stat(font_xml_path)
        parts += (font_xml_path, repr(stat.st_mtime), str(stat.st_size))
    return _MARK_SEPARATOR.join(parts)


def _mark_holds(prop: str = PROP_FONTS_READY) -> bool:
    """Whether a mark still answers for the skin in force.

    The mark names the files it was taken from, so this is one stat of each
    known path -- no walk, no parse.  It stops holding when the skin changed,
    when this addon was updated, or when a Font.xml itself moved, grew or was
    rewritten, which is what a skin update does to it.
    """
    mark = home_window().getProperty(prop)
    parts = mark.split(_MARK_SEPARATOR)
    if len(parts) < 2 or (len(parts) - 2) % 3 or parts[0] != xbmc.getSkinDir():
        return False
    try:
        return _mark(parts[0], parts[2::3]) == mark
    except OSError:
        return False


def _settled() -> bool:
    """Whether the last check still answers, whichever way it went."""
    return _mark_holds(PROP_FONTS_READY) or _mark_holds(PROP_FONTS_FAILED)


def ensure_fonts() -> None:
    """Make sure the overlay's font entries are registered, cheaply.

    What the overlay calls on its way up.  The service has normally installed
    them already, so the ordinary launch answers out of one window-property
    read and one stat; only a session where that has not happened -- the
    service disabled, a skin loaded without our entries reaching it -- pays for
    the walk and the parse, and pays for it once.  So does a skin the entries
    cannot be written into: it is checked once and then left alone.
    """
    if _settled():
        return
    with _install_lock:
        # Taken again behind the lock: the other caller may have been doing
        # exactly this while we waited for it.
        if _settled():
            return
        _install_fonts()


# There is no monitor class here any more.  The one that used to live here
# listened for ``onSkinChanged`` and a ``System.OnUpdated`` notification, and
# Kodi makes neither call: its Python Monitor has no onSkinChanged callback at
# all, and it announces no System.OnUpdated.  What it does announce is
# ``GUI.OnSkinLoaded``, on every skin load -- a switch, an update of the skin in
# use, and the reload above -- and the service listens for that one instead
# (see service/monitor.py).
