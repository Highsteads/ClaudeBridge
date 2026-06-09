#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhook_dispatcher.py
# Description: The webhook dispatcher must (a) deliver an HMAC-signed POST to an
#              opted-in target, and (b) DROP a non-allowlisted target at send time
#              (the SSRF boundary) — recording a failure, never hitting the wire.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mcp_server.security.egress_guard import Allowlist
from mcp_server.webhooks.event_model import Event
from mcp_server.webhooks.subscription_model import Subscription
from mcp_server.webhooks.webhook_dispatcher import WebhookDispatcher


@pytest.fixture
def capture_server():
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            captured["body"] = self.rfile.read(n)
            captured["headers"] = dict(self.headers)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield captured, port
    srv.shutdown()


def _wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return False


def test_delivers_signed_post_to_opted_in_target(capture_server):
    captured, port = capture_server
    # Opt loopback in explicitly (the escape hatch) so the happy path can run.
    # Opt loopback in via a CIDR (the only hard-block escape hatch) so the happy path can run.
    allow = Allowlist.from_entries(["127.0.0.1/32"], http_entries=["127.0.0.1"])
    d = WebhookDispatcher(allowlist_provider=lambda: allow)
    d.start()
    try:
        sub = Subscription(webhook_url=f"http://127.0.0.1:{port}/hook",
                           entity_type="device", entity_id=1)
        ev = Event(event_type="device.state_changed", entity={"id": 1, "name": "Test"})
        d.dispatch(sub, ev)
        assert _wait_for(lambda: "body" in captured), "event was not delivered"

        h = captured["headers"]
        ts = h["X-ClaudeBridge-Timestamp"]
        expect = "sha256=" + hmac.new(
            sub.signing_key.encode(), (ts + ".").encode() + captured["body"], hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(h["X-ClaudeBridge-Signature"], expect)
        assert h.get("X-Event-Id")
        assert json.loads(captured["body"])["event_type"] == "device.state_changed"
        assert sub.stats["last_http_status"] == 200
        assert sub.stats["consecutive_failures"] == 0
    finally:
        d.stop()


def test_drops_non_allowlisted_target_at_send_time(capture_server):
    captured, port = capture_server
    # EMPTY allowlist: the same loopback URL must be dropped, server never hit.
    d = WebhookDispatcher(allowlist_provider=lambda: Allowlist.from_entries([]))
    d.start()
    try:
        sub = Subscription(webhook_url=f"http://127.0.0.1:{port}/hook",
                           entity_type="device", entity_id=2)
        ev = Event(event_type="device.state_changed", entity={"id": 2, "name": "X"})
        d.dispatch(sub, ev)
        # Give the worker time to process and drop.
        assert not _wait_for(lambda: "body" in captured, timeout=1.0), "should NOT have delivered"
        assert sub.stats["consecutive_failures"] >= 1
        assert "egress" in (sub.stats["last_error"] or "")
    finally:
        d.stop()


def test_oversized_payload_is_dropped_not_sent(capture_server):
    captured, port = capture_server
    # Opt loopback in via a CIDR (the only hard-block escape hatch) so the happy path can run.
    allow = Allowlist.from_entries(["127.0.0.1/32"], http_entries=["127.0.0.1"])
    d = WebhookDispatcher(allowlist_provider=lambda: allow)
    d.start()
    try:
        sub = Subscription(webhook_url=f"http://127.0.0.1:{port}/hook",
                           entity_type="device", entity_id=3, max_body_bytes=200)
        big = Event(event_type="device.state_changed",
                    entity={"id": 3, "name": "Big", "blob": "x" * 5000})
        d.dispatch(sub, big)
        assert not _wait_for(lambda: "body" in captured, timeout=1.0)
        assert "exceeds cap" in (sub.stats["last_error"] or "")
    finally:
        d.stop()
