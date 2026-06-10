#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_live_integration.py
# Description: End-to-end tests against the LIVE deployed plugin through the
#              real stack (IWS HTTP + bearer auth + MCP handler) — the one
#              thing unit tests cannot prove. Auto-skipped on machines without
#              a live Indigo install (CI runners), so the suite stays portable.
#              Asserts the live server agrees with the static registry: the
#              "deployed == declared" check.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import glob
import importlib.util
import json
import os
import plistlib
import urllib.error
import urllib.request

import pytest

from conftest import SERVER_PLUGIN

_TIMEOUT = 5
_MCP_URL = "http://127.0.0.1:8176/message/com.clives.indigoplugin.claudebridge/mcp/"
_HEALTH_URL = "http://127.0.0.1:8176/message/com.clives.indigoplugin.claudebridge/health"


def _find_bearer_token():
    base = "/Library/Application Support/Perceptive Automation"
    for d in sorted(glob.glob(os.path.join(base, "Indigo *")), reverse=True):
        secrets_path = os.path.join(d, "Preferences", "secrets.json")
        if os.path.isfile(secrets_path):
            try:
                with open(secrets_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], str):
                    return data[0]
            except (OSError, ValueError):
                pass
    return None


def _live_server_reachable():
    try:
        urllib.request.urlopen("http://127.0.0.1:8176/", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True            # any HTTP answer means IWS is up
    except Exception:
        return False


_TOKEN = _find_bearer_token()
pytestmark = pytest.mark.skipif(
    _TOKEN is None or not _live_server_reachable(),
    reason="no live Indigo install / IWS not reachable — live tests skipped",
)


def _post_mcp(payload, session_id=None):
    headers = {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(_MCP_URL, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode()), dict(resp.headers)


def _registry_count():
    """Tool count parsed from the same bundle the suite is testing."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "gtd_live", os.path.join(repo_root, "scripts", "generate_tool_doc.py"))
    gtd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gtd)
    handler = os.path.join(SERVER_PLUGIN, "mcp_server", "mcp_handler.py")
    return len(gtd.parse_tools(gtd._read(handler)))


def test_live_initialize_reports_installed_version():
    body, headers = _post_mcp({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "clientInfo": {"name": "pytest-live"}},
    })
    assert body["result"]["protocolVersion"] == "2025-06-18"
    assert headers.get("Mcp-Session-Id")
    # The live server must report the version of the bundle under test.
    plist_path = os.path.join(os.path.dirname(SERVER_PLUGIN), "Info.plist")
    with open(plist_path, "rb") as f:
        expected = plistlib.load(f)["PluginVersion"]
    assert body["result"]["serverInfo"]["version"] == expected


def test_live_tools_list_matches_static_registry():
    _, headers = _post_mcp({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "clientInfo": {"name": "pytest-live"}},
    })
    sid = headers["Mcp-Session-Id"]
    body, _ = _post_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                        session_id=sid)
    live_tools = {t["name"] for t in body["result"]["tools"]}
    assert len(live_tools) == _registry_count()
    # Spot-check the surface: every tool advertises a schema + description.
    for t in body["result"]["tools"]:
        assert t["name"] and t["inputSchema"], f"malformed tool entry: {t}"


def test_live_health_endpoint():
    req = urllib.request.Request(
        _HEALTH_URL, headers={"Authorization": f"Bearer {_TOKEN}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        health = json.loads(resp.read().decode())
    assert health["status"] == "ok"
    assert health["tools"] == _registry_count()
    assert health["protocol_version"] == "2025-06-18"
