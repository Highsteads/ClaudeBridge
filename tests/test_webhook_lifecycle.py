#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webhook_lifecycle.py
# Description: The webhook worker survives a disable -> enable (it used to die
#              on the stale wake-up left by the stop, and deliveries stopped for
#              good), the retries of one event count as ONE failure, a
#              quarantine can be lifted, two saves cannot cross and put back a
#              deleted subscription, and the Host header names no default port.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mcp_server.security.egress_guard import Allowlist
from mcp_server.webhooks.event_model import Event
from mcp_server.webhooks.subscription_manager import SubscriptionManager
from mcp_server.webhooks.subscription_model import QUARANTINE_AFTER, Subscription
from mcp_server.webhooks.webhook_dispatcher import WebhookDispatcher, host_header


@pytest.fixture
def receiver():
    """A local receiver. `hold` blocks the first request until released;
    `status` is what it answers."""
    state = {"bodies": [], "hosts": [], "status": 200, "hold": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            hold = state["hold"]
            if hold is not None:
                state["hold"] = None
                hold.wait(5)
            state["bodies"].append(body)
            state["hosts"].append(self.headers.get("Host"))
            self.send_response(state["status"])
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["port"] = srv.server_address[1]
    yield state
    srv.shutdown()


def _dispatcher(**kw):
    allow = Allowlist.from_entries(["127.0.0.1/32"], http_entries=["127.0.0.1"])
    return WebhookDispatcher(allowlist_provider=lambda: allow, **kw)


def _sub(port, **kw):
    return Subscription(webhook_url=f"http://127.0.0.1:{port}/hook", entity_type="device",
                        entity_id=1, **kw)


def _event(n):
    return Event(event_type="device.state_changed", entity={"id": 1, "name": f"e{n}"})


def _wait_for(predicate, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ── M1: disable -> enable ────────────────────────────────────────────────────

def test_a_stop_during_delivery_then_a_start_still_delivers(receiver):
    d = _dispatcher()
    d.start()
    try:
        release = threading.Event()
        receiver["hold"] = release
        sub = _sub(receiver["port"])
        d.dispatch(sub, _event(1))
        assert _wait_for(lambda: receiver["hold"] is None), "first delivery never started"

        stopper = threading.Thread(target=d.stop)      # disable, mid-delivery
        stopper.start()
        time.sleep(0.2)
        release.set()
        stopper.join(10)

        d.start()                                       # enable again
        d.dispatch(sub, _event(2))
        assert _wait_for(lambda: len(receiver["bodies"]) == 2), \
            "the next event after disable -> enable was never delivered"
        assert b'"e2"' in receiver["bodies"][1]
    finally:
        d.stop()


def test_a_start_straight_after_a_non_waiting_stop_still_delivers(receiver):
    d = _dispatcher()
    d.start()
    try:
        release = threading.Event()
        receiver["hold"] = release
        sub = _sub(receiver["port"])
        d.dispatch(sub, _event(1))
        assert _wait_for(lambda: receiver["hold"] is None)

        started = time.monotonic()
        d.stop(wait=False)                              # the Configure-save path
        assert time.monotonic() - started < 1, "stop(wait=False) held the caller"
        d.start()                                       # old worker still mid-delivery
        release.set()
        d.dispatch(sub, _event(2))
        assert _wait_for(lambda: any(b'"e2"' in b for b in receiver["bodies"])), \
            "dispatch() dropped events after a restart over a live old worker"
    finally:
        d.stop()


def test_a_stop_before_the_first_start_leaves_no_trap(receiver):
    """stop() on a dispatcher that never ran still queues its wake-up. The
    first start() drains nothing (there is no stopped run to clean up), so the
    new worker meets that wake-up and must carry on past it."""
    d = _dispatcher()
    d.stop()
    d.start()
    try:
        d.dispatch(_sub(receiver["port"]), _event(1))
        assert _wait_for(lambda: len(receiver["bodies"]) == 1), \
            "a wake-up left by an earlier stop() killed the new worker"
    finally:
        d.stop()


def test_events_queued_before_a_restart_are_not_delivered_after_it(receiver):
    d = _dispatcher()
    sub = _sub(receiver["port"])
    d.start()
    d.stop()
    d._queue.put_nowait((sub, _event(99)))             # left over from the stopped run
    d.start()
    try:
        d.dispatch(sub, _event(3))
        assert _wait_for(lambda: len(receiver["bodies"]) >= 1)
        time.sleep(0.2)
        assert [b'"e3"' in b for b in receiver["bodies"]] == [True]
    finally:
        d.stop()


# ── M3: one failure per event, and a way back ────────────────────────────────

def test_the_retries_of_one_event_are_one_failure(receiver):
    receiver["status"] = 500
    d = _dispatcher(retry_base_delay=0.01, max_retries=3)
    sub = _sub(receiver["port"])
    d._deliver(sub, _event(1))
    assert len(receiver["bodies"]) == 4, "expected the first try plus three retries"
    assert sub.stats["consecutive_failures"] == 1
    assert sub.stats["errors"] == 1 and sub.stats["fires"] == 1
    assert "after 4 attempts" in sub.stats["last_error"]
    assert sub.enabled is True


def test_quarantine_counts_events_and_can_be_lifted(receiver):
    receiver["status"] = 500
    d = _dispatcher(retry_base_delay=0.0, max_retries=1)
    mgr = SubscriptionManager()
    sub = mgr.add(_sub(receiver["port"]))
    for n in range(QUARANTINE_AFTER - 1):
        d._deliver(sub, _event(n))
    assert sub.enabled is True
    d._deliver(sub, _event(99))
    assert sub.enabled is False and sub.quarantined

    assert mgr.reenable_quarantined() == [sub.subscription_id]
    assert sub.enabled is True and sub.stats["consecutive_failures"] == 0
    assert mgr.watches("device", 1)


def test_a_subscription_off_for_another_reason_is_not_re_enabled():
    mgr = SubscriptionManager()
    corrupt = Subscription.from_dict({"webhook_url": "https://x", "entity_type": "device",
                                      "entity_id": "not-a-number"})
    mgr.add(corrupt)
    assert corrupt.enabled is False
    assert mgr.reenable_quarantined() == []
    assert corrupt.enabled is False


def test_a_4xx_is_not_retried_and_is_one_failure(receiver):
    receiver["status"] = 404
    d = _dispatcher(retry_base_delay=0.0)
    sub = _sub(receiver["port"])
    d._deliver(sub, _event(1))
    assert len(receiver["bodies"]) == 1
    assert sub.stats["consecutive_failures"] == 1
    assert sub.stats["last_error"] == "receiver 404"


# ── M2: saves cannot cross ───────────────────────────────────────────────────

class _SlowStore:
    """The first save blocks until released; every save records what it wrote."""

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.writes = []
        self._first = True

    def save(self, subs):
        snapshot = [s.subscription_id for s in subs]
        if self._first:
            self._first = False
            self.entered.set()
            self.release.wait(5)
        self.writes.append(snapshot)

    def load(self):
        return []


def test_an_older_snapshot_cannot_overwrite_a_delete():
    store = _SlowStore()
    mgr = SubscriptionManager(store=store)
    sub = Subscription(webhook_url="https://x", entity_type="device", entity_id=1)
    with mgr._lock:                      # add without saving, so the slow save is ours
        mgr._subs[sub.subscription_id] = sub

    saver = threading.Thread(target=mgr.save)            # snapshot [sub], then stalls
    saver.start()
    assert store.entered.wait(5)
    deleter = threading.Thread(target=mgr.delete, args=(sub.subscription_id,))
    deleter.start()
    time.sleep(0.3)                      # time for an unlocked delete to write first
    store.release.set()
    saver.join(5)
    deleter.join(5)
    assert store.writes[-1] == [], f"a stale snapshot landed last: {store.writes}"


# ── the watch set the plugin reads on every change ───────────────────────────

def test_watches_follows_adds_deletes_and_wildcards():
    mgr = SubscriptionManager()
    assert not mgr.watches("device", 1)
    one = mgr.add(Subscription(webhook_url="https://x", entity_type="device", entity_id=1))
    assert mgr.watches("device", 1) and not mgr.watches("device", 2)
    assert not mgr.watches("variable", 1)
    mgr.add(Subscription(webhook_url="https://x", entity_type="variable"))
    assert mgr.watches("variable", 12345)
    mgr.delete(one.subscription_id)
    assert not mgr.watches("device", 1)


# ── L7: the Host header ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://hooks.example.com/x", "hooks.example.com"),
    ("https://hooks.example.com:443/x", "hooks.example.com"),
    ("https://hooks.example.com:8443/x", "hooks.example.com:8443"),
    ("http://hooks.example.com/x", "hooks.example.com"),
    ("http://hooks.example.com:8080/x", "hooks.example.com:8080"),
    ("https://[2001:db8::1]/x", "[2001:db8::1]"),
])
def test_host_header_names_only_a_non_default_port(url, expected):
    assert host_header(url) == expected


def test_the_wire_host_header_is_the_computed_one(receiver):
    d = _dispatcher()
    d._deliver(_sub(receiver["port"]), _event(1))
    assert receiver["hosts"] == [f"127.0.0.1:{receiver['port']}"]
