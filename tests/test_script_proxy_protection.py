#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_proxy_protection.py
# Description: The Claude Code proxy the plugin deploys into Scripts/ holds the
#              live access key. No script tool may read, list, write, archive or
#              run it, whatever the key's scope, and a key without admin gets
#              every known secret value blanked from script text, automation
#              scripts and the event log. Run through the real dispatcher
#              against a temporary Perceptive Automation folder.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

import json
import logging
import os
import threading
from collections import deque

import pytest

import indigo  # the conftest stub
from mcp_server import client_setup
from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager
from mcp_server.tools.script_tools import ScriptToolsHandler
from mcp_server.tools.system_tools import SystemToolsHandler

from conftest import SERVER_PLUGIN

_LOGGER = logging.getLogger("test-script-proxy")

TOKEN = "live-access-key-0123456789abcdef"
READ_KEY = "phone-read-key"
ADMIN_KEY = "desk-admin-key"


@pytest.fixture()
def pa(tmp_path, monkeypatch):
    """A Perceptive Automation folder with both script folders, Indigo's
    secrets.json holding TOKEN, and the proxy deployed exactly as the plugin
    deploys it at start."""
    root = tmp_path / "Perceptive Automation"
    install = root / "Indigo 2025.2"
    (install / "Preferences").mkdir(parents=True)
    (install / "Preferences" / "secrets.json").write_text(json.dumps([TOKEN]))
    (root / "Python Scripts").mkdir()
    monkeypatch.setattr(indigo.server, "getInstallFolderPath", lambda: str(install),
                        raising=False)
    assert client_setup.deploy_proxy(SERVER_PLUGIN, str(install), "", _LOGGER) is True
    proxy = root / "Scripts" / client_setup.PROXY_NAME
    assert TOKEN in proxy.read_text(encoding="utf-8")
    return root


class _Details:
    """automation_detail_handler double: an action group whose embedded
    script has the key typed into it."""

    def get_details(self, kind, id, include_scripts=True):
        return {"success": True, "kind": kind, "id": id,
                "steps": [{"type": "script", "source": f'KEY = "{TOKEN}"\n'}]}


@pytest.fixture()
def handler(tmp_path):
    scopes = tmp_path / "scopes.json"
    scopes.write_text(json.dumps({"tokens": {
        READ_KEY: {"name": "phone", "scopes": ["read"]},
        ADMIN_KEY: {"name": "desk", "scopes": ["read", "write", "admin"]},
    }}), encoding="utf-8")
    h = object.__new__(MCPHandler)
    h.logger = _LOGGER
    h.plugin = None
    h._secret_redactor = None
    h.scope_manager = ScopeManager(scopes_file=str(scopes), logger=_LOGGER)
    h.rate_limiter = RateLimiter(logger=_LOGGER)
    h.tool_cache = ToolCache(default_ttl=0, logger=_LOGGER)
    h._telemetry_lock = threading.Lock()
    h._tool_call_log = deque(maxlen=200)
    h._tool_error_count = 0
    h.entity_index_manager = None
    h.script_tools_handler = ScriptToolsHandler(data_provider=None, logger=_LOGGER)
    h.system_tools_handler = SystemToolsHandler(data_provider=None, logger=_LOGGER)
    h.automation_detail_handler = _Details()
    h._tools = h._build_tools()
    h._resources = {}
    h._register_resources()
    return h


def _call(h, key, tool, /, **args):
    resp = h._handle_tools_call(1, {"name": tool, "arguments": args},
                                {"authorization": f"Bearer {key}"})
    assert "result" in resp, resp
    return resp["result"]["isError"], resp["result"]["content"][0]["text"]


# ── The proxy itself is out of reach ─────────────────────────────────────────

@pytest.mark.parametrize("key", [READ_KEY, ADMIN_KEY])
@pytest.mark.parametrize("name", ["indigo_mcp_proxy", "indigo_mcp_proxy.py",
                                  "INDIGO_MCP_PROXY.PY", "../Scripts/indigo_mcp_proxy.py"])
def test_read_script_never_returns_the_proxy(pa, handler, key, name):
    is_error, text = _call(handler, key, "read_script", name=name)
    assert is_error
    assert TOKEN not in text
    assert "proxy" in text.lower()


def test_a_link_to_the_proxy_under_another_name_is_refused(pa, handler):
    link = pa / "Python Scripts" / "innocent.py"
    os.symlink(pa / "Scripts" / client_setup.PROXY_NAME, link)
    is_error, text = _call(handler, READ_KEY, "read_script", name="innocent")
    assert is_error and TOKEN not in text


def test_list_python_scripts_leaves_the_proxy_out(pa, handler):
    (pa / "Scripts" / "Garden.py").write_text("print('hi')\n")
    is_error, text = _call(handler, READ_KEY, "list_python_scripts")
    assert not is_error
    names = [s["name"] for s in json.loads(text)["scripts"]]
    assert names == ["Garden.py"]
    assert TOKEN not in text


def test_write_script_cannot_overwrite_the_proxy(pa, handler):
    proxy = pa / "Scripts" / client_setup.PROXY_NAME
    before = proxy.read_text(encoding="utf-8")
    is_error, text = _call(handler, ADMIN_KEY, "write_script",
                           name="indigo_mcp_proxy", content="print(BEARER_TOKEN)\n")
    assert is_error
    assert "proxy" in text.lower()          # the refusal survives the error scrub
    assert proxy.read_text(encoding="utf-8") == before
    # No backup of it was taken either: a backup would be a second readable copy.
    assert not (pa / "Python Scripts" / "_backups").exists()


def test_write_script_create_cannot_make_one_in_its_place(pa, handler):
    (pa / "Scripts" / client_setup.PROXY_NAME).unlink()
    is_error, _ = _call(handler, ADMIN_KEY, "write_script", name="Indigo_MCP_Proxy",
                        content="x = 1\n", create=True)
    assert is_error
    assert not any(p.name.lower() == client_setup.PROXY_NAME
                   for p in (pa / "Python Scripts").iterdir())


def test_delete_and_run_are_refused(pa, handler):
    proxy = pa / "Scripts" / client_setup.PROXY_NAME
    for tool in ("delete_script", "run_script"):
        is_error, text = _call(handler, ADMIN_KEY, tool, name="indigo_mcp_proxy")
        assert is_error, tool
        assert TOKEN not in text
    assert proxy.exists()


def test_its_backups_are_not_listed(pa, handler):
    is_error, _ = _call(handler, READ_KEY, "list_python_scripts",
                        backups_for="indigo_mcp_proxy.py")
    assert is_error


# ── What read_script can reach in Scripts/ ───────────────────────────────────

def test_read_script_reaches_ordinary_scripts_in_both_folders(pa, handler):
    (pa / "Scripts" / "Porch.py").write_text("print('porch')\n")
    (pa / "Python Scripts" / "Hall.py").write_text("print('hall')\n")
    for name, body in (("Porch", "porch"), ("Hall", "hall")):
        is_error, text = _call(handler, READ_KEY, "read_script", name=name)
        assert not is_error
        assert body in json.loads(text)["content"]


def test_a_key_typed_into_a_script_is_blanked_for_a_read_key_only(pa, handler):
    (pa / "Scripts" / "Uses_Key.py").write_text(f'KEY = "{TOKEN}"\n')
    is_error, text = _call(handler, READ_KEY, "read_script", name="Uses_Key")
    assert not is_error
    assert TOKEN not in text
    assert "[redacted IWS_API_KEY]" in json.loads(text)["content"]

    is_error, text = _call(handler, ADMIN_KEY, "read_script", name="Uses_Key")
    assert not is_error and TOKEN in json.loads(text)["content"]


def test_embedded_automation_scripts_are_blanked_for_a_read_key(pa, handler):
    _, text = _call(handler, READ_KEY, "get_automation", kind="action_group", id=5)
    assert TOKEN not in text
    _, text = _call(handler, ADMIN_KEY, "get_automation", kind="action_group", id=5)
    assert TOKEN in text


def test_the_event_log_resource_is_blanked_for_a_read_key(pa, handler, monkeypatch):
    monkeypatch.setattr(indigo.server, "getEventLogList", lambda **kw: [
        {"TimeStamp": "t", "TypeStr": "Script", "TypeVal": 8,
         "Message": f"connecting with {TOKEN}"}], raising=False)
    params = {"uri": "indigo://logs/recent"}
    read = handler._handle_resources_read(1, params, {"authorization": f"Bearer {READ_KEY}"})
    assert TOKEN not in json.dumps(read)
    admin = handler._handle_resources_read(1, params, {"authorization": f"Bearer {ADMIN_KEY}"})
    assert TOKEN in admin["result"]["contents"][0]["text"]


def test_redaction_fails_closed(pa, handler, monkeypatch):
    """If the secret values cannot be read, a read key gets nothing, not the
    unredacted text."""
    (pa / "Scripts" / "Uses_Key.py").write_text(f'KEY = "{TOKEN}"\n')

    def _broken():
        raise OSError("unreadable")
    monkeypatch.setattr(handler, "_get_secret_redactor", _broken)
    is_error, text = _call(handler, READ_KEY, "read_script", name="Uses_Key")
    assert is_error and TOKEN not in text
