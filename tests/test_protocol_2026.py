#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_protocol_2026.py
# Description: MCP 2026-07-28 beside 2025-06-18 (3.7.0). The handler serves a
#              request whose params._meta names its protocol version with no
#              handshake and no session: server/discover, version and header
#              checks with the codes and HTTP statuses the revision sets,
#              resultType / serverInfo / caching hints on every result, and no
#              code from the range the revision reserves. Then the bundled
#              proxy against the real handler, as Claude Code drives it.
#              Rules read from the specification source, 29-09-2026.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0

import http.client
import importlib.util
import json
import os

import pytest

from conftest import SERVER_PLUGIN
from mcp_server import protocol_era as era
from test_mcp_conformance import _tool
from test_protocol_handle_request import ACCEPT, _initialize, _make_handler, _post

V = "2026-07-28"


def _handler(tmp_path, tools):
    """The protocol-test handler (it can hold legacy sessions) with tools."""
    h = _make_handler(tmp_path)
    h._tools = tools
    h.entity_index_manager = None
    h.external_tools = None
    return h


def _meta(version=V, caps=True):
    m = {era.META_PROTOCOL_VERSION: version,
         era.META_CLIENT_INFO: {"name": "claude-code", "version": "2.1.284"}}
    if caps:
        m[era.META_CLIENT_CAPABILITIES] = {"roots": {"listChanged": True}}
    return m


def _modern(h, method, params=None, *, id_=1, version=V, headers=None, caps=True,
            name_header=None):
    p = dict(params or {})
    p["_meta"] = _meta(version, caps)
    hdrs = {"mcp-protocol-version": version, "mcp-method": method}
    if name_header is not None:
        hdrs["mcp-name"] = name_header
    if headers is not None:
        hdrs = headers
    resp = _post(h, {"jsonrpc": "2.0", "id": id_, "method": method, "params": p}, hdrs)
    return resp, (json.loads(resp["content"]) if resp["content"].strip() else None)


# ── server/discover ──────────────────────────────────────────────────────────

def test_discover_advertises_both_eras_and_mints_no_session(tmp_path):
    h = _make_handler(tmp_path)
    resp, body = _modern(h, "server/discover")
    assert resp["status"] == 200
    r = body["result"]
    assert r["resultType"] == "complete"
    assert r["supportedVersions"] == ["2026-07-28", "2025-06-18"]
    assert r["capabilities"] == {"prompts": {}, "resources": {"subscribe": False}, "tools": {}}
    assert r["_meta"][era.META_SERVER_INFO]["name"] == "Indigo Claude Bridge"
    assert r["ttlMs"] == 300_000 and r["cacheScope"] == "private"
    assert h._sessions == {}
    assert "Mcp-Session-Id" not in resp.get("headers", {})


def test_discover_and_initialize_offer_the_same_capabilities(tmp_path):
    h = _make_handler(tmp_path)
    _, body = _modern(h, "server/discover")
    init = json.loads(_post(h, {"jsonrpc": "2.0", "id": 9, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18"}})["content"])
    assert body["result"]["capabilities"] == init["result"]["capabilities"]
    assert body["result"]["_meta"][era.META_SERVER_INFO] == init["result"]["serverInfo"]


# ── no session in the modern era ─────────────────────────────────────────────

def test_a_modern_request_needs_no_session_even_while_legacy_ones_exist(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    _initialize(h)                                       # a legacy client is attached
    resp, body = _modern(h, "tools/list")
    assert resp["status"] == 200
    r = body["result"]
    assert [t["name"] for t in r["tools"]] == ["t"]
    assert r["resultType"] == "complete"
    assert r["ttlMs"] == 300_000 and r["cacheScope"] == "private"


def test_a_modern_tool_call_runs_and_carries_result_type(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    resp, body = _modern(h, "tools/call", {"name": "t", "arguments": {}}, name_header="t")
    assert resp["status"] == 200
    r = body["result"]
    assert r["content"][0]["text"] == "fine"
    assert r["isError"] is False
    assert r["resultType"] == "complete"
    assert r["_meta"]["tool"] == "t"                     # Claude Bridge's own keys survive
    assert era.META_SERVER_INFO in r["_meta"]
    assert "ttlMs" not in r                              # a tool call is not cacheable


def test_a_legacy_session_header_on_a_modern_request_is_ignored(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    _initialize(h)
    resp, _ = _modern(h, "tools/list", headers={"mcp-protocol-version": V,
                                                "mcp-method": "tools/list",
                                                "mcp-session-id": "nonsense"})
    assert resp["status"] == 200


# ── versions and required fields ─────────────────────────────────────────────

def test_an_unsupported_version_is_32022_with_what_to_retry(tmp_path):
    h = _make_handler(tmp_path)
    resp, body = _modern(h, "tools/list", version="2027-01-01")
    assert resp["status"] == 400
    assert body["error"]["code"] == -32022
    assert body["error"]["data"] == {"supported": ["2026-07-28", "2025-06-18"],
                                     "requested": "2027-01-01"}


def test_the_legacy_version_is_not_accepted_through_meta(tmp_path):
    # 2025-06-18 is reached through initialize, never per request.
    h = _make_handler(tmp_path)
    resp, body = _modern(h, "tools/list", version="2025-06-18")
    assert resp["status"] == 400 and body["error"]["code"] == -32022


def test_missing_client_capabilities_is_32602(tmp_path):
    h = _make_handler(tmp_path)
    resp, body = _modern(h, "tools/list", caps=False)
    assert resp["status"] == 400 and body["error"]["code"] == -32602


def test_a_modern_header_on_a_legacy_body_is_32602(tmp_path):
    h = _make_handler(tmp_path)
    _initialize(h)
    resp = _post(h, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                 {"mcp-protocol-version": V})
    assert resp["status"] == 400
    assert json.loads(resp["content"])["error"]["code"] == -32602


# ── header validation (-32020, HTTP 400) ─────────────────────────────────────

@pytest.mark.parametrize("headers", [
    {"mcp-method": "tools/list"},                                   # no version header
    {"mcp-protocol-version": "2025-06-18", "mcp-method": "tools/list"},  # disagrees with body
    {"mcp-protocol-version": V},                                    # no Mcp-Method
    {"mcp-protocol-version": V, "mcp-method": "tools/call"},        # wrong Mcp-Method
])
def test_headers_that_disagree_with_the_body_are_32020(tmp_path, headers):
    h = _make_handler(tmp_path)
    resp, body = _modern(h, "tools/list", headers=headers)
    assert resp["status"] == 400 and body["error"]["code"] == -32020


def test_mcp_name_is_required_and_must_match_on_a_tool_call(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    resp, body = _modern(h, "tools/call", {"name": "t"})
    assert resp["status"] == 400 and body["error"]["code"] == -32020
    resp, body = _modern(h, "tools/call", {"name": "t"}, name_header="other")
    assert resp["status"] == 400 and body["error"]["code"] == -32020


def test_a_base64_mcp_name_is_decoded_before_comparing(tmp_path):
    name = "Hello, 世界"
    h = _handler(tmp_path, {name: _tool(lambda **kw: "fine")})
    resp, body = _modern(h, "tools/call", {"name": name},
                         name_header="=?base64?SGVsbG8sIOS4lueVjA==?=")
    assert resp["status"] == 200 and body["result"]["isError"] is False


# ── methods the revision removed, and codes it reserves ──────────────────────

@pytest.mark.parametrize("method", ["ping", "initialize", "logging/setLevel",
                                    "subscriptions/listen", "no/such/method"])
def test_a_method_2026_does_not_define_here_is_404_32601(tmp_path, method):
    h = _make_handler(tmp_path)
    resp, body = _modern(h, method)
    assert resp["status"] == 404
    assert body["error"]["code"] == -32601


def test_resource_not_found_is_32602_modern_and_32002_legacy(tmp_path):
    h = _make_handler(tmp_path)
    _, body = _modern(h, "resources/read", {"uri": "indigo://nope"},
                      name_header="indigo://nope")
    assert body["error"]["code"] == -32602
    legacy = h._handle_resources_read(5, {"uri": "indigo://nope"}, {})
    assert legacy["error"]["code"] == -32002


def test_a_refused_tool_call_becomes_an_error_result_not_32099(tmp_path):
    h = _handler(tmp_path, {"t": _tool(lambda **kw: "fine")})
    h._handle_tools_call = lambda msg_id, params, headers: h._json_error(
        msg_id, -32099, "Rate limit exceeded: minute=120; retry in 30s")
    resp, body = _modern(h, "tools/call", {"name": "t"}, name_header="t")
    assert resp["status"] == 200
    r = body["result"]
    assert r["isError"] is True
    assert "Rate limit exceeded" in r["content"][0]["text"]
    assert r["resultType"] == "complete"


def test_a_refusal_on_a_resource_is_32600_not_32099(tmp_path):
    h = _make_handler(tmp_path)
    h._resources_scope_denied = lambda msg_id, headers: h._json_error(
        msg_id, -32099, "Resource access requires 'read' scope")
    _, body = _modern(h, "resources/list")
    assert body["error"]["code"] == -32600


def test_no_modern_reply_ever_carries_an_undefined_reserved_code(tmp_path):
    for code in range(-32099, -32019):
        mapped = era.modern_error_code(code)
        assert mapped in (-32020, -32021, -32022) or not (-32099 <= mapped <= -32020)


def test_a_modern_notification_is_202(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "method": "notifications/cancelled",
                     "params": {"requestId": 4, "_meta": _meta()}})
    assert resp["status"] == 202


# ── the pure helpers ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, ok, text", [
    ("us-west1", True, "us-west1"),
    ("=?base64?SGVsbG8sIOS4lueVjA==?=", True, "Hello, 世界"),
    ("=?base64?IHBhZGRlZCA=?=", True, " padded "),
    ("=?base64?bGluZTEKbGluZTI=?=", True, "line1\nline2"),
    ("=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=", True, "=?base64?literal?="),
    ("=?base64?not base64!?=", False, None),
    ("café", False, None),
])
def test_header_values_decode_as_the_spec_table_says(raw, ok, text):
    assert era.decode_header_value(raw) == (ok, text)


def test_health_counts_modern_clients_by_name(tmp_path):
    h = _make_handler(tmp_path)
    h.entity_index_manager = None
    _modern(h, "server/discover")
    _modern(h, "tools/list")
    clients = h._modern_clients
    assert clients["claude-code"]["requests"] == 2
    assert clients["claude-code"]["version"] == "2.1.284"


# ── the bundled proxy against the real handler ───────────────────────────────

_spec = importlib.util.spec_from_file_location(
    "cb_proxy_2026", os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py"))
proxy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy)


class _Server:
    handler = None
    seen = []                  # (status, request headers)


class _Resp:
    def __init__(self, reply):
        self.status = reply["status"]
        self._headers = reply.get("headers") or {}
        self._body = (reply.get("content") or "").encode("utf-8")

    def getheader(self, name, default=None):
        for k, v in self._headers.items():
            if k.lower() == name.lower():
                return v
        return default

    def read(self):
        return self._body


class _Conn:
    def __init__(self, *a, **k):
        self._reply = None

    def request(self, method, path, body=None, headers=None):
        hdrs = dict(headers or {})
        self._reply = _Server.handler.handle_request(method, hdrs, body.decode("utf-8"))
        _Server.seen.append((self._reply["status"], {k.lower(): v for k, v in hdrs.items()}))

    def getresponse(self):
        return _Resp(self._reply)

    def close(self):
        pass


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(http.client, "HTTPConnection", _Conn)
    _Server.handler = _handler(tmp_path, {"t": _tool(lambda **kw: "fine"),
                                          "Hello, 世界": _tool(lambda **kw: "hi")})
    _Server.seen = []
    proxy._connection = None
    proxy._last_exchange = None
    proxy.session_id = None
    proxy._last_init = None
    return _Server


def _send(capsys, msg):
    proxy.post_message(json.loads(json.dumps(msg)))
    out = capsys.readouterr().out.strip()
    return [json.loads(line) for line in out.splitlines()] if out else []


def _modern_msg(method, params=None, id_=1, version=V):
    p = dict(params or {})
    p["_meta"] = _meta(version)
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": p}


def test_claude_codes_probe_then_tool_call_through_the_proxy(wired, capsys):
    """What Claude Code 2.1.28x sends first, then a call, with no initialize."""
    (disc,) = _send(capsys, _modern_msg("server/discover", id_="server-discover-probe-1"))
    assert disc["id"] == "server-discover-probe-1"
    assert "2026-07-28" in disc["result"]["supportedVersions"]
    (listing,) = _send(capsys, _modern_msg("tools/list", id_=2))
    assert {t["name"] for t in listing["result"]["tools"]} == {"t", "Hello, 世界"}
    (call,) = _send(capsys, _modern_msg("tools/call", {"name": "t", "arguments": {}}, id_=3))
    assert call["result"]["content"][0]["text"] == "fine"
    assert [s for s, _ in wired.seen] == [200, 200, 200]
    for _, hdrs in wired.seen:
        assert hdrs["mcp-protocol-version"] == V
        assert "mcp-session-id" not in hdrs
    assert wired.seen[2][1]["mcp-name"] == "t"
    assert wired.handler._sessions == {}


def test_the_proxy_wraps_a_non_ascii_tool_name(wired, capsys):
    (call,) = _send(capsys, _modern_msg("tools/call", {"name": "Hello, 世界"}, id_=4))
    assert call["result"]["content"][0]["text"] == "hi"
    assert wired.seen[0][1]["mcp-name"] == "=?base64?SGVsbG8sIOS4lueVjA==?="


def test_the_proxy_passes_a_modern_error_through_with_its_code(wired, capsys):
    (reply,) = _send(capsys, _modern_msg("tools/list", id_=5, version="2027-01-01"))
    assert reply["id"] == 5
    assert reply["error"]["code"] == -32022
    assert reply["error"]["data"]["supported"][0] == "2026-07-28"
    (reply,) = _send(capsys, _modern_msg("ping", id_=6))
    assert reply["error"]["code"] == -32601


def test_the_proxy_still_serves_a_legacy_client(wired, capsys):
    (init,) = _send(capsys, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    (listing,) = _send(capsys, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "result" in listing
    assert wired.seen[-1][1].get("mcp-session-id") == proxy.session_id
    assert "resultType" not in listing["result"]      # legacy results unchanged


def test_accept_header_is_still_required(tmp_path):
    h = _make_handler(tmp_path)
    resp = h.handle_request("POST", {"mcp-protocol-version": V}, json.dumps(
        _modern_msg("server/discover")))
    assert resp["status"] == 406
    assert ACCEPT["accept"]


def test_a_modern_request_after_a_legacy_handshake_sends_no_session(wired, capsys):
    """One proxy process that did a legacy initialize keeps a session id; a
    modern request from it must still go without one."""
    _send(capsys, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}})
    assert proxy.session_id
    (reply,) = _send(capsys, _modern_msg("tools/list", id_=9))
    assert "result" in reply
    assert "mcp-session-id" not in wired.seen[-1][1]
