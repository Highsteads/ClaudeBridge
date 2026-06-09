#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_v14.py
# Description: indigo_mcp_proxy v1.4 self-healing — RemoteDisconnected-on-reused
#              retry, proactive idle-reconnect, and transparent -32600 session
#              re-handshake + replay. Also pins the safety guarantee that an
#              ambiguous post-send failure on a fresh connection is NOT retried
#              (no double execution) and that a non-session -32600 is NOT
#              mistaken for a session error.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import http.client
import importlib.util
import json
import os
import time
from collections import deque

import pytest
from conftest import SERVER_PLUGIN

_PROXY_PATH = os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py")
_spec = importlib.util.spec_from_file_location("cb_proxy_v14", _PROXY_PATH)
proxy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy)

RD = http.client.RemoteDisconnected  # real class, never patched

PROCESSED = []   # methods the fake "server" actually executed (got past getresponse)
EXCHANGES = deque()
CLOSED = []


class FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self._headers = headers or {"Content-Type": "application/json; charset=utf-8"}

    def getheader(self, name, default=None):
        for k, v in self._headers.items():
            if k.lower() == name.lower():
                return v
        return default

    def read(self):
        return self._body


class FakeConnection:
    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self._pending = None

    def request(self, method, path, body=None, headers=None):
        assert EXCHANGES, "ran out of scripted exchanges"
        ex = EXCHANGES.popleft()
        self._pending = ex
        ex["seen_session"] = (headers or {}).get("Mcp-Session-Id")
        ex["seen_body"] = json.loads(body.decode("utf-8")) if body else None
        if isinstance(ex.get("on_request"), BaseException):
            raise ex["on_request"]

    def getresponse(self):
        ex = self._pending
        gr = ex.get("on_getresponse")
        if isinstance(gr, BaseException):
            raise gr
        PROCESSED.append(ex["seen_body"].get("method") if ex["seen_body"] else None)
        return gr

    def close(self):
        CLOSED.append(self)


@pytest.fixture(autouse=True)
def _fake_transport(monkeypatch):
    EXCHANGES.clear(); PROCESSED.clear(); CLOSED.clear()
    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    proxy._connection = None
    proxy._last_exchange = None
    proxy.session_id = None
    proxy._last_init = None
    yield


def _result(body, id_):
    return FakeResponse(json.dumps({"jsonrpc": "2.0", "id": id_, "result": body}))


def _run(capsys, msg):
    proxy.post_message(json.loads(json.dumps(msg)))   # deep copy in
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def test_remote_disconnected_on_reused_is_retried_once(capsys):
    # Stale keep-alive surfaces at getresponse() as RemoteDisconnected (zero bytes
    # back -> not processed). v1.4 must retry on a fresh conn for a tools/call AND
    # the tool must execute exactly once.
    proxy._connection = FakeConnection("localhost", 8176, 300)
    proxy._last_exchange = time.monotonic()           # not idle, so no proactive drop
    proxy.session_id = "S"
    EXCHANGES.append({"on_getresponse": RD("closed")})
    EXCHANGES.append({"on_getresponse": _result({"ok": True}, 1)})
    r = _run(capsys, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "home_status", "arguments": {}}})
    assert r["result"] == {"ok": True}
    assert PROCESSED == ["tools/call"]                # executed exactly once


def test_proactive_idle_reconnect_drops_stale_connection(capsys):
    # A keep-alive idle longer than the threshold is dropped before writing.
    proxy._connection = FakeConnection("localhost", 8176, 300)
    proxy._last_exchange = time.monotonic() - (proxy.IDLE_RECONNECT_SECONDS + 15)
    stale = proxy._connection
    proxy.session_id = "S"
    EXCHANGES.append({"on_getresponse": _result({"ok": True}, 3)})
    r = _run(capsys, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "home_status", "arguments": {}}})
    assert stale in CLOSED                            # stale conn closed
    assert r["result"] == {"ok": True}
    assert PROCESSED == ["tools/call"]                # single exchange, no spurious retry


def test_minus32600_triggers_rehandshake_and_replay(capsys):
    # IWS invalidated our session: a 200 JSON -32600. The proxy must replay the
    # cached initialize (new id from the response header) + notifications/initialized,
    # then replay the original call once with the new session id.
    proxy._last_init = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18",
                                   "clientInfo": {"name": "claude"}}}
    proxy._connection = FakeConnection("localhost", 8176, 300)
    proxy._last_exchange = time.monotonic()
    proxy.session_id = "OLD"
    EXCHANGES.append({"on_getresponse": FakeResponse(json.dumps(
        {"jsonrpc": "2.0", "id": 4,
         "error": {"code": -32600, "message": "Missing or invalid Mcp-Session-Id"}}))})
    EXCHANGES.append({"on_getresponse": FakeResponse(
        json.dumps({"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": "2025-06-18"}}),
        headers={"Content-Type": "application/json", "Mcp-Session-Id": "NEW"})})
    EXCHANGES.append({"on_getresponse": FakeResponse("{}")})
    replay = {"on_getresponse": _result({"ok": True}, 4)}
    EXCHANGES.append(replay)
    r = _run(capsys, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "home_status", "arguments": {}}})
    assert r["result"] == {"ok": True}               # success, not the -32600
    assert proxy.session_id == "NEW"
    assert PROCESSED == ["tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert replay["seen_session"] == "NEW"           # replay carried the new id


def test_ambiguous_post_send_on_fresh_conn_not_retried(capsys):
    # request() succeeds then getresponse() raises a plain reset (NOT
    # RemoteDisconnected) on a FRESH conn -> the call may have run, so do not retry.
    proxy._connection = None                          # fresh -> reused is False
    proxy.session_id = "S"
    EXCHANGES.append({"on_getresponse": ConnectionResetError(54, "reset")})
    r = _run(capsys, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "device_turn_on", "arguments": {"device_id": 1}}})
    assert r["error"]["code"] == -32603
    assert "may have already executed" in r["error"]["message"]
    assert PROCESSED == []                             # never double-executed


def test_non_session_minus32600_is_not_rehandshaked(capsys):
    # A -32600 that is NOT about the session (e.g. "Invalid Request") must pass
    # through unchanged — no re-handshake loop.
    proxy._last_init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
    proxy._connection = FakeConnection("localhost", 8176, 300)
    proxy._last_exchange = time.monotonic()
    proxy.session_id = "S"
    EXCHANGES.append({"on_getresponse": FakeResponse(json.dumps(
        {"jsonrpc": "2.0", "id": 6, "error": {"code": -32600, "message": "Invalid Request"}}))})
    r = _run(capsys, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                      "params": {"name": "home_status", "arguments": {}}})
    assert r["error"]["code"] == -32600
    assert r["error"]["message"] == "Invalid Request"
    assert PROCESSED == ["tools/call"]                # only the one call, no init replay
