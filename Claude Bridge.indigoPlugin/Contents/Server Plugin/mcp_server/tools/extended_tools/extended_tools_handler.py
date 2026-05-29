#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    extended_tools_handler.py
# Description: IOM-wrapping tools that fill the gaps in Claude Bridge's original
#              tool surface. Devices (CRUD + folder moves), variables (delete +
#              move), schedules (delete/duplicate/execute_now/etc), triggers,
#              action groups, sprinklers, thermostat fan mode, speed control,
#              server tools (speak/sunrise/sunset/getDeprecatedElems/etc),
#              control pages and a cross-plugin update checker.
# Author:      CliveS & Claude Opus 4.7
# Date:        27-05-2026
# Version:     1.0
#
# Each method returns a dict shaped {"success": bool, ...}. The dispatch layer
# in mcp_handler.py wraps these with safe_json_dumps. Every method follows the
# same pattern used by system_tools_handler.py — try/except, structured result
# and log_tool_outcome on success — so logs match the rest of the plugin.

import logging
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider


# ── ID coercion helper ──────────────────────────────────────────────────────

def _coerce_id(value) -> int:
    """Accept int or str (numeric) and return int. Raises ValueError otherwise."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(f"Expected numeric ID, got {value!r}")


class ExtendedToolsHandler(BaseToolHandler):
    """All the IOM wrappers added in v2.5.0."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="extended_tools", logger=logger)
        self.data_provider = data_provider

    # ════════════════════════════════════════════════════════════════════════
    # Device CRUD + folder operations
    # ════════════════════════════════════════════════════════════════════════

    def delete_device(self, device_id) -> Dict[str, Any]:
        """Permanently delete a device. Cannot be undone."""
        self.log_incoming_request("delete_device", {"device_id": device_id})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            name = dev.name
            indigo.device.delete(did)
            msg = f"Deleted device '{name}' (ID {did})"
            self.log_tool_outcome("delete_device", True, msg)
            return {"success": True, "device_id": did, "name": name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "delete_device")

    def duplicate_device(self, device_id, new_name: Optional[str] = None) -> Dict[str, Any]:
        """Duplicate a device. If new_name omitted, Indigo uses 'Copy of <name>'."""
        self.log_incoming_request("duplicate_device", {"device_id": device_id, "new_name": new_name})
        try:
            did = _coerce_id(device_id)
            kwargs = {"duplicateName": new_name} if new_name else {}
            new_dev = indigo.device.duplicate(did, **kwargs)
            msg = f"Duplicated device {did} → '{new_dev.name}' (ID {new_dev.id})"
            self.log_tool_outcome("duplicate_device", True, msg)
            return {"success": True, "source_id": did,
                    "new_device_id": new_dev.id, "name": new_dev.name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "duplicate_device")

    def move_device_to_folder(self, device_id, folder_id) -> Dict[str, Any]:
        """Move a device to a different folder. folder_id=0 means root."""
        self.log_incoming_request("move_device_to_folder",
                                  {"device_id": device_id, "folder_id": folder_id})
        try:
            did = _coerce_id(device_id)
            fid = _coerce_id(folder_id)
            dev = indigo.devices[did]
            indigo.device.moveToFolder(did, value=fid)
            msg = f"Moved device '{dev.name}' to folder {fid}"
            self.log_tool_outcome("move_device_to_folder", True, msg)
            return {"success": True, "device_id": did, "folder_id": fid, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "move_device_to_folder")

    def enable_device(self, device_id, value: bool = True) -> Dict[str, Any]:
        """Enable or disable a device's communication. NOT the same as on/off."""
        self.log_incoming_request("enable_device", {"device_id": device_id, "value": value})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            indigo.device.enable(did, value=bool(value))
            msg = f"{'Enabled' if value else 'Disabled'} device '{dev.name}'"
            self.log_tool_outcome("enable_device", True, msg)
            return {"success": True, "device_id": did, "enabled": bool(value), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "enable_device")

    def rename_device(self, device_id, new_name: str) -> Dict[str, Any]:
        """Rename a device. Uses dev.name = ... + replaceOnServer()."""
        self.log_incoming_request("rename_device",
                                  {"device_id": device_id, "new_name": new_name})
        try:
            did = _coerce_id(device_id)
            new_name = (new_name or "").strip()
            if not new_name:
                return {"success": False, "error": "new_name is required"}
            dev = indigo.devices[did]
            old_name = dev.name
            dev.name = new_name
            dev.replaceOnServer()
            msg = f"Renamed device {did}: '{old_name}' → '{new_name}'"
            self.log_tool_outcome("rename_device", True, msg)
            return {"success": True, "device_id": did,
                    "old_name": old_name, "new_name": new_name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "rename_device")

    def device_toggle(self, device_id) -> Dict[str, Any]:
        """Toggle on/off state. Auto-detects dimmer vs relay vs speedcontrol."""
        self.log_incoming_request("device_toggle", {"device_id": device_id})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if isinstance(dev, indigo.DimmerDevice):
                indigo.dimmer.toggle(did)
                kind = "dimmer"
            elif isinstance(dev, indigo.RelayDevice):
                indigo.relay.toggle(did)
                kind = "relay"
            elif isinstance(dev, indigo.SpeedControlDevice):
                indigo.speedcontrol.toggle(did)
                kind = "speedcontrol"
            else:
                return {"success": False,
                        "error": f"Device '{dev.name}' is not toggleable "
                                 f"({type(dev).__name__})"}
            msg = f"Toggled {kind} '{dev.name}'"
            self.log_tool_outcome("device_toggle", True, msg)
            return {"success": True, "device_id": did, "kind": kind, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "device_toggle")

    def dimmer_brighten_by(self, device_id, amount: int) -> Dict[str, Any]:
        """Increase brightness by N percent. Clamps at 100."""
        self.log_incoming_request("dimmer_brighten_by",
                                  {"device_id": device_id, "amount": amount})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.DimmerDevice):
                return {"success": False, "error": f"'{dev.name}' is not a dimmer"}
            indigo.dimmer.brightenBy(did, value=int(amount))
            msg = f"Brightened '{dev.name}' by {amount}%"
            self.log_tool_outcome("dimmer_brighten_by", True, msg)
            return {"success": True, "device_id": did, "amount": int(amount), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "dimmer_brighten_by")

    def dimmer_dim_by(self, device_id, amount: int) -> Dict[str, Any]:
        """Decrease brightness by N percent. Clamps at 0."""
        self.log_incoming_request("dimmer_dim_by",
                                  {"device_id": device_id, "amount": amount})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.DimmerDevice):
                return {"success": False, "error": f"'{dev.name}' is not a dimmer"}
            indigo.dimmer.dimBy(did, value=int(amount))
            msg = f"Dimmed '{dev.name}' by {amount}%"
            self.log_tool_outcome("dimmer_dim_by", True, msg)
            return {"success": True, "device_id": did, "amount": int(amount), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "dimmer_dim_by")

    # ════════════════════════════════════════════════════════════════════════
    # Variable gaps
    # ════════════════════════════════════════════════════════════════════════

    def variable_delete(self, variable_id) -> Dict[str, Any]:
        """Permanently delete a variable. Cannot be undone."""
        self.log_incoming_request("variable_delete", {"variable_id": variable_id})
        try:
            vid = _coerce_id(variable_id)
            var = indigo.variables[vid]
            name = var.name
            indigo.variable.delete(vid)
            msg = f"Deleted variable '{name}' (ID {vid})"
            self.log_tool_outcome("variable_delete", True, msg)
            return {"success": True, "variable_id": vid, "name": name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "variable_delete")

    def variable_move_to_folder(self, variable_id, folder_id) -> Dict[str, Any]:
        """Move a variable to a different folder. folder_id=0 means root."""
        self.log_incoming_request("variable_move_to_folder",
                                  {"variable_id": variable_id, "folder_id": folder_id})
        try:
            vid = _coerce_id(variable_id)
            fid = _coerce_id(folder_id)
            var = indigo.variables[vid]
            indigo.variable.moveToFolder(vid, value=fid)
            msg = f"Moved variable '{var.name}' to folder {fid}"
            self.log_tool_outcome("variable_move_to_folder", True, msg)
            return {"success": True, "variable_id": vid, "folder_id": fid, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "variable_move_to_folder")

    # ════════════════════════════════════════════════════════════════════════
    # Schedule CRUD (no create — Indigo schedule definitions are GUI-authored)
    # ════════════════════════════════════════════════════════════════════════

    def delete_schedule(self, schedule_id) -> Dict[str, Any]:
        """Permanently delete a schedule."""
        self.log_incoming_request("delete_schedule", {"schedule_id": schedule_id})
        try:
            sid = _coerce_id(schedule_id)
            sched = indigo.schedules[sid]
            name = sched.name
            indigo.schedule.delete(sid)
            msg = f"Deleted schedule '{name}' (ID {sid})"
            self.log_tool_outcome("delete_schedule", True, msg)
            return {"success": True, "schedule_id": sid, "name": name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "delete_schedule")

    def duplicate_schedule(self, schedule_id, new_name: Optional[str] = None) -> Dict[str, Any]:
        """Duplicate a schedule. If new_name omitted, Indigo uses 'Copy of <name>'."""
        self.log_incoming_request("duplicate_schedule",
                                  {"schedule_id": schedule_id, "new_name": new_name})
        try:
            sid = _coerce_id(schedule_id)
            kwargs = {"duplicateName": new_name} if new_name else {}
            new_sched = indigo.schedule.duplicate(sid, **kwargs)
            msg = f"Duplicated schedule {sid} → '{new_sched.name}' (ID {new_sched.id})"
            self.log_tool_outcome("duplicate_schedule", True, msg)
            return {"success": True, "source_id": sid,
                    "new_schedule_id": new_sched.id, "name": new_sched.name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "duplicate_schedule")

    def execute_schedule_now(self, schedule_id, ignore_conditions: bool = False) -> Dict[str, Any]:
        """Execute a schedule immediately. ignore_conditions=True bypasses its conditions."""
        self.log_incoming_request("execute_schedule_now",
                                  {"schedule_id": schedule_id, "ignore_conditions": ignore_conditions})
        try:
            sid = _coerce_id(schedule_id)
            sched = indigo.schedules[sid]
            indigo.schedule.execute(sid, ignoreConditions=bool(ignore_conditions))
            msg = (f"Executed schedule '{sched.name}'"
                   f"{' (conditions bypassed)' if ignore_conditions else ''}")
            self.log_tool_outcome("execute_schedule_now", True, msg)
            return {"success": True, "schedule_id": sid,
                    "ignore_conditions": bool(ignore_conditions), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "execute_schedule_now")

    def schedule_remove_delayed_actions(self, schedule_id) -> Dict[str, Any]:
        """Remove any pending delayed actions for a schedule."""
        self.log_incoming_request("schedule_remove_delayed_actions",
                                  {"schedule_id": schedule_id})
        try:
            sid = _coerce_id(schedule_id)
            sched = indigo.schedules[sid]
            indigo.schedule.removeDelayedActions(sid)
            msg = f"Removed delayed actions for schedule '{sched.name}'"
            self.log_tool_outcome("schedule_remove_delayed_actions", True, msg)
            return {"success": True, "schedule_id": sid, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "schedule_remove_delayed_actions")

    def schedule_get_dependencies(self, schedule_id) -> Dict[str, Any]:
        """Return the indigo.Dict of dependents for a schedule, as a plain dict."""
        self.log_incoming_request("schedule_get_dependencies", {"schedule_id": schedule_id})
        try:
            sid = _coerce_id(schedule_id)
            deps = indigo.schedule.getDependencies(sid)
            # indigo.Dict converts cleanly via dict(...)
            deps_dict = dict(deps) if deps else {}
            return {"success": True, "schedule_id": sid, "dependencies": deps_dict}
        except Exception as exc:
            return self.handle_exception(exc, "schedule_get_dependencies")

    # ════════════════════════════════════════════════════════════════════════
    # Trigger CRUD
    # ════════════════════════════════════════════════════════════════════════

    def delete_trigger(self, trigger_id) -> Dict[str, Any]:
        """Permanently delete a trigger."""
        self.log_incoming_request("delete_trigger", {"trigger_id": trigger_id})
        try:
            tid = _coerce_id(trigger_id)
            trig = indigo.triggers[tid]
            name = trig.name
            indigo.trigger.delete(tid)
            msg = f"Deleted trigger '{name}' (ID {tid})"
            self.log_tool_outcome("delete_trigger", True, msg)
            return {"success": True, "trigger_id": tid, "name": name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "delete_trigger")

    def move_trigger_to_folder(self, trigger_id, folder_id) -> Dict[str, Any]:
        """Move a trigger to a different folder. folder_id=0 means root."""
        self.log_incoming_request("move_trigger_to_folder",
                                  {"trigger_id": trigger_id, "folder_id": folder_id})
        try:
            tid = _coerce_id(trigger_id)
            fid = _coerce_id(folder_id)
            trig = indigo.triggers[tid]
            indigo.trigger.moveToFolder(tid, value=fid)
            msg = f"Moved trigger '{trig.name}' to folder {fid}"
            self.log_tool_outcome("move_trigger_to_folder", True, msg)
            return {"success": True, "trigger_id": tid, "folder_id": fid, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "move_trigger_to_folder")

    # ════════════════════════════════════════════════════════════════════════
    # Action Group CRUD
    # ════════════════════════════════════════════════════════════════════════

    def delete_action_group(self, action_group_id) -> Dict[str, Any]:
        """Permanently delete an action group."""
        self.log_incoming_request("delete_action_group", {"action_group_id": action_group_id})
        try:
            aid = _coerce_id(action_group_id)
            ag = indigo.actionGroups[aid]
            name = ag.name
            indigo.actionGroup.delete(aid)
            msg = f"Deleted action group '{name}' (ID {aid})"
            self.log_tool_outcome("delete_action_group", True, msg)
            return {"success": True, "action_group_id": aid, "name": name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "delete_action_group")

    def duplicate_action_group(self, action_group_id,
                               new_name: Optional[str] = None) -> Dict[str, Any]:
        """Duplicate an action group."""
        self.log_incoming_request("duplicate_action_group",
                                  {"action_group_id": action_group_id, "new_name": new_name})
        try:
            aid = _coerce_id(action_group_id)
            kwargs = {"duplicateName": new_name} if new_name else {}
            new_ag = indigo.actionGroup.duplicate(aid, **kwargs)
            msg = f"Duplicated action group {aid} → '{new_ag.name}' (ID {new_ag.id})"
            self.log_tool_outcome("duplicate_action_group", True, msg)
            return {"success": True, "source_id": aid,
                    "new_action_group_id": new_ag.id, "name": new_ag.name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "duplicate_action_group")

    def enable_action_group(self, action_group_id, value: bool = True) -> Dict[str, Any]:
        """Enable or disable an action group."""
        self.log_incoming_request("enable_action_group",
                                  {"action_group_id": action_group_id, "value": value})
        try:
            aid = _coerce_id(action_group_id)
            ag = indigo.actionGroups[aid]
            indigo.actionGroup.enable(aid, value=bool(value))
            msg = f"{'Enabled' if value else 'Disabled'} action group '{ag.name}'"
            self.log_tool_outcome("enable_action_group", True, msg)
            return {"success": True, "action_group_id": aid,
                    "enabled": bool(value), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "enable_action_group")

    def disable_action_group(self, action_group_id) -> Dict[str, Any]:
        """Disable an action group (convenience for enable_action_group value=False)."""
        return self.enable_action_group(action_group_id, value=False)

    def action_group_get_dependencies(self, action_group_id) -> Dict[str, Any]:
        """Return the dependents of an action group as a plain dict."""
        self.log_incoming_request("action_group_get_dependencies",
                                  {"action_group_id": action_group_id})
        try:
            aid = _coerce_id(action_group_id)
            deps = indigo.actionGroup.getDependencies(aid)
            deps_dict = dict(deps) if deps else {}
            return {"success": True, "action_group_id": aid, "dependencies": deps_dict}
        except Exception as exc:
            return self.handle_exception(exc, "action_group_get_dependencies")

    # ════════════════════════════════════════════════════════════════════════
    # Sprinkler suite
    # ════════════════════════════════════════════════════════════════════════

    def sprinkler_set_zone(self, device_id, zone_index: int) -> Dict[str, Any]:
        """Set the active zone on a sprinkler device (1-based index)."""
        self.log_incoming_request("sprinkler_set_zone",
                                  {"device_id": device_id, "zone_index": zone_index})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.SprinklerDevice):
                return {"success": False, "error": f"'{dev.name}' is not a sprinkler"}
            indigo.sprinkler.setActiveZone(did, index=int(zone_index))
            msg = f"Set sprinkler '{dev.name}' to zone {zone_index}"
            self.log_tool_outcome("sprinkler_set_zone", True, msg)
            return {"success": True, "device_id": did,
                    "zone_index": int(zone_index), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "sprinkler_set_zone")

    def _sprinkler_simple(self, device_id, action_name: str, indigo_fn) -> Dict[str, Any]:
        """Shared shape for sprinkler run/stop/pause/resume/next/prev."""
        self.log_incoming_request(f"sprinkler_{action_name}", {"device_id": device_id})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.SprinklerDevice):
                return {"success": False, "error": f"'{dev.name}' is not a sprinkler"}
            indigo_fn(did)
            msg = f"Sprinkler '{dev.name}': {action_name}"
            self.log_tool_outcome(f"sprinkler_{action_name}", True, msg)
            return {"success": True, "device_id": did, "action": action_name, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, f"sprinkler_{action_name}")

    def sprinkler_run(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "run", indigo.sprinkler.run)

    def sprinkler_stop(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "stop", indigo.sprinkler.stop)

    def sprinkler_pause(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "pause", indigo.sprinkler.pause)

    def sprinkler_resume(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "resume", indigo.sprinkler.resume)

    def sprinkler_next_zone(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "next_zone", indigo.sprinkler.nextZone)

    def sprinkler_previous_zone(self, device_id) -> Dict[str, Any]:
        return self._sprinkler_simple(device_id, "previous_zone", indigo.sprinkler.previousZone)

    # ════════════════════════════════════════════════════════════════════════
    # Thermostat fan mode
    # ════════════════════════════════════════════════════════════════════════

    def set_fan_mode(self, device_id, mode: str) -> Dict[str, Any]:
        """Set the fan mode on a thermostat. mode ∈ {auto, alwaysOn}."""
        self.log_incoming_request("set_fan_mode", {"device_id": device_id, "mode": mode})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.ThermostatDevice):
                return {"success": False, "error": f"'{dev.name}' is not a thermostat"}
            mode_map = {
                "auto":     indigo.kFanMode.Auto,
                "alwayson": indigo.kFanMode.AlwaysOn,
                "always_on": indigo.kFanMode.AlwaysOn,
            }
            key = (mode or "").strip().lower()
            if key not in mode_map:
                return {"success": False,
                        "error": f"Unknown fan mode '{mode}'. Use 'auto' or 'alwaysOn'."}
            indigo.thermostat.setFanMode(did, value=mode_map[key])
            msg = f"Set fan mode on '{dev.name}' to {mode}"
            self.log_tool_outcome("set_fan_mode", True, msg)
            return {"success": True, "device_id": did, "mode": mode, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "set_fan_mode")

    # ════════════════════════════════════════════════════════════════════════
    # Speed control
    # ════════════════════════════════════════════════════════════════════════

    def speedcontrol_set_index(self, device_id, index: int) -> Dict[str, Any]:
        """Set the speed index on a speed-control device (e.g. 0=off, 1=low, 2=med, 3=high)."""
        self.log_incoming_request("speedcontrol_set_index",
                                  {"device_id": device_id, "index": index})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.SpeedControlDevice):
                return {"success": False,
                        "error": f"'{dev.name}' is not a speed control device"}
            indigo.speedcontrol.setSpeedIndex(did, value=int(index))
            msg = f"Set '{dev.name}' speed index to {index}"
            self.log_tool_outcome("speedcontrol_set_index", True, msg)
            return {"success": True, "device_id": did, "index": int(index), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "speedcontrol_set_index")

    def speedcontrol_increase(self, device_id) -> Dict[str, Any]:
        """Increase the speed index by one."""
        self.log_incoming_request("speedcontrol_increase", {"device_id": device_id})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.SpeedControlDevice):
                return {"success": False,
                        "error": f"'{dev.name}' is not a speed control device"}
            indigo.speedcontrol.increaseSpeedIndex(did)
            msg = f"Increased speed index on '{dev.name}'"
            self.log_tool_outcome("speedcontrol_increase", True, msg)
            return {"success": True, "device_id": did, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "speedcontrol_increase")

    def speedcontrol_decrease(self, device_id) -> Dict[str, Any]:
        """Decrease the speed index by one."""
        self.log_incoming_request("speedcontrol_decrease", {"device_id": device_id})
        try:
            did = _coerce_id(device_id)
            dev = indigo.devices[did]
            if not isinstance(dev, indigo.SpeedControlDevice):
                return {"success": False,
                        "error": f"'{dev.name}' is not a speed control device"}
            indigo.speedcontrol.decreaseSpeedIndex(did)
            msg = f"Decreased speed index on '{dev.name}'"
            self.log_tool_outcome("speedcontrol_decrease", True, msg)
            return {"success": True, "device_id": did, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "speedcontrol_decrease")

    # ════════════════════════════════════════════════════════════════════════
    # Server-level tools
    # ════════════════════════════════════════════════════════════════════════

    def server_speak(self, text: str, wait: bool = False) -> Dict[str, Any]:
        """Speak text through the Indigo server (macOS text-to-speech)."""
        self.log_incoming_request("server_speak", {"text_len": len(text or ""), "wait": wait})
        try:
            text = (text or "").strip()
            if not text:
                return {"success": False, "error": "text is required"}
            indigo.server.speak(text, waitUntilDone=bool(wait))
            msg = f"Spoke {len(text)} chars"
            self.log_tool_outcome("server_speak", True, msg)
            return {"success": True, "chars": len(text), "wait": bool(wait), "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "server_speak")

    def calculate_sunrise(self, date_iso: Optional[str] = None) -> Dict[str, Any]:
        """Sunrise for today or a given YYYY-MM-DD date."""
        self.log_incoming_request("calculate_sunrise", {"date_iso": date_iso})
        try:
            if date_iso:
                from datetime import datetime as _dt
                d = _dt.fromisoformat(date_iso)
                t = indigo.server.calculateSunrise(d)
            else:
                t = indigo.server.calculateSunrise()
            return {"success": True, "sunrise": t.isoformat() if t else None,
                    "date": date_iso or "today"}
        except Exception as exc:
            return self.handle_exception(exc, "calculate_sunrise")

    def calculate_sunset(self, date_iso: Optional[str] = None) -> Dict[str, Any]:
        """Sunset for today or a given YYYY-MM-DD date."""
        self.log_incoming_request("calculate_sunset", {"date_iso": date_iso})
        try:
            if date_iso:
                from datetime import datetime as _dt
                d = _dt.fromisoformat(date_iso)
                t = indigo.server.calculateSunset(d)
            else:
                t = indigo.server.calculateSunset()
            return {"success": True, "sunset": t.isoformat() if t else None,
                    "date": date_iso or "today"}
        except Exception as exc:
            return self.handle_exception(exc, "calculate_sunset")

    def get_latitude_longitude(self) -> Dict[str, Any]:
        """Return (latitude, longitude) configured in Indigo prefs."""
        self.log_incoming_request("get_latitude_longitude", {})
        try:
            lat, lon = indigo.server.getLatitudeAndLongitude()
            return {"success": True, "latitude": lat, "longitude": lon}
        except Exception as exc:
            return self.handle_exception(exc, "get_latitude_longitude")

    def get_web_server_url(self) -> Dict[str, Any]:
        """Return the local Indigo web server URL."""
        self.log_incoming_request("get_web_server_url", {})
        try:
            url = indigo.server.getWebServerURL() or ""
            return {"success": True, "url": url}
        except Exception as exc:
            return self.handle_exception(exc, "get_web_server_url")

    def get_deprecated_elements(self, include_warnings: bool = False) -> Dict[str, Any]:
        """Scan for deprecated objects. include_warnings=True surfaces warning-level items too."""
        self.log_incoming_request("get_deprecated_elements",
                                  {"include_warnings": include_warnings})
        try:
            result = indigo.server.getDeprecatedElems(includeWarnings=bool(include_warnings))
            # Result is an indigo.Dict — convert to plain dict for JSON serialisation
            out = {}
            if result:
                try:
                    out = dict(result)
                except Exception:
                    out = {"_raw": str(result)}
            return {"success": True, "include_warnings": bool(include_warnings),
                    "deprecated": out}
        except Exception as exc:
            return self.handle_exception(exc, "get_deprecated_elements")

    def remove_all_delayed_actions(self) -> Dict[str, Any]:
        """Remove every pending delayed action across all schedules. Destructive."""
        self.log_incoming_request("remove_all_delayed_actions", {})
        try:
            indigo.server.removeAllDelayedActions()
            msg = "Removed all pending delayed actions"
            self.log_tool_outcome("remove_all_delayed_actions", True, msg)
            return {"success": True, "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "remove_all_delayed_actions")

    # ════════════════════════════════════════════════════════════════════════
    # Control pages
    # ════════════════════════════════════════════════════════════════════════

    def list_control_pages(self) -> Dict[str, Any]:
        """List all control pages with id/name/folder/hideTabBar."""
        self.log_incoming_request("list_control_pages", {})
        try:
            pages = []
            for cp in indigo.controlPages:
                pages.append({
                    "id":              cp.id,
                    "name":            cp.name,
                    "folderId":        getattr(cp, "folderId", 0),
                    "hideTabBar":      getattr(cp, "hideTabBar", False),
                    "remoteDisplay":   getattr(cp, "displayInRemoteUI", True),
                    "description":     getattr(cp, "description", ""),
                })
            return {"success": True, "count": len(pages), "control_pages": pages}
        except Exception as exc:
            return self.handle_exception(exc, "list_control_pages")

    def get_control_page(self, page_id) -> Dict[str, Any]:
        """Return a control page's properties as a dict."""
        self.log_incoming_request("get_control_page", {"page_id": page_id})
        try:
            pid = _coerce_id(page_id)
            cp = indigo.controlPages[pid]
            data = {
                "id":            cp.id,
                "name":          cp.name,
                "folderId":      getattr(cp, "folderId", 0),
                "hideTabBar":    getattr(cp, "hideTabBar", False),
                "remoteDisplay": getattr(cp, "displayInRemoteUI", True),
                "description":   getattr(cp, "description", ""),
            }
            # Try to surface controls if the IOM exposes them on this version
            try:
                controls = []
                for ctrl in getattr(cp, "controls", []) or []:
                    controls.append({
                        "id":   getattr(ctrl, "id", None),
                        "type": type(ctrl).__name__,
                        "name": getattr(ctrl, "name", ""),
                    })
                data["controls"] = controls
            except Exception:
                data["controls"] = "unavailable on this Indigo version"
            return {"success": True, "control_page": data}
        except Exception as exc:
            return self.handle_exception(exc, "get_control_page")

    # ════════════════════════════════════════════════════════════════════════
    # Plugin updates — cross-plugin sweep
    # ════════════════════════════════════════════════════════════════════════

    def check_plugin_updates(self) -> Dict[str, Any]:
        """
        Walk every installed plugin via indigo.server.getPluginList() and report
        compatibleUpdateAvailable / latestCompatibleVers in one call. Saves the
        per-plugin round-trips that get_plugin_status would need.
        """
        self.log_incoming_request("check_plugin_updates", {})
        try:
            results: List[Dict[str, Any]] = []
            # getPluginList() returns PluginInfo objects, not id strings — use them
            # directly. Passing one back into getPlugin() raised a
            # getPlugin(PluginInfo) signature mismatch and serialised plugin_id as {}.
            plugins = indigo.server.getPluginList() or []
            for p in plugins:
                try:
                    if p is None:
                        continue
                    pid = getattr(p, "pluginId", "")
                    results.append({
                        "plugin_id":             pid,
                        "display_name":          getattr(p, "pluginDisplayName", pid),
                        "current_version":       getattr(p, "pluginVersion", None),
                        "latest_compatible":     getattr(p, "latestCompatibleVers", None),
                        "latest_any":            getattr(p, "latestVers", None),
                        "update_available":      bool(getattr(p, "compatibleUpdateAvailable", False)),
                        "incompatible_update":   bool(getattr(p, "incompatibleUpdateAvailable", False)),
                        "is_enabled":            bool(p.isEnabled()) if hasattr(p, "isEnabled") else None,
                        "is_running":            bool(p.isRunning()) if hasattr(p, "isRunning") else None,
                        "included_with_server":  bool(getattr(p, "includedWithServer", False)),
                        "download_url":          getattr(p, "latestCompatibleDownloadURL", ""),
                    })
                except Exception as inner:
                    results.append({"plugin_id": pid, "error": str(inner)})
            updates = [r for r in results if r.get("update_available")]
            return {
                "success":           True,
                "plugin_count":      len(results),
                "updates_available": len(updates),
                "updates":           updates,
                "all_plugins":       results,
            }
        except Exception as exc:
            return self.handle_exception(exc, "check_plugin_updates")
