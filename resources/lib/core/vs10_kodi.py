# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What Kodi tells ``core.vs10`` before a switch.

Whether this build has the native ``vs10.*`` actions, the Dolby Vision LED
setting, whether a video plays, and whether the stream is a DV + HDR10+
hybrid.
"""

import json
from functools import cache
from typing import Any

import xbmc
from core.log import log
from core.utils import PROP_HDR10PLUS_PRESENT, home_window

# A setting added together with the native vs10.* actions (SamuriHL/
# coreelec-xbmc commit 7df0943); if JSON-RPC knows it, the actions exist.
VS10_PROBE_SETTING = "coreelec.amlogic.dolbyvision.vs10.dv"


def is_playing_video() -> bool:
    """Return whether a video plays (needed for native VS10 actions)."""
    try:
        return xbmc.Player().isPlayingVideo()
    except RuntimeError:  # Kodi is shutting down
        return False


def _ask_setting(setting: str, what: str) -> dict[str, Any] | None:
    """Return Kodi's JSON-RPC answer for the value of *setting*, or None."""
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {"setting": setting},
        }
    )
    try:
        response = json.loads(xbmc.executeJSONRPC(request))
    except (RuntimeError, ValueError) as e:
        log(f"{what} probe failed: {e}", xbmc.LOGWARNING)
        return None
    return response if isinstance(response, dict) else None


def probe_vs10_actions() -> bool:
    """Return whether this Kodi build has the native VS10 engine.

    Probes one of its settings over JSON-RPC (added with the ``vs10.*``
    actions): a result means the actions exist.
    """
    response = _ask_setting(VS10_PROBE_SETTING, "VS10 Actions")
    return response is not None and "result" in response


@cache
def vs10_actions_available() -> bool:
    """Return the probe result (probed once), logging the chosen path."""
    available = probe_vs10_actions()
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


def probe_dv_led_setting() -> int | None:
    """Return the DV LED setting (0 TV-LED, 1 Player-LED), or None.

    Reads the value of ``coreelec.amlogic.dolbyvisionled``; its mere
    presence says nothing (checking presence once put TV-LED boxes on the
    Player-LED output).  None when unreadable, so the caller can try
    elsewhere.
    """
    response = _ask_setting("coreelec.amlogic.dolbyvisionled", "Dolby Vision LED")
    result = (response or {}).get("result")
    if not isinstance(result, dict):
        return None
    value: Any = result.get("value")  # whatever the setting holds
    # As a number, so a textual "0" is still TV-LED.
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 if value else 0


def hybrid_dv_hdr10plus() -> bool:
    """Return whether the stream is a DV + HDR10+ hybrid.

    Uses the properties from ``info.publish.publish_hdr_type``.
    """
    home = home_window()
    return (
        home.getProperty(PROP_HDR10PLUS_PRESENT) == "1"
        and "dolby" in home.getProperty("TinyPPI.HdrType").lower()
    )
