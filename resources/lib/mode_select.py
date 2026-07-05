"""
mode_select.py – VS10-mode selection dialog for TinyPPI.

Open via ``RunScript(script.tinyppi,dialog)`` or programmatically:

    from mode_select import open_dialog
    open_dialog()
"""

import threading
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
_PROP_RUNNING = "TinyPPI.Running"
_PROP_ACTIVE = "TinyPPI.Active"

# ---------------------------------------------------------------------------
# Sysfs
# ---------------------------------------------------------------------------

def _w(path: str, value: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
        xbmc.log(f"TinyPPI: {path} = {value}", xbmc.LOGINFO)
    except OSError as e:
        xbmc.log(f"TinyPPI: FAILED {path}: {e}", xbmc.LOGERROR)


def _delay(ms: int) -> None:
    try:
        xbmc.sleep(ms)
    except Exception:
        time.sleep(ms / 1000)


def _write_sequence(
    steps: tuple[tuple[str, str], ...],
    delay_ms: int = 100,
) -> None:
    """Write a sysfs sequence, waiting between steps when requested."""
    for index, (path, value) in enumerate(steps):
        if index and delay_ms > 0:
            _delay(delay_ms)
        _w(path, value)


def _set_passthrough_mode(dv_mode: str, delay_ms: int = 100) -> None:
    """Set the CoreELEC policy and enable Dolby Vision in the requested mode."""
    _write_sequence(
        (
            (_POLICY, "2"),
            (_ENABLE, "Y"),
            (_DVMODE, dv_mode),
        ),
        delay_ms=delay_ms,
    )


def _set_sdr_conversion_mode(dv_mode: str) -> None:
    """Reset to SDR first, then enable the requested conversion mode."""
    _write_sequence(
        (
            (_POLICY, "2"),
            (_DVMODE, "0"),
            (_ENABLE, "Y"),
            (_DVMODE, dv_mode),
        )
    )


def _clear_overlay_state(home) -> None:
    """Allow the main TinyPPI overlay to open after closing this dialog."""
    home.clearProperty(_PROP_RUNNING)
    home.clearProperty(_PROP_ACTIVE)


# ---------------------------------------------------------------------------
# VS10 Mode
# ---------------------------------------------------------------------------

def original_sdr() -> None:
    _set_passthrough_mode("0", delay_ms=0)


def hdr10() -> None:
    _set_sdr_conversion_mode("3")


def dv() -> None:
    _set_passthrough_mode("2")


def original_hdr() -> None:
    _set_passthrough_mode("3")


def original_hlg() -> None:
    # Native HLG: HLG is not a supported VS10 *input*, so with the core
    # enabled (even in BYPASS) no output-mode switch happens.  Turn VS10 off
    # (policy=follow-source, enable=N) so HLG passes through the standard HDR
    # path untouched.
    _write_sequence(
        (
            (_POLICY, "0"),
            (_ENABLE, "N"),
        )
    )


def original_dv() -> None:
    _set_passthrough_mode("2")


def sdr8() -> None:
    _set_sdr_conversion_mode("5")


def sdr10() -> None:
    _set_sdr_conversion_mode("4")


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

_MODES = {
    "original_sdr": original_sdr,
    "hdr10": hdr10,
    "dv": dv,
    "original_hdr": original_hdr,
    "original_hlg": original_hlg,
    "original_dv": original_dv,
    "sdr8": sdr8,
    "sdr10": sdr10,
}


def set_mode(name: str) -> None:
    fn = _MODES.get(name)
    if fn:
        fn()
        xbmc.log(f"TinyPPI: mode set -> {name}", xbmc.LOGINFO)
    else:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)


def run_mode(mode: str) -> None:
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
    # HDR10
    1005: original_hdr,
    1006: sdr8,
    1008: dv,
    # HLG (Original bypasses VS10 so HLG stays HLG)
    1009: original_hlg,
    1010: sdr8,
    1011: dv,
    # DV
    1012: original_dv,
    1013: sdr8,
}

# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(xbmcgui.WindowXMLDialog):
    """
    Simple menu dialog that lets the user choose a VS10 output mode or
    launch the main TinyPPI overlay.
    """

    def onInit(self) -> None:
        # The SDR / HDR10 / Dolby Vision groups branch on TinyPPI.HdrType, which
        # is filled by hdrprobe in the background.  Refresh it while the dialog
        # is open so the correct group appears as soon as detection completes.
        self._running = True
        self._monitor = xbmc.Monitor()
        threading.Thread(target=self._hdr_type_loop, daemon=True).start()

    def _hdr_type_loop(self) -> None:
        from properties import publish_hdr_type

        home = xbmcgui.Window(10000)
        while self._running and not self._monitor.abortRequested():
            publish_hdr_type(home)
            if self._monitor.waitForAbort(0.5):
                break

    def close(self) -> None:
        self._running = False
        super().close()

    def onClick(self, control_id: int) -> None:
        if control_id == _BTN_TINYPPI:
            self.close()
            _clear_overlay_state(xbmcgui.Window(10000))
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
