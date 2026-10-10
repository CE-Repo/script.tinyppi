# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Host-name trust and the guessing lockout (web/access.py)."""

import pytest

from web import access


@pytest.mark.parametrize("host", [
    "", "192.168.1.20", "192.168.1.20:8099", "[fe80::1]:8099", "coreelec", "coreelec:8099",
    "coreelec.local", "box.fritz.box", "tv.speedport.ip", "media.lan", "media.home.arpa", "box.local.",
])
def test_home_network_names_are_trusted(host):
    assert access.trusted_host(host)


@pytest.mark.parametrize("host", ["evil.example.com", "tv.dyndns.org:8099", "attacker.net"])
def test_other_names_are_not(host):
    assert not access.trusted_host(host)


def test_lockout_after_ten_different_wrong_tokens(monkeypatch):
    guesses = access.Guesses()
    for i in range(9):
        guesses.wrong("10.0.0.5", f"GUESS{i}")
    assert guesses.locked_for("10.0.0.5") == 0
    guesses.wrong("10.0.0.5", "GUESS9")
    assert guesses.locked_for("10.0.0.5") > 590
    assert guesses.locked_for("10.0.0.6") == 0


def test_the_same_old_token_is_not_a_guess():
    guesses = access.Guesses()
    for _ in range(50):
        guesses.wrong("10.0.0.5", "OLDTOKEN")
        guesses.wrong("10.0.0.5", "")
    assert guesses.locked_for("10.0.0.5") == 0


def test_the_table_is_capped():
    guesses = access.Guesses()
    for i in range(access._MAX_TRACKED + 50):
        guesses.wrong(f"10.1.{i // 250}.{i % 250}", "WRONG")
    assert len(guesses._wrong) <= access._MAX_TRACKED


@pytest.mark.parametrize(("address", "plain", "key"), [
    ("192.168.1.20", "192.168.1.20", "192.168.1.20"),
    ("::ffff:192.168.1.20", "192.168.1.20", "192.168.1.20"),
    ("2001:db8:1:2:aaaa::1", "2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
    ("fe80::1234", "fe80::1234", "fe80::/64"),
    ("not-an-address", "not-an-address", "not-an-address"),
])
def test_client_addresses(address, plain, key):
    assert access.plain_address(address) == plain
    assert access.client_key(address) == key


def test_new_ipv6_addresses_in_one_network_share_the_lockout():
    guesses = access.Guesses()
    for i in range(access._GUESS_LIMIT):
        guesses.wrong(access.client_key(f"2001:db8:1:2::{i + 1:x}"), f"GUESS{i}")
    assert guesses.locked_for(access.client_key("2001:db8:1:2::ffff")) > 590
    assert guesses.locked_for(access.client_key("2001:db8:1:3::1")) == 0
