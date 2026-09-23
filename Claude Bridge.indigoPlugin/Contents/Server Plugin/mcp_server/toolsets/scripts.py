#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    scripts.py
# Description: Script and code tools — the Python Scripts folders, running a
#              script or arbitrary Python as a job, and the client's menus.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from ..common import exec_lock
from ..registry import tool
from ._schema import boolean, coerce_bool, enum, number, string

_WAIT = number(f"Seconds to wait for the run to finish before handing back a job_id "
               f"(default {exec_lock.DEFAULT_WAIT_SECONDS}, 0-{exec_lock.MAX_WAIT_SECONDS})")
_JOB_ID = string("Collect a run that is still going: the job_id an earlier call returned")
_JOB_NOTE = (
    f" A run that takes longer than wait_seconds (default {exec_lock.DEFAULT_WAIT_SECONDS}) keeps "
    "going in the background: the reply is {status: 'running', job_id}, and calling again with "
    "that job_id waits a little longer and returns the finished result. Only one run of this "
    "tool or its sibling can hold the output capture at a time; another is refused at once, "
    f"naming the running job. Results are kept {exec_lock.RESULT_TTL_SECONDS // 60} minutes.")


@tool("list_python_scripts", scope="read", cacheable=True, reads={"script"},
      description=("List the Python scripts (.py files) in the Indigo script folders with "
                   "name, size, last-modified date and full path. With backups_for, list the "
                   "automatic backups kept for that one script instead, newest first."),
      properties={"backups_for": string("Optional script filename whose backups to list")})
def list_python_scripts(ctx, backups_for=None):
    if backups_for:
        return ctx.script_tools_handler.list_script_backups(backups_for)
    return ctx.system_tools_handler.list_python_scripts()


@tool("read_script", scope="read", cacheable=True, reads={"script"},
      description="Read the full content of a Python script from the Indigo Scripts folder.",
      properties={"name": string("Script filename (with or without .py)")},
      required=["name"])
def read_script(ctx, name):
    return ctx.script_tools_handler.read_script(name)


@tool("write_script", scope="admin", invalidates={"script"}, sensitive=True,
      description=("Write a Python script in the Indigo Scripts folder. By default it overwrites "
                   "an EXISTING script, taking a timestamped backup first, and refuses a missing "
                   "one. create=true makes a NEW script instead and refuses one that already "
                   "exists."),
      properties={
          "name": string("Script filename (with or without .py)"),
          "content": string("Full Python source code"),
          "create": boolean("true to create a new script (default false: overwrite an "
                            "existing one)"),
      },
      required=["name", "content"])
def write_script(ctx, name, content, create=False):
    handler = ctx.script_tools_handler
    if coerce_bool(create):
        return handler.create_script(name, content)
    return handler.write_script(name, content)


@tool("delete_script", scope="admin", invalidates={"script"},
      description=("Safely archive a Python script (moves to _backups/_archived/). Does not "
                   "permanently delete — can be recovered manually."),
      properties={"name": string("Script filename to archive")},
      required=["name"])
def delete_script(ctx, name):
    return ctx.script_tools_handler.delete_script(name)


@tool("run_script", scope="admin", invalidates={"*"}, sensitive=True, redact=True,
      description=("Execute a Python script from the Python Scripts folder in the Indigo Python "
                   "context, with full access to the indigo module. Use for triggering "
                   "automation logic, one-off tasks, or testing scripts. Returns stdout/stderr."
                   + _JOB_NOTE),
      properties={"name": string("Script filename (with or without .py extension)"),
                  "wait_seconds": _WAIT, "job_id": _JOB_ID})
def run_script(ctx, name=None, wait_seconds=None, job_id=None):
    return ctx.script_tools_handler.run_script(name, wait_seconds=wait_seconds, job_id=job_id)


@tool("execute_indigo_python", scope="admin", invalidates={"*"}, sensitive=True, redact=True,
      description=("Run arbitrary Python in this plugin's Indigo context. Has full access to the "
                   "`indigo` module (devices, variables, triggers, thermostat.setHeatSetpoint, "
                   "etc). mode='exec' runs a statement block and returns captured stdout/stderr. "
                   "mode='eval' evaluates a single expression and returns its repr in 'value'. "
                   "ADMIN scope — treat as arbitrary code execution on the Indigo server."
                   + _JOB_NOTE),
      properties={
          "code": string("Python source. For 'exec' use print() to surface output."),
          "mode": enum(["exec", "eval"], "exec (default) for statements, eval for a single "
                                         "expression"),
          "wait_seconds": _WAIT,
          "job_id": _JOB_ID,
      })
def execute_indigo_python(ctx, code=None, mode="exec", wait_seconds=None, job_id=None):
    return ctx.scripting_shell_handler.execute_indigo_python(
        code, mode, wait_seconds=wait_seconds, job_id=job_id)


@tool("execute_plugin_menu_item", scope="admin",
      description=("Click a plugin's menu item under the Indigo client's Plugins menu (e.g. "
                   "plugin_name='Zigbee2MQTT Bridge', menu_item_name='Refresh Device "
                   "Capabilities'). Uses AppleScript GUI scripting — requires the Indigo GUI "
                   "client to be running and System Events permission granted. ADMIN scope."),
      properties={
          "plugin_name": string("The name shown under the Plugins menu"),
          "menu_item_name": string("The menu item label to click"),
          "timeout": number("osascript timeout in seconds (default 15)"),
      },
      required=["plugin_name", "menu_item_name"])
def execute_plugin_menu_item(ctx, plugin_name, menu_item_name, timeout=15):
    return ctx.scripting_shell_handler.execute_plugin_menu_item(
        plugin_name, menu_item_name, timeout)


@tool("execute_client_menu_item", scope="admin",
      description=(
          "Click any item in the Indigo client's own menu bar, given the full path (e.g. "
          "path=['Interfaces','Z-Wave','Disable']). Use this for the client commands that have "
          "no API at all — indigo.zwave has isEnabled() and no setter, so this is the only way "
          "to make Indigo release the Z-Wave stick for a controller backup. Pass list_only=true "
          "with a menu or submenu path (or [] for the menu-bar titles) to READ a menu instead "
          "of clicking it, which is how you find an item's current label: several are toggles "
          "that rename themselves, and the Z-Wave one reads 'Disable' when on and 'Enable' when "
          "off. Listing does not bring the client to the front. Clicking does. Refuses Claude "
          "Bridge's own submenu and Quit. Requires the Indigo GUI client running and System "
          "Events permission. ADMIN scope."),
      properties={
          "path": {"type": "array", "items": {"type": "string"},
                   "description": ("Menu path, outermost first, e.g. ['Interfaces','Z-Wave',"
                                   "'Disable']. At least two levels to click. For list_only this "
                                   "names the menu to read, and [] returns the menu-bar titles.")},
          "list_only": boolean("Read the menu's item names instead of clicking (default false)"),
          "timeout": number("osascript timeout in seconds (default 15, max 60)"),
      },
      required=["path"])
def execute_client_menu_item(ctx, path, list_only=False, timeout=15):
    return ctx.scripting_shell_handler.execute_client_menu_item(path, list_only, timeout)
