# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Stand-in for Kodi's ``xbmcaddon`` module.

Settings live in ``SETTINGS`` (strings, as Kodi stores them); unset ids
read as their ``resources/settings.xml`` default.
"""

import os
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SETTINGS: dict[str, str] = {}
DEFAULTS = {
    setting.get("id"): setting.findtext("default") or ""
    for setting in ET.parse(os.path.join(ROOT, "resources", "settings.xml")).iter("setting")
}
VERSION = ET.parse(os.path.join(ROOT, "addon.xml")).getroot().get("version")


class Addon:
    def __init__(self, addon_id="script.tinyppi"):
        self._id = addon_id

    def getSetting(self, key):
        return SETTINGS.get(key, DEFAULTS.get(key, ""))

    def getSettingBool(self, key):
        return self.getSetting(key) == "true"

    def getSettingInt(self, key):
        return int(self.getSetting(key) or 0)

    def getSettingString(self, key):
        return self.getSetting(key)

    def setSetting(self, key, value):
        SETTINGS[key] = str(value)

    def getLocalizedString(self, string_id):
        return f"#{string_id}"

    def getAddonInfo(self, key):
        return {
            "id": self._id,
            "path": ROOT,
            "profile": f"special://profile/addon_data/{self._id}/",
            "version": VERSION,
            "name": "TinyPPI",
        }.get(key, "")
