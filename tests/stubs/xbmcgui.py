# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-in for Kodi's ``xbmcgui`` module (properties, dialogs, controls).

Controls remember what was done to them (``calls`` and the plain fields
below); dialogs append ``(method, args, kwargs)`` to ``DIALOGS``.
"""

ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN = 1, 2, 3, 4
ACTION_SELECT_ITEM, ACTION_PREVIOUS_MENU, ACTION_STOP, ACTION_NAV_BACK = 7, 10, 13, 92
NOTIFICATION_INFO, NOTIFICATION_WARNING, NOTIFICATION_ERROR = "info", "warning", "error"

# Window properties by window id, shared by every Window object.
PROPERTIES: dict[int, dict[str, str]] = {}
# Every dialog call, in order.
DIALOGS: list[tuple[str, tuple, dict]] = []


class Control:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.control_id = 0
        self.calls: list[tuple[str, tuple]] = []
        self.position: tuple[int, int] | None = None
        self.visible = True
        self.label = ""
        self.height: int | None = None
        self.width: int | None = None
        self.animations: list = []
        self.percent: float | None = None
        self.items: list = []
        self.selected = 0

    def _record(self, name, *args):
        self.calls.append((name, args))

    def getId(self):
        return self.control_id

    def setPosition(self, x, y):
        self._record("setPosition", x, y)
        self.position = (x, y)

    def setVisible(self, visible):
        self._record("setVisible", visible)
        self.visible = visible

    def setLabel(self, label="", *args, **kwargs):
        self._record("setLabel", label)
        self.label = label

    def setHeight(self, height):
        self._record("setHeight", height)
        self.height = height

    def setWidth(self, width):
        self._record("setWidth", width)
        self.width = width

    def setAnimations(self, animations):
        self._record("setAnimations", animations)
        self.animations = list(animations)

    def setPercent(self, percent):
        self._record("setPercent", percent)
        self.percent = percent

    def setImage(self, image, *args):
        self._record("setImage", image)

    def reset(self):
        self._record("reset")
        self.items = []
        self.selected = 0

    def addItems(self, items):
        self._record("addItems", items)
        self.items.extend(items)
        self.selected = 0

    def selectItem(self, index):
        self._record("selectItem", index)
        self.selected = index

    def getSelectedPosition(self):
        return self.selected


class ControlImage(Control):
    pass


class ControlLabel(Control):
    pass


class ControlGroup(Control):
    pass


class ControlButton(Control):
    pass


class Window:
    def __init__(self, window_id=10000):
        self._props = PROPERTIES.setdefault(window_id, {})
        self.controls: dict[int, Control] = {}
        self.added: list[Control] = []
        self.calls: list[tuple[str, tuple]] = []
        self.focus = 0

    def getProperty(self, key):
        return self._props.get(key, "")

    def setProperty(self, key, value):
        self._props[key] = value

    def clearProperty(self, key):
        self._props.pop(key, None)

    def getControl(self, control_id):
        if control_id not in self.controls:
            self.controls[control_id] = Control()
            self.controls[control_id].control_id = control_id
        return self.controls[control_id]

    def addControls(self, controls):
        self.calls.append(("addControls", (controls,)))
        self.added.extend(controls)

    def removeControls(self, controls):
        self.calls.append(("removeControls", (controls,)))
        for control in controls:
            if control in self.added:
                self.added.remove(control)

    def getWidth(self):
        return 1920

    def getHeight(self):
        return 1080

    def setFocusId(self, control_id):
        self.calls.append(("setFocusId", (control_id,)))
        self.focus = control_id

    def getFocusId(self):
        return self.focus

    def show(self):
        self.calls.append(("show", ()))

    def doModal(self):
        self.calls.append(("doModal", ()))

    def close(self):
        self.calls.append(("close", ()))


class WindowXML(Window):
    def __init__(self, *args, **kwargs):
        super().__init__(13000)


class WindowXMLDialog(WindowXML):
    pass


class WindowDialog(Window):
    pass


class Action:
    def __init__(self, action_id=0, button_code=0):
        self._id, self._button = action_id, button_code

    def getId(self):
        return self._id

    def getButtonCode(self):
        return self._button


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2 = label, label2
        self.properties: dict[str, str] = {}

    def getLabel(self):
        return self.label

    def getLabel2(self):
        return self.label2

    def setLabel(self, label):
        self.label = label

    def setLabel2(self, label):
        self.label2 = label

    def setProperty(self, key, value):
        self.properties[key] = value

    def getProperty(self, key):
        return self.properties.get(key, "")


class Dialog:
    def notification(self, *args, **kwargs):
        DIALOGS.append(("notification", args, kwargs))

    def ok(self, *args, **kwargs):
        DIALOGS.append(("ok", args, kwargs))
        return True

    def textviewer(self, *args, **kwargs):
        DIALOGS.append(("textviewer", args, kwargs))

    def colorpicker(self, *args, **kwargs):
        DIALOGS.append(("colorpicker", args, kwargs))
        return ""

    def input(self, *args, **kwargs):
        DIALOGS.append(("input", args, kwargs))
        return ""


def getScreenWidth():
    return 1920


def getScreenHeight():
    return 1080


def getCurrentWindowId():
    return 10000


def getCurrentWindowDialogId():
    return 9999
