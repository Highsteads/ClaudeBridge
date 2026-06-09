#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhook_handler.py
# Description: The 3 webhook tools — create must vet the URL through the egress
#              firewall at create time (deny-all on empty allow-list, refuse a
#              non-allow-listed host), reveal the signing key exactly once, and
#              list must never leak secrets.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

from mcp_server.security.egress_guard import Allowlist
from mcp_server.webhooks.subscription_manager import SubscriptionManager
from mcp_server.tools.webhooks.webhook_handler import WebhookHandler


def _handler(allow_entries=None):
    mgr = SubscriptionManager()
    allow = Allowlist.from_entries(allow_entries or [])
    return WebhookHandler(mgr, allowlist_provider=lambda: allow), mgr


def test_create_denied_when_allowlist_empty():
    h, _ = _handler([])
    r = h.create_subscription(webhook_url="https://8.8.8.8/hook",
                              entity_type="device", conditions={"onState": True})
    assert r["success"] is False
    assert "allow-list is empty" in r["error"]


def test_create_refuses_non_allowlisted_host():
    h, _ = _handler(["1.1.1.1"])   # allow a different IP
    r = h.create_subscription(webhook_url="https://8.8.8.8/hook",
                              entity_type="device", conditions={"onState": True})
    assert r["success"] is False
    assert "refused" in r["error"]


def test_create_refuses_ssrf_target_even_if_only_entry():
    # Operator can't accidentally allow loopback by listing the host — the IP
    # gate still blocks it unless an extra_cidr opts the range in.
    h, _ = _handler(["127.0.0.1"])   # ip-literal entry, but it's loopback
    r = h.create_subscription(webhook_url="https://127.0.0.1/hook",
                              entity_type="device", conditions={"onState": True})
    assert r["success"] is False


def test_create_succeeds_for_allowlisted_target_and_reveals_key_once():
    h, mgr = _handler(["8.8.8.8"])
    r = h.create_subscription(webhook_url="https://8.8.8.8/hook",
                              entity_type="device", conditions={"onState": True})
    assert r["success"] is True
    assert r["signing_key"]                         # revealed once
    assert mgr.count() == 1
    # the embedded subscription view must NOT carry secrets
    assert "signing_key" not in r["subscription"]
    assert r["subscription"]["auth_token"] == ""


def test_list_redacts_secrets():
    h, mgr = _handler(["8.8.8.8"])
    h.create_subscription(webhook_url="https://8.8.8.8/hook", entity_type="device",
                          conditions={"onState": True}, auth_token="super-secret")
    listing = h.list_subscriptions()
    assert listing["success"] and listing["count"] == 1
    sub = listing["subscriptions"][0]
    assert "signing_key" not in sub
    assert sub["auth_token"] == "***"               # redacted, not the real token


def test_validation_errors():
    h, _ = _handler(["8.8.8.8"])
    assert h.create_subscription(webhook_url="", entity_type="device",
                                 conditions={"x": 1})["success"] is False
    assert h.create_subscription(webhook_url="https://8.8.8.8/", entity_type="thing",
                                 conditions={"x": 1})["success"] is False
    assert h.create_subscription(webhook_url="https://8.8.8.8/", entity_type="device",
                                 conditions={})["success"] is False
    # dwell + any_change is rejected
    bad = h.create_subscription(webhook_url="https://8.8.8.8/", entity_type="device",
                                conditions={"any_change": True}, duration_seconds=30)
    assert bad["success"] is False
    # bad int
    assert h.create_subscription(webhook_url="https://8.8.8.8/", entity_type="device",
                                 conditions={"onState": True}, entity_id="abc")["success"] is False


def test_delete():
    h, mgr = _handler(["8.8.8.8"])
    r = h.create_subscription(webhook_url="https://8.8.8.8/hook", entity_type="device",
                              conditions={"onState": True})
    sid = r["subscription_id"]
    assert h.delete_subscription(sid)["success"] is True
    assert mgr.count() == 0
    assert h.delete_subscription(sid)["success"] is False   # already gone
