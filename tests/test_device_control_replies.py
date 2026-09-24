#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_control_replies.py
# Description: Device-control replies report what the device says afterwards,
#              refuse what cannot work, and never call an unconfirmed change a
#              success or a slow one a failure. From the 3.0.1 review.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import threading
import time
from types import SimpleNamespace

import pytest

from conftest import call_tool

LOG = logging.getLogger("test-device-replies")


class _Dev:
    def __init__(self, **attrs):
        self.id, self.name = 3, "Thing"
        for k, v in attrs.items():
            setattr(self, k, v)


class _Recorder:
    """An indigo namespace (device, dimmer, speedcontrol...) that records calls
    and runs an optional effect on the device."""

    def __init__(self, effects=None):
        self.calls, self.effects = [], effects or {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            effect = self.effects.get(name)
            return effect(*args, **kwargs) if effect else None
        return _call


@pytest.fixture()
def indigo_ns(monkeypatch):
    import indigo

    class DimmerDevice(_Dev):
        pass

    class RelayDevice(_Dev):
        pass

    class SpeedControlDevice(_Dev):
        pass

    class SprinklerDevice(_Dev):
        pass

    for cls in (DimmerDevice, RelayDevice, SpeedControlDevice, SprinklerDevice):
        monkeypatch.setattr(indigo, cls.__name__, cls, raising=False)

    def _install(dev, **namespaces):
        monkeypatch.setattr(indigo, "devices", {dev.id: dev})
        for name, ns in namespaces.items():
            monkeypatch.setattr(indigo, name, ns, raising=False)
        return indigo
    _install.classes = SimpleNamespace(dimmer=DimmerDevice, relay=RelayDevice,
                                       speed=SpeedControlDevice, sprinkler=SprinklerDevice)
    return _install


def _provider():
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
    p = IndigoDataProvider(logger=LOG)
    p.CONFIRM_TIMEOUT_S = 0.05
    return p


def _ext(provider=None):
    from mcp_server.tools.extended_tools.extended_tools_handler import ExtendedToolsHandler
    return ExtendedToolsHandler(provider or _provider(), logger=LOG)


# ── get_device_by_name (item 5) ──────────────────────────────────────────────

def test_an_ambiguous_name_is_a_failure_not_a_device():
    provider = SimpleNamespace(get_device_by_name=lambda n: {
        "error": "Ambiguous device name 'hall': 2 devices match.",
        "candidates": [{"id": 1, "name": "Hall A"}, {"id": 2, "name": "Hall B"}]})
    ctx = SimpleNamespace(logger=LOG, data_provider=provider, plugin=None)
    out = call_tool(ctx, "get_device_by_name", name="hall")
    assert out["success"] is False and "Ambiguous" in out["error"]
    assert len(out["candidates"]) == 2 and "device" not in out


# ── locks (items 6 and 7) ────────────────────────────────────────────────────

def test_unlock_sends_no_code_and_confirms_from_the_device(indigo_ns):
    dev = _Dev(onState=True)
    device = _Recorder({"unlock": lambda *a, **k: setattr(dev, "onState", False)})
    indigo_ns(dev, device=device)
    out = _provider().unlock_device(3)
    assert device.calls == [("unlock", (3,), {})]
    assert out["confirmed"] is True and out["current"] is False


def test_a_lock_that_has_not_reported_is_not_confirmed(indigo_ns):
    dev = _Dev(onState=False)
    indigo_ns(dev, device=_Recorder())
    out = _provider().lock_device(3)
    assert out["success"] is True and out["confirmed"] is False
    assert "not yet confirmed" in out["note"]


def test_a_fan_speed_reply_reads_back_the_level(indigo_ns):
    dev = _Dev(speedLevel=10)
    speed = _Recorder({"setSpeedLevel": lambda d, value: setattr(dev, "speedLevel", value)})
    indigo_ns(dev, speedcontrol=speed)
    out = _provider().set_fan_speed(3, 60)
    assert out["confirmed"] is True and out["current"] == 60 and out["previous"] == 10


# ── energy reset (item 8) ────────────────────────────────────────────────────

def test_a_slow_energy_reset_is_unconfirmed_not_failed(indigo_ns):
    dev = _Dev(energyAccumTotal=12.5)
    indigo_ns(dev, device=_Recorder())
    ext = _ext()
    ext.RESET_WAIT_S = 0.05
    out = ext.reset_energy_accumulator(3)
    assert out["success"] is True and out["status"] == "unconfirmed"
    assert "did NOT" not in out["message"] and "not yet confirmed" in out["message"]


def test_an_energy_reset_that_lands_is_confirmed(indigo_ns):
    dev = _Dev(energyAccumTotal=12.5)
    indigo_ns(dev, device=_Recorder(
        {"resetEnergyAccumTotal": lambda d: setattr(dev, "energyAccumTotal", 0.0)}))
    out = _ext().reset_energy_accumulator(3)
    assert out["confirmed"] is True and out["current_kwh"] == 0.0


# ── ping (item 9) ────────────────────────────────────────────────────────────

def test_a_slow_ping_answers_pending_and_logs_the_late_result(indigo_ns, caplog):
    release = threading.Event()

    def _ping(did, suppressLogging=True):
        release.wait(2)
        return {"Success": True, "TimeDelta": 40}

    indigo_ns(_Dev(), device=_Recorder({"ping": _ping}))
    ext = _ext()
    ext.PING_WAIT_S = 0.05
    started = time.monotonic()
    out = ext.ping_device(3)
    assert time.monotonic() - started < 1.0, "the dispatch thread must not wait for the radio"
    assert out["success"] is True and out["status"] == "pending"
    with caplog.at_level(logging.INFO, logger=LOG.name):
        release.set()
        deadline = time.monotonic() + 2
        while "answered after" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.01)
    assert "reachable" in caplog.text and "answered after" in caplog.text


def test_a_quick_ping_answers_in_full(indigo_ns):
    indigo_ns(_Dev(), device=_Recorder({"ping": lambda d, **k: {"Success": False}}))
    out = _ext().ping_device(3)
    assert out["status"] == "answered" and out["reachable"] is False


# ── dimmer, speed index, sprinkler zone, toggle ──────────────────────────────

def test_brighten_refuses_a_negative_amount(indigo_ns):
    dev = indigo_ns.classes.dimmer(brightness=50)
    dimmer = _Recorder()
    indigo_ns(dev, dimmer=dimmer)
    out = _ext().dimmer_brighten_by(3, -10)
    assert out["success"] is False and "positive" in out["error"]
    assert dimmer.calls == []


def test_dim_reports_the_new_level(indigo_ns):
    dev = indigo_ns.classes.dimmer(brightness=50)
    dimmer = _Recorder({"dim": lambda d, by: setattr(dev, "brightness", 50 - by)})
    indigo_ns(dev, dimmer=dimmer)
    out = _ext().dimmer_dim_by(3, 20)
    assert out["previous"] == 50 and out["current"] == 30 and out["changed"] is True


def test_toggle_reports_the_state_it_ended_in(indigo_ns):
    dev = indigo_ns.classes.relay(onState=False)
    relay = _Recorder({"toggle": lambda d: setattr(dev, "onState", True)})
    indigo_ns(dev, relay=relay, dimmer=_Recorder(), speedcontrol=_Recorder())
    out = _ext().device_toggle(3)
    assert out["current"] is True and "now on" in out["message"]


def test_speed_index_is_checked_against_the_devices_own_count(indigo_ns):
    dev = indigo_ns.classes.speed(speedIndex=0, speedIndexCount=3)
    speed = _Recorder({"setSpeedIndex": lambda d, value: setattr(dev, "speedIndex", value)})
    indigo_ns(dev, speedcontrol=speed)
    assert "0-2" in _ext().speedcontrol_set_index(3, 3)["error"]
    assert speed.calls == []
    out = _ext().speedcontrol_set_index(3, 2)
    assert out["confirmed"] is True and out["current"] == 2


def test_sprinkler_zone_is_checked_against_the_zone_count(indigo_ns):
    dev = indigo_ns.classes.sprinkler(zoneCount=4)
    sprinkler = _Recorder()
    indigo_ns(dev, sprinkler=sprinkler)
    assert "1-4" in _ext().sprinkler_set_zone(3, 5)["error"]
    assert "1-4" in _ext().sprinkler_set_zone(3, 0)["error"]
    assert sprinkler.calls == []
    assert _ext().sprinkler_set_zone(3, 4)["success"] is True


# ── search_entities device_types, state filter (items 10 and 12) ────────────

def test_a_bare_string_device_type_is_one_type_not_letters():
    seen = {}

    def _search(query, device_types, entity_types, state_filter, detail="slim"):
        seen["types"] = device_types
        return {"success": True}

    ctx = SimpleNamespace(logger=LOG, plugin=None,
                          search_handler=SimpleNamespace(search=_search))
    out = call_tool(ctx, "search_entities", query="hall", device_types="light")
    assert out["success"] is True and seen["types"] == ["dimmer"]


def test_a_numeric_contains_does_not_raise():
    from mcp_server.common.state_filter import StateFilter
    devices = [{"name": "a", "states": {"zone": 15}}, {"name": "b", "states": {"zone": 7}}]
    out = StateFilter.filter_by_state(devices, {"zone": {"contains": 5}})
    assert [d["name"] for d in out] == ["a"]
