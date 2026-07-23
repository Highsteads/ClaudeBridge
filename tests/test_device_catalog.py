#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_catalog.py
# Description: Tests for the device-catalogue capability awareness added in
#              ClaudeBridge v2.14.0 — profile lookup, advisory refusals (fire
#              only on an explicit catalogue False, never on missing data),
#              and device-detail enrichment.
# Author:      CliveS & Claude Opus 4.8
# Date:        23-07-2026
# Version:     1.0

import pytest

from mcp_server.common import device_catalog


class Dev:
    """Minimal device stand-in carrying the two ids the catalogue keys on."""

    def __init__(self, plugin_id, type_id):
        self.pluginId = plugin_id
        self.deviceTypeId = type_id


# A synthetic dense profile set, injected so the tests never depend on the
# vendored snapshot's exact contents (which change as the estate does).
_FAKE_PROFILES = {
    ("com.test.dimmer", "colourBulb"): {
        "base_class": "indigo.DimmerDevice",
        "capabilities": {"supportsOnState": True, "supportsRGB": True,
                         "supportsWhite": True, "supportsWhiteTemperature": True},
        "model": "Colour Bulb",
    },
    ("com.test.dimmer", "plainDimmer"): {
        "base_class": "indigo.DimmerDevice",
        "capabilities": {"supportsOnState": True, "supportsStatusRequest": True,
                         "supportsRGB": False, "supportsColor": False,
                         "supportsWhite": False, "supportsWhiteTemperature": False},
        "model": "Plain Dimmer",
    },
    ("com.test.thermo", "heatOnly"): {
        "base_class": "indigo.ThermostatDevice",
        "capabilities": {"supportsHeatSetpoint": True, "supportsCoolSetpoint": False},
        "model": "Heat-only Stat",
    },
    ("com.test.sparse", "noFlags"): {
        "base_class": "indigo.Device",
        "capabilities": {"supportsOnState": True},  # no RGB flag at all
        "model": "Sparse Device",
    },
}


@pytest.fixture(autouse=True)
def _inject_profiles(monkeypatch):
    monkeypatch.setattr(device_catalog, "_PROFILES", dict(_FAKE_PROFILES))


# ── profile_for / capabilities ───────────────────────────────────────────────

def test_profile_for_hit_and_miss():
    assert device_catalog.profile_for(Dev("com.test.dimmer", "colourBulb"))["model"] == "Colour Bulb"
    assert device_catalog.profile_for(Dev("com.test.nope", "x")) is None
    # Built-in / interface device (empty pluginId) misses cleanly.
    assert device_catalog.profile_for(Dev("", "zwDimmerType")) is None


def test_profile_for_accepts_dict():
    d = {"pluginId": "com.test.dimmer", "deviceTypeId": "colourBulb"}
    assert device_catalog.profile_for(d)["model"] == "Colour Bulb"


def test_capabilities_map():
    caps = device_catalog.capabilities(Dev("com.test.dimmer", "plainDimmer"))
    assert caps["supportsRGB"] is False and caps["supportsOnState"] is True
    assert device_catalog.capabilities(Dev("com.test.nope", "x")) == {}


# ── refusal discipline: explicit False only ──────────────────────────────────

def test_refusal_fires_on_explicit_false():
    msg = device_catalog.refusal(Dev("com.test.dimmer", "plainDimmer"),
                                 "supportsRGB", "RGB colour")
    assert msg is not None
    assert "not supported" in msg
    assert "supportsRGB=false" in msg
    # Names what it DOES support.
    assert "on/off" in msg


def test_refusal_passes_capable_device():
    assert device_catalog.refusal(Dev("com.test.dimmer", "colourBulb"),
                                  "supportsRGB", "RGB colour") is None


def test_refusal_passes_uncataloged():
    assert device_catalog.refusal(Dev("com.test.nope", "x"),
                                  "supportsRGB", "RGB colour") is None


def test_refusal_passes_when_flag_absent():
    # A profile that simply doesn't mention supportsRGB must NOT refuse —
    # absent is ambiguous, only an explicit False blocks.
    assert device_catalog.refusal(Dev("com.test.sparse", "noFlags"),
                                  "supportsRGB", "RGB colour") is None


def test_refusal_passes_builtin_empty_plugin():
    assert device_catalog.refusal(Dev("", "zwDimmerType"),
                                  "supportsRGB", "RGB colour") is None


def test_setpoint_refusal():
    assert device_catalog.refusal(Dev("com.test.thermo", "heatOnly"),
                                  "supportsCoolSetpoint", "a cool setpoint") is not None
    assert device_catalog.refusal(Dev("com.test.thermo", "heatOnly"),
                                  "supportsHeatSetpoint", "a heat setpoint") is None


# ── control-handler integration ──────────────────────────────────────────────

@pytest.fixture()
def handler(monkeypatch):
    import sys
    from mcp_server.tools.device_control.device_control_handler import DeviceControlHandler

    # Fake indigo.devices so _capability_refusal can resolve a device to its ids.
    class FakeDevices:
        def __init__(self, mapping):
            self._m = mapping

        def __getitem__(self, key):
            return self._m[key]

    devices = FakeDevices({
        1: Dev("com.test.dimmer", "plainDimmer"),
        2: Dev("com.test.dimmer", "colourBulb"),
        3: Dev("com.test.nope", "x"),
    })
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", devices, raising=False)

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


def test_set_color_passes_uncataloged(handler):
    result = handler.set_color(3, 255, 0, 0)
    assert result.get("changed") is True


# ── list_uncataloged_devices ─────────────────────────────────────────────────

def test_list_uncataloged_devices(monkeypatch):
    import sys
    from mcp_server.tools.audit import audit_handler as ah

    class D:
        def __init__(self, did, name, pid, tid):
            self.id, self.name, self.pluginId, self.deviceTypeId = did, name, pid, tid

    devs = {
        1: D(1, "Cat Bulb", "com.test.dimmer", "colourBulb"),   # cataloged → excluded
        2: D(2, "Gap A #1", "com.test.gap", "gadget"),          # uncataloged type X
        3: D(3, "Gap A #2", "com.test.gap", "gadget"),          # same type → collapse
        4: D(4, "Gap B", "com.test.gap", "widget"),             # uncataloged type Y
        5: D(5, "Builtin", "", "zwDimmerType"),                 # no pluginId → excluded
    }

    class FakeDevices:
        def __iter__(self):
            return iter(devs.keys())

        def __getitem__(self, k):
            return devs[k]

    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", FakeDevices(), raising=False)
    monkeypatch.setattr(ah, "indigo", ind, raising=False)

    h = ah.AuditHandler(data_provider=None)
    out = h.list_uncataloged_devices()
    assert out["success"] is True
    assert out["total_uncataloged_types"] == 2  # gadget + widget, builtin/cataloged excluded
    by_type = {e["device_type_id"]: e for e in out["uncataloged"]}
    assert by_type["gadget"]["device_count"] == 2  # collapsed
    assert by_type["gadget"]["example_device"]["id"] == 2
    assert "widget" in by_type
    assert "colourBulb" not in by_type
