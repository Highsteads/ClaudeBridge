#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_handler_smoke.py
# Description: Behavioural smoke tests for the bread-and-butter tool handlers
#              that previously had no regression coverage: device_control
#              (device-id coercion incl. the JSON-bool rejection, on/off/
#              brightness validation), variable_control (id coercion + the
#              secret-preview truncation) and home_status (response shape over
#              a faked Indigo estate).
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import logging
import sys
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.device_control import DeviceControlHandler
from mcp_server.tools.home_status import HomeStatusHandler
from mcp_server.tools.variable_control import VariableControlHandler
from mcp_server.tools.variable_control.variable_control_handler import _preview

_LOGGER = logging.getLogger("test-handlers")


# ── device_control: _coerce_device_id ─────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (True,    None),     # JSON true must NOT become device ID 1
    (False,   None),     # JSON false must NOT become device ID 0
    ("123",   123),
    (" 42 ",  42),
    ("-5",    -5),
    ("abc",   "abc"),    # non-numeric string passes through → rejected later
    (7,       7),
])
def test_coerce_device_id(raw, expected):
    assert DeviceControlHandler._coerce_device_id(raw) == expected


def test_turn_on_rejects_bool_device_id_without_touching_provider():
    provider = MagicMock()
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.turn_on(True)
    assert result["success"] is False and "integer" in result["error"]
    provider.turn_on_device.assert_not_called()


def test_turn_on_coerces_string_id_and_delegates():
    provider = MagicMock()
    provider.get_device.return_value = {"name": "Hall Lamp"}
    provider.turn_on_device.return_value = {"success": True, "changed": True}
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.turn_on("123")
    provider.turn_on_device.assert_called_once_with(123)
    assert result == {"success": True, "changed": True}


def test_turn_off_delegates_and_passes_result_through():
    provider = MagicMock()
    provider.get_device.return_value = None
    provider.turn_off_device.return_value = {"error": "device not found"}
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    assert h.turn_off(99) == {"error": "device not found"}


def test_set_brightness_rejects_non_numeric_level():
    provider = MagicMock()
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.set_brightness(123, "bright")
    assert result["success"] is False and "number" in result["error"]
    provider.set_device_brightness.assert_not_called()


def test_set_brightness_delegates_valid_call():
    provider = MagicMock()
    provider.get_device.return_value = {"name": "Lamp"}
    provider.set_device_brightness.return_value = {"success": True, "changed": True}
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    h.set_brightness("123", 50)
    provider.set_device_brightness.assert_called_once_with(123, 50)


# ── variable_control ──────────────────────────────────────────────────────────

def test_variable_update_coerces_string_id_and_delegates():
    provider = MagicMock()
    provider.get_variable.return_value = {"name": "my_var"}
    provider.update_variable.return_value = {"success": True,
                                             "previous": "old", "current": "new"}
    h = VariableControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.update("55", "new")
    provider.update_variable.assert_called_once_with(55, "new")
    assert result["success"] is True


def test_variable_update_rejects_non_numeric_id():
    provider = MagicMock()
    h = VariableControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.update("not-an-id", "x")
    assert result["success"] is False and "integer" in result["error"]
    provider.update_variable.assert_not_called()


def test_variable_create_requires_name():
    provider = MagicMock()
    h = VariableControlHandler(data_provider=provider, logger=_LOGGER)
    result = h.create("")
    assert result["success"] is False
    provider.create_variable.assert_not_called()


def test_preview_truncates_long_values_for_the_log():
    secret = "sk-" + "a" * 100
    out = _preview(secret)
    assert len(out) < len(secret)
    assert "103 chars" in out
    assert _preview("short") == "short"     # short values untouched


# ── home_status shape over a faked estate ─────────────────────────────────────

class _FakeDevice:
    def __init__(self, dev_id, name, plugin_id, on=False, states=None,
                 brightness=None, error=""):
        self.id = dev_id
        self.name = name
        self.enabled = True
        self.pluginId = plugin_id
        self.onState = on
        self.states = states or {}
        self.errorState = error
        if brightness is not None:
            self.brightness = brightness


class _FakeVariable:
    def __init__(self, var_id, name, value):
        self.id, self.name, self.value = var_id, name, value


class _FakeEnabled:
    def __init__(self, enabled=True):
        self.enabled = enabled


def test_home_status_shape(monkeypatch):
    ind = sys.modules["indigo"]
    devices = {
        1: _FakeDevice(1, "Hall Lamp", "com.x.zigbee", on=True, brightness=70),
        2: _FakeDevice(2, "Door Sensor", "com.x.sensor",
                       states={"batteryLevel": 15}),
        3: _FakeDevice(3, "Broken Plug", "com.x.shelly", error="offline"),
    }
    variables = {10: _FakeVariable(10, "battery_soc", "94.1"),
                 11: _FakeVariable(11, "unrelated_note", "hi")}
    monkeypatch.setattr(ind, "devices", devices, raising=False)
    monkeypatch.setattr(ind, "variables", variables, raising=False)
    monkeypatch.setattr(ind, "triggers", {20: _FakeEnabled(True), 21: _FakeEnabled(False)}, raising=False)
    monkeypatch.setattr(ind, "schedules", {30: _FakeEnabled(True)}, raising=False)
    monkeypatch.setattr(ind, "actionGroups", {40: object()}, raising=False)

    h = HomeStatusHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.home_status()

    assert result["success"] is True
    # Alerts: the offline plug and the 15% battery sensor must surface.
    error_names = [e["name"] for e in result["alerts"]["devices_in_error"]]
    assert "Broken Plug" in error_names
    batt = result["alerts"]["low_battery"]
    assert batt and batt[0]["name"] == "Door Sensor" and batt[0]["battery_pct"] == 15
    # Grouping: zigbee dimmer → lights; shelly → energy.
    assert any(d["name"] == "Hall Lamp" for d in result["devices"]["lights"])
    assert any(d["name"] == "Broken Plug" for d in result["devices"]["energy"])
    # Key variables filtered by pattern: battery_soc in, unrelated_note out.
    key_names = [v["name"] for v in result["key_variables"]]
    assert "battery_soc" in key_names and "unrelated_note" not in key_names
    # Automation counts reflect enabled flags.
    assert result["automation"]["enabled_triggers"] == 1
    assert result["automation"]["total_triggers"] == 2
    assert result["automation"]["total_schedules"] == 1
    assert result["automation"]["total_action_groups"] == 1
