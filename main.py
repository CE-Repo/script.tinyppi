# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Addon entry point: bootstrap the lib path and dispatch the command."""

import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui

_ADDON_ID = "script.tinyppi"

_HOME_WINDOW_ID = 10000

# Home-window property the service publishes while it is running, and the
# request / acknowledgement pair a launch hands a view over with.  See
# _hand_to_service.
_PROP_SERVICE      = "TinyPPI.Service"
_PROP_OPEN_REQUEST = "TinyPPI.OpenRequest"
_PROP_OPEN_ACK     = "TinyPPI.OpenAck"

# Written into the request when a launch gives up waiting and opens the view
# itself, so a service that answers very late leaves it alone rather than
# opening a second one on top of it.
_WITHDRAWN = "-"

# The notification messages the service opens a view on, keyed by view.  A
# keymap can send one of these itself -- NotifyAll(script.tinyppi,open_overlay)
# -- which opens the overlay without starting a script at all.
_OPEN_MESSAGES = {
    "overlay": "open_overlay",
    "dialog":  "open_dialog",
}

# How long a launch waits for the service to take the view off its hands before
# opening it here instead, and how often it looks.  The service acknowledges as
# the first thing it does, so the wait is a couple of milliseconds in practice;
# the timeout only covers a service that is marked as running but is not.
_ACK_TIMEOUT_MS = 750
_ACK_STEP_MS    = 10


def _bootstrap_lib_path(addon: xbmcaddon.Addon) -> None:
    """Add resources/lib to the import path once."""
    lib_path = os.path.join(addon.getAddonInfo("path"), "resources", "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


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
    ``_PROP_SERVICE`` while it runs and acknowledges this request before it
    does anything else, so a launch that gets no answer simply opens the view
    itself (below) rather than doing nothing at all.
    """
    message = _OPEN_MESSAGES.get(view)
    if not message:
        return False

    home = xbmcgui.Window(_HOME_WINDOW_ID)
    if home.getProperty(_PROP_SERVICE) != "1":
        return False

    token = f"{view}:{os.getpid()}:{time.time():.3f}"
    home.setProperty(_PROP_OPEN_ACK, "")
    home.setProperty(_PROP_OPEN_REQUEST, token)
    xbmc.executebuiltin(f"NotifyAll({_ADDON_ID},{message})")

    waited = 0
    while waited < _ACK_TIMEOUT_MS:
        if home.getProperty(_PROP_OPEN_ACK) == token:
            return True
        xbmc.sleep(_ACK_STEP_MS)
        waited += _ACK_STEP_MS

    # Withdraw the request before opening the view here, so a service that is
    # only very late does not open a second one on top of it.
    home.setProperty(_PROP_OPEN_REQUEST, _WITHDRAWN)
    xbmc.log(
        "TinyPPI: the service did not answer – opening in this script instead",
        xbmc.LOGWARNING,
    )
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
    _bootstrap_lib_path(addon)

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
