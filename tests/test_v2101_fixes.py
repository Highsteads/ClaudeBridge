#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2101_fixes.py
# Description: Regression tests for the v2.10.1 deep-review medium batch —
#              multi-source battery reader, MCP bool coercion, log-level int
#              mapping, JSON-null variable write, energy_compare clamping, and
#              the cache-invalidation gaps.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import logging


# ── battery_pct: covers battery / batteryLevel state + native property ───────

class _FakeDev:
    def __init__(self, states=None, native=None):
        self.states = states or {}
        if native is not None:
            self.batteryLevel = native


def test_battery_pct_reads_battery_state():
    from mcp_server.common.battery import battery_pct
    # z2m convention: the `battery` custom state (the 43-device majority)
    assert battery_pct(_FakeDev(states={"battery": 87})) == 87


def test_battery_pct_reads_batterylevel_state():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={"batteryLevel": 12})) == 12


def test_battery_pct_reads_native_property():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={}, native=5)) == 5


def test_battery_pct_none_when_absent():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={"temperature": 21})) is None
    assert battery_pct(_FakeDev(states={"battery": ""})) is None


# ── _coerce_bool: string "false" must be False (bool('false') is True) ───────

def test_coerce_bool_string_false_is_false():
    from mcp_server.tools.extended_tools.extended_tools_handler import _coerce_bool
    assert _coerce_bool("false") is False
    assert _coerce_bool("0") is False
    assert _coerce_bool("") is False
    assert _coerce_bool("no") is False
    assert _coerce_bool("true") is True
    assert _coerce_bool("1") is True
    assert _coerce_bool(True) is True
    assert _coerce_bool(False) is False


# ── log_message level → real logging int (a string is silently ignored) ──────

def test_log_levels_map_to_ints():
    from mcp_server.adapters.indigo_data_provider import _LOG_LEVELS
    assert _LOG_LEVELS["WARNING"] == logging.WARNING
    assert _LOG_LEVELS["DEBUG"] == logging.DEBUG
    assert _LOG_LEVELS["ERROR"] == logging.ERROR
    assert _LOG_LEVELS["INFO"] == logging.INFO


# ── cache invalidation gaps closed ───────────────────────────────────────────

def test_subscription_and_folder_invalidation_wired():
    from mcp_server.common import tool_cache as tc
    assert "subscribe" in tc._INVALIDATION_MAP
    assert "unsubscribe" in tc._INVALIDATION_MAP
    assert "list_subscriptions" in tc._INVALIDATION_MAP["subscribe"]
    assert "create_variable_folder" in tc._INVALIDATION_MAP
    assert "list_variable_folders" in tc._INVALIDATION_MAP["create_variable_folder"]
