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
#
# These assert the DISPATCHED path, not a level map in isolation. The original
# v2.10.1 test imported _LOG_LEVELS from indigo_data_provider and checked its
# contents — but that module's log_message had no callers, so the map was dead
# code and the live tool (ScriptToolsHandler.log_message) went on passing the
# raw string for another six versions with a green suite. Assert what Indigo
# actually receives.

def test_log_levels_map_to_ints():
    from mcp_server.common.log_levels import LOG_LEVELS, resolve
    assert LOG_LEVELS["WARNING"] == logging.WARNING
    assert LOG_LEVELS["DEBUG"] == logging.DEBUG
    assert LOG_LEVELS["ERROR"] == logging.ERROR
    assert LOG_LEVELS["INFO"] == logging.INFO
    # resolve() tolerates junk, case and already-resolved ints
    assert resolve("warning") == logging.WARNING
    assert resolve(None) == logging.INFO
    assert resolve("nonsense") == logging.INFO
    assert resolve(logging.ERROR) == logging.ERROR


def _live_log_message(monkeypatch, level):
    """Drive the real ScriptToolsHandler.log_message and capture the indigo call."""
    import mcp_server.tools.script_tools.script_tools_handler as sth

    handler = object.__new__(sth.ScriptToolsHandler)
    handler.tool_name = "script_tools"
    handler.logger = logging.getLogger("test")

    calls = []

    class _FakeServer:
        @staticmethod
        def log(message, **kwargs):
            calls.append((message, kwargs))

    monkeypatch.setattr(sth.indigo, "server", _FakeServer, raising=False)
    result = handler.log_message("hello", level)
    assert calls, "indigo.server.log was never called"
    return result, calls[0]


def test_log_message_passes_int_level_not_string(monkeypatch):
    """The regression that hid in dead code: level= must be a logging INT.

    Indigo silently ignores a STRING level and writes the line at Info, so a
    string here means every WARNING/DEBUG the tool claims to have logged was
    really an Info line.
    """
    for name, expected in (("WARNING", logging.WARNING),
                           ("DEBUG",   logging.DEBUG),
                           ("INFO",    logging.INFO)):
        _result, (_msg, kwargs) = _live_log_message(monkeypatch, name)
        assert kwargs["level"] == expected, f"{name} did not resolve to an int"
        assert not isinstance(kwargs["level"], str)


def test_log_message_error_sets_iserror(monkeypatch):
    result, (_msg, kwargs) = _live_log_message(monkeypatch, "ERROR")
    assert kwargs["level"] == logging.ERROR
    assert kwargs.get("isError") is True
    assert result["level"] == "ERROR"


def test_log_message_unknown_level_falls_back_to_info(monkeypatch):
    _result, (_msg, kwargs) = _live_log_message(monkeypatch, "SHOUTY")
    assert kwargs["level"] == logging.INFO


# ── scaffold_automation_script must not emit the broken log helper ───────────

def test_scaffold_template_maps_level_to_int():
    """Every generated script inherits this helper — it must map, not pass through.

    The old template emitted `def log(message, level="INFO")` passing the string
    straight to indigo.server.log, and used level="ERROR" in the top-level
    exception handler, so a scaffolded script logged its own traceback at Info.
    """
    import inspect
    import mcp_server.tools.script_tools.script_tools_handler as sth

    src = inspect.getsource(sth.ScriptToolsHandler.scaffold_automation_script)
    assert "_LOG_LEVELS.get(str(level).upper(), logging.INFO)" in src, \
        "generated log() helper no longer maps the level name to a logging int"
    assert 'level="ERROR"' not in src, \
        "generated script still passes a STRING level to indigo.server.log"


# ── cache invalidation gaps closed ───────────────────────────────────────────

def test_subscription_and_folder_invalidation_wired():
    from mcp_server.common import tool_cache as tc
    assert "subscribe" in tc._INVALIDATION_MAP
    assert "unsubscribe" in tc._INVALIDATION_MAP
    assert "list_subscriptions" in tc._INVALIDATION_MAP["subscribe"]
    assert "create_variable_folder" in tc._INVALIDATION_MAP
    assert "list_variable_folders" in tc._INVALIDATION_MAP["create_variable_folder"]
