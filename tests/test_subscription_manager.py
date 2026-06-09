#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_subscription_manager.py
# Description: Transition detection — a subscription fires only when its condition
#              crosses from not-matching to matching (not on every change while it
#              stays matched), reverts cancel pending dwell, comparators + entity
#              filtering + any_change + dwell arming behave.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

from mcp_server.webhooks.subscription_manager import SubscriptionManager
from mcp_server.webhooks.subscription_model import Subscription


def _mgr(*subs):
    m = SubscriptionManager()
    for s in subs:
        m.add(s)
    return m


def _dev(dev_id, on, states=None):
    return {"id": dev_id, "name": f"Dev{dev_id}", "deviceTypeId": "relay",
            "onState": on, "states": states or {}}


def test_fires_on_transition_into_match():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          conditions={"onState": True}))
    matches = m.evaluate_device_change(_dev(1, False), _dev(1, True))
    assert len(matches) == 1
    assert matches[0][1].event_type == "device.state_changed"


def test_does_not_fire_while_already_matched():
    # onState stays True; brightness changes (a real change) but the condition was
    # already satisfied -> NOT a transition -> no fire (the "no flood" property).
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          conditions={"onState": True}))
    a = _dev(1, True, {"brightness": 10})
    b = _dev(1, True, {"brightness": 20})
    assert m.evaluate_device_change(a, b) == []


def test_no_fire_when_nothing_changed():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          conditions={"onState": True}))
    assert m.evaluate_device_change(_dev(1, True), _dev(1, True)) == []


def test_comparator_condition_crosses_threshold():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          conditions={"battery": {"lt": 20}}))
    a = _dev(1, True, {"battery": 25})
    b = _dev(1, True, {"battery": 15})
    assert len(m.evaluate_device_change(a, b)) == 1
    # And not again while it stays low
    c = _dev(1, True, {"battery": 12})
    assert m.evaluate_device_change(b, c) == []


def test_entity_id_filter():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          entity_id=5, conditions={"onState": True}))
    assert m.evaluate_device_change(_dev(3, False), _dev(3, True)) == []   # different device
    assert len(m.evaluate_device_change(_dev(5, False), _dev(5, True))) == 1


def test_any_change_fires_on_any_device_change():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="device",
                          conditions={"any_change": True}))
    a = _dev(1, True, {"battery": 50})
    b = _dev(1, True, {"battery": 49})
    assert len(m.evaluate_device_change(a, b)) == 1


def test_variable_transition_and_any_change():
    m = _mgr(
        Subscription(webhook_url="https://x", entity_type="variable",
                     conditions={"value": "on"}),
        Subscription(webhook_url="https://y", entity_type="variable",
                     conditions={"any_change": True}),
    )
    matches = m.evaluate_variable_change(
        {"id": 9, "name": "v", "value": "off"}, {"id": 9, "name": "v", "value": "on"})
    # both the "value==on" transition and the any_change fire
    assert len(matches) == 2


def test_variable_no_change_no_fire():
    m = _mgr(Subscription(webhook_url="https://x", entity_type="variable",
                          conditions={"any_change": True}))
    assert m.evaluate_variable_change(
        {"id": 9, "name": "v", "value": "on"}, {"id": 9, "name": "v", "value": "on"}) == []


def test_dwell_arms_instead_of_firing_immediately():
    recorded = []
    m = SubscriptionManager(dispatch_callback=lambda s, e: recorded.append((s, e)))
    m.add(Subscription(webhook_url="https://x", entity_type="device",
                       entity_id=1, conditions={"onState": True}, duration_seconds=30))
    matches = m.evaluate_device_change(_dev(1, False), _dev(1, True))
    assert matches == []                  # not fired immediately...
    assert m._dwell.pending() == 1        # ...a dwell timer is armed
    # Reverting cancels the pending dwell
    m.evaluate_device_change(_dev(1, True), _dev(1, False))
    assert m._dwell.pending() == 0
    m.shutdown()
