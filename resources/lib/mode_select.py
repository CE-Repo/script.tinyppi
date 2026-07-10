"""VS10-mode selection dialog.

Open via ``RunScript(script.tinyppi,dialog)`` or ``open_dialog()``.
"""

import threading
import time
import xbmc
import xbmcaddon
import xbmcgui

from utils import clear_overlay_state

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_POLICY = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE = "/sys/class/amdolby_vision/dv_mode"

_BTN_TINYPPI = 1001


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


def original_sdr() -> None:
    _set_passthrough_mode("0", delay_ms=0)


def hdr10() -> None:
    _set_sdr_conversion_mode("3")


def dv() -> None:
    _set_passthrough_mode("2")


def original_hdr() -> None:
    _set_passthrough_mode("3")


def original_hlg() -> None:
    # HLG is not a valid VS10 input, so turn VS10 off (policy=follow-source,
    # enable=N) to let HLG pass through the standard HDR path untouched.
    _write_sequence(
        (
            (_POLICY, "0"),
            (_ENABLE, "N"),
        )
    )


# Alias of dv; kept as its own name so keymaps can use both.
original_dv = dv


def sdr8() -> None:
    _set_sdr_conversion_mode("5")


def sdr10() -> None:
    _set_sdr_conversion_mode("4")


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
    """Run the VS10 mode named ``name`` (see ``_MODES``), logging the result."""
    fn = _MODES.get(name)
    if fn:
        fn()
        xbmc.log(f"TinyPPI: mode set -> {name}", xbmc.LOGINFO)
    else:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)


__all__ = list(_MODES.keys()) + ["open_dialog", "set_mode"]


# Dialog button id -> action.
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


class SettingsDialog(xbmcgui.WindowXMLDialog):
    """Menu dialog to pick a VS10 output mode or launch the TinyPPI overlay."""

    def onInit(self) -> None:
        # The SDR / HDR10 / DV groups branch on TinyPPI.HdrType, filled by
        # hdrprobe in the background; refresh it so the right group appears
        # once detection completes.
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
            clear_overlay_state(xbmcgui.Window(10000))
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


def open_dialog() -> None:
    """Create and display the mode-selection dialog modally."""
    win = SettingsDialog(
        "script-tinyppi-dialog.xml",
        _ADDON_PATH,
        "Default",
        "1080i",
    )
    win.doModal()
    del win
