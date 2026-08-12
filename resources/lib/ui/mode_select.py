"""VS10-mode selection dialog.

Open via ``RunScript(script.tinyppi,dialog)`` or ``open_dialog()``.
"""

import json
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core.utils import clear_overlay_state

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_POLICY = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE = "/sys/class/amdolby_vision/dv_mode"

# One of the settings introduced alongside the native VS10 keymap actions in
# SamuriHL/coreelec-xbmc commit 7df0943. Both were added in the same change, so
# its presence over JSON-RPC tells us the running Kodi build ships the VS10
# output engine (and therefore the vs10.* actions).
_VS10_PROBE_SETTING = "coreelec.amlogic.dolbyvision.vs10.dv"

# Cached result of the one-time capability probe (None = not yet probed).
_vs10_actions = None

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


def _read(path: str):
    """Read a sysfs node, returning its stripped contents or None on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _dv_state():
    """Snapshot the DV driver nodes, used to tell whether a native action took."""
    return (_read(_POLICY), _read(_ENABLE), _read(_DVMODE))


def _wait_for_dv_change(before, timeout_ms: int = 500, step_ms: int = 50) -> bool:
    """Poll the DV driver state, returning True once it differs from ``before``."""
    waited = 0
    while waited < timeout_ms:
        _delay(step_ms)
        waited += step_ms
        if _dv_state() != before:
            return True
    return False


def _is_playing_video() -> bool:
    """True when a video is playing, i.e. when native VS10 actions can apply."""
    try:
        return xbmc.Player().isPlayingVideo()
    except Exception:
        return False


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


# Native VS10 keymap action (SamuriHL/coreelec-xbmc commit 7df0943) that each
# TinyPPI mode maps to. When these actions are available they are fired instead
# of the sysfs sequences above, which are then skipped entirely.
#
# Only four actions exist, and vs10.sdr is hard-wired to SDR10 output
# (DOLBY_VISION_OUTPUT_MODE_SDR10, dv_mode 4). There is NO action for SDR8
# output (DOLBY_VISION_OUTPUT_MODE_SDR8, dv_mode 5), so 'sdr8' has no native
# entry here on purpose: it always takes the sysfs path, which writes dv_mode 5
# -- the exact same state the native engine uses for SDR8. That keeps a real
# distinction between 8-bit and 10-bit SDR output.
_VS10_ACTION = {
    "original_sdr": "vs10.original",
    "original_hdr": "vs10.original",
    "original_hlg": "vs10.original",
    "original_dv":  "vs10.dv",
    "dv":           "vs10.dv",
    "hdr10":        "vs10.hdr10",
    "sdr10":        "vs10.sdr",
}


def _probe_vs10_actions() -> bool:
    """Return True if this Kodi build ships the native VS10 output engine.

    Probes one of its settings over JSON-RPC, since the settings and the
    ``vs10.*`` keymap actions were added in the same commit: a ``result`` means
    the actions exist too, an ``error`` means we must drive sysfs ourselves.
    """
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {"setting": _VS10_PROBE_SETTING},
        }
    )
    try:
        response = json.loads(xbmc.executeJSONRPC(request))
    except Exception as e:
        xbmc.log(f"TinyPPI: VS10 Actions probe failed: {e}", xbmc.LOGWARNING)
        return False
    return isinstance(response, dict) and "result" in response


def _vs10_actions_available() -> bool:
    """Cached capability check, logging the chosen path once per session."""
    global _vs10_actions
    if _vs10_actions is None:
        _vs10_actions = _probe_vs10_actions()
        if _vs10_actions:
            xbmc.log(
                "TinyPPI: native VS10 Actions available -> preferred during "
                "playback, with sysfs fallback if they don't take effect",
                xbmc.LOGINFO,
            )
        else:
            xbmc.log(
                "TinyPPI: native VS10 Actions not available -> using the "
                "built-in TinyPPI VS10 (sysfs) path",
                xbmc.LOGINFO,
            )
    return _vs10_actions


def set_mode(name: str) -> None:
    """Apply the VS10 mode ``name`` (see ``_MODES``), preferring native actions.

    The native ``vs10.*`` actions only do anything during playback and can
    still silently no-op, so we try them only then and verify the DV driver
    state actually moved; either failure falls back to the built-in sysfs
    sequence, which always works.
    """
    sysfs = _MODES.get(name)
    if sysfs is None:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)
        return

    action = _VS10_ACTION.get(name)
    if action and _vs10_actions_available():
        if _is_playing_video():
            before = _dv_state()
            xbmc.executebuiltin(f"Action({action})")
            if _wait_for_dv_change(before):
                xbmc.log(
                    f"TinyPPI: mode '{name}' set via VS10 Actions -> "
                    f"Action({action})",
                    xbmc.LOGINFO,
                )
                return
            xbmc.log(
                f"TinyPPI: VS10 Action({action}) had no effect on the DV "
                "driver -> falling back to built-in TinyPPI VS10 (sysfs)",
                xbmc.LOGWARNING,
            )
        else:
            xbmc.log(
                f"TinyPPI: no video playing -> VS10 Action({action}) cannot "
                f"apply; using built-in TinyPPI VS10 (sysfs) for '{name}'",
                xbmc.LOGINFO,
            )
    elif _vs10_actions_available():
        # Native engine is present but this mode has no native action (e.g.
        # 'sdr8' -- the actions only expose SDR10, not SDR8). Use sysfs so the
        # real 8-bit vs 10-bit SDR distinction is preserved.
        xbmc.log(
            f"TinyPPI: '{name}' has no native VS10 action -> using built-in "
            "TinyPPI VS10 (sysfs) to keep the exact output",
            xbmc.LOGINFO,
        )

    sysfs()
    xbmc.log(
        f"TinyPPI: mode '{name}' set via built-in TinyPPI VS10 (sysfs)",
        xbmc.LOGINFO,
    )


__all__ = list(_MODES.keys()) + ["open_dialog", "set_mode"]


# Dialog button id -> mode name (routed through ``set_mode`` so the dialog also
# prefers the native VS10 Actions when they are available).
_ACTIONS = {
    # SDR
    1002: "original_sdr",
    1003: "hdr10",
    1004: "dv",
    # HDR10
    1005: "original_hdr",
    1006: "sdr8",
    1008: "dv",
    # HLG (Original bypasses VS10 so HLG stays HLG)
    1009: "original_hlg",
    1010: "sdr8",
    1011: "dv",
    # DV
    1012: "original_dv",
    1013: "sdr8",
}


class SettingsDialog(xbmcgui.WindowXMLDialog):
    """Menu dialog to pick a VS10 output mode or launch the TinyPPI overlay."""

    def onInit(self) -> None:
        # The SDR / HDR10 / DV groups branch on TinyPPI.HdrType, derived from
        # the stream's side data; refresh it so the right group appears as soon
        # as the player publishes it.
        self._running = True
        self._pending_mode = None
        self._monitor = xbmc.Monitor()
        threading.Thread(target=self._hdr_type_loop, daemon=True).start()

    def _hdr_type_loop(self) -> None:
        """Republish the HDR type until the dialog closes.

        A failed read only costs this cycle: the dialog would otherwise keep
        showing whichever SDR / HDR10 / DV group was up when the thread died.
        """
        from info.properties import publish_hdr_type

        home = xbmcgui.Window(10000)
        logged = False
        while self._running and not self._monitor.abortRequested():
            try:
                publish_hdr_type(home)
            except Exception as e:
                if not logged:
                    logged = True
                    xbmc.log(f"TinyPPI: HDR type refresh failed: {e}",
                             xbmc.LOGWARNING)
            if self._monitor.waitForAbort(0.5):
                break

    def close(self) -> None:
        self._running = False
        super().close()

    def onClick(self, control_id: int) -> None:
        if control_id == _BTN_TINYPPI:
            self.close()
            clear_overlay_state(xbmcgui.Window(10000))
            from ui.overlay import open_tinyppi
            open_tinyppi()
            return

        mode = _ACTIONS.get(control_id)
        if mode:
            # Defer applying: a native VS10 action fired now would be dropped by
            # the window manager while this modal dialog's closing animation is
            # still running ("ignoring action ..., because topmost modal dialog
            # closing animation is running"). open_dialog() applies it once
            # doModal() has returned, i.e. after the dialog is fully gone.
            self._pending_mode = mode
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
    mode = getattr(win, "_pending_mode", None)
    del win
    if mode:
        # The dialog and its closing animation are fully gone now, so a native
        # VS10 action will reach the fullscreen video player instead of being
        # ignored. Let the underlying window settle first, then apply.
        _delay(250)
        set_mode(mode)
