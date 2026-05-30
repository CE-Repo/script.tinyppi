"""
mode_select.py – VS10-mode selection dialog for TinyPPI.

Open via ``RunScript(script.tinyppi,dialog)`` or programmatically:

    from mode_select import open_dialog
    open_dialog()
"""

import xbmc
import xbmcaddon
import xbmcgui

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_BTN_TINYPPI = 1001

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
