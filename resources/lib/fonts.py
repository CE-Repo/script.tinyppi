"""
fonts.py – Install required fonts into the active Kodi skin.

On import the module immediately calls ``install_fonts()`` so that fonts are
available before TinyPPI opens its overlay window.  The ``FontInstallMonitor``
class re-runs the installation whenever the skin changes or Kodi is updated.
"""

import os
import shutil
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON     = xbmcaddon.Addon()
_ADDON_DIR = _ADDON.getAddonInfo("path")

_ADDONS_ROOT = os.path.dirname(os.path.dirname(_ADDON_DIR))

_REQUIRED_FONTS = [
    {"name": "font23_narrow", "filename": "Inter-Regular.ttf", "size": "21"},
    {"name": "font32",        "filename": "Inter-Bold.ttf",    "size": "32"},
]

_ADDON_FONTS_DIR = os.path.normpath(os.path.join(_ADDON_DIR, "fonts"))

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
        if any(f.endswith(".ttf") for f in files):
            return root
    return None


def _get_skin_path() -> str | None:
    """
    Return the filesystem path of the currently active Kodi skin.

    Checks the user addons directory first, then the system addons directory.
    """
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
        if name_el is not None and filename_el is not None:
            registered.add((name_el.text.strip(), filename_el.text.strip()))
    return registered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fonts_already_installed(skin_path: str) -> bool:
    """
    Return True only when ALL required fonts are present both in Font.xml
    and as .ttf files on disk.
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

    registered = _registered_fonts(xml_root)

    for f in _REQUIRED_FONTS:
        if (f["name"], f["filename"]) not in registered:
            _log(f"XML entry missing: {f['name']}")
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


def _install_xml(skin_path: str) -> bool:
    """
    Insert missing font entries into every ``<fontset>`` block in Font.xml.

    Returns True when at least one entry was written.
    """
    font_xml_path = _find_font_xml(skin_path)
    if not font_xml_path:
        _log("installxml: Font.xml not found", xbmc.LOGERROR)
        return False

    tree     = ET.parse(font_xml_path)
    xml_root = tree.getroot()
    registered = _registered_fonts(xml_root)
    modified = False

    for fontset in xml_root.findall("fontset"):
        fset_id    = fontset.get("id", "?")
        include_el = fontset.find("include")

        insert_idx = (list(fontset).index(include_el) + 1
                      if include_el is not None
                      else len(list(fontset)))

        _log(f'Editing fontset "{fset_id}", insert index: {insert_idx}')

        for f in _REQUIRED_FONTS:
            key = (f["name"], f["filename"])
            if key in registered:
                continue
            el = ET.Element("font")
            ET.SubElement(el, "name").text     = f["name"]
            ET.SubElement(el, "filename").text = f["filename"]
            ET.SubElement(el, "size").text     = f["size"]
            fontset.insert(insert_idx, el)
            insert_idx += 1
            registered.add(key)
            modified = True
            _log(f'Font inserted: {f["name"]} in fontset "{fset_id}"')

    if modified:
        try:
            ET.indent(tree, space="    ")
        except AttributeError:
            pass
        tree.write(font_xml_path, encoding="utf-8", xml_declaration=True)
        _log(f"Font.xml written: {font_xml_path}")

    return modified


def _install_ttf(skin_path: str) -> bool:
    """
    Copy missing .ttf files from the addon fonts directory into the skin.

    Returns True when at least one file was copied.
    """
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
    """
    Install all required fonts into the active Kodi skin.

    A ``ReloadSkin`` is triggered automatically when any file was changed.
    Does nothing when fonts are already fully installed.
    """
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
        import traceback
        _log(traceback.format_exc(), xbmc.LOGERROR)
        return

    if xml_modified or ttf_modified:
        try:
            xbmc.executebuiltin("ReloadSkin(reload)")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Monitor  (re-installs on skin change or system update)
# ---------------------------------------------------------------------------

class FontInstallMonitor(xbmc.Monitor):
    """Re-run font installation whenever the active skin or Kodi itself changes."""

    def onSkinChanged(self) -> None:
        _log("Skin changed – checking fonts")
        xbmc.sleep(500)
        install_fonts()

    def onNotification(self, sender: str, method: str, data: str) -> None:
        if method == "System.OnUpdated":
            _log("System.OnUpdated – checking fonts")
            install_fonts()


# ---------------------------------------------------------------------------
# Run on import
# ---------------------------------------------------------------------------

_monitor = FontInstallMonitor()
install_fonts()
