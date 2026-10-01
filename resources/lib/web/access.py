# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Who may use the dashboard, beyond holding the token.

Two things the token alone does not cover:

- **Guessing it.**  A token is eight characters out of thirty-two, which is a
  great many guesses -- but a request is cheap, and nothing used to stop one
  machine on the network from making them all night.  An address that keeps
  presenting tokens that are wrong is shut out for a while (``Guesses``).

- **A web page reading it through somebody's browser.**  With *Require the
  token for reading too* off, which is how the add-on ships, the readings and
  the library answer anyone who asks.  A page on the internet cannot ask
  directly -- the browser keeps it to its own origin -- but it can point its own
  host name at the box's address once the page has loaded (DNS rebinding) and
  then ask as if it were the box.  The one thing that gives it away is the
  name it asked for, which it cannot leave out: the ``Host`` header carries
  the attacker's own domain.  So a read that comes in under a name no home
  network would use is treated as if reading needed the token (``trusted_host``).
"""

import hashlib
import ipaddress
import socket
import threading
import time

import xbmc

from core.log import channel

# How many different wrong tokens one address may present inside the window
# before it is shut out, and for how long it then is.
#
# Different ones, because a page holding a token that has since been replaced
# presents the same wrong one again and again -- with every poster on a wall
# of them -- and that is somebody to ask for the new token, not somebody to
# lock out.  Somebody guessing presents a new one every time.  Ten to a window
# leaves plenty of room for a token mistyped on a phone, and is nowhere near
# what working through 32 ** 8 of them would take.
_GUESS_LIMIT  = 10
_GUESS_WINDOW = 600.0
_LOCKOUT      = 600.0

# How many addresses are remembered at once.  A home network has a handful;
# the cap only keeps something sending from a great many from growing this
# without end.
_MAX_TRACKED = 256

# Host names a home network gives its own machines, and which no public DNS
# answers for -- so no page on the internet can have its own name end in one.
# A single label (``coreelec``, ``localhost``) and an address typed as it is
# are just as safe; see ``trusted_host``.
#
# ``fritz.box`` and ``speedport.ip`` are the names the two most common routers
# here hand out: the first is the vendor's own domain, the second sits under a
# top-level name that does not exist.
_PRIVATE_SUFFIXES = (
    ".local", ".localhost", ".localdomain", ".lan", ".home", ".home.arpa",
    ".internal", ".intranet", ".corp", ".private",
    ".fritz.box", ".speedport.ip",
)


_log = channel("web", xbmc.LOGINFO)


class Guesses:
    """Remembers wrong tokens per address, and shuts out the one guessing.

    Shared by every request thread, hence the lock.  Nothing here is ever
    written to disk: a restart forgets every lock-out, which costs a guesser a
    restart of somebody else's Kodi to get round.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # address -> (start of its window, the wrong tokens seen in it)
        self._wrong: dict[str, tuple[float, set[bytes]]] = {}
        # address -> when its lock-out ends
        self._locked: dict[str, float] = {}

    def locked_for(self, address: str) -> float:
        """Seconds until *address* may try again, 0 when it may now."""
        now = time.monotonic()
        with self._lock:
            until = self._locked.get(address, 0.0)
            if until <= now:
                self._locked.pop(address, None)
                return 0.0
            return until - now

    def wrong(self, address: str, presented: str) -> None:
        """Note that *address* presented *presented* and it was not the token.

        No token at all is not a guess: it is a page that has not been given
        one yet, which is asked for it rather than counted against.
        """
        if not presented:
            return
        # Kept as a digest rather than as typed: this is a list of near-misses
        # for a secret, and it has no need to hold any of them.
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
        """Drop what no longer counts, and the oldest if there is still too
        much.  Called with the lock held."""
        for address in [a for a, (start, _) in self._wrong.items()
                        if now - start > _GUESS_WINDOW]:
            del self._wrong[address]
        for address in [a for a, until in self._locked.items() if until <= now]:
            del self._locked[address]
        while len(self._wrong) >= _MAX_TRACKED:
            oldest = min(self._wrong, key=lambda a: self._wrong[a][0])
            del self._wrong[oldest]


def _own_names() -> frozenset[str]:
    """The names this box goes by itself, lower-cased."""
    names = set()
    for lookup in (socket.gethostname, socket.getfqdn):
        try:
            name = lookup().strip().lower().rstrip(".")
        except OSError:
            continue
        if name:
            names.add(name)
    return frozenset(names)


_OWN_NAMES: frozenset[str] | None = None


def trusted_host(header: str) -> bool:
    """Whether a request's ``Host`` header names the box the way only somebody
    on its own network would.

    Trusted: no header at all (no browser leaves it out), an address typed as
    it is, a name of a single label, one of the box's own names, and any name
    under a suffix no public DNS answers for (``_PRIVATE_SUFFIXES``).  Anything
    else may well be the box reached through a name somebody gave it -- a
    dynamic DNS name, say -- and still works, only with the token, the same as
    with *Require the token for reading too* switched on.
    """
    global _OWN_NAMES

    host = (header or "").strip().lower()
    if not host:
        return True
    # The port, and the brackets an IPv6 address is written in.
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
    if _OWN_NAMES is None:
        _OWN_NAMES = _own_names()
    return host in _OWN_NAMES
