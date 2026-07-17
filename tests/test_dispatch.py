#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_dispatch.py
# Description: Behavioural tests for the tool-call dispatch chokepoint
#              (MCPHandler._handle_tools_call): scope enforcement on a live
#              dispatch, required-argument validation (-32602), sensitive-tool
#              error scrubbing, rate limiting, and the happy-path response
#              shape. The handler is built skeletally (object.__new__) so no
#              vector store, runtime_config or Indigo server is needed.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import json
import logging
import threading
from collections import deque

from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager

_LOGGER = logging.getLogger("test-dispatch")


def _make_handler(tmp_path, scopes_data=None, tools=None, per_minute=120):
    """Skeletal MCPHandler with only the attributes _handle_tools_call uses."""
    scopes_file = str(tmp_path / "scopes.json")
    if scopes_data is not None:
        (tmp_path / "scopes.json").write_text(
            json.dumps(scopes_data), encoding="utf-8"
        )
    h = object.__new__(MCPHandler)
    h.logger          = _LOGGER
    h.scope_manager   = ScopeManager(scopes_file=scopes_file, logger=_LOGGER)
    h.rate_limiter    = RateLimiter(per_minute=per_minute, per_day=5_000,
                                    admin_multiplier=1.0, logger=_LOGGER)
    h.tool_cache      = ToolCache(default_ttl=0, logger=_LOGGER)
    h._emitter_local  = threading.local()
    h._telemetry_lock = threading.Lock()
    h._tool_call_log  = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools          = tools or {}
    return h


def _tool(fn, required=None, properties=None):
    return {
        "description": "test tool",
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
        "function": fn,
    }


_READONLY_SCOPES = {"tokens": {"phone": {"name": "phone-app", "scopes": ["read"]}}}


# ── Routing & validation ──────────────────────────────────────────────────────

def test_unknown_tool_returns_32602(tmp_path):
    h = _make_handler(tmp_path)
    resp = h._handle_tools_call(1, {"name": "no_such_tool", "arguments": {}})
    assert resp["error"]["code"] == -32602
    assert "Unknown tool" in resp["error"]["message"]


def test_missing_required_argument_returns_32602_naming_the_field(tmp_path):
    h = _make_handler(tmp_path, tools={
        "device_turn_on": _tool(lambda **kw: "ok", required=["device_id"]),
    })
    resp = h._handle_tools_call(2, {"name": "device_turn_on", "arguments": {}})
    assert resp["error"]["code"] == -32602
    assert "device_id" in resp["error"]["message"]


# ── Scope enforcement through the live dispatch path ──────────────────────────

def test_read_token_denied_on_write_tool(tmp_path):
    called = []
    h = _make_handler(tmp_path, scopes_data=_READONLY_SCOPES, tools={
        "device_turn_on": _tool(lambda **kw: called.append(1) or "ok"),
    })
    resp = h._handle_tools_call(
        3, {"name": "device_turn_on", "arguments": {"device_id": 1}},
        headers={"authorization": "Bearer phone"},
    )
    assert resp["error"]["code"] == -32099
    assert "requires scope 'write'" in resp["error"]["message"]
    assert not called, "tool function must never run on a scope denial"


def test_unclassified_tool_fails_closed_to_admin_in_dispatch(tmp_path):
    # A registered-but-unclassified tool must be unreachable by a read token —
    # the fail-closed default exercised through the real dispatch path.
    h = _make_handler(tmp_path, scopes_data=_READONLY_SCOPES, tools={
        "a_brand_new_unclassified_tool": _tool(lambda **kw: "ok"),
    })
    resp = h._handle_tools_call(
        4, {"name": "a_brand_new_unclassified_tool", "arguments": {}},
        headers={"authorization": "Bearer phone"},
    )
    assert resp["error"]["code"] == -32099
    assert "requires scope 'admin'" in resp["error"]["message"]


def test_read_token_allowed_on_read_tool(tmp_path):
    h = _make_handler(tmp_path, scopes_data=_READONLY_SCOPES, tools={
        "list_devices": _tool(lambda **kw: "[]"),
    })
    resp = h._handle_tools_call(
        5, {"name": "list_devices", "arguments": {}},
        headers={"authorization": "Bearer phone"},
    )
    assert "error" not in resp
    assert resp["result"]["content"][0]["text"] == "[]"


# ── Error scrubbing ───────────────────────────────────────────────────────────

def test_sensitive_tool_error_is_scrubbed_from_client(tmp_path):
    def _boom(**kw):
        raise RuntimeError("hyper-secret /private/path leaked")

    h = _make_handler(tmp_path, tools={"run_script": _tool(_boom)})
    resp = h._handle_tools_call(6, {"name": "run_script", "arguments": {}})
    assert resp["error"]["code"] == -32603
    assert "hyper-secret" not in resp["error"]["message"]
    assert "event log" in resp["error"]["message"]


def test_normal_tool_error_text_passes_through(tmp_path):
    def _boom(**kw):
        raise RuntimeError("device 42 not found")

    h = _make_handler(tmp_path, tools={"list_devices": _tool(_boom)})
    resp = h._handle_tools_call(7, {"name": "list_devices", "arguments": {}})
    assert resp["error"]["code"] == -32603
    assert "device 42 not found" in resp["error"]["message"]


# ── Rate limiting & telemetry ─────────────────────────────────────────────────

def test_rate_limit_returns_32099_with_retry_hint(tmp_path):
    h = _make_handler(tmp_path, per_minute=1, tools={
        "list_devices": _tool(lambda **kw: "[]"),
    })
    headers = {"authorization": "Bearer some-token"}
    first = h._handle_tools_call(8, {"name": "list_devices", "arguments": {}},
                                 headers=headers)
    assert "error" not in first
    second = h._handle_tools_call(9, {"name": "list_devices", "arguments": {}},
                                  headers=headers)
    assert second["error"]["code"] == -32099
    assert "Rate limit exceeded" in second["error"]["message"]


def test_happy_path_shape_and_telemetry(tmp_path):
    h = _make_handler(tmp_path, tools={
        "list_devices": _tool(lambda **kw: "hello"),
    })
    resp = h._handle_tools_call(10, {"name": "list_devices", "arguments": {}})
    assert resp["jsonrpc"] == "2.0" and resp["id"] == 10
    assert resp["result"]["content"] == [{"type": "text", "text": "hello"}]
    assert resp["result"]["_meta"]["tool"] == "list_devices"
    assert len(h._tool_call_log) == 1
    entry = h._tool_call_log[0]
    assert entry["name"] == "list_devices" and entry["ok"] is True


# ── v2.12.1: unknown-argument rejection + enable_device alias ─────────────────

_ADMIN_SCOPES = {"tokens": {"admin-key": {"name": "admin-tests",
                                          "scopes": ["admin"]}}}


def test_unknown_argument_rejected_loudly(tmp_path):
    """A misnamed argument must return -32602 naming it — never be silently
    dropped so a parameter default inverts the caller's intent (live-hit
    17-Jul-2026: enable_device called with enable=false re-ENABLED the device)."""
    calls = []
    tools = {"demo": _tool(lambda value=True: calls.append(value) or "ok",
                           properties={"value": {"type": "boolean"}})}
    h = _make_handler(tmp_path, scopes_data=_ADMIN_SCOPES, tools=tools)
    resp = h._handle_tools_call(1, {"name": "demo", "arguments": {"enable": False}},
                                {"authorization": "Bearer admin-key"})
    assert resp["error"]["code"] == -32602
    assert "enable" in resp["error"]["message"]
    assert "value" in resp["error"]["message"], "error must list the valid names"
    assert calls == [], "the tool must NOT have run"


def test_known_arguments_still_dispatch(tmp_path):
    calls = []
    tools = {"demo": _tool(lambda value=True: calls.append(value) or "ok",
                           properties={"value": {"type": "boolean"}})}
    h = _make_handler(tmp_path, scopes_data=_ADMIN_SCOPES, tools=tools)
    resp = h._handle_tools_call(2, {"name": "demo", "arguments": {"value": False}},
                                {"authorization": "Bearer admin-key"})
    assert "error" not in resp
    assert calls == [False]


def test_enable_device_alias_resolves(tmp_path):
    """enable= is an accepted alias of value= and must carry the caller's
    False through to the extended handler."""
    h = object.__new__(MCPHandler)
    seen = {}
    h._ext_call = lambda name, did, value: seen.update({"name": name, "value": value}) or "ok"
    MCPHandler._tool_enable_device(h, 42, enable=False)
    assert seen == {"name": "enable_device", "value": False}
    MCPHandler._tool_enable_device(h, 42)            # default stays enable
    assert seen["value"] is True
    MCPHandler._tool_enable_device(h, 42, value=False, enable=True)
    assert seen["value"] is False, "explicit value wins over the alias"
