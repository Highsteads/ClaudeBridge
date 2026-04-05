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

VALID_SECTIONS = (
    "energy", "heating", "security", "devices", "alerts", "automation"
)

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
    # home_status_report — configurable prose narrative
    # ────────────────────────────────────────────────────────────────────────

    def home_status_report(self, sections: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Generate a configurable markdown prose report of home status.
        Claude should present the `report` field directly to the user.

        sections: list of section names to include.
                  Valid: energy, heating, security, devices, alerts, automation
                  Default: all sections.
        """
        self.log_incoming_request("home_status_report", {"sections": sections})
        try:
            active = (
                [s.lower() for s in sections if s.lower() in VALID_SECTIONS]
                if sections
                else list(VALID_SECTIONS)
            )

            ts    = datetime.now().strftime("%A %-d %B %Y, %H:%M")
            lines: List[str] = [f"# Home Status Report\n*{ts}*\n"]

            # ── Alerts section ─────────────────────────────────────────────
            if "alerts" in active:
                errors   = []
                low_batt = []
                for did in indigo.devices:
                    dev = indigo.devices[did]
                    if not dev.enabled:
                        continue
                    try:
                        if dev.errorState:
                            errors.append(dev.name)
                    except AttributeError:
                        pass
                    batt = dev.states.get("batteryLevel")
                    if batt is not None:
                        try:
                            if int(batt) <= 20:
                                low_batt.append(f"{dev.name} ({batt}%)")
                        except (ValueError, TypeError):
                            pass
                lines.append("## Alerts")
                if errors or low_batt:
                    if errors:
                        et = ", ".join(errors[:5]) + ("…" if len(errors) > 5 else "")
                        lines.append(
                            f"There are **{len(errors)} device(s) in error**: {et}."
                        )
                    if low_batt:
                        bt = ", ".join(low_batt[:5]) + ("…" if len(low_batt) > 5 else "")
                        lines.append(
                            f"**{len(low_batt)} device(s) have low battery**: {bt}."
                        )
                else:
                    lines.append("No active alerts — all devices healthy.")
                lines.append("")

            # ── Energy section ─────────────────────────────────────────────
            if "energy" in active:
                snap        = self._sigen_snapshot()
                energy_vars = snap.get("variables", {})
                soc = solar_w = grid_w = decision = tariff = None

                for dev_key in snap:
                    if dev_key == "variables":
                        continue
                    states = snap[dev_key].get("states", {})
                    if soc is None:
                        soc = (states.get("batterySOC") or states.get("soc")
                               or states.get("batterySoc"))
                    if solar_w is None:
                        solar_w = (states.get("pvPower") or states.get("solarPower")
                                   or states.get("pvWatts"))
                    if grid_w is None:
                        grid_w = (states.get("gridPower") or states.get("gridWatts"))

                for k, v in energy_vars.items():
                    kl = k.lower()
                    if soc is None and "soc" in kl:
                        soc = v
                    if solar_w is None and ("pv" in kl or "solar" in kl) and (
                        "watt" in kl or "power" in kl or "kw" in kl
                    ):
                        solar_w = v
                    if grid_w is None and "grid" in kl and (
                        "watt" in kl or "power" in kl or "kw" in kl
                    ):
                        grid_w = v
                    if decision is None and "decision" in kl:
                        decision = v
                    if tariff is None and ("tariff" in kl or "rate" in kl or "octopus" in kl):
                        tariff = v

                energy_parts: List[str] = []
                if soc is not None:
                    energy_parts.append(f"the battery is at **{soc}% SOC**")
                if solar_w is not None:
                    try:
                        w = float(solar_w)
                        kw = w / 1000 if w > 100 else w
                        energy_parts.append(f"solar is generating **{kw:.2f} kW**")
                    except (ValueError, TypeError):
                        energy_parts.append(f"solar is at {solar_w}")
                if grid_w is not None:
                    try:
                        gw = float(grid_w)
                        if gw > 50:
                            energy_parts.append(f"drawing **{gw:.0f} W from the grid**")
                        elif gw < -50:
                            energy_parts.append(
                                f"exporting **{abs(gw):.0f} W to the grid**"
                            )
                        else:
                            energy_parts.append("not importing or exporting")
                    except (ValueError, TypeError):
                        pass

                lines.append("## Energy")
                if energy_parts:
                    lines.append("Currently " + ", ".join(energy_parts) + ".")
                else:
                    lines.append("Energy device data is not currently available.")
                if tariff:
                    lines.append(f"Current tariff/rate: {tariff}.")
                if decision:
                    lines.append(f"Battery manager decision: *{decision}*.")
                lines.append("")

            # ── Heating section ────────────────────────────────────────────
            if "heating" in active:
                zones: List[Dict] = []
                for did in indigo.devices:
                    dev = indigo.devices[did]
                    if not dev.enabled:
                        continue
                    if not any(
                        x in dev.pluginId.lower()
                        for x in ("homeassistant", "ramses", "evohome", "thermostat")
                    ):
                        continue
                    temp  = (dev.states.get("temperatureInput1")
                             or dev.states.get("displayTemp")
                             or dev.states.get("temperature"))
                    setpt = (dev.states.get("heatSetpoint")
                             or dev.states.get("setpointHeat")
                             or dev.states.get("setpoint"))
                    if temp is not None or setpt is not None:
                        zones.append({"name": dev.name, "temp": temp, "setpoint": setpt})

                lines.append("## Heating")
                if zones:
                    def _is_active(z):
                        try:
                            return float(z["setpoint"] or 0) > 5.5
                        except (ValueError, TypeError):
                            return False

                    active_z = [z for z in zones if _is_active(z)]
                    lines.append(
                        f"There are **{len(zones)} zones** monitored, "
                        f"of which **{len(active_z)} are actively heating**."
                    )
                    if active_z[:6]:
                        zone_strs = [
                            f"{z['name']} ({z['temp']}°C → {z['setpoint']}°C)"
                            for z in active_z[:6]
                        ]
                        lines.append("Active zones: " + "; ".join(zone_strs) + ".")
                else:
                    lines.append("No heating zone data available.")
                lines.append("")

            # ── Security section ───────────────────────────────────────────
            if "security" in active:
                open_contacts: List[str] = []
                active_motion: List[str] = []
                active_alarms: List[str] = []
                for did in indigo.devices:
                    dev = indigo.devices[did]
                    if not dev.enabled:
                        continue
                    name_l = dev.name.lower()
                    try:
                        on = dev.onState
                    except AttributeError:
                        continue
                    if any(x in name_l for x in ("door", "window", "contact", "reed")) and on:
                        open_contacts.append(dev.name)
                    elif any(x in name_l for x in ("motion", "pir", "presence", "occupancy")) and on:
                        active_motion.append(dev.name)
                    elif any(x in name_l for x in ("leak", "water", "smoke", "co ")) and on:
                        active_alarms.append(dev.name)

                lines.append("## Security")
                if not open_contacts and not active_motion and not active_alarms:
                    lines.append(
                        "All doors and windows are closed. No motion or alarms detected."
                    )
                else:
                    if open_contacts:
                        lines.append(
                            f"**{len(open_contacts)} open contact(s)**: "
                            f"{', '.join(open_contacts[:6])}."
                        )
                    if active_motion:
                        lines.append(
                            f"**{len(active_motion)} active motion sensor(s)**: "
                            f"{', '.join(active_motion[:6])}."
                        )
                    if active_alarms:
                        lines.append(
                            f"⚠ **Active alarm(s)**: {', '.join(active_alarms)}."
                        )
                lines.append("")

            # ── Devices section ────────────────────────────────────────────
            if "devices" in active:
                total    = len(list(indigo.devices))
                enabled  = sum(1 for d in indigo.devices if indigo.devices[d].enabled)
                disabled = total - enabled
                lines.append("## Devices")
                lines.append(
                    f"There are **{total} devices** in Indigo: "
                    f"{enabled} enabled"
                    + (f", {disabled} disabled." if disabled else ".")
                )
                lines.append("")

            # ── Automation section ─────────────────────────────────────────
            if "automation" in active:
                enabled_trigs  = sum(
                    1 for t in indigo.triggers if indigo.triggers[t].enabled
                )
                enabled_scheds = sum(
                    1 for s in indigo.schedules if indigo.schedules[s].enabled
                )
                total_trigs    = len(list(indigo.triggers))
                total_scheds   = len(list(indigo.schedules))
                total_ags      = len(list(indigo.actionGroups))
                lines.append("## Automation")
                lines.append(
                    f"Running **{enabled_trigs} of {total_trigs} triggers**, "
                    f"**{enabled_scheds} of {total_scheds} schedules**, "
                    f"and **{total_ags} action groups**."
                )
                lines.append("")

            report = "\n".join(lines)
            result = {
                "success":   True,
                "timestamp": ts,
                "sections":  active,
                "report":    report,
            }
            self.log_tool_outcome("home_status_report", True,
                                  f"Report generated ({', '.join(active)})")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "home_status_report")

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
