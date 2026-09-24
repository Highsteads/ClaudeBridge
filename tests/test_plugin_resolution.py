#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_resolution.py
# Description: Plugin names resolve to exactly one bundle or refuse; Indigo's
#              hidden built-in plugins are listed; lock PINs never reach the
#              event log; the HTML check skips non-JavaScript blocks; address
#              clashes ignore a device's own sub-devices (3.0.2).
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import os
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.audit import audit_handler as ah
from mcp_server.tools.base_handler import BaseToolHandler, CallerError
from mcp_server.tools.plugin_control import plugin_control_handler as pch
from mcp_server.tools.plugin_control.plugin_scanner import PluginScanner
from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as pdt


def _plugins_dir(tmp_path, *names):
    for n in names:
        (tmp_path / f"{n}.indigoPlugin" / "Contents").mkdir(parents=True)
    return str(tmp_path)


def test_partial_name_matching_several_bundles_is_refused(tmp_path, monkeypatch):
    pd = _plugins_dir(tmp_path, "Claude Bridge", "ESPHomeBridge", "Zigbee2MQTTBridge")
    monkeypatch.setattr(pdt, "_plugins_dir", lambda: pd)
    with pytest.raises(CallerError) as e:
        pdt._resolve_installed_bundle("Bridge")
    assert "ESPHomeBridge" in str(e.value) and "Zigbee2MQTTBridge" in str(e.value)


def test_exact_and_single_partial_names_resolve(tmp_path, monkeypatch):
    pd = _plugins_dir(tmp_path, "ESPHomeBridge", "Zigbee2MQTTBridge", ".Z-Wave")
    monkeypatch.setattr(pdt, "_plugins_dir", lambda: pd)
    assert pdt._resolve_installed_bundle("zigbee2mqttbridge").lower().endswith("zigbee2mqttbridge.indigoplugin")
    assert pdt._resolve_installed_bundle("ESPHome").endswith("ESPHomeBridge.indigoPlugin")
    assert pdt._resolve_installed_bundle("Z-Wave").endswith(".Z-Wave.indigoPlugin")


def test_scanner_sees_hidden_builtin_plugins(tmp_path, monkeypatch):
    _plugins_dir(tmp_path, ".Z-Wave", "Visible")
    s = PluginScanner(logging.getLogger("t"))
    seen = []
    monkeypatch.setattr(s, "_parse_plugin_bundle", lambda p, e: seen.append(os.path.basename(p)) or {"id": p})
    s._scan_directory(str(tmp_path), True)
    assert ".Z-Wave.indigoPlugin" in seen


def test_caller_errors_log_as_warnings(caplog):
    h = BaseToolHandler("t", logger=logging.getLogger("t"))
    with caplog.at_level(logging.DEBUG, logger="t"):
        h.handle_exception(CallerError("ambiguous"))
        h.handle_exception(RuntimeError("boom"))
    levels = [r.levelname for r in caplog.records]
    assert levels == ["WARNING", "ERROR"]


def test_outcome_levels(caplog):
    h = BaseToolHandler("t", logger=logging.getLogger("t"))
    with caplog.at_level(logging.DEBUG, logger="t"):
        h.log_tool_outcome("read", True)
        h.log_tool_outcome("refused", False)
        h.log_tool_outcome("caller code", False, level=logging.DEBUG)
    assert [r.levelname for r in caplog.records] == ["DEBUG", "WARNING", "DEBUG"]


@pytest.mark.parametrize("key, secret", [("userPin", True), ("code", True), ("password", True),
                                         ("apiKey", True), ("brightness", False), ("zone", False)])
def test_secret_props_are_masked(key, secret):
    assert pch._is_secret_prop(key) is secret


@pytest.mark.parametrize("attrs, stype", [('', ''), (' type="module"', 'module'),
                                          (" type='application/json'", 'application/json'),
                                          (' TYPE="text/template"', 'text/template')])
def test_script_type(attrs, stype):
    assert pdt._script_type(attrs) == stype


def test_sub_devices_of_one_node_are_not_a_clash(monkeypatch):
    fake = MagicMock()
    fake.device.getGroupList.side_effect = lambda i: [1, 2, 3] if i in (1, 2, 3) else [i]
    monkeypatch.setattr(ah, "indigo", fake, raising=False)
    assert ah._one_device_group([1, 2, 3]) is True
    assert ah._one_device_group([4, 5]) is False
