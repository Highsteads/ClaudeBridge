#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_egress_adversarial.py
# Description: Adversarial battery against the webhook egress firewall — actively
#              tries to defeat it: DNS rebinding (benign at create, internal at
#              send), decimal/octal/hex IP literals smuggled through the resolver,
#              mixed DNS answers, exotic IPv6, userinfo tricks, and verifying the
#              dispatcher never follows a redirect to an internal address.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mcp_server.security.egress_guard import Allowlist, EgressDenied, vet_url
from mcp_server.webhooks.event_model import Event
from mcp_server.webhooks.subscription_model import Subscription
from mcp_server.webhooks.webhook_dispatcher import WebhookDispatcher


def _addrinfo(ips, port=443):
    """Fake socket.getaddrinfo result for the given IP strings."""
    out = []
    for ip in ips:
        fam = 10 if ":" in ip else 2          # AF_INET6 / AF_INET
        sockaddr = (ip, port, 0, 0) if ":" in ip else (ip, port)
        out.append((fam, 1, 6, "", sockaddr))
    return out


def _patch_dns(monkeypatch, mapping):
    """Patch socket.getaddrinfo so host->IPs follows `mapping` (dict host->[ips])."""
    import socket

    def fake(host, port, *a, **k):
        if host in mapping:
            return _addrinfo(mapping[host], port or 443)
        raise socket.gaierror(f"no fake mapping for {host}")
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _denied(url, allow):
    try:
        vet_url(url, allow)
        return False
    except EgressDenied:
        return True


# ── IP literals smuggled in decimal / octal / hex / shorthand ───────────────
# ipaddress.ip_address rejects these, so they're treated as hostnames and go to
# the resolver. Even if the OS resolver decodes them to 127.0.0.1, the resolved
# IP is re-vetted and must be blocked.

@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "0177.0.0.1", "127.1"])
def test_numeric_ip_obfuscation_blocked(monkeypatch, host):
    # Simulate a permissive resolver that decodes the trick to loopback.
    _patch_dns(monkeypatch, {host: ["127.0.0.1"]})
    allow = Allowlist.from_entries([host])         # even if the operator listed the literal string
    assert _denied(f"https://{host}/hook", allow)


# ── Exotic IPv6 forms for loopback / unspecified / mapped ───────────────────

@pytest.mark.parametrize("url", [
    "https://[::1]/h",
    "https://[0:0:0:0:0:0:0:1]/h",          # fully-expanded ::1
    "https://[::ffff:127.0.0.1]/h",         # IPv4-mapped loopback
    "https://[::ffff:7f00:1]/h",            # same, hex form
    "https://[::]/h",                       # unspecified
])
def test_exotic_ipv6_blocked(url):
    assert _denied(url, Allowlist.from_entries([]))


# ── Reserved / special ranges ───────────────────────────────────────────────

@pytest.mark.parametrize("ip", ["0.0.0.0", "100.64.0.1", "224.0.0.1", "169.254.169.254", "192.0.2.1"])
def test_special_ranges_blocked(ip):
    assert _denied(f"https://{ip}/h", Allowlist.from_entries([ip]))


# ── userinfo / scheme tricks ─────────────────────────────────────────────────

def test_userinfo_refused():
    assert _denied("https://8.8.8.8@127.0.0.1/h", Allowlist.from_entries(["8.8.8.8", "127.0.0.1/32"]))

@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://8.8.8.8/", "ftp://8.8.8.8/", "dict://8.8.8.8/"])
def test_nonhttp_schemes_refused(url):
    assert _denied(url, Allowlist.from_entries(["8.8.8.8"]))


# ── Mixed DNS answer: one allowed, one blocked -> whole thing refused ───────

def test_mixed_dns_answer_refused(monkeypatch):
    _patch_dns(monkeypatch, {"evil.example.com": ["93.184.216.34", "127.0.0.1"]})
    allow = Allowlist.from_entries(["evil.example.com"])
    assert _denied("https://evil.example.com/h", allow)


# ── Hostname allow-listed but resolving to an internal IP -> refused ────────

def test_allowlisted_name_resolving_internal_is_refused(monkeypatch):
    _patch_dns(monkeypatch, {"rebind.example.com": ["192.168.100.160"]})
    allow = Allowlist.from_entries(["rebind.example.com"])   # name allowed...
    assert _denied("https://rebind.example.com/h", allow)    # ...but IP is internal -> blocked


# ── DNS REBINDING: benign at create, internal at send -> dispatcher drops ───

def test_dns_rebinding_dropped_at_send_time(monkeypatch):
    # At create time the host resolves to a public IP and is allow-listed by name.
    _patch_dns(monkeypatch, {"rebind.example.com": ["93.184.216.34"]})
    allow = Allowlist.from_entries(["rebind.example.com"])
    # create-time vet passes
    assert vet_url("https://rebind.example.com/h", allow)

    # Now the attacker flips DNS to loopback. Send-time vet must catch it.
    _patch_dns(monkeypatch, {"rebind.example.com": ["127.0.0.1"]})
    sub = Subscription(webhook_url="https://rebind.example.com/h",
                       entity_type="device", entity_id=1)
    d = WebhookDispatcher(allowlist_provider=lambda: allow)
    d.start()
    try:
        d.dispatch(sub, Event(event_type="device.state_changed", entity={"id": 1}))
        time.sleep(0.8)
        assert sub.stats["consecutive_failures"] >= 1
        assert "egress" in (sub.stats["last_error"] or "")
    finally:
        d.stop()


# ── Redirect to an internal address is NOT followed ─────────────────────────

def test_redirect_to_internal_not_followed():
    # A receiver that 302-redirects to a loopback URL. The dispatcher must treat
    # the 3xx as a failure and never chase it.
    hit = {"followed": False}

    class Redirector(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            # Drain the request body first so the client cleanly receives our
            # status (an unread body would RST the socket and mask the 3xx).
            self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            if self.path == "/internal":
                hit["followed"] = True          # would only happen if a redirect was chased
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            else:
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/internal")
                self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), Redirector)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        allow = Allowlist.from_entries(["127.0.0.1/32"], http_entries=["127.0.0.1"])
        sub = Subscription(webhook_url=f"http://127.0.0.1:{port}/hook",
                           entity_type="device", entity_id=1)
        d = WebhookDispatcher(allowlist_provider=lambda: allow)
        d.start()
        try:
            d.dispatch(sub, Event(event_type="device.state_changed", entity={"id": 1}))
            time.sleep(0.8)
            assert hit["followed"] is False                 # redirect was NOT chased
            assert "redirect" in (sub.stats["last_error"] or "").lower()
        finally:
            d.stop()
    finally:
        srv.shutdown()


# ── Case / trailing-dot normalisation doesn't bypass the allow-list ─────────

def test_trailing_dot_and_case(monkeypatch):
    _patch_dns(monkeypatch, {"hooks.example.com": ["93.184.216.34"]})
    allow = Allowlist.from_entries(["hooks.example.com"])
    # trailing dot + upper-case must still match the allow-list entry
    assert vet_url("https://Hooks.Example.com./h", allow)
