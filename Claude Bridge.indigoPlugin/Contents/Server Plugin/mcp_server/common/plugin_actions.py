#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_actions.py
# Description: Read a plugin's Actions.xml so a caller can be told what is
#              callable BEFORE dispatching, and refused when the call would
#              silently do nothing.
# Author:      CliveS & Claude Opus 5
# Date:        06-09-2026 08:26 BST
# Version:     1.0

"""
Why this exists at all.

`indigo.server.getPlugin(id).executeAction(actionTypeId, deviceId=0, props=None)`
is the only route to another plugin's own actions, and it fails SILENTLY in two
ways that are indistinguishable from success at the call site:

  1. An action declared with `deviceFilter=` is a DEVICE action. Called without
     a `deviceId` it returns None and does nothing at all. Measured 06-09-2026:
     `setTimerStartValue` with the device id moved the timer 60 -> 43 seconds;
     the identical call without it returned None and left it at 60. This is the
     whole of the long-standing "Email+ drops its props" folklore — the props
     arrive intact, the DEVICE is what was missing.

  2. A misspelt actionTypeId reaches no callback and also returns None.

Neither raises. So the only way to give a caller a real answer is to read the
plugin's own Actions.xml and check the call against it first.

Pure text in, dict out — no `indigo` import, so it runs under the test suite
with no live server.
"""

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# Field types that carry no value — they are layout, not input. Reporting them
# as accepted props would send a caller looking for a "separator" to fill in.
_NON_INPUT_FIELD_TYPES = {"label", "separator"}

# Relative path of a plugin's action definitions inside its bundle.
ACTIONS_XML_RELPATH = os.path.join("Contents", "Server Plugin", "Actions.xml")


def actions_xml_path(plugin_folder_path: str) -> str:
    """Absolute path to a plugin bundle's Actions.xml.

    `pluginFolderPath` resolves the disabled folder too, so this works for a
    plugin sitting in `Plugins (Disabled)/`. It is `''` for an unknown plugin
    id — the caller checks that, because `getPlugin()` given a wrong id returns
    an object whose isInstalled/isEnabled/isRunning are all False and therefore
    reads exactly like a real outage.
    """
    if not plugin_folder_path:
        return ""
    return os.path.join(plugin_folder_path, ACTIONS_XML_RELPATH)


def parse_actions_xml(xml_text: str) -> Dict[str, Dict[str, Any]]:
    """Return {action_id: {name, device_action, fields, callback, ui_path}}.

    `device_action` is True when the <Action> carries a `deviceFilter`, which
    is Indigo's own marker that the action operates on a device and therefore
    needs a deviceId.

    Raises ET.ParseError on malformed XML — the caller degrades rather than
    refusing, since a plugin we cannot parse may still be perfectly callable.
    """
    root = ET.fromstring(xml_text)
    actions: Dict[str, Dict[str, Any]] = {}
    for node in root.findall("Action"):
        action_id = node.get("id")
        if not action_id:
            continue
        fields: List[str] = []
        for field in node.findall(".//Field"):
            if field.get("type") in _NON_INPUT_FIELD_TYPES:
                continue
            fid = field.get("id")
            if fid:
                fields.append(fid)
        name_node = node.find("Name")
        cb_node = node.find("CallbackMethod")
        actions[action_id] = {
            "name": (name_node.text or "").strip() if name_node is not None else "",
            "device_action": bool(node.get("deviceFilter")),
            "device_filter": node.get("deviceFilter") or "",
            "fields": fields,
            "callback": (cb_node.text or "").strip() if cb_node is not None else "",
            "ui_path": node.get("uiPath") or "",
        }
    return actions


def read_plugin_actions(plugin_folder_path: str) -> Dict[str, Any]:
    """Read and parse one plugin's Actions.xml.

    Never raises. Returns {"available": bool, "actions": {...}, "reason": str}
    so a plugin whose XML is missing or malformed degrades to "dispatch without
    the guard, and say so" rather than blocking a call that would have worked.
    """
    path = actions_xml_path(plugin_folder_path)
    if not path:
        return {"available": False, "actions": {}, "path": "",
                "reason": "plugin folder path is empty (unknown plugin id?)"}
    if not os.path.exists(path):
        return {"available": False, "actions": {}, "path": path,
                "reason": "the plugin declares no Actions.xml"}
    try:
        # Indigo's embedded Python defaults open() to ASCII — be explicit, or a
        # plugin whose action names carry an accent raises UnicodeDecodeError.
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        return {"available": True, "actions": parse_actions_xml(text), "path": path,
                "reason": ""}
    except ET.ParseError as exc:
        return {"available": False, "actions": {}, "path": path,
                "reason": f"Actions.xml did not parse: {exc}"}
    except Exception as exc:                                  # noqa: BLE001
        return {"available": False, "actions": {}, "path": path,
                "reason": f"could not read Actions.xml: {exc}"}


def summarise_actions(actions: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A compact, ordered listing for an error message or a discovery call."""
    out = []
    for action_id in sorted(actions):
        meta = actions[action_id]
        out.append({
            "action_type_id": action_id,
            "name":           meta.get("name", ""),
            "needs_device":   meta.get("device_action", False),
            "props":          meta.get("fields", []),
        })
    return out


def check_call(
    actions: Dict[str, Dict[str, Any]],
    action_type_id: str,
    device_id: Optional[int],
    props: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Decide whether this call can possibly do anything.

    Returns {"ok": bool, "error": str, "warnings": [str], "action": {...}}.
    Separated from the dispatch so the decision is testable on its own — the
    guard is the point of the tool, and a guard nothing can drive is a comment.
    """
    warnings: List[str] = []

    meta = actions.get(action_type_id)
    if meta is None:
        return {
            "ok": False,
            "error": (f"'{action_type_id}' is not an action this plugin declares. "
                      f"Indigo does not raise for an unknown action id — the call "
                      f"would return cleanly and do nothing."),
            "warnings": warnings,
            "action": None,
        }

    if meta["device_action"] and device_id is None:
        return {
            "ok": False,
            "error": (f"'{action_type_id}' is a DEVICE action (deviceFilter="
                      f"'{meta['device_filter']}') and needs device_id. Without it "
                      f"Indigo returns None and does nothing, with no error — pass "
                      f"the device this action should operate on."),
            "warnings": warnings,
            "action": meta,
        }

    if not meta["device_action"] and device_id is not None:
        warnings.append(
            f"'{action_type_id}' is a plugin-level action (no deviceFilter); "
            f"device_id {device_id} will be passed but the plugin may ignore it."
        )

    if props:
        declared = set(meta["fields"])
        # Only worth saying when the action declares SOME fields. An action with
        # no ConfigUI at all (every IWS hidden action) legitimately takes props
        # that appear nowhere in the XML.
        if declared:
            undeclared = sorted(set(props) - declared)
            if undeclared:
                warnings.append(
                    f"props not declared in this action's ConfigUI: "
                    f"{', '.join(undeclared)} (declared: {', '.join(sorted(declared)) or 'none'}) "
                    f"— check for a typo; the plugin will simply not find them."
                )

    return {"ok": True, "error": "", "warnings": warnings, "action": meta}
