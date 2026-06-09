#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhook_redteam_fixes.py
# Description: Regression tests pinning the confirmed findings fixed after the
#              multi-agent adversarial review (v2.8.1): any_change guard,
#              max_fires counts successes only, from_dict entity_id coercion,
#              wildcard dwell cancel-on-delete, bounded-queue drop+count.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import queue

from mcp_server.security.egress_guard import Allowlist
from mcp_server.webhooks.subscription_model import Subscription
from mcp_server.webhooks.subscription_manager import SubscriptionManager
from mcp_server.webhooks.webhook_dispatcher import WebhookDispatcher
from mcp_server.tools.webhooks.webhook_handler import WebhookHandler


def _handler():
    mgr = SubscriptionManager()
    allow = Allowlist.from_entries(["8.8.8.8"])
    # Gate explicitly enabled — these tests exercise validation logic, not the
    # dark-ship default (covered in test_webhook_v282_fixes).
    return WebhookHandler(mgr, allowlist_provider=lambda: allow,
                          enabled_provider=lambda: True), mgr


# 1. any_change cannot be combined with a state condition (silent-override bug)
def test_any_change_with_other_condition_rejected():
    h, _ = _handler()
    r = h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                              conditions={"any_change": True, "onState": True})
    assert r["success"] is False
    assert "any_change" in r["error"]
    # any_change ALONE is still fine
    ok = h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                               conditions={"any_change": True})
    assert ok["success"] is True


# 2. max_fires must count only SUCCESSES — failures must not self-delete the sub
def test_max_fires_counts_only_successes():
    sub = Subscription(webhook_url="https://x", entity_type="device", max_fires=1)
    sub.record_failure("boom")
    sub.record_failure("boom again")
    assert sub.stats["successful_fires"] == 0      # failures don't count toward max_fires
    assert sub.stats["fires"] == 2                 # but still tracked for display
    sub.record_success(200)
    assert sub.stats["successful_fires"] == 1


# 3. from_dict coerces a string entity_id to int (hand-edited store safety)
def test_from_dict_coerces_string_entity_id():
    sub = Subscription.from_dict({
        "webhook_url": "https://x", "entity_type": "device", "entity_id": "123",
        "conditions": {"onState": True},
    })
    assert sub.entity_id == 123 and isinstance(sub.entity_id, int)
    # a bad value degrades to None rather than crashing
    bad = Subscription.from_dict({"webhook_url": "https://x", "entity_type": "device",
                                  "entity_id": "not-a-number", "conditions": {"x": 1}})
    assert bad.entity_id is None


# 4. Deleting a WILDCARD subscription cancels its dwell timers (orphan fix)
def test_wildcard_subscription_dwell_cancelled_on_delete():
    fired = []
    m = SubscriptionManager(dispatch_callback=lambda s, e: fired.append(s))
    sub = Subscription(webhook_url="https://x", entity_type="device",
                       entity_id=None, conditions={"onState": True}, duration_seconds=30)
    m.add(sub)
    # a change to device 7 arms a dwell keyed "<subid>:7" (per-event entity id)
    m.evaluate_device_change(
        {"id": 7, "name": "D", "onState": False, "states": {}},
        {"id": 7, "name": "D", "onState": True, "states": {}})
    assert m._dwell.pending() == 1
    assert m.delete(sub.subscription_id) is True
    assert m._dwell.pending() == 0                 # cancelled, not orphaned
    m.shutdown()


# 5. Bounded queue drops + counts when full (never blocks the callback thread)
def test_dispatch_drops_when_queue_full():
    d = WebhookDispatcher(allowlist_provider=lambda: Allowlist.from_entries([]),
                          max_queue=1)
    # worker NOT started, so nothing drains the queue
    sub = Subscription(webhook_url="https://x", entity_type="device")
    d.dispatch(sub, object())     # fills the single slot
    d.dispatch(sub, object())     # dropped
    d.dispatch(sub, object())     # dropped
    assert d._dropped == 2
    assert d._queue.qsize() == 1
