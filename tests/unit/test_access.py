# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Host-name trust, home-network clients and the guessing lockout (web/access.py)."""

from types import SimpleNamespace

import pytest

import xbmc
from web import access


@pytest.fixture(autouse=True)
def own_names(monkeypatch):
    """Replace the box's host name lookups (no resolver is asked); the names are
    looked up afresh.  Every test starts on a box called "coreelec"."""
    def install(hostname, fqdn):
        monkeypatch.setattr(access, "socket", SimpleNamespace(gethostname=hostname, getfqdn=fqdn))
        access._own_names.cache_clear()
    install(lambda: "coreelec", lambda: "coreelec")
    yield install
    access._own_names.cache_clear()


@pytest.fixture(autouse=True)
def own_ipv6(tmp_path, monkeypatch):
    """The box's IPv6 address table in a file of the test's own (empty at
    first), read afresh: write(lines) replaces it."""
    table = tmp_path / "if_inet6"
    table.write_text("")
    monkeypatch.setattr(access, "_IF_INET6", str(table))
    monkeypatch.setattr(access, "_own_networks", access._OwnNetworks())

    def write(*lines):
        table.write_text("".join(line + "\n" for line in lines))
    return write


# Lines of /proc/net/if_inet6: the box's global 2a01:598:1234:5600::10/64,
# and its link-local address.
OWN_GLOBAL = "2a010598123456000000000000000010 02 40 00 80     eth0"
OWN_LINK = "fe80000000000000021122fffe334455 02 40 20 80     eth0"


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
    ("2a00:1450:4001:2:aaaa::1", "2a00:1450:4001:2:aaaa::1", "2a00:1450:4001:2::/64"),
    ("fe80::1234", "fe80::1234", "fe80::1234"),          # at home: on its own
    ("fd12:3456:789a:1::5", "fd12:3456:789a:1::5", "fd12:3456:789a:1::5"),
    ("not-an-address", "not-an-address", "not-an-address"),
])
def test_client_addresses(address, plain, key):
    assert access.plain_address(address) == plain
    assert access.client_key(address) == key


def test_new_ipv6_addresses_in_one_network_share_the_lockout():
    guesses = access.Guesses()
    for i in range(access._GUESS_LIMIT):
        guesses.wrong(access.client_key(f"2a00:1450:4001:2::{i + 1:x}"), f"GUESS{i}")
    assert guesses.locked_for(access.client_key("2a00:1450:4001:2::ffff")) > 590
    assert guesses.locked_for(access.client_key("2a00:1450:4001:3::1")) == 0


def test_a_device_at_home_locks_out_only_itself(own_ipv6):
    own_ipv6(OWN_GLOBAL)
    guesses = access.Guesses()
    for i in range(access._GUESS_LIMIT):
        guesses.wrong(access.client_key("2a01:598:1234:5600::aa"), f"GUESS{i}")
    assert guesses.locked_for(access.client_key("2a01:598:1234:5600::aa")) > 590
    assert guesses.locked_for(access.client_key("2a01:598:1234:5600::bb")) == 0


@pytest.mark.parametrize(("address", "home"), [
    ("127.0.0.1", True), ("::1", True), ("192.168.1.20", True), ("10.0.0.7", True),
    ("172.16.4.2", True), ("::ffff:192.168.1.20", True), ("169.254.1.1", True),
    ("fe80::1", True), ("fd12:3456:789a:1::5", True),
    ("8.8.8.8", False), ("::ffff:8.8.8.8", False), ("2a00:1450:4001:2::1", False),
    ("2a01:598:1234:5600::abcd", False),                 # the box's prefix is not known
    ("not-an-address", False), ("", False),
])
def test_home_network_clients(address, home):
    assert access.home_peer(address) is home


def test_addresses_in_the_boxs_own_ipv6_network_are_at_home(own_ipv6):
    own_ipv6(OWN_LINK, OWN_GLOBAL)
    assert access.home_peer("2a01:598:1234:5600::abcd")
    assert access.home_peer("::1")
    assert not access.home_peer("2a01:598:1234:5601::1")


def test_the_own_networks_are_read_again_after_a_minute(own_ipv6, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(access.time, "monotonic", lambda: now[0])
    assert not access.home_peer("2a01:598:1234:5600::abcd")
    own_ipv6(OWN_GLOBAL)
    now[0] += 59
    assert not access.home_peer("2a01:598:1234:5600::abcd")
    now[0] += 1
    assert access.home_peer("2a01:598:1234:5600::abcd")


@pytest.mark.parametrize("lines", [
    ("zz010598123456000000000000000010 02 40 00 80     eth0",),
    ("2a010598123456000000000000000010 02 zz 00 80     eth0",),
])
def test_an_unreadable_address_table_knows_no_own_networks(own_ipv6, lines):
    own_ipv6(*lines)
    assert not access.home_peer("2a01:598:1234:5600::abcd")
    assert any("own IPv6 networks unknown" in message for _level, message in xbmc.LOG)


def test_a_box_without_an_address_table_knows_no_own_networks(monkeypatch):
    monkeypatch.setattr(access, "_IF_INET6", "/nonexistent/if_inet6")
    assert not access.home_peer("2a01:598:1234:5600::abcd")
    assert access.home_peer("192.168.1.20")


def test_short_lines_in_the_address_table_are_skipped(own_ipv6):
    own_ipv6("2a010598123456000000000000000010 02 40", OWN_GLOBAL)
    assert access.home_peer("2a01:598:1234:5600::abcd")


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


def test_the_lockouts_are_capped_and_the_one_ending_soonest_goes(clock):
    guesses = access.Guesses()
    for i in range(access._MAX_TRACKED + 1):
        clock.now += 1
        address = f"10.3.{i // 250}.{i % 250}"
        for guess in range(access._GUESS_LIMIT):
            guesses.wrong(address, f"GUESS{guess}")
    assert len(guesses._locked) == access._MAX_TRACKED
    assert "10.3.0.0" not in guesses._locked
    assert guesses.locked_for("10.3.1.6") > 0




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
