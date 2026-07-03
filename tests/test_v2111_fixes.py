#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2111_fixes.py
# Description: Regression tests for the v2.11.1 deferred-medium cleanup —
#              numeric-aware state equality, cache invalidate-during-compute
#              guard, search-refresh wiring, and get_devices_by_type limiting.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import logging

_LOG = logging.getLogger("test-v2111")


# ── #36 state_filter: eq/ne are numeric-aware ────────────────────────────────

def test_loose_eq_numeric_string_vs_number():
    from mcp_server.common.state_filter import StateFilter
    assert StateFilter._loose_eq("72.5", 72.5) is True
    assert StateFilter._loose_eq("20", 20) is True
    assert StateFilter._loose_eq("on", "on") is True
    assert StateFilter._loose_eq("on", "off") is False
    assert StateFilter._loose_eq(None, 5) is False


def test_state_filter_eq_matches_stringy_numeric_state():
    from mcp_server.common.state_filter import StateFilter
    entity = {"id": 1, "states": {"temperature": "21.5"}}
    # eq against a NUMBER must match a numeric string state
    assert StateFilter.matches_state(entity, {"temperature": {"eq": 21.5}}) is True
    assert StateFilter.matches_state(entity, {"temperature": {"ne": 30}}) is True
    # simple-equality form too
    assert StateFilter.matches_state(entity, {"temperature": 21.5}) is True


# ── #35 cache: a mutation during compute prevents caching the stale result ───

def test_cache_skips_store_when_generation_bumped_during_compute():
    from mcp_server.common.tool_cache import ToolCache
    cache = ToolCache(default_ttl=60, logger=_LOG)

    calls = {"n": 0}

    def _compute():
        calls["n"] += 1
        # Simulate a mutation landing WHILE this read computes.
        cache.invalidate_for_tool("device_turn_on")
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


# ── #43 search refresh wired for structure-changing tools ────────────────────

def test_search_refresh_tools_set():
    from mcp_server.mcp_handler import MCPHandler
    s = MCPHandler._SEARCH_REFRESH_TOOLS
    for t in ("delete_device", "rename_device", "variable_create", "variable_delete",
              "execute_indigo_python", "run_script"):
        assert t in s, t
    # a pure device on/off must NOT trigger a full index rebuild
    assert "device_turn_on" not in s
