"""Install the required fonts into the active Kodi skin.

Runs install_fonts() on import so fonts are ready before the overlay opens;
FontInstallMonitor re-runs it on skin change or Kodi update.
"""

import os
import re
import shutil
import traceback
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon

_ADDON     = xbmcaddon.Addon()
_ADDON_DIR = _ADDON.getAddonInfo("path")

_ADDONS_ROOT = os.path.dirname(os.path.dirname(_ADDON_DIR))

_REQUIRED_FONTS = (
    {"name": "font23_narrow", "filename": "Noto-Regular.ttf", "size": "21"},
    {"name": "font32",        "filename": "Noto-Bold.ttf",    "size": "32"},
)

# Fonts ship in the tools.tinyppi addon; resolve defensively so a missing
# tools addon never breaks import.
try:
    _TOOLS_DIR = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
except Exception:
    _TOOLS_DIR = ""

_ADDON_FONTS_DIR = (os.path.normpath(os.path.join(_TOOLS_DIR, "tools", "fonts"))
                    if _TOOLS_DIR else "")


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


def _find_ttf_dir(skin_path: str) -> str | None:
    """Return the first directory under *skin_path* that contains a .ttf file."""
    for root, _dirs, files in os.walk(skin_path):
        if any(fname.lower().endswith(".ttf") for fname in files):
            return root
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


def _registered_fonts(xml_root) -> set[tuple[str, str]]:
    """Return a set of (name, filename) pairs already present in Font.xml."""
    registered: set[tuple[str, str]] = set()
    for font in xml_root.findall(".//font"):
        name_el     = font.find("name")
        filename_el = font.find("filename")
        name = (name_el.text or "").strip() if name_el is not None else ""
        filename = (filename_el.text or "").strip() if filename_el is not None else ""
        if name and filename:
            registered.add((name, filename))
    return registered


def fonts_already_installed(skin_path: str) -> bool:
    """Return True only when every required font is in Font.xml and on disk."""
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
        for font_spec in _REQUIRED_FONTS:
            if (font_spec["name"], font_spec["filename"]) not in registered:
                _log(
                    f"XML entry missing: {font_spec['name']} "
                    f'in fontset "{fontset.get("id", "?")}"'
                )
                return False

    ttf_dest_dir = _find_ttf_dir(skin_path)
    if not ttf_dest_dir:
        _log("No TTF directory found", xbmc.LOGWARNING)
        return False

    for _root, _dirs, files in os.walk(_ADDON_FONTS_DIR):
        for fname in files:
            dest = os.path.normpath(os.path.join(ttf_dest_dir, fname))
            if not os.path.exists(dest):
                _log(f"TTF missing: {fname}")
                return False

    return True


# Text-based editing preserves the file byte-for-byte apart from the inserted
# entries: the original XML declaration, encoding, blank lines and line endings
# stay untouched (ElementTree would rewrite all of these on re-serialisation).
_FONTSET_RE = re.compile(r"(<fontset\b[^>]*>)(.*?)(</fontset>)", re.DOTALL)
_INCLUDE_RE = re.compile(r"<include\b.*?(?:/>|</include>)", re.DOTALL)
_ID_RE      = re.compile(r'\bid\s*=\s*"([^"]*)"')


def _fontset_has(inner: str, spec: dict) -> bool:
    """True if *inner* (a fontset body) already declares this font."""
    name_ok = re.search(r"<name>\s*" + re.escape(spec["name"]) + r"\s*</name>",
                        inner)
    file_ok = re.search(r"<filename>\s*" + re.escape(spec["filename"])
                        + r"\s*</filename>", inner)
    return bool(name_ok and file_ok)


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

    Works purely on the file text so nothing outside the inserted <font>
    blocks is altered.
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

        # Insert right after the <include> element; derive the child indent
        # from the include line so it matches the surrounding formatting.
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


def _install_ttf(skin_path: str) -> bool:
    """Copy missing .ttf files into the skin; True if any file was copied."""
    ttf_dest_dir = _find_ttf_dir(skin_path)
    if not ttf_dest_dir:
        _log("installttf: no TTF destination directory", xbmc.LOGWARNING)
        return False

    _log(f"TTF source: {_ADDON_FONTS_DIR}")
    _log(f"TTF target: {ttf_dest_dir}")

    modified = False
    for _root, _dirs, files in os.walk(_ADDON_FONTS_DIR):
        for fname in files:
            src  = os.path.normpath(os.path.join(_root, fname))
            dest = os.path.normpath(os.path.join(ttf_dest_dir, fname))
            if not os.path.exists(dest):
                shutil.copy(src, dest)
                _log(f"TTF copied: {fname}")
                modified = True
            else:
                _log(f"TTF already exists: {fname}")

    return modified


def install_fonts() -> None:
    """Install missing fonts into the active skin, reloading it if anything
    changed.  No-op when the fonts are already installed."""
    skin_path = _get_skin_path()
    if not skin_path:
        _log("Skin path not found", xbmc.LOGWARNING)
        return

    _log(f"Skin path: {skin_path}")

    if fonts_already_installed(skin_path):
        _log("All fonts already installed – skipping")
        return

    try:
        xml_modified = _install_xml(skin_path)
        ttf_modified = _install_ttf(skin_path)
    except Exception as exc:
        _log(f"Installation error: {exc}", xbmc.LOGERROR)
        _log(traceback.format_exc(), xbmc.LOGERROR)
        return

    if xml_modified or ttf_modified:
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


_monitor = FontInstallMonitor()
install_fonts()
