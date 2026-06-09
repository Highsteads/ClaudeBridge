#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_retry.py
# Description: indigo_mcp_proxy must retry a tools/call when the connection failed
#              BEFORE the request was sent (stale keep-alive / server reload — the
#              request never reached the server, so it did not execute), but must
#              NOT retry a tools/call when the failure came AFTER sending.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

import indigo_mcp_proxy as proxy


class _Resp:
    def getheader(self, name, default=""):
        if name == "Mcp-Session-Id":
            return "sess-1"
        if name == "Content-Type":
            return "application/json"
        return default

    def read(self):
        return b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'


class _Conn:
    """Fake HTTP connection scripted to fail at a chosen phase."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on          # 'request' | 'getresponse' | None

    def request(self, *a, **k):
        if self.fail_on == "request":
            raise OSError(32, "Broken pipe")

    def getresponse(self):
        if self.fail_on == "getresponse":
            raise OSError(54, "Connection reset by peer")
        return _Resp()


def _patch_conns(monkeypatch, conns):
    proxy._connection = None
    proxy.session_id = None
    seq = list(conns)
    monkeypatch.setattr(proxy, "_get_connection",
                        lambda: seq.pop(0) if seq else _Conn())
    return seq


def test_tools_call_retried_when_send_failed(monkeypatch, capsys):
    # First connection fails during request() (never sent) -> must retry on a
    # fresh connection and succeed.
    seq = _patch_conns(monkeypatch, [_Conn("request"), _Conn(None)])
    proxy.post_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "device_turn_on", "arguments": {}}})
    out = capsys.readouterr().out
    assert '"result"' in out, "retry after a send-failure should deliver the response"
    assert "Connection error" not in out
    assert seq == [], "both connections should have been used (fail then retry)"


def test_tools_call_not_retried_when_receive_failed(monkeypatch, capsys):
    # request() succeeds (sent) but getresponse() fails -> the call may have run,
    # so it must NOT be retried.
    _patch_conns(monkeypatch, [_Conn("getresponse")])
    proxy.post_message({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "device_turn_on", "arguments": {}}})
    out = capsys.readouterr().out
    assert "not retried" in out
    assert "already executed" in out


def test_idempotent_retried_when_receive_failed(monkeypatch, capsys):
    # An idempotent method is still retried even after a post-send failure.
    seq = _patch_conns(monkeypatch, [_Conn("getresponse"), _Conn(None)])
    proxy.post_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    out = capsys.readouterr().out
    assert "not retried" not in out
    assert '"result"' in out
    assert seq == []
