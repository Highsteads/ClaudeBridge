#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_live_integration.py
# Description: End-to-end tests against the LIVE deployed plugin through the
#              real stack (IWS HTTP + bearer auth + MCP handler) — the one
#              thing unit tests cannot prove. Auto-skipped on machines without
#              a live Indigo install (CI runners), so the suite stays portable.
#              Asserts the live server agrees with the static registry: the
#              "deployed == declared" check.
# Author:      CliveS & Claude Fable 5; Claude Fable 5.1 (1.1)
# Date:        10-06-2026 (1.1: 11-09-2026)
# Version:     1.2
#
# v1.2 (23-09-2026): the registry comparisons now run only when the live plugin
#   is running the bundle under test (the installed mcp_handler.py is the same
#   file). Testing the repo ahead of a deploy — the spring clean removed ten
#   tools the installed plugin still serves — used to fail on a difference the
#   test exists to report AFTER deployment, not before it. When the suite runs
#   against the installed bundle (conftest's default) nothing is skipped.
#
# v1.1 (11-09-2026): since 2.26.0 the live tools/list also carries the tools
#   other plugins provide (the Dashboards plugin's eight, here), each with
#   "[provided by the <Name> plugin]" on the end of its description. Those are
#   not in the static registry, so "deployed == declared" now means the BUILT-IN
#   tools equal the registry and the health count equals registry + providers.
#   Both tests had been red on this Mac since 2.26.0 shipped.

import filecmp
import glob
import json
import os
import plistlib
import re
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
    """Tool count from the registry of the same bundle the suite is testing."""
    from mcp_server import registry
    return len(registry.load())


def _installed_server_plugin():
    base = "/Library/Application Support/Perceptive Automation"
    for d in sorted(glob.glob(os.path.join(base, "Indigo *")), reverse=True):
        sp = os.path.join(d, "Plugins", "Claude Bridge.indigoPlugin",
                          "Contents", "Server Plugin")
        if os.path.isdir(sp):
            return sp
    return None


def _require_live_runs_bundle_under_test():
    """Skip a registry comparison when the live plugin runs different code.

    The comparison is "deployed == declared", which only means something when
    the deployed code IS the code under test. The registry lives in
    mcp_handler.py, so that file decides.
    """
    installed = _installed_server_plugin()
    if installed is None:
        pytest.skip("no installed Claude Bridge bundle to compare against")
    rel = os.path.join("mcp_server", "mcp_handler.py")
    if os.path.realpath(installed) == os.path.realpath(SERVER_PLUGIN):
        return
    if not filecmp.cmp(os.path.join(installed, rel),
                       os.path.join(SERVER_PLUGIN, rel), shallow=False):
        pytest.skip("the live plugin is not running the bundle under test "
                    "(installed mcp_handler.py differs) — deploy, then re-run")


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


_PROVIDED_RE = re.compile(r"\[provided by the .+ plugin\]$")


def _live_tools():
    """(built-in names, provider-tool names) from a fresh session's tools/list.
    A provider tool is one another plugin contributed through its manifest;
    the manager marks each with the suffix _PROVIDED_RE matches."""
    _, headers = _post_mcp({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "clientInfo": {"name": "pytest-live"}},
    })
    sid = headers["Mcp-Session-Id"]
    body, _ = _post_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                        session_id=sid)
    tools = body["result"]["tools"]
    # Spot-check the surface: every tool advertises a schema + description.
    for t in tools:
        assert t["name"] and t["inputSchema"], f"malformed tool entry: {t}"
    provided = {t["name"] for t in tools if _PROVIDED_RE.search(t.get("description", ""))}
    builtin = {t["name"] for t in tools} - provided
    return builtin, provided


def test_live_tools_list_matches_static_registry():
    _require_live_runs_bundle_under_test()
    builtin, provided = _live_tools()
    assert len(builtin) == _registry_count(), (
        f"{len(builtin)} built-in tools live against {_registry_count()} in the "
        f"registry ({len(provided)} provider tools set aside)")


def test_live_health_endpoint():
    req = urllib.request.Request(
        _HEALTH_URL, headers={"Authorization": f"Bearer {_TOKEN}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        health = json.loads(resp.read().decode())
    assert health["status"] == "ok"
    assert health["protocol_version"] == "2025-06-18"
    _require_live_runs_bundle_under_test()
    _, provided = _live_tools()
    assert health["tools"] == _registry_count() + len(provided)
