"""
Home status handler for ClaudeBridge MCP server.

Provides a single aggregated home status snapshot by pulling together:
  - All Indigo device states grouped by protocol/type
  - All Indigo variables (key values)
  - SigenEnergyManager inverter states (battery, solar, grid, tariff)
  - RAMSES ESP heating status (last MQTT activity, zone setpoints)
  - Active alerts (devices in error, low battery, offline devices)
  - Automation summary (enabled triggers/schedules count)

Tools:
  - home_status()         : full structured snapshot
  - energy_status()       : SigenEnergyManager states only
  - heating_status()      : RAMSES + Evohome zone states
  - security_status()     : all contact/motion sensors
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

# SigenEnergyManager device type IDs
SIGEN_INVERTER_TYPE  = "sigenergyInverter"
SIGEN_BATTERY_TYPE   = "sigenergyBattery"
SIGEN_MANAGER_TYPE   = "batteryManager"

# Known key variable names for status
_KEY_VARIABLE_PATTERNS = [
    "lux", "soc", "solar", "battery", "grid", "tariff", "rate",
    "temperature", "setpoint", "mode", "state", "status", "level",
    "octopus", "export", "import", "forecast",
]


def _dev_summary(dev) -> Dict[str, Any]:
    """Minimal device summary dict."""
    d = {
        "id":       dev.id,
        "name":     dev.name,
        "enabled":  dev.enabled,
        "plugin":   dev.pluginId,
    }
    # onState for relays/dimmers/sensors
    try:
        d["on"] = dev.onState
    except AttributeError:
        pass
    try:
        d["brightness"] = dev.brightness
    except AttributeError:
        pass
    # Error state
    try:
        err = dev.errorState
        if err:
            d["error"] = str(err)
    except AttributeError:
        pass
    return d


def _is_key_variable(name: str) -> bool:
    nl = name.lower()
    return any(p in nl for p in _KEY_VARIABLE_PATTERNS)


class HomeStatusHandler(BaseToolHandler):
    """Handler for comprehensive home state snapshots."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="home_status", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # home_status — full snapshot
    # ────────────────────────────────────────────────────────────────────────

    def home_status(self) -> Dict[str, Any]:
        """
        Return a comprehensive structured snapshot of the home.
        Groups devices by protocol, surfaces key variables, energy status,
        and active alerts. Designed for Claude to narrate as a readable report.
        """
        self.log_incoming_request("home_status", {})
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # ── Devices by protocol ───────────────────────────────────────
            groups: Dict[str, List] = {
                "lights":    [],
                "sensors":   [],
                "switches":  [],
                "heating":   [],
                "energy":    [],
                "other":     [],
            }
            errors   = []
            low_batt = []

            for did in indigo.devices:
                dev = indigo.devices[did]
                if not dev.enabled:
                    continue

                # Error / battery collection
                try:
                    if dev.errorState:
                        errors.append({"id": dev.id, "name": dev.name,
                                       "error": str(dev.errorState)})
                except AttributeError:
                    pass
                batt = dev.states.get("batteryLevel")
                if batt is not None:
                    try:
                        if int(batt) <= 20:
                            low_batt.append({"id": dev.id, "name": dev.name,
                                             "battery_pct": int(batt)})
                    except (ValueError, TypeError):
                        pass

                # Grouping
                pid = dev.pluginId.lower()
                if any(x in pid for x in ("hue", "zigbee", "z-wave", "zwave")) \
                        and hasattr(dev, "brightness"):
                    groups["lights"].append(_dev_summary(dev))
                elif any(x in pid for x in ("ramses", "evohome", "homeassistant")):
                    groups["heating"].append(_dev_summary(dev))
                elif any(x in pid for x in ("sigenergy", "energy", "shelly", "octopus")):
                    groups["energy"].append(_dev_summary(dev))
                elif any(x in pid for x in ("sensor", "motion", "contact", "leak",
                                             "smoke", "zwave")):
                    groups["sensors"].append(_dev_summary(dev))
                elif hasattr(dev, "onState") and not hasattr(dev, "brightness"):
                    groups["switches"].append(_dev_summary(dev))
                else:
                    groups["other"].append(_dev_summary(dev))

            # ── Key variables ─────────────────────────────────────────────
            key_vars = []
            for vid in indigo.variables:
                v = indigo.variables[vid]
                if _is_key_variable(v.name):
                    key_vars.append({
                        "id":    v.id,
                        "name":  v.name,
                        "value": v.value,
                    })
            key_vars.sort(key=lambda x: x["name"].lower())

            # ── Energy snapshot ───────────────────────────────────────────
            energy = self._sigen_snapshot()

            # ── Automation summary ────────────────────────────────────────
            enabled_triggers  = sum(1 for t in indigo.triggers
                                    if indigo.triggers[t].enabled)
            enabled_schedules = sum(1 for s in indigo.schedules
                                    if indigo.schedules[s].enabled)

            result = {
                "success":   True,
                "timestamp": ts,
                "alerts": {
                    "devices_in_error":  errors[:10],
                    "low_battery":       sorted(low_batt, key=lambda x: x["battery_pct"])[:10],
                },
                "devices": {
                    k: v for k, v in groups.items() if v
                },
                "device_counts": {k: len(v) for k, v in groups.items()},
                "key_variables": key_vars[:40],
                "energy":  energy,
                "automation": {
                    "enabled_triggers":  enabled_triggers,
                    "enabled_schedules": enabled_schedules,
                    "total_triggers":    len(list(indigo.triggers)),
                    "total_schedules":   len(list(indigo.schedules)),
                    "total_action_groups": len(list(indigo.actionGroups)),
                },
            }
            self.log_tool_outcome("home_status", True, "Home status snapshot complete")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "home_status")

    # ────────────────────────────────────────────────────────────────────────
    # energy_status
    # ────────────────────────────────────────────────────────────────────────

    def energy_status(self) -> Dict[str, Any]:
        """Return SigenEnergyManager device states as an energy snapshot."""
        self.log_incoming_request("energy_status", {})
        try:
            result = {"success": True, **self._sigen_snapshot()}
            self.log_tool_outcome("energy_status", True, "Energy snapshot complete")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "energy_status")

    def _sigen_snapshot(self) -> Dict[str, Any]:
        """Read all SigenEnergyManager device states into a flat dict."""
        snap: Dict[str, Any] = {}
        for did in indigo.devices:
            dev = indigo.devices[did]
            if not dev.enabled:
                continue
            dtype = getattr(dev, "deviceTypeId", "")
            if dtype in (SIGEN_INVERTER_TYPE, SIGEN_BATTERY_TYPE, SIGEN_MANAGER_TYPE):
                section = dtype.replace("sigenergy", "").replace("battery", "battery")
                snap[section] = {
                    "id":     dev.id,
                    "name":   dev.name,
                    "states": dict(dev.states),
                }
        # Also pull key energy variables
        energy_vars = {}
        for vid in indigo.variables:
            v = indigo.variables[vid]
            vl = v.name.lower()
            if any(x in vl for x in ("soc", "solar", "battery", "grid", "tariff",
                                      "export", "import", "kwh", "watt", "rate",
                                      "octopus", "forecast")):
                energy_vars[v.name] = v.value
        if energy_vars:
            snap["variables"] = energy_vars
        return snap

    # ────────────────────────────────────────────────────────────────────────
    # heating_status
    # ────────────────────────────────────────────────────────────────────────

    def heating_status(self) -> Dict[str, Any]:
        """Return all heating/thermostat device states (Evohome TRVs via HA Agent)."""
        self.log_incoming_request("heating_status", {})
        try:
            zones = []
            for did in indigo.devices:
                dev = indigo.devices[did]
                if not dev.enabled:
                    continue
                pid = dev.pluginId.lower()
                if not any(x in pid for x in ("homeassistant", "ramses", "evohome",
                                               "thermostat")):
                    continue
                zone: Dict[str, Any] = {
                    "id":     dev.id,
                    "name":   dev.name,
                    "plugin": dev.pluginId,
                }
                for state_key in ("setpoint", "temperature", "hvacMode",
                                  "heatSetpoint", "coolSetpoint", "temperatureInput1",
                                  "displayTemp", "setpointHeat", "onState"):
                    val = dev.states.get(state_key)
                    if val is not None:
                        zone[state_key] = val
                zones.append(zone)

            zones.sort(key=lambda x: x["name"].lower())
            result = {
                "success": True,
                "count":   len(zones),
                "zones":   zones,
            }
            self.log_tool_outcome("heating_status", True, f"{len(zones)} zones")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "heating_status")

    # ────────────────────────────────────────────────────────────────────────
    # security_status
    # ────────────────────────────────────────────────────────────────────────

    def security_status(self) -> Dict[str, Any]:
        """Return all contact, motion, leak, and smoke sensor states."""
        self.log_incoming_request("security_status", {})
        try:
            open_contacts = []
            active_motion = []
            alerts        = []

            for did in indigo.devices:
                dev = indigo.devices[did]
                if not dev.enabled:
                    continue
                name_l = dev.name.lower()
                is_contact = any(x in name_l for x in
                                 ("door", "window", "contact", "reed"))
                is_motion  = any(x in name_l for x in
                                 ("motion", "pir", "presence", "occupancy"))
                is_alert   = any(x in name_l for x in
                                 ("leak", "water", "smoke", "co ", "carbon"))

                try:
                    on = dev.onState
                except AttributeError:
                    continue

                if is_contact and on:
                    open_contacts.append({"id": dev.id, "name": dev.name})
                elif is_motion and on:
                    active_motion.append({"id": dev.id, "name": dev.name})
                elif is_alert and on:
                    alerts.append({"id": dev.id, "name": dev.name})

            result = {
                "success":        True,
                "open_contacts":  open_contacts,
                "active_motion":  active_motion,
                "active_alerts":  alerts,
                "summary": {
                    "open_contacts": len(open_contacts),
                    "active_motion": len(active_motion),
                    "active_alerts": len(alerts),
                },
            }
            self.log_tool_outcome("security_status", True,
                                  f"{len(open_contacts)} open contacts, "
                                  f"{len(active_motion)} motion active")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "security_status")
