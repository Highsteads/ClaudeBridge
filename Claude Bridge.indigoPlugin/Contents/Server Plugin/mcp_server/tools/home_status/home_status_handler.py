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
  - heating_status()      : every thermostat device, with whether it is heating
  - security_status()     : open contacts, unlocked locks, motion and alarms
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from ...adapters.indigo_data_provider import IndigoDataProvider
from ...common.battery import battery_pct as _battery_pct
from ...common import device_roles


def _security_snapshot(devices) -> Dict[str, List[Dict[str, Any]]]:
    """Open contacts, unlocked locks, active motion and active alarms, judged
    by what each device IS (common/device_roles.py), not by its name."""
    snap: Dict[str, List[Dict[str, Any]]] = {
        "open_contacts": [], "unlocked_locks": [], "active_motion": [], "active_alerts": []}
    for dev in devices:
        if not getattr(dev, "enabled", True):
            continue
        on = device_roles.on_state(dev)
        if on is None:
            continue
        entry = {"id": dev.id, "name": dev.name}
        if device_roles.is_lock(dev):
            if not on:                       # a lock's onState True means LOCKED
                snap["unlocked_locks"].append(entry)
            continue
        role = device_roles.sensor_role(dev)
        if role == "contact" and on:
            snap["open_contacts"].append(entry)
        elif role == "motion" and on:
            snap["active_motion"].append(entry)
        elif role == "alarm" and on:
            snap["active_alerts"].append(entry)
    return snap


def _thermostats(devices) -> List[Any]:
    """Every enabled thermostat, whichever plugin owns it. Selected by class:
    picking by plugin-id words missed Z-Wave, ecobee and Nest thermostats."""
    return [d for d in devices
            if getattr(d, "enabled", True) and device_roles.is_thermostat(d)]


def _first(states, *keys):
    """First key that is actually PRESENT, rather than first that is truthy.

    Battery percentage, solar watts, grid watts, a room temperature and a
    setpoint can all legitimately read 0, and an `or` chain treats 0 as absent —
    reporting a real measurement as missing, which is the worst direction to be
    wrong in. Returns None only when no key holds a value.
    """
    for key in keys:
        value = states.get(key)
        if value is not None:
            return value
    return None

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
        data_provider: "IndigoDataProvider",
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
                batt = _battery_pct(dev)
                if batt is not None:
                    try:
                        if int(batt) <= 20:
                            low_batt.append({"id": dev.id, "name": dev.name,
                                             "battery_pct": int(batt)})
                    except (ValueError, TypeError):
                        pass

                # Grouping
                # By device class, not plugin-id words: "shelly" put every
                # Shelly plug under energy, and a dimmer from any other plugin
                # was never a light.
                cls = type(dev).__name__
                pid = dev.pluginId.lower()
                if cls == "DimmerDevice":
                    groups["lights"].append(_dev_summary(dev))
                elif cls == "ThermostatDevice":
                    groups["heating"].append(_dev_summary(dev))
                elif any(x in pid for x in ("sigenergy", "octopus")):
                    groups["energy"].append(_dev_summary(dev))
                elif cls == "SensorDevice":
                    groups["sensors"].append(_dev_summary(dev))
                elif cls == "RelayDevice":
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

            # Snapshot the device collection ONCE and reuse it for every
            # section that iterates devices (alerts, heating, security, devices).
            # Iterating the live indigo.devices collection separately per
            # section meant several full passes over the whole estate per call.
            all_devices = list(indigo.devices)

            ts    = datetime.now().strftime("%A %-d %B %Y, %H:%M")
            lines: List[str] = [f"# Home Status Report\n*{ts}*\n"]

            # ── Alerts section ─────────────────────────────────────────────
            if "alerts" in active:
                errors   = []
                low_batt = []
                for dev in all_devices:
                    if not dev.enabled:
                        continue
                    try:
                        if dev.errorState:
                            errors.append(dev.name)
                    except AttributeError:
                        pass
                    batt = _battery_pct(dev)
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
                    # _first, not `or`: every one of these can legitimately be 0
                    # — a flat battery, no sun, nothing crossing the meter — and
                    # `or` reads 0 as missing, so it fell through to the variable
                    # name guesses below or reported the figure as unavailable.
                    # Zero is a reading, and often the interesting one.
                    if soc is None:
                        soc = _first(states, "batterySOC", "soc", "batterySoc")
                    if solar_w is None:
                        solar_w = _first(states, "pvPower", "solarPower", "pvWatts")
                    if grid_w is None:
                        grid_w = _first(states, "gridPower", "gridWatts")

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
                for dev in _thermostats(all_devices):
                    # See _first: a room genuinely at 0.0 C, or a setpoint of 0
                    # on an off zone, must not read as "no sensor".
                    temp  = _first(dev.states, "temperatureInput1",
                                   "displayTemp", "temperature")
                    setpt = _first(dev.states, "heatSetpoint",
                                   "setpointHeat", "setpoint")
                    if temp is not None or setpt is not None:
                        zones.append({"name": dev.name, "temp": temp, "setpoint": setpt,
                                      "heating": device_roles.thermostat_is_heating(dev)})

                lines.append("## Heating")
                if zones:
                    # Heating means heatIsOn, or a setpoint above the room. The
                    # old "setpoint > 5.5" test counted every idle RAMSES zone
                    # at its 8 degree frost setpoint as heating (12 of 12).
                    active_z = [z for z in zones if z["heating"]]
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
                snap = _security_snapshot(all_devices)
                open_contacts = [e["name"] for e in snap["open_contacts"]]
                unlocked      = [e["name"] for e in snap["unlocked_locks"]]
                active_motion = [e["name"] for e in snap["active_motion"]]
                active_alarms = [e["name"] for e in snap["active_alerts"]]

                lines.append("## Security")
                if not open_contacts and not unlocked and not active_motion and not active_alarms:
                    lines.append(
                        "All doors and windows are closed and every lock is locked. "
                        "No motion or alarms detected."
                    )
                else:
                    if unlocked:
                        lines.append(f"**Unlocked**: {', '.join(unlocked)}.")
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
                total    = len(all_devices)
                enabled  = sum(1 for d in all_devices if d.enabled)
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
            snap = self._sigen_snapshot()
            result = {"success": True, **snap}
            # Section keys are the device types with "sigenergy" removed.
            if not any(k in snap for k in ("Inverter", "Battery", "batteryManager")):
                # This view reads SigenEnergyManager devices only; say so
                # rather than hand another house an unexplained empty answer.
                result["note"] = ("No SigenEnergyManager devices found. This section "
                                  "reads that plugin's inverter, battery and manager "
                                  "devices; for any other meter use get_device_by_id "
                                  "or device_history.")
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
            for dev in _thermostats(indigo.devices[did] for did in indigo.devices):
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
                zone["heating"] = device_roles.thermostat_is_heating(dev)
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
            snap = _security_snapshot(indigo.devices[did] for did in indigo.devices)
            result = {
                "success": True,
                **snap,
                "summary": {k: len(v) for k, v in snap.items()},
            }
            self.log_tool_outcome("security_status", True,
                                  f"{len(snap['open_contacts'])} open contacts, "
                                  f"{len(snap['unlocked_locks'])} unlocked")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "security_status")
