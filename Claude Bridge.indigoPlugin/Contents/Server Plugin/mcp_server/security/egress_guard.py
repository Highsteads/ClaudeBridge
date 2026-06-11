"""
Egress firewall for the outbound webhook feature.

A webhook lets a caller register a URL that ClaudeBridge will POST device/variable
state to. That is both a data-egress channel and a Server-Side Request Forgery
(SSRF) vector — without a guard, a caller could point a subscription at
http://127.0.0.1:8176/ (IWS itself), http://192.168.x/ (the LAN/router), or
http://169.254.169.254/ (cloud metadata) and have the plugin fire authenticated
POSTs at it. This module is the default-deny firewall that stops that.

Design stance (matches ClaudeBridge's deny-by-default ScopeManager):
  * Empty allowlist  => every target refused.
  * Validate TWICE   => create-time (UX) AND send-time (the real boundary, because
                        DNS can rebind between the two).
  * Connect to the IP you validated => vet_url returns the resolved IPs so the
                        caller can pin the connection and the HTTP client can't
                        re-resolve to a different address.
  * ipaddress is the single source of truth => never string-compare against
                        "127.0.0.1"; normalise every host/literal through it so
                        octal/hex/decimal/IPv4-mapped tricks can't smuggle a
                        blocked address past the gate.

Original ClaudeBridge implementation, stdlib only (ipaddress, socket, urllib.parse).
"""

import ipaddress
import socket
from typing import List, Optional, Sequence, Set
from urllib.parse import urlsplit


class EgressDenied(Exception):
    """Raised when a webhook target is not permitted. The message is safe to
    surface to the caller (it names the reason, not any secret)."""


# Redundant, auditable hard-block list. `is_global`/`is_private` etc. already
# catch these, but keeping explicit nets means the control is reviewable and
# does not silently change if a Python release revises is_global's definition.
_HARD_BLOCK_NETS = [
    ipaddress.ip_network(c) for c in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # RFC1918 private
        "127.0.0.0/8", "::1/128",                          # loopback
        "169.254.0.0/16", "fe80::/10",                     # link-local
        "169.254.169.254/32", "fd00:ec2::254/128",         # cloud metadata
        "0.0.0.0/8", "::/128",                             # unspecified / "this host"
        "100.64.0.0/10",                                   # carrier-grade NAT
    )
]


class Allowlist:
    """A set of approved webhook destinations.

    Entries are auto-classified: anything that parses as a CIDR goes to
    extra_cidrs, anything that parses as a bare IP goes to ip_literals, and the
    rest are treated as host patterns (exact FQDN or leading-wildcard *.domain).
    `http_entries` are the subset for which plain (non-TLS) http is permitted.
    """

    def __init__(
        self,
        hosts: Set[str],
        ip_literals: Set[str],
        extra_cidrs: List[ipaddress._BaseNetwork],
        http_hosts: Set[str],
    ):
        self.hosts = hosts
        self.ip_literals = ip_literals
        self.extra_cidrs = extra_cidrs
        self.http_hosts = http_hosts

    def is_empty(self) -> bool:
        return not (self.hosts or self.ip_literals or self.extra_cidrs)

    @classmethod
    def from_entries(
        cls,
        entries: Sequence[str],
        http_entries: Optional[Sequence[str]] = None,
    ) -> "Allowlist":
        hosts: Set[str] = set()
        ip_literals: Set[str] = set()
        extra_cidrs: List[ipaddress._BaseNetwork] = []
        for raw in entries or ():
            e = (raw or "").strip().lower()
            if not e:
                continue
            if "/" in e:
                try:
                    extra_cidrs.append(ipaddress.ip_network(e, strict=False))
                    continue
                except ValueError:
                    continue  # ignore a malformed CIDR rather than fail open
            try:
                ip = ipaddress.ip_address(e.strip("[]"))
                ip_literals.add(str(_unmap(ip)))
                continue
            except ValueError:
                pass
            hosts.add(e.rstrip("."))
        http_hosts = {(h or "").strip().lower().rstrip(".") for h in (http_entries or ()) if (h or "").strip()}
        return cls(hosts, ip_literals, extra_cidrs, http_hosts)


def _unmap(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """Collapse an IPv4-mapped IPv6 address (::ffff:127.0.0.1) to its embedded
    IPv4 so it can't smuggle a blocked v4 address past a v6 'looks global' check."""
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        return ip.ipv4_mapped
    return ip


def _ip_is_denied(ip: ipaddress._BaseAddress) -> bool:
    """True if this address is non-global / private / loopback / etc."""
    ip = _unmap(ip)
    if (not ip.is_global) or ip.is_loopback or ip.is_link_local \
            or ip.is_private or ip.is_multicast or ip.is_reserved \
            or ip.is_unspecified:
        return True
    return any(ip in net for net in _HARD_BLOCK_NETS)


def _ip_in_extra_cidrs(ip: ipaddress._BaseAddress, allowlist: Allowlist) -> bool:
    """True if the IP falls in an operator-listed extra CIDR. This is the ONLY
    way a hard-blocked (private/loopback/link-local) range becomes reachable —
    deliberately CIDR-only so a bare ip_literals entry can't punch a hole in the
    hard block (you must knowingly opt a whole range in, e.g. 192.168.1.50/32)."""
    ip = _unmap(ip)
    return any(ip in net for net in allowlist.extra_cidrs)


def _ip_literal_listed(ip: ipaddress._BaseAddress, allowlist: Allowlist) -> bool:
    """True if this exact IP is in the operator's ip_literals list. Grants a
    specific (global) IP target past the 'must be on the allow-list' gate, but
    does NOT override the hard block — that needs an extra_cidrs entry."""
    return str(_unmap(ip)) in allowlist.ip_literals


def _host_matches(host: str, patterns: Set[str]) -> bool:
    """Exact-host or strict leading-wildcard (*.domain) match. The wildcard
    matches a sub-domain of `domain` only — never `domain` itself, and never via
    substring (so '*.example.com' does NOT match 'example.com.attacker.net')."""
    if host in patterns:
        return True
    for p in patterns:
        if p.startswith("*."):
            suffix = p[1:]  # ".example.com"
            domain = p[2:]  # "example.com"
            if host.endswith(suffix) and host != domain and len(host) > len(suffix):
                return True
    return False


def vet_url(url: str, allowlist: Allowlist, resolve: bool = True) -> List[ipaddress._BaseAddress]:
    """Validate a webhook URL against the allowlist and the SSRF firewall.

    Returns the list of vetted, connect-ready resolved IPs (pin the connection to
    one of these). Raises EgressDenied with a caller-safe reason on any problem.
    Call at create-time AND immediately before every delivery.
    """
    p = urlsplit(url)

    # ── scheme + credentials ──
    if p.scheme not in ("https", "http"):
        raise EgressDenied(f"scheme {p.scheme!r} not permitted (https only; http only for allow-listed hosts)")
    if p.username or p.password:
        raise EgressDenied("credentials embedded in the URL are not permitted")

    host = p.hostname
    if not host:
        raise EgressDenied("URL has no host")
    host = host.rstrip(".").lower()

    # Is the host an IP literal? (decide before IDNA — literals must not be idna-encoded)
    is_literal = False
    try:
        literal_ip = ipaddress.ip_address(host.strip("[]"))
        is_literal = True
    except ValueError:
        literal_ip = None
        # A DNS name: IDNA-encode so a punycode/homograph host can't dodge an
        # exact-host allowlist entry. Reject anything that isn't a clean hostname.
        try:
            host = host.encode("idna").decode("ascii")
        except Exception:
            raise EgressDenied(f"host {host!r} is not a valid hostname")

    # ── scheme policy for plain http ──
    if p.scheme == "http" and host not in allowlist.http_hosts:
        raise EgressDenied(f"plain http to {host!r} not permitted; add it to the http allow-list")

    name_allowed = (not is_literal) and _host_matches(host, allowlist.hosts)

    # ── resolve and vet EVERY address ──
    if is_literal:
        candidates = [literal_ip]
    else:
        port = p.port or (443 if p.scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise EgressDenied(f"host {host!r} did not resolve: {e}")
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        if not candidates:
            raise EgressDenied(f"host {host!r} resolved to no usable addresses")

    vetted: List[ipaddress._BaseAddress] = []
    for ip in candidates:
        cidr_allowed = _ip_in_extra_cidrs(ip, allowlist)      # the ONLY hard-block override
        listed = cidr_allowed or _ip_literal_listed(ip, allowlist)
        # Hard SSRF gate first — a non-global address is refused unless the
        # operator opted its RANGE in via allow_extra_cidrs (not just ip_literals).
        if _ip_is_denied(ip) and not cidr_allowed:
            raise EgressDenied(
                f"host {host!r} resolves to {ip} which is non-global/blocked; "
                f"opt the range in via allow_extra_cidrs to permit it"
            )
        # IP-literal targets must be explicitly listed (by IP or CIDR).
        if is_literal and not listed:
            raise EgressDenied(f"IP-literal target {ip} is not in the IP allow-list")
        # Named targets must match a host pattern OR be an explicitly-listed IP.
        if (not is_literal) and (not name_allowed) and (not listed):
            raise EgressDenied(f"host {host!r} is not on the allow-list")
        vetted.append(_unmap(ip))

    return vetted
