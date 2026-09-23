#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_advertised_capabilities.py
# Description: The server must not advertise a capability it cannot honour.
#              Pins the initialize capabilities against what the handler
#              actually implements (ClaudeBridge v2.24.3).
# Author:      CliveS & Claude Opus 5
# Date:        30-08-2026
# Version:     1.1 (behaviour, not source text: 24-09-2026)
#
# There is no push channel to a client: IWS answers one request with one
# response, and the SSE path is a buffered body built inside a single call.
# So `listChanged` can never be sent and `logging` can never be honoured.
# Advertising them cost real time — a client told it will be notified when the
# tool list changes has no reason to re-read it, which is why a session
# connected before the delete gate shipped went on stripping the new `confirm`
# argument while the plugin refused calls that were correctly made.

import json

import pytest

from mcp_server.mcp_handler import MCPHandler
from test_protocol_handle_request import _make_handler, _post

# These used to read the capabilities block out of mcp_handler.py's source
# with a regex pinned to a 20-space indent. They now run initialize and ask.


@pytest.fixture()
def server(tmp_path):
    h = _make_handler(tmp_path)
    resp = _post(h, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": MCPHandler.PROTOCOL_VERSION,
                                "clientInfo": {"name": "tests"}}})
    assert resp["status"] == 200
    caps = json.loads(resp["content"])["result"]["capabilities"]
    return h, resp["headers"]["Mcp-Session-Id"], caps


def _call(h, session, method, params=None):
    resp = _post(h, {"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}},
                 {"mcp-session-id": session})
    return json.loads(resp["content"])


def test_no_listchanged_is_advertised(server):
    """Never claim a notification with no channel to send it on."""
    _, _, caps = server
    assert not any("listChanged" in (v or {}) for v in caps.values()), (
        "listChanged is advertised again — this server has no push channel, so "
        "the notification can never be sent. Add a real channel first, or leave "
        "the claim out.")


def test_no_logging_capability_is_advertised(server):
    """`logging` means server-initiated messages plus logging/setLevel."""
    h, session, caps = server
    assert "logging" not in caps, (
        "logging is advertised, but logging/setLevel is not implemented and "
        "there is no channel for server-initiated log notifications")
    # And indeed the server does not serve it.
    assert _call(h, session, "logging/setLevel", {"level": "info"})["error"]["code"] == -32601


def test_subscribe_false_is_kept(server):
    """An accurate negative declaration is worth stating."""
    _, _, caps = server
    assert caps["resources"] == {"subscribe": False}


def test_advertised_capabilities_have_handlers(server):
    """Every advertised capability must map to methods the handler serves."""
    h, session, caps = server
    required = {
        "prompts":   ("prompts/list", "prompts/get"),
        "resources": ("resources/list", "resources/read"),
        "tools":     ("tools/list", "tools/call"),
    }
    for name, methods in required.items():
        if name in caps:
            for method in methods:
                reply = _call(h, session, method, {"name": "x", "uri": "indigo://x"})
                code = reply.get("error", {}).get("code")
                assert code != -32601, f"advertises '{name}' but does not serve {method}"


@pytest.mark.parametrize("capability", ["prompts", "resources", "tools"])
def test_the_three_real_capabilities_are_still_advertised(server, capability):
    """The fix removes false claims — it must not remove true ones."""
    _, _, caps = server
    assert capability in caps
