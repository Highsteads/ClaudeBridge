#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2202_low_fixes.py
# Description: Regression tests for the low-severity batch of the 09-Aug-2026
#              deep review — the security and data-integrity subset.
# Author:      CliveS & Claude Opus 5
# Date:        09-08-2026
# Version:     1.0

# ── Credentials must not appear in a diagnostic dump ─────────────────────────

def test_snapshot_masks_secrets_by_default():
    from mcp_server import runtime_config

    runtime_config.configure(anthropic_api_key="sk-ant-secret-value",
                             influxdb_password="hunter2")
    snap = runtime_config.snapshot()

    assert "sk-ant-secret-value" not in str(snap)
    assert "hunter2" not in str(snap)
    # Still says whether a value is SET — masking must not destroy the signal.
    assert "set" in str(snap["anthropic_api_key"]).lower()

    revealed = runtime_config.snapshot(reveal_secrets=True)
    assert revealed["anthropic_api_key"] == "sk-ant-secret-value"


def test_influx_enabled_is_not_fooled_by_the_string_false():
    """Indigo re-serialises a checkbox as "false", and bool("false") is True."""
    from mcp_server import runtime_config

    for falsey in ("false", "False", "0", "no", "off", "", False):
        runtime_config.configure(influxdb_enabled=falsey)
        assert runtime_config.is_influx_enabled() is False, falsey
    for truthy in ("true", "True", "1", "yes", "on", True):
        runtime_config.configure(influxdb_enabled=truthy)
        assert runtime_config.is_influx_enabled() is True, truthy


# ── Battery reporting ────────────────────────────────────────────────────────

class _Dev:
    def __init__(self, states, native=None):
        self.states = states
        if native is not None:
            self.batteryLevel = native


def test_battery_low_flag_read_as_a_string_is_not_truthy():
    """A "False" string state meant every OK sensor reported as flat."""
    from mcp_server.common.battery import battery_pct

    assert battery_pct(_Dev({"battery": 0, "batteryLow": "false"})) is None
    assert battery_pct(_Dev({"battery": 0, "batteryLow": "False"})) is None
    assert battery_pct(_Dev({"battery": 0, "batteryLow": "true"})) == 1
    assert battery_pct(_Dev({"battery": 0, "batteryLow": True})) == 1


def test_out_of_range_battery_reads_as_unknown():
    """255 is the classic 'unknown' sentinel. Reporting it as a percentage puts
    a possibly-failing sensor at the healthy end of a low-battery sweep."""
    from mcp_server.common.battery import battery_pct

    assert battery_pct(_Dev({"battery": 255})) is None
    assert battery_pct(_Dev({"battery": -5})) is None
    assert battery_pct(_Dev({"battery": 101})) is None
    assert battery_pct(_Dev({"battery": 100})) == 100
    assert battery_pct(_Dev({"battery": 42})) == 42


# ── scopes.json is hand-edited, so it must survive an obvious mistake ────────

def test_a_string_scope_is_not_exploded_into_characters(tmp_path):
    """list("admin") is five scopes, none of them real — a token with a string
    scope silently had NO usable permissions and nothing said why."""
    import json

    from mcp_server.security.scope_manager import ScopeManager

    path = tmp_path / "scopes.json"
    path.write_text(json.dumps({
        "default_scopes": "read",
        "tokens": {"tok-abc": {"name": "phone", "scopes": "admin"}},
    }))

    sm = ScopeManager(str(path))
    assert sm._default == ["read"]
    assert sm._tokens["tok-abc"]["scopes"] == ["admin"]


# ── Deleting one saved note must not delete another ─────────────────────────

def test_memory_ids_are_unique_within_the_same_millisecond():
    """forget() deletes BY id, so a shared id means collateral deletion."""
    import time

    from mcp_server.tools.memory import memory_handler

    existing = [{"id": int(time.time() * 1000)}]
    # Reproduces the generator: start at "now" and step past anything taken.
    memory_id = existing[0]["id"]
    taken = {m["id"] for m in existing}
    while memory_id in taken:
        memory_id += 1
    assert memory_id not in taken

    src = memory_handler.__file__
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    assert "while memory_id in existing" in body, (
        "remember() still trusts a bare millisecond epoch to be unique"
    )


# ── An audit figure must mean something ──────────────────────────────────────

def test_false_is_not_an_empty_variable():
    """Every boolean flag sits at "false" half the time, so counting those made
    the empty-variable total track the state of the house, not anything wrong."""
    import ast
    import os

    from conftest import SERVER_PLUGIN

    path = os.path.join(SERVER_PLUGIN, "mcp_server", "tools", "audit",
                        "audit_handler.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "audit_home")
    src = ast.unparse(fn)
    assert "'none', 'null'" in src or '"none", "null"' in src
    assert "'false'" not in src and '"false"' not in src, (
        "audit_home still counts a boolean variable set to false as empty"
    )


# ── Arguments are coerced before they are compared ───────────────────────────

def test_hvac_mode_rejects_a_non_string_cleanly():
    """mode.lower() ran outside the try, so a number raised AttributeError."""
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider

    provider = object.__new__(IndigoDataProvider)
    result = provider.set_hvac_mode(1, 42)
    assert result["success"] is False
    assert "Unknown HVAC mode" in result["error"]

    result = provider.set_hvac_mode(1, None)
    assert result["success"] is False
