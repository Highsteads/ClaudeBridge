#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_registry.py
# Description: The tool registry is the one place a tool is declared, so these
#              tests pin what every entry must carry and that every view the
#              rest of the plugin takes (scopes, cache, delete gate, error
#              handling, search refresh) is derived from it and agrees with it.
#              Replaces test_tool_registry_consistency.py, which policed four
#              hand-kept copies of the same facts.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import inspect

import pytest

from mcp_server import registry
from mcp_server.common import tool_cache
from mcp_server.security import delete_gate
from mcp_server.security import scope_manager as sm

REG = registry.load()
NAMES = sorted(REG)

_JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}


def _types(prop):
    found = set()
    if isinstance(prop.get("type"), str):
        found.add(prop["type"])
    for sub in prop.get("anyOf", []):
        found |= _types(sub)
    return found


def test_the_surface_is_the_agreed_70():
    # 69 at 3.0; change_log (read) added in 3.4.0.
    assert len(REG) == 70
    by_scope = {sc: len(registry.names_in_scope(sc)) for sc in registry.SCOPES}
    assert by_scope == {"read": 29, "write": 20, "admin": 21}


@pytest.mark.parametrize("name", NAMES)
def test_every_tool_is_complete_and_valid(name):
    spec = REG[name]
    assert spec.name == name
    assert spec.scope in registry.SCOPES
    assert spec.description and len(spec.description) >= 15, "a tool needs a real description"
    schema = spec.input_schema
    assert schema["type"] == "object"
    props = schema["properties"]
    for pname, prop in props.items():
        types = _types(prop)
        assert types, f"{name}.{pname} declares no type"
        assert types <= _JSON_TYPES, f"{name}.{pname} has an unknown type {types}"
        assert prop.get("description"), f"{name}.{pname} has no description"
        if "enum" in prop:
            assert prop["enum"] and len(set(prop["enum"])) == len(prop["enum"])
    assert set(spec.required) <= set(props), f"{name}: required names a missing property"


@pytest.mark.parametrize("name", NAMES)
def test_the_function_accepts_exactly_the_declared_arguments(name):
    """A property the function cannot take would TypeError on every call; a
    parameter the schema never declares can never be reached."""
    spec = REG[name]
    params = inspect.signature(spec.func).parameters
    names = [p for p in params if p != "ctx"]
    takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values())
    declared = set(spec.properties) - ({"confirm"} if spec.gated else set())
    if not takes_kwargs:
        assert declared == set(names), f"{name}: schema {sorted(declared)} vs function {names}"
    for req in spec.required:
        if req in params:
            assert params[req].default is inspect.Parameter.empty, \
                f"{name}: required '{req}' has a default"


def test_destructive_tools_carry_confirm_and_are_admin():
    for name in registry.destructive_names():
        spec = REG[name]
        assert "confirm" in spec.properties
        assert "confirm" not in spec.required
        assert spec.scope == "admin"
        assert delete_gate.CONFIRM_DESCRIPTION_SUFFIX.strip() in spec.description


def test_a_non_destructive_tool_has_no_confirm():
    for name, spec in REG.items():
        if not spec.gated:
            assert "confirm" not in spec.properties, name


def test_zwave_exclusion_alone_is_gated_and_carries_confirm():
    spec = REG["zwave"]
    assert spec.destructive_actions == {"enter_exclusion"}
    assert "confirm" in spec.properties and "confirm" not in spec.required
    assert spec.is_destructive_call({"action": "enter_exclusion"})
    assert not spec.is_destructive_call({"action": "enter_inclusion"})


def test_reset_energy_alone_needs_admin():
    spec = REG["device_control"]
    assert spec.scope == "write"
    assert spec.scope_for({"action": "reset_energy"}) == "admin"
    assert spec.scope_for({"action": "on"}) == "write"
    assert "reset_energy action needs the admin scope" in spec.description


@pytest.mark.parametrize("meta", [
    {"action_scopes": {"no_such_action": "admin"}},
    {"action_scopes": {"go": "read"}},          # a per-action scope may only go up
    {"destructive_actions": {"no_such_action"}},
    {"destructive": True, "destructive_actions": {"go"}},
])
def test_a_per_action_rule_that_cannot_hold_is_refused_at_import(meta):
    with pytest.raises(ValueError):
        registry.tool("widget_probe", scope="write", description="d",
                      properties={"action": {"type": "string", "enum": ["go", "stop"]}},
                      **meta)(lambda ctx, action: None)
    assert "widget_probe" not in REG


def test_cacheable_tools_are_reads_and_declare_what_they_read():
    for name in registry.cacheable_names():
        spec = REG[name]
        assert spec.scope == "read", f"{name}: only a read may be cached"
        assert spec.reads, f"{name}: a cacheable tool must say what it reads"
        assert not spec.invalidates, f"{name}: a cached read invalidates nothing"


def test_every_read_bucket_is_dropped_by_something_or_is_ttl_only():
    dropped = set()
    for spec in REG.values():
        dropped |= spec.invalidates
    for name in registry.cacheable_names():
        for bucket in REG[name].reads:
            assert bucket in dropped or bucket in registry.TTL_ONLY_BUCKETS, \
                f"{name} reads '{bucket}', which no tool invalidates"


def test_no_mutator_is_left_stale_after_its_own_change():
    """Every write/admin tool that changes Indigo state invalidates something,
    unless it is one of the few whose effect no cached read shows."""
    no_cached_effect = {"send_notification", "send_email", "log_message",
                        "webhook_create", "webhook_list", "webhook_delete",
                        "execute_plugin_menu_item", "execute_client_menu_item",
                        "raw_server_request"}
    for name, spec in REG.items():
        if spec.scope != "read" and name not in no_cached_effect:
            assert spec.invalidates, f"{name} changes state but drops no cached answer"


def test_the_redacted_tools_are_exactly_the_code_runners():
    assert registry.redact_names() == {"execute_indigo_python", "run_script"}
    assert registry.clear_all_names() == {"execute_indigo_python", "run_script"}


def test_a_provider_tool_cannot_take_a_built_in_name(tmp_path):
    """A plugin-provided tool named like a built-in is skipped, never shadows it:
    the handler hands the whole registry to the external manager as built-ins."""
    import json
    from test_external_tools import MANIFEST, _bundle, _manager
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["tool_prefix"] = "device"
    manifest["provider"]["plugin_id"] = "com.example.device"
    manifest["tools"][0]["name"] = "control"            # -> device_control
    mgr = _manager()
    entries = mgr.rescan(set(REG), plugin_list=[
        _bundle(tmp_path, "com.example.device", json.dumps(manifest))])
    assert "device_control" not in entries
    assert mgr.skipped_names == ["device_control"]
    assert set(entries).isdisjoint(REG)


def test_decorator_refuses_a_bad_declaration():
    with pytest.raises(ValueError):
        registry.tool("zz_bad_scope", description="x" * 20, scope="superuser")
    with pytest.raises(ValueError):
        registry.tool("zz_bad_bucket", description="x" * 20, scope="read",
                      cacheable=True, reads={"devcie"})(lambda ctx: {})
    with pytest.raises(TypeError):
        registry.tool("zz_bad_meta", description="x" * 20, scope="read", cachable=True)
    with pytest.raises(ValueError):
        registry.tool("search_entities", description="x" * 20, scope="read")(lambda ctx: {})
    assert not any(n.startswith("zz_") for n in REG)


# ── Every derived view agrees with the registry ──────────────────────────────

def test_scope_sets_are_derived():
    assert sm.READ_TOOLS == set(registry.names_in_scope("read"))
    assert sm.WRITE_TOOLS == set(registry.names_in_scope("write"))
    assert sm.ADMIN_TOOLS == set(registry.names_in_scope("admin"))
    for name, spec in REG.items():
        assert sm.required_scope_for(name) == spec.scope


def test_cache_views_are_derived():
    assert tool_cache.CACHEABLE_TOOLS == set(registry.cacheable_names())
    assert tool_cache._CLEAR_ALL_TOOLS == set(registry.clear_all_names())
    for mutator, victims in tool_cache._INVALIDATION_MAP.items():
        for victim in victims:
            assert REG[victim].reads & REG[mutator].invalidates


def test_delete_gate_is_derived():
    assert delete_gate.DESTRUCTIVE_TOOLS == set(registry.destructive_names())


def test_the_handler_advertises_exactly_the_registry():
    """The live tools/list comes from the registry, schema for schema."""
    from mcp_server.mcp_handler import MCPHandler
    h = object.__new__(MCPHandler)
    built = MCPHandler._build_tools(h)
    assert set(built) == set(REG)
    for name, entry in built.items():
        assert entry["inputSchema"] == REG[name].input_schema
        assert entry["description"] == REG[name].description
        assert callable(entry["function"])


def test_every_tool_function_lives_in_a_toolset_module():
    for name, spec in REG.items():
        assert spec.func.__module__.startswith("mcp_server.toolsets."), name


# ── The derived invalidation actually drops what it should ───────────────────

def _warm(cache, *tools):
    for name in tools:
        cache.get_or_compute(name, {}, lambda: '{"success": true}')
        assert cache.get_or_compute(name, {}, lambda: "x")[1] is True, f"{name} did not cache"


def test_a_mutator_drops_exactly_the_reads_it_changes():
    cache = tool_cache.ToolCache(default_ttl=60)
    _warm(cache, "list_action_groups", "list_variables", "list_plugins")
    dropped = cache.invalidate_for_tool("update_automation")
    assert dropped == 1
    assert cache.get_or_compute("list_action_groups", {}, lambda: "fresh")[1] is False
    assert cache.get_or_compute("list_variables", {}, lambda: "x")[1] is True
    assert cache.get_or_compute("list_plugins", {}, lambda: "x")[1] is True


def test_the_code_runners_clear_everything_and_a_read_drops_nothing():
    cache = tool_cache.ToolCache(default_ttl=60)
    _warm(cache, "list_action_groups", "list_variables")
    assert cache.invalidate_for_tool("list_devices") == 0
    assert cache.invalidate_for_tool("execute_indigo_python") == 2
    assert cache.stats()["entries"] == 0


def test_an_uncacheable_or_unknown_tool_is_never_cached():
    cache = tool_cache.ToolCache(default_ttl=60)
    for name in ("get_plugin_status", "device_control", "some_provider_tool"):
        cache.get_or_compute(name, {}, lambda: "a")
        assert cache.get_or_compute(name, {}, lambda: "b") == ("b", False), name
