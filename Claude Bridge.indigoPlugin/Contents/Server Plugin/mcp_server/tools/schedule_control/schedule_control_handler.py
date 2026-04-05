"""
Schedule and trigger control handler for ClaudeBridge MCP server.

Tools:
  - list_schedules     : list all Indigo schedules with enabled state
  - enable_schedule    : enable a schedule by ID or name
  - disable_schedule   : disable a schedule by ID or name
  - list_triggers      : list all Indigo triggers with enabled state and type
  - enable_trigger     : enable a trigger by ID or name
  - disable_trigger    : disable a trigger by ID or name
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider


def _schedule_to_dict(s) -> Dict[str, Any]:
    """Convert an Indigo schedule object to a plain dict."""
    d: Dict[str, Any] = {
        "id":      s.id,
        "name":    s.name,
        "enabled": s.enabled,
    }
    # nextExecution may not exist on all schedule types
    try:
        nxt = s.nextExecution
        d["next_execution"] = str(nxt) if nxt else None
    except AttributeError:
        d["next_execution"] = None
    try:
        d["folder_id"] = s.folderId
    except AttributeError:
        pass
    return d


def _trigger_to_dict(t) -> Dict[str, Any]:
    """Convert an Indigo trigger object to a plain dict."""
    d: Dict[str, Any] = {
        "id":      t.id,
        "name":    t.name,
        "enabled": t.enabled,
    }
    try:
        d["plugin_id"]      = t.pluginId
        d["plugin_type_id"] = t.pluginTypeId
    except AttributeError:
        pass
    try:
        d["folder_id"] = t.folderId
    except AttributeError:
        pass
    return d


def _resolve_schedule(id_or_name: Union[int, str]):
    """Return an Indigo schedule object by numeric ID or name, or None."""
    try:
        sid = int(id_or_name)
        if sid in indigo.schedules:
            return indigo.schedules[sid]
    except (ValueError, TypeError):
        pass
    # Name lookup (case-insensitive)
    name_lower = str(id_or_name).lower()
    for s in indigo.schedules:
        if indigo.schedules[s].name.lower() == name_lower:
            return indigo.schedules[s]
    return None


def _resolve_trigger(id_or_name: Union[int, str]):
    """Return an Indigo trigger object by numeric ID or name, or None."""
    try:
        tid = int(id_or_name)
        if tid in indigo.triggers:
            return indigo.triggers[tid]
    except (ValueError, TypeError):
        pass
    name_lower = str(id_or_name).lower()
    for t in indigo.triggers:
        if indigo.triggers[t].name.lower() == name_lower:
            return indigo.triggers[t]
    return None


class ScheduleControlHandler(BaseToolHandler):
    """Handler for Indigo schedule and trigger management."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="schedule_control", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # Schedules
    # ────────────────────────────────────────────────────────────────────────

    def list_schedules(self) -> Dict[str, Any]:
        """Return all Indigo schedules."""
        self.log_incoming_request("list_schedules", {})
        try:
            schedules = [_schedule_to_dict(indigo.schedules[s])
                         for s in indigo.schedules]
            schedules.sort(key=lambda x: x["name"].lower())
            result = {
                "success": True,
                "count":   len(schedules),
                "schedules": schedules,
            }
            self.log_tool_outcome("list_schedules", True,
                                  f"{len(schedules)} schedules")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "list_schedules")

    def enable_schedule(self, schedule_id: Union[int, str]) -> Dict[str, Any]:
        """Enable a schedule by ID or name."""
        self.log_incoming_request("enable_schedule", {"schedule_id": schedule_id})
        try:
            s = _resolve_schedule(schedule_id)
            if s is None:
                return {"success": False,
                        "error": f"Schedule '{schedule_id}' not found"}
            indigo.schedule.enable(s, value=True)
            result = {"success": True,
                      "message": f"Schedule '{s.name}' (ID {s.id}) enabled"}
            self.log_tool_outcome("enable_schedule", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "enable_schedule")

    def disable_schedule(self, schedule_id: Union[int, str]) -> Dict[str, Any]:
        """Disable a schedule by ID or name."""
        self.log_incoming_request("disable_schedule", {"schedule_id": schedule_id})
        try:
            s = _resolve_schedule(schedule_id)
            if s is None:
                return {"success": False,
                        "error": f"Schedule '{schedule_id}' not found"}
            indigo.schedule.enable(s, value=False)
            result = {"success": True,
                      "message": f"Schedule '{s.name}' (ID {s.id}) disabled"}
            self.log_tool_outcome("disable_schedule", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "disable_schedule")

    # ────────────────────────────────────────────────────────────────────────
    # Triggers
    # ────────────────────────────────────────────────────────────────────────

    def list_triggers(self) -> Dict[str, Any]:
        """Return all Indigo triggers."""
        self.log_incoming_request("list_triggers", {})
        try:
            triggers = [_trigger_to_dict(indigo.triggers[t])
                        for t in indigo.triggers]
            triggers.sort(key=lambda x: x["name"].lower())
            result = {
                "success":  True,
                "count":    len(triggers),
                "triggers": triggers,
            }
            self.log_tool_outcome("list_triggers", True,
                                  f"{len(triggers)} triggers")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "list_triggers")

    def enable_trigger(self, trigger_id: Union[int, str]) -> Dict[str, Any]:
        """Enable a trigger by ID or name."""
        self.log_incoming_request("enable_trigger", {"trigger_id": trigger_id})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            indigo.trigger.enable(t, value=True)
            result = {"success": True,
                      "message": f"Trigger '{t.name}' (ID {t.id}) enabled"}
            self.log_tool_outcome("enable_trigger", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "enable_trigger")

    def disable_trigger(self, trigger_id: Union[int, str]) -> Dict[str, Any]:
        """Disable a trigger by ID or name."""
        self.log_incoming_request("disable_trigger", {"trigger_id": trigger_id})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            indigo.trigger.enable(t, value=False)
            result = {"success": True,
                      "message": f"Trigger '{t.name}' (ID {t.id}) disabled"}
            self.log_tool_outcome("disable_trigger", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "disable_trigger")
