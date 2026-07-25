#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_cache_external_invalidation.py
# Description: Regression tests for the v2.17.0 cache-staleness fix — a device or
#              variable changed by the real world (wall switch, Z-Wave
#              association, trigger, another plugin) must not keep being served
#              from cache as though it were current.
# Author:      CliveS & Claude Opus 5
# Date:        25-07-2026
# Version:     1.0

import logging

from mcp_server.common.tool_cache import ToolCache

_LOGGER = logging.getLogger("test")


def _cache(ttl=300):
    return ToolCache(default_ttl=ttl, logger=_LOGGER)


def test_device_change_invalidates_device_reads():
    """The bug: a light switched at the wall stayed 'off' in cache for the TTL."""
    c = _cache()
    calls = []

    def compute_off():
        calls.append("off")
        return {"onState": False}

    def compute_on():
        calls.append("on")
        return {"onState": True}

    v, hit = c.get_or_compute("get_device_by_id", {"device_id": 1}, compute_off)
    assert v == {"onState": False} and hit is False

    # Same read again — served from cache, as intended.
    v, hit = c.get_or_compute("get_device_by_id", {"device_id": 1}, compute_off)
    assert hit is True

    # The world moves: deviceUpdated fires for a change we did not make.
    c.note_external_change("device")

    v, hit = c.get_or_compute("get_device_by_id", {"device_id": 1}, compute_on)
    assert hit is False, "served a pre-change value after the device changed"
    assert v == {"onState": True}
    assert c.stale_drops >= 1


def test_variable_change_invalidates_variable_reads():
    c = _cache()
    c.get_or_compute("list_variables", {}, lambda: ["a"])
    _v, hit = c.get_or_compute("list_variables", {}, lambda: ["a"])
    assert hit is True

    c.note_external_change("variable")
    _v, hit = c.get_or_compute("list_variables", {}, lambda: ["a", "b"])
    assert hit is False


def test_device_change_does_not_evict_unrelated_domains():
    """A presence-sensor storm must not flush script or memory caches."""
    c = _cache()
    c.get_or_compute("list_python_scripts", {}, lambda: ["x.py"])
    c.note_external_change("device")
    _v, hit = c.get_or_compute("list_python_scripts", {}, lambda: ["x.py"])
    assert hit is True, "a device change wrongly invalidated an unrelated tool"


def test_home_status_depends_on_both_domains():
    for domain in ("device", "variable"):
        c = _cache()
        c.get_or_compute("home_status", {}, lambda: {"n": 1})
        assert c.get_or_compute("home_status", {}, lambda: {"n": 1})[1] is True
        c.note_external_change(domain)
        assert c.get_or_compute("home_status", {}, lambda: {"n": 2})[1] is False, \
            f"home_status ignored a {domain} change"


def test_change_during_compute_is_not_stored():
    """A result computed across a change is already stale — never cache it."""
    c = _cache()

    def slow_compute():
        # The world moves while we are computing.
        c.note_external_change("device")
        return {"onState": False}

    v, hit = c.get_or_compute("get_device_by_id", {"device_id": 2}, slow_compute)
    assert hit is False and v == {"onState": False}

    # Must NOT have been stored, so the next read recomputes.
    v2, hit2 = c.get_or_compute("get_device_by_id", {"device_id": 2},
                                lambda: {"onState": True})
    assert hit2 is False, "stored a result computed across a real-world change"
    assert v2 == {"onState": True}


def test_note_external_change_is_cheap_and_safe():
    c = _cache()
    c.note_external_change("nonsense")      # unknown domain — ignored, no raise
    before = dict(c.stats()["domain_gen"])
    for _ in range(1000):
        c.note_external_change("device")
    after = c.stats()["domain_gen"]
    assert after["device"] == before["device"] + 1000
    assert after["variable"] == before["variable"]
