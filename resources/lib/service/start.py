# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Service entry point (xbmc.service in addon.xml): run service/monitor.py.

Kodi's add-on checker asks for entry points this small.
"""

import os
import sys

_LIB_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from service.monitor import run  # noqa: E402  needs the path above

if __name__ == "__main__":
    run()
