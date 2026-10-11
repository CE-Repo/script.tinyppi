#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Run kodi-addon-checker with the web dashboard's own file types allowed.

The checker's file whitelist is meant for add-ons in Kodi's official
repository and has no setting.  The dashboard needs scripts, icons and a web
app manifest, so this wrapper leaves those out of the whitelist check, in
resources/web only.  Every other check runs unchanged; the arguments are the
checker's own (see the addon job in .github/workflows/ci.yml).
"""

import os

from kodi_addon_checker import check_files
from kodi_addon_checker.__main__ import main

WEB_FILE_TYPES = (".js", ".svg", ".webmanifest")
WEB_FOLDER = os.path.join("resources", "web")

_check_file_whitelist = check_files.check_file_whitelist


def _is_web_file(file):
    return (os.path.join(file["path"], "").find(os.path.join(WEB_FOLDER, "")) != -1
            and file["name"].lower().endswith(WEB_FILE_TYPES))


def check_file_whitelist(report, file_index, addon_path):
    """The checker's whitelist check, without the dashboard's files."""
    _check_file_whitelist(report, [f for f in file_index if not _is_web_file(f)], addon_path)


check_files.check_file_whitelist = check_file_whitelist

if __name__ == "__main__":
    main()
