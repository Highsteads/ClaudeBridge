#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_session_status.py
# Description: The bundled proxy against the real MCPHandler.handle_request,
#              with the HTTP layer faked: the MCP Streamable HTTP status codes
#              the plugin now sends (404 for an unknown session, 400 for a
#              missing one, 202 with no body for a notification) are handled,
#              and the proxy keeps working across a plugin restart.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

import http.client
import importlib.util
import json
import os

import pytest

from conftest import SERVER_PLUGIN
from test_protocol_handle_request import _make_handler

_spec = importlib.util.spec_from_file_location(
    "cb_proxy_session_status", os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py"))
proxy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy)


class Server:
    """Stands in for Indigo's web server: every POST goes to the handler."""
    handler = None
    statuses = []


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
        self._reply = Server.handler.handle_request(method, dict(headers or {}),
                                                    body.decode("utf-8"))
        Server.statuses.append(self._reply["status"])

    def getresponse(self):
        return _Resp(self._reply)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _wire(monkeypatch, tmp_path):
    monkeypatch.setattr(http.client, "HTTPConnection", _Conn)
    Server.handler = _make_handler(tmp_path)
    Server.statuses = []
    proxy._connection = None
    proxy._last_exchange = None
    proxy.session_id = None
    proxy._last_init = None
    yield


def _send(capsys, msg):
    proxy.post_message(json.loads(json.dumps(msg)))
    out = capsys.readouterr().out.strip()
    return [json.loads(line) for line in out.splitlines()] if out else []


def _attach(capsys):
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18",
                                         "clientInfo": {"name": "claude-code"}}})
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert _send(capsys, {"jsonrpc": "2.0", "method": "notifications/initialized"}) == []


def _other_client_initializes():
    Server.handler.handle_request(
        "POST", {"accept": "application/json"},
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))


def test_a_notification_is_202_and_nothing_reaches_the_client(capsys):
    _attach(capsys)
    assert 202 in Server.statuses


def test_an_unknown_session_404_re_handshakes_and_replays(capsys):
    _attach(capsys)
    proxy.session_id = "expired-session"
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert reply == {"jsonrpc": "2.0", "id": 7, "result": {}}
    assert 404 in Server.statuses
    assert proxy.session_id in Server.handler._sessions


def test_a_missing_session_400_re_handshakes_and_replays(capsys):
    _attach(capsys)
    proxy.session_id = None
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    assert reply["id"] == 8 and "result" in reply
    assert 400 in Server.statuses


def test_the_proxy_carries_on_across_a_plugin_restart(capsys, tmp_path):
    _attach(capsys)
    old_session = proxy.session_id

    # Restart: a new handler with an empty session store. The old id is let
    # through (the grace clause) until somebody initializes...
    Server.handler = _make_handler(tmp_path)
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert reply["result"] == {}
    assert proxy.session_id == old_session

    # ...and once another client has, the stale id gets a 404 and the proxy
    # quietly starts a new session. The client sees only its answer.
    _other_client_initializes()
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert reply == {"jsonrpc": "2.0", "id": 3, "result": {}}
    assert proxy.session_id != old_session
    assert proxy.session_id in Server.handler._sessions


def test_a_404_that_initialize_cannot_cure_is_reported_once(capsys, monkeypatch):
    """A 404 from the web server itself (the plugin is disabled) looks like an
    expired session. The re-handshake gets the same 404, and the request is
    answered with the error, not left waiting or retried for ever."""
    _attach(capsys)

    def _not_found(*a, **k):
        return {"status": 404, "headers": {"Content-Type": "text/html"},
                "content": "<html>Not Found</html>"}
    monkeypatch.setattr(Server.handler, "handle_request", _not_found)
    (reply,) = _send(capsys, {"jsonrpc": "2.0", "id": 4, "method": "ping"})
    assert reply["id"] == 4
    assert "404" in reply["error"]["message"]
