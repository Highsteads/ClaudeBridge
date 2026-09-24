#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_jsonrpc_robustness.py
# Description: Malformed and awkward JSON-RPC input gets a clean answer for the
#              right request id: an internal fault still names the id, params
#              and arguments of the wrong shape are -32602 (never -32603 with a
#              traceback), a null clientInfo does not fail the handshake, and
#              a null argument means "not given" rather than beating the
#              tool's default.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import logging
import threading
from collections import deque

import pytest

from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager

_LOGGER = logging.getLogger("test-jsonrpc-robustness")
ACCEPT = {"accept": "application/json"}


def _handler(tmp_path, tools=None):
    h = object.__new__(MCPHandler)
    h.logger            = _LOGGER
    h.plugin            = None
    h.scope_manager     = ScopeManager(scopes_file=str(tmp_path / "absent.json"), logger=_LOGGER)
    h.rate_limiter      = RateLimiter(logger=_LOGGER)
    h.tool_cache        = ToolCache(default_ttl=0, logger=_LOGGER)
    h._telemetry_lock   = threading.Lock()
    h._tool_call_log    = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools            = tools or {}
    h._resources        = {}
    h._sessions         = {}
    h._sessions_lock    = threading.Lock()
    h._session_idle_ttl = 24 * 3600
    h._session_max      = 500
    h.entity_index_manager = None
    return h


def _tool(fn, properties=None, required=None):
    return {"description": "test tool",
            "inputSchema": {"type": "object", "properties": properties or {},
                            "required": required or []},
            "function": fn}


def _post(h, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return json.loads(h.handle_request("POST", dict(ACCEPT), body)["content"])


# ── Item 1: the id is always answered ─────────────────────────────────────────

def test_an_internal_fault_is_answered_against_the_request_id(tmp_path, monkeypatch):
    h = _handler(tmp_path)

    def _explode(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(h, "_dispatch_message", _explode)
    reply = _post(h, {"jsonrpc": "2.0", "id": 42, "method": "ping"})
    assert reply["id"] == 42
    assert reply["error"]["code"] == -32603


def test_an_error_with_no_readable_id_carries_id_null(tmp_path):
    h = _handler(tmp_path)
    reply = _post(h, "{not json")
    assert "id" in reply and reply["id"] is None
    assert reply["error"]["code"] == -32700


def test_a_non_object_message_is_invalid_request_not_a_crash(tmp_path):
    h = _handler(tmp_path)
    reply = _post(h, "5")
    assert reply["error"]["code"] == -32600
    assert reply["id"] is None


def test_a_non_string_method_is_invalid_request(tmp_path):
    h = _handler(tmp_path)
    reply = _post(h, {"jsonrpc": "2.0", "id": 3, "method": ["tools/list"]})
    assert reply == {"jsonrpc": "2.0", "id": 3,
                     "error": {"code": -32600, "message": "Invalid Request"}}


# ── Item 3: shapes that used to reach a .get() and raise ──────────────────────

def test_params_as_a_list_is_invalid_params(tmp_path):
    h = _handler(tmp_path)
    reply = _post(h, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": ["x"]})
    assert reply["id"] == 4 and reply["error"]["code"] == -32602


def test_null_client_info_does_not_fail_the_handshake(tmp_path):
    h = _handler(tmp_path)
    reply = _post(h, {"jsonrpc": "2.0", "id": 5, "method": "initialize",
                      "params": {"protocolVersion": MCPHandler.PROTOCOL_VERSION,
                                 "clientInfo": None}})
    assert "error" not in reply
    assert reply["result"]["protocolVersion"] == MCPHandler.PROTOCOL_VERSION


@pytest.mark.parametrize("name", [["list"], {"a": 1}, 7, None])
def test_a_tool_name_that_is_not_a_string_is_invalid_params(tmp_path, name):
    h = _handler(tmp_path)
    reply = h._handle_tools_call(6, {"name": name, "arguments": {}})
    assert reply["id"] == 6 and reply["error"]["code"] == -32602


def test_arguments_that_are_not_an_object_are_invalid_params(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "ok")})
    reply = h._handle_tools_call(7, {"name": "t", "arguments": ["a", "b"]})
    assert reply["error"]["code"] == -32602
    assert "must be a JSON object" in reply["error"]["message"]


def test_a_coercion_fault_is_invalid_params_not_internal_error(tmp_path, monkeypatch):
    import mcp_server.mcp_handler as mod

    def _bad(args, props):
        raise ValueError("cannot read that")

    monkeypatch.setattr(mod, "coerce_to_schema", _bad)
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "ok")})
    reply = h._handle_tools_call(8, {"name": "t", "arguments": {}})
    assert reply["error"]["code"] == -32602
    assert "cannot read that" in reply["error"]["message"]


def test_unicode_digits_reach_the_tool_unchanged(tmp_path):
    seen = {}
    h = _handler(tmp_path, {"t": _tool(lambda **kw: seen.update(kw) or "ok",
                                       properties={"n": {"type": ["integer", "string"]}})})
    reply = h._handle_tools_call(9, {"name": "t", "arguments": {"n": "²"}})
    assert reply["result"]["isError"] is False
    assert seen == {"n": "²"}


# ── Item 3b: null means "not given" ──────────────────────────────────────────

def test_a_null_optional_argument_leaves_the_default_in_charge(tmp_path):
    seen = []

    def set_enabled(enabled=True):
        seen.append(enabled)
        return "ok"

    h = _handler(tmp_path, {"t": _tool(set_enabled, properties={"enabled": {"type": "boolean"}})})
    reply = h._handle_tools_call(10, {"name": "t", "arguments": {"enabled": None}})
    assert reply["result"]["isError"] is False
    assert seen == [True], "a JSON null must not reach the tool and beat its default"


def test_a_null_required_argument_is_refused_by_name(tmp_path):
    called = []
    h = _handler(tmp_path, {"t": _tool(lambda **kw: called.append(kw) or "ok",
                                       properties={"device": {"type": "string"}},
                                       required=["device"])})
    reply = h._handle_tools_call(11, {"name": "t", "arguments": {"device": None}})
    assert reply["error"]["code"] == -32602
    assert "cannot be null" in reply["error"]["message"] and "device" in reply["error"]["message"]
    assert called == []


def test_a_misnamed_null_argument_is_still_reported_as_unknown(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "ok", properties={"value": {"type": "boolean"}})})
    reply = h._handle_tools_call(12, {"name": "t", "arguments": {"enable": None}})
    assert reply["error"]["code"] == -32602
    assert "enable" in reply["error"]["message"]


# ── Item 9: the per-request line is DEBUG, not INFO ──────────────────────────

def test_an_ordinary_request_logs_nothing_at_info(tmp_path, caplog):
    h = _handler(tmp_path)
    with caplog.at_level(logging.DEBUG, logger=_LOGGER.name):
        _post(h, {"jsonrpc": "2.0", "id": 13, "method": "ping"})
    assert [r for r in caplog.records if r.levelno >= logging.INFO] == []
    assert any("ping" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)
