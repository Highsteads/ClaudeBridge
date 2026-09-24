#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_lifecycle.py
# Description: plugin.py start-up, device status and small callbacks: a failed
#              Claude Code setup no longer aborts start-up, a failed start-up
#              stops what it started, the device says "Unavailable" when the
#              MCP server is not up, lastActivity is throttled, a webhook
#              disable does not block the dispatch thread, unwatched devices
#              are not copied for the webhooks, and the menu text is honest.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import SERVER_PLUGIN, load_plugin_module

_LOG = logging.getLogger("test-plugin-lifecycle")


def _bare(mod):
    p = object.__new__(mod.Plugin)
    p.pluginId = "com.clives.indigoplugin.claudebridge"
    p.pluginVersion = "test"
    p.pluginDisplayName = "Claude Bridge"
    p.logger = _LOG
    p.pluginPrefs = {}
    p.allow_destructive_delete = False
    p.rate_limit_per_minute, p.rate_limit_per_day, p.cache_ttl_seconds = 120, 5000, 60
    p.mcp_handler = None
    p.mcp_server_device = None
    p.webhook_manager = None
    p.webhook_dispatcher = None
    p.webhooks_enabled = False
    p._last_activity_write = 0.0
    return p


@pytest.fixture
def started(monkeypatch, tmp_path):
    """A Plugin ready to run startup() against doubles; records the order of
    the steps that matter."""
    mod = load_plugin_module()
    p = _bare(mod)
    order = []
    ind = sys.modules["indigo"]
    install = str(tmp_path / "Indigo 2025.2")
    monkeypatch.setattr(ind, "server", SimpleNamespace(getInstallFolderPath=lambda: install,
                                                       getReflectorURL=lambda: None))
    monkeypatch.setattr(ind, "devices", MagicMock())
    monkeypatch.setattr(ind, "variables", MagicMock())
    monkeypatch.setattr(ind, "actionGroups", MagicMock())
    ind.devices.subscribeToChanges.side_effect = lambda: order.append("subscribe")
    ind.devices.iter.return_value = [SimpleNamespace(deviceTypeId="mcpServer")]
    handler = MagicMock()
    monkeypatch.setattr(mod, "IndigoDataProvider", MagicMock())
    monkeypatch.setattr(mod, "MCPHandler", MagicMock(return_value=handler))
    p._init_webhooks = MagicMock(side_effect=lambda: order.append("webhooks"))
    setup = MagicMock(side_effect=lambda *a, **k: order.append("claude-code") or [])
    monkeypatch.setattr(mod.client_setup, "setup_claude_code_integration", setup)
    monkeypatch.chdir(SERVER_PLUGIN)
    return SimpleNamespace(plugin=p, handler=handler, setup=setup, order=order, mod=mod)


# ── H1 ───────────────────────────────────────────────────────────────────────

def test_claude_code_setup_runs_last(started):
    started.plugin.startup()
    assert started.order == ["webhooks", "subscribe", "claude-code"]


def test_a_failed_claude_code_setup_does_not_abort_startup(started, caplog):
    started.setup.side_effect = PermissionError(13, "Permission denied", "/x/Scripts")
    with caplog.at_level(logging.WARNING, logger=_LOG.name):
        started.plugin.startup()
    assert started.plugin.mcp_handler is started.handler, "the MCP server was thrown away"
    started.plugin._init_webhooks.assert_called_once()
    assert "subscribe" in started.order
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Claude Code auto-configure failed" in r.getMessage() for r in warnings)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_failed_startup_stops_what_it_started(started, monkeypatch):
    p = started.plugin
    monkeypatch.setattr(p, "_get_mcp_client_urls", MagicMock(side_effect=RuntimeError("late fault")))
    p.startup()
    started.handler.stop.assert_called_once()       # its entity-index threads
    assert p.mcp_handler is None
    started.setup.assert_not_called()


def test_a_failed_startup_after_webhooks_stops_the_webhook_worker(started):
    p = started.plugin
    dispatcher, manager = MagicMock(), MagicMock()

    def _init_then_fail():
        p.webhook_dispatcher, p.webhook_manager = dispatcher, manager
        raise RuntimeError("fault after the webhook worker started")

    p._init_webhooks = MagicMock(side_effect=_init_then_fail)
    p.startup()
    dispatcher.stop.assert_called_once()
    manager.shutdown.assert_called_once()
    started.handler.stop.assert_called_once()
    assert p.mcp_handler is None


# ── L4 ───────────────────────────────────────────────────────────────────────

class _Dev:
    def __init__(self, **states):
        self.deviceTypeId = "mcpServer"
        self.name = "Claude Bridge"
        self.id = 1
        self.states = dict(states)
        self.writes = []

    def updateStatesOnServer(self, updates):
        for u in updates:
            self.states[u["key"]] = u["value"]
            self.writes.append(u["key"])

    def updateStateOnServer(self, key, value):
        self.states[key] = value
        self.writes.append(key)


@pytest.mark.parametrize("handler,expected", [(None, "Unavailable"), (object(), "Running")])
def test_device_status_follows_the_mcp_handler(monkeypatch, handler, expected):
    mod = load_plugin_module()
    p = _bare(mod)
    p.mcp_handler = handler
    monkeypatch.setattr(sys.modules["indigo"], "server", SimpleNamespace(getTime=lambda: "now"))
    dev = _Dev(serverStatus="Stopped")
    p.deviceStartComm(dev)
    assert dev.states["serverStatus"] == expected


def test_last_activity_is_written_at_most_once_a_minute(monkeypatch):
    mod = load_plugin_module()
    p = _bare(mod)
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sys.modules["indigo"], "server", SimpleNamespace(getTime=lambda: "t"))
    dev = _Dev()
    p.mcp_server_device = dev
    p._note_activity()
    p._note_activity()
    clock[0] += 59
    p._note_activity()
    assert dev.writes == ["lastActivity"]
    clock[0] += 2
    p._note_activity()
    assert dev.writes == ["lastActivity", "lastActivity"]


def test_a_request_stamps_activity(monkeypatch):
    mod = load_plugin_module()
    p = _bare(mod)
    p.mcp_handler = MagicMock()
    p.mcp_handler.handle_request.return_value = {"status": 200}
    p._note_activity = MagicMock()
    action = SimpleNamespace(props={"incoming_request_method": "POST", "headers": {}, "request_body": ""})
    assert p.handle_mcp_endpoint(action) == {"status": 200}
    p._note_activity.assert_called_once()


# ── L1, L6 and the webhook watch set ─────────────────────────────────────────

def test_disabling_webhooks_does_not_join_on_the_dispatch_thread():
    mod = load_plugin_module()
    p = _bare(mod)
    p.webhooks_enabled = True
    p.webhook_dispatcher = MagicMock()
    p.webhook_manager = MagicMock()
    p._read_webhook_config = lambda: setattr(p, "webhooks_enabled", False)
    p._reconfigure_webhooks()
    p.webhook_dispatcher.stop.assert_called_once_with(wait=False)


def test_the_timestamp_toggle_is_saved_at_once():
    mod = load_plugin_module()
    p = _bare(mod)
    p.timestamp_enabled = True
    p._ts_filter = None
    p.savePluginPrefs = MagicMock()
    p.menuToggleTimestamps()
    assert p.pluginPrefs["timestampEnabled"] is False
    p.savePluginPrefs.assert_called_once()


class _Counted:
    """Counts every attempt to copy it into a dict. (Raising would not do: the
    webhook hook contains every exception, so a raise would pass unnoticed.)"""
    copies = 0

    def __init__(self, dev_id):
        self.id = dev_id

    def keys(self):
        type(self).copies += 1
        return ["id"]

    def __getitem__(self, key):
        return self.id


def test_an_unwatched_device_is_not_copied_for_the_webhooks():
    from mcp_server.webhooks.subscription_manager import SubscriptionManager
    from mcp_server.webhooks.subscription_model import Subscription
    mod = load_plugin_module()
    p = _bare(mod)
    p.webhooks_enabled = True
    p.webhook_dispatcher = MagicMock()
    p.webhook_manager = SubscriptionManager()
    p.webhook_manager.add(Subscription(webhook_url="https://x", entity_type="device", entity_id=5))
    _Counted.copies = 0
    p._webhook_on_device_change(_Counted(77), _Counted(77))
    assert _Counted.copies == 0, "dict() was built for a device nobody watches"
    p._webhook_on_device_change(_Counted(5), _Counted(5))
    assert _Counted.copies == 2, "a watched device must still be evaluated"


# ── Info items ───────────────────────────────────────────────────────────────

def test_the_starter_scopes_file_gives_unlisted_tokens_read_only(monkeypatch, tmp_path):
    mod = load_plugin_module()
    p = _bare(mod)
    install = tmp_path / "Indigo 2025.2"
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "server", SimpleNamespace(getInstallFolderPath=lambda: str(install),
                                                       log=lambda *a, **k: None))
    p.scaffold_scopes_menu()
    path = install / "Preferences/Plugins/com.clives.indigoplugin.claudebridge/scopes.json"
    assert json.loads(path.read_text(encoding="utf-8"))["default_scopes"] == ["read"]

    path.write_text('{"default_scopes": ["read", "write", "admin"]}', encoding="utf-8")
    p.scaffold_scopes_menu()                        # an existing file is never rewritten
    assert json.loads(path.read_text(encoding="utf-8"))["default_scopes"] == ["read", "write", "admin"]


def test_show_plugin_info_names_the_scopes_path(monkeypatch, tmp_path):
    mod = load_plugin_module()
    p = _bare(mod)
    p.timestamp_enabled = True
    monkeypatch.setattr(sys.modules["indigo"], "server",
                        SimpleNamespace(getInstallFolderPath=lambda: str(tmp_path / "Indigo 2025.2")))
    banner = MagicMock()
    monkeypatch.setattr(mod, "log_startup_banner", banner)
    monkeypatch.setattr(p, "_get_mcp_client_urls", lambda: [])
    p.showPluginInfo()
    extras = dict(banner.call_args.kwargs["extras"])
    assert extras["scopes.json:"].endswith("com.clives.indigoplugin.claudebridge/scopes.json")


def test_the_client_info_menu_points_at_the_docs_and_keeps_tls_on(monkeypatch, tmp_path):
    mod = load_plugin_module()
    p = _bare(mod)
    logged = []
    monkeypatch.setattr(sys.modules["indigo"], "server", SimpleNamespace(
        getInstallFolderPath=lambda: str(tmp_path / "Indigo 2025.2"), version="2025.2.0",
        log=lambda text, **k: logged.append(text)))
    monkeypatch.setattr(p, "_get_mcp_client_urls", lambda: [
        {"label": "Network (IP)", "url": "http://192.0.2.10:8176/message/x/mcp/"}])
    p.show_mcp_client_info_menu()
    text = "\n".join(logged)
    assert "https://docs.indigodomo.com/2025.2/user/remote-access/web-server/" in text
    assert "wiki.indigodomo.com" not in text
    assert '"NODE_TLS_REJECT_UNAUTHORIZED"' not in text
    assert "NODE_EXTRA_CA_CERTS" in text


def test_the_reenable_menu_item_is_wired():
    mod = load_plugin_module()
    root = ET.parse(os.path.join(SERVER_PLUGIN, "MenuItems.xml")).getroot()
    callbacks = {m.findtext("CallbackMethod") for m in root.iter("MenuItem")}
    assert "reenable_webhooks_menu" in callbacks
    assert hasattr(mod.Plugin, "reenable_webhooks_menu")


def test_the_config_dialog_no_longer_promises_fallback_fields():
    text = open(os.path.join(SERVER_PLUGIN, "PluginConfig.xml"), encoding="utf-8").read()
    assert "fields below are a fallback" not in text


def test_the_energy_prompt_is_not_tied_to_one_installation():
    from mcp_server.prompts import get_prompt
    text = get_prompt("energy_day_review", {})["messages"][0]["content"]["text"]
    assert "Sigenergy" not in text and "KPI" not in text
