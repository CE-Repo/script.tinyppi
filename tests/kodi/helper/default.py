# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Runs inside Kodi for the test suite (via Addons.ExecuteAddon).

Commands: ``set key=value ...`` writes TinyPPI settings, ``get key ...``
reads them, ``props name ...`` reads Home-window properties, ``labels``
InfoLabels, ``builtin`` runs a builtin.  The answer is written as JSON to
``$KODI_TEST_ROOT/helper-out.json``.
"""

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

OUT = os.path.join(os.environ.get("KODI_TEST_ROOT", "/opt/kodi-test"), "helper-out.json")


def main():
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    result = {"command": command}
    if command == "set":
        addon = xbmcaddon.Addon("script.tinyppi")
        for pair in args:
            key, _, value = pair.partition("=")
            addon.setSetting(key, value)
    elif command == "get":
        addon = xbmcaddon.Addon("script.tinyppi")
        result["settings"] = {key: addon.getSetting(key) for key in args}
    elif command == "props":
        home = xbmcgui.Window(10000)
        result["props"] = {name: home.getProperty(name) for name in args}
    elif command == "labels":
        result["labels"] = {label: xbmc.getInfoLabel(label) for label in args}
    elif command == "builtin":
        xbmc.executebuiltin(args[0])
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(result, handle)


main()
