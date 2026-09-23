#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_log_message.py
# Description: log_message hands Indigo a logging INT level, never a string.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2101_fixes.py (v2.10.1)


import logging


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
