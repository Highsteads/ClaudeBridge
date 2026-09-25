#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_delete_gate.py
# Description: The irreversible-delete gate — default-off preference plus a
#              per-call confirm, both enforced on the real dispatch path
#              (ClaudeBridge v2.24.0).
# Author:      CliveS & Claude Opus 5
# Date:        29-08-2026
# Version:     1.0

import pytest

from mcp_server import runtime_config
from mcp_server.security import delete_gate
from mcp_server.security.delete_gate import DeleteDenied

from test_dispatch import _make_handler, _tool

ADMIN_SCOPES = {"tokens": {"root": {"name": "admin-token", "scopes": ["admin"]}}}


@pytest.fixture(autouse=True)
def restore_preference():
    """Never leave the preference on — a later test must not inherit it."""
    before = runtime_config.get("allow_destructive_delete")
    yield
    runtime_config.configure(allow_destructive_delete=before)


def _allow(value):
    runtime_config.configure(allow_destructive_delete=value)


# ── The preference ───────────────────────────────────────────────────────────

def test_default_is_off():
    """An install that has never opened the dialog must refuse."""
    runtime_config._config.pop("allow_destructive_delete", None)
    assert delete_gate.is_enabled() is False


@pytest.mark.parametrize("stored,expected", [
    (True, True), (False, False),
    # Indigo re-serialises a checkbox as a STRING after a dialog save. bool()
    # on these is the bug that made the old InfluxDB switch read backwards.
    ("true", True), ("false", False), ("", False),
    ("True", True), ("False", False), ("on", True), ("off", False),
    # Junk must not read as permission.
    ("banana", False), (None, False),
])
def test_preference_coercion(stored, expected):
    _allow(stored)
    assert delete_gate.is_enabled() is expected


# ── The gate in isolation ────────────────────────────────────────────────────

def test_ungated_tool_passes_untouched():
    _allow(False)
    delete_gate.check("list_devices", {})


def test_delete_script_is_not_gated():
    """It archives to _backups/_archived/, so it is recoverable."""
    assert "delete_script" not in delete_gate.DESTRUCTIVE_TOOLS


def test_both_conditions_needed():
    _allow(True)
    delete_gate.check("delete_automation", {"confirm": True})   # passes

    _allow(False)
    with pytest.raises(DeleteDenied):
        delete_gate.check("delete_automation", {"confirm": True})

    _allow(True)
    with pytest.raises(DeleteDenied):
        delete_gate.check("delete_automation", {})


def test_missing_confirm_names_the_stale_client_cache():
    """An MCP client caches the tool list and drops unknown arguments.

    A client connected before this gate existed strips `confirm` in flight, so
    the caller is refused for omitting something they did pass. Telling them
    only to "pass confirm=true" is advice they cannot act on. Live-hit within
    an hour of shipping the gate.
    """
    _allow(True)
    with pytest.raises(DeleteDenied) as exc:
        delete_gate.check("delete_automation", {})
    message = str(exc.value)
    assert "reconnect" in message
    assert "tool list" in message


def test_refusal_names_every_missing_condition():
    """Naming only the first would send the caller round the loop twice."""
    _allow(False)
    with pytest.raises(DeleteDenied) as exc:
        delete_gate.check("delete_device", {})
    message = str(exc.value)
    assert "plugin preferences" in message
    assert "confirm=true" in message


@pytest.mark.parametrize("truthy", [1, "true", "yes", None, 0])
def test_confirm_must_be_the_boolean_true(truthy):
    """A truthy string is not consent — only True is."""
    _allow(True)
    with pytest.raises(DeleteDenied):
        delete_gate.check("delete_automation", {"confirm": truthy})


# ── Through the real dispatch path ───────────────────────────────────────────

def test_admin_token_alone_cannot_delete(tmp_path):
    """The whole point: admin scope is necessary but no longer sufficient."""
    _allow(False)
    called = []
    h = _make_handler(tmp_path, scopes_data=ADMIN_SCOPES, tools={
        "delete_automation": _tool(lambda **kw: called.append(kw) or "gone"),
    })
    resp = h._handle_tools_call(
        1, {"name": "delete_automation", "arguments": {"kind": "trigger", "id": 1, "confirm": True}},
        headers={"authorization": "Bearer root"},
    )
    assert resp["error"]["code"] == -32099
    assert called == [], "the handler must never run"


def test_enabled_and_confirmed_reaches_the_handler(tmp_path):
    _allow(True)
    called = []
    h = _make_handler(tmp_path, scopes_data=ADMIN_SCOPES, tools={
        "delete_automation": _tool(lambda **kw: called.append(kw) or "gone"),
    })
    resp = h._handle_tools_call(
        2, {"name": "delete_automation", "arguments": {"kind": "trigger", "id": 7, "confirm": True}},
        headers={"authorization": "Bearer root"},
    )
    assert "error" not in resp, resp
    assert called == [{"kind": "trigger", "id": 7}], "confirm must be consumed, not forwarded"


def test_confirm_is_declared_on_every_gated_tool():
    """Undeclared, the unknown-argument check would reject the confirm itself.
    The registry adds it to every destructive tool, with the gate's wording."""
    from mcp_server import registry
    gated = registry.destructive_names()
    assert gated == {"delete_device", "variable_delete", "delete_automation", "delete_folder"}
    for name in gated:
        spec = registry.spec_for(name)
        props = spec.input_schema["properties"]
        assert "confirm" in props, f"{name} would reject its own confirm argument"
        assert props["confirm"]["type"] == "boolean"
        assert "confirm" not in spec.input_schema.get("required", []), \
            "a missing confirm must reach the gate's explanation, not -32602"
        assert "confirm=true" in spec.description


def test_derived_set_matches_the_registry():
    from mcp_server import registry
    assert delete_gate.DESTRUCTIVE_TOOLS == set(registry.destructive_names())


def test_every_gated_tool_also_requires_admin_scope():
    """The gate is a THIRD boundary, never a replacement for the scope check."""
    from mcp_server.security.scope_manager import ADMIN_TOOLS
    assert delete_gate.DESTRUCTIVE_TOOLS <= ADMIN_TOOLS


@pytest.mark.parametrize("text", ["true", "True", "yes"])
def test_a_string_confirm_is_refused_with_the_real_reason(text):
    """confirm:"true" is still refused, but the stale-tool-list advice would
    send the caller round in a circle: they DID pass it. Say what is wrong."""
    _allow(True)
    with pytest.raises(DeleteDenied) as exc:
        delete_gate.check("delete_automation", {"confirm": text})
    message = str(exc.value)
    assert "JSON boolean true" in message
    assert repr(text) in message
    assert "reconnect" not in message


# ── One action of a multi-action tool (zwave enter_exclusion) ────────────────

def _zwave_handler(tmp_path, seen):
    from mcp_server import registry
    spec = registry.spec_for("zwave")
    tool = _tool(lambda **kw: seen.append(kw) or "ok", required=list(spec.required),
                 properties=spec.properties)
    return _make_handler(tmp_path, scopes_data=ADMIN_SCOPES, tools={"zwave": tool})


def _zwave(h, **args):
    return h._handle_tools_call(1, {"name": "zwave", "arguments": args},
                                {"authorization": "Bearer root"})


def test_zwave_exclusion_is_refused_without_confirm_and_the_preference(tmp_path):
    seen = []
    h = _zwave_handler(tmp_path, seen)
    _allow(True)
    resp = _zwave(h, action="enter_exclusion")
    assert resp["error"]["code"] == -32099 and "confirm" in resp["error"]["message"]
    _allow(False)
    resp = _zwave(h, action="enter_exclusion", confirm=True)
    assert resp["error"]["code"] == -32099 and "preferences" in resp["error"]["message"]
    assert seen == []


def test_zwave_exclusion_runs_with_both_and_confirm_is_consumed(tmp_path):
    seen = []
    h = _zwave_handler(tmp_path, seen)
    _allow(True)
    resp = _zwave(h, action="enter_exclusion", confirm=True)
    assert resp["result"]["isError"] is False
    assert seen == [{"action": "enter_exclusion"}]


def test_the_other_zwave_actions_are_not_gated(tmp_path):
    seen = []
    h = _zwave_handler(tmp_path, seen)
    _allow(False)
    resp = _zwave(h, action="enter_inclusion")
    assert resp["result"]["isError"] is False
    assert seen == [{"action": "enter_inclusion"}]
