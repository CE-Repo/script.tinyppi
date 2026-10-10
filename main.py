# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Add-on entry point: set up the import path and dispatch the command."""

import os
import sys
import time

import xbmc
import xbmcgui

# Put resources/lib on the import path (derived from this file, without
# asking Kodi).
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "resources", "lib")
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from core.constants import (  # noqa: E402  needs the path above
    ADDON_ID,
    HOME_WINDOW_ID,
    OPEN_MESSAGES,
    OPEN_WITHDRAWN,
    PROP_OPEN_ACK,
    PROP_OPEN_REQUEST,
    PROP_SERVICE,
)
from core.log import log  # noqa: E402

# How long (and how often) a launch waits for the service to acknowledge a
# handover.  Normally a few milliseconds; the timeout covers a service that
# is marked as running but does not answer.
_ACK_TIMEOUT_MS = 750
_ACK_STEP_MS    = 10


def _split_args(raw_args: list[str]) -> list[str]:
    """Flatten Kodi's comma-separated script arguments."""
    args: list[str] = []
    for raw in raw_args:
        args.extend(raw.split(","))
    return args


def _hand_to_service(view: str) -> bool:
    """Ask the running service to open *view*; return whether it accepted.

    Each launch runs in a fresh interpreter that would have to import the
    overlay modules first; the service has them loaded already, which saves
    most of the delay.  Without an acknowledgement the caller opens the
    view itself.
    """
    message = OPEN_MESSAGES.get(view)
    if not message:
        return False

    home = xbmcgui.Window(HOME_WINDOW_ID)
    if home.getProperty(PROP_SERVICE) != "1":
        return False

    token = f"{view}:{os.getpid()}:{time.time():.3f}"
    home.setProperty(PROP_OPEN_ACK, "")
    home.setProperty(PROP_OPEN_REQUEST, token)
    xbmc.executebuiltin(f"NotifyAll({ADDON_ID},{message})")

    waited = 0
    while waited < _ACK_TIMEOUT_MS:
        if home.getProperty(PROP_OPEN_ACK) == token:
            return True
        xbmc.sleep(_ACK_STEP_MS)
        waited += _ACK_STEP_MS

    # Withdraw the request, so a late service does not open a second view.
    home.setProperty(PROP_OPEN_REQUEST, OPEN_WITHDRAWN)
    log("the service did not answer – opening in this script instead",
        xbmc.LOGWARNING)
    return False


def _open_view(view: str) -> None:
    """Open the overlay or the VS10 dialog, preferably in the service."""
    if _hand_to_service(view):
        return

    # Imported lazily: the fast path above needs none of this.
    if view == "dialog":
        from ui.overlay import open_dialog_mode
        open_dialog_mode()
    else:
        from ui.overlay import open_tinyppi
        open_tinyppi()


def main() -> None:
    """Run the command given in the script arguments."""
    args = _split_args(sys.argv[1:])
    command = args[0] if args else ""

    # Read settings only without an explicit view: creating the handle parses
    # the whole settings definition.
    if not command:
        from core import settings
        launch_mode = settings.addon().getSetting("launch_mode")
        command = "dialog" if launch_mode == "1" else "overlay"

    if command in ("overlay", "dialog"):
        _open_view(command)
    elif command == "splash":
        from ui.splash import open_splash
        open_splash()
    elif command == "run_mode" and len(args) > 1:
        from core.vs10 import set_mode
        set_mode(args[1])
    elif command == "pick_color" and len(args) > 1:
        from ui.theme import pick_color
        pick_color(args[1], args[2] if len(args) > 2 else "")
    elif command == "web_info":
        from ui.webinfo import show_web_info
        show_web_info()
    elif command == "web_token":
        from ui.webinfo import new_web_token
        new_web_token()
    else:
        _open_view("overlay")


if __name__ == "__main__":
    main()
