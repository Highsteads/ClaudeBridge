#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    automations.py
# Description: Trigger, schedule and action-group tools — listing, reading the
#              full definition, firing, enabling, editing and deleting.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..registry import tool
from ._schema import (AUTOMATION_ID, AUTOMATION_KIND, AUTOMATION_KINDS, bad_choice, boolean,
                      coerce_bool, enum, id_or_name, number, refuse, string)
from .devices import resolve_device

def _check_kind(kind, allowed=AUTOMATION_KINDS):
    return None if kind in allowed else bad_choice("kind", kind, allowed)


# ── Listing ──────────────────────────────────────────────────────────────────

@tool("list_action_groups", scope="read", cacheable=True, reads={"action_group"},
      description="List all action groups")
def list_action_groups(ctx):
    return ctx.list_handlers.list_all_action_groups()


@tool("list_schedules", scope="read", cacheable=True, reads={"schedule"},
      description=("List all Indigo schedules with their ID, name, enabled state, and next "
                   "scheduled execution time."))
def list_schedules(ctx):
    return ctx.schedule_control_handler.list_schedules()


@tool("list_triggers", scope="read", cacheable=True, reads={"trigger"},
      description=("List all Indigo triggers with their ID, name, enabled state, and plugin "
                   "type information."))
def list_triggers(ctx):
    return ctx.schedule_control_handler.list_triggers()


# ── Reading one automation ───────────────────────────────────────────────────

@tool("get_automation", scope="read",
      description=("Full definition of one trigger, schedule or action group: event settings "
                   "(triggers), decoded timing (schedules: time/date type, sun offsets, repeat "
                   "interval), conditions, and the ACTION STEPS — device commands, variable "
                   "sets, embedded and linked scripts, plugin actions — that the IOM does not "
                   "expose. Read from Indigo's database file, so very recent edits may lag by "
                   "a few minutes."),
      properties={
          "kind": AUTOMATION_KIND,
          "id": AUTOMATION_ID,
          "include_scripts": boolean("Include embedded script source (default true; false "
                                     "returns line counts only)"),
      },
      required=["kind", "id"])
def get_automation(ctx, kind, id, include_scripts=True):
    refusal = _check_kind(kind)
    if refusal:
        return refusal
    return ctx.automation_detail_handler.get_details(
        kind, id, include_scripts=coerce_bool(include_scripts))


_DEPENDENCY_KINDS = ("device", "variable") + AUTOMATION_KINDS


@tool("get_dependencies", scope="read",
      description=("Indigo's own getDependencies() for one object: which devices, variables, "
                   "triggers, schedules, action groups and control pages the server records as "
                   "depending on it. Useful before deleting. For a device or variable, "
                   "find_automation_references is richer: it tags each reference with its role, "
                   "follows action-group chains and scans scripts, none of which the server's "
                   "own graph covers."),
      properties={
          "kind": enum(_DEPENDENCY_KINDS, "Which kind of object"),
          "id": id_or_name("Numeric id (preferred) or exact name"),
      },
      required=["kind", "id"])
def get_dependencies(ctx, kind, id):
    refusal = _check_kind(kind, _DEPENDENCY_KINDS)
    if refusal:
        return refusal
    result = ctx.extended_tools_handler.get_dependencies(kind, id)
    if kind in ("device", "variable") and isinstance(result, dict) and result.get("success"):
        result["see_also"] = ("find_automation_references gives role-tagged references, "
                              "action-group chains and script mentions for this "
                              f"{kind}; the server's graph above has none of those")
    return result


@tool("find_automation_references", scope="read",
      description=("Reverse lookup: which triggers/schedules/action groups reference a device, "
                   "variable, or action group — role-tagged (watches / condition_reads / "
                   "acts_on / sets / executes) and following action-group execution chains "
                   "transitively. Cross-checked against the server's own dependency graph, AND "
                   "against both Python script folders on disk (entity_type 'script', role "
                   "'script_reference', with line numbers) which getDependencies does not "
                   "cover. Also text-scans EMBEDDED scripts — scripted conditions, "
                   "trigger/schedule action scripts and action-group scripts — by numeric ID and "
                   "by quoted name; those hits carry confidence 'heuristic'. Plugins that "
                   "hard-code an ID in their own source remain uncovered. Richer than "
                   "get_dependencies for automation debugging and safe-delete checks."),
      properties={
          "entity_type": enum(["device", "variable", "action_group"],
                              "Kind of entity to find references to"),
          "entity_id": number("Numeric entity ID"),
          "include_server_check": boolean("Also merge indigo getDependencies results "
                                          "(default true)"),
          "include_scripts": boolean("Also scan the Scripts and Python Scripts folders for the "
                                     "ID and the quoted name (default true)"),
      },
      required=["entity_type", "entity_id"])
def find_automation_references(ctx, entity_type, entity_id, include_server_check=True,
                               include_scripts=True):
    return ctx.automation_detail_handler.find_automation_references(
        entity_type, entity_id,
        include_server_check=coerce_bool(include_server_check),
        include_scripts=coerce_bool(include_scripts))


@tool("investigate_event", scope="read",
      description=("Answer 'what caused this device change?' — finds the change in the event "
                   "log, collects trigger/schedule/action-group activity in a window around it, "
                   "and ranks candidates by temporal proximity plus structural evidence (does "
                   "the automation actually act on the device, directly or through action-group "
                   "chains?). Reports likelihood with evidence, never certainty."),
      properties={
          "device_id": number("Device whose change to investigate (or use search_text)"),
          "search_text": string("Log-line fragment to locate the target event instead of "
                                "device_id"),
          "around_time": string("Investigate the match nearest this time (HH:MM[:SS] today, "
                                "or full YYYY-MM-DD HH:MM:SS)"),
          "occurrence": number("1 = most recent match, 2 = one before, ... (default 1)"),
          "lookback_seconds": number("Candidate window before the event (default 60)"),
          "lookahead_seconds": number("Candidate window after the event (default 5)"),
          "search_days": number("How many days of logs to search for the target event "
                                "(default 2, max 14)"),
      })
def investigate_event(ctx, device_id=None, search_text=None, around_time=None, occurrence=1,
                      lookback_seconds=60, lookahead_seconds=5, search_days=2):
    return ctx.automation_detail_handler.investigate_event(
        device_id=device_id, search_text=search_text, around_time=around_time,
        occurrence=occurrence, lookback_seconds=lookback_seconds,
        lookahead_seconds=lookahead_seconds, search_days=search_days)


# ── Running ──────────────────────────────────────────────────────────────────

@tool("action_execute_group", scope="write",
      invalidates={"action_group", "device", "variable"},
      description="Execute an action group",
      properties={"action_group_id": id_or_name("The ID of the action group"),
                  "delay": number("Optional delay in seconds")},
      required=["action_group_id"])
def action_execute_group(ctx, action_group_id, delay=None):
    return ctx.action_control_handler.execute(action_group_id, delay)


@tool("execute_schedule_now", scope="write", invalidates={"schedule", "device", "variable"},
      description=("Execute a schedule immediately. ignore_conditions=True bypasses the "
                   "schedule's own conditions."),
      properties={"schedule_id": id_or_name("Schedule ID"),
                  "ignore_conditions": boolean("Bypass the schedule's conditions (default "
                                               "false)")},
      required=["schedule_id"])
def execute_schedule_now(ctx, schedule_id, ignore_conditions=False):
    return ctx.extended_tools_handler.execute_schedule_now(
        schedule_id, ignore_conditions=ignore_conditions)


@tool("fire_trigger", scope="write", invalidates={"device", "variable"},
      description=("Execute a single Indigo trigger directly by ID or name "
                   "(indigo.trigger.execute). Use this when you want to invoke a specific "
                   "trigger's actions without going through the event system used by "
                   "fire_indigo_event."),
      properties={"trigger_id": id_or_name("Trigger ID (number) or trigger name (string)")},
      required=["trigger_id"])
def fire_trigger(ctx, trigger_id):
    return ctx.schedule_control_handler.fire_trigger(trigger_id)


@tool("fire_indigo_event", scope="write", invalidates={"device", "variable"},
      description=("Fire all Indigo Triggers of type 'Claude Bridge → Claude Event' with a "
                   "structured payload. Use this to drive Indigo automations from a Claude tool "
                   "call. Inside the user's Trigger actions, the payload is available via "
                   "Indigo's event-data substitution %%e:\"name\"%%, %%e:\"data\"%%, "
                   "%%e:\"source\"%%. Users filter on event name with a Script Condition testing "
                   "event_data.get('name')."),
      properties={
          "name": string("Short event name (e.g. 'sunset_routine', 'leak_detected'). Triggers "
                         "can filter on this via a Script Condition on event_data."),
          "data": {"type": "object",
                   "description": ("Optional structured payload. Serialised to JSON and "
                                   "exposed as %%e:\"data\"%%.")},
          "source": string("Origin label, default 'claude'. Useful when multiple agents or "
                           "scripts share the event channel."),
      },
      required=["name"])
def fire_indigo_event(ctx, name, data=None, source="claude"):
    if not ctx.plugin or not hasattr(ctx.plugin, "fire_claude_event"):
        return {"error": "Plugin reference unavailable — cannot fire events"}
    return ctx.plugin.fire_claude_event(name, data, source)


# ── Changing ─────────────────────────────────────────────────────────────────

@tool("set_enabled", scope="write", invalidates={"trigger", "schedule"},
      description=("Enable or disable a trigger or schedule, by id or name. Optionally delay "
                   "the change (delay_seconds) and/or revert it automatically after "
                   "duration_seconds — e.g. silence a motion trigger for 30 minutes."),
      properties={
          "kind": enum(["trigger", "schedule"], "trigger or schedule"),
          "id": AUTOMATION_ID,
          "enabled": boolean("true to enable, false to disable"),
          "delay_seconds": number("Seconds to wait before changing (optional)"),
          "duration_seconds": number("Revert automatically after this many seconds "
                                     "(optional)"),
      },
      required=["kind", "id", "enabled"])
def set_enabled(ctx, kind, id, enabled, delay_seconds=None, duration_seconds=None):
    refusal = _check_kind(kind, ("trigger", "schedule"))
    if refusal:
        return refusal
    sc = ctx.schedule_control_handler
    verb = "enable" if coerce_bool(enabled) else "disable"
    return getattr(sc, f"{verb}_{kind}")(id, delay_seconds=delay_seconds,
                                         duration_seconds=duration_seconds)


@tool("update_automation", scope="write", invalidates={"trigger", "schedule", "action_group"},
      description=("Edit an automation's basic fields and return before/after. Every kind: name "
                   "and description. A trigger watching a device state or a variable can also "
                   "have its event re-pointed: device_id, state_selector, state_change_type, "
                   "state_value, variable_id, variable_change_type, variable_value (change types "
                   "accept e.g. 'becomes_true', 'becomes_false', 'changes'). Schedule timing, "
                   "action steps and conditions cannot be edited through the API (Indigo UI "
                   "only)."),
      properties={
          "kind": AUTOMATION_KIND,
          "id": AUTOMATION_ID,
          "fields": {"type": "object",
                     "description": "Fields to change, e.g. {\"name\": \"New name\"}"},
      },
      required=["kind", "id", "fields"])
def update_automation(ctx, kind, id, fields):
    refusal = _check_kind(kind)
    if refusal:
        return refusal
    return getattr(ctx.schedule_control_handler, f"update_{kind}")(id, fields)


@tool("delete_automation", scope="admin", destructive=True, refresh_search=True,
      invalidates={"trigger", "schedule", "action_group"},
      description="Permanently delete a trigger, schedule or action group.",
      properties={"kind": AUTOMATION_KIND, "id": id_or_name("Numeric id")},
      required=["kind", "id"])
def delete_automation(ctx, kind, id):
    refusal = _check_kind(kind)
    if refusal:
        return refusal
    return getattr(ctx.extended_tools_handler, f"delete_{kind}")(id)


@tool("remove_delayed_actions", scope="admin", invalidates={"device", "schedule"},
      description=("Cancel pending delayed actions. kind='device' cancels them for ONE device "
                   "(e.g. a queued auto-off from device_control duration), leaving others alone; "
                   "kind='schedule' for one schedule; kind='all' removes every pending delayed "
                   "action on the server — confirm with the user first."),
      properties={
          "kind": enum(["device", "schedule", "all"], "What to clear"),
          "id": id_or_name("Device id or name, or schedule id (not used for 'all')"),
      },
      required=["kind"])
def remove_delayed_actions(ctx, kind, id=None):
    refusal = _check_kind(kind, ("device", "schedule", "all"))
    if refusal:
        return refusal
    ext = ctx.extended_tools_handler
    if kind == "all":
        if id is not None:
            return refuse("remove_delayed_actions: id does not apply to kind 'all'")
        return ext.remove_all_delayed_actions()
    if id is None:
        return refuse(f"remove_delayed_actions: kind '{kind}' needs id")
    if kind == "device":
        device_id, match, refusal = resolve_device(ctx, id)
        if refusal:
            return refusal
        result = ext.device_remove_delayed_actions(device_id)
        if isinstance(result, dict):
            result.update(match)
        return result
    return ext.schedule_remove_delayed_actions(id)
