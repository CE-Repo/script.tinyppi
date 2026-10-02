# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-in for Kodi's ``xbmcgui`` module (properties, dialogs, controls)."""

ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN = 1, 2, 3, 4
ACTION_SELECT_ITEM, ACTION_PREVIOUS_MENU, ACTION_STOP, ACTION_NAV_BACK = 7, 10, 13, 92
NOTIFICATION_INFO, NOTIFICATION_WARNING, NOTIFICATION_ERROR = "info", "warning", "error"

# Window properties by window id, shared by every Window object.
PROPERTIES: dict[int, dict[str, str]] = {}


class Window:
    def __init__(self, window_id=10000):
        self._props = PROPERTIES.setdefault(window_id, {})

    def getProperty(self, key):
        return self._props.get(key, "")

    def setProperty(self, key, value):
        self._props[key] = value

    def clearProperty(self, key):
        self._props.pop(key, None)


class WindowXML(Window):
    def __init__(self, *args, **kwargs):
        super().__init__(13000)


class WindowXMLDialog(WindowXML):
    pass


class WindowDialog(Window):
    pass


class Action:
    def getId(self):
        return 0

    def getButtonCode(self):
        return 0


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2 = label, label2


class Dialog:
    def notification(self, *args, **kwargs):
        pass

    def ok(self, *args, **kwargs):
        return True

    def textviewer(self, *args, **kwargs):
        pass

    def colorpicker(self, *args, **kwargs):
        return ""

    def input(self, *args, **kwargs):
        return ""


class Control:
    def __init__(self, *args, **kwargs):
        pass


class ControlImage(Control):
    pass


class ControlLabel(Control):
    pass


class ControlGroup(Control):
    pass


class ControlButton(Control):
    pass


def getScreenWidth():
    return 1920


def getScreenHeight():
    return 1080


def getCurrentWindowId():
    return 10000


def getCurrentWindowDialogId():
    return 9999
