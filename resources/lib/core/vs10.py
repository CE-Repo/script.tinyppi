# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10 output modes: switching the Dolby Vision driver.

``set_mode`` applies a mode, through Kodi's native VS10 actions where they
exist and work, else through the driver's sysfs nodes.  No window is
involved: the dialog (ui.mode_select), the dashboard (web.vs10) and
``RunScript(script.tinyppi,run_mode,<mode>)`` all switch through here.
"""

import json
import threading
import time
from functools import cache
from typing import Any

import xbmc
from core import display
from core.log import log
from core.utils import PROP_HDR10PLUS_PRESENT, home_window

# Dolby Vision driver nodes of CoreELEC 22 (kernel 5.15, Amlogic-ne).  All
# values match what CoreELEC's Kodi writes in CAMLCodec::OpenDecoder /
# CloseDecoder, since both drive the same driver.
_POLICY  = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE  = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE  = "/sys/class/amdolby_vision/dv_mode"

# Low-latency (Player-LED) policy: 0 TV-LED, 1 Player-LED.  Kodi writes it
# only for streams it enables DV for (see ``_player_led_mode``).
_LL_POLICY = "/sys/module/aml_media/parameters/dolby_vision_ll_policy"

# Its two values.  A DV mode writes the one matching its output (tunnelled
# IPT: off, plain IPT: on) instead of keeping the last title's value, which
# would produce a wrong picture.
_DOLBY_VISION_LL_DISABLE = "0"
_DOLBY_VISION_LL_YUV422  = "1"

# Whether the DV core is actually running; it clears once the core is down,
# when the rest of a switch may proceed.
_DV_STATUS     = "/sys/module/aml_media/parameters/dolby_vision_status"
_DV_STATUS_OFF = "0"

# dolby_vision_policy values: follow-source (what Kodi leaves when it turns
# DV off) and force-output (a VS10 mode).
_POLICY_FOLLOW_SOURCE = "1"
_POLICY_FORCE_OUTPUT  = "2"

# The output the driver actually sends (AMDV_OUTPUT_MODE enum): 0 IPT and
# 1 IPT tunnelled are DV; then HDR10, SDR10, SDR8, bypass.
_DV_OUTPUT       = "/sys/module/aml_media/parameters/dolby_vision_mode"
_DV_OUTPUT_MODES = ("0", "1")

# Output format per value.  Bypass (5) is absent on purpose: the engine is
# not holding an output, so nothing needs clearing (see _needs_sdr_first).
_DV_OUTPUT_FORMAT = {
    "0": "dv",     # AMDV_OUTPUT_MODE_IPT
    "1": "dv",     # AMDV_OUTPUT_MODE_IPT_TUNNEL
    "2": "hdr10",  # AMDV_OUTPUT_MODE_HDR10
    "3": "sdr",    # AMDV_OUTPUT_MODE_SDR10
    "4": "sdr",    # AMDV_OUTPUT_MODE_SDR8
}

# _DVMODE takes the same enum shifted by one (``(mode + 1) % 6``, as Kodi
# writes it), so bypass is 0.  _DVMODE is written shifted, _DV_OUTPUT is read
# unshifted.
_MODE_BYPASS     = "0"   # AMDV_OUTPUT_MODE_BYPASS: source untouched
_MODE_DV_IPT     = "1"   # AMDV_OUTPUT_MODE_IPT, Dolby Vision for Player-LED
_MODE_DV_TUNNEL  = "2"   # AMDV_OUTPUT_MODE_IPT_TUNNEL, DV for TV-LED
_MODE_HDR10      = "3"
_MODE_SDR10      = "4"
_MODE_SDR8       = "5"

# How long the driver gets to apply a mode change.
_DV_OUTPUT_TIMEOUT_MS = 1000

# A setting added together with the native vs10.* actions (SamuriHL/
# coreelec-xbmc commit 7df0943); if JSON-RPC knows it, the actions exist.
_VS10_PROBE_SETTING = "coreelec.amlogic.dolbyvision.vs10.dv"

# Failed sysfs writes per thread, so a switch can tell whether its sequence
# reached the driver (see _apply_mode).  Per thread: staged switches, the
# dashboard and the dialog may run at once.
_writes = threading.local()


def _failed_writes() -> int:
    return getattr(_writes, "failed", 0)


def _w(path: str, value: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
        log(f"{path} = {value}", xbmc.LOGINFO)
    except OSError as e:
        _writes.failed = _failed_writes() + 1
        log(f"FAILED {path}: {e}", xbmc.LOGERROR)


def delay(ms: int) -> None:
    """Wait *ms* milliseconds, in Kodi's own sleep while Kodi runs."""
    try:
        xbmc.sleep(ms)
    except Exception:  # Kodi is shutting down
        time.sleep(ms / 1000)


def _read(path: str) -> str | None:
    """Return a sysfs node's stripped contents, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _dv_state() -> tuple[str | None, str | None, str | None]:
    """Return the DV driver nodes, to tell whether a native action took."""
    return (_read(_POLICY), _read(_ENABLE), _read(_DVMODE))


def _wait_for_dv_change(before: tuple[str | None, ...], timeout_ms: int = 500,
                        step_ms: int = 50) -> bool:
    """Poll the DV driver state; True once it differs from *before*."""
    waited = 0
    while waited < timeout_ms:
        delay(step_ms)
        waited += step_ms
        if _dv_state() != before:
            return True
    return False


def _dv_output_active() -> bool:
    """Return whether the driver is currently sending Dolby Vision."""
    return _read(_DV_OUTPUT) in _DV_OUTPUT_MODES


def _dv_status_off() -> bool:
    """Return whether the DV core is down (True when the node is missing)."""
    status = _read(_DV_STATUS)
    return status is None or status == _DV_STATUS_OFF


def _wait_for_dv_status_off(timeout_ms: int = 500, step_ms: int = 50) -> bool:
    """Wait until the DV core is down; False on timeout.

    For a switch to Dolby Vision the core stays up and this is just the
    driver's settling time; callers continue either way.
    """
    waited = 0
    while waited < timeout_ms:
        delay(step_ms)
        waited += step_ms
        if _dv_status_off():
            return True
    return False


def _wait_for_dv_output_change(
    before: bool,
    timeout_ms: int = _DV_OUTPUT_TIMEOUT_MS,
    step_ms: int = 50,
) -> bool:
    """Wait until the output crosses the DV line; False on timeout."""
    waited = 0
    while waited < timeout_ms:
        if _dv_output_active() != before:
            return True
        delay(step_ms)
        waited += step_ms
    return False


def _wait_for_dv_output_value_change(
    before: str | None,
    timeout_ms: int = _DV_OUTPUT_TIMEOUT_MS,
    step_ms: int = 50,
) -> bool:
    """Wait until the output mode differs from *before*; False on timeout.

    Unlike ``_wait_for_dv_output_change`` this also sees changes that do not
    cross the DV line (e.g. SDR8 to HDR10), which the sysfs path must reset
    the display for.
    """
    waited = 0
    while waited < timeout_ms:
        if _read(_DV_OUTPUT) != before:
            return True
        delay(step_ms)
        waited += step_ms
    return False


def _is_playing_video() -> bool:
    """Return whether a video plays (needed for native VS10 actions)."""
    try:
        return xbmc.Player().isPlayingVideo()
    except Exception:  # Kodi is shutting down
        return False


def _reset_display_after_switch(name: str, output_before: str | None, via_sysfs: bool) -> None:
    """Re-apply the HDMI output after a VS10 switch (see ``core.display``).

    Kodi only re-applies the display mode when the stream's HDR type
    changes; after a VS10 switch the TV would otherwise stay on the old
    format with wrong colours (most visibly in Player-LED mode).

    * The sysfs path is never signalled, so every switch it makes is reset.
    * Native ``vs10.*`` actions handle everything except crossing the DV
      line, so only those switches are reset.

    Both TV-LED and Player-LED need it.  Issue #64 (later switches landing on
    SDR) came from resetting a driver still busy with the previous mode;
    ``_set_passthrough_mode`` now waits for the DV core first.

    The reset only happens during playback and once the driver confirms the
    change (this wait is also the settling time of conversion modes).  Only
    kernel 5.15 (CoreELEC 22) has the DRM property; elsewhere it is a no-op.
    """
    if not _is_playing_video():
        return

    dv_before = output_before in _DV_OUTPUT_MODES

    if via_sysfs:
        moved = _wait_for_dv_output_value_change(output_before)
    else:
        if (name in _DV_MODES) == dv_before:
            return
        moved = _wait_for_dv_output_change(dv_before)

    if not moved:
        log(
            f"'{name}' did not move the driver's output mode "
            "-> no display reset",
            xbmc.LOGWARNING,
        )
        return

    if (name in _DV_MODES) != dv_before:
        direction = "from" if dv_before else "to"
        reason = f"VS10 output switched {direction} Dolby Vision"
    else:
        reason = f"VS10 output switched to '{name}'"
    display.reset(reason)


def _write_sequence(
    steps: tuple[tuple[str, str], ...],
    delay_ms: int = 100,
) -> None:
    """Write a sysfs sequence, waiting *delay_ms* between steps."""
    for index, (path, value) in enumerate(steps):
        if index and delay_ms > 0:
            delay(delay_ms)
        _w(path, value)


def _set_passthrough_mode(dv_mode: str, delay_ms: int = 100) -> None:
    """Set the driver policy and enable Dolby Vision in mode *dv_mode*.

    The order matters: enable before forcing the policy (forcing first asks
    for an output the driver is not running yet).  Bypass is the reverse:
    restore follow-source, wait for the core to stop, then disable (writing
    ``enable=N`` into a live core left the display half-switched).

    DV modes also set the low-latency policy to match TV-LED (tunnelled IPT)
    or Player-LED (plain IPT).
    """
    steps = []

    if dv_mode == _MODE_BYPASS:
        steps.append((_POLICY, _POLICY_FOLLOW_SOURCE))
    else:
        steps.append((_ENABLE, "Y"))
        steps.append((_POLICY, _POLICY_FORCE_OUTPUT))

    if dv_mode == _MODE_DV_TUNNEL:
        steps.append((_LL_POLICY, _DOLBY_VISION_LL_DISABLE))
    elif dv_mode == _MODE_DV_IPT:
        steps.append((_LL_POLICY, _DOLBY_VISION_LL_YUV422))

    steps.append((_DVMODE, dv_mode))

    _write_sequence(tuple(steps), delay_ms=delay_ms)

    # Let the driver finish the previous mode before the display reset or
    # the switch-off below.
    _wait_for_dv_status_off()

    if dv_mode == _MODE_BYPASS:
        _write_sequence(((_ENABLE, "N"),))


def _set_sdr_conversion_mode(dv_mode: str) -> None:
    """Enable conversion mode *dv_mode*.

    No detour through bypass: two outputs in a row land on a core still
    tearing down the first, which gives a wrong picture.  Where a mode must
    be cleared first, ``set_mode`` stages two switches (see
    ``_staged_switch``).
    """
    _write_sequence(
        (
            (_ENABLE, "Y"),
            (_POLICY, _POLICY_FORCE_OUTPUT),
            (_DVMODE, dv_mode),
        )
    )


def original_sdr() -> None:
    _set_passthrough_mode(_MODE_BYPASS, delay_ms=0)


def hdr10() -> None:
    _set_sdr_conversion_mode(_MODE_HDR10)


def dv() -> None:
    # Player-LED uses IPT, TV-LED tunnelled IPT, as Kodi chooses itself.
    if _player_led_mode():
        _set_passthrough_mode(_MODE_DV_IPT)
    else:
        _set_passthrough_mode(_MODE_DV_TUNNEL)


def original_hdr() -> None:
    _set_passthrough_mode(_MODE_HDR10)


def original_hlg() -> None:
    # HLG is no valid VS10 input, so VS10 is turned off (the dialog and the
    # dashboard offer HLG no modes; this stays reachable via ``run_mode`` to
    # clear a leftover mode).  Follow-source with enable=N is the state Kodi
    # leaves when it releases DV (policy 0 would be follow-sink).
    _write_sequence(
        (
            (_POLICY, _POLICY_FOLLOW_SOURCE),
            (_ENABLE, "N"),
        )
    )


# Alias of dv, so keymaps can use either name.
original_dv = dv


def sdr8() -> None:
    _set_sdr_conversion_mode(_MODE_SDR8)


def sdr10() -> None:
    _set_sdr_conversion_mode(_MODE_SDR10)


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

# Modes with Dolby Vision output; crossing this set needs a display reset
# even with native actions (see _reset_display_after_switch).
_DV_MODES = ("dv", "original_dv")

# Output format per mode, named as in ``_DV_OUTPUT_FORMAT``.  original_sdr
# (bypass) is only offered for SDR sources; original_hlg has no output of its
# own.
_MODE_OUTPUT = {
    "original_sdr": "sdr",
    "sdr8":         "sdr",
    "sdr10":        "sdr",
    "hdr10":        "hdr10",
    "original_hdr": "hdr10",
    "dv":           "dv",
    "original_dv":  "dv",
}

# Switches the driver cannot make directly ("from this output, not to
# these"): HDR10 <-> DV needs SDR in between to clear the display setup.
_NO_DIRECT_SWITCH: dict[str, tuple[str, ...]] = {
    "hdr10": ("dv",),
    "dv":    ("hdr10",),
}

# The intermediate SDR step: forced SDR10 (bypass would keep the HDR10/DV
# source), also what ``vs10.sdr`` produces.
_SDR_STAGE = "sdr10"

# Extra pause between the stages, after waiting for the DV core.
_STAGE_GAP_MS = 250

# Upper bound for a staged switch; only limits one that goes wrong.
_STAGE_TIMEOUT_S = 15


def _needs_sdr_first(name: str) -> bool:
    """Return whether mode *name* must go through SDR from the current output.

    Only when VS10 is holding an output (not bypass), the output is
    readable, and a video plays.
    """
    if not _is_playing_video():
        return False

    output = _DV_OUTPUT_FORMAT.get(_read(_DV_OUTPUT) or "", "")
    return _MODE_OUTPUT.get(name) in _NO_DIRECT_SWITCH.get(output, ())


# Native vs10.* action per mode (SamuriHL/coreelec-xbmc commit 7df0943),
# used instead of the sysfs sequences when available.  vs10.sdr always means
# SDR10 and there is no SDR8 action, so 'sdr8' always uses sysfs (dv_mode 5),
# keeping 8-bit and 10-bit SDR distinct.
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
    """Return whether this Kodi build has the native VS10 engine.

    Probes one of its settings over JSON-RPC (added with the ``vs10.*``
    actions): a result means the actions exist.
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
        log(f"VS10 Actions probe failed: {e}", xbmc.LOGWARNING)
        return False
    return isinstance(response, dict) and "result" in response


@cache
def _vs10_actions_available() -> bool:
    """Return the probe result (probed once), logging the chosen path."""
    available = _probe_vs10_actions()
    if available:
        log(
            "native VS10 Actions available -> preferred during "
            "playback, with sysfs fallback if they don't take effect",
            xbmc.LOGINFO,
        )
    else:
        log(
            "native VS10 Actions not available -> using the "
            "built-in TinyPPI VS10 (sysfs) path",
            xbmc.LOGINFO,
        )
    return available


def _probe_dv_Player_LED_setting() -> int | None:

    """Return the DV LED setting (0 TV-LED, 1 Player-LED), or None.

    Reads the value of ``coreelec.amlogic.dolbyvisionled``; its mere
    presence says nothing (checking presence once put TV-LED boxes on the
    Player-LED output).  None when unreadable, so the caller can try
    elsewhere.
    """
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {"setting": "coreelec.amlogic.dolbyvisionled"},
        }
    )
    try:
        response = json.loads(xbmc.executeJSONRPC(request))
    except Exception as e:
        log(f"probe failed: {e}", xbmc.LOGWARNING)
        return None
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        return None
    value: Any = result.get("value")  # whatever the setting holds
    # As a number, so a textual "0" is still TV-LED.
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 if value else 0


def _player_led_mode() -> bool:
    """Return whether Dolby Vision runs in Player-LED mode on this box.

    Kodi's setting first; the driver's ``dolby_vision_ll_policy`` only as a
    fallback, since it may be stale from an earlier title.  Defaults to
    TV-LED (CoreELEC's default).
    """
    setting = _probe_dv_Player_LED_setting()
    if setting is not None:
        return setting != 0

    ll_policy = _read(_LL_POLICY)
    if ll_policy is not None:
        log(
            "Dolby Vision LED mode unreadable from Kodi -> taking the "
            f"driver's low-latency policy ({ll_policy})",
            xbmc.LOGINFO,
        )
        return ll_policy not in ("", "0")

    return False


def _hybrid_dv_hdr10plus() -> bool:
    """Return whether the stream is a DV + HDR10+ hybrid.

    Uses the properties from ``info.publish.publish_hdr_type``.
    """
    home = home_window()
    return (
        home.getProperty(PROP_HDR10PLUS_PRESENT) == "1"
        and "dolby" in home.getProperty("TinyPPI.HdrType").lower()
    )


def set_mode(name: str) -> None:
    """Apply VS10 mode *name* (see ``_MODES``).

    DV <-> HDR10 needs SDR in between as a switch of its own, so such modes
    are reached in two switches (see ``_switch_through_sdr``).

    DV + HDR10+ hybrids are switched anyway and only logged: the dialog and
    dashboard offer them no modes, but keymaps and ``run_mode`` still work,
    in case the driver does take it on some box.
    """
    if name not in _MODES:
        log(f"Unknown mode '{name}'", xbmc.LOGERROR)
        return

    if _hybrid_dv_hdr10plus():
        log(
            f"'{name}' is being applied to a Dolby Vision title that "
            "also carries HDR10+; the driver is not expected to take a VS10 "
            "mode for a hybrid grade, so the output may not change",
            xbmc.LOGWARNING,
        )

    if _needs_sdr_first(name):
        _switch_through_sdr(name)
        return

    _switch(name)


def _switch(name: str) -> None:
    """Switch to mode *name* and reset the display as needed.

    The output mode is sampled before ``_apply_mode``; the reset depends on
    the path it took.
    """
    output_before = _read(_DV_OUTPUT)
    via_sysfs = _apply_mode(name)
    _reset_display_after_switch(name, output_before, via_sysfs)


def _staged_switch(name: str) -> None:
    """Reach mode *name* via SDR in two complete switches.

    Like pressing SDR and then the mode by hand.  Each stage includes its
    display reset, and the DV core is waited out in between plus a short
    pause, so the second stage meets an idle driver.
    """
    log(
        f"'{name}' cannot be reached from the output now on the wire "
        "in one switch -> going through SDR first",
        xbmc.LOGINFO,
    )
    _switch(_SDR_STAGE)
    _wait_for_dv_status_off()
    delay(_STAGE_GAP_MS)
    _switch(name)


def _switch_through_sdr(name: str) -> None:
    """Run the staged switch on its own thread and wait for it.

    Waiting keeps a ``RunScript`` interpreter alive until both stages are
    done (otherwise it could stop halfway, on SDR).  The timeout only bounds
    a switch that went wrong.
    """
    worker = threading.Thread(
        target=_staged_switch,
        args=(name,),
        name="TinyPPI-vs10-stage",
        daemon=True,
    )
    worker.start()
    worker.join(_STAGE_TIMEOUT_S)
    if worker.is_alive():
        log(
            f"staged switch to '{name}' is still running after "
            f"{_STAGE_TIMEOUT_S}s -> leaving it to finish on its own",
            xbmc.LOGWARNING,
        )


def _apply_mode(name: str) -> bool:
    """Switch the VS10 output to *name*, preferring the native actions.

    Native actions only work during playback and can silently do nothing,
    so the driver state is verified; otherwise the sysfs sequence is used.
    Returns whether sysfs was used (see ``_reset_display_after_switch``).
    """
    sysfs = _MODES[name]
    action = _VS10_ACTION.get(name)
    if action and _vs10_actions_available():
        if _is_playing_video():
            before = _dv_state()
            xbmc.executebuiltin(f"Action({action})")
            if _wait_for_dv_change(before):
                log(
                    f"mode '{name}' set via VS10 Actions -> "
                    f"Action({action})",
                    xbmc.LOGINFO,
                )
                return False
            log(
                f"VS10 Action({action}) had no effect on the DV "
                "driver -> falling back to built-in TinyPPI VS10 (sysfs)",
                xbmc.LOGWARNING,
            )
        else:
            log(
                f"no video playing -> VS10 Action({action}) cannot "
                f"apply; using built-in TinyPPI VS10 (sysfs) for '{name}'",
                xbmc.LOGINFO,
            )
    elif _vs10_actions_available():
        # No native action for this mode (e.g. 'sdr8'); sysfs keeps SDR8.
        log(
            f"'{name}' has no native VS10 action -> using built-in "
            "TinyPPI VS10 (sysfs) to keep the exact output",
            xbmc.LOGINFO,
        )

    failed_before = _failed_writes()
    sysfs()
    failed = _failed_writes() - failed_before
    if failed:
        # Never log "set" for a sequence that did not reach the driver.
        log(
            f"mode '{name}' NOT set via built-in TinyPPI VS10 (sysfs): "
            f"{failed} write(s) failed, see the lines above",
            xbmc.LOGERROR,
        )
    else:
        log(
            f"mode '{name}' set via built-in TinyPPI VS10 (sysfs)",
            xbmc.LOGINFO,
        )
    return True


__all__ = list(_MODES.keys()) + ["set_mode"]
