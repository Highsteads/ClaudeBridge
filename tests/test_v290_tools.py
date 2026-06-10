#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v290_tools.py
# Description: Regression tests for the v2.9.0 capability batch: delay/duration
#              on device_turn_on/off (guarded coercion, scheduled path skips
#              the state poll), folder-delete refusal semantics, the
#              audit_api_coverage drift detector, and payload-bytes telemetry.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import sys
import types
from unittest.mock import MagicMock

import pytest

from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
from mcp_server.tools.device_control import DeviceControlHandler
from mcp_server.tools.system_tools.system_tools_handler import SystemToolsHandler

from test_dispatch import _LOGGER, _make_handler, _tool


# ── delay / duration on the data provider ────────────────────────────────────

class _FakeDev:
    def __init__(self, name="Fan", on=False):
        self.name = name
        self.onState = on


def _provider(monkeypatch, dev=None):
    ind = sys.modules["indigo"]
    dev = dev or _FakeDev()
    devices = MagicMock()
    devices.__contains__ = MagicMock(return_value=True)
    devices.__getitem__ = MagicMock(return_value=dev)
    monkeypatch.setattr(ind, "devices", devices, raising=False)
    monkeypatch.setattr(ind, "device", MagicMock(), raising=False)
    p = object.__new__(IndigoDataProvider)
    p.logger = _LOGGER
    p._poll_for_change = lambda *a, **k: True   # pretend the state flipped
    return p, ind


def test_turn_on_passes_delay_and_duration_to_indigo(monkeypatch):
    p, ind = _provider(monkeypatch)
    result = p.turn_on_device(42, delay=0, duration=600)
    ind.device.turnOn.assert_called_once_with(42, delay=0, duration=600)
    assert result["duration_seconds"] == 600
    assert "Auto-off" in result["note"]


def test_turn_on_with_delay_returns_scheduled_without_polling(monkeypatch):
    p, ind = _provider(monkeypatch)
    p._poll_for_change = lambda *a, **k: pytest.fail("must not poll on a delayed action")
    result = p.turn_on_device(42, delay=30)
    ind.device.turnOn.assert_called_once_with(42, delay=30, duration=0)
    assert result["scheduled"] is True and result["delay_seconds"] == 30


def test_turn_off_duration_means_auto_on(monkeypatch):
    p, ind = _provider(monkeypatch)
    result = p.turn_off_device(42, duration=120)
    ind.device.turnOff.assert_called_once_with(42, delay=0, duration=120)
    assert "Auto-on" in result["note"]


@pytest.mark.parametrize("bad", ["soon", -5, "ten"])
def test_junk_delay_is_rejected_not_passed_through(monkeypatch, bad):
    p, ind = _provider(monkeypatch)
    result = p.turn_on_device(42, delay=bad)
    assert "error" in result
    ind.device.turnOn.assert_not_called()


def test_stringy_numeric_delay_is_coerced(monkeypatch):
    # Estate rule: MCP clients often send numbers as strings.
    p, ind = _provider(monkeypatch)
    result = p.turn_on_device(42, delay="30", duration="60")
    ind.device.turnOn.assert_called_once_with(42, delay=30, duration=60)
    assert result["scheduled"] is True


def test_handler_threads_kwargs_through():
    provider = MagicMock()
    provider.get_device.return_value = {"name": "Fan"}
    provider.turn_on_device.return_value = {"scheduled": True, "note": "x",
                                            "delay_seconds": 5, "duration_seconds": 0}
    h = DeviceControlHandler(data_provider=provider, logger=_LOGGER)
    h.turn_on("42", delay=5, duration=0)
    provider.turn_on_device.assert_called_once_with(42, delay=5, duration=0)


# ── folder delete semantics ───────────────────────────────────────────────────

class _FakeFolder:
    def __init__(self, fid, name):
        self.id, self.name = fid, name


def _fake_collection(monkeypatch, attr, folders, members):
    """Install a fake indigo.<devices|variables> with folders + iter()."""
    ind = sys.modules["indigo"]
    coll = types.SimpleNamespace()
    coll.folders = folders
    coll.iter = lambda: iter(members)
    coll.folder = MagicMock()
    monkeypatch.setattr(ind, attr, coll, raising=False)
    return coll


def test_delete_device_folder_refuses_non_empty(monkeypatch):
    member = types.SimpleNamespace(name="Lamp", folderId=7)
    coll = _fake_collection(monkeypatch, "devices", [_FakeFolder(7, "Spare")], [member])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_device_folder("Spare")
    assert result["success"] is False and "refusing" in result["error"]
    assert result["members"] == ["Lamp"]
    coll.folder.delete.assert_not_called()


def test_delete_device_folder_deletes_empty_by_name_or_id(monkeypatch):
    coll = _fake_collection(monkeypatch, "devices", [_FakeFolder(7, "Spare")], [])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_device_folder(7)
    assert result["success"] is True and result["deleted_children"] == 0
    args, kwargs = coll.folder.delete.call_args
    assert args[0].id == 7 and kwargs == {"deleteAllChildren": False}


def test_delete_variable_folder_cascades_only_when_asked(monkeypatch):
    member = types.SimpleNamespace(name="old_var", folderId=9)
    coll = _fake_collection(monkeypatch, "variables", [_FakeFolder(9, "Retired")], [member])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.delete_variable_folder("Retired", delete_children=True)
    assert result["success"] is True and result["deleted_children"] == 1
    coll.folder.delete.assert_called_once()
    assert coll.folder.delete.call_args.kwargs == {"deleteAllChildren": True}


def test_delete_folder_not_found(monkeypatch):
    _fake_collection(monkeypatch, "devices", [], [])
    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    assert h.delete_device_folder("NoSuch")["success"] is False


# ── audit_api_coverage drift detection ────────────────────────────────────────

def test_audit_api_coverage_detects_additions_and_removals(monkeypatch):
    ind = sys.modules["indigo"]

    def ns(**fns):
        return types.SimpleNamespace(**fns)

    f = lambda: None  # noqa: E731 — any callable will do
    # A tiny live surface: one genuinely-new method + one baseline method,
    # with everything else absent → most of the baseline reads as "removed".
    monkeypatch.setattr(ind, "device", ns(turnOn=f, fakeNewMethod=f), raising=False)
    for missing in ["dimmer", "relay", "sensor", "thermostat", "sprinkler",
                    "speedcontrol", "iodevice", "variable", "trigger", "schedule",
                    "actionGroup", "controlPage", "zwave", "insteon",
                    "devices", "variables", "triggers", "schedules",
                    "actionGroups", "controlPages"]:
        monkeypatch.delattr(ind, missing, raising=False)
    monkeypatch.setattr(ind, "server", ns(version="2025.2.0"), raising=False)

    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.audit_api_coverage()
    assert result["success"] is True
    assert "device.fakeNewMethod" in result["new_since_baseline"]
    assert "device.turnOn" not in result["removed_since_baseline"]
    assert "device.beep" in result["removed_since_baseline"]   # absent from fake live


# ── payload-bytes telemetry ───────────────────────────────────────────────────

def test_telemetry_records_response_bytes(tmp_path):
    h = _make_handler(tmp_path, tools={"list_devices": _tool(lambda **kw: "hello")})
    h._handle_tools_call(1, {"name": "list_devices", "arguments": {}})
    entry = h._tool_call_log[0]
    assert entry["bytes"] == len("hello")
