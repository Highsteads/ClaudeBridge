#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    device_control_map.py
# Description: One-call answers to "what can switch this device, and when?"
#              (who_controls) and "what switched it, each time, over the last
#              days?" (explain_device_changes).
# Author:      CliveS & Claude Opus 5.5
# Date:        21-11-2026
# Version:     1.0

"""
Everything in Indigo that can change one device, in one reply.

find_automation_references already says WHICH automations reference a device.
It does not say when they fire, under what conditions, whether they are
enabled, or what they do to the device, so answering "what turns this on at
8pm?" took one get_automation call per hit. who_controls joins those together,
and also looks in four places no reference lookup covered:

  - control page buttons whose action steps act on the device
  - linked script files: a schedule that runs a .py file on disk which
    mentions the device (embedded scripts were already covered)
  - other devices' settings that hold this device's id (a plugin's group,
    a watchdog, a virtual device pointing at it)
  - plugin settings files (Preferences/Plugins/*.indiPref) that hold the id

explain_device_changes reads the event log the other way round: every line
where the device changed in a window, each with its most likely cause, and a
summary by cause. "It comes on at 8pm when I am away" shows up as one cause
with a column of 8pm times on the days it happened.

Both are reads. Every text match is labelled heuristic; decoded structure is
exact. What neither can see — a plugin's own source code, HomeKit, Alexa, an
app, the wall switch — is said in the reply's notes, not left to be assumed.
"""

import bisect
import datetime
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import indigo
except ImportError:
    indigo = None

from ..base_handler import BaseToolHandler
from ...adapters.indidb import schema
from ...common import plugin_prefs
from ...common.script_refs import find_script_references, scripts_dirs
from . import detail_renderer
from .automation_detail_handler import AUTOMATION_LOG_SOURCES

# Roles that mean "this can change the device", against roles that only read it.
CONTROL_ROLES = ("acts_on", "script_reference", "plugin_config_reference")

_HOW = {
    "acts_on":                 "action step",
    "script_reference":        "embedded script",
    "plugin_config_reference": "plugin action setting",
}

# Event-log lines that name the device without changing it.
_NOT_A_CHANGE = re.compile(r"\brequest\b|\brequested\b", re.IGNORECASE)

# Two lines for one change ("sent ... on", then "received ... is on") are
# counted once when they fall this close together.
SAME_CHANGE_SECONDS = 3.0

EXPLAIN_DEFAULT_DAYS = 7
EXPLAIN_MAX_DAYS = 14
EXPLAIN_DEFAULT_LIMIT = 50
EXPLAIN_MAX_LIMIT = 200
EXPLAIN_MAX_ENTRIES = 50000

_BETWEEN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")


# ── Small pure helpers (tested directly) ─────────────────────────────────────

def parse_between(text: Optional[str]) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    """'19:30-20:30' -> ((1170, 1230), None) in minutes since midnight.

    A window may cross midnight ('23:00-01:00'). Returns (None, None) for no
    window and (None, message) for one that cannot be read.
    """
    if text is None or str(text).strip() == "":
        return None, None
    m = _BETWEEN_RE.match(str(text))
    if not m:
        return None, f"between must look like 19:30-20:30, got {text!r}"
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None, f"between has an impossible time: {text!r}"
    return (h1 * 60 + m1, h2 * 60 + m2), None


def in_window(ts: datetime.datetime, window: Optional[Tuple[int, int]]) -> bool:
    if window is None:
        return True
    start, end = window
    minute = ts.hour * 60 + ts.minute
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end          # crosses midnight


def change_text(message: str, needle: str) -> str:
    """What the line says happened, with the source's own words: the text
    either side of the quoted device name, trimmed."""
    lower = message.lower()
    at = lower.find(needle.lower())
    if at < 0:
        return message.strip()
    before = message[:at].strip()
    after = message[at + len(needle):].strip()
    return " ".join(part for part in (before, after) if part) or message.strip()


def schedule_when(timing: Dict[str, Any]) -> str:
    """A schedule's rendered timing as a phrase a person would say."""
    time_type = str(timing.get("time_type", ""))
    if "absolute" in time_type and timing.get("at"):
        when = f"at {timing['at']}"
    elif "sun" in time_type:
        offset = timing.get("sun_offset")
        base = "sunrise" if "sunrise" in time_type else "sunset"
        when = f"at {base}" + (f" {offset}" if offset and offset not in ("+0m", "-0m") else "")
    elif "interval" in time_type and timing.get("every_seconds"):
        when = f"every {timing['every_seconds']} seconds"
    else:
        when = f"timing {time_type or 'unknown'}"
    repeat = timing.get("repeat_every_days")
    if repeat == 1:
        when += ", every day"
    elif isinstance(repeat, int) and repeat > 1:
        when += f", every {repeat} days"
    elif repeat == 0:
        when += ", once only"
    if timing.get("randomize_window"):
        when += f", randomised by up to {timing['randomize_window']}"
    return when


def trigger_when(event: Dict[str, Any]) -> str:
    """A trigger's rendered event as a phrase."""
    if "device" in event:
        dev = event["device"].get("name") or event["device"].get("id")
        state = event.get("state")
        change = str(event.get("change", "changes")).split(" (")[0]
        value = event.get("value")
        text = f"when {dev}" + (f" {state}" if state else "") + f" {change}"
        return text + (f" {value}" if value else "")
    if "variable" in event:
        var = event["variable"].get("name") or event["variable"].get("id")
        change = str(event.get("change", "changes")).split(" (")[0]
        value = event.get("value")
        return f"when variable {var} {change}" + (f" {value}" if value else "")
    if event.get("event_label") or event.get("plugin_id"):
        return f"on plugin event {event.get('event_label') or event.get('plugin_event_id')}" \
               f" ({event.get('plugin_id')})"
    return f"on {str(event.get('type', 'an event')).split(' (')[0]}"


def condition_is_always(rendered: Dict[str, Any]) -> bool:
    return not rendered or rendered.get("type") == "always" \
        or str(rendered.get("type", "")).startswith("always")


def _steps_of(record: Dict[str, Any]) -> List[Any]:
    """The action steps a trigger, schedule or action group record holds."""
    if not isinstance(record, dict):
        return []
    if isinstance(record.get("ActionSteps"), list):
        return record["ActionSteps"]
    inline = record.get("ActionGroup")
    if isinstance(inline, dict) and isinstance(inline.get("ActionSteps"), list):
        return inline["ActionSteps"]
    return []


def id_in_value(value: Any, entity_id: int) -> bool:
    """Does a stored setting hold this id? An int, a digit string, or one
    entry of a comma- or space-separated list; dicts and lists are searched."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == entity_id
    if isinstance(value, str):
        text = value.strip()
        if text == str(entity_id):
            return True
        return str(entity_id) in re.split(r"[\s,;]+", text)
    if isinstance(value, dict):
        return any(id_in_value(v, entity_id) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(id_in_value(v, entity_id) for v in value)
    return False


def _plain_dict(value: Any) -> Optional[Dict[str, Any]]:
    """An indigo.Dict (not a dict subclass) or dict as a plain dict, else None."""
    if isinstance(value, dict):
        return value
    try:
        return {k: value[k] for k in value.keys()}
    except Exception:
        return None


def _plain_value(value: Any) -> Any:
    d = _plain_dict(value) if not isinstance(value, (str, bytes, int, float, bool)) else None
    if d is not None:
        return {k: _plain_value(v) for k, v in d.items()}
    if not isinstance(value, (str, bytes)) and hasattr(value, "__iter__"):
        try:
            return [_plain_value(v) for v in value]
        except Exception:
            return value
    return value


def _matching_keys(props: Any, entity_id: int, prefix: str = "") -> List[str]:
    """Every key path in a nested settings dict whose value holds the id."""
    found: List[str] = []
    props = _plain_value(props)
    if isinstance(props, dict):
        for key, value in props.items():
            path = f"{prefix}{key}"
            if isinstance(value, (dict, list)):
                found.extend(_matching_keys(value, entity_id, path + "."))
            elif id_in_value(value, entity_id):
                found.append(path)
    elif isinstance(props, list):
        if id_in_value(props, entity_id):
            found.append(prefix.rstrip(".") or "(list)")
    return found


def prefs_file_keys(path: str, entity_id: int) -> List[str]:
    """Setting names in one .indiPref file whose value holds the id."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    keys: List[str] = []
    wanted = str(entity_id)
    for element in root.iter():
        text = (element.text or "").strip()
        if not text or element is root:
            continue
        if text == wanted or wanted in re.split(r"[\s,;]+", text):
            keys.append(element.tag)
    seen = set()
    return [k for k in keys if not (k in seen or seen.add(k))]


def _as_on(value: Any) -> Optional[bool]:
    """An on/off value from SQL Logger history, which may be a bool, 0/1 or text."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes", "t"):
        return True
    if text in ("0", "false", "off", "no", "f"):
        return False
    return None


def history_changes(rows: Iterable[Dict[str, Any]]) -> List[Tuple[datetime.datetime, str]]:
    """Turn sparse SQL Logger rows (a value only where it changed, else null)
    into (time, what) changes. The first value of each column is the starting
    point, not a change. A brightness move in the same row as an on/off change
    is folded into it."""
    parsed = []
    for row in rows or []:
        try:
            ts = datetime.datetime.strptime(str(row.get("ts"))[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        parsed.append((ts, row))
    parsed.sort(key=lambda p: p[0])
    changes: List[Tuple[datetime.datetime, str]] = []
    last_on: Optional[bool] = None
    last_bri: Any = None
    for ts, row in parsed:
        on = _as_on(row.get("onoffstate"))
        bri = row.get("brightnesslevel")
        what = None
        if on is not None:
            if last_on is not None and on != last_on:
                what = "turned on" if on else "turned off"
            last_on = on
        if bri not in (None, ""):
            if last_bri is not None and str(bri) != str(last_bri) and what is None:
                what = f"brightness {bri}%"
            elif what == "turned on" and str(bri) not in ("", "0"):
                what = f"turned on at {bri}%"
            last_bri = bri
        if what:
            changes.append((ts, what))
    return changes


def _join(items: List[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ── The handler ──────────────────────────────────────────────────────────────

class DeviceControlMap(BaseToolHandler):
    """who_controls and explain_device_changes."""

    def __init__(
        self,
        detail_handler,
        structure_store,
        page_reader: Optional[Callable[[int], Tuple[Optional[list], Optional[str]]]] = None,
        control_pages_provider: Optional[Callable[[], Iterable[Tuple[int, str]]]] = None,
        devices_provider: Optional[Callable[[], Iterable[Any]]] = None,
        prefs_dir_provider: Optional[Callable[[], Optional[str]]] = None,
        script_dirs_provider: Optional[Callable[[], List[str]]] = None,
        history_reader: Optional[Callable[[int, int], Dict[str, Any]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="device_control_map", logger=logger)
        self.detail = detail_handler
        self.store = structure_store
        self.page_reader = page_reader
        self.control_pages_provider = control_pages_provider or _live_control_pages
        self.devices_provider = devices_provider or _live_devices
        self.prefs_dir_provider = prefs_dir_provider or plugin_prefs.prefs_dir
        self.script_dirs_provider = script_dirs_provider or scripts_dirs
        # (device_id, hours) -> a device_history reply. Used when a device's
        # plugin never logs it by name (measured: a Zigbee lamp here whose
        # only log lines are a script's own), so the log has no change lines.
        self.history_reader = history_reader

    # ── who_controls ─────────────────────────────────────────────────────────

    def who_controls(
        self,
        device_id: int,
        include_scripts: bool = True,
        include_plugins: bool = True,
        include_control_pages: bool = True,
    ) -> Dict[str, Any]:
        self.log_incoming_request("who_controls", {"device_id": device_id})
        try:
            name = self.detail._lookup_name("device", device_id)
            if name is None:
                return {"success": False, "error": f"Device {device_id} not found"}

            refs = self.store.find_references("device", device_id)
            controls: List[Dict[str, Any]] = []
            seen = set()
            for ref in refs:
                if ref.get("role") not in CONTROL_ROLES:
                    continue
                entry = self._describe_route(ref, device_id)
                key = (entry["entity_type"], entry["id"], tuple(
                    a["id"] for a in entry.get("via_action_groups", [])), entry["how"])
                if key in seen:
                    continue
                seen.add(key)
                controls.append(entry)

            notes: List[str] = []
            scripts: List[Dict[str, Any]] = []
            if include_scripts:
                scripts = self._script_routes(device_id, name, controls, seen, notes)

            pages: List[Dict[str, Any]] = []
            if include_control_pages:
                pages = self._control_page_buttons(device_id, notes)

            plugin_held: List[Dict[str, Any]] = []
            plugin_prefs_hits: List[Dict[str, Any]] = []
            if include_plugins:
                plugin_held = self._devices_holding_id(device_id, notes)
                plugin_prefs_hits = self._prefs_holding_id(device_id, notes)

            reacts = [self._reader_entry(r) for r in refs if r.get("role") == "watches"]
            checks = [self._reader_entry(r) for r in refs
                      if r.get("role") == "condition_reads"]

            controls.sort(key=lambda c: (not c.get("enabled", True),
                                         c["entity_type"], str(c.get("name", "")).lower()))
            upcoming = sorted(
                ({"name": c["name"], "id": c["id"], "next_run": c["next_run"],
                  "action": c.get("action")}
                 for c in controls
                 if c["entity_type"] == "schedule" and c.get("next_run")
                 and c.get("enabled", True)),
                key=lambda u: u["next_run"])

            notes.append(
                "Not covered by any of these sources: a plugin that keeps the id in its own "
                "code, HomeKit, Alexa, Apple Shortcuts, phone apps, the device's own "
                "built-in schedule and the switch on the wall. explain_device_changes shows "
                "what actually changed the device, including changes with no automation "
                "behind them.")
            if any(c.get("confidence") == "heuristic" for c in controls) \
                    or scripts or plugin_held or plugin_prefs_hits:
                notes.append(
                    "Entries marked heuristic were found by matching the device's id or "
                    "quoted name as text. A match means the id is there, not that the code "
                    "necessarily switches the device: read it before relying on it.")

            result = {
                "success": True,
                "device": {"id": device_id, "name": name},
                "summary": self._summary(name, controls, scripts, pages,
                                         plugin_held, plugin_prefs_hits),
                "controls": controls,
                "upcoming": upcoming,
                "control_pages": pages,
                "scripts": scripts,
                "plugin_devices": plugin_held,
                "plugin_settings": plugin_prefs_hits,
                "reacts_to_it": reacts,
                "checks_it": checks,
                "notes": notes,
                "structure_source": self.store.freshness(),
            }
            self.log_tool_outcome("who_controls", True,
                                  f"'{name}': {len(controls)} automations")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "who_controls")

    # Route description ------------------------------------------------------

    def _record(self, kind: str, entity_id: int) -> Optional[Dict[str, Any]]:
        try:
            return self.store.get_structure(kind, entity_id)
        except Exception:
            return None

    def _describe_route(self, ref: Dict[str, Any], device_id: int) -> Dict[str, Any]:
        kind, cid = ref["entity_type"], ref["id"]
        chain = list(ref.get("via_action_groups") or [])
        chain_ids = [c["id"] if isinstance(c, dict) else c for c in chain]
        entry: Dict[str, Any] = {
            "entity_type": kind,
            "id": cid,
            "name": self.detail._display_name(kind, cid),
            "how": _HOW.get(ref.get("role"), ref.get("role")),
        }
        if ref.get("confidence") == "heuristic":
            entry["confidence"] = "heuristic"
            if ref.get("detail"):
                entry["matched"] = ref["detail"]
        if chain_ids:
            entry["via_action_groups"] = [
                {"id": ag, "name": self.detail._display_name("action_group", ag)}
                for ag in chain_ids]
        self._add_timing(entry, kind, cid)

        # What it does to the device: the steps in the container that holds
        # them (the innermost action group of a chain, else the automation).
        if ref.get("role") == "acts_on":
            holder_kind, holder_id = (("action_group", chain_ids[-1]) if chain_ids
                                      else (kind, cid))
            actions = self._actions_on(holder_kind, holder_id, device_id)
            if actions:
                entry["action"] = _join([a["text"] for a in actions])
                entry["steps"] = actions
            elif ref.get("detail"):
                entry["action"] = str(ref["detail"]).split(" (")[0]

        entry["conditions"] = self._route_conditions(kind, cid, chain_ids)
        return entry

    def _route_conditions(self, kind: str, cid: int, chain_ids: List[int]):
        """Conditions along a route: the automation's own, then each action
        group's on the way, only those that are not "always"."""
        conds = []
        for c_kind, c_id in [(kind, cid)] + [("action_group", ag) for ag in chain_ids]:
            record = self._record(c_kind, c_id)
            if record is None:
                continue
            rendered = detail_renderer.render_condition(
                record.get("Condition"), self.detail._lookup_name, include_scripts=False)
            if not condition_is_always(rendered):
                conds.append({"on": self.detail._display_name(c_kind, c_id),
                              "condition": rendered})
        return conds or "none"

    def _add_timing(self, entry: Dict[str, Any], kind: str, cid: int) -> None:
        record = self._record(kind, cid)
        live = self.detail._live_enrichment(kind, cid)
        if "enabled" in live:
            entry["enabled"] = live["enabled"]
        elif record is not None and "Enabled" in record:
            entry["enabled"] = record.get("Enabled")
        if record is None:
            entry["when"] = "not in the database file yet"
            return
        if kind == "schedule":
            timing = detail_renderer.render_schedule_details(
                record, self.detail._lookup_name, include_scripts=False)["timing"]
            entry["when"] = schedule_when(timing)
            entry["timing"] = timing
            if live.get("next_execution"):
                entry["next_run"] = live["next_execution"]
        elif kind == "trigger":
            event = detail_renderer.render_trigger_details(
                record, self.detail._lookup_name, include_scripts=False)["event"]
            entry["when"] = trigger_when(event)
            entry["event"] = event
        else:
            runners = [r for r in self.store.find_references("action_group", cid)
                       if r.get("role") == "executes"]
            if runners:
                names = [self.detail._display_name(r["entity_type"], r["id"])
                         for r in runners]
                entry["when"] = "when run by " + _join(sorted(set(names)))
            else:
                entry["when"] = ("only when run by hand, a control page, a script or "
                                 "a plugin - no trigger or schedule runs it")

    def _actions_on(self, kind: str, cid: int, device_id: int) -> List[Dict[str, Any]]:
        record = self._record(kind, cid)
        if record is None:
            return []
        rendered = detail_renderer.render_action_steps(
            _steps_of(record), self.detail._lookup_name, include_scripts=False)
        out = []
        for step in rendered:
            dev = step.get("device")
            if not (isinstance(dev, dict) and dev.get("id") == device_id):
                continue
            text = str(step.get("action", step.get("type", "action"))).split(" (")[0]
            if step.get("brightness_percent") is not None:
                text += f" to {step['brightness_percent']:g}%"
            elif step.get("value") not in (None, ""):
                text += f" {step['value']}"
            item = {"step": step.get("step"), "text": text}
            if step.get("delay_seconds"):
                item["delay_seconds"] = step["delay_seconds"]
                item["text"] = f"{text} after {step['delay_seconds']} seconds"
            if step.get("auto_complement_seconds"):
                item["reverts_after_seconds"] = step["auto_complement_seconds"]
            out.append(item)
        return out

    def _reader_entry(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        kind, cid = ref["entity_type"], ref["id"]
        entry = {"entity_type": kind, "id": cid,
                 "name": self.detail._display_name(kind, cid)}
        if ref.get("detail"):
            entry["detail"] = ref["detail"]
        if ref.get("confidence") == "heuristic":
            entry["confidence"] = "heuristic"
        if ref.get("via_action_groups"):
            entry["via_action_groups"] = [
                c.get("name", c.get("id")) if isinstance(c, dict) else c
                for c in ref["via_action_groups"]]
        return entry

    # Scripts on disk, and the automations that run them --------------------

    def _linked_script_runners(self) -> Dict[str, List[Tuple[str, int]]]:
        """Script file name -> automations whose step runs that linked file."""
        runners: Dict[str, List[Tuple[str, int]]] = {}
        for kind in ("trigger", "schedule", "action_group"):
            for cid, record in (self.store.get_all_structures(kind) or {}).items():
                for step in _steps_of(record):
                    if not (isinstance(step, dict)
                            and step.get("Class") == schema.ACTION_CLASS_SCRIPT
                            and step.get("ScriptUseLink")):
                        continue
                    path = detail_renderer.decode_script_link(step.get("ScriptLink2"))
                    if not path:
                        continue
                    # Indigo's bookmark can hold the path in lower case
                    # (measured: ".../python scripts/kitchen_lights_on.py"
                    # for Kitchen_Lights_On.py), so file names compare
                    # without regard to case.
                    base = os.path.basename(path).lower()
                    if (kind, cid) not in runners.setdefault(base, []):
                        runners[base].append((kind, cid))
        return runners

    def _script_routes(self, device_id: int, name: str,
                       controls: List[Dict[str, Any]], seen: set,
                       notes: List[str]) -> List[Dict[str, Any]]:
        try:
            dirs = list(self.script_dirs_provider() or [])
        except Exception as exc:
            notes.append(f"Script folders could not be listed: {exc}")
            return []
        if not dirs:
            notes.append("No Indigo script folder found, so no script files were searched.")
            return []
        try:
            hits = find_script_references(device_id, name, dirs)
        except Exception as exc:
            notes.append(f"Script folder search failed: {exc}")
            return []

        runners = self._linked_script_runners() if hits else {}
        scripts: List[Dict[str, Any]] = []
        for hit in hits:
            base = hit["script"].split("/")[-1].lower()
            run_by = []
            for kind, cid in runners.get(base, []):
                starts = [(kind, cid, [])]
                if kind == "action_group":
                    for parent in self.store.find_references("action_group", cid):
                        if parent.get("role") == "executes":
                            chain = [c["id"] if isinstance(c, dict) else c
                                     for c in (parent.get("via_action_groups") or [])]
                            starts.append((parent["entity_type"], parent["id"], chain))
                for s_kind, s_id, chain in starts:
                    entry: Dict[str, Any] = {
                        "entity_type": s_kind, "id": s_id,
                        "name": self.detail._display_name(s_kind, s_id),
                        "how": "linked script",
                        "action": f"runs {hit['script'].split('/')[-1]}, "
                                  f"which mentions the device",
                        "script": hit["script"],
                        "confidence": "heuristic",
                        "matched": f"lines {hit['lines'][:5]} of {hit['script']} "
                                   f"(by {' and '.join(hit['matched_by'])})",
                    }
                    if chain or (s_kind, s_id) != (kind, cid):
                        entry["via_action_groups"] = [
                            {"id": ag, "name": self.detail._display_name("action_group", ag)}
                            for ag in (chain or [cid])]
                    self._add_timing(entry, s_kind, s_id)
                    entry["conditions"] = self._route_conditions(
                        s_kind, s_id, [a["id"] for a in entry.get("via_action_groups", [])])
                    key =(s_kind, s_id, tuple(a["id"] for a in
                                               entry.get("via_action_groups", [])),
                           "linked script")
                    if key not in seen:
                        seen.add(key)
                        controls.append(entry)
                    run_by.append(entry["name"])
            scripts.append({
                "script": hit["script"],
                "lines": hit["lines"],
                "matched_by": hit["matched_by"],
                "run_by": sorted(set(run_by)) or (
                    "no trigger, schedule or action group runs this file as a linked "
                    "script; a plugin (such as a script runner) or another script may"),
                "confidence": "heuristic",
            })
        return scripts

    # Control pages ----------------------------------------------------------

    def _control_page_buttons(self, device_id: int,
                              notes: List[str]) -> List[Dict[str, Any]]:
        if self.page_reader is None:
            notes.append("Control pages were not searched: no page reader available.")
            return []
        try:
            pages = list(self.control_pages_provider() or [])
        except Exception as exc:
            notes.append(f"Control pages could not be listed: {exc}")
            return []
        found: List[Dict[str, Any]] = []
        unread = 0
        for page_id, page_name in pages:
            try:
                elements, _note = self.page_reader(page_id)
            except Exception:
                elements = None
            if elements is None:
                unread += 1
                continue
            for element in elements:
                hit = self._element_acts_on(element, device_id)
                if hit is None:
                    continue
                found.append({"page_id": page_id, "page": page_name,
                              "element": element.get("caption")
                              or element.get("type") or "element",
                              "index": element.get("index"),
                              "does": hit})
        if unread:
            notes.append(f"{_count(unread, 'control page', 'control pages')} could not be "
                         f"read, so a button on it would be missed.")
        return found

    @staticmethod
    def _element_acts_on(element: Dict[str, Any], device_id: int) -> Optional[str]:
        actions = []
        for step in element.get("on_tap") or []:
            if step.get("device_id") == device_id:
                actions.append(str(step.get("action") or step.get("action_class")
                                   or "acts on it").split(" (")[0])
        if actions:
            return "tapping it will " + _join(actions)
        target = element.get("target") or {}
        if target.get("id") == device_id and element.get("type") == "device" \
                and str(element.get("action_class", "")).startswith("control"):
            return "tapping it controls the device directly"
        return None

    # Plugins that hold the id ----------------------------------------------

    def _devices_holding_id(self, device_id: int,
                            notes: List[str]) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        try:
            devices = list(self.devices_provider() or [])
        except Exception as exc:
            notes.append(f"Other devices' settings could not be read: {exc}")
            return found
        for dev in devices:
            try:
                if dev.id == device_id:
                    continue
                global_props = _plain_dict(getattr(dev, "globalProps", None)) or {}
            except Exception:
                continue
            for namespace, props in global_props.items():
                keys = _matching_keys(props, device_id)
                if keys:
                    found.append({"device_id": dev.id, "device": dev.name,
                                  "plugin": namespace, "settings": keys,
                                  "confidence": "heuristic"})
        return found

    def _prefs_holding_id(self, device_id: int,
                          notes: List[str]) -> List[Dict[str, Any]]:
        try:
            folder = self.prefs_dir_provider()
        except Exception:
            folder = None
        if not folder or not os.path.isdir(folder):
            notes.append("Plugin settings files were not searched: folder not found.")
            return []
        found: List[Dict[str, Any]] = []
        for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
            if not entry.name.endswith(".indiPref") or not entry.is_file():
                continue
            keys = prefs_file_keys(entry.path, device_id)
            if keys:
                found.append({"plugin": entry.name[:-len(".indiPref")],
                              "settings": keys, "confidence": "heuristic"})
        return found

    # Summary ----------------------------------------------------------------

    @staticmethod
    def _summary(name, controls, scripts, pages, plugin_held, prefs) -> str:
        kinds = {"schedule": 0, "trigger": 0, "action_group": 0}
        for c in controls:
            kinds[c["entity_type"]] = kinds.get(c["entity_type"], 0) + 1
        parts = []
        if kinds["schedule"]:
            parts.append(_count(kinds["schedule"], "schedule", "schedules"))
        if kinds["trigger"]:
            parts.append(_count(kinds["trigger"], "trigger", "triggers"))
        if kinds["action_group"]:
            parts.append(_count(kinds["action_group"], "action group", "action groups"))
        if pages:
            parts.append(_count(len(pages), "control page button", "control page buttons"))
        if scripts:
            parts.append(_count(len(scripts), "script file", "script files"))
        if plugin_held:
            parts.append(_count(len(plugin_held), "other device's settings",
                                "other devices' settings"))
        if prefs:
            parts.append(_count(len(prefs), "plugin's settings", "plugins' settings"))
        if not parts:
            return (f"Nothing in Indigo's automations, control pages, scripts or plugin "
                    f"settings refers to {name}.")
        disabled = sum(1 for c in controls if c.get("enabled") is False)
        text = f"{name} is referred to by {_join(parts)}."
        if disabled:
            text += f" {_count(disabled, 'of the automations is', 'of the automations are')} disabled."
        return text

    def _changes_from_history(self, device_id, days, window, wanted):
        """Changes from SQL Logger history when the log has none. Returns
        (changes, note) where a note says why history could not be used."""
        reply = None
        for columns in (["onoffstate", "brightnesslevel"], ["onoffstate"],
                        ["brightnesslevel"]):
            try:
                reply = self.history_reader(device_id, days * 24, columns)
            except Exception as exc:
                return [], f"SQL Logger history could not be read: {exc}"
            if isinstance(reply, dict) and reply.get("success"):
                break
        if not (isinstance(reply, dict) and reply.get("success")):
            error = reply.get("error") if isinstance(reply, dict) else None
            return [], ("SQL Logger history had nothing to use"
                        + (f": {error}" if error else "") + ".")
        changes = []
        for ts, what in history_changes(reply.get("rows") or []):
            if not in_window(ts, window) or (wanted and wanted not in what.lower()):
                continue
            stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            changes.append((ts, {"entry": {"TimeStamp": stamp,
                                           "TypeStr": "SQL Logger history"},
                                 "what": what}))
        note = None
        if reply.get("truncated"):
            note = (f"The SQL Logger history held more rows than one read takes, so only "
                    f"changes from {reply.get('ts_oldest')} on were found.")
        return changes, note

    def _hidden_controllers(self, device_id: int) -> List[Dict[str, Any]]:
        """Automations that can change the device and are set to stay out of
        the event log (the record's Stealth flag), so a log reader cannot see
        them run. Linked scripts included; plugins and pages are not needed."""
        try:
            mapped = self.who_controls(device_id, include_scripts=True,
                                       include_plugins=False, include_control_pages=False)
        except Exception:
            return []
        hidden, seen = [], set()
        for c in mapped.get("controls", []) if isinstance(mapped, dict) else []:
            record = self._record(c["entity_type"], c["id"])
            if not (isinstance(record, dict) and record.get("Stealth")):
                continue
            key = (c["entity_type"], c["id"])
            if key in seen:
                continue
            seen.add(key)
            hidden.append({"entity_type": c["entity_type"], "id": c["id"],
                           "name": c["name"]})
        return hidden

    # ── explain_device_changes ───────────────────────────────────────────────

    def explain_device_changes(
        self,
        device_id: int,
        days: int = EXPLAIN_DEFAULT_DAYS,
        between: Optional[str] = None,
        contains: Optional[str] = None,
        limit: int = EXPLAIN_DEFAULT_LIMIT,
        lookback_seconds: int = 60,
    ) -> Dict[str, Any]:
        self.log_incoming_request("explain_device_changes",
                                  {"device_id": device_id, "days": days,
                                   "between": between, "contains": contains})
        try:
            reader = getattr(self.detail, "log_query_handler", None)
            if reader is None:
                return {"success": False, "error": "Event-log reader unavailable"}
            name = self.detail._lookup_name("device", device_id)
            if name is None:
                return {"success": False, "error": f"Device {device_id} not found"}
            window, problem = parse_between(between)
            if problem:
                return {"success": False, "error": problem}
            days = max(1, min(int(days), EXPLAIN_MAX_DAYS))
            limit = max(1, min(int(limit), EXPLAIN_MAX_LIMIT))
            lookback_seconds = max(1, min(int(lookback_seconds), 3600))
            needle = f'"{name}"'
            needle_lower = needle.lower()
            wanted = (contains or "").strip().lower()

            name_lower = name.lower()

            def _is_script_line(entry):
                return (str(entry.get("TypeStr", "")).startswith("Script")
                        and name_lower in str(entry.get("Message", "")).lower())

            def _useful(entry):
                return (entry.get("TypeStr") in AUTOMATION_LOG_SOURCES
                        or needle_lower in str(entry.get("Message", "")).lower()
                        or _is_script_line(entry))

            now = datetime.datetime.now()
            entries, meta = reader._read_log_range(
                now - datetime.timedelta(days=days), None, None,
                limit=EXPLAIN_MAX_ENTRIES, keep=_useful)

            stamped = [(ts, e) for ts, e in self.detail._timestamped(entries)]
            stamped.sort(key=lambda p: p[0])
            automation = [(ts, e) for ts, e in stamped
                          if e.get("TypeStr") in AUTOMATION_LOG_SOURCES]
            auto_times = [ts for ts, _ in automation]
            # A script's own line naming the device ("Kitchen Spot Lights turned
            # OFF") is the evidence left when the automation that ran it is set
            # to stay out of the event log: measured on this house, where most
            # lighting triggers are, so their runs log nothing at all.
            script_lines = [(ts, e) for ts, e in stamped if _is_script_line(e)]
            script_times = [ts for ts, _ in script_lines]
            hidden = self._hidden_controllers(device_id)

            changes: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
            last_ts = None
            for ts, e in stamped:
                message = str(e.get("Message", ""))
                if needle_lower not in message.lower() or _NOT_A_CHANGE.search(message):
                    continue
                if e.get("TypeStr") in AUTOMATION_LOG_SOURCES \
                        or str(e.get("TypeStr", "")).startswith("Script"):
                    continue
                if not in_window(ts, window):
                    continue
                what = change_text(message, needle)
                if wanted and wanted not in what.lower():
                    continue
                if last_ts is not None and (ts - last_ts).total_seconds() <= SAME_CHANGE_SECONDS:
                    continue
                last_ts = ts
                changes.append((ts, {"entry": e, "what": what}))

            change_source = "event log"
            history_note = None
            if not changes and self.history_reader is not None:
                changes, history_note = self._changes_from_history(
                    device_id, days, window, wanted)
                change_source = "SQL Logger history" if changes else "none found"

            total = len(changes)
            shown = changes[-limit:]
            events: List[Dict[str, Any]] = []
            by_cause: Dict[Tuple[str, Any], Dict[str, Any]] = {}
            for ts, item in reversed(shown):
                lo = bisect.bisect_left(auto_times, ts - datetime.timedelta(seconds=lookback_seconds))
                hi = bisect.bisect_right(auto_times, ts + datetime.timedelta(seconds=5))
                candidates = automation[lo:hi]
                ranked = self.detail._rank_candidates(candidates, ts, device_id,
                                                      lookback_seconds) if candidates else []
                top = ranked[0] if ranked else None
                # Only an automation that is linked to the device is named as
                # the cause. Timing alone blamed a leak-sensor trigger for a
                # kitchen light in the first live run.
                likely = top is not None and top.get("relationship") is not None
                s_lo = bisect.bisect_left(script_times,
                                          ts - datetime.timedelta(seconds=lookback_seconds))
                s_hi = bisect.bisect_right(script_times, ts + datetime.timedelta(seconds=2))
                script_hit = script_lines[s_hi - 1] if s_hi > s_lo else None
                event = {
                    "time": item["entry"].get("TimeStamp"),
                    "day": _WEEKDAYS[ts.weekday()],
                    "source": item["entry"].get("TypeStr"),
                    "what": item["what"],
                }
                if likely:
                    event["likely_cause"] = {k: top[k] for k in
                                             ("entity_type", "id", "name", "score",
                                              "seconds_before_event", "evidence")
                                             if k in top}
                    key = (top["entity_type"], top.get("id", top["name"]))
                    label = f"{top['entity_type'].replace('_', ' ')} {top['name']}"
                elif script_hit is not None:
                    s_ts, s_entry = script_hit
                    event["likely_cause"] = {
                        "entity_type": "script",
                        "script_line": str(s_entry.get("Message", ""))[:200],
                        "seconds_before_event": round((ts - s_ts).total_seconds(), 1),
                        "evidence": ["a script logged a line naming the device just "
                                     "before the change"],
                    }
                    if hidden:
                        event["likely_cause"]["run_by_one_of"] = [h["name"] for h in hidden]
                    key = ("script", None)
                    label = ("a script that logs the device by name"
                             + (" (run by an automation hidden from the event log)"
                                if hidden else ""))
                else:
                    event["likely_cause"] = None
                    if top is not None:
                        event["nearest_activity"] = {
                            "name": top["name"], "entity_type": top["entity_type"],
                            "seconds_before_event": top.get("seconds_before_event"),
                            "note": "ran nearby but nothing links it to the device"}
                    key = ("none", None)
                    label = ("nothing logged near it links to the device: manual, a plugin, "
                             "an app, HomeKit, the device itself"
                             + (", or an automation hidden from the event log"
                                if hidden else ""))
                events.append(event)
                group = by_cause.setdefault(key, {"cause": label, "count": 0, "times": [],
                                                  "days": []})
                group["count"] += 1
                group["times"].append(ts.strftime("%H:%M"))
                group["days"].append(ts.strftime("%a %d %b"))

            summary = sorted(by_cause.values(), key=lambda g: -g["count"])
            for group in summary:
                times = sorted(group["times"])
                group["earliest"], group["latest"] = times[0], times[-1]
                group["times"] = group["times"][:20]
                group["days"] = group["days"][:20]

            notes: List[str] = []
            if total > len(shown):
                notes.append(f"{total} changes matched; the newest {len(shown)} are shown. "
                             f"Narrow it with between, contains or fewer days.")
            if change_source == "SQL Logger history":
                notes.append(f"{name}'s plugin does not log its changes by name, so the "
                             f"changes come from the SQL Logger's record of its on/off and "
                             f"brightness states, which is written a moment after the change.")
            if history_note:
                notes.append(history_note)
            if not total:
                notes.append(f"No change to {name} was found in the window, in the event log"
                             + (" or the SQL Logger history" if self.history_reader else "")
                             + ". Indigo logs a device change only when the device or its "
                               "plugin logs it.")
            if hidden:
                names = [h["name"] for h in hidden]
                notes.append(
                    f"{_count(len(hidden), 'automation that can change', 'automations that can change')} "
                    f"{name} {'is' if len(hidden) == 1 else 'are'} set to stay out of the event "
                    f"log ({_join(names[:10])}{' and more' if len(names) > 10 else ''}), so "
                    f"{'its runs leave' if len(hidden) == 1 else 'their runs leave'} no line to "
                    f"match. Turn that off in the automation's own dialog to make its runs "
                    f"traceable.")
            notes.append("A cause is a likelihood from what ran just before the change and "
                         "whether it is linked to the device, never a certainty. A device's own "
                         "logging can lag its command by a few seconds.")
            result = {
                "hidden_from_event_log": hidden,
                "success": True,
                "device": {"id": device_id, "name": name},
                "window": {"days": days, "between": between, "contains": contains,
                           "lookback_seconds": lookback_seconds},
                "change_count": total,
                "change_source": change_source,
                "by_cause": summary,
                "events": events,
                "notes": notes,
                "log_scan": self.detail._scan_summary(meta),
            }
            self.log_tool_outcome("explain_device_changes", True,
                                  f"'{name}': {total} changes")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "explain_device_changes")


# ── Live providers ───────────────────────────────────────────────────────────

def _live_control_pages() -> List[Tuple[int, str]]:
    if indigo is None:
        return []
    return [(cp.id, cp.name) for cp in indigo.controlPages]


def _live_devices() -> List[Any]:
    if indigo is None:
        return []
    return list(indigo.devices)
