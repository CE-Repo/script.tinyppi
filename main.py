"""
main.py – Addon entry point for script.tinyppi.

This file exists solely to bootstrap the Python path and hand off execution
to resources/lib/overlay.py.  Keep it minimal — all real logic lives in lib.
"""

import os
import sys

import xbmcaddon

_addon_path = xbmcaddon.Addon().getAddonInfo("path")
sys.path.insert(0, os.path.join(_addon_path, "resources", "lib"))

from overlay import open_tinyppi, open_dialog_mode

if "dialog" in sys.argv[1:]:
    open_dialog_mode()
else:
    open_tinyppi()
