#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_protocol_handle_request.py
# Description: Protocol-layer tests for MCPHandler.handle_request /
#              _dispatch_message: HTTP method/Accept gating, JSON parse errors,
#              batch rejection, initialize session minting, session validation
#              (including the load-bearing empty-store reconnect grace that
#              lets the proxy survive a plugin restart), protocol-version
#              enforcement, and notification semantics.
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

_LOGGER = logging.getLogger("test-protocol")

ACCEPT = {"accept": "application/json, text/event-stream"}


def _make_handler(tmp_path):
    """Skeletal MCPHandler with the attributes the protocol layer touches."""
    h = object.__new__(MCPHandler)
    h.logger            = _LOGGER
    h.plugin            = None
    h.scope_manager     = ScopeManager(scopes_file=str(tmp_path / "absent.json"),
                                       logger=_LOGGER)
    h.rate_limiter      = RateLimiter(logger=_LOGGER)
    h.tool_cache        = ToolCache(default_ttl=0, logger=_LOGGER)
    h._emitter_local    = threading.local()
    h._telemetry_lock   = threading.Lock()
    h._tool_call_log    = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools            = {}
    h._resources        = {}
    h._sessions         = {}
    h._sessions_lock    = threading.Lock()
    h._session_idle_ttl = 24 * 3600
    h._session_max      = 500
    return h


def _post(h, payload, extra_headers=None):
    headers = dict(ACCEPT)
    if extra_headers:
        headers.update(extra_headers)
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return h.handle_request("POST", headers, body)


def _initialize(h):
    """Run a real initialize and return the minted session id."""
    resp = _post(h, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": MCPHandler.PROTOCOL_VERSION,
                                "clientInfo": {"name": "tests"}}})
    assert resp["status"] == 200
    return resp["headers"]["Mcp-Session-Id"]


# ── HTTP-level gating ─────────────────────────────────────────────────────────

def test_non_post_is_405_with_allow_header(tmp_path):
    h = _make_handler(tmp_path)
    resp = h.handle_request("GET", dict(ACCEPT), "")
    assert resp["status"] == 405
    assert resp["headers"]["Allow"] == "POST"


def test_wrong_accept_header_is_406(tmp_path):
    h = _make_handler(tmp_path)
    resp = h.handle_request("POST", {"accept": "text/html"}, "{}")
    assert resp["status"] == 406


def test_malformed_json_returns_parse_error(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, "{not json")
    assert resp["status"] == 200                      # JSON-RPC error, not HTTP
    assert json.loads(resp["content"])["error"]["code"] == -32700


def test_batch_requests_are_rejected(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert json.loads(resp["content"])["error"]["code"] == -32600


# ── initialize / sessions ─────────────────────────────────────────────────────

def test_initialize_mints_session_and_returns_header(tmp_path):
    h = _make_handler(tmp_path)
    sid = _initialize(h)
    assert sid and sid in h._sessions
    assert h._sessions[sid]["client_info"]["name"] == "tests"


def test_initialize_with_unsupported_version_is_refused(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "1999-01-01"}})
    err = json.loads(resp["content"])["error"]
    assert err["code"] == -32602
    assert MCPHandler.PROTOCOL_VERSION in err["data"]["supported"]


def test_unknown_session_rejected_when_sessions_exist(tmp_path):
    h = _make_handler(tmp_path)
    _initialize(h)                                    # store is now non-empty
    resp = _post(h, {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                 {"mcp-session-id": "forged-session-id"})
    err = json.loads(resp["content"])["error"]
    assert err["code"] == -32600
    assert "Mcp-Session-Id" in err["message"]


def test_empty_store_grace_lets_stale_session_reconnect(tmp_path):
    # After a plugin restart _sessions is empty but the proxy still holds its
    # pre-restart session id. The deliberate grace clause must let the request
    # through rather than locking the client out (documented load-bearing).
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                 {"mcp-session-id": "session-from-before-the-restart"})
    assert json.loads(resp["content"])["result"] == {}


def test_known_session_passes_and_updates_last_seen(tmp_path):
    h = _make_handler(tmp_path)
    sid = _initialize(h)
    before = h._sessions[sid]["last_seen"]
    resp = _post(h, {"jsonrpc": "2.0", "id": 4, "method": "ping"},
                 {"mcp-session-id": sid})
    assert json.loads(resp["content"])["result"] == {}
    assert h._sessions[sid]["last_seen"] >= before


# ── Protocol-version header ───────────────────────────────────────────────────

def test_mismatched_protocol_version_header_is_rejected(tmp_path):
    # Enforced independently of session state (v2.8.2 fix) — a PRESENT but
    # wrong version is refused even during the empty-store reconnect window.
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 5, "method": "ping"},
                 {"mcp-protocol-version": "2024-01-01"})
    err = json.loads(resp["content"])["error"]
    assert err["code"] == -32600
    assert "protocol version" in err["message"].lower()


def test_missing_protocol_version_header_is_tolerated(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 6, "method": "ping"})
    assert json.loads(resp["content"])["result"] == {}


# ── Notifications & unknown methods ───────────────────────────────────────────

def test_notification_returns_empty_json_body(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp["status"] == 200
    assert resp["content"] == "{}"


def test_unknown_method_is_32601(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 7, "method": "no/such/method"})
    assert json.loads(resp["content"])["error"]["code"] == -32601


def test_tools_list_reflects_registry(tmp_path):
    h = _make_handler(tmp_path)
    h._tools["demo_tool"] = {"description": "demo",
                             "inputSchema": {"type": "object"},
                             "function": lambda **kw: "x"}
    resp = _post(h, {"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    tools = json.loads(resp["content"])["result"]["tools"]
    assert tools == [{"name": "demo_tool", "description": "demo",
                      "inputSchema": {"type": "object"}}]
