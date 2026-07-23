"""
Renderers that turn raw .indiDb automation records into readable structures.

Pure functions over decoded record dicts — no indigo import, so the whole
module unit-tests standalone. Name resolution comes in as a callable
(kind, id) -> Optional[str] supplied by the handler.
"""

import base64
import re
from typing import Any, Callable, Dict, List, Optional

from ...adapters.indidb import schema

NameLookup = Callable[[str, int], Optional[str]]

# Unset sentinel for TimeStartCap/TimeEndCap and condition end times.
_UNSET_SENTINELS = {4294967295, 18446744073709551615}

# Printable POSIX path ending in a script extension, for ScriptLink2 decode.
_LINK_PATH_RE = re.compile(rb"/[ -~]{3,300}?\.(?:py|scpt|applescript|sh)")


def _named(name_lookup: NameLookup, kind: str, entity_id: Any) -> Dict[str, Any]:
    """{'id': N, 'name': ...} with name resolved best-effort."""
    entry: Dict[str, Any] = {"id": entity_id}
    if isinstance(entity_id, int):
        name = name_lookup(kind, entity_id)
        entry["name"] = name if name is not None else f"<unknown {kind} {entity_id}>"
    return entry


def decode_script_link(link_b64: Any) -> Optional[str]:
    """
    Best-effort path extraction from a ScriptLink2 value (base64 macOS
    bookmark blob). The embedded sandbox-extension string carries the full
    POSIX path in printable ASCII — regex it out. None if undecodable.
    """
    if not isinstance(link_b64, str) or not link_b64:
        return None
    try:
        blob = base64.b64decode(link_b64, validate=False)
    except Exception:
        return None
    matches = _LINK_PATH_RE.findall(blob)
    if not matches:
        return None
    # The sandbox-extension copy is the longest, most complete occurrence.
    best = max(matches, key=len)
    try:
        return best.decode("ascii")
    except UnicodeDecodeError:
        return None


# ── Conditions ────────────────────────────────────────────────────────────────

def render_condition(condition: Any, name_lookup: NameLookup) -> Dict[str, Any]:
    """Decode one Condition dict (recursing into compounds)."""
    if not isinstance(condition, dict) or "Type" not in condition:
        return {"type": "always"}
    cond_type = condition.get("Type")
    rendered: Dict[str, Any] = {
        "type": schema.label(schema.CONDITION_TYPES, cond_type, prefix="type"),
    }

    if cond_type == 3:
        rendered["variable"] = _named(name_lookup, "variable", condition.get("VarID"))
        rendered["comparison"] = schema.label(schema.VAR_STATE_CODES,
                                              condition.get("VarState"))
        if condition.get("VarValue"):
            rendered["value"] = condition["VarValue"]
        var2 = condition.get("VarID2")
        if isinstance(var2, int) and var2 > 0:
            rendered["compare_to_variable"] = _named(name_lookup, "variable", var2)
    elif cond_type == 5:
        start = condition.get("StartTimeDate")
        end = condition.get("EndTimeDate")
        rendered["start"] = schema.seconds_to_hhmm(start)
        rendered["end"] = (None if end in _UNSET_SENTINELS
                           else schema.seconds_to_hhmm(end))
        rendered["operator"] = schema.label(schema.TIME_DATE_OPERATORS,
                                            condition.get("TimeDateCompareOperator"))
    elif cond_type == 7:
        rendered["device"] = _named(name_lookup, "device", condition.get("DevID"))
        if condition.get("DevState"):
            rendered["state"] = condition["DevState"]
        rendered["comparison"] = schema.label(schema.DEV_COMP_CODES,
                                              condition.get("DevComp"))
        if condition.get("DevValue"):
            rendered["value"] = condition["DevValue"]
    elif cond_type == 100:
        condition_list = condition.get("ConditionList") or {}
        rendered["logic"] = schema.label(schema.CONDITION_LOGIC,
                                         condition_list.get("Logic"))
        rendered["conditions"] = [
            render_condition(item, name_lookup)
            for item in (condition_list.get("Conditions") or [])
            if isinstance(item, dict)
        ]
    return rendered


# ── Action steps ──────────────────────────────────────────────────────────────

def render_action_steps(
    steps: Any,
    name_lookup: NameLookup,
    include_scripts: bool = True,
) -> List[Dict[str, Any]]:
    """Decode an ActionSteps vector into readable step dicts, in order."""
    rendered: List[Dict[str, Any]] = []
    if not isinstance(steps, list):
        return rendered

    for position, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        step_class = step.get("Class")
        entry: Dict[str, Any] = {
            "step": position,
            "type": schema.label(schema.ACTION_CLASSES, step_class, prefix="class"),
        }
        if step.get("DelayAction"):
            entry["delay_seconds"] = step.get("DelayAmount")
            if step.get("ReplaceExistingDelayedAction"):
                entry["replaces_existing_delayed"] = True

        if step_class == schema.ACTION_CLASS_DEVICE:
            entry["device"] = _named(name_lookup, "device", step.get("DeviceID"))
            action_code = step.get("DeviceAction")
            entry["action"] = schema.label(schema.DEVICE_ACTION_CODES, action_code)
            value = step.get("DeviceActionValue")
            if action_code == 7 and isinstance(value, int):
                entry["brightness_percent"] = value / 10.0  # stored in tenths
            elif isinstance(value, int) and value != 0:
                entry["value"] = value
            if step.get("AutoComplement"):
                entry["auto_complement_seconds"] = step.get("ComplementCountdown")

        elif step_class == schema.ACTION_CLASS_THERMOSTAT:
            entry["device"] = _named(name_lookup, "device", step.get("DeviceID"))
            entry["action"] = schema.label(schema.THERMOSTAT_ACTION_CODES,
                                           step.get("HVACAction"))
            raw_value = step.get("HVACActionValue")
            if raw_value not in (None, ""):
                entry["value"] = raw_value

        elif step_class == schema.ACTION_CLASS_UNIVERSAL:
            entry["device"] = _named(name_lookup, "device", step.get("DeviceID"))
            entry["action"] = schema.label(schema.UNIVERSAL_ACTION_CODES,
                                           step.get("DeviceAction"))

        elif step_class == schema.ACTION_CLASS_EXEC_GROUP:
            entry["action_group"] = _named(name_lookup, "action_group",
                                           step.get("ActionGroupID"))

        elif step_class == schema.ACTION_CLASS_SCRIPT:
            if step.get("ScriptUseLink"):
                entry["script"] = {
                    "kind": "linked file",
                    "path": decode_script_link(step.get("ScriptLink2")),
                }
            else:
                source = step.get("ScriptSource") or ""
                script: Dict[str, Any] = {
                    "kind": "embedded",
                    "lines": source.count("\n") + 1 if source else 0,
                }
                if include_scripts and source:
                    script["source"] = source
                entry["script"] = script

        elif step_class == schema.ACTION_CLASS_VARIABLE:
            entry["variable"] = _named(name_lookup, "variable", step.get("VarID"))
            entry["action"] = schema.label(schema.VAR_ACTION_CODES,
                                           step.get("VarAction"))
            entry["value"] = step.get("VarValue")

        elif step_class == schema.ACTION_CLASS_PLUGIN:
            entry["plugin_id"] = step.get("PluginID")
            if step.get("TypeLabelPlugin"):
                entry["action"] = step["TypeLabelPlugin"]
            device_id = step.get("DeviceID")
            if isinstance(device_id, int) and device_id > 0:
                entry["device"] = _named(name_lookup, "device", device_id)
            meta = step.get("MetaProps")
            if isinstance(meta, dict):
                plugin_id = step.get("PluginID")
                entry["config"] = meta.get(plugin_id, meta) if plugin_id else meta

        rendered.append(entry)
    return rendered


# ── Whole-record renderers ────────────────────────────────────────────────────

def _common_fields(record: dict) -> Dict[str, Any]:
    common: Dict[str, Any] = {
        "id":   record.get("ID"),
        "name": record.get("Name"),
    }
    if record.get("Description"):
        common["description"] = record["Description"]
    if "Enabled" in record:
        common["enabled"] = record.get("Enabled")
    folder = record.get("FolderID")
    if isinstance(folder, int) and folder > 0:
        common["folder_id"] = folder
    if record.get("Stealth"):
        common["hidden_from_event_log"] = True
    return common


def render_trigger_details(
    record: dict, name_lookup: NameLookup, include_scripts: bool = True
) -> Dict[str, Any]:
    details = _common_fields(record)
    details["entity_type"] = "trigger"

    trigger_class = record.get("Class")
    event: Dict[str, Any] = {
        "type": schema.label(schema.TRIGGER_CLASSES, trigger_class, prefix="class"),
    }
    if trigger_class == 501:
        event["device"] = _named(name_lookup, "device", record.get("DeviceID"))
        if record.get("DeviceStateSelector"):
            event["state"] = record["DeviceStateSelector"]
        event["change"] = schema.label(schema.DEVICE_STATE_CHANGE_CODES,
                                       record.get("DeviceStateChange"))
        if record.get("DeviceStateValue"):
            event["value"] = record["DeviceStateValue"]
    elif trigger_class == 502:
        event["variable"] = _named(name_lookup, "variable", record.get("VarID"))
        event["change"] = schema.label(schema.VAR_CHANGE_CODES,
                                       record.get("VarChange"))
        if record.get("VarValue"):
            event["value"] = record["VarValue"]
    elif trigger_class == 598:
        event["plugin_id"] = record.get("PluginID")
        if record.get("TypeLabelPlugin"):
            event["event_label"] = record["TypeLabelPlugin"]
        if record.get("TypeIdPlugin"):
            event["plugin_event_id"] = record["TypeIdPlugin"]
        meta = record.get("MetaProps")
        if isinstance(meta, dict):
            plugin_id = record.get("PluginID")
            event["config"] = meta.get(plugin_id, meta) if plugin_id else meta
    details["event"] = event

    details["condition"] = render_condition(record.get("Condition"), name_lookup)
    inline_group = record.get("ActionGroup") or {}
    details["action_steps"] = render_action_steps(
        inline_group.get("ActionSteps") if isinstance(inline_group, dict) else None,
        name_lookup, include_scripts)
    return details


def render_schedule_details(
    record: dict, name_lookup: NameLookup, include_scripts: bool = True
) -> Dict[str, Any]:
    details = _common_fields(record)
    details["entity_type"] = "schedule"

    time_type = record.get("TimeType")
    timing: Dict[str, Any] = {
        "time_type": schema.label(schema.TIME_TYPES, time_type, prefix="TimeType"),
        "date_type": schema.label(schema.DATE_TYPES, record.get("DateType"),
                                  prefix="DateType"),
    }
    if time_type == 0:
        timing["at"] = schema.seconds_to_hhmm(record.get("Time"))
    elif time_type in (1, 2):
        delta = record.get("SunDelta")
        if isinstance(delta, int):
            sign = "+" if delta >= 0 else "-"
            timing["sun_offset"] = f"{sign}{abs(delta) // 60}m"
    elif time_type == 3:
        timing["every_seconds"] = record.get("Countdown")
    repeat = record.get("RepeatInterval")
    if isinstance(repeat, int):
        timing["repeat_every_days"] = repeat  # 0 = fire once only
    if record.get("RandomizeAmount"):
        timing["randomize_window"] = record["RandomizeAmount"]
    if record.get("UseEndLimit"):
        timing["end_limit"] = {
            "day":   record.get("DateEndDay"),
            "month": record.get("DateEndMonth"),
            "year":  record.get("DateEndYear"),
        }
    if record.get("AutoDelete"):
        timing["auto_delete_after_firing"] = True
    details["timing"] = timing

    details["condition"] = render_condition(record.get("Condition"), name_lookup)
    inline_group = record.get("ActionGroup") or {}
    details["action_steps"] = render_action_steps(
        inline_group.get("ActionSteps") if isinstance(inline_group, dict) else None,
        name_lookup, include_scripts)
    return details


def render_action_group_details(
    record: dict, name_lookup: NameLookup, include_scripts: bool = True
) -> Dict[str, Any]:
    details = _common_fields(record)
    details["entity_type"] = "action_group"
    details["condition"] = render_condition(record.get("Condition"), name_lookup)
    details["action_steps"] = render_action_steps(
        record.get("ActionSteps"), name_lookup, include_scripts)
    return details
