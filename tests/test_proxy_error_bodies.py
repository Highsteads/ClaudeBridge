#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_error_bodies.py
# Description: indigo_mcp_proxy 1.7 answers every request with JSON-RPC. The
#              plugin's own 503 body ({"error": ...}, JSON but not JSON-RPC)
#              used to be passed through verbatim, so the client's request id
#              was never answered. Also checks the plugin's 503/500 bodies are
#              now JSON-RPC errors carrying the request id.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import http.client
import importlib.util
import json
import os

import pytest

from conftest import SERVER_PLUGIN, load_plugin_module

_spec = importlib.util.spec_from_file_location(
    "cb_proxy_error_bodies", os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py"))
proxy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy)

REPLIES = []


class _Resp:
    def __init__(self, status, body, content_type="application/json"):
        self.status = status
        self._body = body.encode("utf-8")
        self._ct = content_type

    def getheader(self, name, default=None):
        return self._ct if name.lower() == "content-type" else default

    def read(self):
        return self._body


class _Conn:
    def __init__(self, *a, **k):
        pass

    def request(self, *a, **k):
        pass

    def getresponse(self):
        return REPLIES.pop(0)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _transport(monkeypatch):
    REPLIES.clear()
    monkeypatch.setattr(http.client, "HTTPConnection", _Conn)
    proxy._connection = None
    proxy._last_exchange = None
    proxy.session_id = None
    proxy._last_init = None


def _send(capsys, msg):
    proxy.post_message(json.loads(json.dumps(msg)))
    out = capsys.readouterr().out.strip()
    return [json.loads(line) for line in out.splitlines()] if out else []


def test_a_json_503_that_is_not_json_rpc_is_answered_for_the_request_id(capsys):
    REPLIES.append(_Resp(503, json.dumps(
        {"error": "MCP server unavailable - plugin initialization failed"})))
    out = _send(capsys, {"jsonrpc": "2.0", "id": 17, "method": "tools/list"})
    assert len(out) == 1
    reply = out[0]
    assert reply["jsonrpc"] == "2.0" and reply["id"] == 17
    assert "HTTP 503" in reply["error"]["message"]
    assert "plugin initialization failed" in reply["error"]["message"]


def test_a_json_rpc_503_is_answered_with_its_message(capsys):
    REPLIES.append(_Resp(503, json.dumps({"jsonrpc": "2.0", "id": 8,
                                          "error": {"code": -32603, "message": "not ready"}})))
    out = _send(capsys, {"jsonrpc": "2.0", "id": 8, "method": "ping"})
    assert out[0]["id"] == 8 and "not ready" in out[0]["error"]["message"]


def test_a_200_body_that_is_json_but_not_json_rpc_is_an_error_not_passed_through(capsys):
    REPLIES.append(_Resp(200, json.dumps({"hello": "world"})))
    out = _send(capsys, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert out[0]["id"] == 9 and "error" in out[0]
    assert "hello" not in json.dumps(out[0].get("result", {}))


def test_a_request_answered_with_nothing_still_gets_an_answer(capsys):
    REPLIES.append(_Resp(200, ""))
    out = _send(capsys, {"jsonrpc": "2.0", "id": 10, "method": "ping"})
    assert out[0]["id"] == 10 and "empty reply" in out[0]["error"]["message"]


def test_a_notification_ack_writes_nothing(capsys):
    REPLIES.append(_Resp(200, "{}"))
    assert _send(capsys, {"jsonrpc": "2.0", "method": "notifications/initialized"}) == []


def test_a_normal_reply_is_passed_through_unchanged(capsys):
    body = {"jsonrpc": "2.0", "id": 11, "result": {"tools": []}}
    REPLIES.append(_Resp(200, json.dumps(body)))
    assert _send(capsys, {"jsonrpc": "2.0", "id": 11, "method": "tools/list"}) == [body]


# ── the plugin's side: its 503 and 500 bodies are JSON-RPC ──────────────────

@pytest.mark.parametrize("body,expected_id", [
    (json.dumps({"jsonrpc": "2.0", "id": 21, "method": "tools/list"}), 21),
    (json.dumps({"jsonrpc": "2.0", "id": "abc", "method": "ping"}), "abc"),
    ("{not json", None),
    ("", None),
])
def test_the_plugin_http_error_body_is_json_rpc_with_the_id(body, expected_id):
    mod = load_plugin_module()
    reply = mod.Plugin._jsonrpc_http_error(503, body, "MCP server unavailable")
    assert reply["status"] == 503
    assert reply["headers"]["Content-Type"].startswith("application/json")
    content = json.loads(reply["content"])
    assert content["jsonrpc"] == "2.0" and content["id"] == expected_id
    assert content["error"]["message"] == "MCP server unavailable"


def test_the_endpoint_answers_503_as_json_rpc_when_the_handler_failed():
    from types import SimpleNamespace
    import logging
    mod = load_plugin_module()
    p = object.__new__(mod.Plugin)
    p.logger = logging.getLogger("test-proxy-error-bodies")
    p.mcp_handler = None
    action = SimpleNamespace(props={"incoming_request_method": "POST", "headers": {},
                                    "request_body": json.dumps({"jsonrpc": "2.0", "id": 5,
                                                                "method": "ping"})})
    reply = p.handle_mcp_endpoint(action)
    assert reply["status"] == 503
    assert json.loads(reply["content"])["id"] == 5
