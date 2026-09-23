#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    runtime_config.py
# Description: In-process configuration store for the MCP server modules.
#              Carries settings from plugin.py to the downstream MCP
#              code without going through os.environ.
# Author:      CliveS & Claude Opus 4.7
# Date:        23-05-2026
# Version:     1.0
#
# Why not os.environ: two tool handlers shell out without an explicit
# `env=` (system_tools and scripting_shell), so anything in os.environ is
# inherited by the child. Up to v2.3 plugin.py wrote the Anthropic key and
# the InfluxDB credentials there. Those settings went with the historical
# analysis tool in the September 2026 spring clean; what is left is the
# destructive-delete switch, which plugin.py publishes here at startup and
# on every PluginConfig save.

_DEFAULTS = {
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


def get_bool(key, default=False):
    """Read a config value coerced to bool, guarded against Indigo's strings.

    NOT bool(): Indigo re-serialises a checkbox as the STRING "false" after a
    Configure dialog save, and bool("false") is True — so a feature would read
    as ENABLED precisely for the users who had turned it off and saved (a live
    bug in the old InfluxDB switch until v2.20.2).

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

