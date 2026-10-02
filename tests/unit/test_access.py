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
