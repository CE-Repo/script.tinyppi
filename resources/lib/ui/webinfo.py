"""The dashboard's two settings buttons: show its address, mint a new token.

Both run through ``RunScript`` from the settings dialog, so they happen in
their own interpreter and never hold the settings UI while sysfs or a socket
answers.
"""

import xbmcaddon
import xbmcgui

from web.server import ensure_token, generate_token, local_address

_ADDON = xbmcaddon.Addon()

_HEADING       = 32446   # Web dashboard
_ADDRESS_INTRO = 32447   # Open this address in a browser on the same network:
_TOKEN_LABEL   = 32436   # Access token
_TOKEN_NEW     = 32438   # Generate a new token


def show_web_info() -> None:
    """Show the URL and token together, which is what someone standing in
    front of the TV with a phone actually needs."""
    address = local_address()
    token   = ensure_token(_ADDON)
    body = (
        f"{_ADDON.getLocalizedString(_ADDRESS_INTRO)}\n\n"
        f"[B]{address}[/B]\n\n"
        f"{_ADDON.getLocalizedString(_TOKEN_LABEL)}:  [B]{token}[/B]"
    )
    xbmcgui.Dialog().textviewer(
        _ADDON.getLocalizedString(_HEADING), body, usemono=True
    )


def new_web_token() -> None:
    """Mint a new token and show it, so the one just invalidated is replaced
    by one the user can read straight away.

    Every browser holding the old token is logged out by this; that is the
    point of the button.
    """
    token = generate_token(_ADDON)
    xbmcgui.Dialog().ok(
        _ADDON.getLocalizedString(_TOKEN_NEW),
        f"{_ADDON.getLocalizedString(_TOKEN_LABEL)}:  [B]{token}[/B]",
    )
