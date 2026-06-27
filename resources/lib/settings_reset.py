"""
Reset helpers for add-on settings.

The settings dialog invokes this via ``RunScript(script.tinyppi,reset_settings)``.
"""

import os
import xml.etree.ElementTree as ET

import xbmcgui
import xbmcaddon
import xbmcvfs

from theme import _COLOR_SETTINGS, _save_custom, apply_theme


def _iter_setting_defaults(addon):
    """Yield ``(setting_id, default_value)`` pairs from resources/settings.xml."""
    settings_path = addon.getAddonInfo("path").rstrip("/\\") + "/resources/settings.xml"
    settings_path = xbmcvfs.translatePath(settings_path)
    root = ET.parse(settings_path).getroot()

    for setting in root.iter("setting"):
        setting_id = setting.get("id")
        default = setting.find("default")
        if setting_id and default is not None:
            yield setting_id, (default.text or "").strip()


def reset_all_settings(addon=None) -> None:
    """
    Reset every add-on setting with a default value back to that default.

    Custom HEX colors are stored outside Kodi's settings system, so they are
    cleared explicitly as part of the reset.
    """
    addon = addon or xbmcaddon.Addon()

    defaults = dict(_iter_setting_defaults(addon))
    for setting_id, value in defaults.items():
        addon.setSetting(setting_id, value)

    _save_custom({})

    try:
        color_overrides = {
            setting_id: defaults.get(setting_id, "0")
            for setting_id in _COLOR_SETTINGS
        }
        apply_theme(xbmcgui.Window(10000), addon, overrides={**defaults, **color_overrides}, custom={})
    except Exception:  # pragma: no cover - best effort, never block the reset
        pass

    xbmcgui.Dialog().notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(32249),
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )
