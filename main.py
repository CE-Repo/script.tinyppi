# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Addon entry point: bootstrap the lib path and dispatch the command."""

import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui

# resources/lib on the import path, read off this file rather than asked of
# Kodi: the constants below are needed before anything else is.
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

# How long a launch waits for the service to take the view off its hands before
# opening it here instead, and how often it looks.  The service acknowledges as
# the first thing it does, so the wait is a couple of milliseconds in practice;
# the timeout only covers a service that is marked as running but is not.
_ACK_TIMEOUT_MS = 750
_ACK_STEP_MS    = 10


def _split_args(raw_args: list[str]) -> list[str]:
    """Flatten Kodi's comma-separated script arguments."""
    args: list[str] = []
    for raw in raw_args:
        args.extend(raw.split(","))
    return args


def _hand_to_service(view: str) -> bool:
    """Ask the running service to open *view*, returning whether it took it.

    Kodi starts a fresh interpreter for every launch, and the overlay's own
    modules -- the property getters, the side-data reader, the theme, the
    title list -- have to be imported into it before anything can be drawn.
    The service has had all of them loaded since Kodi started, so handing the
    view over there opens it without that import pass, which is most of the
    wait between the button and the first frame.

    Nothing is assumed about the service being alive: it publishes
    ``PROP_SERVICE`` while it runs and acknowledges this request before it
    does anything else, so a launch that gets no answer simply opens the view
    itself (below) rather than doing nothing at all.
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

    # Withdraw the request before opening the view here, so a service that is
    # only very late does not open a second one on top of it.
    home.setProperty(PROP_OPEN_REQUEST, OPEN_WITHDRAWN)
    log("the service did not answer – opening in this script instead",
        xbmc.LOGWARNING)
    return False


def _open_view(view: str) -> None:
    """Open the overlay or the VS10 dialog, in the service where possible."""
    if _hand_to_service(view):
        return

    # Imported here rather than at the top of the module: on the fast path
    # above nothing of this is needed, and every other command has its own
    # imports to do.
    if view == "dialog":
        from ui.overlay import open_dialog_mode
        open_dialog_mode()
    else:
        from ui.overlay import open_tinyppi
        open_tinyppi()


def main() -> None:
    """Dispatch TinyPPI's script entry point."""
    addon = xbmcaddon.Addon()

    args = _split_args(sys.argv[1:])
    command = args[0] if args else ""

    if not command:
        command = "dialog" if addon.getSetting("launch_mode") == "1" else "overlay"

    if command in ("overlay", "dialog"):
        _open_view(command)
    elif command == "splash":
        from ui.splash import open_splash
        open_splash()
    elif command == "run_mode" and len(args) > 1:
        from ui.mode_select import set_mode
        set_mode(args[1])
    elif command == "custom_color" and len(args) > 1:
        from ui.theme import custom_color
        custom_color(args[1])
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
