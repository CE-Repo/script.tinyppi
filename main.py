# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Add-on entry point: put resources/lib on the import path and run the command.

The work is done in resources/lib/launcher.py; Kodi's add-on checker asks for
entry points this small.
"""

import os
import sys

# Derived from this file, without asking Kodi.
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "resources", "lib")
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from launcher import main  # noqa: E402  needs the path above

if __name__ == "__main__":
    main()
