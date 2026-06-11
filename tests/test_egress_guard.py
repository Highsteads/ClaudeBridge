#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_egress_guard.py
# Description: The webhook egress firewall must default-deny and block every SSRF
#              class (loopback / private / link-local / metadata / IPv4-mapped /
#              bare-IP / non-https / credentials-in-URL), while permitting only
#              explicitly opted-in hosts, IPs, and CIDRs.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import pytest

from mcp_server.security.egress_guard import Allowlist, EgressDenied, vet_url


def _denied(url, allow):
    try:
        vet_url(url, allow)
        return False
    except EgressDenied:
        return True


EMPTY = Allowlist.from_entries([])


# ── default-deny blocks every SSRF target ───────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://127.0.0.1/hook",            # loopback
    "https://192.168.77.20/hook",        # private (an arbitrary LAN host)
    "http://169.254.169.254/latest/",    # cloud metadata
    "https://[::1]/hook",                # IPv6 loopback
    "https://[::ffff:127.0.0.1]/hook",   # IPv4-mapped loopback
    "https://10.0.0.5/hook",             # RFC1918
    "https://8.8.8.8/hook",              # bare public IP not opted in
    "file:///etc/passwd",                # non-http scheme
])
def test_empty_allowlist_denies(url):
    assert _denied(url, EMPTY)


def test_credentials_in_url_refused():
    allow = Allowlist.from_entries(["8.8.8.8"])
    assert _denied("https://user:pass@8.8.8.8/hook", allow)


# ── explicit opt-in escape hatches ──────────────────────────────────────────

def test_extra_cidr_allows_lan_host():
    allow = Allowlist.from_entries(["192.168.77.0/24"])
    assert not _denied("https://192.168.77.50/hook", allow)


def test_ip_literal_allowlist_is_exact():
    allow = Allowlist.from_entries(["8.8.8.8"])
    assert not _denied("https://8.8.8.8/hook", allow)
    assert _denied("https://1.1.1.1/hook", allow)   # a different IP is still denied


def test_http_requires_separate_optin():
    # On the general allowlist but NOT the http allowlist -> https only.
    allow = Allowlist.from_entries(["192.168.77.0/24"])
    assert _denied("http://192.168.77.50/hook", allow)
    allow2 = Allowlist.from_entries(["192.168.77.0/24"], http_entries=["192.168.77.50"])
    assert not _denied("http://192.168.77.50/hook", allow2)


# ── host-pattern matching rules ─────────────────────────────────────────────

def test_wildcard_matches_subdomain_only():
    from mcp_server.security.egress_guard import _host_matches
    pats = {"*.example.com"}
    assert _host_matches("hooks.example.com", pats)
    assert not _host_matches("example.com", pats)                 # not the bare domain
    assert not _host_matches("example.com.attacker.net", pats)    # not a suffix attack


def test_exact_host_match():
    from mcp_server.security.egress_guard import _host_matches
    assert _host_matches("hooks.slack.com", {"hooks.slack.com"})
    assert not _host_matches("evil.com", {"hooks.slack.com"})


# ── IPv4-mapped normalisation in the deny gate ──────────────────────────────

def test_ipv4_mapped_is_unwrapped_and_blocked():
    import ipaddress
    from mcp_server.security.egress_guard import _ip_is_denied
    assert _ip_is_denied(ipaddress.ip_address("::ffff:127.0.0.1"))
    assert _ip_is_denied(ipaddress.ip_address("::ffff:169.254.169.254"))
    assert not _ip_is_denied(ipaddress.ip_address("8.8.8.8"))
