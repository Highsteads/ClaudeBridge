#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tool_cache.py
# Description: The read-tool cache: error results are never stored, a mutation during
#              a compute stops the stale result being stored, and every mutator
#              drops the listings it changes.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v210_fixes.py, test_v2101_fixes.py, test_v2111_fixes.py,
#   test_v2201_medium_fixes.py


import logging

_LOG = logging.getLogger("test-tool-cache")


# ── error results are not cached ─────────────────────────────────────────────

def test_tool_cache_does_not_store_error_results():
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)
    calls = {"n": 0}

    def _compute_error():
        calls["n"] += 1
        return '{"success": false, "error": "transient"}'

    ok = lambda r: '"success": false' not in r and '"error"' not in r
    # First call computes an error; it must NOT be cached.
    r1, hit1 = cache.get_or_compute("home_status", {}, _compute_error, cache_ok=ok)
    assert hit1 is False
    # Second identical call must recompute (not serve the cached error).
    r2, hit2 = cache.get_or_compute("home_status", {}, _compute_error, cache_ok=ok)
    assert hit2 is False
    assert calls["n"] == 2


def test_tool_cache_still_caches_good_results():
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)
    calls = {"n": 0}

    def _compute_ok():
        calls["n"] += 1
        return '{"success": true, "value": 1}'

    ok = lambda r: '"success": false' not in r
    cache.get_or_compute("home_status", {}, _compute_ok, cache_ok=ok)
    _, hit = cache.get_or_compute("home_status", {}, _compute_ok, cache_ok=ok)
    assert hit is True
    assert calls["n"] == 1


# ── #35 cache: a mutation during compute prevents caching the stale result ───

def test_cache_skips_store_when_generation_bumped_during_compute():
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)

    calls = {"n": 0}

    def _compute():
        calls["n"] += 1
        # Simulate a mutation landing WHILE this read computes.
        cache.invalidate_for_tool("device_control")
        return '{"success": true, "value": %d}' % calls["n"]

    # First call computes AND a mutation bumps the generation mid-compute → not stored
    r1, hit1 = cache.get_or_compute("home_status", {}, _compute)
    assert hit1 is False
    # Second call must recompute (the stale result was not cached)
    r2, hit2 = cache.get_or_compute("home_status", {}, _compute)
    assert hit2 is False
    assert calls["n"] == 2


def test_cache_normal_store_still_works():
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)
    calls = {"n": 0}

    def _compute():
        calls["n"] += 1
        return '{"success": true}'

    cache.get_or_compute("home_status", {}, _compute)
    _, hit = cache.get_or_compute("home_status", {}, _compute)
    assert hit is True and calls["n"] == 1


# ── cache invalidation gaps closed ───────────────────────────────────────────

def test_folder_invalidation_wired():
    from mcp_server.common import tool_cache as tc
    assert "create_folder" in tc._INVALIDATION_MAP
    assert "list_variable_folders" in tc._INVALIDATION_MAP["create_folder"]


# ── Cache invalidation must cover every mutator ──────────────────────────────

def test_update_writers_invalidate_their_caches():
    """Triggers/schedules have no domain counter, so nothing else drops their
    buckets — a renamed trigger read stale for the whole TTL."""
    from mcp_server.common.tool_cache import _INVALIDATION_MAP

    tool = "update_automation"
    assert tool in _INVALIDATION_MAP, f"{tool} invalidates nothing"
    for listing in ("list_action_groups", "audit"):
        assert listing in _INVALIDATION_MAP[tool], f"{tool} leaves {listing} stale"


def test_trigger_and_schedule_lists_are_never_cached():
    """A trigger or schedule changed in the Indigo client reaches no change
    callback here, so a cached list would be stale for the whole TTL."""
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)
    for name in ("list_triggers", "list_schedules"):
        cache.get_or_compute(name, {}, lambda: '{"success": true, "n": 1}')
        assert cache.get_or_compute(name, {}, lambda: "fresh") == ("fresh", False), name


def test_set_enabled_drops_the_cached_audit():
    """audit(check='home') counts disabled triggers and schedules; the check
    straight after set_enabled must see the change."""
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)
    args = {"check": "home"}
    cache.get_or_compute("audit", args, lambda: '{"success": true, "disabled_triggers": 0}')
    assert cache.get_or_compute("audit", args, lambda: "stale")[1] is True
    assert cache.invalidate_for_tool("set_enabled") == 1
    assert cache.get_or_compute("audit", args, lambda: "fresh") == ("fresh", False)


# ── enable/disable_action_group fully removed ────────────────────────────────

def test_action_group_enable_disable_removed_from_invalidation_map():
    from mcp_server.common import tool_cache as tc
    assert "enable_action_group" not in tc._INVALIDATION_MAP
    assert "disable_action_group" not in tc._INVALIDATION_MAP
