#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tool_registry_consistency.py
# Description: Cross-file consistency net for the tool registry. Tool metadata
#              lives in four places (mcp_handler registration, scope_manager
#              classification, tool_cache invalidation map, README table); only
#              the scope side had an automated check. These tests pin the rest:
#              registration and classification must match exactly, every
#              cacheable tool must be invalidated by at least one mutator OR be
#              consciously TTL-only, and the invalidation map may reference
#              only real, mutating, cacheable names.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import importlib.util
import os

from conftest import SERVER_PLUGIN

from mcp_server.common.tool_cache import (
    CACHEABLE_TOOLS,
    _CLEAR_ALL_TOOLS,
    _INVALIDATION_MAP,
)
from mcp_server.security.scope_manager import ADMIN_TOOLS, READ_TOOLS, WRITE_TOOLS


# Reuse the README generator's AST parsers — identical extraction logic, so this
# test and `generate_tool_doc.py --check` can never disagree about the registry.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "generate_tool_doc",
    os.path.join(_REPO_ROOT, "scripts", "generate_tool_doc.py"),
)
_gtd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gtd)

_HANDLER_PATH = os.path.join(SERVER_PLUGIN, "mcp_server", "mcp_handler.py")
_SCOPE_PATH   = os.path.join(SERVER_PLUGIN, "mcp_server", "security", "scope_manager.py")

REGISTERED = set(_gtd.parse_tools(_gtd._read(_HANDLER_PATH)))
CLASSIFIED = set(_gtd.parse_scope_sets(_gtd._read(_SCOPE_PATH)))

_BUCKET_UNION = set()
for _bucket in _INVALIDATION_MAP.values():
    _BUCKET_UNION |= _bucket

# Cacheable tools whose ONLY freshness mechanism is the TTL — aggregates over
# slow-changing or external data where no single mutator maps cleanly onto
# them. This list is a conscious decision, not an omission: a NEW cacheable
# tool must either appear in an _INVALIDATION_MAP bucket or be added here
# deliberately, otherwise test_cacheable_coverage fails.
TTL_ONLY_CACHEABLE = {
    "energy_compare", "energy_daily_summary", "energy_log_days", "energy_status",
    "find_conflicts", "find_large_files", "find_orphaned_plugin_data",
    "heating_status", "security_status", "system_health",
    # list_subscriptions removed in v2.10.1 — subscribe/unsubscribe now invalidate it.
}


# ── Registration ↔ classification ─────────────────────────────────────────────

def test_every_registered_tool_is_classified():
    unclassified = REGISTERED - CLASSIFIED
    assert not unclassified, (
        f"Registered in mcp_handler.py but missing from READ/WRITE/ADMIN_TOOLS "
        f"(would fail closed to admin at runtime): {sorted(unclassified)}"
    )


def test_every_classified_tool_is_registered():
    stale = CLASSIFIED - REGISTERED
    assert not stale, (
        f"Classified in scope_manager.py but not registered in mcp_handler.py "
        f"(stale entry or typo): {sorted(stale)}"
    )


def test_registry_is_nonempty_sanity():
    # Guards against the AST parse silently matching nothing after a refactor
    # of the registration pattern — an empty set would make the two equality
    # tests above pass vacuously.
    assert len(REGISTERED) >= 100, f"only {len(REGISTERED)} tools parsed — extraction broken?"


# ── Cache invalidation coverage ───────────────────────────────────────────────

def test_cacheable_coverage():
    uncovered = CACHEABLE_TOOLS - _BUCKET_UNION
    unexpected = uncovered - TTL_ONLY_CACHEABLE
    assert not unexpected, (
        f"Cacheable tools not invalidated by any mutator and not in the "
        f"TTL_ONLY_CACHEABLE allowlist — add them to an _INVALIDATION_MAP "
        f"bucket or consciously allowlist them: {sorted(unexpected)}"
    )
    # Both directions: an allowlisted tool that gains bucket coverage (or stops
    # being cacheable) should be removed from the allowlist.
    redundant = TTL_ONLY_CACHEABLE - uncovered
    assert not redundant, (
        f"TTL_ONLY_CACHEABLE entries that are now covered by a bucket or no "
        f"longer cacheable — prune them: {sorted(redundant)}"
    )


def test_invalidation_map_keys_are_registered_mutators():
    keys = set(_INVALIDATION_MAP) | _CLEAR_ALL_TOOLS
    unregistered = keys - REGISTERED
    assert not unregistered, (
        f"_INVALIDATION_MAP/_CLEAR_ALL_TOOLS name tools that are not "
        f"registered (typo or removed tool): {sorted(unregistered)}"
    )
    not_mutators = keys - (WRITE_TOOLS | ADMIN_TOOLS)
    assert not not_mutators, (
        f"_INVALIDATION_MAP/_CLEAR_ALL_TOOLS keys must be WRITE or ADMIN "
        f"tools (a READ tool never invalidates): {sorted(not_mutators)}"
    )


def test_invalidation_bucket_members_are_cacheable():
    not_cacheable = _BUCKET_UNION - CACHEABLE_TOOLS
    assert not not_cacheable, (
        f"Invalidation buckets reference tools that are never cached "
        f"(typo or stale entry): {sorted(not_cacheable)}"
    )


def test_cacheable_tools_are_read_scoped():
    # Caching a mutator would replay its side effects' stale view AND skip the
    # mutation on a cache hit — only READ tools may be cacheable.
    non_read = CACHEABLE_TOOLS - READ_TOOLS
    assert not non_read, (
        f"CACHEABLE_TOOLS must all be READ-scoped: {sorted(non_read)}"
    )
