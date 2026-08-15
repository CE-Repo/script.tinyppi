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
import xml.etree.ElementTree as ET

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


def _registered_fonts(xml_root) -> set[tuple[str, str, str]]:
    """Return the (name, filename, size) of every font already in Font.xml.

    The size is part of the identity, not just the name and file: ``arial.ttf``
    and a name like ``font32`` are common enough in skins that a match on those
    two alone would report a font as present at a size the overlay never asked
    for, and its rows would be laid out against the wrong metrics.
    """
    registered: set[tuple[str, str, str]] = set()
    for font in xml_root.findall(".//font"):
        values = []
        for tag in ("name", "filename", "size"):
            element = font.find(tag)
            values.append(
                (element.text or "").strip() if element is not None else ""
            )
        if all(values):
            registered.add(tuple(values))
    return registered


def fonts_already_installed(skin_path: str) -> bool:
    """Return True only when every required font is registered in Font.xml.

    Nothing is checked on disk: the file named is Kodi's own ``arial.ttf``,
    which it locates through its own search path, and substitutes for itself
    when it cannot.
    """
    font_xml_path = _find_font_xml(skin_path)
    if not font_xml_path:
        return False

    try:
        tree     = ET.parse(font_xml_path)
        xml_root = tree.getroot()
    except ET.ParseError as exc:
        _log(f"XML parse error: {exc}", xbmc.LOGERROR)
        return False

    # Every fontset must carry all required fonts, not just the first.
    fontsets = xml_root.findall("fontset")
    if not fontsets:
        return False

    for fontset in fontsets:
        registered = _registered_fonts(fontset)
        fset_id = fontset.get("id", "?")

        for font_spec in _REQUIRED_FONTS:
            if _spec_entry(font_spec) not in registered:
                _log(f'XML entry missing: {font_spec["name"]} in fontset "{fset_id}"')
                return False

    return True


# Text-based editing preserves the file byte-for-byte apart from the inserted
# entries: the original XML declaration, encoding, blank lines and line endings
# stay untouched (ElementTree would rewrite all of these on re-serialisation).
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

    try:
        with open(font_xml_path, "rb") as fh:
            original = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _log(f"installxml: cannot read Font.xml: {exc}", xbmc.LOGERROR)
        return False

    nl = "\r\n" if "\r\n" in original else "\n"
    modified = False

    def _process(match: "re.Match") -> str:
        nonlocal modified
        open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)
        fset_id = (_ID_RE.search(open_tag).group(1)
                   if _ID_RE.search(open_tag) else "?")

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
