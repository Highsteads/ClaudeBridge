#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    devices.py
# Description: Device tools — finding, reading and controlling devices.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import time
from typing import Any, Dict, List, Optional, Tuple

from ..common import device_capabilities
from ..common.indigo_device_types import DeviceTypeResolver, IndigoDeviceType, IndigoEntityType
from ..registry import tool
from ..tools.device_control.color_names import parse_color
from ._schema import (DELAY, DEVICE, DURATION, bad_choice, boolean, coerce_bool, enum,
                      id_or_name, number, refuse, string, unused_args)

_DEVICE_TYPES_HELP = ("Valid types: dimmer, relay, sensor, multiio, speedcontrol, sprinkler, "
                      "thermostat, device. Aliases supported: light→dimmer, switch→relay, "
                      "motion→sensor, fan→speedcontrol, etc.")


# ── Shared helpers ───────────────────────────────────────────────────────────

def enrich_device_capabilities(device):
    """Attach a capabilities block to a serialised device dict, in place, read
    live off the device (``supports*`` flags). Advisory metadata — absent when
    the device cannot be resolved or exposes no flags."""
    if not isinstance(device, dict):
        return device
    try:
        import indigo
        dev = indigo.devices[device["id"]]
    except Exception:
        return device
    caps = device_capabilities.live_capabilities(dev)
    if caps:
        device["capabilities"] = caps
    return device


def device_group(device_id) -> Optional[List[Dict[str, Any]]]:
    """Every device in this one's Indigo group, itself included (a
    multi-endpoint Z-Wave node, a camera's detection sensors), oldest — the
    group's root — first. None when the device stands alone or the group
    cannot be read."""
    try:
        import indigo
        ids = list(indigo.device.getGroupList(int(device_id)))
    except Exception:
        return None
    if len(ids) < 2:
        return None
    members = []
    for member in ids:
        try:
            name = indigo.devices[member].name
        except Exception:
            name = None
        members.append({"id": member, "name": name})
    return members


def compact_device(device: Any) -> Any:
    """One device without the repeats, in place.

    dict(dev) carries the owning plugin's props three times over (pluginProps,
    ownerProps and that plugin's entry in globalProps), the supports* flags
    both at the top level and in `capabilities`, and a dozen properties that
    are simply null on most devices. What goes:
      - ownerProps, when it matches pluginProps (kept when it differs — it can
        be stale, and the difference is then worth seeing);
      - globalProps; other plugins' props, if any, stay as otherPluginProps;
      - empty sharedProps, and top-level flags repeated in capabilities;
      - properties whose value is null.
    detail="full" on the tools returns the device untouched.
    """
    if not isinstance(device, dict):
        return device
    owner = device.get("pluginId") or ""
    props = device.get("pluginProps")
    if device.get("ownerProps") == props:
        device.pop("ownerProps", None)
    global_props = device.pop("globalProps", None)
    if isinstance(global_props, dict):
        others = {pid: scoped for pid, scoped in global_props.items()
                  if pid != owner and scoped}
        if others:
            device["otherPluginProps"] = others
    if not device.get("sharedProps"):
        device.pop("sharedProps", None)
    for flag, value in (device.get("capabilities") or {}).items():
        if device.get(flag) == value:
            device.pop(flag, None)
    for key in [k for k, v in device.items() if v is None]:
        device.pop(key)
    return device


def present_device(device: Any, detail: Optional[str]) -> Any:
    """What get_device_by_id / get_device_by_name return for one device."""
    device = enrich_device_capabilities(device)
    if isinstance(device, dict) and "id" in device:
        group = device_group(device["id"])
        if group:
            device["group"] = group
    return device if detail == "full" else compact_device(device)


# The lowest score that means every word of the name was found in the device's
# name: 1.0 for the whole phrase, 0.95 for all the words in any order. Anything
# lower is a spelling-similarity or synonym guess, and a guess never switches a
# device — asking for a "Landing Two" that does not exist must not switch
# "Landing One" because the two names look alike.
_CONTROL_MIN_SCORE = 0.95


def resolve_device_for_control(name: str, devices: List[Dict[str, Any]]):
    """Pick the ONE device a spoken name means, or refuse.

    Acts on a single exact-name match, or else on a single candidate scoring
    0.5 or more — and then only when that candidate contains every word of the
    name (score 0.95 or more). A lone looser match is refused with the
    candidate named, never acted on. Until 2.27.3 it took the top hit whenever
    that scored 0.5, and any name merely containing the words scores 1.0 — so
    with two "Hall Lamp..." devices it could switch whichever the search listed
    first. Returns (device, None) or (None, refusal).
    """
    def _cands(items):
        return [{"id": d.get("id"), "name": d.get("name"),
                 "score": d.get("relevance_score")} for d in items[:5]]

    wanted = (name or "").strip().lower()
    exact = [d for d in devices if str(d.get("name", "")).strip().lower() == wanted]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, {"success": False,
                      "error": f"{len(exact)} devices are called '{name}'; "
                               f"use the device id instead",
                      "candidates": _cands(exact)}
    confident = [d for d in devices if (d.get("relevance_score") or 0) >= 0.5]
    if len(confident) == 1:
        only = confident[0]
        score = only.get("relevance_score") or 0
        if score >= _CONTROL_MIN_SCORE:
            return only, None
        return None, {"success": False,
                      "error": f"No device is called '{name}'. The nearest is "
                               f"'{only.get('name')}' (score {score:.2f}), which is only a "
                               f"loose match, so nothing was switched. Use its exact name "
                               f"or its device id if that is the one you mean.",
                      "candidates": _cands(confident)}
    if not confident:
        top = devices[0]
        return None, {"success": False,
                      "error": f"No confident match for '{name}' (best: "
                               f"'{top.get('name')}' score="
                               f"{(top.get('relevance_score') or 0):.2f})",
                      "suggestions": [d.get("name") for d in devices[:3]]}
    return None, {"success": False,
                  "error": f"'{name}' matches {len(confident)} devices; nothing "
                           f"was switched. Use the full name or the device id.",
                  "candidates": _cands(confident)}


_RESOLVE_TOP_K = 50


def resolve_device(ctx, device) -> Tuple[Optional[int], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Turn a `device` argument (id or name) into a device id.

    Returns (device_id, match_info, refusal). match_info is non-empty only when
    a name was resolved, and names what was matched so the reply can say so.
    """
    if device is None or isinstance(device, bool) or (isinstance(device, str) and not device.strip()):
        return None, {}, refuse("device is required: a device id or its name")
    if isinstance(device, (int, float)):
        if float(device).is_integer():
            return int(device), {}, None
        return None, {}, refuse(f"device id must be a whole number, got {device!r}")
    text = str(device).strip()
    if text.lstrip("-").isdigit():
        return int(text), {}, None
    # A fixed top_k: without it, words in the NAME ("one", "all", "list"...)
    # set the result count, and "Landing One" came back as one hit that could
    # be "Landing One Nightlight" instead of the device called exactly that.
    found = ctx.search_handler.search(query=text, entity_types=["devices"], detail="slim",
                                      top_k=_RESOLVE_TOP_K)
    devices = (found.get("results") or {}).get("devices") or []
    if not devices:
        return None, {}, refuse(f"No device found matching '{text}'")
    top, refusal = resolve_device_for_control(text, devices)
    if refusal:
        return None, {}, refusal
    return top["id"], {"matched_device": top.get("name"),
                       "match_score": top.get("relevance_score")}, None


def _error_text(result: Any) -> str:
    return str(result.get("error")) if isinstance(result, dict) else str(result)


def _with_match(result: Any, match: Dict[str, Any]) -> Any:
    if isinstance(result, dict) and match:
        result.update(match)
    return result


def _resolve_types(device_types) -> Tuple[Optional[List[str]], Optional[Dict[str, Any]]]:
    """Resolve device-type aliases, or return a refusal with suggestions."""
    resolved, invalid = DeviceTypeResolver.resolve_device_types(device_types)
    if not invalid:
        return resolved, None
    parts = [f"Invalid device types: {invalid}",
             f"Valid types: {IndigoDeviceType.get_all_types()}"]
    for bad in invalid:
        suggestions = DeviceTypeResolver.get_suggestions_for_invalid_type(bad)
        if suggestions:
            parts.append(f"Did you mean: {', '.join(suggestions)}")
    return None, refuse(" | ".join(parts))


# ── Reading ──────────────────────────────────────────────────────────────────

@tool("search_entities", scope="read", cacheable=True,
      reads={"device", "variable", "action_group"},
      description=("Search for Indigo entities using natural language. Results are slim by "
                   "default (id, name, state, lastChanged). Use detail='full' only when you "
                   "need complete device properties such as Z-Wave config or plugin props."),
      properties={
          "query": string("Natural language search query"),
          "device_types": {"type": "array", "items": {"type": "string"},
                           "description": "Optional device types to filter. " + _DEVICE_TYPES_HELP},
          "entity_types": {"type": "array",
                           "items": {"type": "string", "enum": ["device", "variable", "action"]},
                           "description": ("Optional entity types to search: device, variable, "
                                           "action (singular; 'action' means action groups). "
                                           "Omit to search all three.")},
          "state_filter": {"type": "object",
                           "description": "Optional state conditions to filter results"},
          "detail": enum(["slim", "full"],
                         "Result detail level. 'slim' (default) returns id/name/state/lastChanged "
                         "only — fast. 'full' returns complete device objects including all "
                         "plugin and Z-Wave properties."),
      },
      required=["query"])
def search_entities(ctx, query, device_types=None, entity_types=None,
                    state_filter=None, detail="slim"):
    # A bare string ("light") iterated letter by letter into "l", "i", "g"...
    if isinstance(device_types, str):
        device_types = [device_types]
    if device_types:
        device_types, refusal = _resolve_types(device_types)
        if refusal:
            refusal["query"] = query
            return refusal
    if entity_types:
        if isinstance(entity_types, str):
            entity_types = [entity_types]
        entity_types = [IndigoEntityType.normalise(et) for et in entity_types]
        invalid = [et for et in entity_types if not IndigoEntityType.is_valid_type(et)]
        if invalid:
            return refuse(f"Invalid entity types: {invalid} | "
                          f"Valid types: {IndigoEntityType.get_all_types()}", query=query)
    ctx.logger.info(f"[search_entities]: query: '{query}', device_types: {device_types}, "
                    f"entity_types: {entity_types}, state_filter: {state_filter}")
    return ctx.search_handler.search(query, device_types, entity_types, state_filter,
                                     detail=detail)


@tool("list_devices", scope="read", cacheable=True, reads={"device"},
      description=("List devices. With no arguments, every device, which is large on a big "
                   "estate — prefer a filter or `fields`. device_type narrows to one type "
                   "(aliases accepted), plugin_id to one plugin's devices, folder to one device "
                   "folder (id or name), and state_filter to devices whose states match, e.g. "
                   "{\"onState\": true} or {\"heatIsOn\": true}. fields returns just id, name "
                   "and the properties or states named, e.g. [\"address\", \"batteryLevel\"]. "
                   "Any filter returns count, total_matched and truncated, and limit caps the "
                   "list (default 200)."),
      properties={
          "device_type": string("Optional device type. " + _DEVICE_TYPES_HELP),
          "plugin_id": string("Optional: only devices owned by this plugin bundle id"),
          "folder": id_or_name("Optional: only devices in this device folder (id or name; "
                               "0 is the top level)"),
          "fields": {"type": "array", "items": {"type": "string"},
                     "description": ("Optional: return id, name and only these. Each is a "
                                     "device property (address, pluginId, folderId, enabled, "
                                     "lastChanged...) or a state name (case-sensitive).")},
          "state_filter": {"type": "object",
                           "description": ("Optional state conditions using Indigo state names, "
                                           "e.g. {\"onState\": true}, "
                                           "{\"temperature\": {\"gt\": 21}}")},
          "limit": {"type": "integer",
                    "description": "Max devices when filtering (default 200)"},
          "detail": enum(["slim", "full"],
                         "device_type only: 'slim' (default) short rows, 'full' every "
                         "property"),
      })
def list_devices(ctx, device_type=None, state_filter=None, limit=None, detail=None,
                 plugin_id=None, folder=None, fields=None):
    if plugin_id is not None or folder is not None or fields is not None:
        return _list_devices_filtered(ctx, device_type, state_filter, limit, detail,
                                      plugin_id, folder, fields)
    if detail is not None and not (device_type and not state_filter):
        return refuse("list_devices: detail applies only with device_type alone")
    if not device_type and not state_filter:
        if limit is not None:
            return refuse("limit applies only with device_type or state_filter — "
                          "call list_devices with no arguments for every device")
        return ctx.list_handlers.list_all_devices()
    if device_type and not state_filter:
        if detail is not None and detail not in ("slim", "full"):
            return bad_choice("detail", detail, ("slim", "full"))
        kwargs = {"limit": 200 if limit is None else limit}
        if detail is not None:
            kwargs["detail"] = detail
        return ctx.get_devices_by_type_handler.get_devices(device_type, **kwargs)
    types = None
    if device_type:
        types, refusal = _resolve_types([device_type])
        if refusal:
            return refusal
    result = ctx.list_handlers.get_devices_by_state(state_filter, types)
    try:
        cap = max(1, int(200 if limit is None else limit))
    except (TypeError, ValueError):
        cap = 200
    devices = result.get("devices") or []
    result["total_matched"] = len(devices)
    result["truncated"] = len(devices) > cap
    result["limit"] = cap
    result["devices"] = devices[:cap]
    result["count"] = len(result["devices"])
    return result


def _list_devices_filtered(ctx, device_type, state_filter, limit, detail,
                           plugin_id, folder, fields):
    if detail is not None:
        return refuse("list_devices: detail does not combine with plugin_id, folder or "
                      "fields — fields chooses what each row carries")
    if isinstance(fields, str):
        fields = [fields]
    if fields is not None and (not isinstance(fields, list)
                               or not all(isinstance(f, str) and f.strip() for f in fields)):
        return refuse("fields must be a list of property or state names")
    if fields is not None and not fields:
        return refuse("fields is empty — leave it out for the standard rows")
    if plugin_id is not None and not str(plugin_id).strip():
        return refuse("plugin_id is empty")
    types = None
    if device_type:
        types, refusal = _resolve_types([device_type])
        if refusal:
            return refusal
    folder_id = None
    if folder is not None:
        folder_id, problem = ctx.list_handlers.resolve_device_folder(folder)
        if problem:
            return refuse(problem)
    try:
        cap = max(1, int(200 if limit is None else limit))
    except (TypeError, ValueError):
        return refuse(f"limit must be a whole number, got {limit!r}")
    return ctx.list_handlers.list_devices_filtered(
        device_types=types, state_filter=state_filter,
        plugin_id=None if plugin_id is None else str(plugin_id).strip(),
        folder_id=folder_id, fields=[f.strip() for f in fields] if fields else None,
        limit=cap)


_ONE_DEVICE_DETAIL = enum(
    ["compact", "full"],
    "'compact' (default) gives the owning plugin's props once as pluginProps, other "
    "plugins' props as otherPluginProps, and leaves out null properties and repeated "
    "flags. 'full' is the raw device with every props block.")


def _check_one_device_detail(detail):
    if detail is not None and detail not in ("compact", "full"):
        return bad_choice("detail", detail, ("compact", "full"))
    return None


@tool("get_device_by_id", scope="read", cacheable=True, reads={"device"},
      description=("Get a specific device by ID: its properties, states, props and "
                   "capabilities, plus `group` (the devices Indigo groups it with, root "
                   "first) when it is part of one."),
      properties={"device_id": id_or_name("The device ID"),
                  "detail": _ONE_DEVICE_DETAIL},
      required=["device_id"])
def get_device_by_id(ctx, device_id, detail=None):
    refusal = _check_one_device_detail(detail)
    if refusal:
        return refusal
    device_id = int(device_id)
    device = ctx.data_provider.get_device(device_id)
    if device is None:
        return {"error": f"Device {device_id} not found"}
    return present_device(device, detail)


@tool("get_device_by_name", scope="read",
      description=("Find a device by name and return its full state in one round trip. Tries "
                   "exact match, then case-insensitive, then partial match. Returns all device "
                   "states, properties, and current values, like get_device_by_id."),
      properties={"name": string("Device name (exact, partial, or case-insensitive)"),
                  "detail": _ONE_DEVICE_DETAIL},
      required=["name"])
def get_device_by_name(ctx, name, detail=None):
    refusal = _check_one_device_detail(detail)
    if refusal:
        return refusal
    result = ctx.data_provider.get_device_by_name(name)
    if result is None:
        return refuse(f"No device found matching '{name}'")
    if isinstance(result, dict) and "error" in result:
        # An ambiguous name is a refusal with candidates, not a device.
        return {"success": False, **result}
    return {"success": True, "device": present_device(result, detail)}


@tool("device_history", scope="read",
      description=("Read recent SQL Logger history for one device. Returns timestamp + "
                   "non-null state columns. Column names are stored LOWERCASE (batterysoc, not "
                   "batterySoc); an unknown name is an error listing the valid columns. Rows are "
                   "sparse — only changed values are written, so forward-fill before deriving "
                   "trends. `limit` caps rows from the NEWEST end, so on a chatty device it can "
                   "cut the window far shorter than `hours` — check `truncated` and the "
                   "`ts_oldest`/`ts_newest` span before concluding anything about earlier "
                   "events."),
      properties={
          "device_id": id_or_name("The device ID"),
          "hours": number("Lookback in hours (default 24)"),
          "limit": number("Max rows (default 500, max 5000)"),
          "columns": {"type": "array", "items": {"type": "string"},
                      "description": "Optional list of column names to return"},
          "summary": boolean("Instead of rows: rows per day, and per column how many rows "
                             "carry a value (how often that state was written) with its "
                             "min and max, busiest first. limit does not apply; the newest "
                             "250,000 rows at most are counted (default false)"),
      },
      required=["device_id"])
def device_history(ctx, device_id, hours=24, limit=500, columns=None, summary=False):
    return ctx.plugin_dev_tools_handler.device_history(
        device_id, hours=hours, limit=limit, columns=columns,
        summary=coerce_bool(summary))


# ── Control ──────────────────────────────────────────────────────────────────

_DEVICE_ACTIONS = ("on", "off", "toggle", "brightness", "brighten", "dim", "color",
                   "status_request", "beep", "ping", "reset_energy")

_ACTION_ARGS = {
    "on": ("delay", "duration"), "off": ("delay", "duration"),
    "brightness": ("value",), "brighten": ("value",), "dim": ("value",),
    "color": ("color", "red", "green", "blue", "white", "white_temperature"),
}


@tool("device_control", scope="write", invalidates={"device"},
      description=(
          "Control one device, by id or by name. action: on / off (optional delay, and "
          "duration to revert automatically — 'fan on for 10 minutes' is duration=600), "
          "toggle, brightness (value 0-100), brighten / dim (value = percentage points, "
          "more than 0), "
          "color (a 'color' hex code or CSS name such as 'dodgerblue', or red/green/blue "
          "0-255, plus optional white 0-100 and white_temperature in Kelvin), status_request (poll the "
          "device), beep (to find it physically), ping (reachability), reset_energy (zero "
          "the kWh total; the old total is returned but cannot be restored). A name must "
          "match exactly or match one device confidently, otherwise nothing is switched and "
          "the candidates come back."),
      properties={
          "device": DEVICE,
          "action": enum(_DEVICE_ACTIONS, "What to do"),
          "value": number("brightness: level 0-100. brighten/dim: percentage points"),
          "color": string("color action: hex (#RRGGBB, #RGB) or a CSS colour name; takes "
                          "precedence over red/green/blue. British 'grey' spellings accepted"),
          "red": number("Red channel 0-255"),
          "green": number("Green channel 0-255"),
          "blue": number("Blue channel 0-255"),
          "white": number("White level 0-100 (RGBW only)"),
          "white_temperature": number("Colour temperature in Kelvin, 1200-15000 (e.g. "
                                      "2700 warm, 6500 cool)"),
          "delay": DELAY,
          "duration": DURATION,
      },
      required=["device", "action"])
def device_control(ctx, device, action, value=None, color=None, red=None, green=None,
                   blue=None, white=None, white_temperature=None, delay=None, duration=None):
    t_start = time.perf_counter()
    if action not in _DEVICE_ACTIONS:
        return bad_choice("action", action, _DEVICE_ACTIONS)
    stray = unused_args("device_control", action,
                        {"value": value, "color": color, "red": red, "green": green,
                         "blue": blue, "white": white, "white_temperature": white_temperature,
                         "delay": delay, "duration": duration},
                        _ACTION_ARGS.get(action, ()))
    if stray:
        return stray
    if action in ("brightness", "brighten", "dim") and value is None:
        return refuse(f"device_control: action '{action}' needs value")
    if action in ("brighten", "dim"):
        try:
            points = float(value)
        except (TypeError, ValueError):
            points = None
        if isinstance(value, bool) or points is None or points <= 0:
            other = "dim" if action == "brighten" else "brighten"
            return refuse(f"device_control: {action} needs a positive value in percentage "
                          f"points, got {value!r} — use {other} to go the other way")

    device_id, match, refusal = resolve_device(ctx, device)
    if refusal:
        return refusal

    dc = ctx.device_control_handler
    ext = ctx.extended_tools_handler
    if action == "on":
        result = dc.turn_on(device_id, delay=delay or 0, duration=duration or 0)
    elif action == "off":
        result = dc.turn_off(device_id, delay=delay or 0, duration=duration or 0)
    elif action == "toggle":
        # Indigo decides the direction. The search snapshot is rebuilt on a 300 s
        # interval, so deciding here could invert the command for five minutes.
        result = ext.device_toggle(device_id)
    elif action == "brightness":
        result = dc.set_brightness(device_id, value)
    elif action == "brighten":
        result = ext.dimmer_brighten_by(device_id, value)
    elif action == "dim":
        result = ext.dimmer_dim_by(device_id, value)
    elif action == "color":
        if color is not None:
            try:
                red, green, blue = parse_color(color)
            except ValueError as ce:
                return refuse(str(ce))
        if red is None or green is None or blue is None:
            return refuse("Provide either a 'color' string (hex or CSS name) "
                          "or all three of red/green/blue (0-255).")
        result = dc.set_color(device_id, red, green, blue,
                              white=white, white_temperature=white_temperature)
    elif action == "status_request":
        result = dc.request_status_update(device_id)
    elif action == "beep":
        result = ext.beep_device(device_id)
    elif action == "ping":
        result = ext.ping_device(device_id)
    else:
        result = ext.reset_energy_accumulator(device_id)
    result = _with_match(result, match)
    if match and isinstance(result, dict):
        result["elapsed_ms"] = round((time.perf_counter() - t_start) * 1000)
    return result


_HVAC_MODES = ["heat", "cool", "auto", "off", "programHeat", "programCool", "programAuto"]


@tool("thermostat_control", scope="write", invalidates={"device"},
      description=("Change a thermostat or TRV (e.g. RAMSES, Evohome). Give any combination "
                   "of heat_setpoint, cool_setpoint, heat_delta, cool_delta (step up with a "
                   "positive number, down with a negative one), hvac_mode and fan_mode. "
                   "Temperatures are in the device's own unit, as Indigo shows it; a value "
                   "outside a sane band for that unit is refused, never clamped. They are "
                   "applied in that order and the reply lists what was done, with "
                   "confirmed=false where the device has not reported the new value yet; "
                   "the first failure stops the rest."),
      properties={
          "device": DEVICE,
          "heat_setpoint": number("Target heat temperature, in the device's own unit"),
          "cool_setpoint": number("Target cool temperature, in the device's own unit"),
          "heat_delta": number("Degrees to raise (+) or lower (-) the heat setpoint"),
          "cool_delta": number("Degrees to raise (+) or lower (-) the cool setpoint"),
          "hvac_mode": enum(_HVAC_MODES, "HVAC operating mode"),
          "fan_mode": enum(["auto", "alwaysOn", "always_on"], "Fan mode"),
      },
      required=["device"])
def thermostat_control(ctx, device, heat_setpoint=None, cool_setpoint=None, heat_delta=None,
                       cool_delta=None, hvac_mode=None, fan_mode=None):
    steps = [(k, v) for k, v in (("heat_setpoint", heat_setpoint),
                                  ("cool_setpoint", cool_setpoint),
                                  ("heat_delta", heat_delta), ("cool_delta", cool_delta),
                                  ("hvac_mode", hvac_mode), ("fan_mode", fan_mode))
             if v is not None]
    if not steps:
        return refuse("thermostat_control: give at least one of heat_setpoint, cool_setpoint, "
                      "heat_delta, cool_delta, hvac_mode, fan_mode")
    for key in ("heat_delta", "cool_delta"):
        val = dict(steps).get(key)
        if val is not None and not val:
            return refuse(f"thermostat_control: {key} must not be 0")

    device_id, match, refusal = resolve_device(ctx, device)
    if refusal:
        return refusal

    dc = ctx.device_control_handler
    done: List[Dict[str, Any]] = []
    for i, (key, val) in enumerate(steps):
        if key == "heat_setpoint":
            result = dc.set_heat_setpoint(device_id, val)
        elif key == "cool_setpoint":
            result = dc.set_cool_setpoint(device_id, val)
        elif key == "heat_delta":
            result = (dc.increase_heat_setpoint(device_id, val) if val > 0
                      else dc.decrease_heat_setpoint(device_id, abs(val)))
        elif key == "cool_delta":
            result = (dc.increase_cool_setpoint(device_id, val) if val > 0
                      else dc.decrease_cool_setpoint(device_id, abs(val)))
        elif key == "hvac_mode":
            result = dc.set_hvac_mode(device_id, val)
        else:
            result = ctx.extended_tools_handler.set_fan_mode(device_id, val)
        ok = (isinstance(result, dict) and result.get("success") is not False
              and "error" not in result)
        done.append({"step": key, "value": val, "result": result})
        if not ok:
            return _with_match({"success": False, "device_id": device_id,
                                "error": f"{key} failed: {_error_text(result)}",
                                "done": done[:-1], "failed": done[-1],
                                "not_attempted": [k for k, _ in steps[i + 1:]]}, match)
    return _with_match({"success": True, "device_id": device_id, "done": done}, match)


@tool("speed_control", scope="write", invalidates={"device"},
      description=("Set a fan or speed-control device. Give exactly one of level (0-100 "
                   "percent), index (0 off, 1 low, 2 medium, 3 high on a four-speed device; the "
                   "top index is the device's speedIndexCount minus one) or step (+1 or -1 to "
                   "move one index up or down). The reply gives the speed the device reports "
                   "afterwards."),
      properties={
          "device": DEVICE,
          "level": number("Speed level 0-100"),
          "index": number("Speed index, 0 up to the device's speedIndexCount minus one"),
          "step": number("+1 for one index faster, -1 for one slower"),
      },
      required=["device"])
def speed_control(ctx, device, level=None, index=None, step=None):
    given = [k for k, v in (("level", level), ("index", index), ("step", step)) if v is not None]
    if len(given) != 1:
        return refuse("speed_control: give exactly one of level, index or step"
                      + (f" — got {', '.join(given)}" if given else ""))
    if step is not None and step not in (1, -1):
        return refuse(f"speed_control: step must be +1 or -1, got {step!r}")
    device_id, match, refusal = resolve_device(ctx, device)
    if refusal:
        return refusal
    ext = ctx.extended_tools_handler
    if level is not None:
        result = ctx.device_control_handler.set_fan_speed(device_id, level)
    elif index is not None:
        result = ext.speedcontrol_set_index(device_id, index)
    elif step == 1:
        result = ext.speedcontrol_increase(device_id)
    else:
        result = ext.speedcontrol_decrease(device_id)
    return _with_match(result, match)


_SPRINKLER_ACTIONS = ("run", "stop", "pause", "resume", "next_zone", "previous_zone", "set_zone")


@tool("sprinkler_control", scope="write", invalidates={"device"},
      description=("Drive a sprinkler device: run the programme, stop, pause, resume, "
                   "next_zone, previous_zone, or set_zone with zone (1-based)."),
      properties={
          "device": DEVICE,
          "action": enum(_SPRINKLER_ACTIONS, "What to do"),
          "zone": number("Zone number, 1 up to the device's zone count (set_zone only)"),
      },
      required=["device", "action"])
def sprinkler_control(ctx, device, action, zone=None):
    if action not in _SPRINKLER_ACTIONS:
        return bad_choice("action", action, _SPRINKLER_ACTIONS)
    stray = unused_args("sprinkler_control", action, {"zone": zone},
                        ("zone",) if action == "set_zone" else ())
    if stray:
        return stray
    if action == "set_zone" and zone is None:
        return refuse("sprinkler_control: set_zone needs zone")
    device_id, match, refusal = resolve_device(ctx, device)
    if refusal:
        return refusal
    ext = ctx.extended_tools_handler
    if action == "set_zone":
        result = ext.sprinkler_set_zone(device_id, zone)
    else:
        result = getattr(ext, f"sprinkler_{action}")(device_id)
    return _with_match(result, match)


_BROADCASTS = {"lights_on": "all_lights_on", "lights_off": "all_lights_off",
               "all_off": "all_devices_off"}


@tool("all_devices", scope="write", invalidates={"device"},
      description=("Send one of Indigo's native broadcasts: lights_on, lights_off or all_off. "
                   "They reach native-protocol devices (Z-Wave/Insteon/X10) ONLY — devices owned "
                   "by plugins (zigbee2mqtt, Shelly, Tasmota) are NOT affected; switch those "
                   "individually or through an action group."),
      properties={"action": enum(list(_BROADCASTS), "Which broadcast")},
      required=["action"])
def all_devices(ctx, action):
    if action not in _BROADCASTS:
        return bad_choice("action", action, _BROADCASTS)
    return getattr(ctx.extended_tools_handler, _BROADCASTS[action])()


@tool("lock_control", scope="admin", invalidates={"device"},
      description=("Lock or unlock a Z-Wave or other lock device. Indigo's lock and unlock "
                   "commands take no PIN. The reply says whether the lock has reported the "
                   "new state yet (confirmed). ADMIN scope: this is physical security."),
      properties={
          "device": DEVICE,
          "action": enum(["lock", "unlock"], "lock or unlock"),
      },
      required=["device", "action"])
def lock_control(ctx, device, action):
    # No `code`: indigo.device.unlock takes no PIN (only delay and duration),
    # and passing one raised a TypeError. With it gone from the schema the
    # dispatcher refuses a `code` argument as unknown, naming the valid ones.
    if action not in ("lock", "unlock"):
        return bad_choice("action", action, ("lock", "unlock"))
    device_id, match, refusal = resolve_device(ctx, device)
    if refusal:
        return refusal
    dc = ctx.device_control_handler
    result = dc.lock_device(device_id) if action == "lock" else dc.unlock_device(device_id)
    return _with_match(result, match)


# ── Device housekeeping ──────────────────────────────────────────────────────

@tool("enable_device", scope="write", invalidates={"device"},
      description=("Enable or disable a device's communication. NOT the same as on/off — this "
                   "controls whether Indigo polls/listens to the device at all."),
      properties={
          "device_id": id_or_name("The device ID"),
          "value": boolean("True to enable, False to disable (default True)"),
          "enable": boolean("Alias of value — the name callers naturally reach for"),
      },
      required=["device_id"])
def enable_device(ctx, device_id, value=None, enable=None):
    # `enable` is an accepted alias for `value` (v2.12.1) — an explicit value
    # wins if a caller supplies both; the default remains True (enable).
    resolved = value if value is not None else (enable if enable is not None else True)
    return ctx.extended_tools_handler.enable_device(device_id, value=resolved)


@tool("rename_device", scope="write", invalidates={"device"}, refresh_search=True,
      description="Rename a device.",
      properties={"device_id": id_or_name("The device ID"),
                  "new_name": string("New device name")},
      required=["device_id", "new_name"])
def rename_device(ctx, device_id, new_name):
    return ctx.extended_tools_handler.rename_device(device_id, new_name)


@tool("delete_device", scope="admin", invalidates={"device"}, refresh_search=True,
      destructive=True,
      description="Permanently delete a device. Destructive — cannot be undone.",
      properties={"device_id": id_or_name("Device ID")},
      required=["device_id"])
def delete_device(ctx, device_id):
    return ctx.extended_tools_handler.delete_device(device_id)
