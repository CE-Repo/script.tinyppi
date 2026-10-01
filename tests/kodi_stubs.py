# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-ins for the modules Kodi provides to an add-on.

Just enough of ``xbmc``, ``xbmcgui``, ``xbmcaddon`` and ``xbmcvfs`` to import
the add-on's own code outside Kodi and drive the parts of it that are plain
logic.  Anything a test does not set up answers the way an idle Kodi would:
nothing playing, no InfoLabel, every setting at its empty default.
"""

import os
import re
import sys
import tempfile
import time
import types
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ID = "script.tinyppi"


def _addon_version() -> str:
    with open(os.path.join(REPO, "addon.xml"), encoding="utf-8") as handle:
        return re.search(r'<addon\b[^>]*\bversion="([^"]+)"', handle.read()).group(1)


class State:
    """What the stubs answer with; reset before every test (see conftest)."""

    def __init__(self) -> None:
        root = tempfile.mkdtemp(prefix="tinyppi-kodi-")
        self.root       = root
        self.special    = {
            "special://profile/": os.path.join(root, "profile") + os.sep,
            "special://home/":    os.path.join(root, "home") + os.sep,
            "special://skin/":    os.path.join(root, "skin") + os.sep,
            "special://xbmc/":    os.path.join(root, "xbmc") + os.sep,
            "special://temp/":    os.path.join(root, "temp") + os.sep,
        }
        self.settings   = {}
        self.properties = {}
        self.logged     = []
        self.builtins   = []
        self.skin_dir   = "skin.test"
        self.abort      = False


state = State()


# --- xbmc ----------------------------------------------------------------------

xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING = 0, 1, 2
xbmc.LOGERROR, xbmc.LOGFATAL, xbmc.LOGNONE   = 3, 4, 5


def _log(message, level=xbmc.LOGDEBUG):
    state.logged.append((message, level))


def _translate(path):
    for prefix, target in state.special.items():
        if path.startswith(prefix):
            return target + path[len(prefix):]
    return path


class Monitor:
    def __init__(self, *args, **kwargs):
        pass

    def abortRequested(self):
        return state.abort

    def waitForAbort(self, timeout=None):
        if timeout:
            time.sleep(min(timeout, 0.01))
        return state.abort


class Player:
    def __init__(self, *args, **kwargs):
        pass

    def isPlaying(self):
        return False

    def isPlayingVideo(self):
        return False


xbmc.log               = _log
xbmc.translatePath     = _translate
xbmc.getCondVisibility = lambda condition: False
xbmc.getInfoLabel      = lambda label: ""
xbmc.getLocalizedString = lambda string_id: ""
xbmc.getSkinDir        = lambda: state.skin_dir
xbmc.executebuiltin    = lambda command, wait=False: state.builtins.append(command)
xbmc.executeJSONRPC    = lambda request: '{"id": 1, "jsonrpc": "2.0", "error": {}}'
xbmc.sleep             = lambda ms: time.sleep(ms / 1000)
xbmc.Monitor           = Monitor
xbmc.Player            = Player


# --- xbmcgui -------------------------------------------------------------------

xbmcgui = types.ModuleType("xbmcgui")


class Window:
    """Window properties, kept per window id for as long as a test runs."""

    def __init__(self, window_id=0):
        self._props = state.properties.setdefault(window_id, {})

    def getProperty(self, key):
        return self._props.get(key.lower(), "")

    def setProperty(self, key, value):
        self._props[key.lower()] = str(value)

    def clearProperty(self, key):
        self._props.pop(key.lower(), None)

    def clearProperties(self):
        self._props.clear()

    def getControl(self, control_id):
        return mock.MagicMock()


class _Dialog(Window):
    def __init__(self, *args, **kwargs):
        super().__init__(-1)

    def doModal(self):
        pass

    def show(self):
        pass

    def close(self):
        pass


xbmcgui.Window          = Window
xbmcgui.WindowDialog    = _Dialog
xbmcgui.WindowXML       = _Dialog
xbmcgui.WindowXMLDialog = _Dialog
xbmcgui.ListItem        = mock.MagicMock
xbmcgui.Dialog          = mock.MagicMock
xbmcgui.Action          = mock.MagicMock
xbmcgui.NOTIFICATION_INFO    = "info"
xbmcgui.NOTIFICATION_WARNING = "warning"
xbmcgui.NOTIFICATION_ERROR   = "error"


_GUI_CONSTANTS: dict = {}


def _gui_fallback(name):
    # The ACTION_* and the like: distinct numbers are all any code here needs.
    if name.isupper():
        return _GUI_CONSTANTS.setdefault(name, 90000 + len(_GUI_CONSTANTS))
    # The control classes (ControlImage, ControlLabel, ...).
    if name[:1].isupper():
        return mock.MagicMock
    raise AttributeError(name)


xbmcgui.__getattr__ = _gui_fallback


# --- xbmcaddon -----------------------------------------------------------------

xbmcaddon = types.ModuleType("xbmcaddon")


class Addon:
    def __init__(self, addon_id=None):
        self._id = addon_id or ADDON_ID

    def getAddonInfo(self, key):
        return {
            "id":      self._id,
            "name":    "TinyPPI",
            "path":    REPO,
            "profile": f"special://profile/addon_data/{self._id}/",
            "version": _addon_version(),
        }.get(key, "")

    def getSetting(self, key):
        return str(state.settings.get(key, ""))

    def getSettingBool(self, key):
        return self.getSetting(key) == "true"

    def getSettingInt(self, key):
        try:
            return int(self.getSetting(key))
        except ValueError:
            return 0

    def getSettingString(self, key):
        return self.getSetting(key)

    def setSetting(self, key, value):
        state.settings[key] = str(value)

    def getLocalizedString(self, string_id):
        return ""

    def openSettings(self):
        pass


xbmcaddon.Addon = Addon


# --- xbmcvfs -------------------------------------------------------------------

xbmcvfs = types.ModuleType("xbmcvfs")


class File:
    def __init__(self, path, mode="r"):
        self._handle = open(_translate(path), "wb" if "w" in mode else "rb")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def read(self, size=-1):
        return self._handle.read(size).decode("utf-8", errors="replace")

    def readBytes(self, size=-1):
        return bytearray(self._handle.read(size))

    def write(self, data):
        self._handle.write(data.encode("utf-8") if isinstance(data, str) else data)
        return True

    def close(self):
        self._handle.close()


xbmcvfs.File          = File
xbmcvfs.translatePath = _translate
xbmcvfs.exists        = lambda path: os.path.exists(_translate(path))
xbmcvfs.mkdirs        = lambda path: os.makedirs(_translate(path), exist_ok=True) or True


def install() -> None:
    """Put the stand-ins where ``import xbmc`` and friends will find them, and
    the add-on's own packages on the path."""
    for module in (xbmc, xbmcgui, xbmcaddon, xbmcvfs):
        sys.modules.setdefault(module.__name__, module)
    lib = os.path.join(REPO, "resources", "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)


def reset() -> None:
    """Start the next test from an idle Kodi again."""
    global state
    fresh = State()
    state.__dict__.update(fresh.__dict__)
    for path in fresh.special.values():
        os.makedirs(path, exist_ok=True)
