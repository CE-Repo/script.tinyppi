# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's two settings actions: show the address, create a token.

Both run via ``RunScript`` from the settings dialog, in their own
interpreter, so they never block the settings UI.
"""

import xbmcgui

from core import settings
from core.utils import localized
from web.server import ensure_token, generate_token, local_address

_HEADING       = 32446   # Web dashboard
_ADDRESS_INTRO = 32447   # Open this address in a browser on the same network:
_TOKEN_LABEL   = 32436   # Access token
_TOKEN_NEW     = 32438   # Generate a new token


def show_web_info() -> None:
    """Show the dashboard URL and token together."""
    address = local_address()
    token   = ensure_token(settings.addon())
    body = (
        f"{localized(_ADDRESS_INTRO)}\n\n"
        f"[B]{address}[/B]\n\n"
        f"{localized(_TOKEN_LABEL)}:  [B]{token}[/B]"
    )
    xbmcgui.Dialog().textviewer(localized(_HEADING), body, usemono=True)


def new_web_token() -> None:
    """Create and show a new token, logging out every browser using the old one."""
    token = generate_token(settings.addon())
    xbmcgui.Dialog().ok(
        localized(_TOKEN_NEW),
        f"{localized(_TOKEN_LABEL)}:  [B]{token}[/B]",
    )
