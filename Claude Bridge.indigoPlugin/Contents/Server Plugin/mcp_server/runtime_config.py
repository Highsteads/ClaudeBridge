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
    # Irreversible deletes are refused unless the owner turns this on AND the
    # call passes confirm=true. Default False, and it must stay False: a
    # missing key has to read as "not allowed", never as "not yet decided".
    "allow_destructive_delete": False,
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


def get_bool(key, default=False):
    """Read a config value coerced to bool, guarded against Indigo's strings.

    NOT bool(): Indigo re-serialises a checkbox as the STRING "false" after a
    Configure dialog save, and bool("false") is True — so a feature would read
    as ENABLED precisely for the users who had turned it off and saved. That
    was a live bug in is_influx_enabled until v2.20.2, and the reasoning was
    trapped inside that one function where nothing else could reuse it.

    An UNRECOGNISED string returns the caller's default rather than False, so a
    pref holding junk cannot silently flip a default-on feature off — the same
    rule plugin_utils.as_bool adopted in v1.4.
    """
    value = get(key, default)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off", ""):
            return False
        return bool(default)
    return bool(value)


def is_influx_enabled():
    """Convenience wrapper used in two hot paths."""
    return get_bool("influxdb_enabled", False)


# Keys whose values must never appear in a diagnostic dump.
_SECRET_KEYS = frozenset({"anthropic_api_key", "influxdb_password"})


def snapshot(reveal_secrets: bool = False):
    """Return a copy of the current live config, for diagnostics.

    Credentials are MASKED by default. This dict is for logging and health
    output, and a caller cannot be expected to know which keys are sensitive —
    so the safe form is the default and revealing them has to be asked for.
    """
    merged = dict(_DEFAULTS)
    merged.update(_config)
    if reveal_secrets:
        return merged
    for key in _SECRET_KEYS:
        value = merged.get(key)
        if value:
            merged[key] = f"<set, {len(str(value))} chars>"
    return merged
