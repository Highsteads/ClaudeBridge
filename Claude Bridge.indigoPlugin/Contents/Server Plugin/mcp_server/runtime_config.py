#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    runtime_config.py
# Description: In-process configuration store for the MCP server modules.
#              Replaces os.environ as the credential channel between
#              plugin.py and the downstream MCP code.
# Author:      CliveS & Claude Opus 4.7
# Date:        23-05-2026
# Version:     1.0
#
# Per the global secrets policy
# (/Users/indigo/.claude/CLAUDE.md → Secrets policy section):
#
#     "NEVER set credentials into os.environ — they leak to every
#      spawned subprocess."
#
# Two ClaudeBridge tool handlers shell out without an explicit `env=`:
#
#   - mcp_server/tools/system_tools/system_tools_handler.py:83
#       subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
#   - mcp_server/tools/scripting_shell/scripting_shell_handler.py:194
#       subprocess.run(["osascript", "-e", script], ...)
#
# Anything in os.environ at that moment is inherited by the child.  Up to
# v2.3, plugin.py wrote ANTHROPIC_API_KEY plus the full InfluxDB credential
# set (host/port/username/password/database) into os.environ before either
# of those tools could run.  This module replaces that channel: plugin.py
# calls `configure(...)` at startup and on every PluginConfig save, and
# every downstream module that previously did `os.environ.get(...)` now
# does `runtime_config.get(...)`.

_DEFAULTS = {
    "anthropic_api_key":  "",
    "large_model":        "claude-sonnet-4-6",
    "small_model":        "claude-haiku-4-5-20251001",
    "influxdb_enabled":   False,
    "influxdb_host":      "localhost",
    "influxdb_port":      8086,
    "influxdb_username":  "",
    "influxdb_password":  "",
    "influxdb_database":  "indigo",
    "db_file":            "",
}

_config = {}


def configure(**kwargs):
    """Populate or update the runtime config.

    Unknown keys are silently ignored so the caller can pass through a
    larger dict (e.g. `pluginPrefs`) without filtering it first.
    """
    for key, value in kwargs.items():
        if key in _DEFAULTS:
            _config[key] = value


def get(key, default=None):
    """Read a config value.

    Resolution order: live value (set via `configure()`) → module default
    → caller-supplied `default`.  Returning None is allowed.
    """
    if key in _config:
        return _config[key]
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    return default


def get_int(key, default=0):
    """Read a config value coerced to int, guarded against bad input.

    Indigo re-serialises PluginConfig fields as STRINGS after a Configure
    dialog save (and as '' when blank), so a value that defaults to an int
    here can arrive as '8086' or '' or arbitrary text. Coerce inside
    try/except and fall back to a real int — never raise and never return a
    string.
    """
    value = get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(default)
        except (TypeError, ValueError):
            return 0


def is_influx_enabled():
    """Convenience wrapper used in two hot paths."""
    return bool(get("influxdb_enabled"))


def snapshot():
    """Return a copy of the current live config (for diagnostics)."""
    merged = dict(_DEFAULTS)
    merged.update(_config)
    return merged
