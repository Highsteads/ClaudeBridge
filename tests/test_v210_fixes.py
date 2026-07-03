#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v210_fixes.py
# Description: Regression tests for the v2.10.0 deep-review fix batch — the
#              return-vs-raise cluster (error results not cached, counted or
#              leaked), the /health bearer-token mask, the get_dependencies
#              deep-convert, and the enable/disable_action_group removal.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import json
import logging

_LOG = logging.getLogger("test-v210")


# ── H3: /health must not expose raw bearer tokens ────────────────────────────

def test_rate_limiter_snapshot_masks_bearer_tokens():
    from mcp_server.security import RateLimiter
    rl = RateLimiter(per_minute=100, per_day=5000, logger=_LOG)
    secret = "sk-live-SUPERSECRETTOKEN-abcdef"
    rl.check(secret, {"read"})
    snap = rl.snapshot()
    # The raw token must NOT appear as a key…
    assert secret not in snap
    # …but a stable, non-reversible label must, carrying the counts.
    assert len(snap) == 1
    (masked_key, counts), = snap.items()
    assert masked_key.startswith("token-")
    assert secret[:8] not in masked_key
    assert counts["minute"] == 1


def test_rate_limiter_snapshot_keeps_anonymous_readable():
    from mcp_server.security import RateLimiter
    rl = RateLimiter(per_minute=100, per_day=5000, logger=_LOG)
    rl.check("anonymous", {"read"})
    assert "anonymous" in rl.snapshot()


# ── return-vs-raise cluster: error results detected, not cached, scrubbed ────

def test_result_ok_detects_error_payloads():
    from mcp_server.mcp_handler import MCPHandler
    assert MCPHandler._result_ok('{"success": true, "devices": []}') is True
    assert MCPHandler._result_ok('{"success": false, "error": "boom"}') is False
    assert MCPHandler._result_ok('{"error": "not found"}') is False
    # A plain (non-JSON, non-dict) string is a normal result, not an error.
    assert MCPHandler._result_ok("just some text") is True
    assert MCPHandler._result_ok('{"success": true, "error": null}') is True


def test_scrub_error_result_removes_raw_text():
    from mcp_server.mcp_handler import MCPHandler
    raw = '{"success": false, "error": "SMTP auth failed for user bob@example.com via mail.host:587"}'
    scrubbed = json.loads(MCPHandler._scrub_error_result(raw))
    assert scrubbed["success"] is False
    assert "bob@example.com" not in scrubbed["error"]
    assert "event log" in scrubbed["error"]


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


# ── H10: get_dependencies deep-converts nested lists ─────────────────────────

def test_deps_to_plain_deep_converts_nested_lists():
    from mcp_server.tools.extended_tools.extended_tools_handler import _deps_to_plain
    # Emulate getDependencies() shape: a mapping of bucket -> list of {ID,Name}.
    deps = {
        "devices":     [{"ID": 1, "Name": "Kitchen Light"}],
        "triggers":    [],
        "schedules":   [{"ID": 5, "Name": "Nightly"}],
    }
    out = _deps_to_plain(deps)
    assert out["devices"] == [{"ID": 1, "Name": "Kitchen Light"}]
    assert out["schedules"][0]["Name"] == "Nightly"
    assert out["triggers"] == []
    # Crucially, the nested lists survive a JSON round-trip as real arrays,
    # not the {} the encoder produced for a raw indigo.List.
    assert json.loads(json.dumps(out))["devices"][0]["ID"] == 1


# ── H9: enable/disable_action_group fully removed ────────────────────────────

def test_action_group_enable_disable_removed_from_scopes():
    from mcp_server.security import scope_manager as sm
    every = sm.READ_TOOLS | sm.WRITE_TOOLS | sm.ADMIN_TOOLS
    assert "enable_action_group" not in every
    assert "disable_action_group" not in every
    # duplicate_action_group is a real IOM op and must remain.
    assert "duplicate_action_group" in sm.WRITE_TOOLS


def test_action_group_enable_disable_removed_from_invalidation_map():
    from mcp_server.common import tool_cache as tc
    assert "enable_action_group" not in tc._INVALIDATION_MAP
    assert "disable_action_group" not in tc._INVALIDATION_MAP
