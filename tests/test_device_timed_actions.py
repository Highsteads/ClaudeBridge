#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_timed_actions.py
# Description: delay and duration on device_turn_on / device_turn_off: guarded
#              coercion, and the scheduled path skips the state poll.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v290_tools.py (v2.9.0)


import sys
from unittest.mock import MagicMock

import pytest

from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
from mcp_server.tools.device_control import DeviceControlHandler

from conftest import FakeDevice
from test_dispatch import _LOGGER


# ── delay / duration on the data provider ────────────────────────────────────
def _FakeDev(name="Fan", on=False):
    return FakeDevice(name=name, onState=on)


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
