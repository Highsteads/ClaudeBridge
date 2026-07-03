"""
Schedule and trigger control handler for ClaudeBridge MCP server.

Tools:
  - list_schedules     : list all Indigo schedules with enabled state
  - enable_schedule    : enable a schedule by ID or name (optional auto-revert)
  - disable_schedule   : disable a schedule by ID or name (optional auto-revert)
  - list_triggers      : list all Indigo triggers with enabled state and type
  - enable_trigger     : enable a trigger by ID or name (optional auto-revert)
  - disable_trigger    : disable a trigger by ID or name (optional auto-revert)
  - fire_trigger       : execute a trigger directly by ID or name (indigo.trigger.execute)
  - update_trigger     : edit a trigger's name/description/event settings
  - update_schedule    : rename a schedule / edit its description
  - update_action_group: rename an action group / edit its description

Schedule TIMING attributes (timeType, absoluteTime, sunDelta, randomizeBy,
autoDelete, dateType) are READ-ONLY on live IOM instances (verified on
2025.2 — setattr raises 'the attribute "X" is read-only on this instance'),
so update_schedule deliberately offers name/description only.
"""

import logging
from typing import Any, Dict, Optional, Union

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


def _resolve_action_group(id_or_name: Union[int, str]):
    """Return an Indigo action group object by numeric ID or name, or None."""
    try:
        agid = int(id_or_name)
        if agid in indigo.actionGroups:
            return indigo.actionGroups[agid]
    except (ValueError, TypeError):
        pass
    name_lower = str(id_or_name).lower()
    for ag in indigo.actionGroups:
        if indigo.actionGroups[ag].name.lower() == name_lower:
            return indigo.actionGroups[ag]
    return None


def _enable_kwargs(value: bool,
                   delay_seconds: Optional[int],
                   duration_seconds: Optional[int]) -> Dict[str, Any]:
    """kwargs for indigo.trigger/schedule.enable() with optional timing.
    duration = seconds until the enable/disable auto-reverts; delay = seconds
    before it takes effect. Both native IOM parameters."""
    kwargs: Dict[str, Any] = {"value": value}
    if delay_seconds:
        kwargs["delay"] = int(delay_seconds)
    if duration_seconds:
        kwargs["duration"] = int(duration_seconds)
    return kwargs


def _timing_suffix(value: bool,
                   delay_seconds: Optional[int],
                   duration_seconds: Optional[int]) -> str:
    parts = []
    if delay_seconds:
        parts.append(f"in {int(delay_seconds)}s")
    if duration_seconds:
        reverts_to = "disabled" if value else "enabled"
        parts.append(f"auto-reverts to {reverts_to} after {int(duration_seconds)}s")
    return f" ({', '.join(parts)})" if parts else ""


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

    def enable_schedule(self, schedule_id: Union[int, str],
                        delay_seconds: Optional[int] = None,
                        duration_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Enable a schedule by ID or name, with optional delay/auto-revert."""
        self.log_incoming_request("enable_schedule", {"schedule_id": schedule_id})
        try:
            s = _resolve_schedule(schedule_id)
            if s is None:
                return {"success": False,
                        "error": f"Schedule '{schedule_id}' not found"}
            indigo.schedule.enable(
                s, **_enable_kwargs(True, delay_seconds, duration_seconds))
            result = {"success": True,
                      "message": (f"Schedule '{s.name}' (ID {s.id}) enabled"
                                  + _timing_suffix(True, delay_seconds,
                                                   duration_seconds))}
            self.log_tool_outcome("enable_schedule", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "enable_schedule")

    def disable_schedule(self, schedule_id: Union[int, str],
                         delay_seconds: Optional[int] = None,
                         duration_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Disable a schedule by ID or name, with optional delay/auto-revert."""
        self.log_incoming_request("disable_schedule", {"schedule_id": schedule_id})
        try:
            s = _resolve_schedule(schedule_id)
            if s is None:
                return {"success": False,
                        "error": f"Schedule '{schedule_id}' not found"}
            indigo.schedule.enable(
                s, **_enable_kwargs(False, delay_seconds, duration_seconds))
            result = {"success": True,
                      "message": (f"Schedule '{s.name}' (ID {s.id}) disabled"
                                  + _timing_suffix(False, delay_seconds,
                                                   duration_seconds))}
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

    def enable_trigger(self, trigger_id: Union[int, str],
                       delay_seconds: Optional[int] = None,
                       duration_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Enable a trigger by ID or name, with optional delay/auto-revert."""
        self.log_incoming_request("enable_trigger", {"trigger_id": trigger_id})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            indigo.trigger.enable(
                t, **_enable_kwargs(True, delay_seconds, duration_seconds))
            result = {"success": True,
                      "message": (f"Trigger '{t.name}' (ID {t.id}) enabled"
                                  + _timing_suffix(True, delay_seconds,
                                                   duration_seconds))}
            self.log_tool_outcome("enable_trigger", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "enable_trigger")

    def disable_trigger(self, trigger_id: Union[int, str],
                        delay_seconds: Optional[int] = None,
                        duration_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Disable a trigger by ID or name, with optional delay/auto-revert."""
        self.log_incoming_request("disable_trigger", {"trigger_id": trigger_id})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            indigo.trigger.enable(
                t, **_enable_kwargs(False, delay_seconds, duration_seconds))
            result = {"success": True,
                      "message": (f"Trigger '{t.name}' (ID {t.id}) disabled"
                                  + _timing_suffix(False, delay_seconds,
                                                   duration_seconds))}
            self.log_tool_outcome("disable_trigger", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "disable_trigger")

    def fire_trigger(self, trigger_id: Union[int, str]) -> Dict[str, Any]:
        """Fire a trigger by ID or name via indigo.trigger.execute()."""
        self.log_incoming_request("fire_trigger", {"trigger_id": trigger_id})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            if not t.enabled:
                return {"success": False,
                        "error": f"Trigger '{t.name}' (ID {t.id}) is disabled"}
            indigo.trigger.execute(t)
            result = {"success": True,
                      "message": f"Trigger '{t.name}' (ID {t.id}) fired",
                      "trigger_id":   t.id,
                      "trigger_name": t.name}
            self.log_tool_outcome("fire_trigger", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "fire_trigger")

    # ────────────────────────────────────────────────────────────────────────
    # Field editing (update_trigger / update_schedule / update_action_group)
    # ────────────────────────────────────────────────────────────────────────

    # Editable trigger fields: snake_case tool field -> (IOM attribute,
    # enum class name or None). The device_* fields exist only on
    # device-state-change triggers, the variable_* fields only on
    # variable-change triggers — setattr on the wrong subclass fails and is
    # surfaced as an error. enabled/folderId are deliberately absent (the
    # enable/move tools own those).
    _TRIGGER_EDIT_FIELDS = {
        "name":                 ("name", None),
        "description":          ("description", None),
        "device_id":            ("deviceId", None),
        "state_selector":       ("stateSelector", None),
        "state_selector_index": ("stateSelectorIndex", None),
        "state_change_type":    ("stateChangeType", "kStateChange"),
        "state_value":          ("stateValue", None),
        "variable_id":          ("variableId", None),
        "variable_change_type": ("variableChangeType", "kVarChange"),
        "variable_value":       ("variableValue", None),
    }
    # Schedule timing is read-only on live instances (see module docstring).
    _SCHEDULE_EDIT_FIELDS = {
        "name":        ("name", None),
        "description": ("description", None),
    }
    _ACTION_GROUP_EDIT_FIELDS = {
        "name":        ("name", None),
        "description": ("description", None),
    }

    @staticmethod
    def _to_indigo_enum(enum_name: str, value: Any):
        """'becomes_true' or 'BecomesTrue' -> indigo.kStateChange.BecomesTrue."""
        enum_cls = getattr(indigo, enum_name)
        text = str(value)
        camel = ("".join(part.capitalize() for part in text.split("_"))
                 if "_" in text or text.islower() else text)
        if not hasattr(enum_cls, camel):
            valid = sorted(n for n in dir(enum_cls) if n[:1].isupper())
            raise ValueError(
                f"Invalid {enum_name} value {value!r} — valid: {', '.join(valid)}")
        return getattr(enum_cls, camel)

    @staticmethod
    def _snapshot(elem, field_map, field_names) -> Dict[str, Any]:
        snap: Dict[str, Any] = {}
        for field in field_names:
            attr, _enum = field_map[field]
            try:
                snap[field] = str(getattr(elem, attr))
            except AttributeError:
                snap[field] = None
        return snap

    def _update_fields(self, entity_label: str, elem, collection,
                       field_map: Dict[str, Any],
                       fields: Dict[str, Any]) -> Dict[str, Any]:
        """Shared edit path: validate, snapshot, setattr, replaceOnServer,
        re-fetch, report before/after plus anything the server ignored."""
        unknown = sorted(f for f in fields if f not in field_map)
        if unknown:
            return {"success": False,
                    "error": (f"Field(s) not editable for a {entity_label}: "
                              f"{', '.join(unknown)}. Editable: "
                              f"{', '.join(sorted(field_map))}")}
        if not fields:
            return {"success": False,
                    "error": "No fields provided — pass e.g. "
                             "{\"name\": \"New name\"}"}

        # Referenced entities must exist — a typo'd id would silently
        # re-point the trigger at nothing.
        if "device_id" in fields:
            try:
                dev_id = int(fields["device_id"])
            except (ValueError, TypeError):
                return {"success": False, "error": "device_id must be numeric"}
            if dev_id not in indigo.devices:
                return {"success": False,
                        "error": f"device_id {dev_id} does not match an "
                                 f"existing device"}
            fields = dict(fields, device_id=dev_id)
        if "variable_id" in fields:
            try:
                var_id = int(fields["variable_id"])
            except (ValueError, TypeError):
                return {"success": False, "error": "variable_id must be numeric"}
            if var_id not in indigo.variables:
                return {"success": False,
                        "error": f"variable_id {var_id} does not match an "
                                 f"existing variable"}
            fields = dict(fields, variable_id=var_id)

        before = self._snapshot(elem, field_map, fields.keys())
        for field, value in fields.items():
            attr, enum_name = field_map[field]
            if enum_name is not None:
                value = self._to_indigo_enum(enum_name, value)
            try:
                setattr(elem, attr, value)
            except (AttributeError, TypeError) as exc:
                return {"success": False,
                        "error": (f"Cannot set '{field}' on this {entity_label} "
                                  f"({exc}) — device_* fields only apply to "
                                  f"device-state-change triggers, variable_* "
                                  f"fields to variable-change triggers")}
        elem.replaceOnServer()

        refreshed = collection[elem.id]
        after = self._snapshot(refreshed, field_map, fields.keys())
        not_applied = sorted(
            field for field in fields
            if before.get(field) == after.get(field)
            and str(fields[field]) != str(before.get(field)))

        result: Dict[str, Any] = {
            "success": True,
            "id": elem.id,
            "before": before,
            "after": after,
            "note": ("Field editing uses replaceOnServer(), which never "
                     "touches action steps or conditions — verify with the "
                     "matching get_*_details tool if in doubt."),
        }
        if not_applied:
            result["warning"] = (f"The server kept the old value for: "
                                 f"{', '.join(not_applied)}")
        return result

    def update_trigger(self, trigger_id: Union[int, str],
                       fields: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a trigger's name, description, or event settings."""
        self.log_incoming_request("update_trigger",
                                  {"trigger_id": trigger_id, "fields": fields})
        try:
            t = _resolve_trigger(trigger_id)
            if t is None:
                return {"success": False,
                        "error": f"Trigger '{trigger_id}' not found"}
            result = self._update_fields("trigger", t, indigo.triggers,
                                         self._TRIGGER_EDIT_FIELDS,
                                         dict(fields or {}))
            self.log_tool_outcome("update_trigger", result.get("success", False),
                                  f"'{t.name}' ({t.id})")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "update_trigger")

    def update_schedule(self, schedule_id: Union[int, str],
                        fields: Dict[str, Any]) -> Dict[str, Any]:
        """Rename a schedule or edit its description (timing is read-only)."""
        self.log_incoming_request("update_schedule",
                                  {"schedule_id": schedule_id, "fields": fields})
        try:
            s = _resolve_schedule(schedule_id)
            if s is None:
                return {"success": False,
                        "error": f"Schedule '{schedule_id}' not found"}
            result = self._update_fields("schedule", s, indigo.schedules,
                                         self._SCHEDULE_EDIT_FIELDS,
                                         dict(fields or {}))
            self.log_tool_outcome("update_schedule", result.get("success", False),
                                  f"'{s.name}' ({s.id})")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "update_schedule")

    def update_action_group(self, action_group_id: Union[int, str],
                            fields: Dict[str, Any]) -> Dict[str, Any]:
        """Rename an action group or edit its description."""
        self.log_incoming_request("update_action_group",
                                  {"action_group_id": action_group_id,
                                   "fields": fields})
        try:
            ag = _resolve_action_group(action_group_id)
            if ag is None:
                return {"success": False,
                        "error": f"Action group '{action_group_id}' not found"}
            result = self._update_fields("action group", ag, indigo.actionGroups,
                                         self._ACTION_GROUP_EDIT_FIELDS,
                                         dict(fields or {}))
            self.log_tool_outcome("update_action_group",
                                  result.get("success", False),
                                  f"'{ag.name}' ({ag.id})")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "update_action_group")
