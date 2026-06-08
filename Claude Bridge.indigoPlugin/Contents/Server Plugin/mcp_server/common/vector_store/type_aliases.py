#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    type_aliases.py
# Description: Keyword->device-type bridge for the search store. Folds a curated
#              set of synonyms per deviceTypeId into an entity's searchable text
#              so a query like "light" finds a z2mLight named "Lounge Lamp", or
#              "plug" finds a shellyRelay, even when the word isn't in the name.
#              Curated against this estate's real deviceTypeId distribution
#              (53 types / 224 devices, 08-06-2026); a device-class fallback
#              covers any type not in the table so unknown/future types still
#              bridge on their category.
# Author:      CliveS & Claude Opus 4.8
# Date:        08-06-2026
# Version:     1.0

from typing import Any, Dict

# deviceTypeId -> space-separated synonym string. Lower-case throughout; matched
# as plain substring/word membership by VectorStore._score (no stemming), so
# include the common singular forms a user would actually type.
TYPE_ALIASES: Dict[str, str] = {
    # ── Lights / dimmers ────────────────────────────────────────────────
    "z2mLight":            "light lamp bulb dimmer dimmable lighting",
    "zwDimmerType":        "light lamp bulb dimmer dimmable lighting",
    "esphomeLight":        "light lamp bulb dimmer lighting",
    # ── Relays / plugs / switches ───────────────────────────────────────
    "shellyRelay":         "plug switch outlet socket relay power smartplug",
    "zwRelayType":         "switch relay outlet plug socket",
    "z2mRelay":            "relay switch plug outlet socket",
    "esphomeSwitch":       "switch relay plug outlet",
    "tasmotaEnergyPlug":   "plug switch outlet socket power energy smartplug",
    "pseudoRelay":         "virtual switch relay pseudo",
    # ── Contact / door / window ─────────────────────────────────────────
    "z2mContactSensor":    "contact door window opening reed magnet sensor",
    # ── Motion / occupancy / presence ───────────────────────────────────
    "zwOnOffSensorType":   "motion occupancy presence binary sensor pir",
    "z2mOccupancySensor":  "occupancy presence motion person sensor pir",
    "zwaveSensorMotion":   "motion occupancy presence sensor pir",
    # ── Buttons / scene controllers ─────────────────────────────────────
    "z2mButton":           "button scene controller switch wallmote remote",
    "zwCustomType":        "button scene controller wallmote remote",
    # ── Value / generic sensors ─────────────────────────────────────────
    # These are CATCH-ALL types (z2mSensor covers leak/motion/temp/humidity/
    # presence; zwValueSensorType covers any multilevel reading). Tag them ONLY
    # with the generic word — putting specific words like "leak"/"temperature"
    # here would falsely match EVERY sensor of the type. The specific devices
    # are found by name ("... Leak Sensor", "... Humidity") instead.
    "zwValueSensorType":   "sensor reading value measurement",
    "z2mSensor":           "sensor",
    "shellyUniADC":        "sensor battery voltage adc analog",
    # ── Thermostats / heating ───────────────────────────────────────────
    # No "temperature" here — a radiator is a heat source, not a temperature
    # sensor; tagging it "temperature" would crowd out actual temp sensors.
    "ramsesZoneThermostat":"radiator trv thermostat heating valve zone heat evohome",
    "zwThermostatType":    "thermostat heating heat floor",
    "esphomeClimate":      "thermostat climate heating cooling hvac",
    # ── Locks ───────────────────────────────────────────────────────────
    "zwLockType":          "lock door deadbolt smartlock",
    "esphomeLock":         "lock door deadbolt",
    "doorLock":            "lock door deadbolt smartlock",
    # ── Weather (Ecowitt) ───────────────────────────────────────────────
    "ecowittIndoor":       "weather sensor indoor temperature humidity ecowitt",
    "ecowittOutdoor":      "weather sensor outdoor temperature humidity ecowitt",
    "ecowittMain":         "weather gateway station ecowitt",
    "ecowittMultiChannel": "weather sensor temperature humidity ecowitt channel",
    "ecowittRain":         "weather rain rainfall precipitation ecowitt",
    "ecowittSolar":        "weather solar uv radiation ecowitt sunlight",
    "ecowittWind":         "weather wind speed direction ecowitt",
    # ── Power stations / batteries ──────────────────────────────────────
    "ecoflowRiver3":       "battery power station portable ecoflow generator backup",
    "ecoflowDelta3":       "battery power station portable ecoflow generator backup",
    "batteryManager":      "battery manager storage soc sigenergy",
    # ── Solar / energy ──────────────────────────────────────────────────
    "sigenergyInverter":   "solar inverter battery pv sigenergy energy",
    "solarForecast":       "solar forecast pv generation prediction",
    "tariffMonitor":       "tariff energy electricity price rate octopus",
    "axleVppMonitor":      "vpp virtual power plant energy axle",
    # ── Network / Wi-Fi ─────────────────────────────────────────────────
    "unifiAP":             "wifi access point ap unifi network wireless",
    "unifiController":     "unifi controller network gateway",
    # ── Repeaters / coordinators / bridges ──────────────────────────────
    "z2mRepeater":         "repeater router extender zigbee",
    "z2mCoordinator":      "coordinator bridge hub zigbee gateway",
    "snifferCoordinator":  "sniffer coordinator zigbee mqtt monitor",
    "homeKitBridgeDevice": "homekit siri bridge apple home",
    "mqttBroker":          "mqtt broker mosquitto messaging",
    # ── Appliances / monitors ───────────────────────────────────────────
    "applianceMonitor":    "appliance monitor washing machine tumble dryer",
    "damGroup":            "activity monitor group sensor",
    # ── Misc ────────────────────────────────────────────────────────────
    "timer":               "timer countdown delay",
    "clockdisplay":        "clock time display",
    "imapAccount":         "email imap mail inbox",
    "smtpAccount":         "email smtp mail send",
    "formulaConvertedSensorString": "sensor converted formula derived",
}


def _class_fallback(class_name: str) -> str:
    """Category synonyms derived from the Indigo device class, so a type not in
    TYPE_ALIASES still bridges on its broad category. Matches on substring to be
    robust to 'DimmerDevice' vs 'indigo.DimmerDevice' style values."""
    c = class_name.lower()
    if "dimmer" in c:
        return "light lamp dimmer dimmable lighting"
    if "relay" in c:
        return "switch relay plug outlet socket"
    if "thermostat" in c:
        return "thermostat heating temperature radiator"
    if "sensor" in c:
        return "sensor"
    return ""


def aliases_for(entity: Dict[str, Any]) -> str:
    """Return the space-joined alias string for an entity's device type.

    Returns "" for variables / action groups (no deviceTypeId) and for unknown
    device types with no class hint. The explicit TYPE_ALIASES entry and the
    device-class fallback are combined (both, when available) so a known type
    gets its curated synonyms plus its category words.
    """
    dtid = entity.get("deviceTypeId")
    if not dtid:
        return ""
    parts = []
    explicit = TYPE_ALIASES.get(dtid)
    if explicit:
        parts.append(explicit)
    fallback = _class_fallback(str(entity.get("class", "")))
    if fallback:
        parts.append(fallback)
    return " ".join(parts)
