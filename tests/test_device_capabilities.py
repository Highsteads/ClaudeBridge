#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_capabilities.py
# Description: Tests for LIVE device-capability awareness (ClaudeBridge
#              v2.16.0) — reads supports* flags straight off the device, no
#              catalogue. Refusals fire only on an explicit live False.
# Author:      CliveS & Claude Opus 4.8
# Date:        23-07-2026
# Version:     1.0

import pytest

from mcp_server.common import device_capabilities as dc


class Dev:
    """Device stand-in exposing supports* flags as live attributes, like a
    real Indigo device object."""

    def __init__(self, model="Test Device", **supports):
        self.model = model
        for name, value in supports.items():
            setattr(self, name, value)


# ── live_capabilities ────────────────────────────────────────────────────────

def test_live_capabilities_reads_flags():
    dev = Dev(supportsOnState=True, supportsRGB=False, supportsWhite=False)
    caps = dc.live_capabilities(dev)
    assert caps == {"supportsOnState": True, "supportsRGB": False,
                    "supportsWhite": False}


def test_live_capabilities_ignores_non_bool_and_non_supports():
    dev = Dev(supportsOnState=True)
    dev.supportsWeird = "yes"   # non-bool → skipped
    dev.brightness = 50          # not a supports* attr → skipped
    assert dc.live_capabilities(dev) == {"supportsOnState": True}


# ── refusal discipline: explicit live False only ─────────────────────────────

def test_refusal_fires_on_explicit_false():
    dev = Dev(model="Dimmer Switch (FGD212)",
              supportsOnState=True, supportsStatusRequest=True,
              supportsRGB=False, supportsColor=False, supportsWhite=False)
    msg = dc.refusal(dev, "supportsRGB", "RGB colour")
    assert msg is not None
    assert "supportsRGB=false" in msg
    assert "Dimmer Switch (FGD212)" in msg
    assert "on/off" in msg and "status requests" in msg


def test_refusal_passes_capable_device():
    dev = Dev(supportsRGB=True, supportsWhite=True)
    assert dc.refusal(dev, "supportsRGB", "RGB colour") is None


def test_refusal_passes_when_flag_absent():
    # A relay has no supportsRGB attribute at all → getattr None → proceed.
    dev = Dev(supportsOnState=True)
    assert dc.refusal(dev, "supportsRGB", "RGB colour") is None


def test_refusal_setpoints():
    dev = Dev(supportsHeatSetpoint=True, supportsCoolSetpoint=False)
    assert dc.refusal(dev, "supportsCoolSetpoint", "a cool setpoint") is not None
    assert dc.refusal(dev, "supportsHeatSetpoint", "a heat setpoint") is None


# ── control-handler integration ──────────────────────────────────────────────

@pytest.fixture()
def handler(monkeypatch):
    import sys
    from mcp_server.tools.device_control.device_control_handler import DeviceControlHandler

    plain = Dev(model="Plain Dimmer", supportsOnState=True,
                supportsRGB=False, supportsWhite=False)
    colour = Dev(model="Colour Bulb", supportsRGB=True, supportsWhite=True)
    relay = Dev(model="Relay", supportsOnState=True)  # no supportsRGB

    class FakeDevices:
        _m = {1: plain, 2: colour, 3: relay}

        def __getitem__(self, key):
            return self._m[key]

    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", FakeDevices(), raising=False)
    mod = sys.modules["mcp_server.tools.device_control.device_control_handler"]
    monkeypatch.setattr(mod, "indigo", ind, raising=False)

    class FakeDP:
        def set_color(self, *a, **k):
            return {"device_name": "x", "changed": True}

    h = DeviceControlHandler(data_provider=FakeDP())
    monkeypatch.setattr(h, "_coerce_device_id", lambda x: x)
    return h


def test_set_color_refused_on_plain_dimmer(handler):
    result = handler.set_color(1, 255, 0, 0)
    assert result["success"] is False
    assert result["unsupported_capability"] == "supportsRGB"


def test_set_color_allowed_on_colour_bulb(handler):
    result = handler.set_color(2, 255, 0, 0)
    assert result.get("changed") is True
    assert "unsupported_capability" not in result


def test_set_color_passes_device_without_flag(handler):
    # Relay exposes no supportsRGB → not blocked (proceeds; Indigo would
    # reject the odd request itself).
    result = handler.set_color(3, 255, 0, 0)
    assert result.get("changed") is True
