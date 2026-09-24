#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    device_roles.py
# Description: What part a device plays in the house for the status views —
#              contact, motion, alarm, lock, thermostat — read from what Indigo
#              knows about it, not from words in its name.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

"""
Until 3.0.2 home_status sorted devices by words in their names and treated
"on" as "open". Live on 24-09-2026 that listed a LOCKED front door lock and two
garage-door relays as open doors, filed "Front Door Motion" as a door, and
dropped an UNLOCKED lock altogether.

Indigo already says what a device is:
  * a sensor's `subType` is one of indigo.kSensorDeviceSubType
    ("Door/Window", "Motion", "Presence", "Water Leak", "Smoke", ...);
  * a lock is a relay whose props carry IsLockSubType (or subType "Lock"),
    and its onState True means LOCKED;
  * a thermostat is an indigo.ThermostatDevice.
Names are the last resort, and only for SENSORS that declare no subType —
never for relays, dimmers or buttons, which is how the false doors got in.
"""

from typing import Any, Optional

CONTACT_SUBTYPES = {"Door/Window"}
MOTION_SUBTYPES  = {"Motion", "Presence"}
ALARM_SUBTYPES   = {"Water Leak", "Gas Leak", "Smoke", "Carbon Monoxide",
                    "Glass Break", "Tamper"}

_ALARM_WORDS   = ("leak", "smoke", "carbon", " co ", "flood")
_MOTION_WORDS  = ("motion", "pir", "presence", "occupancy")
_CONTACT_WORDS = ("door", "window", "contact", "reed")


def _class_name(dev: Any) -> str:
    return type(dev).__name__


def _props(dev: Any) -> dict:
    for attr in ("ownerProps", "pluginProps"):
        try:
            value = getattr(dev, attr)
            if value:
                return dict(value)
        except Exception:
            continue
    return {}


def is_lock(dev: Any) -> bool:
    if _class_name(dev) != "RelayDevice":
        return False
    return bool(_props(dev).get("IsLockSubType")) or getattr(dev, "subType", "") == "Lock"


def is_thermostat(dev: Any) -> bool:
    return _class_name(dev) == "ThermostatDevice"


def sensor_role(dev: Any) -> Optional[str]:
    """'contact', 'motion', 'alarm' or None for a sensor; None for anything
    that is not a SensorDevice."""
    if _class_name(dev) != "SensorDevice":
        return None
    sub = getattr(dev, "subType", "") or ""
    if sub in CONTACT_SUBTYPES:
        return "contact"
    if sub in MOTION_SUBTYPES:
        return "motion"
    if sub in ALARM_SUBTYPES:
        return "alarm"
    if sub:
        return None          # a declared subtype we do not report (temperature, lux...)
    # A button or remote reports "on" for a press, not for an open door; live,
    # "Hall Garage Door Opener" (a z2m button) read as an open contact.
    type_id = str(getattr(dev, "deviceTypeId", "")).lower()
    if any(w in type_id for w in ("button", "remote", "scene", "switch")):
        return None
    name = f" {str(getattr(dev, 'name', '')).lower()} "
    # Alarm and motion first: "Front Door Motion" is a motion sensor, not a door.
    if any(w in name for w in _ALARM_WORDS):
        return "alarm"
    if any(w in name for w in _MOTION_WORDS):
        return "motion"
    if any(w in name for w in _CONTACT_WORDS):
        return "contact"
    return None


def on_state(dev: Any) -> Optional[bool]:
    try:
        value = dev.onState
    except AttributeError:
        return None
    return None if value is None else bool(value)


def thermostat_is_heating(dev: Any) -> Optional[bool]:
    """True/False where the device can say, None where it cannot.

    A zone is heating when Indigo reports heatIsOn, or failing that when its
    heat setpoint is above the room temperature. A setpoint on its own proves
    nothing: an idle RAMSES zone sits at its 8 degree frost setpoint."""
    states = getattr(dev, "states", {}) or {}
    mode = str(states.get("hvacOperationMode", states.get("hvacMode", ""))).lower()
    if mode in ("off", "hvacoff", "0"):
        return False
    if "heatIsOn" in states:
        return bool(states.get("heatIsOn"))
    try:
        setpoint = float(states.get("setpointHeat", states.get("heatSetpoint")))
        temp = float(states.get("temperatureInput1", states.get("temperature")))
    except (TypeError, ValueError):
        return None
    return setpoint > temp
