# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Register the overlay's font sizes in the active Kodi skin.

The overlay lays out against two specific sizes (21 for the metadata rows, 32
for the headers), so it registers them in the skin's Font.xml under its own
names.  Both name ``arial.ttf``, which Kodi distributes itself -- nothing is
copied into the skin, so there is no font file that can go missing or drift out
of sync with the entry that names it.

Runs install_fonts() on import so the entries are in place before the overlay
opens; FontInstallMonitor re-runs it on skin change or Kodi update.
"""

import os
import re
import traceback

import xbmc
import xbmcaddon

_ADDON     = xbmcaddon.Addon()
_ADDON_DIR = _ADDON.getAddonInfo("path")

_ADDONS_ROOT = os.path.dirname(os.path.dirname(_ADDON_DIR))

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



def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _find_font_xml(skin_path: str) -> str | None:
    """Return the path to Font.xml inside *skin_path*, or None if absent."""
    for root, _dirs, files in os.walk(skin_path):
        for fname in files:
            if fname.lower() == "font.xml":
                found = os.path.normpath(os.path.join(root, fname))
                _log(f"Font.xml found: {found}")
                return found
    _log(f"No Font.xml in: {skin_path}", xbmc.LOGWARNING)
    return None


def _get_skin_path() -> str | None:
    """Return the active Kodi skin path (user addons dir first, then system)."""
    skin_dir   = xbmc.getSkinDir()
    local_path = os.path.normpath(os.path.join(_ADDONS_ROOT, skin_dir))
    sys_path   = os.path.normpath(os.path.join(os.getcwd(), "addons", skin_dir))

    _log(f"Skin local: {local_path}")
    _log(f"Skin sys:   {sys_path}")

    if os.path.exists(local_path):
        return local_path
    if os.path.exists(sys_path):
        return sys_path
    return None


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


def _fontset_has(inner: str, spec: dict) -> bool:
    """True if *inner* (a fontset body) already declares this exact font.

    Name, file and size have to meet inside one <font> block.  Matching them
    anywhere in the fontset would pair this addon's font name with an unrelated
    entry's font file -- names like ``font32`` are common in skins -- and skip
    an insert the overlay needs.
    """
    target = _spec_entry(spec)
    return any(_block_entry(block) == target for block in _FONT_RE.findall(inner))


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


def fonts_already_installed(skin_path: str) -> bool:
    """Return True only when every required font is registered in Font.xml.

    Nothing is checked on disk: the file named is Kodi's own ``arial.ttf``,
    which it locates through its own search path, and substitutes for itself
    when it cannot.

    The size is part of a font's identity here, not just its name and file:
    ``arial.ttf`` and a name like ``font32`` are common enough in skins that a
    match on those two alone would report a font as present at a size the
    overlay never asked for, and its rows would be laid out against the wrong
    metrics.  That is _fontset_has's rule, which is also the one _install_xml
    picks its inserts by.
    """
    font_xml_path = _find_font_xml(skin_path)
    if not font_xml_path:
        return False

    original = _read_font_xml(font_xml_path)
    if original is None:
        return False

    # Every fontset must carry all required fonts, not just the first.
    fontsets = _FONTSET_RE.findall(original)
    if not fontsets:
        return False

    for open_tag, inner, _close_tag in fontsets:
        fset_id = _fontset_id(open_tag)
        for font_spec in _REQUIRED_FONTS:
            if not _fontset_has(inner, font_spec):
                _log(f'XML entry missing: {font_spec["name"]} '
                     f'in fontset "{fset_id}"')
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


def _install_xml(skin_path: str) -> bool:
    """Insert missing font entries into every <fontset>; True if any written.

    Nothing already in the file is edited or removed -- the entries go in ahead
    of it, where Kodi reads them first.  Works purely on the file text so
    nothing outside the inserted <font> blocks is altered.
    """
    font_xml_path = _find_font_xml(skin_path)
    if not font_xml_path:
        _log("installxml: Font.xml not found", xbmc.LOGERROR)
        return False

    original = _read_font_xml(font_xml_path)
    if original is None:
        return False

    nl = "\r\n" if "\r\n" in original else "\n"
    modified = False

    def _process(match: "re.Match") -> str:
        nonlocal modified
        open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)
        fset_id = _fontset_id(open_tag)

        missing = [s for s in _REQUIRED_FONTS if not _fontset_has(inner, s)]
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
        try:
            with open(font_xml_path, "wb") as fh:
                fh.write(updated.encode("utf-8"))
        except OSError as exc:
            _log(f"installxml: cannot write Font.xml: {exc}", xbmc.LOGERROR)
            return False
        _log(f"Font.xml written: {font_xml_path}")

    return modified


def install_fonts() -> None:
    """Register the missing font entries in the active skin, reloading it if
    anything changed.  No-op when they are already there."""
    skin_path = _get_skin_path()
    if not skin_path:
        _log("Skin path not found", xbmc.LOGWARNING)
        return

    _log(f"Skin path: {skin_path}")

    if fonts_already_installed(skin_path):
        _log("All fonts already registered – skipping")
        return

    try:
        modified = _install_xml(skin_path)
    except Exception as exc:
        _log(f"Installation error: {exc}", xbmc.LOGERROR)
        _log(traceback.format_exc(), xbmc.LOGERROR)
        return

    if modified:
        try:
            xbmc.executebuiltin("ReloadSkin(reload)")
        except Exception:
            pass


class FontInstallMonitor(xbmc.Monitor):
    """Re-run font installation when the active skin or Kodi changes."""

    def onSkinChanged(self) -> None:
        _log("Skin changed – checking fonts")
        xbmc.sleep(500)
        install_fonts()

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if method == "System.OnUpdated":
            _log("System.OnUpdated – checking fonts")
            install_fonts()


# Kept in a module global rather than discarded: the name is the only reference
# to the monitor, and without it the instance is collected and stops listening.
_monitor = FontInstallMonitor()
install_fonts()
