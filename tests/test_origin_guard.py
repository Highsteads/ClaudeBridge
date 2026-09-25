#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_origin_guard.py
# Description: The MCP endpoint validates the Origin header, as the Streamable
#              HTTP transport requires against DNS rebinding: a web page from
#              any host but this Mac or the Indigo server gets 403, and a
#              request with no Origin (the proxy, curl) still works.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

import json

import pytest

import indigo  # the conftest stub
from mcp_server.security import origin_guard
from mcp_server.security.origin_guard import OriginGuard, origin_allowed

from test_protocol_handle_request import _make_handler

PING = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})


def _post(h, origin=None, host="evil.example"):
    headers = {"Accept": "application/json", "Host": host}
    if origin is not None:
        headers["Origin"] = origin
    return h.handle_request("POST", headers, PING)


@pytest.fixture()
def handler(tmp_path, monkeypatch):
    monkeypatch.setattr(origin_guard, "discover_own_hosts",
                        lambda: {"indigo-mac.local", "192.168.1.20", "myhouse.indigodomo.net"})
    h = _make_handler(tmp_path)
    h._origin_guard = OriginGuard(discover=origin_guard.discover_own_hosts)
    return h


def test_no_origin_is_a_client_that_is_not_a_browser(handler):
    resp = _post(handler)
    assert resp["status"] == 200 and json.loads(resp["content"])["result"] == {}


@pytest.mark.parametrize("origin", [
    "http://localhost:3000", "http://127.0.0.1", "http://127.8.9.10:8176",
    "http://[::1]:8176", "http://indigo-mac.local:8176", "http://192.168.1.20:8176",
    "https://myhouse.indigodomo.net", "HTTP://LOCALHOST",
])
def test_this_mac_and_the_indigo_server_are_allowed(handler, origin):
    assert _post(handler, origin)["status"] == 200


@pytest.mark.parametrize("origin", [
    "https://evil.example", "http://evil.example:8176", "null", "file://",
    "http://localhost.evil.example", "not a url",
])
def test_any_other_origin_is_403(handler, origin):
    resp = _post(handler, origin)
    assert resp["status"] == 403
    assert json.loads(resp["content"])["error"]["code"] == -32600


def test_the_host_header_is_not_trusted(handler):
    """DNS rebinding: the hostile page and the Host header name the same
    domain, so a same-host check would let it in."""
    assert _post(handler, "http://evil.example:8176", host="evil.example:8176")["status"] == 403


def test_the_indigo_servers_own_address_is_discovered(monkeypatch):
    monkeypatch.setattr(indigo.server, "getWebServerURL",
                        lambda: "http://indigo-mac.local:8176", raising=False)
    monkeypatch.setattr(indigo.server, "getReflectorURL",
                        lambda: "https://myhouse.indigodomo.net", raising=False)
    hosts = origin_guard.discover_own_hosts()
    assert {"localhost", "127.0.0.1", "::1", "indigo-mac.local",
            "myhouse.indigodomo.net"} <= hosts
    assert origin_allowed("https://myhouse.indigodomo.net", hosts)


def test_a_failed_lookup_still_allows_loopback():
    def _broken():
        raise OSError("no network")
    guard = OriginGuard(discover=_broken)
    assert guard.allowed("http://localhost:8176")
    assert not guard.allowed("http://indigo-mac.local")
