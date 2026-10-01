# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Names every part of the add-on agrees on.

Kept free of Kodi imports so main.py can read them on its fast path -- the one
that hands a view to the service before anything else has been loaded.
"""

ADDON_ID = "script.tinyppi"

# Where Kodi keeps this add-on's own files: the settings it is set to, the
# custom colours, the scaled logo textures.
PROFILE_DIR = f"special://profile/addon_data/{ADDON_ID}"

# The Home window, where TinyPPI publishes its state as properties.
HOME_WINDOW_ID = 10000

# --- Handing a view to the service -------------------------------------------
#
# Published while the service runs, and read by main.py: a launch that finds it
# hands its view over there instead of importing the whole overlay into a
# throwaway interpreter of its own.
PROP_SERVICE = "TinyPPI.Service"

# The request a launch leaves behind for the service, and the acknowledgement it
# waits for.
PROP_OPEN_REQUEST = "TinyPPI.OpenRequest"
PROP_OPEN_ACK     = "TinyPPI.OpenAck"

# Written into the request when a launch gives up waiting and opens the view
# itself, so a service that answers very late leaves it alone rather than
# opening a second one on top of it.
OPEN_WITHDRAWN = "-"

# The notification messages the service opens a view on, keyed by view.  A
# keymap can send one of these itself -- NotifyAll(script.tinyppi,open_overlay)
# -- which opens the overlay without starting a script at all.  Kodi delivers
# them to the service's monitor as ``Other.<message>``.
OPEN_MESSAGES = {
    "overlay": "open_overlay",
    "dialog":  "open_dialog",
}
