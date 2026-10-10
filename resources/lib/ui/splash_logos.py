# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""What the codec-logo splash shows: the logos for the current output and
audio, the DV layer pill, and whether a conversion is under way.

Read from Kodi's InfoLabels and the side data; drawing them is
``ui.splash``'s job.
"""

import xbmc
from core.maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP, IMAX_LOGO_MAP
from core.utils import info
from info.imax import imax_logo, is_known_imax_title


def current_logos(hdr_token: str) -> tuple[str, str]:
    """Return the ``(video, audio)`` logos for the current output.

    The video logo is always set (SDR fallback); the audio logo is '' for a
    codec without one.  ``ui.splash._mode_logos`` decides what a mode shows.
    """
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    audio_logo = AUDIO_LOGO_MAP.get(codec, "")

    video_logo = HDR_LOGO_MAP.get(hdr_token, HDR_LOGO_MAP[""])
    # IMAX films get the combined logo of the output format.  The map lookup
    # comes first, so only candidate formats pay for the title match.
    if hdr_token in IMAX_LOGO_MAP and is_known_imax_title():
        video_logo = imax_logo(hdr_token) or video_logo

    return video_logo, audio_logo


def video_has_audio(player: xbmc.Player) -> bool:
    """Return whether the video has an audio track.

    Asks the player as well: the codec is also empty before Kodi has named
    it.
    """
    if info("VideoPlayer.AudioCodec").strip():
        return True
    try:
        return bool(player.getAvailableAudioStreams())
    except RuntimeError:
        # Playback ended; the loop notices.  True keeps the stack unchanged.
        return True


def is_converting(hdr_type: str, gamut: str) -> bool:
    """Return whether the output *gamut* shows a conversion.

    Mirrors the check-circle condition in script-tinyppi-main.xml: non-DV
    source output as DV, HDR/DV output as SDR, or SDR/DV output as HDR10.
    *hdr_type* comes from the side data, so this works without the overlay.
    """
    gamut = gamut.upper()
    parts = gamut.split()
    mode = parts[0] if parts else ""

    non_dv_source     = hdr_type in ("hdr10", "hlg", "hdr10+", "")
    hdr_or_dv_source  = hdr_type in ("hdr10", "hlg", "hdr10+") or "dolby" in hdr_type
    sdr_or_dv_source  = hdr_type in ("", "hdr10+") or "dolby" in hdr_type

    if non_dv_source and "DV" in gamut:
        return True
    if hdr_or_dv_source and "SDR" in gamut:
        return True
    return bool(sdr_or_dv_source and mode == "HDR10")


def dv_layer_token(hdr_token: str, hdr_type: str, el_type: str) -> str:
    """Return the DV pill token for the output: fel, mel, other or ''.

    Based on the actual output (*hdr_token*): '' when it is not DV, 'other'
    for non-DV sources converted to DV and other profiles, else the source's
    enhancement layer (*el_type*).
    """
    if hdr_token != "dolbyvision":
        return ""
    if "dolby" not in hdr_type:
        return "other"
    el_type = el_type.upper()
    if el_type == "FEL":
        return "fel"
    if el_type == "MEL":
        return "mel"
    return "other"
