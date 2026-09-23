#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugins.py
# Description: Plugin tools — listing, status, update checks, development
#              checks, restarts and running a plugin's own actions.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from typing import Any, Dict

from ..registry import tool
from ._schema import boolean, id_or_name, refuse, string

_PLUGIN_NAME = string("Plugin display name or .indigoPlugin folder name")


@tool("list_plugins", scope="read", cacheable=True, reads={"plugin"},
      description="List all Indigo plugins",
      properties={"include_disabled": boolean("Whether to include disabled plugins "
                                              "(default: False)")})
def list_plugins(ctx, include_disabled=False):
    return ctx.plugin_control_handler.list_plugins(include_disabled)


@tool("get_plugin_status", scope="read",
      description=("One installed plugin by bundle id: enabled, running (enabled only says it "
                   "SHOULD run — a plugin that died in startup() is still enabled; running "
                   "answers 'did the restart work'), display name, version and bundle path. An "
                   "id that is not installed is an error, not a disabled plugin. Never cached."),
      properties={"plugin_id": string("Plugin bundle identifier (e.g. "
                                      "'com.clives.indigoplugin.claudebridge')")},
      required=["plugin_id"])
def get_plugin_status(ctx, plugin_id):
    return ctx.plugin_control_handler.get_plugin_status(plugin_id)


@tool("check_plugin_updates", scope="read",
      description=("Sweep every installed plugin and report which have a compatible update "
                   "available. One call instead of one get_plugin_status per plugin."))
def check_plugin_updates(ctx):
    return ctx.extended_tools_handler.check_plugin_updates()


_CHECKS = {
    "xml":      "plugin_validate_xml",
    "html":     "plugin_node_check_html",
    "lint":     "plugin_lint",
    "diff":     "plugin_diff_source_vs_installed",
    "packages": "plugin_show_packages_versions",
}


@tool("plugin_check", scope="read",
      description=(
          "Development checks on one plugin, keyed by check in the reply; a failing check does "
          "not stop the others. xml: parse Devices/Actions/Events/MenuItems/PluginConfig and "
          "apply Indigo's naming rules (camelCase ASCII state ids, no spaces in an Actions "
          "uiPath, batteryLevel reserved). html: `node --check` every inline <script> under "
          "Contents/Resources. lint: plugin.py against CliveS-plugin conventions (header, log() "
          "helper, no bare print(), open() of .py with encoding='utf-8', no hardcoded Indigo "
          "version paths, the pluginId loop-guard with subscribeToChanges). diff: the source "
          "repo bundle against the installed one (stale assets, gutted Packages, version "
          "mismatch). packages: the {name: version} of every bundled library. Default: all five."),
      properties={
          "plugin_name": _PLUGIN_NAME,
          "checks": {"type": "array", "items": {"type": "string", "enum": list(_CHECKS)},
                     "description": "Which checks to run (default all)"},
      },
      required=["plugin_name"])
def plugin_check(ctx, plugin_name, checks=None):
    if isinstance(checks, str):
        checks = [checks]
    wanted = list(checks) if checks else list(_CHECKS)
    unknown = [c for c in wanted if c not in _CHECKS]
    if unknown:
        return refuse(f"plugin_check: unknown check(s) {unknown} — valid: {', '.join(_CHECKS)}")
    handler = ctx.plugin_dev_tools_handler
    results: Dict[str, Any] = {}
    failed = []
    for check in dict.fromkeys(wanted):          # keep order, drop repeats
        try:
            outcome = getattr(handler, _CHECKS[check])(plugin_name)
        except Exception as exc:                 # one check must not sink the rest
            outcome = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        results[check] = outcome
        if not isinstance(outcome, dict) or outcome.get("success") is False:
            failed.append(check)
    reply = {"success": len(failed) < len(results),
             "plugin_name": plugin_name, "checks": results}
    if failed:
        reply["failed_checks"] = failed
    if failed and len(failed) == len(results):
        reply["error"] = f"every check failed: {', '.join(failed)}"
    return reply


@tool("plugin_refresh_deps", scope="admin", invalidates={"plugin"},
      description=("Delete the pip-install success marker so Indigo re-runs requirements.txt "
                   "on next plugin restart. restart=true also triggers the restart "
                   "immediately (refused for Claude Bridge itself)."),
      properties={"plugin_name": _PLUGIN_NAME,
                  "restart": boolean("Restart plugin after (default false)")},
      required=["plugin_name"])
def plugin_refresh_deps(ctx, plugin_name, restart=False):
    return ctx.plugin_dev_tools_handler.plugin_refresh_deps(plugin_name, restart=restart)


@tool("restart_plugin", scope="admin", invalidates={"plugin"},
      description=("Restart an Indigo plugin. Refuses Claude Bridge itself — that kills the "
                   "session asking; restart it from the Indigo Plugins menu."),
      properties={"plugin_id": string("Plugin bundle identifier")},
      required=["plugin_id"])
def restart_plugin(ctx, plugin_id):
    return ctx.plugin_control_handler.restart_plugin(plugin_id)


@tool("execute_device_action", scope="admin", invalidates={"device"},
      description=(
          "Run a plugin's own custom action from its Actions.xml — the actions that appear "
          "under Device -> Actions in the Indigo client, which no built-in tool can reach. Give "
          "device_id for a device action (Indigo marks those with deviceFilter) or plugin_id "
          "alone for a plugin-level action; props carries the action's ConfigUI fields. The "
          "call is checked against the plugin's Actions.xml first, so an unknown action id, a "
          "device action with no device, or a stopped owning plugin come back as errors — "
          "Indigo itself returns cleanly and does nothing in all three cases. A plugin action "
          "reports success by changing state, not by returning a value, so re-read the device "
          "to confirm the effect. ADMIN scope: these actuate real hardware (valves, locks, "
          "doors, sprinklers)."),
      properties={
          "action_type_id": string("The <Action id=...> from the plugin's Actions.xml"),
          "device_id": id_or_name("Device id or exact name. REQUIRED for any action declared "
                                  "with deviceFilter; omit only for a plugin-level action."),
          "props": {"type": "object",
                    "description": ("The action's ConfigUI field values, e.g. {'amount': '43', "
                                    "'amountType': 'seconds'}. Indigo stores ConfigUI values as "
                                    "strings, so prefer strings unless the field is a checkbox.")},
          "plugin_id": string("Owning plugin's bundle id. Derived from the device when omitted; "
                              "required for a plugin-level action."),
          "wait_until_done": boolean("Block until the plugin's callback returns (default true). "
                                     "Dispatch is single-threaded, so a slow action holds every "
                                     "other tool call."),
      },
      required=["action_type_id"])
def execute_device_action(ctx, action_type_id, device_id=None, props=None, plugin_id=None,
                          wait_until_done=True):
    return ctx.plugin_control_handler.execute_device_action(
        action_type_id=action_type_id, device_id=device_id, props=props,
        plugin_id=plugin_id, wait_until_done=wait_until_done)
