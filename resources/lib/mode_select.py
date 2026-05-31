"""
mode_select.py – VS10-mode selection dialog for TinyPPI.

Open via ``RunScript(script.tinyppi,dialog)`` or programmatically:

    from mode_select import open_dialog
    open_dialog()
"""

import time
import xbmc
import xbmcaddon
import xbmcgui

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_POLICY = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE = "/sys/class/amdolby_vision/dv_mode"

_BTN_TINYPPI = 1001

# ---------------------------------------------------------------------------
# Sysfs
# ---------------------------------------------------------------------------

def _w(path: str, value: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(value)
        xbmc.log(f"TinyPPI: {path} = {value}", xbmc.LOGINFO)
    except OSError as e:
        xbmc.log(f"TinyPPI: FAILED {path}: {e}", xbmc.LOGERROR)


def _delay(ms: int):
    try:
        xbmc.sleep(ms)
    except Exception:
        time.sleep(ms / 1000)

# ---------------------------------------------------------------------------
# VS10 Mode
# ---------------------------------------------------------------------------

def original_sdr():
    _w(_POLICY, "2"); _w(_ENABLE, "Y"); _w(_DVMODE, "0")

def hdr10():
    _w(_POLICY, "2"); _delay(100); _w(_DVMODE, "0"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "3")

def dv():
    _w(_POLICY, "2"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "2")

def original_hdr():
    _w(_POLICY, "2"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "3")

def original_dv():
    _w(_POLICY, "2"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "2")

def sdr8():
    _w(_POLICY, "2"); _delay(100); _w(_DVMODE, "0"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "5")

def sdr10():
    _w(_POLICY, "2"); _delay(100); _w(_DVMODE, "0"); _delay(100); _w(_ENABLE, "Y"); _delay(100); _w(_DVMODE, "4")


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

_MODES = {
    "original_sdr": original_sdr,
    "hdr10": hdr10,
    "dv": dv,
    "original_hdr": original_hdr,
    "original_dv": original_dv,
    "sdr8": sdr8,
    "sdr10": sdr10,
}

def set_mode(name: str):
    fn = _MODES.get(name)
    if fn:
        fn()
        xbmc.log(f"TinyPPI: mode set -> {name}", xbmc.LOGINFO)
    else:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)


def run_mode(mode: str):
    set_mode(mode)

__all__ = list(_MODES.keys()) + ["open_dialog", "set_mode", "run_mode"]


# ---------------------------------------------------------------------------
# Button-ID
# ---------------------------------------------------------------------------

_ACTIONS = {
    # SDR
    1002: original_sdr,
    1003: hdr10,
    1004: dv,
    # HDR
    1005: original_hdr,
    1006: sdr8,
    1008: dv,
    # DV
    1009: original_dv,
    1010: sdr8,
}

# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(xbmcgui.WindowXMLDialog):
    """
    Simple menu dialog that lets the user choose a VS10 output mode or
    launch the main TinyPPI overlay.
    """

    def onClick(self, control_id: int) -> None:
        if control_id == _BTN_TINYPPI:
            self.close()
            from overlay import open_tinyppi
            open_tinyppi()
            return

        action = _ACTIONS.get(control_id)
        if action:
            action()
            self.close()

    def onAction(self, action: xbmcgui.Action) -> None:
        if action.getId() in (
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_STOP,
        ):
            self.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_dialog() -> None:
    """Create and display the settings/mode-selection dialog modally."""
    win = SettingsDialog(
        "script-tinyppi-dialog.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    win.doModal()
    del win
