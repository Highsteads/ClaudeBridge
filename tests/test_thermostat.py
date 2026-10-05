#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_thermostat.py
# Description: set_hvac_mode refuses a non-string mode cleanly.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2202_low_fixes.py (09-Aug-2026 review)


# ── Arguments are coerced before they are compared ───────────────────────────

def test_hvac_mode_rejects_a_non_string_cleanly():
    """mode.lower() ran outside the try, so a number raised AttributeError."""
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider

    provider = object.__new__(IndigoDataProvider)
    result = provider.set_hvac_mode(1, 42)
    assert result["success"] is False
    assert "Unknown HVAC mode" in result["error"]

    result = provider.set_hvac_mode(1, None)
    assert result["success"] is False


# ── Setpoints: unit-aware band, refuse never clamp, confirm by read-back ─────
# (3.0.1 review) The band assumed Celsius, so a Fahrenheit 70 was refused and
# a delta from 68 was silently CLAMPED to 35. Replies set confirmed=True
# whenever the attribute existed, even when the device still read the old value.


import pytest  # noqa: E402


class _Thermostat:
    def __init__(self, heat, cool=None, temps=(), name="Hall Stat"):
        self.id, self.name = 11, name
        self.heatSetpoint, self.coolSetpoint = heat, cool
        self.temperatures = list(temps)


class _ThermostatNS:
    """indigo.thermostat: records every call; applies it to the device unless
    the device is 'slow' (then nothing changes, like a TRV not yet reporting)."""

    def __init__(self, dev, slow=False):
        self.dev, self.slow, self.calls = dev, slow, []

    def _apply(self, attr, value):
        if not self.slow:
            setattr(self.dev, attr, value)

    def setHeatSetpoint(self, dev_id, value):
        self.calls.append(("setHeatSetpoint", value))
        self._apply("heatSetpoint", value)

    def setCoolSetpoint(self, dev_id, value):
        self.calls.append(("setCoolSetpoint", value))
        self._apply("coolSetpoint", value)

    def increaseHeatSetpoint(self, dev_id, delta):
        self.calls.append(("increaseHeatSetpoint", delta))
        self._apply("heatSetpoint", round(self.dev.heatSetpoint + delta, 1))

    def decreaseHeatSetpoint(self, dev_id, delta):
        self.calls.append(("decreaseHeatSetpoint", delta))
        self._apply("heatSetpoint", round(self.dev.heatSetpoint - delta, 1))

    def increaseCoolSetpoint(self, dev_id, delta):
        self.calls.append(("increaseCoolSetpoint", delta))
        self._apply("coolSetpoint", round(self.dev.coolSetpoint + delta, 1))

    def decreaseCoolSetpoint(self, dev_id, delta):
        self.calls.append(("decreaseCoolSetpoint", delta))
        self._apply("coolSetpoint", round(self.dev.coolSetpoint - delta, 1))


@pytest.fixture()
def rig(monkeypatch):
    import indigo
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider

    def _make(dev, slow=False):
        ns = _ThermostatNS(dev, slow=slow)
        monkeypatch.setattr(indigo, "devices", {dev.id: dev})
        monkeypatch.setattr(indigo, "thermostat", ns)
        provider = IndigoDataProvider()
        provider.CONFIRM_TIMEOUT_S = 0.05
        return provider, ns
    return _make


def test_a_fahrenheit_thermostat_accepts_a_fahrenheit_setpoint(rig):
    provider, ns = rig(_Thermostat(heat=68.0, temps=[70.5]))
    out = provider.set_heat_setpoint(11, 70)
    assert out["success"] is True and out["unit"] == "F"
    assert ns.calls == [("setHeatSetpoint", 70.0)]
    assert out["confirmed"] is True and out["current"] == 70.0


def test_a_celsius_setpoint_outside_the_band_is_refused(rig):
    provider, ns = rig(_Thermostat(heat=20.0, temps=[19.5]))
    out = provider.set_heat_setpoint(11, 70)
    assert out["success"] is False and "5-35 degrees C" in out["error"]
    assert ns.calls == []


def test_a_delta_that_leaves_the_band_is_refused_not_clamped(rig):
    """The reported case: 68F + 1 used to come out as 35."""
    provider, ns = rig(_Thermostat(heat=34.5, temps=[21.0]))
    out = provider.increase_heat_setpoint(11, 1)
    assert out["success"] is False and "35.5" in out["error"]
    assert "nothing was changed" in out["error"]
    assert ns.calls == []


def test_a_fahrenheit_delta_uses_indigos_own_increase_command(rig):
    provider, ns = rig(_Thermostat(heat=68.0, temps=[69.0]))
    out = provider.increase_heat_setpoint(11, 1)
    assert ns.calls == [("increaseHeatSetpoint", 1.0)]
    assert out["success"] is True and out["current"] == 69.0 and out["confirmed"] is True


def test_a_negative_cool_delta_uses_decrease(rig):
    provider, ns = rig(_Thermostat(heat=20.0, cool=24.0, temps=[22.0]))
    out = provider.decrease_cool_setpoint(11, 0.5)
    assert ns.calls == [("decreaseCoolSetpoint", 0.5)]
    assert out["current"] == 23.5 and out["confirmed"] is True


def test_a_device_that_has_not_caught_up_is_not_confirmed(rig):
    provider, ns = rig(_Thermostat(heat=18.0, temps=[18.0]), slow=True)
    out = provider.set_heat_setpoint(11, 21)
    assert out["success"] is True
    assert out["confirmed"] is False and out["current"] == 18.0 and out["requested"] == 21.0
    assert "not yet confirmed" in out["note"]


def test_no_readings_means_the_widest_band(rig):
    provider, ns = rig(_Thermostat(heat=None, temps=[]))
    assert provider.set_heat_setpoint(11, 70)["success"] is True
    assert provider.set_heat_setpoint(11, 120)["success"] is False


# ── The mode map only names kHvacMode members that exist (3.8.1) ──────────────
# 3.0 to 3.8.0 built the map from indigo.kHvacMode.ProgramAuto, which Indigo does
# not have, so EVERY set_hvac_mode call raised AttributeError. The shared stub
# makes kHvacMode a MagicMock that invents any attribute, which is why nothing
# noticed. This one has only the members the live Indigo 2025.2 reports.

import pytest


class _LiveHvacModes:
    Off = 0
    Heat = 1
    Cool = 2
    HeatCool = 3
    ProgramHeat = 4
    ProgramCool = 5
    ProgramHeatCool = 6


class _FakeThermostat:
    def __init__(self):
        self.calls = []

    def setHvacMode(self, device_id, value=None):
        self.calls.append((device_id, value))


@pytest.fixture
def hvac(monkeypatch):
    from mcp_server.adapters import indigo_data_provider as idp

    thermostat = _FakeThermostat()
    monkeypatch.setattr(idp.indigo, "kHvacMode", _LiveHvacModes, raising=False)
    monkeypatch.setattr(idp.indigo, "thermostat", thermostat, raising=False)
    monkeypatch.setattr(idp.indigo, "devices", {7: type("D", (), {"name": "Lounge"})()},
                        raising=False)
    provider = object.__new__(idp.IndigoDataProvider)
    provider.logger = type("L", (), {"info": lambda *a, **k: None,
                                     "error": lambda *a, **k: None})()
    return provider, thermostat


@pytest.mark.parametrize("mode, expected", [
    ("off", 0), ("heat", 1), ("cool", 2), ("auto", 3), ("heatcool", 3),
    ("programHeat", 4), ("programCool", 5),
    ("programHeatCool", 6), ("programAuto", 6), ("program heat cool", 6),
])
def test_every_advertised_hvac_mode_reaches_indigo(hvac, mode, expected):
    provider, thermostat = hvac
    result = provider.set_hvac_mode(7, mode)
    assert result["success"] is True, result
    assert thermostat.calls == [(7, expected)]


def test_the_tool_schema_modes_are_all_accepted(hvac):
    from mcp_server.toolsets.devices import _HVAC_MODES

    provider, thermostat = hvac
    for mode in _HVAC_MODES:
        assert provider.set_hvac_mode(7, mode)["success"] is True, mode
    assert len(thermostat.calls) == len(_HVAC_MODES)
