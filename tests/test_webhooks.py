#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhooks.py
# Description: Webhook subscriptions: rate-cap drops do not quarantine, a corrupt
#              entity_id fails closed, the feature gate defaults closed, any_change
#              stands alone, max_fires counts successes, dwell timers die with their
#              subscription, a full queue drops and counts, verify_ssl is strict.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_webhook_v282_fixes.py (v2.8.2), test_webhook_redteam_fixes.py
#   (v2.8.1), test_v284_fixes.py (v2.8.4)


from mcp_server.security.egress_guard import Allowlist
from mcp_server.webhooks.subscription_model import Subscription, QUARANTINE_AFTER
from mcp_server.webhooks.subscription_manager import SubscriptionManager
from mcp_server.webhooks.webhook_dispatcher import WebhookDispatcher
from mcp_server.tools.webhooks.webhook_handler import WebhookHandler


# ── v2.8.2 robustness ─────────────────────────────────────────────────────────

def _sub(**kw):
    base = dict(webhook_url="https://example.com/hook", entity_type="device")
    base.update(kw)
    return Subscription(**base)


def test_record_dropped_does_not_quarantine():
    """A global rate-cap drop must leave consecutive_failures at 0 and the
    subscription enabled — one busy sub must not disable a healthy one."""
    s = _sub()
    for _ in range(QUARANTINE_AFTER + 3):
        s.record_dropped("global webhook rate cap reached; delivery dropped")
    assert s.stats["consecutive_failures"] == 0
    assert s.enabled is True
    assert s.stats["last_error"].startswith("global webhook rate cap")


def test_record_failure_still_quarantines():
    """Attributable failures must still quarantine after the threshold."""
    s = _sub()
    for _ in range(QUARANTINE_AFTER):
        s.record_failure("receiver 500", http_status=500)
    assert s.enabled is False


def test_corrupt_present_entity_id_fails_closed():
    """A present-but-unparseable entity_id must disable the subscription, never
    silently become a wildcard (entity_id=None while enabled)."""
    s = Subscription.from_dict({
        "webhook_url": "https://example.com/hook",
        "entity_type": "device",
        "entity_id": "not-a-number",
        "enabled": True,
    })
    assert s.entity_id is None
    assert s.enabled is False, "corrupt scoped id must fail closed, not firehose"


def test_absent_entity_id_is_wildcard_and_enabled():
    """An explicitly absent entity_id is the intended wildcard — stays enabled."""
    s = Subscription.from_dict({
        "webhook_url": "https://example.com/hook",
        "entity_type": "device",
        "enabled": True,
    })
    assert s.entity_id is None
    assert s.enabled is True


def test_string_numeric_entity_id_still_coerced():
    """A valid string id ('123') must still coerce to int and stay enabled."""
    s = Subscription.from_dict({
        "webhook_url": "https://example.com/hook",
        "entity_type": "device",
        "entity_id": "123",
        "enabled": True,
    })
    assert s.entity_id == 123
    assert s.enabled is True


def test_webhook_handler_defaults_gate_closed():
    """A WebhookHandler built without an enabled_provider must refuse create —
    the outbound-egress feature must never default open."""
    from mcp_server.tools.webhooks.webhook_handler import WebhookHandler

    class _Mgr:
        pass

    h = WebhookHandler(_Mgr(), lambda: object(), enabled_provider=None)
    res = h.create_subscription(webhook_url="https://example.com/hook",
                                entity_type="device")
    assert res["success"] is False
    assert "disabled" in res["error"].lower()


# ── v2.8.1 adversarial review ─────────────────────────────────────────────────

def _handler():
    mgr = SubscriptionManager()
    allow = Allowlist.from_entries(["8.8.8.8"])
    # Gate explicitly enabled — these tests exercise validation logic, not the
    # dark-ship default (covered above).
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


def test_verify_ssl_strict_tristate():
    from mcp_server.webhooks.subscription_manager import SubscriptionManager
    from mcp_server.security.egress_guard import Allowlist
    from mcp_server.tools.webhooks.webhook_handler import WebhookHandler

    def handler():
        mgr = SubscriptionManager()
        allow = Allowlist.from_entries(["8.8.8.8"])
        return WebhookHandler(mgr, allowlist_provider=lambda: allow,
                              enabled_provider=lambda: True), mgr

    # A real boolean False is the ONLY thing that disables verification.
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl=False)
    assert mgr.list_all()[0].verify_ssl is False

    # The string "false" must NOT disable it (would silently drop TLS checks).
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl="false")
    assert mgr.list_all()[0].verify_ssl is True

    # An empty string also defaults to verify.
    h, mgr = handler()
    h.create_subscription(webhook_url="https://8.8.8.8/h", entity_type="device",
                          conditions={"any_change": True}, verify_ssl="")
    assert mgr.list_all()[0].verify_ssl is True
