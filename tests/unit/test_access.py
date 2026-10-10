# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Host-name trust and the guessing lockout (web/access.py)."""

from types import SimpleNamespace

import pytest

import xbmc
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


@pytest.mark.parametrize("host", [".", ":8099", "[]:8099", "..."])
def test_a_host_header_without_a_name_is_not_trusted(host):
    assert not access.trusted_host(host)


class _Clock:
    """Stands in for the time module: access only reads time.monotonic()."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(access, "time", fake)
    return fake


def test_the_lockout_is_logged_and_ends_after_ten_minutes(clock):
    guesses = access.Guesses()
    for i in range(access._GUESS_LIMIT):
        guesses.wrong("10.0.0.5", f"GUESS{i}")
    assert xbmc.LOG == [(xbmc.LOGWARNING, "TinyPPI [web]: 10.0.0.5 presented 10 wrong tokens; "
                                          "turning it away for 10 minutes")]
    assert guesses.locked_for("10.0.0.5") == 600
    clock.now += 450
    assert guesses.locked_for("10.0.0.5") == 150
    clock.now += 150
    assert guesses.locked_for("10.0.0.5") == 0


# wrong() restarts an expired window itself, even where the sweep that drops
# expired windows has not run.
@pytest.mark.parametrize("swept", [True, False], ids=["swept", "unswept"])
def test_wrong_tokens_from_an_expired_window_no_longer_count(clock, monkeypatch, swept):
    guesses = access.Guesses()
    if not swept:
        monkeypatch.setattr(guesses, "_forget_expired", lambda now: None)
    for i in range(access._GUESS_LIMIT - 1):
        guesses.wrong("10.0.0.5", f"OLD{i}")
    clock.now += access._GUESS_WINDOW + 1

    for i in range(access._GUESS_LIMIT - 1):
        guesses.wrong("10.0.0.5", f"NEW{i}")
    assert guesses.locked_for("10.0.0.5") == 0
    guesses.wrong("10.0.0.5", "NEW9")
    assert guesses.locked_for("10.0.0.5") == access._LOCKOUT


def test_the_sweep_drops_expired_windows_and_ended_lockouts(clock):
    guesses = access.Guesses()
    for i in range(access._GUESS_LIMIT):
        guesses.wrong("10.0.0.5", f"GUESS{i}")
    guesses.wrong("10.0.0.6", "GUESS")
    guesses.wrong("10.0.0.7", "GUESS")
    assert set(guesses._locked) == {"10.0.0.5"}

    clock.now += access._LOCKOUT + 1
    guesses.wrong("10.0.0.8", "GUESS")

    assert set(guesses._locked) == set()
    assert set(guesses._wrong) == {"10.0.0.8"}


def test_over_the_cap_the_oldest_address_is_forgotten(clock):
    guesses = access.Guesses()
    for i in range(access._MAX_TRACKED):
        clock.now += 1
        guesses.wrong(f"10.1.{i // 250}.{i % 250}", "WRONG")
    clock.now += 1
    guesses.wrong("10.2.0.1", "WRONG")
    assert "10.1.0.0" not in guesses._wrong
    assert {"10.1.0.1", "10.2.0.1"} <= set(guesses._wrong)
    assert len(guesses._wrong) == access._MAX_TRACKED


@pytest.fixture
def own_names(monkeypatch):
    """Replace the box's host name lookups; the names are looked up afresh."""
    def install(hostname, fqdn):
        monkeypatch.setattr(access, "socket", SimpleNamespace(gethostname=hostname, getfqdn=fqdn))
        access._own_names.cache_clear()
    yield install
    access._own_names.cache_clear()


def test_the_boxs_own_names_are_trusted(own_names):
    own_names(lambda: "CoreELEC", lambda: "coreelec.example.org.")
    assert access._own_names() == frozenset({"coreelec", "coreelec.example.org"})
    assert access.trusted_host("CoreELEC.Example.org:8099")
    assert access.trusted_host("coreelec.example.org.")
    assert not access.trusted_host("tv.example.org")


def _unresolvable():
    raise OSError("no host name")


@pytest.mark.parametrize(("hostname", "fqdn", "names"), [
    (_unresolvable, lambda: "kodi.example.net", {"kodi.example.net"}),
    (lambda: "kodi", _unresolvable, {"kodi"}),
    (lambda: "  ", lambda: ".", set()),
    (_unresolvable, _unresolvable, set()),
], ids=["no-hostname", "no-fqdn", "blank", "neither"])
def test_name_lookups_that_fail_or_come_back_empty_are_skipped(own_names, hostname, fqdn, names):
    own_names(hostname, fqdn)
    assert access._own_names() == frozenset(names)
    assert access.trusted_host("kodi.example.net") == ("kodi.example.net" in names)
