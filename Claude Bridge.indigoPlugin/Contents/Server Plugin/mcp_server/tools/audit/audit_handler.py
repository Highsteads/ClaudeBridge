"""
Audit handler for ClaudeBridge MCP server.

Provides configuration health checks and housekeeping analysis:
  - audit_home            : comprehensive health check across all Indigo objects
  - find_devices_in_error : devices currently in error or offline state
  - find_low_battery      : devices with battery level below threshold
  - find_stale_devices    : devices with no state change in N days
  - audit_variables       : variables with empty/null values or no script references
  - dependency_map        : everything that references a given device or variable
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider


def _scripts_dir() -> str:
    pa_base = os.path.dirname(indigo.server.getInstallFolderPath())
    return os.path.join(pa_base, "Python Scripts")


def _days_since(ts) -> Optional[float]:
    """Return days since a timestamp (datetime or epoch float). None if unavailable."""
    try:
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return (time.time() - float(ts)) / 86400.0
        # datetime object
        if hasattr(ts, "timestamp"):
            return (time.time() - ts.timestamp()) / 86400.0
    except Exception:
        pass
    return None


def _scan_scripts_for_ids(script_dir: str) -> Dict[int, List[str]]:
    """
    Scan all .py files in script_dir.
    Returns {numeric_id: [script_name, ...]} for every 8-12 digit ID found.
    """
    id_pattern = re.compile(r"\b(\d{8,12})\b")
    id_map: Dict[int, List[str]] = {}
    if not os.path.isdir(script_dir):
        return id_map
    for entry in os.scandir(script_dir):
        if not entry.name.endswith(".py") or not entry.is_file():
            continue
        try:
            with open(entry.path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        for m in id_pattern.findall(content):
            iid = int(m)
            id_map.setdefault(iid, [])
            if entry.name not in id_map[iid]:
                id_map[iid].append(entry.name)
    return id_map


class AuditHandler(BaseToolHandler):
    """Handler for Indigo configuration audit and housekeeping tools."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="audit", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # audit_home — comprehensive health snapshot
    # ────────────────────────────────────────────────────────────────────────

    def audit_home(self) -> Dict[str, Any]:
        """
        Run a full configuration health check and return a summary covering:
        devices in error, low-battery devices, stale devices, empty variables,
        disabled triggers, disabled schedules, and a count of Python scripts.
        """
        self.log_incoming_request("audit_home", {})
        try:
            errors     = self._collect_device_errors()
            batteries  = self._collect_low_battery(threshold=20)
            stale      = self._collect_stale_devices(days=7)

            # Variables with empty or "null" values
            empty_vars = []
            for vid in indigo.variables:
                v = indigo.variables[vid]
                val = str(v.value).strip().lower()
                if val in ("", "none", "null", "false") and not v.readOnly:
                    empty_vars.append({"id": v.id, "name": v.name, "value": v.value})

            # Disabled triggers
            disabled_triggers = []
            for tid in indigo.triggers:
                t = indigo.triggers[tid]
                if not t.enabled:
                    disabled_triggers.append({"id": t.id, "name": t.name})

            # Disabled schedules
            disabled_schedules = []
            for sid in indigo.schedules:
                s = indigo.schedules[sid]
                if not s.enabled:
                    disabled_schedules.append({"id": s.id, "name": s.name})

            # Script count
            scripts_dir = _scripts_dir()
            script_count = 0
            if os.path.isdir(scripts_dir):
                script_count = sum(
                    1 for e in os.scandir(scripts_dir)
                    if e.name.endswith(".py") and e.is_file()
                )

            result = {
                "success": True,
                "summary": {
                    "devices_in_error":    len(errors),
                    "low_battery_devices": len(batteries),
                    "stale_devices_7d":    len(stale),
                    "empty_variables":     len(empty_vars),
                    "disabled_triggers":   len(disabled_triggers),
                    "disabled_schedules":  len(disabled_schedules),
                    "python_scripts":      script_count,
                    "total_devices":       len(list(indigo.devices)),
                    "total_variables":     len(list(indigo.variables)),
                    "total_triggers":      len(list(indigo.triggers)),
                    "total_schedules":     len(list(indigo.schedules)),
                    "total_action_groups": len(list(indigo.actionGroups)),
                },
                "devices_in_error":   errors[:20],
                "low_battery":        batteries[:20],
                "stale_devices":      stale[:20],
                "empty_variables":    empty_vars[:20],
                "disabled_triggers":  disabled_triggers[:20],
                "disabled_schedules": disabled_schedules[:20],
            }
            self.log_tool_outcome("audit_home", True, "Home audit complete")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "audit_home")

    # ────────────────────────────────────────────────────────────────────────
    # find_devices_in_error
    # ────────────────────────────────────────────────────────────────────────

    def find_devices_in_error(self) -> Dict[str, Any]:
        """Return all devices currently in error or offline state."""
        self.log_incoming_request("find_devices_in_error", {})
        try:
            errors = self._collect_device_errors()
            result = {
                "success": True,
                "count":   len(errors),
                "devices": errors,
            }
            self.log_tool_outcome("find_devices_in_error", True,
                                  f"{len(errors)} devices in error")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_devices_in_error")

    def _collect_device_errors(self) -> List[Dict[str, Any]]:
        errors = []
        for did in indigo.devices:
            dev = indigo.devices[did]
            try:
                err = dev.errorState
            except AttributeError:
                err = None
            if err:
                errors.append({
                    "id":         dev.id,
                    "name":       dev.name,
                    "error":      str(err),
                    "plugin_id":  dev.pluginId,
                    "enabled":    dev.enabled,
                })
        return errors

    # ────────────────────────────────────────────────────────────────────────
    # find_low_battery
    # ────────────────────────────────────────────────────────────────────────

    def find_low_battery(self, threshold: int = 20) -> Dict[str, Any]:
        """Return devices with a batteryLevel state below the given threshold (%)."""
        self.log_incoming_request("find_low_battery", {"threshold": threshold})
        try:
            low = self._collect_low_battery(threshold)
            result = {
                "success":   True,
                "threshold": threshold,
                "count":     len(low),
                "devices":   low,
            }
            self.log_tool_outcome("find_low_battery", True,
                                  f"{len(low)} devices below {threshold}%")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_low_battery")

    def _collect_low_battery(self, threshold: int = 20) -> List[Dict[str, Any]]:
        low = []
        for did in indigo.devices:
            dev = indigo.devices[did]
            batt = dev.states.get("batteryLevel")
            if batt is None:
                continue
            try:
                pct = int(batt)
            except (ValueError, TypeError):
                continue
            if pct <= threshold:
                low.append({
                    "id":           dev.id,
                    "name":         dev.name,
                    "battery_pct":  pct,
                    "plugin_id":    dev.pluginId,
                })
        low.sort(key=lambda x: x["battery_pct"])
        return low

    # ────────────────────────────────────────────────────────────────────────
    # find_stale_devices
    # ────────────────────────────────────────────────────────────────────────

    def find_stale_devices(self, days: int = 7) -> Dict[str, Any]:
        """
        Return devices whose lastChanged timestamp is more than `days` days ago,
        and which are expected to be active (enabled, not virtual/plugin-less).
        """
        self.log_incoming_request("find_stale_devices", {"days": days})
        try:
            stale = self._collect_stale_devices(days)
            result = {
                "success":   True,
                "threshold_days": days,
                "count":     len(stale),
                "devices":   stale,
            }
            self.log_tool_outcome("find_stale_devices", True,
                                  f"{len(stale)} devices stale > {days}d")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_stale_devices")

    def _collect_stale_devices(self, days: int = 7) -> List[Dict[str, Any]]:
        stale = []
        for did in indigo.devices:
            dev = indigo.devices[did]
            if not dev.enabled:
                continue
            lc = getattr(dev, "lastChanged", None)
            age = _days_since(lc)
            if age is not None and age > days:
                stale.append({
                    "id":           dev.id,
                    "name":         dev.name,
                    "days_since_change": round(age, 1),
                    "last_changed": str(lc) if lc else None,
                    "plugin_id":    dev.pluginId,
                })
        stale.sort(key=lambda x: x["days_since_change"], reverse=True)
        return stale

    # ────────────────────────────────────────────────────────────────────────
    # audit_variables
    # ────────────────────────────────────────────────────────────────────────

    def audit_variables(self) -> Dict[str, Any]:
        """
        Report variables that appear unused: not referenced in any Python script.
        Also flags variables whose value is empty, None, or the literal string 'null'.
        """
        self.log_incoming_request("audit_variables", {})
        try:
            scripts_dir = _scripts_dir()
            id_map      = _scan_scripts_for_ids(scripts_dir)

            unused   = []
            problematic = []

            for vid in indigo.variables:
                v   = indigo.variables[vid]
                val = str(v.value).strip().lower()

                in_scripts = id_map.get(v.id, [])

                if not in_scripts:
                    unused.append({
                        "id":    v.id,
                        "name":  v.name,
                        "value": v.value,
                    })

                if val in ("", "none", "null") and not v.readOnly:
                    problematic.append({
                        "id":    v.id,
                        "name":  v.name,
                        "value": v.value,
                        "issue": "empty/null value",
                    })

            result = {
                "success":              True,
                "total_variables":      len(list(indigo.variables)),
                "unreferenced_in_scripts": len(unused),
                "problematic_count":    len(problematic),
                "note": (
                    "unreferenced means not found in Python Scripts folder. "
                    "Variables may still be used by triggers/action groups."
                ),
                "unreferenced": unused,
                "problematic":  problematic,
            }
            self.log_tool_outcome("audit_variables", True,
                                  f"{len(unused)} unreferenced, {len(problematic)} problematic")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "audit_variables")

    # ────────────────────────────────────────────────────────────────────────
    # dependency_map
    # ────────────────────────────────────────────────────────────────────────

    # ────────────────────────────────────────────────────────────────────────
    # find_conflicts
    # ────────────────────────────────────────────────────────────────────────

    def find_conflicts(self) -> Dict[str, Any]:
        """
        Detect configuration conflicts in Indigo.

        Device conflicts:
          - Duplicate device names (two devices with the same name)
          - Multiple devices sharing the same hardware address

        Automation conflicts:
          - Triggers with duplicate names
          - Python scripts referencing IDs that belong to no device or variable
            (orphaned references — the device/variable was likely deleted)
          - Multiple scripts writing to the same variable ID via updateValue()
            (potential race condition)
        """
        self.log_incoming_request("find_conflicts", {})
        try:
            # ── Collect all device IDs / variable IDs ─────────────────────
            all_dev_ids = {indigo.devices[d].id for d in indigo.devices}
            all_var_ids = {indigo.variables[v].id for v in indigo.variables}
            all_known   = all_dev_ids | all_var_ids

            # ── Device: duplicate names ────────────────────────────────────
            name_map: Dict[str, List] = {}
            addr_map: Dict[str, List] = {}
            for did in indigo.devices:
                dev = indigo.devices[did]
                name_map.setdefault(dev.name.lower(), []).append(
                    {"id": dev.id, "name": dev.name, "enabled": dev.enabled}
                )
                addr = getattr(dev, "address", "").strip()
                if addr:
                    addr_map.setdefault(addr, []).append(
                        {"id": dev.id, "name": dev.name, "address": addr}
                    )

            duplicate_names = [
                {"name": devs[0]["name"], "devices": devs}
                for devs in name_map.values() if len(devs) > 1
            ]
            shared_addresses = [
                {"address": addr, "devices": devs}
                for addr, devs in addr_map.items() if len(devs) > 1
            ]

            # ── Automation: duplicate trigger names ────────────────────────
            trig_name_map: Dict[str, List] = {}
            for tid in indigo.triggers:
                t = indigo.triggers[tid]
                trig_name_map.setdefault(t.name.lower(), []).append(
                    {"id": t.id, "name": t.name, "enabled": t.enabled}
                )
            duplicate_trigger_names = [
                {"name": trigs[0]["name"], "triggers": trigs}
                for trigs in trig_name_map.values() if len(trigs) > 1
            ]

            # ── Script analysis ────────────────────────────────────────────
            scripts_dir = _scripts_dir()
            id_map      = _scan_scripts_for_ids(scripts_dir)

            # Orphaned: IDs in scripts that aren't any device or variable
            orphaned_refs = [
                {"id": iid, "scripts": scripts,
                 "note": "ID in scripts but no matching device or variable"}
                for iid, scripts in id_map.items()
                if iid not in all_known
            ]

            # Write conflicts: multiple scripts calling updateValue(SAME_VAR_ID)
            write_map: Dict[int, List[str]] = {}
            write_pat = re.compile(r"updateValue\s*\(\s*(\d{8,12})\s*[,)]")
            if os.path.isdir(scripts_dir):
                for entry in os.scandir(scripts_dir):
                    if not (entry.name.endswith(".py") and entry.is_file()):
                        continue
                    try:
                        with open(entry.path, "r", encoding="utf-8",
                                  errors="replace") as fh:
                            content = fh.read()
                        for m in write_pat.findall(content):
                            iid = int(m)
                            if iid in all_var_ids:
                                write_map.setdefault(iid, [])
                                if entry.name not in write_map[iid]:
                                    write_map[iid].append(entry.name)
                    except OSError:
                        pass

            write_conflicts = []
            for var_id, scripts in write_map.items():
                if len(scripts) > 1:
                    vname = ""
                    try:
                        vname = indigo.variables[var_id].name
                    except Exception:
                        pass
                    write_conflicts.append({
                        "variable_id":   var_id,
                        "variable_name": vname,
                        "scripts":       scripts,
                        "note": "Multiple scripts write to this variable — potential race condition",
                    })

            total_conflicts = (len(duplicate_names) + len(shared_addresses)
                               + len(duplicate_trigger_names)
                               + len(orphaned_refs) + len(write_conflicts))

            result = {
                "success": True,
                "summary": {
                    "duplicate_device_names":   len(duplicate_names),
                    "shared_device_addresses":  len(shared_addresses),
                    "duplicate_trigger_names":  len(duplicate_trigger_names),
                    "orphaned_script_refs":     len(orphaned_refs),
                    "variable_write_conflicts": len(write_conflicts),
                    "total_conflicts":          total_conflicts,
                },
                "device_conflicts": {
                    "duplicate_names":  duplicate_names[:20],
                    "shared_addresses": shared_addresses[:20],
                },
                "automation_conflicts": {
                    "duplicate_trigger_names":  duplicate_trigger_names[:20],
                    "orphaned_script_refs":     orphaned_refs[:30],
                    "variable_write_conflicts": write_conflicts[:20],
                },
            }
            self.log_tool_outcome("find_conflicts", True,
                                  f"{total_conflicts} potential conflicts found")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_conflicts")

    def dependency_map(self, entity_id: Union[int, str]) -> Dict[str, Any]:
        """
        Build a dependency map for a device or variable.
        Returns which Python scripts reference it by numeric ID.
        Also returns all triggers and action groups (names only — the Indigo
        API does not expose their internal conditions or action steps, so
        content-level filtering is not possible).
        """
        self.log_incoming_request("dependency_map", {"entity_id": entity_id})
        try:
            # Resolve ID and name
            eid   = None
            ename = str(entity_id)
            entity_type = "unknown"

            try:
                eid = int(entity_id)
            except (ValueError, TypeError):
                pass

            # Try device
            dev = None
            if eid and eid in indigo.devices:
                dev = indigo.devices[eid]
                eid, ename, entity_type = dev.id, dev.name, "device"
            elif str(entity_id) in indigo.devices:
                dev = indigo.devices[str(entity_id)]
                eid, ename, entity_type = dev.id, dev.name, "device"

            # Try variable
            var = None
            if entity_type == "unknown":
                if eid and eid in indigo.variables:
                    var = indigo.variables[eid]
                    eid, ename, entity_type = var.id, var.name, "variable"
                elif str(entity_id) in indigo.variables:
                    var = indigo.variables[str(entity_id)]
                    eid, ename, entity_type = var.id, var.name, "variable"

            if entity_type == "unknown":
                return {"success": False,
                        "error": f"No device or variable found matching '{entity_id}'"}

            # Scan scripts
            scripts_dir  = _scripts_dir()
            id_map       = _scan_scripts_for_ids(scripts_dir)
            scripts_refs = id_map.get(eid, [])

            # List all triggers and action groups (content not accessible via API)
            all_triggers = [
                {"id": indigo.triggers[t].id, "name": indigo.triggers[t].name,
                 "enabled": indigo.triggers[t].enabled}
                for t in indigo.triggers
            ]
            all_ags = [
                {"id": indigo.actionGroups[a].id, "name": indigo.actionGroups[a].name}
                for a in indigo.actionGroups
            ]

            result = {
                "success":      True,
                "entity_id":    eid,
                "entity_name":  ename,
                "entity_type":  entity_type,
                "script_references": {
                    "count":   len(scripts_refs),
                    "scripts": scripts_refs,
                },
                "api_limitation": (
                    "Indigo's Python API does not expose trigger conditions or "
                    "action group steps — content-level dependency mapping is not "
                    "possible. The lists below show ALL triggers and action groups; "
                    "manual inspection is needed to find which ones reference this entity."
                ),
                "all_triggers":      all_triggers,
                "all_action_groups": all_ags,
            }
            self.log_tool_outcome("dependency_map", True,
                                  f"{len(scripts_refs)} script refs for '{ename}'")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "dependency_map")
