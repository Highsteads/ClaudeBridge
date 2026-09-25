#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    origin_guard.py
# Description: The Origin check the MCP Streamable HTTP transport requires of
#              every server, against DNS rebinding: a request whose Origin
#              names a host that is not this Mac or the Indigo server is refused.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

"""
Validate the Origin header of an MCP request.

A web page on any site can make the browser POST to a server on the local
network. The browser adds an Origin header naming the page's site, and that is
the one thing the page cannot forge. So a request that carries an Origin must
come from a page served by this Mac (localhost, 127.0.0.1, ::1, its own names
and addresses) or by the Indigo web server itself (the address Indigo reports,
and its Reflector). Anything else is refused with 403.

A request with NO Origin is let through: that is every client that is not a
browser — the bundled proxy, mcp-remote, curl — and the access key still
guards it. The request's own Host header is deliberately not trusted: in a DNS
rebinding attack the attacker's page and the Host header name the same
hostile domain, so matching one against the other would let it straight in.
"""

import ipaddress
import socket
import threading
import time
from typing import Callable, Iterable, Optional, Set
from urllib.parse import urlsplit

try:
    import indigo
except ImportError:      # unit tests run outside the plugin host
    indigo = None

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _host_of(url: str) -> Optional[str]:
    try:
        host = urlsplit(str(url or "").strip()).hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: Optional[str], own_hosts: Iterable[str]) -> bool:
    """True if a request with this Origin header may proceed. None or blank
    means no Origin was sent: not a browser, so allowed."""
    if origin is None or not str(origin).strip():
        return True
    host = _host_of(origin)
    if not host:
        return False          # "null" (a sandboxed page, a file) or junk
    if host in LOOPBACK_NAMES or _is_loopback(host):
        return True
    return host in {h.lower() for h in own_hosts}


def discover_own_hosts() -> Set[str]:
    """This Mac's names and addresses, and the hosts Indigo's web server is
    reached by. Every lookup is best effort: one that fails adds nothing."""
    hosts: Set[str] = set(LOOPBACK_NAMES)
    try:
        name = socket.gethostname().lower()
        if name:
            hosts.add(name)
            base = name[:-len(".local")] if name.endswith(".local") else name
            hosts.update({base, f"{base}.local"})
            for info in socket.getaddrinfo(name, None):
                hosts.add(str(info[4][0]).lower())
    except (OSError, UnicodeError):
        pass
    if indigo is not None:
        for getter in ("getWebServerURL", "getReflectorURL"):
            try:
                host = _host_of(getattr(indigo.server, getter)() or "")
            except Exception:
                host = None
            if host and isinstance(host, str):
                hosts.add(host)
    return hosts


class OriginGuard:
    """origin_allowed() against this server's own hosts, looked up once and
    refreshed every REFRESH_SECONDS (an address can change under DHCP)."""

    REFRESH_SECONDS = 300.0

    def __init__(self, discover: Callable[[], Set[str]] = discover_own_hosts):
        self._discover = discover
        self._hosts: Set[str] = set()
        self._at = 0.0
        self._lock = threading.Lock()

    def own_hosts(self) -> Set[str]:
        with self._lock:
            now = time.monotonic()
            if not self._hosts or now - self._at > self.REFRESH_SECONDS:
                try:
                    self._hosts = set(self._discover())
                except Exception:
                    self._hosts = set(LOOPBACK_NAMES)
                self._at = now
            return self._hosts

    def allowed(self, origin: Optional[str]) -> bool:
        if origin is None or not str(origin).strip():
            return True
        host = _host_of(origin)
        if host and (host in LOOPBACK_NAMES or _is_loopback(host)):
            return True       # no lookup needed for the common case
        return origin_allowed(origin, self.own_hosts())
