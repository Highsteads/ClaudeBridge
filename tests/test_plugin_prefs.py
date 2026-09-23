#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_prefs.py
# Description: The plugin's own settings: the Configure dialog still validates
#              what it holds, and settings left over from removed dialog fields
#              are deleted at start-up without their values reaching the log.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# The validation test came from test_v2200_high_fixes.py (09-Aug-2026 review),
# where it was an AST check on the text of validatePrefsConfigUi. It now calls
# the method.

import logging
import os

import pytest

from conftest import SERVER_PLUGIN, load_plugin_module
from mcp_server import orphan_prefs

CONFIG_XML = os.path.join(SERVER_PLUGIN, "PluginConfig.xml")

# What the live install still held on 23-09-2026 from the removed AI and
# InfluxDB settings, plus old separators and help labels.
LIVE_ORPHANS = {
    "anthropic_api_key": "sk-ant-NOT-A-REAL-KEY",
    "enable_influxdb": False,
    "influx_database": "indigo",
    "influx_login": "influx-user",
    "influx_password": "hunter2-influx",
    "influx_port": "8086",
    "influx_url": "http://influx.example",
    "influxdb_secrets_help": "",
    "large_model": "claude-x",
    "small_model": "claude-y",
    "api_key_help": "", "connection_status_help": "", "test_connections_button": "",
    "separator1": "", "separator2": "", "separator4": "", "separator_phase2": "",
}


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _current_prefs():
    ids = orphan_prefs.config_field_ids(CONFIG_XML)
    assert ids and "log_level" in ids and "webhooks_enabled" in ids
    return {k: "kept" for k in ids}


# ── the dialog's validation ──────────────────────────────────────────────────

def _plugin():
    mod = load_plugin_module()
    return mod, object.__new__(mod.Plugin)


def test_other_prefs_are_still_validated():
    """Removing the key check must not have gutted the rest of the validator."""
    _, p = _plugin()
    ok, _values, errors = p.validatePrefsConfigUi({"log_level": "7"})
    assert ok is False and "log_level" in errors
    ok, _values, errors = p.validatePrefsConfigUi({"log_level": "20", "cache_ttl_seconds": "999"})
    assert ok is False and "cache_ttl_seconds" in errors
    ok, _values, errors = p.validatePrefsConfigUi({"log_level": "20"})
    assert ok is True and not errors


# ── orphaned settings ────────────────────────────────────────────────────────

def test_orphans_go_and_every_dialog_field_stays():
    prefs = {**_current_prefs(), **LIVE_ORPHANS, "timestampEnabled": False}
    removed = orphan_prefs.purge_orphan_prefs(prefs, CONFIG_XML)
    assert set(removed) == set(LIVE_ORPHANS)
    assert set(prefs) == set(_current_prefs()) | {"timestampEnabled"}


def test_a_key_the_plugin_writes_itself_is_kept():
    """timestampEnabled is written by the Toggle Timestamps menu item and is in
    no dialog; purging it would reset the user's choice at every start."""
    prefs = {"timestampEnabled": False}
    assert orphan_prefs.purge_orphan_prefs(prefs, CONFIG_XML) == []
    assert prefs == {"timestampEnabled": False}


def test_nothing_is_removed_when_the_dialog_cannot_be_read(tmp_path):
    prefs = {**_current_prefs(), **LIVE_ORPHANS}
    before = dict(prefs)
    assert orphan_prefs.purge_orphan_prefs(prefs, str(tmp_path / "missing.xml")) == []
    broken = tmp_path / "broken.xml"
    broken.write_text("<PluginConfig><Field id=")
    assert orphan_prefs.purge_orphan_prefs(prefs, str(broken)) == []
    empty = tmp_path / "empty.xml"
    empty.write_text("<PluginConfig/>")
    assert orphan_prefs.purge_orphan_prefs(prefs, str(empty)) == []
    assert prefs == before


def test_startup_purges_and_logs_a_count_never_a_value(monkeypatch):
    mod, p = _plugin()
    p.pluginVersion = "test"
    p.allow_destructive_delete = False
    p.pluginPrefs = {**_current_prefs(), **LIVE_ORPHANS}
    rec = _Recorder()
    p.logger = logging.getLogger("test-plugin-prefs")
    p.logger.addHandler(rec)
    p.logger.setLevel(logging.DEBUG)

    def _stop_here(**_kw):
        raise RuntimeError("stop after the purge")
    monkeypatch.setattr(mod, "IndigoDataProvider", _stop_here)
    monkeypatch.chdir(SERVER_PLUGIN)          # Indigo runs a plugin from here
    try:
        p.startup()
    finally:
        p.logger.removeHandler(rec)

    assert not set(LIVE_ORPHANS) & set(p.pluginPrefs)
    purge_lines = [line for line in rec.lines if "Removed" in line]
    assert purge_lines == [f"Removed {len(LIVE_ORPHANS)} stored setting(s) left over "
                           f"from Configure fields that no longer exist"]
    text = "\n".join(rec.lines)
    for value in LIVE_ORPHANS.values():
        if isinstance(value, str) and len(value) > 3:
            assert value not in text, "a stored value reached the log"
    for key in LIVE_ORPHANS:
        assert key not in text


@pytest.mark.parametrize("stored,default,expected", [
    (None, True, True), ("false", True, False), ("true", False, True),
    (False, True, False), ("junk", True, True),
])
def test_checkbox_prefs_read_through_the_shared_as_bool(stored, default, expected):
    """plugin.py's private _as_bool was replaced by plugin_utils.as_bool."""
    mod, _ = _plugin()
    assert not hasattr(mod.Plugin, "_as_bool")
    assert mod.as_bool(stored, default) is expected
