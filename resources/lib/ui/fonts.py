# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Register the overlay's font sizes in the active Kodi skin.

The overlay is laid out for two sizes (21 for the metadata rows, 32 for the
headers), registered in the skin's Font.xml under its own names.  Both use
Kodi's own ``arial.ttf``; no font file is copied into the skin.

The service installs the entries at startup and on every skin load.
``ensure_fonts()``, called by the overlay, then only checks the mark the
install left (see ``PROP_FONTS_READY``): one property read and one stat per
known Font.xml.  The mark names its files, so a Font.xml replaced under a
running Kodi is caught on the next launch.

A skin with several resolution folders (``<res folder=...>`` in its
addon.xml) has one Font.xml per folder; each gets the entries.
"""

import contextlib
import os
import re
import threading
import traceback
from collections.abc import Sequence

import xbmc
import xbmcvfs
from core import settings
from core.files import atomic_write
from core.log import channel
from core.protocols import PropertyTarget
from core.utils import home_window

# Kodi's own arial.ttf by full path.  A bare name is looked up in the skin's
# font folder first, and some skins ship a different typeface under that
# name.  A "://" path passes CURL::IsFullPath, so Kodi skips the search; if
# it fails to load, Kodi still falls back to its bare "arial.ttf".
_FONT_FILE = "special://xbmc/media/Fonts/arial.ttf"

# Only the sizes are custom; bold headers use [B] markup, so no bold face is
# registered.
_REQUIRED_FONTS = (
    {"name": "font23_narrow", "filename": _FONT_FILE, "size": "21"},
    {"name": "font32",        "filename": _FONT_FILE, "size": "32"},
)

# Home-window mark for Font.xml files checked and found complete: skin, add-on
# version (an update may need new fonts), and each file's path and stamp.
# Checking against it costs one stat per file instead of a skin walk and a
# parse.  Home properties do not survive a restart, so every session checks
# at least once.
PROP_FONTS_READY = "TinyPPI.FontsReady"

# The same mark for Font.xml files that could not be updated (read-only
# system skins on CoreELEC, no fontset, no Font.xml).  Retrying cannot help
# until the skin or a file changes, so failures are remembered too.
PROP_FONTS_FAILED = "TinyPPI.FontsFailed"

# Separator that appears in no path or version.
_MARK_SEPARATOR = "\n"

# One install at a time: the startup warm-up and the skin-load handler can
# run at the same moment.
_install_lock = threading.Lock()


_log = channel("fonts", xbmc.LOGINFO)


# The <res> entries of a skin's addon.xml and their folders.  Kodi reads
# Font.xml from the folder of the current resolution, falling back to the
# default (CSkinInfo::GetSkinPath).  Read as text like Font.xml (see below),
# with comments stripped so a commented-out <res> is ignored.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_RES_RE     = re.compile(r"<res\b[^>]*>", re.IGNORECASE)
_FOLDER_RE  = re.compile(r"""\bfolder\s*=\s*(["'])(.*?)\1""")

# Folders the fallback walk skips: images and fonts, never a Font.xml.
_WALK_SKIP = frozenset({"media", "fonts"})


def _res_folders(skin_path: str) -> list[str]:
    """Return the resolution folders declared by *skin_path*'s addon.xml.

    Absolute paths in declaration order; [] when there are none.
    """
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
        # Never write outside the skin folder.
        if os.path.commonpath((skin_path, folder)) != skin_path:
            continue
        if folder not in folders:
            folders.append(folder)
    return folders


def _font_xml_in(folder: str) -> str | None:
    """Return the Font.xml directly inside *folder*, or None.

    Matched case-insensitively; the exact spelling sorts first.
    """
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        if name.lower() == "font.xml" and os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return None


def _walk_for_font_xmls(skin_path: str) -> list[str]:
    """Return every Font.xml under *skin_path*, sorted.

    Fallback for skins whose addon.xml names no folder with one.
    """
    found = []
    for root, dirs, files in os.walk(skin_path):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d.lower() not in _WALK_SKIP]
        for fname in files:
            if fname.lower() == "font.xml":
                found.append(os.path.normpath(os.path.join(root, fname)))
    return sorted(found)


def _find_font_xmls(skin_path: str) -> list[str]:
    """Return every Font.xml of *skin_path* that Kodi may load, or [].

    One per declared resolution folder; the resolution can change while the
    skin runs, so all of them get the entries.
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
    """Return the folder of the active skin, or None.

    ``special://skin/`` resolves to wherever the skin was loaded from, user
    or system add-on folder.
    """
    path = os.path.normpath(xbmcvfs.translatePath("special://skin/"))
    return path if os.path.isdir(path) else None


def _spec_entry(spec: dict) -> tuple[str, str, str]:
    """Return the ``(name, filename, size)`` key of a required font."""
    return (spec["name"], spec["filename"], spec["size"])


# Font.xml is handled as text rather than parsed as XML: writing keeps the
# file byte-for-byte apart from the inserted entries (ElementTree would
# rewrite declaration, encoding and line endings), the check and the insert
# use the same matching rule, and no entity expansion (CWE-611) can happen.
_FONTSET_RE = re.compile(r"(<fontset\b[^>]*>)(.*?)(</fontset>)", re.DOTALL)
_INCLUDE_RE = re.compile(r"<include\b.*?(?:/>|</include>)", re.DOTALL)
_ID_RE      = re.compile(r'\bid\s*=\s*"([^"]*)"')
# A whole <font> element including its indent and line break.
_FONT_RE    = re.compile(r"[ \t]*<font>.*?</font>[ \t]*\r?\n?", re.DOTALL)


def _block_entry(block: str) -> tuple[str, str, str] | None:
    """Return a <font> block's ``(name, filename, size)``, or None if incomplete."""
    values = []
    for tag in ("name", "filename", "size"):
        match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", block, re.DOTALL)
        if match is None:
            return None
        values.append(match.group(1))
    name, filename, size = values
    return name, filename, size


def _fontset_entries(inner: str) -> set:
    """Return the ``(name, filename, size)`` triples in a fontset body.

    The three values must come from the same <font> block; matching them
    separately could pair our name (``font32`` is common) with another
    entry's file and skip a needed insert.  Built once per fontset, since
    the regex pass is the main cost.
    """
    entries = set()
    for block in _FONT_RE.findall(inner):
        entry = _block_entry(block)
        if entry is not None:
            entries.add(entry)
    return entries


def _read_font_xml(font_xml_path: str) -> str | None:
    """Return the text of *font_xml_path*, or None when unreadable."""
    try:
        with open(font_xml_path, "rb") as fh:
            return fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _log(f"cannot read Font.xml: {exc}", xbmc.LOGERROR)
        return None


def _fontset_id(open_tag: str) -> str:
    """Return the id of a <fontset> opening tag, for logging."""
    match = _ID_RE.search(open_tag)
    return match.group(1) if match else "?"


def fonts_already_installed(font_xml_path: str) -> bool:
    """Return whether every fontset in *font_xml_path* has all required fonts.

    The size is part of the match, not just name and file: ``font32`` with
    ``arial.ttf`` is common in skins and may have another size.  The font
    file itself is not checked (Kodi locates and substitutes it).
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
    """Render a <font> element at *indent*, with a leading newline."""
    return (
        f"{nl}{indent}<font>"
        f"{nl}{indent}    <name>{spec['name']}</name>"
        f"{nl}{indent}    <filename>{spec['filename']}</filename>"
        f"{nl}{indent}    <size>{spec['size']}</size>"
        f"{nl}{indent}</font>"
    )


def _install_xml(font_xml_path: str) -> bool:
    """Insert missing font entries into every <fontset>; True if written.

    Existing content is never changed; the entries go first, where Kodi
    reads them first.
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

        # Insert after the <include> element, at the top of the fontset: Kodi
        # uses the first <font> of a name, so ours wins over older or skin
        # entries.  The indent is copied from the include line.
        inc = _INCLUDE_RE.search(inner)
        if inc:
            insert_pos = inc.end()
            line_start = inner.rfind("\n", 0, inc.start()) + 1
            indent = inner[line_start:inc.start()]
            indent = indent[:len(indent) - len(indent.lstrip(" \t"))]
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
        # Atomic: a truncated Font.xml breaks the skin (see core.files).
        try:
            atomic_write(font_xml_path, updated.encode("utf-8"))
        except OSError as exc:
            _log(f"installxml: cannot write Font.xml: {exc}", xbmc.LOGERROR)
            return False
        _log(f"Font.xml written: {font_xml_path}")

    return modified


def _install_fonts() -> None:
    """Fully check the skin's Font.xml files and add missing entries.

    Sets ``PROP_FONTS_READY`` when all are complete, or ``PROP_FONTS_FAILED``
    when a file is missing or cannot be updated; ``ensure_fonts()`` skips
    the work while either mark holds.  Call with ``_install_lock`` held.
    """
    home     = home_window()
    skin_dir = xbmc.getSkinDir()
    home.clearProperty(PROP_FONTS_READY)
    home.clearProperty(PROP_FONTS_FAILED)

    # Not remembered as a failure: the skin may still be loading.
    skin_path = _get_skin_path()
    if not skin_path:
        _log("Skin path not found", xbmc.LOGWARNING)
        return

    _log(f"Skin path: {skin_path}")

    # Located once for both steps; this is the most expensive part.
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

    # Mark the files as they are after the writes.
    _remember(home, skin_dir, font_xmls,
              PROP_FONTS_FAILED if failed else PROP_FONTS_READY)
    if not written:
        return
    with contextlib.suppress(Exception):
        xbmc.executebuiltin("ReloadSkin(reload)")


def _remember(home: PropertyTarget, skin_dir: str, font_xmls: Sequence[str],
              prop: str = PROP_FONTS_READY) -> None:
    """Set mark *prop* for *font_xmls* (ready or failed)."""
    try:
        home.setProperty(prop, _mark(skin_dir, font_xmls))
    except OSError as exc:
        # No mark; the next launch checks in full.
        _log(f"cannot stat Font.xml: {exc}", xbmc.LOGWARNING)


def _mark(skin_dir: str, font_xmls: Sequence[str]) -> str:
    """Return a mark describing *font_xmls* as they are now.

    Raises OSError when a file is gone.
    """
    parts = [skin_dir, settings.addon().getAddonInfo("version")]
    for font_xml_path in font_xmls:
        stat = os.stat(font_xml_path)
        parts += (font_xml_path, repr(stat.st_mtime), str(stat.st_size))
    return _MARK_SEPARATOR.join(parts)


def _mark_holds(prop: str = PROP_FONTS_READY) -> bool:
    """Return whether mark *prop* still matches the active skin.

    One stat per known file.  The mark lapses when the skin, the add-on
    version or any Font.xml changes.
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
    """Return whether the last check's result (ready or failed) still holds."""
    return _mark_holds(PROP_FONTS_READY) or _mark_holds(PROP_FONTS_FAILED)


def ensure_fonts() -> None:
    """Make sure the overlay's font entries are registered, cheaply.

    Normally the service has done this, so the check is one property read
    and a stat.  Otherwise the full check runs once; an unwritable skin is
    also only checked once.
    """
    if _settled():
        return
    with _install_lock:
        # Re-check: the other caller may have just done it.
        if _settled():
            return
        _install_fonts()
