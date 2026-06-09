#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhook_v282_fixes.py
# Description: Regressions for the v2.8.2 webhook-robustness fixes:
#              - record_dropped() (global rate-cap) must NOT quarantine a sub
#              - a corrupt PRESENT entity_id must fail closed (disabled), not
#                widen a scoped subscription to a wildcard firehose
#              - WebhookHandler with no enabled_provider must refuse create
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

from mcp_server.webhooks.subscription_model import Subscription, QUARANTINE_AFTER


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
