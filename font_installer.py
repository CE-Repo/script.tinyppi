import os
import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon()
CWD = ADDON.getAddonInfo('path')
PATHADDONS = os.path.dirname(os.path.dirname(CWD))

modified = False

REQUIRED_FONTS = [
    {'name': 'font23_narrow', 'filename': 'inter-r.ttf',  'size': '21'},
]


def _findFontXml(skinpath):
    """Finds the Fonts.xml (or Font.xml) in the skin directory."""
    for root, dirs, files in os.walk(skinpath):
        for file in files:
            if 'Font' in file and file.endswith('.xml'):
                found = os.path.normpath(os.path.join(root, file))
                xbmc.log(f'[FontInstallMonitor] Font-XML found: {found}', xbmc.LOGINFO)
                return found
    xbmc.log(f'[FontInstallMonitor] No Font-XML in: {skinpath}', xbmc.LOGWARNING)
    return None


def _findTtfDir(skinpath):
    """Returns the directory that already contains .ttf files."""
    for root, dirs, files in os.walk(skinpath):
        for file in files:
            if file.endswith('.ttf'):
                return root
    return None


def fontsAlreadyInstalled(skinpath):
    """
    Returns True only if ALL required fonts are present both in the XML
    and as .ttf files on disk.
    """
    import xml.etree.ElementTree as ET

    fontxmlpath = _findFontXml(skinpath)
    if not fontxmlpath:
        return False

    try:
        tree    = ET.parse(fontxmlpath)
        xmlroot = tree.getroot()
    except ET.ParseError as e:
        xbmc.log(f'[FontInstallMonitor] XML-Parse-Error: {e}', xbmc.LOGERROR)
        return False

    registered = set()
    for font in xmlroot.findall('.//font'):
        name_el     = font.find('name')
        filename_el = font.find('filename')
        if name_el is not None and filename_el is not None:
            registered.add((name_el.text.strip(), filename_el.text.strip()))

    for f in REQUIRED_FONTS:
        if (f['name'], f['filename']) not in registered:
            xbmc.log(f"[FontInstallMonitor] XML entry missed: {f['name']}", xbmc.LOGINFO)
            return False

    ttf_destdir = _findTtfDir(skinpath)
    if not ttf_destdir:
        xbmc.log('[FontInstallMonitor] No TTF directory found', xbmc.LOGWARNING)
        return False

    addon_fonts_dir = os.path.normpath(os.path.join(CWD, 'fonts'))
    for root, dirs, files in os.walk(addon_fonts_dir):
        for file in files:
            dest = os.path.normpath(os.path.join(ttf_destdir, file))
            if not os.path.exists(dest):
                xbmc.log(f'[FontInstallMonitor] TTF missed: {file}', xbmc.LOGINFO)
                return False

    return True


def installFont():
    global modified

    def getSkinPath():
        localpath = os.path.normpath(os.path.join(PATHADDONS, xbmc.getSkinDir()))
        syspath   = os.path.normpath(os.path.join(os.getcwd(), 'addons', xbmc.getSkinDir()))
        xbmc.log(f'[FontInstallMonitor] Skin local: {localpath}', xbmc.LOGINFO)
        xbmc.log(f'[FontInstallMonitor] Skin sys:   {syspath}',   xbmc.LOGINFO)
        if os.path.exists(localpath):
            return localpath
        elif os.path.exists(syspath):
            return syspath
        return None

    skinpath = getSkinPath()
    if not skinpath:
        xbmc.log('[FontInstallMonitor] Skin path not found', xbmc.LOGWARNING)
        return

    xbmc.log(f'[FontInstallMonitor] Skin path: {skinpath}', xbmc.LOGINFO)

    if fontsAlreadyInstalled(skinpath):
        xbmc.log('[FontInstallMonitor] All fonts are already installed – skip installation', xbmc.LOGINFO)
        return

    # ── XML ──────────────────────────────────────────────────────────────────

    def installxml(path):
        import xml.etree.ElementTree as ET

        fontxmlpath = _findFontXml(path)
        if not fontxmlpath:
            xbmc.log('[FontInstallMonitor] installxml: Font-XML not found', xbmc.LOGERROR)
            return

        tree    = ET.parse(fontxmlpath)
        xmlroot = tree.getroot()

        registered = set()
        for font in xmlroot.findall('.//font'):
            name_el     = font.find('name')
            filename_el = font.find('filename')
            if name_el is not None and filename_el is not None:
                registered.add((name_el.text.strip(), filename_el.text.strip()))

        added = False

        for fontset in xmlroot.findall('fontset'):
            fset_id = fontset.get('id', '?')
            include_el = fontset.find('include')

            if include_el is not None:
                insert_idx = list(fontset).index(include_el) + 1
            else:
                insert_idx = len(list(fontset))

            xbmc.log(f'[FontInstallMonitor] Edit fontset "{fset_id}", Insert Index: {insert_idx}', xbmc.LOGINFO)

            for f in REQUIRED_FONTS:
                if (f['name'], f['filename']) not in registered:
                    el = ET.Element('font')
                    ET.SubElement(el, 'name').text     = f['name']
                    ET.SubElement(el, 'filename').text = f['filename']
                    ET.SubElement(el, 'size').text     = f['size']
                    fontset.insert(insert_idx, el)
                    insert_idx += 1
                    registered.add((f['name'], f['filename']))
                    added = True
                    xbmc.log(f"[FontInstallMonitor] Font inserted: {f['name']} in fontset \"{fset_id}\"", xbmc.LOGINFO)

        if added:
            try:
                ET.indent(tree, space='    ')
            except AttributeError:
                pass

            tree.write(fontxmlpath, encoding='utf-8', xml_declaration=True)
            xbmc.log(f'[FontInstallMonitor] XML writen: {fontxmlpath}', xbmc.LOGINFO)

            global modified
            modified = True
        else:
            xbmc.log('[FontInstallMonitor] No new fonts have been added', xbmc.LOGINFO)

    # ── TTF ──────────────────────────────────────────────────────────────────

    def installttf(path):
        import shutil

        ttf_destdir = _findTtfDir(path)
        if not ttf_destdir:
            xbmc.log('[FontInstallMonitor] installttf: No TTF destination directory', xbmc.LOGWARNING)
            return

        addon_fonts_dir = os.path.normpath(os.path.join(CWD, 'fonts'))
        xbmc.log(f'[FontInstallMonitor] TTF source: {addon_fonts_dir}', xbmc.LOGINFO)
        xbmc.log(f'[FontInstallMonitor] TTF target: {ttf_destdir}', xbmc.LOGINFO)

        for root, dirs, files in os.walk(addon_fonts_dir):
            for file in files:
                src  = os.path.normpath(os.path.join(root, file))
                dest = os.path.normpath(os.path.join(ttf_destdir, file))
                if not os.path.exists(dest):
                    shutil.copy(src, dest)
                    xbmc.log(f'[FontInstallMonitor] TTF copied: {file}', xbmc.LOGINFO)
                    global modified
                    modified = True
                else:
                    xbmc.log(f'[FontInstallMonitor] TTF already exists: {file}', xbmc.LOGINFO)

    # ── Run ──────────────────────────────────────────────────────────────────

    try:
        installxml(skinpath)
        installttf(skinpath)
    except Exception as e:
        xbmc.log(f'[FontInstallMonitor] Installation error: {e}', xbmc.LOGERROR)
        import traceback
        xbmc.log(traceback.format_exc(), xbmc.LOGERROR)

    try: 
        if modified:
            xbmc.executebuiltin('ReloadSkin(reload)')
    except Exception: 
        pass


# ─── Monitor ──────────────────────────────────────────────────────────────────

class FontInstallMonitor(xbmc.Monitor):

    def onNotification(self, sender, method, data):
        if method == 'System.OnUpdated':
            xbmc.log('[FontInstallMonitor] System.OnUpdated – Check fonts', xbmc.LOGINFO)
            self._reinstall()

    def onSkinChanged(self):
        xbmc.log('[FontInstallMonitor] Skin changed – Check fonts', xbmc.LOGINFO)
        xbmc.sleep(500)
        self._reinstall()

    def _reinstall(self):
        global modified
        modified = False
        installFont()


_monitor = FontInstallMonitor()

# ─── Initial call ─────────────────────────────────────────────────────────────

installFont()
