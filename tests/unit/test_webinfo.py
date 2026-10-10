# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's settings actions: show the address, create a token (ui/webinfo.py)."""

import pytest

import xbmcaddon
import xbmcgui
from ui import webinfo
from web import server

ADDRESS = "http://192.0.2.10:8099/"


@pytest.fixture(autouse=True)
def address(monkeypatch):
    monkeypatch.setattr(webinfo, "local_address", lambda: ADDRESS)


def test_the_address_and_the_stored_token_are_shown_together():
    xbmcaddon.SETTINGS["web_token"] = "  Secret42  "
    webinfo.show_web_info()
    [shown] = xbmcgui.DIALOGS
    assert shown == ("textviewer", (
        "#32201",
        f"#32202\n\n[B]{ADDRESS}[/B]\n\n#32187:  [B]Secret42[/B]",
    ), {"usemono": True})
    assert xbmcaddon.SETTINGS["web_token"] == "  Secret42  "       # left as it was


def test_without_a_token_one_is_created_and_shown():
    webinfo.show_web_info()
    token = xbmcaddon.SETTINGS["web_token"]
    assert len(token) == server._TOKEN_LENGTH and set(token) <= set(server._TOKEN_ALPHABET)
    [(kind, (_heading, body), _kwargs)] = xbmcgui.DIALOGS
    assert kind == "textviewer" and body.endswith(f"#32187:  [B]{token}[/B]")


def test_a_new_token_replaces_the_old_one_and_is_shown():
    xbmcaddon.SETTINGS["web_token"] = "old-token"
    webinfo.new_web_token()
    token = xbmcaddon.SETTINGS["web_token"]
    assert token != "old-token" and len(token) == server._TOKEN_LENGTH
    [shown] = xbmcgui.DIALOGS
    assert shown == ("ok", ("#32189", f"#32187:  [B]{token}[/B]"), {})
