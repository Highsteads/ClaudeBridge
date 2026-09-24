#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_scope_manager.py
# Description: Regression tests for the per-token scope model (deny-by-default
#              classification + fail-closed lookups). Guards the v2.7.0 security
#              fix from regressing.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.0

import json

import pytest

from mcp_server.security import scope_manager as sm
from mcp_server.security.scope_manager import ScopeManager, ScopeDenied, required_scope_for


# ── Classification partition ──────────────────────────────────────────────────

def test_buckets_are_pairwise_disjoint():
    assert not (sm.READ_TOOLS & sm.WRITE_TOOLS)
    assert not (sm.READ_TOOLS & sm.ADMIN_TOOLS)
    assert not (sm.WRITE_TOOLS & sm.ADMIN_TOOLS)


@pytest.mark.parametrize("tool", [
    "execute_indigo_python", "run_script", "write_script", "delete_script",
    "restart_plugin", "plugin_refresh_deps", "delete_device", "delete_automation",
    "delete_folder", "variable_delete", "remove_delayed_actions", "lock_control",
    "execute_plugin_menu_item", "execute_client_menu_item", "execute_device_action",
    "zwave", "webhook_create", "webhook_list", "webhook_delete", "raw_server_request",
])
def test_dangerous_tools_require_admin(tool):
    assert required_scope_for(tool) == "admin", f"{tool} must be admin-scoped"


@pytest.mark.parametrize("tool", [
    "device_control", "thermostat_control", "speed_control", "sprinkler_control",
    "all_devices", "variable_update", "variable_create", "action_execute_group",
    "set_enabled", "update_automation", "fire_trigger", "send_email",
    "send_notification", "rename_device", "duplicate", "move_to_folder",
    "create_folder",
])
def test_mutating_tools_require_at_least_write(tool):
    assert required_scope_for(tool) in ("write", "admin"), \
        f"{tool} must not be readable by a read-only token"


@pytest.mark.parametrize("tool", [
    "list_devices", "get_device_by_id", "home_status", "search_entities",
    "energy_history", "audit", "read_script", "query_event_log", "server_info",
    "get_dependencies", "get_automation", "plugin_check", "control_pages",
    "system_health",
])
def test_read_tools_are_read(tool):
    assert required_scope_for(tool) == "read"


def test_unknown_tool_fails_closed_to_admin():
    # A newly-added tool that nobody classified must NOT be reachable by a
    # read/write token — it defaults to admin.
    assert required_scope_for("a_brand_new_unclassified_tool") == "admin"


# ── Lookup behaviour ──────────────────────────────────────────────────────────

def test_unconfigured_grants_full_access(tmp_path):
    # No scopes.json at all → stock single-token behaviour (backward compatible).
    mgr = ScopeManager(scopes_file=str(tmp_path / "absent.json"))
    scopes = mgr.scopes_for_token("any-token")
    assert {"read", "write", "admin"} <= scopes
    # check() passes for an admin tool in the unconfigured state.
    mgr.check("any-token", "execute_indigo_python")


def _write(tmp_path, data):
    p = tmp_path / "scopes.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_configured_unknown_token_denied_without_explicit_default(tmp_path):
    f = _write(tmp_path, {"tokens": {"known": {"name": "cc", "scopes": ["read", "write", "admin"]}}})
    mgr = ScopeManager(scopes_file=f)
    # Unknown token, no explicit default_scopes → deny (empty set).
    assert mgr.scopes_for_token("stranger") == set()
    with pytest.raises(ScopeDenied):
        mgr.check("stranger", "list_devices")


def test_configured_explicit_default_applies_to_unknown(tmp_path):
    f = _write(tmp_path, {"default_scopes": ["read"], "tokens": {}})
    mgr = ScopeManager(scopes_file=f)
    assert mgr.scopes_for_token("stranger") == {"read"}
    mgr.check("stranger", "list_devices")               # read ok
    with pytest.raises(ScopeDenied):
        mgr.check("stranger", "device_turn_on")          # write denied


def test_empty_scope_list_means_deny_all(tmp_path):
    # Explicit [] must be deny-all, NOT "fall back to full default".
    f = _write(tmp_path, {"default_scopes": ["read", "write", "admin"],
                          "tokens": {"quarantined": {"name": "q", "scopes": []}}})
    mgr = ScopeManager(scopes_file=f)
    assert mgr.scopes_for_token("quarantined") == set()
    with pytest.raises(ScopeDenied):
        mgr.check("quarantined", "list_devices")


def test_read_token_cannot_mutate(tmp_path):
    f = _write(tmp_path, {"tokens": {"phone": {"name": "phone-app", "scopes": ["read"]}}})
    mgr = ScopeManager(scopes_file=f)
    mgr.check("phone", "list_devices")                   # read ok
    for tool in ("device_turn_on", "delete_device", "run_script", "unlock_device"):
        with pytest.raises(ScopeDenied):
            mgr.check("phone", tool)


def test_malformed_first_load_fails_closed_to_read_only(tmp_path):
    p = tmp_path / "scopes.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    mgr = ScopeManager(scopes_file=str(p))
    scopes = mgr.scopes_for_token("any")
    assert "admin" not in scopes and "write" not in scopes   # never full on a broken file
    assert scopes == {"read"}


def test_audit_classification_flags_unclassified():
    mgr = ScopeManager(scopes_file="")   # unconfigured
    report = mgr.audit_classification(list(sm.READ_TOOLS) + ["mystery_tool"])
    assert report["unclassified"] == ["mystery_tool"]
    assert report["multi_classified"] == []


# ── H9: enable/disable_action_group fully removed ────────────────────────────

def test_action_group_enable_disable_removed_from_scopes():
    from mcp_server.security import scope_manager as sm
    every = sm.READ_TOOLS | sm.WRITE_TOOLS | sm.ADMIN_TOOLS
    assert "enable_action_group" not in every
    assert "disable_action_group" not in every
    # duplicating an action group is a real IOM op and must remain.
    assert "duplicate" in sm.WRITE_TOOLS


# ── Scope classification of the new tools ────────────────────────────────────

def test_new_tool_scopes():
    from mcp_server.security import scope_manager as sm
    # Z-Wave management is ADMIN (config reprogram / physical pair / mesh traffic)
    assert "zwave" in sm.ADMIN_TOOLS
    # thermostat changes, cool setpoints included, are WRITE
    assert "thermostat_control" in sm.WRITE_TOOLS
    # the introspection tools are READ
    for t in ("get_dependencies", "server_info"):
        assert t in sm.READ_TOOLS, t


def test_required_scope_resolves():
    from mcp_server.security.scope_manager import required_scope_for
    assert required_scope_for("zwave") == "admin"
    assert required_scope_for("thermostat_control") == "write"
    assert required_scope_for("server_info") == "read"


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


# ── Unknown scope names are named at load (24-09-2026) ───────────────────────

def test_an_unknown_scope_name_is_warned_about(tmp_path, caplog):
    import json as _json
    import logging as _logging
    from mcp_server.security import ScopeManager as _SM
    path = tmp_path / "scopes.json"
    path.write_text(_json.dumps({"default_scopes": ["Read"],
                                 "tokens": {"t": {"name": "x", "scopes": ["read", "wirte"]}}}),
                    encoding="utf-8")
    log = _logging.getLogger("test-scope-unknown")
    with caplog.at_level(_logging.WARNING, logger=log.name):
        mgr = _SM(scopes_file=str(path), logger=log)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "'Read'" in text and "'wirte'" in text and "grant nothing" in text
    assert mgr.scopes_for_token("t") == {"read", "wirte"}      # grants nothing extra


def test_known_scope_names_raise_no_warning(tmp_path, caplog):
    import json as _json
    import logging as _logging
    from mcp_server.security import ScopeManager as _SM
    path = tmp_path / "scopes.json"
    path.write_text(_json.dumps({"default_scopes": ["read"],
                                 "tokens": {"t": {"scopes": ["read", "write", "admin"]}}}),
                    encoding="utf-8")
    log = _logging.getLogger("test-scope-known")
    with caplog.at_level(_logging.WARNING, logger=log.name):
        _SM(scopes_file=str(path), logger=log)
    assert not [r for r in caplog.records if "unknown scope" in r.getMessage()]
