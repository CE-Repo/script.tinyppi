"""
main.py – Addon entry point for script.tinyppi.

This file exists solely to bootstrap the Python path and hand off execution
to resources/lib/overlay.py.  Keep it minimal — all real logic lives in lib.
"""

import os
import sys
import xbmcaddon

_addon = xbmcaddon.Addon()
_addon_path = _addon.getAddonInfo("path")
sys.path.insert(0, os.path.join(_addon_path, "resources", "lib"))

from overlay import open_tinyppi, open_dialog_mode
from mode_select import run_mode

raw_args = sys.argv[1:]

args = []
for a in raw_args:
    args.extend(a.split(","))

if not args or args[0] == "":
    launch_mode = _addon.getSetting("launch_mode")
    if launch_mode == "1":
        open_dialog_mode()
    else:
        open_tinyppi()

elif args[0] == "dialog":
    open_dialog_mode()

elif args[0] == "run_mode" and len(args) > 1:
    run_mode(args[1])

else:
    open_tinyppi()
