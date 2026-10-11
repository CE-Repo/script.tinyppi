# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dashboard access checks beyond the token itself.

- **Guessing:** an address presenting too many different wrong tokens is
  locked out for a while (``Guesses``).
- **Home network:** reading without the token is for clients on the home
  network only (``home_peer``).  The server also listens on IPv6, where the
  box may have addresses the internet can reach.
- **IPv6:** a device beyond the home network can pick any address in its
  /64 at will, so its guesses and connections count per /64 network; at
  home every address counts on its own (``client_key``).
- **DNS rebinding:** with *Require the token for reading too* off (the
  default), a web page could point its own host name at the box and read
  through the visitor's browser.  Its ``Host`` header still carries the
  attacker's domain, so reads under a name no home network uses require the
  token (``trusted_host``).
"""

import hashlib
import ipaddress
import socket
import threading
import time
from functools import cache

import xbmc
from core.log import channel

# Different wrong tokens allowed per address and window, and the lockout.
# Only distinct tokens count: a page with an outdated token repeats the same
# one on every request and should be asked for the new one, not locked out.
# Ten allows for typos while making 32 ** 8 guesses hopeless.
_GUESS_LIMIT  = 10
_GUESS_WINDOW = 600.0
_LOCKOUT      = 600.0

# Cap on tracked addresses, in the windows and in the lockouts each, so many
# senders cannot grow either table forever.  Over the cap a lockout gives way
# to the one ending soonest: it is the least protection lost, and a sender
# with that many addresses has that many fresh windows anyway.
_MAX_TRACKED = 256

# The box's own IPv6 addresses with their prefix lengths (Linux), and how
# long the networks read from it are kept: a router may hand out a new
# prefix at any time.
_IF_INET6 = "/proc/net/if_inet6"
_OWN_NETWORKS_TTL = 60.0

# Home-network suffixes no public DNS answers for, so no internet page can
# use them (see trusted_host).  ``fritz.box`` and ``speedport.ip`` are what
# the most common German routers hand out.
_PRIVATE_SUFFIXES = (
    ".local", ".localhost", ".localdomain", ".lan", ".home", ".home.arpa",
    ".internal", ".intranet", ".corp", ".private",
    ".fritz.box", ".speedport.ip",
)


_log = channel("web", xbmc.LOGINFO)


def plain_address(address: str) -> str:
    """Return *address* with an IPv4-mapped IPv6 address as plain IPv4.

    The dual-stack server sees IPv4 clients as ``::ffff:a.b.c.d``.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return str(parsed.ipv4_mapped)
    return address


def _read_own_networks() -> frozenset[ipaddress.IPv6Network]:
    """Return the networks of the box's global IPv6 addresses (none if unknown)."""
    networks = set()
    try:
        with open(_IF_INET6, encoding="ascii") as table:
            for line in table:
                # address, interface index, prefix length, scope, flags, name
                fields = line.split()
                if len(fields) < 4 or fields[3] != "00":    # global scope only
                    continue
                address = ipaddress.IPv6Address(int(fields[0], 16))
                networks.add(ipaddress.IPv6Network((address, int(fields[2], 16)),
                                                   strict=False))
    except (OSError, ValueError) as exc:
        _log(f"own IPv6 networks unknown: {exc}", xbmc.LOGDEBUG)
    return frozenset(networks)


class _OwnNetworks:
    """The box's own IPv6 networks, read again once a minute."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._read_at = float("-inf")
        self._networks: frozenset[ipaddress.IPv6Network] = frozenset()

    def get(self) -> frozenset[ipaddress.IPv6Network]:
        now = time.monotonic()
        with self._lock:
            if now - self._read_at >= _OWN_NETWORKS_TTL:
                self._networks = _read_own_networks()
                self._read_at = now
            return self._networks


_own_networks = _OwnNetworks()


def home_peer(address: str) -> bool:
    """Return whether *address* is a client on the home network.

    Loopback, private and link-local addresses (IPv4 and IPv6 ULA), and
    addresses in one of the box's own IPv6 networks: home devices often
    reach the box over global IPv6 addresses from the same prefix.
    """
    try:
        parsed = ipaddress.ip_address(plain_address(address))
    except ValueError:
        return False
    if parsed.is_loopback or parsed.is_private or parsed.is_link_local:
        return True
    return (isinstance(parsed, ipaddress.IPv6Address)
            and any(parsed in network for network in _own_networks.get()))


def client_key(address: str) -> str:
    """Return what guesses and connection caps count *address* under.

    IPv4 addresses count on their own, and so do IPv6 ones on the home
    network, where one device locking itself out must not lock out the
    house.  Other IPv6 addresses count per /64, the block one device can
    draw new addresses from (privacy extensions).
    """
    address = plain_address(address)
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(parsed, ipaddress.IPv6Address) and not home_peer(address):
        return str(ipaddress.IPv6Network((parsed, 64), strict=False))
    return address


class Guesses:
    """Track wrong tokens per address and lock out guessers.

    Shared by all request threads (hence the lock); kept in memory only.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # address -> (window start, wrong token digests in it)
        self._wrong: dict[str, tuple[float, set[bytes]]] = {}
        # address -> lockout end
        self._locked: dict[str, float] = {}

    def locked_for(self, address: str) -> float:
        """Return the seconds until *address* may try again (0 if now)."""
        now = time.monotonic()
        with self._lock:
            until = self._locked.get(address, 0.0)
            if until <= now:
                self._locked.pop(address, None)
                return 0.0
            return until - now

    def wrong(self, address: str, presented: str) -> None:
        """Record that *address* presented the wrong token *presented*.

        An empty token is not a guess (the page simply has none yet).
        """
        if not presented:
            return
        # Store a digest only; near-misses of a secret are not kept.
        digest = hashlib.sha256(presented.encode("utf-8", "replace")).digest()[:8]
        now = time.monotonic()
        with self._lock:
            self._forget_expired(now)
            start, seen = self._wrong.get(address, (now, set()))
            if now - start > _GUESS_WINDOW:
                start, seen = now, set()
            seen.add(digest)
            if len(seen) < _GUESS_LIMIT:
                self._wrong[address] = (start, seen)
                return
            self._wrong.pop(address, None)
            self._locked[address] = now + _LOCKOUT
        _log(f"{address} presented {_GUESS_LIMIT} wrong tokens; turning it away "
             f"for {int(_LOCKOUT // 60)} minutes", xbmc.LOGWARNING)

    def _forget_expired(self, now: float) -> None:
        """Drop expired entries and, over the caps, the oldest (lock held)."""
        for address in [a for a, (start, _) in self._wrong.items()
                        if now - start > _GUESS_WINDOW]:
            del self._wrong[address]
        for address in [a for a, until in self._locked.items() if until <= now]:
            del self._locked[address]
        while len(self._wrong) >= _MAX_TRACKED:
            oldest = min(self._wrong, key=lambda a: self._wrong[a][0])
            del self._wrong[oldest]
        while len(self._locked) >= _MAX_TRACKED:
            ending = min(self._locked, key=self._locked.__getitem__)
            del self._locked[ending]


@cache
def _own_names() -> frozenset[str]:
    """Return this box's own host names, lower-cased (looked up once)."""
    names = set()
    for lookup in (socket.gethostname, socket.getfqdn):
        try:
            name = lookup().strip().lower().rstrip(".")
        except OSError:
            continue
        if name:
            names.add(name)
    return frozenset(names)


def trusted_host(header: str) -> bool:
    """Return whether the ``Host`` header can only come from the home network.

    Trusted: no header (browsers always send one), an IP address, a single
    label, the box's own names, or a ``_PRIVATE_SUFFIXES`` name.  Other
    names (e.g. dynamic DNS) still work, but reading then needs the token.
    """
    host = (header or "").strip().lower()
    if not host:
        return True
    # Strip the port and IPv6 brackets.
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    host = host.rstrip(".")
    if not host:
        return False

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "." not in host or host.endswith(_PRIVATE_SUFFIXES):
        return True
    return host in _own_names()
