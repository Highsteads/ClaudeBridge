#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_mcp_conformance.py
# Description: MCP 2025-06-18 shapes: a failed tool call is a result with
#              isError, templated resources are listed by
#              resources/templates/list (not resources/list), tools carry
#              annotations derived from their scope, and the tool explorer
#              escapes everything it prints.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import logging
import threading
from collections import deque

from mcp_server import registry
from mcp_server.common.json_encoder import safe_json_dumps
from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager

_LOGGER = logging.getLogger("test-mcp-conformance")


def _handler(tmp_path, tools=None, resources=None):
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
    h._resources        = resources or {}
    h._sessions         = {}
    h._sessions_lock    = threading.Lock()
    h.entity_index_manager = None
    h.external_tools    = None
    return h


def _tool(fn, description="test tool", properties=None):
    return {"description": description,
            "inputSchema": {"type": "object", "properties": properties or {}},
            "function": fn}


# ── isError ──────────────────────────────────────────────────────────────────

def test_a_failure_payload_is_flagged_is_error(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: safe_json_dumps(
        {"success": False, "error": "no such device"}))})
    reply = h._handle_tools_call(1, {"name": "t", "arguments": {}})
    assert reply["result"]["isError"] is True
    assert "no such device" in reply["result"]["content"][0]["text"]


def test_a_success_says_is_error_false(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    reply = h._handle_tools_call(2, {"name": "t", "arguments": {}})
    assert reply["result"]["isError"] is False


def test_a_raised_exception_is_a_tool_result_not_a_protocol_error(tmp_path):
    def _boom(**kw):
        raise RuntimeError("the hub went away")

    h = _handler(tmp_path, {"t": _tool(_boom)})
    reply = h._handle_tools_call(3, {"name": "t", "arguments": {}})
    assert "error" not in reply
    assert reply["id"] == 3
    assert reply["result"]["isError"] is True
    assert "the hub went away" in reply["result"]["content"][0]["text"]


# ── resources/templates/list ─────────────────────────────────────────────────

def _resources():
    return {
        "indigo://devices": {"name": "Devices", "description": "all", "function": lambda: "[]"},
        "indigo://devices/{device_id}": {"name": "Device", "description": "one",
                                         "function": lambda i: "{}"},
    }


def test_resources_list_carries_only_concrete_uris(tmp_path):
    h = _handler(tmp_path, resources=_resources())
    reply = h._handle_resources_list(1, {}, {})
    uris = [r["uri"] for r in reply["result"]["resources"]]
    assert uris == ["indigo://devices"]


def test_templates_are_served_by_resources_templates_list(tmp_path):
    h = _handler(tmp_path, resources=_resources())
    reply = h._dispatch_message({"jsonrpc": "2.0", "id": 2,
                                 "method": "resources/templates/list", "params": {}}, {})
    templates = reply["result"]["resourceTemplates"]
    assert templates == [{"uriTemplate": "indigo://devices/{device_id}", "name": "Device",
                          "description": "one", "mimeType": "application/json"}]


def test_a_templated_resource_is_still_readable(tmp_path):
    h = _handler(tmp_path, resources=_resources())
    reply = h._handle_resources_read(3, {"uri": "indigo://devices/12"}, {})
    assert reply["result"]["contents"][0]["text"] == "{}"


# ── annotations ──────────────────────────────────────────────────────────────

def test_annotations_follow_scope_and_the_delete_gate(tmp_path):
    reg = registry.load()
    tools = {name: _tool(lambda **kw: "x") for name in reg}
    h = _handler(tmp_path, tools)
    listed = {t["name"]: t for t in h._handle_tools_list(1, {})["result"]["tools"]}
    for name, spec in reg.items():
        ann = listed[name]["annotations"]
        assert ann["readOnlyHint"] is (spec.scope == "read"), name
        if spec.scope != "read":
            assert ann["destructiveHint"] is (spec.destructive or spec.scope == "admin"), name
    assert listed["delete_device"]["annotations"] == {"readOnlyHint": False, "destructiveHint": True}
    assert listed["list_devices"]["annotations"] == {"readOnlyHint": True}


def test_a_plugin_provided_tool_is_annotated_from_its_write_flag(tmp_path):
    tools = {"acme_read": dict(_tool(lambda **kw: "x"), external_provider="com.acme", write=False),
             "acme_set": dict(_tool(lambda **kw: "x"), external_provider="com.acme", write=True)}
    h = _handler(tmp_path, tools)
    listed = {t["name"]: t for t in h._handle_tools_list(1, {})["result"]["tools"]}
    assert listed["acme_read"]["annotations"] == {"readOnlyHint": True}
    assert listed["acme_set"]["annotations"] == {"readOnlyHint": False, "destructiveHint": False}


def test_tools_list_keeps_its_three_original_keys(tmp_path):
    h = _handler(tmp_path, {"list_devices": _tool(lambda **kw: "x")})
    entry = h._handle_tools_list(1, {})["result"]["tools"][0]
    assert {"name", "description", "inputSchema"} <= set(entry)


# ── the explorer page escapes what it prints ─────────────────────────────────

def test_the_explorer_escapes_names_types_and_descriptions(tmp_path):
    evil = "<script>alert(1)</script>"
    tools = {"acme_x": _tool(lambda **kw: "x", description=evil,
                             properties={evil: {"type": evil, "description": evil}})}
    h = _handler(tmp_path, tools)
    page = h.get_tool_explorer_html(endpoint_url=evil)
    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_registry_change_domains_are_the_cache_domains():
    from mcp_server.common import tool_cache
    assert set(tool_cache._DOMAINS) == set(registry.CHANGE_DOMAINS)


def test_initialize_reply_is_json_serialisable(tmp_path):
    h = _handler(tmp_path)
    h._session_idle_ttl, h._session_max = 3600, 10
    reply = h._handle_initialize(1, {"protocolVersion": "2024-11-05"})
    reply.pop("_mcp_session_id")
    json.dumps(reply)
    assert reply["result"]["protocolVersion"] == MCPHandler.PROTOCOL_VERSION
