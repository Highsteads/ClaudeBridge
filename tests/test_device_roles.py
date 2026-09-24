#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_roles.py
# Description: The security and heating views judge a device by what Indigo
#              says it is, not by words in its name. Shapes copied from the live
#              devices that were misreported on 24-09-2026.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

from mcp_server.common import device_roles
from mcp_server.tools.home_status import home_status_handler as hs


class SensorDevice:
    def __init__(self, name, on, subType="", enabled=True, i=1):
        self.id, self.name, self.onState, self.subType, self.enabled = i, name, on, subType, enabled
        self.ownerProps = {}


class RelayDevice(SensorDevice):
    def __init__(self, name, on, props=None, subType="", i=2):
        super().__init__(name, on, subType, i=i)
        self.ownerProps = props or {}


class ThermostatDevice:
    def __init__(self, name, states, i=3):
        self.id, self.name, self.states, self.enabled = i, name, states, True
        self.onState = None


def test_a_locked_lock_is_not_an_open_door():
    lock = RelayDevice("Front Door Lock", True, {"IsLockSubType": True})
    snap = hs._security_snapshot([lock])
    assert snap["open_contacts"] == [] and snap["unlocked_locks"] == []


def test_an_unlocked_lock_is_reported():
    lock = RelayDevice("Front Door Lock", False, {"IsLockSubType": True})
    assert hs._security_snapshot([lock])["unlocked_locks"] == [{"id": 2, "name": "Front Door Lock"}]


def test_relays_and_buttons_named_door_are_not_contacts():
    relay = RelayDevice("Hall Garage Door Opener", True)
    button = SensorDevice("Virtual Garage Door Opener", True, subType="Binary")
    snap = hs._security_snapshot([relay, button])
    assert snap["open_contacts"] == []


def test_subtype_decides_before_the_name():
    motion = SensorDevice("Front Door Motion", True, subType="Motion")
    contact = SensorDevice("Bathroom Door Contact Sensor", True, subType="Door/Window")
    snap = hs._security_snapshot([motion, contact])
    assert [e["name"] for e in snap["active_motion"]] == ["Front Door Motion"]
    assert [e["name"] for e in snap["open_contacts"]] == ["Bathroom Door Contact Sensor"]


def test_name_fallback_puts_motion_before_door_and_catches_leaks():
    assert device_roles.sensor_role(SensorDevice("Living Room Door Motion Sensor", True)) == "motion"
    assert device_roles.sensor_role(SensorDevice("Bathroom Boiler Leak Sensor", True)) == "alarm"
    assert device_roles.sensor_role(SensorDevice("Office Temperature", True, subType="Temperature")) is None


def test_idle_frost_setpoint_is_not_heating():
    idle = ThermostatDevice("Hall", {"setpointHeat": 8.0, "temperatureInput1": 19.5})
    warm = ThermostatDevice("Lounge", {"setpointHeat": 21.0, "temperatureInput1": 18.0})
    told = ThermostatDevice("Bed 1", {"heatIsOn": True, "setpointHeat": 8, "temperatureInput1": 20})
    off = ThermostatDevice("Bath", {"hvacOperationMode": "off", "heatIsOn": True})
    assert [device_roles.thermostat_is_heating(t) for t in (idle, warm, told, off)] == \
        [False, True, True, False]


def test_thermostats_selected_by_class_not_plugin():
    zwave = ThermostatDevice("En Suite Floor Heating Thermostat", {})
    zwave.pluginId = "com.perceptiveautomation.indigoplugin.zwave"
    lamp = SensorDevice("Thermostat Lamp", True)
    assert hs._thermostats([zwave, lamp]) == [zwave]


def test_a_button_named_door_is_not_a_contact():
    button = SensorDevice("Hall Garage Door Opener", True)
    button.deviceTypeId = "z2mButton"
    assert device_roles.sensor_role(button) is None
