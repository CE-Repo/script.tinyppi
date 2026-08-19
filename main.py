"""Addon entry point: bootstrap the lib path and dispatch the command."""

import os
import sys

import xbmcaddon


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


def main() -> None:
    """Dispatch TinyPPI's script entry point."""
    addon = xbmcaddon.Addon()
    _bootstrap_lib_path(addon)

    from ui.mode_select import set_mode
    from ui.overlay import open_dialog_mode, open_tinyppi

    args = _split_args(sys.argv[1:])
    command = args[0] if args else ""

    if not command:
        if addon.getSetting("launch_mode") == "1":
            open_dialog_mode()
        else:
            open_tinyppi()
        return

    if command == "dialog":
        open_dialog_mode()
    elif command == "splash":
        from ui.splash import open_splash
        open_splash()
    elif command == "run_mode" and len(args) > 1:
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
        open_tinyppi()


if __name__ == "__main__":
    main()
