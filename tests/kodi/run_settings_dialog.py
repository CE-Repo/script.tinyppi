# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Kodi's settings dialog for TinyPPI: every category opens, cleanly."""

import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import config
import driver as kodi
from report import Report


def category_names():
    """The categories' English labels, in order."""
    tree = ET.parse(os.path.join(config.REPO, "resources", "settings.xml")).getroot()
    with open(os.path.join(config.REPO, "resources", "language", "resource.language.en_gb", "strings.po"),
              encoding="utf-8") as handle:
        strings = dict(re.findall(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', handle.read()))
    return [strings[c.get("label")] for c in tree.iter("category")]


def main():
    report = Report("settings-dialog")
    expected = category_names()
    k = kodi.Kodi(kodi.make_home("settings-dialog"))
    print(f"Kodi answered after {k.start():.1f} s", flush=True)
    try:
        kodi.start_tinyppi(k)
        mark = k.log_size()
        kodi.builtin("Addon.OpenSettings(script.tinyppi)")
        time.sleep(4)
        report.check("the settings dialog opens", kodi.window()["id"] == 10140, kodi.window())
        kodi.rpc("Input.Left")            # onto the category list
        time.sleep(1)
        seen = []
        for index in range(len(expected)):
            seen.append(kodi.labels("System.CurrentControl")["System.CurrentControl"])
            kodi.shot(f"settings-category-{index + 1}")
            kodi.rpc("Input.Down")
            time.sleep(1.5)
        report.check(f"all {len(expected)} categories open in order", seen == expected, seen)
        kodi.rpc("Input.Back")
        time.sleep(2)
        bad = [line[:200] for line in k.log(mark).splitlines()
               if (" error " in line or "warning" in line) and ("etting" in line or "tinyppi" in line.lower())]
        report.check("no setting errors or warnings in the log", not bad, bad[:6])
    finally:
        k.quit()
        k.stop_display()
    sys.exit(report.finish())


if __name__ == "__main__":
    main()
