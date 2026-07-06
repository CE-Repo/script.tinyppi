"""
main.py – Addon entry point for script.tinyppi.

This file exists solely to bootstrap the Python path and hand off execution
to resources/lib/overlay.py.  Keep it minimal — all real logic lives in lib.
"""

import os
import sys

import xbmcaddon


def _bootstrap_lib_path(addon: xbmcaddon.Addon) -> None:
    """Add resources/lib to the import path once."""
    lib_path = os.path.join(addon.getAddonInfo("path"), "resources", "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _split_args(raw_args: list[str]) -> list[str]:
    """Kodi may pass comma-separated script arguments; flatten them."""
    args: list[str] = []
    for raw in raw_args:
        args.extend(raw.split(","))
    return args


def main() -> None:
    """Dispatch TinyPPI's script entry point."""
    addon = xbmcaddon.Addon()
    _bootstrap_lib_path(addon)

    from mode_select import set_mode
    from overlay import open_dialog_mode, open_tinyppi

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
    elif command == "run_mode" and len(args) > 1:
        set_mode(args[1])
    elif command == "custom_color" and len(args) > 1:
        from theme import custom_color
        custom_color(args[1])
    else:
        open_tinyppi()


if __name__ == "__main__":
    main()
