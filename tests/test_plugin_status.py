#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_status.py
# Description: get_plugin_status reports whether a plugin is RUNNING (enabled
#              only says it should be), is never served from the TTL cache,
#              and restart_plugin names a mistyped id as not found rather than
#              "not enabled".
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import logging
from unittest.mock import MagicMock

import pytest

from mcp_server.common.tool_cache import CACHEABLE_TOOLS
from mcp_server.tools.plugin_control import plugin_control_handler as pc

INSTALLED = [{"id": "com.example.good", "name": "Good", "version": "1.2", "path": "/x"}]


@pytest.fixture
def handler(monkeypatch):
    fake = MagicMock()
    plugins = {}

    def _get(pid):
        return plugins.setdefault(pid, MagicMock(name=pid))

    fake.server.getPlugin.side_effect = _get
    monkeypatch.setattr(pc, "indigo", fake)
    h = pc.PluginControlHandler(data_provider=MagicMock(), logger=logging.getLogger("t"))
    monkeypatch.setattr(h, "_get_cached_plugins", lambda include_disabled: INSTALLED)
    h.plugins = plugins
    return h


def test_status_reports_running_separately_from_enabled(handler):
    p = handler.plugins.setdefault("com.example.good", MagicMock())
    p.isEnabled.return_value = True
    p.isRunning.return_value = False          # died in startup()
    out = handler.get_plugin_status("com.example.good")
    assert out["status"]["enabled"] is True
    assert out["status"]["running"] is False


def test_running_is_none_when_indigo_cannot_say(handler):
    p = handler.plugins.setdefault("com.example.good", MagicMock())
    p.isRunning.side_effect = AttributeError("old Indigo")
    out = handler.get_plugin_status("com.example.good")
    assert out["status"]["running"] is None


def test_status_is_not_cached():
    assert "get_plugin_status" not in CACHEABLE_TOOLS


def test_restart_of_a_mistyped_id_says_not_found(handler):
    out = handler.restart_plugin("com.example.typo")
    assert out["success"] is False
    assert "not found" in out["error"]
    assert "com.example.typo" not in handler.plugins   # never reached getPlugin


def test_restart_of_an_installed_plugin_goes_ahead(handler):
    p = handler.plugins.setdefault("com.example.good", MagicMock())
    p.isEnabled.return_value = True
    out = handler.restart_plugin("com.example.good")
    assert out["success"] is True
    p.restart.assert_called_once_with(waitUntilDone=False)


def test_scan_cache_is_short():
    assert pc.PluginControlHandler.CACHE_DURATION <= 60
