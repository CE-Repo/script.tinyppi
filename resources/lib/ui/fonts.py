# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Register the overlay's font sizes in the active Kodi skin.

The overlay lays out against two specific sizes (21 for the metadata rows, 32
for the headers), so it registers them in the skin's Font.xml under its own
names.  Both name ``arial.ttf``, which Kodi distributes itself -- nothing is
copied into the skin, so there is no font file that can go missing or drift out
of sync with the entry that names it.

Nothing runs on import.  The service installs the entries once at Kodi start
and FontInstallMonitor re-runs it on skin change or Kodi update, so by the time
anyone presses the button the work is long done; ``ensure_fonts()`` is what the
overlay calls on its way up, and on the ordinary launch that is a single
window-property read (see PROP_FONTS_READY) rather than a walk of the skin
directory and a parse of its Font.xml.
"""

import os
import re
import traceback

import xbmc
import xbmcaddon
import xbmcgui

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

# Home-window (10000) property naming the skin whose Font.xml has been checked
# and found complete this Kodi session.  Verifying that costs a walk of the skin
# directory for its Font.xml plus a parse of the file, which is far too much to
# put in front of a window the viewer is waiting for -- so it is done once, by
# the service at startup, and every later launch reads this instead.  Kodi drops
# Home-window properties when it exits, so a session always checks once; a skin
# change clears it (see FontInstallMonitor).
PROP_FONTS_READY = "TinyPPI.FontsReady"



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


def fonts_already_installed(skin_path: str, font_xml_path: str = "") -> bool:
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

    Pass *font_xml_path* when the caller has already located the file: finding
    it means walking the skin directory, and install_fonts() does that once for
    the check and the insert together rather than once for each.
    """
    font_xml_path = font_xml_path or _find_font_xml(skin_path)
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


def _install_xml(skin_path: str, font_xml_path: str = "") -> bool:
    """Insert missing font entries into every <fontset>; True if any written.

    Nothing already in the file is edited or removed -- the entries go in ahead
    of it, where Kodi reads them first.  Works purely on the file text so
    nothing outside the inserted <font> blocks is altered.
    """
    font_xml_path = font_xml_path or _find_font_xml(skin_path)
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
    anything changed.  No-op when they are already there.

    Marks the skin as checked (PROP_FONTS_READY) once the entries are known to
    be in place, which is what lets ensure_fonts() skip all of this on every
    later launch.  A check that could not be completed -- no skin path, no
    Font.xml, an unreadable or unwritable file -- leaves the mark off, so the
    next launch tries again instead of trusting a check that never happened.
    """
    home     = xbmcgui.Window(10000)
    skin_dir = xbmc.getSkinDir()
    home.clearProperty(PROP_FONTS_READY)

    skin_path = _get_skin_path()
    if not skin_path:
        _log("Skin path not found", xbmc.LOGWARNING)
        return

    _log(f"Skin path: {skin_path}")

    # Located once and handed to both steps below: the walk that finds it is
    # the most expensive part of the whole check.
    font_xml_path = _find_font_xml(skin_path)
    if not font_xml_path:
        return

    if fonts_already_installed(skin_path, font_xml_path):
        _log("All fonts already registered – skipping")
        home.setProperty(PROP_FONTS_READY, skin_dir)
        return

    try:
        modified = _install_xml(skin_path, font_xml_path)
    except Exception as exc:
        _log(f"Installation error: {exc}", xbmc.LOGERROR)
        _log(traceback.format_exc(), xbmc.LOGERROR)
        return

    if not modified:
        return

    home.setProperty(PROP_FONTS_READY, skin_dir)
    try:
        xbmc.executebuiltin("ReloadSkin(reload)")
    except Exception:
        pass


def ensure_fonts() -> None:
    """Make sure the overlay's font entries are registered, cheaply.

    What the overlay calls on its way up.  The service has normally installed
    them at Kodi start, so the ordinary launch answers out of a single
    window-property read and touches no disk at all; only a session where that
    has not happened -- the service disabled, or a skin changed since -- pays
    for the walk and the parse, and pays for it once.
    """
    if xbmcgui.Window(10000).getProperty(PROP_FONTS_READY) == xbmc.getSkinDir():
        return
    install_fonts()


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


