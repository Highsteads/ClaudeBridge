#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_props.py
# Description: Regression tests for reliable foreign-device property reads.
# Author:      CliveS & Claude Opus 4.8
# Date:        21-07-2026
# Version:     1.0
#
# THE BUG (live-measured 21-07-2026): read from inside Claude Bridge's own
# plugin host, `dev.pluginProps` came back EMPTY for 18 of 19 ShellyDirect
# devices, while `dev.globalProps[dev.pluginId]` was correct for all 19. The
# empty read looked exactly like "this device has no such property", so a
# duplicate-IP audit reported no duplicates over a live clash, and a plugin
# review nearly got a severity call wrong.
#
# Second half of the same bug: all 19 of those devices also had an EMPTY native
# `dev.address` and kept the IP in the `ip_address` plugin prop, so
# find_conflicts' shared-address check was blind to every one of them.

import pytest

from conftest import SERVER_PLUGIN  # noqa: F401  (path wiring)

from mcp_server.common.device_props import (  # noqa: E402
    device_address,
    device_dict,
    device_props,
    device_props_with_source,
)


class FakeDict(dict):
    """Stand-in for indigo.Dict — a mapping that dict() can copy."""


class FakeDevice:
    """Minimal device double with the three competing property views."""

    def __init__(self, plugin_id="com.example.plugin", plugin_props=None,
                 global_props=None, owner_props=None, address="",
                 dev_id=1, name="Fake"):
        self.id = dev_id
        self.name = name
        self.pluginId = plugin_id
        self.address = address
        self.pluginProps = FakeDict(plugin_props or {})
        self.ownerProps = FakeDict(owner_props or {})
        self.globalProps = FakeDict(global_props or {})

    def keys(self):
        return ["id", "name", "pluginId", "address", "pluginProps"]

    def __getitem__(self, key):
        return getattr(self, key)


# --------------------------------------------------------------------------
# The headline bug: empty pluginProps, correct globalProps
# --------------------------------------------------------------------------

def _shelly_like():
    """The exact live shape: pluginProps empty, globalProps populated."""
    return FakeDevice(
        plugin_id="com.clives.indigoplugin.shellydirect",
        plugin_props={},
        global_props={"com.clives.indigoplugin.shellydirect":
                      {"ip_address": "192.168.1.50", "channel": "0"}},
        owner_props={"ip_address": "192.168.1.99"},   # stale on purpose
        address="",
        name="Conservatory Lamp Plug",
    )


def test_empty_plugin_props_falls_through_to_global_props():
    dev = _shelly_like()
    assert dev.pluginProps == {}, "fixture must reproduce the empty read"
    assert device_props(dev) == {"ip_address": "192.168.1.50", "channel": "0"}


def test_global_props_wins_over_stale_owner_props():
    dev = _shelly_like()
    # ownerProps also has data, but it lags saved versions — must not win.
    assert device_props(dev).get("ip_address") == "192.168.1.50"


def test_source_is_reported_so_empty_is_never_silent():
    props, source = device_props_with_source(_shelly_like())
    assert source == "globalProps"

    bare = FakeDevice(plugin_props={}, global_props={}, owner_props={})
    props, source = device_props_with_source(bare)
    assert props == {}
    assert source == "empty", "a genuinely empty read must say so explicitly"


def test_populated_plugin_props_are_used_when_present():
    dev = FakeDevice(plugin_props={"k": "from_plugin_props"},
                     global_props={"com.example.plugin": {"k": "from_global"}})
    props, source = device_props_with_source(dev)
    assert source == "globalProps"
    assert props["k"] == "from_global"


def test_owner_props_are_the_last_resort_not_the_first():
    dev = FakeDevice(plugin_props={}, global_props={},
                     owner_props={"k": "from_owner"})
    props, source = device_props_with_source(dev)
    assert source == "ownerProps"
    assert props["k"] == "from_owner"


# --------------------------------------------------------------------------
# Robustness — a bad device must never raise into a tool response
# --------------------------------------------------------------------------

@pytest.mark.parametrize("dev", [None, object()])
def test_never_raises_on_junk_input(dev):
    assert device_props(dev) == {}
    assert device_address(dev) == ""


def test_global_props_lookup_that_raises_falls_back():
    class Exploding(FakeDevice):
        @property
        def globalProps(self):
            raise RuntimeError("boom")

        @globalProps.setter
        def globalProps(self, _v):
            pass

    dev = Exploding(plugin_props={"k": "v"})
    assert device_props(dev) == {"k": "v"}


# --------------------------------------------------------------------------
# The address half of the bug
# --------------------------------------------------------------------------

def test_address_falls_back_to_plugin_props_when_native_is_empty():
    dev = _shelly_like()
    assert (dev.address or "") == "", "fixture must have an empty native address"
    assert device_address(dev) == "192.168.1.50"


def test_native_address_wins_when_set():
    dev = FakeDevice(address="  10.0.0.1  ",
                     global_props={"com.example.plugin": {"ip_address": "10.0.0.2"}})
    assert device_address(dev) == "10.0.0.1"


@pytest.mark.parametrize("key", ["address", "ip_address", "ipAddress", "ip",
                                 "host", "hostname", "hostName", "deviceAddress"])
def test_common_address_prop_keys_are_all_recognised(key):
    dev = FakeDevice(global_props={"com.example.plugin": {key: "192.168.1.77"}})
    assert device_address(dev) == "192.168.1.77"


def test_address_is_blank_when_nothing_carries_one():
    assert device_address(FakeDevice()) == ""


def test_duplicate_addresses_are_detectable_via_plugin_props():
    """The audit's actual failure: two devices clashing on a props-held IP."""
    a = _shelly_like()
    b = _shelly_like()
    b.id, b.name = 2, "Colour Lamp Plug"
    seen = {}
    for dev in (a, b):
        seen.setdefault(device_address(dev), []).append(dev.name)
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert clashes == {"192.168.1.50": ["Conservatory Lamp Plug", "Colour Lamp Plug"]}

    # ...and the old native-attribute-only check finds nothing at all.
    native = {}
    for dev in (a, b):
        addr = (getattr(dev, "address", "") or "").strip()
        if addr:
            native.setdefault(addr, []).append(dev.name)
    assert native == {}, "documents the blindness this fix removes"


# --------------------------------------------------------------------------
# device_dict — the serialisation every tool inherits
# --------------------------------------------------------------------------

def test_device_dict_repairs_plugin_props_and_records_the_source():
    data = device_dict(_shelly_like())
    assert data["pluginProps"] == {"ip_address": "192.168.1.50", "channel": "0"}
    assert data["pluginPropsSource"] == "globalProps"
    assert data["resolvedAddress"] == "192.168.1.50"


def test_device_dict_marks_a_genuinely_empty_device():
    data = device_dict(FakeDevice(plugin_props={}, global_props={}, owner_props={}))
    assert data["pluginProps"] == {}
    assert data["pluginPropsSource"] == "empty"


def test_device_dict_returns_empty_dict_rather_than_raising():
    assert device_dict(object()) == {}


# The two wiring guards below used to grep the modules' source for
# "device_dict" and "device_address(dev)". They now run the code over devices
# with the live ShellyDirect shape (24-09-2026).

class _Devices:
    """indigo.devices as the provider and the audit use it: iterating yields
    devices, indexing takes an id or a device, `in` takes an id."""

    def __init__(self, devices):
        self._by_id = {d.id: d for d in devices}

    def __iter__(self):
        return iter(list(self._by_id.values()))

    def __contains__(self, key):
        return key in self._by_id

    def __getitem__(self, key):
        return self._by_id[getattr(key, "id", key)]


def _two_shellies():
    a, b = _shelly_like(), _shelly_like()
    b.id, b.name = 2, "Colour Lamp Plug"
    for dev in (a, b):
        dev.enabled = True
    return a, b


def test_data_provider_serialises_through_device_dict(monkeypatch):
    """Every way the provider hands out a device must carry the repaired props."""
    import logging

    from mcp_server.adapters import indigo_data_provider as idp

    a, _b = _two_shellies()
    monkeypatch.setattr(idp.indigo, "devices", _Devices([a]), raising=False)
    provider = idp.IndigoDataProvider(logger=logging.getLogger("t"))
    served = {
        "get_device": provider.get_device(1),
        "get_all_devices_unfiltered": provider.get_all_devices_unfiltered()[0],
        "get_device_by_name (exact)": provider.get_device_by_name("Conservatory Lamp Plug"),
        "get_device_by_name (any case)": provider.get_device_by_name("conservatory lamp plug"),
        "get_device_by_name (partial)": provider.get_device_by_name("Conservatory"),
    }
    for how, data in served.items():
        assert data["pluginPropsSource"] == "globalProps", how
        assert data["pluginProps"]["ip_address"] == "192.168.1.50", how


def test_audit_uses_the_resolved_address(monkeypatch):
    """find_conflicts sees two devices clashing on a props-held IP."""
    import logging
    from types import SimpleNamespace

    from mcp_server.tools.audit import audit_handler as ah

    a, b = _two_shellies()
    fake = SimpleNamespace(devices=_Devices([a, b]), variables={}, triggers={})
    monkeypatch.setattr(ah, "indigo", fake)
    monkeypatch.setattr(ah, "_scripts_dirs", lambda: [])
    monkeypatch.setattr(ah, "_iter_script_files", lambda dirs: iter(()))
    result = ah.AuditHandler(data_provider=None, logger=logging.getLogger("t")).find_conflicts()
    assert result["success"] is True
    assert result["summary"]["shared_device_addresses"] == 1
    clash = result["device_conflicts"]["shared_addresses"][0]
    assert clash["address"] == "192.168.1.50"
    assert {d["addressSource"] for d in clash["devices"]} == {"pluginProps"}
