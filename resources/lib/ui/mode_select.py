# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""VS10-mode selection dialog.

Open via ``RunScript(script.tinyppi,dialog)`` or ``open_dialog()``.
"""

import json
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from core import display
from core.utils import PROP_HDR10PLUS_PRESENT, clear_overlay_state

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

# The Dolby Vision driver, as CoreELEC 22 (kernel 5.15, Amlogic-ne) exposes it.
# Every value below is the one CoreELEC's own Kodi writes to these nodes in
# CAMLCodec::OpenDecoder / CloseDecoder, which is what this add-on has to agree
# with: it drives the same driver, on the same box, mid-playback.
_POLICY  = "/sys/module/aml_media/parameters/dolby_vision_policy"
_ENABLE  = "/sys/module/aml_media/parameters/dolby_vision_enable"
_DVMODE  = "/sys/class/amdolby_vision/dv_mode"

# Whether the driver runs Dolby Vision low latency, i.e. Player-LED: 0 is
# DOLBY_VISION_LL_DISABLE (TV-LED), 1 is DOLBY_VISION_LL_YUV422 (Player-LED).
# Kodi only writes it for a stream it turns Dolby Vision on for, so it answers
# for that playback and not for an HDR10 one -- see ``_player_led_mode``.
_LL_POLICY = "/sys/module/aml_media/parameters/dolby_vision_ll_policy"

# The two values that node takes.  A mode that puts Dolby Vision on the wire
# has to write the one its own output goes with -- tunnelled IPT is TV-LED and
# wants the low-latency path off, plain IPT is Player-LED and wants it on --
# rather than leave the node holding whatever the last title put there: a
# driver asked for one end while still set up for the other sends the picture
# out wrong.
_DOLBY_VISION_LL_DISABLE = "0"
_DOLBY_VISION_LL_YUV422  = "1"

# Whether the driver is running its Dolby Vision core, as opposed to merely
# having been asked to.  It clears once the core is actually down, which is the
# moment the rest of a switch may go on.
_DV_STATUS     = "/sys/module/aml_media/parameters/dolby_vision_status"
_DV_STATUS_OFF = "0"

# dolby_vision_policy: AMDV_FOLLOW_SINK, AMDV_FOLLOW_SOURCE and
# AMDV_FORCE_OUTPUT_MODE.  Forcing is what a VS10 mode is; follow-source is what
# Kodi leaves behind when it turns Dolby Vision off, and so what a mode that
# wants no VS10 at all restores.
_POLICY_FOLLOW_SOURCE = "1"
_POLICY_FORCE_OUTPUT  = "2"

# The output mode the Dolby Vision driver is actually sending, as opposed to
# the one just asked for through _DVMODE.  It follows the driver's own
# AMDV_OUTPUT_MODE enum, where 0 (IPT) and 1 (IPT tunnelled) are the two Dolby
# Vision outputs and the rest are HDR10, SDR10, SDR8 and bypass.
_DV_OUTPUT       = "/sys/module/aml_media/parameters/dolby_vision_mode"
_DV_OUTPUT_MODES = ("0", "1")

# Which of the three output formats each of those values names.  5 is
# AMDV_OUTPUT_MODE_BYPASS and is deliberately absent: bypass is the engine
# standing aside rather than an output it is holding, and a mode engaged from
# there is a fresh start with nothing to clear -- see ``_needs_sdr_first``.
_DV_OUTPUT_FORMAT = {
    "0": "dv",     # AMDV_OUTPUT_MODE_IPT
    "1": "dv",     # AMDV_OUTPUT_MODE_IPT_TUNNEL
    "2": "hdr10",  # AMDV_OUTPUT_MODE_HDR10
    "3": "sdr",    # AMDV_OUTPUT_MODE_SDR10
    "4": "sdr",    # AMDV_OUTPUT_MODE_SDR8
}

# _DVMODE takes that same enum shifted by one -- Kodi writes it as
# ``(AMDV_OUTPUT_MODE_x + 1) % 6`` -- so bypass lands on 0 and the modes below
# read one higher than the output mode they select.  Both spellings are live at
# once: _DVMODE is written shifted, _DV_OUTPUT is read unshifted.
_MODE_BYPASS     = "0"   # AMDV_OUTPUT_MODE_BYPASS, i.e. the source untouched
_MODE_DV_IPT     = "1"   # AMDV_OUTPUT_MODE_IPT, Dolby Vision for Player-LED
_MODE_DV_TUNNEL  = "2"   # AMDV_OUTPUT_MODE_IPT_TUNNEL, DV for TV-LED
_MODE_HDR10      = "3"
_MODE_SDR10      = "4"
_MODE_SDR8       = "5"

# How long the driver gets to pick up a mode change before the switch is taken
# to have stayed on the same side of the Dolby Vision line.
_DV_OUTPUT_TIMEOUT_MS = 1000

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


def _dv_output_active() -> bool:
    """Return whether the driver is currently sending Dolby Vision."""
    return _read(_DV_OUTPUT) in _DV_OUTPUT_MODES


def _dv_status_off() -> bool:
    """Whether the driver's Dolby Vision core is down.

    A node that cannot be read answers True: a box without it has nothing to
    wait for, and sitting out the full timeout on every switch there would buy
    nothing but a slower switch.
    """
    status = _read(_DV_STATUS)
    return status is None or status == _DV_STATUS_OFF


def _wait_for_dv_status_off(timeout_ms: int = 500, step_ms: int = 50) -> bool:
    """Poll the DV driver state, returning True once its core has gone down.

    False when the core is still up at the end, which is the ordinary answer
    for a switch *to* Dolby Vision: there the core is meant to stay up and the
    wait is simply the settling time the driver takes.  Either way the caller
    goes on -- what it needed was for the driver to be done, not for it to be
    off.
    """
    waited = 0
    while waited < timeout_ms:
        _delay(step_ms)
        waited += step_ms
        if _dv_status_off():
            return True
    return False


def _wait_for_dv_output_change(
    before: bool,
    timeout_ms: int = _DV_OUTPUT_TIMEOUT_MS,
    step_ms: int = 50,
) -> bool:
    """Poll the driver's output mode, returning True once it crossed the
    Dolby Vision line (and False if it never does)."""
    waited = 0
    while waited < timeout_ms:
        if _dv_output_active() != before:
            return True
        _delay(step_ms)
        waited += step_ms
    return False


def _wait_for_dv_output_value_change(
    before,
    timeout_ms: int = _DV_OUTPUT_TIMEOUT_MS,
    step_ms: int = 50,
) -> bool:
    """Poll the driver's output mode, returning True once it reads anything
    other than ``before`` (and False if it never does).

    The same wait as ``_wait_for_dv_output_change``, asked of the raw value
    rather than of which side of the Dolby Vision line it falls on: SDR8 to
    HDR10 moves the output without crossing that line, and a switch the sysfs
    path has to reset the display for is any switch the driver actually took.
    """
    waited = 0
    while waited < timeout_ms:
        if _read(_DV_OUTPUT) != before:
            return True
        _delay(step_ms)
        waited += step_ms
    return False


def _is_playing_video() -> bool:
    """True when a video is playing, i.e. when native VS10 actions can apply."""
    try:
        return xbmc.Player().isPlayingVideo()
    except Exception:
        return False


def _reset_display_after_switch(name: str, output_before, via_sysfs: bool) -> None:
    """Re-init the HDMI output the switch it follows has just moved.

    Kodi only re-applies the display mode when the played stream's HDR type
    changes, and a VS10 switch made mid-playback never tells it about one.  The
    driver then starts sending a different output format while the HDMI output
    is still set up for the one before it, so the TV never switches over and the
    picture comes out with the wrong colours -- most visibly in Player-LED mode.
    Asking the display driver to re-apply its output is the missing step; see
    ``core.display`` for how that is done.

    Which switches need one is the path's answer, not the user's:

    * The built-in sysfs path writes the driver's nodes behind Kodi's back, so
      *nothing* it does is ever signalled -- every mode it moves the output to
      leaves the display set up for the one before it, SDR8 to HDR10 as much as
      SDR to Dolby Vision.  Every switch it takes is reset.
    * The native ``vs10.*`` actions go through Kodi's own VS10 engine, which
      handles the output it knows how to handle; only the Dolby Vision line,
      which no VS10 action re-negotiates the HDMI output for, is left to be
      reset here.

    Both ends of Dolby Vision need it.  TV-LED was held back from the reset for
    a while, on the grounds that tunnelled Dolby Vision negotiates the HDMI
    output itself and that a reset there did harm rather than nothing, leaving
    later switches in the same playback landing on SDR instead of the mode
    picked (issue #64).  What actually caused that was the reset going out over
    a driver that had not finished with the mode before it; now that
    ``_set_passthrough_mode`` waits for the Dolby Vision core to come down
    first, the reset lands on a settled driver and SDR to Dolby Vision and back
    works on both ends.

    The move is confirmed against the driver before anything is re-applied,
    because a mode the driver did not take is a mode the display has nothing to
    re-apply for.  That wait doubles as the settling time a conversion mode
    takes on its own, since ``_set_sdr_conversion_mode`` waits on nothing.
    Playback gates it too, since a switch with nothing on screen has no output
    to re-apply.

    Only kernel 5.15 (CoreELEC 22) feels any of this: the reset is a DRM
    property on the HDMI connector, which the older kernels have no equivalent
    for, so there ``core.display`` finds nothing to drive either way.
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
        xbmc.log(
            f"TinyPPI: '{name}' did not move the driver's output mode "
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
    """Write a sysfs sequence, waiting between steps when requested."""
    for index, (path, value) in enumerate(steps):
        if index and delay_ms > 0:
            _delay(delay_ms)
        _w(path, value)


def _set_passthrough_mode(dv_mode: str, delay_ms: int = 100) -> None:
    """Set the CoreELEC policy and enable Dolby Vision in the requested mode.

    The order is as much of the answer as the values are.  Enabling before the
    policy is forced hands the driver a core it can still bring up its own way;
    forcing first asks it to hold an output it is not yet running.  Bypass
    wants neither and is written the other way about: follow-source restores
    what Kodi leaves behind, and the driver is only switched off once the core
    it was running has actually come down -- an ``enable=N`` written into a
    live core is what used to leave the display half-switched.

    A mode that puts Dolby Vision on the wire also states which end is mapping
    it, tunnelled IPT for TV-LED and plain IPT for Player-LED, rather than
    trusting the low-latency policy the last title left behind.
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

    # Give the driver the moment it needs to be done with the mode before this
    # one.  The display reset that follows a crossing, and the switch-off just
    # below, both have to land after that and not into the middle of it.
    _wait_for_dv_status_off()

    if dv_mode == _MODE_BYPASS:
        _write_sequence(((_ENABLE, "N"),))


def _set_sdr_conversion_mode(dv_mode: str) -> None:
    """Enable the requested conversion mode.

    The trip through bypass that used to open this sequence is gone.  It was
    there to clear whatever VS10 mode was in place, and what it actually did
    was ask the driver for two outputs in a row: the second landed on a core
    still tearing the first one down, which is the state the wrong picture came
    out of.  Clearing a mode is a switch of its own, and where one is needed
    ``set_mode`` makes it one -- see ``_staged_switch``.
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
    # Which of the two Dolby Vision outputs the box wants: Player-LED takes IPT,
    # TV-LED the tunnelled one, exactly as Kodi picks between them itself.
    if _player_led_mode():
        _set_passthrough_mode(_MODE_DV_IPT)
    else:
        _set_passthrough_mode(_MODE_DV_TUNNEL)


def original_hdr() -> None:
    _set_passthrough_mode(_MODE_HDR10)


def original_hlg() -> None:
    # HLG is not a valid VS10 input, so turn VS10 off to let HLG pass through
    # the standard HDR path untouched.  That is also why neither the dialog nor
    # the dashboard offers HLG any modes at all; this one is left reachable
    # through ``run_mode`` for a keymap that wants to clear a VS10 mode an
    # earlier title left behind.  Follow-source with enable=N is the state
    # Kodi itself leaves the driver in when it releases Dolby Vision; policy 0 is
    # follow-sink, a different thing, and not what "off" means here.
    _write_sequence(
        (
            (_POLICY, _POLICY_FOLLOW_SOURCE),
            (_ENABLE, "N"),
        )
    )


# Alias of dv; kept as its own name so keymaps can use both.
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

# The modes that leave Dolby Vision on the wire, whether converted to it or
# passed through.  Crossing in or out of this set is the one move the native
# VS10 actions still need a display reset for; the sysfs path needs one for
# every move it makes -- see ``_reset_display_after_switch``.
_DV_MODES = ("dv", "original_dv")

# What each mode leaves on the wire, in the same three names
# ``_DV_OUTPUT_FORMAT`` reads back off the driver.  ``original_sdr`` is bypass,
# i.e. the source untouched, and SDR is what that is: the SDR group is the only
# menu offering it.  ``original_hlg`` has no entry because it names no output of
# its own -- it turns VS10 off and lets HLG through as it is.
_MODE_OUTPUT = {
    "original_sdr": "sdr",
    "sdr8":         "sdr",
    "sdr10":        "sdr",
    "hdr10":        "hdr10",
    "original_hdr": "hdr10",
    "dv":           "dv",
    "original_dv":  "dv",
}

# The swap the driver will not make in one go, read as "from this output, not
# straight to any of these".  HDR10 and Dolby Vision each leave the display set
# up for themselves, and the parameters of the one do not survive being handed
# the other; SDR in between is what clears them.
_NO_DIRECT_SWITCH = {
    "hdr10": ("dv",),
    "dv":    ("hdr10",),
}

# The output SDR is asked for as that step.  Forced SDR10, not bypass: bypass
# is the source untouched, which for an HDR10 or a Dolby Vision title is the
# very format being cleared.  It is also the output Kodi's own ``vs10.sdr``
# names, so the stage looks the same whichever path applies it.
_SDR_STAGE = "sdr10"

# How long the driver is left to itself between the two stages, on top of
# waiting for its Dolby Vision core to come down.
_STAGE_GAP_MS = 250

# How long a staged switch may take before the caller stops waiting on it.
# Generous: the two stages wait on the driver themselves, and the number is
# here to bound a switch that goes wrong, not to pace one that does not.
_STAGE_TIMEOUT_S = 15


def _needs_sdr_first(name: str) -> bool:
    """Whether ``name`` has to go through SDR to be reached from the output
    now on the wire.

    Only an output the VS10 engine is *holding* needs the step.  Bypass says
    the engine is standing aside, and engaging a mode from there is a fresh
    start with no earlier output to clear.  An output that cannot be read needs
    nothing either: a switch staged for a reason that could not be established
    is worse than one that lets the driver answer for itself.  Playback gates
    it too, since a switch with nothing on screen moves no display.
    """
    if not _is_playing_video():
        return False

    output = _DV_OUTPUT_FORMAT.get(_read(_DV_OUTPUT))
    return _MODE_OUTPUT.get(name) in _NO_DIRECT_SWITCH.get(output, ())


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


def _probe_dv_Player_LED_setting():
    """Return the configured Dolby Vision LED mode, or None when it cannot be
    read.

    ``coreelec.amlogic.dolbyvisionled`` is CoreELEC's own
    ``AML_DISPLAY_DV_LED``: 0 is TV-LED, 1 Player-LED.  Unlike
    ``_probe_vs10_actions``, which asks whether a setting is there at all, this
    one has to read what it says -- the setting exists on every build that can
    do either end, so its presence alone answers nothing.  Going by presence put
    a TV-LED box on the Player-LED output, where the picture went out SDR
    BT.2020nc.

    None, not False, when the value does not arrive: not knowing is not the same
    as TV-LED, and the caller has somewhere else to ask.
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
        xbmc.log(f"TinyPPI: probe failed: {e}", xbmc.LOGWARNING)
        return None
    if not isinstance(response, dict) or "result" not in response:
        return None
    value = response["result"].get("value")
    # Read as a number, so a "0" that arrives as text is still TV-LED: taking
    # it as a bare string would repeat the mistake this replaced.
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 if value else 0


def _player_led_mode() -> bool:
    """Return True if Dolby Vision is being driven Player-LED on this box.

    Kodi's own setting answers first, because it answers for every source.  The
    driver's ``dolby_vision_ll_policy`` describes the same choice -- Kodi writes
    it from that very setting -- but only for a stream it turned Dolby Vision on
    for; an HDR10 one leaves it holding whatever the last title put there, which
    is why it stands in only when the setting cannot be read at all rather than
    being trusted over it.

    TV-LED is the answer when neither can be read: it is CoreELEC's default and
    the end that needs nothing done for it.
    """
    setting = _probe_dv_Player_LED_setting()
    if setting is not None:
        return setting != 0

    ll_policy = _read(_LL_POLICY)
    if ll_policy is not None:
        xbmc.log(
            "TinyPPI: Dolby Vision LED mode unreadable from Kodi -> taking the "
            f"driver's low-latency policy ({ll_policy})",
            xbmc.LOGINFO,
        )
        return ll_policy not in ("", "0")

    return False


def _hybrid_dv_hdr10plus() -> bool:
    """Return whether the playing stream is a Dolby Vision + HDR10+ hybrid.

    Read off the two properties ``info.properties.publish_hdr_type`` publishes,
    rather than parsed here: the side data is already being read once a poll
    for the overlay and the dialog, and this only needs its answer.
    """
    home = xbmcgui.Window(10000)
    return (
        home.getProperty(PROP_HDR10PLUS_PRESENT) == "1"
        and "dolby" in home.getProperty("TinyPPI.HdrType").lower()
    )


def set_mode(name: str) -> None:
    """Apply the VS10 mode ``name`` (see ``_MODES``).

    One press, one mode -- but not always one switch.  Dolby Vision and HDR10
    cannot be swapped for one another in a single one: the display keeps the
    parameters of the format it was already showing, and the picture comes out
    wrong.  SDR in between is what clears them, and it only counts as a step if
    it is a switch in its own right, so where the crossing needs it the mode is
    reached in two (see ``_switch_through_sdr``) and the caller is none the
    wiser.

    A hybrid Dolby Vision + HDR10+ title is switched like any other and only
    noted in the log.  Neither the dialog nor the dashboard offers it a mode
    any more -- the driver does not take one there -- but this is
    also the entry point a keymap and ``run_mode`` come through, and a mode
    bound to a button stays bound to it: refusing the write here would replace
    a switch that does nothing with a shortcut that does nothing, and take the
    escape hatch away from a box where it turns out to work.
    """
    if name not in _MODES:
        xbmc.log(f"TinyPPI: Unknown mode '{name}'", xbmc.LOGERROR)
        return

    if _hybrid_dv_hdr10plus():
        xbmc.log(
            f"TinyPPI: '{name}' is being applied to a Dolby Vision title that "
            "also carries HDR10+; the driver is not expected to take a VS10 "
            "mode for a hybrid grade, so the output may not change",
            xbmc.LOGWARNING,
        )

    if _needs_sdr_first(name):
        _switch_through_sdr(name)
        return

    _switch(name)


def _switch(name: str) -> None:
    """One switch, whole: the output moved and the display told about it.

    The output is switched by ``_apply_mode``; what is left here is the step
    neither path performs on its own -- the display reset the switch needs.
    Which one that is depends on the path ``_apply_mode`` took, so it says,
    and the driver's output mode is sampled before the switch so the two sides
    can be compared afterwards.
    """
    output_before = _read(_DV_OUTPUT)
    via_sysfs = _apply_mode(name)
    _reset_display_after_switch(name, output_before, via_sysfs)


def _staged_switch(name: str) -> None:
    """Reach ``name`` by way of SDR, as two switches with the driver's own
    state read in between.

    This is the manual route -- press SDR, then press the mode -- done for the
    user.  Both stages are whole switches, display reset included, because that
    is what makes the SDR one clear anything: written into the same pass as the
    mode after it, it is not a step the driver ever stands on, which is the
    state the wrong picture came out of.  Between them the Dolby Vision core is
    waited out and the driver then left alone for a moment longer, so the
    second stage arrives at a driver that is done rather than one still busy.
    """
    xbmc.log(
        f"TinyPPI: '{name}' cannot be reached from the output now on the wire "
        "in one switch -> going through SDR first",
        xbmc.LOGINFO,
    )
    _switch(_SDR_STAGE)
    _wait_for_dv_status_off()
    _delay(_STAGE_GAP_MS)
    _switch(name)


def _switch_through_sdr(name: str) -> None:
    """Run the staged switch on a thread of its own, and wait for it there.

    The thread is what keeps the two stages apart: each gets its own call, its
    own waits and its own display reset, rather than being folded into the one
    pass the driver will not take.  The wait is what keeps them alive -- a mode
    switch arrives through ``RunScript`` more often than not, and that
    interpreter is torn down the moment its script returns, which left to
    itself would end the switch half way through with the driver on SDR.  So
    the caller is held for as long as the switch takes and no longer; the
    timeout only bounds one that has gone wrong.
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
        xbmc.log(
            f"TinyPPI: staged switch to '{name}' is still running after "
            f"{_STAGE_TIMEOUT_S}s -> leaving it to finish on its own",
            xbmc.LOGWARNING,
        )


def _apply_mode(name: str) -> bool:
    """Switch the VS10 output to ``name``, preferring the native actions.

    The native ``vs10.*`` actions only do anything during playback and can
    still silently no-op, so we try them only then and verify the DV driver
    state actually moved; either failure falls back to the built-in sysfs
    sequence, which always works.

    Returns whether the switch went out over that sysfs path, which is what
    decides how much of a display reset it needs -- see
    ``_reset_display_after_switch``.
    """
    sysfs = _MODES[name]
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
                return False
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
    return True


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
