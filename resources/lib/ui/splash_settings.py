# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The splash's settings, read in one go per settings change.

Three modes (``start``, ``osd`` and ``tinyppi``) each have their own logo
choice and order, position, size and DV pill edge (see ``ui.splash``).
"""

from typing import NamedTuple

import xbmcaddon


class ModeSettings(NamedTuple):
    """One mode's settings, read once per settings change."""

    show_video: bool
    show_audio: bool
    audio_first: bool
    offset_x: int
    offset_y: int
    scale: float
    pill_at_top: bool


class Settings(NamedTuple):
    """All settings the controller uses.

    Read in one go when ``core.settings`` returns a new handle (i.e. after a
    change), not on every poll.
    """

    show_on_start: bool
    show_on_osd: bool
    show_on_tinyppi: bool
    duration: int
    modes: dict[str, ModeSettings]


# Per-mode offset settings (x, y).
_OFFSET_SETTINGS = {
    "start":   ("splash_start_offset_x",   "splash_start_offset_y"),
    "osd":     ("splash_osd_offset_x",     "splash_osd_offset_y"),
    "tinyppi": ("splash_tinyppi_offset_x", "splash_tinyppi_offset_y"),
}

# Per-mode size setting (80-130 %, default 100 %), times the panel's base scale.
_SCALE_SETTINGS = {
    "start":   "splash_start_scale",
    "osd":     "splash_osd_scale",
    "tinyppi": "splash_tinyppi_scale",
}

# Per-mode logo selection and order (default: both, video on top).
_SHOW_VIDEO_SETTINGS = {
    "start":   "splash_start_show_video",
    "osd":     "splash_osd_show_video",
    "tinyppi": "splash_tinyppi_show_video",
}
_SHOW_AUDIO_SETTINGS = {
    "start":   "splash_start_show_audio",
    "osd":     "splash_osd_show_audio",
    "tinyppi": "splash_tinyppi_show_audio",
}
_ORDER_SETTINGS = {
    "start":   "splash_start_order",
    "osd":     "splash_osd_order",
    "tinyppi": "splash_tinyppi_order",
}
# splash_<mode>_order: 0 keeps video on top, 1 puts audio on top.
_ORDER_AUDIO_FIRST = 1

# Per-mode edge of the DV layer pill.
_PILL_POSITION_SETTINGS = {
    "start":   "splash_start_pill_position",
    "osd":     "splash_osd_pill_position",
    "tinyppi": "splash_tinyppi_pill_position",
}
# splash_<mode>_pill_position: 0 bottom edge, 1 top edge.
_PILL_TOP = 1


def read_settings(addon: xbmcaddon.Addon) -> Settings:
    """Read all controller settings (see ``Settings``)."""
    modes = {}
    for mode, (setting_x, setting_y) in _OFFSET_SETTINGS.items():
        modes[mode] = ModeSettings(
            show_video=addon.getSettingBool(_SHOW_VIDEO_SETTINGS[mode]),
            show_audio=addon.getSettingBool(_SHOW_AUDIO_SETTINGS[mode]),
            audio_first=(
                addon.getSettingInt(_ORDER_SETTINGS[mode]) == _ORDER_AUDIO_FIRST
            ),
            offset_x=addon.getSettingInt(setting_x),
            offset_y=addon.getSettingInt(setting_y),
            scale=_mode_scale(addon, mode),
            pill_at_top=(
                addon.getSettingInt(_PILL_POSITION_SETTINGS[mode]) == _PILL_TOP
            ),
        )
    return Settings(
        show_on_start=addon.getSettingBool("splash_enabled"),
        show_on_osd=addon.getSettingBool("splash_show_on_osd"),
        show_on_tinyppi=addon.getSettingBool("splash_show_on_tinyppi"),
        duration=addon.getSettingInt("splash_duration"),
        modes=modes,
    )


def _mode_scale(addon: xbmcaddon.Addon, mode: str) -> float:
    """Return *mode*'s size multiplier, clamped to 0.8-1.3."""
    try:
        percent = addon.getSettingInt(_SCALE_SETTINGS[mode])
    except (KeyError, TypeError, ValueError, RuntimeError):  # unknown mode, or not an integer
        return 1.0
    return min(1.3, max(0.8, percent / 100.0))
