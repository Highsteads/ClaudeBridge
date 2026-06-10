#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tool_cache_sweep.py
# Description: The TTL cache used to drop expired entries only when the same
#              key was re-read — a key never requested again sat in the dict
#              forever. The periodic sweep added 10-06-2026 removes lapsed
#              entries on any cache touch; these tests pin that behaviour.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import time

from mcp_server.common.tool_cache import ToolCache


def test_expired_entries_swept_without_reread():
    c = ToolCache(default_ttl=60)
    stale_key = ("home_status", "{}")
    c._store[stale_key] = (time.monotonic() - 10, "stale")   # already expired
    c._last_sweep = time.monotonic() - 120                   # sweep is due
    # Touching the cache with a DIFFERENT key must still evict the stale one.
    c.get_or_compute("list_devices", {}, lambda: "fresh")
    assert stale_key not in c._store


def test_live_entries_survive_the_sweep():
    c = ToolCache(default_ttl=60)
    live_key = ("home_status", "{}")
    c._store[live_key] = (time.monotonic() + 30, "live")
    c._last_sweep = time.monotonic() - 120
    c.get_or_compute("list_devices", {}, lambda: "fresh")
    assert c._store[live_key][1] == "live"
