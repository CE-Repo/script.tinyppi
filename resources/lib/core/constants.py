# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Names shared across the add-on.

Free of Kodi imports, so main.py can read them on its fast path before
anything else is loaded.
"""

ADDON_ID = "script.tinyppi"

# The add-on's data folder: stored settings, custom colours, scaled logos.
PROFILE_DIR = f"special://profile/addon_data/{ADDON_ID}"

# The Home window, where TinyPPI publishes its state as properties.
HOME_WINDOW_ID = 10000

# --- Handing a view to the service -----------------------------------------
#
# Set while the service runs.  A launch that finds it hands its view to the
# service instead of loading the overlay in a throwaway interpreter.
PROP_SERVICE = "TinyPPI.Service"

# The request a launch leaves for the service, and the service's reply.
PROP_OPEN_REQUEST = "TinyPPI.OpenRequest"
PROP_OPEN_ACK     = "TinyPPI.OpenAck"

# Written into the request when a launch stops waiting and opens the view
# itself, so a late service does not open a second one.
OPEN_WITHDRAWN = "-"

# Notification messages that open a view, keyed by view.  A keymap can send
# one directly, e.g. NotifyAll(script.tinyppi,open_overlay), without starting
# a script; the service's monitor receives it as ``Other.<message>``.
OPEN_MESSAGES = {
    "overlay": "open_overlay",
    "dialog":  "open_dialog",
}
