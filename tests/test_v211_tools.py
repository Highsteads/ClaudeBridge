#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v211_tools.py
# Description: Tests for the v2.11.0 API-coverage batch — MCP prompts, and the
#              scope classification of the new Z-Wave / setpoint / read tools.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0


# ── MCP prompts (were empty; now populated) ──────────────────────────────────

def test_prompts_list_is_populated():
    from mcp_server.prompts import list_prompts
    prompts = list_prompts()
    names = {p["name"] for p in prompts}
    assert {"house_state", "energy_day_review", "battery_sweep",
            "recover_wedged_plugin", "zwave_tune_sensor"} <= names
    # each entry has the MCP-required shape
    for p in prompts:
        assert p["name"] and p["description"]
        assert isinstance(p["arguments"], list)


def test_prompt_get_fills_arguments():
    from mcp_server.prompts import get_prompt
    got = get_prompt("battery_sweep", {"threshold": 15})
    assert got is not None
    text = got["messages"][0]["content"]["text"]
    assert "threshold=15" in text
    # required-arg default placeholder when not supplied
    plugin = get_prompt("recover_wedged_plugin", {})
    assert "<plugin>" in plugin["messages"][0]["content"]["text"]


def test_prompt_get_unknown_returns_none():
    from mcp_server.prompts import get_prompt
    assert get_prompt("does_not_exist", {}) is None


# ── Scope classification of the new tools ────────────────────────────────────

def test_new_tool_scopes():
    from mcp_server.security import scope_manager as sm
    # Z-Wave management is ADMIN (config reprogram / physical pair / mesh traffic)
    for t in ("zwave_send_config_parameter", "zwave_start_network_optimize",
              "zwave_stop_network_optimize", "zwave_enter_inclusion_mode",
              "zwave_enter_exclusion_mode", "zwave_exit_inclusion_exclusion_mode"):
        assert t in sm.ADMIN_TOOLS, t
    # cool setpoints are WRITE
    assert "increase_cool_setpoint" in sm.WRITE_TOOLS
    assert "decrease_cool_setpoint" in sm.WRITE_TOOLS
    # the introspection tools are READ
    for t in ("trigger_get_dependencies", "get_reflector_status", "get_indigo_paths"):
        assert t in sm.READ_TOOLS, t


def test_required_scope_resolves():
    from mcp_server.security.scope_manager import required_scope_for
    assert required_scope_for("zwave_enter_inclusion_mode") == "admin"
    assert required_scope_for("increase_cool_setpoint") == "write"
    assert required_scope_for("get_indigo_paths") == "read"
