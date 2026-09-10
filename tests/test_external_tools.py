#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_external_tools.py
# Description: Plugin-provided MCP tools (v2.26.0) — the provider-manifest v1
#              contract as Claude Bridge reads it. Manifest parsing and every
#              refusal it must make; discovery over a fake plugin list and
#              temp bundles; the registry manager (enforced prefixes,
#              first-come prefix ownership, built-in collisions skipped, the
#              write gate consulted per call); dispatch through a fake plugin
#              (not running, ok, in-band error, protocol violations, raised
#              exception, timeout); the scope manager's dynamic read/write
#              classification with its fail-closed edges; and the handler
#              end to end — refresh, tools/list, tools/call, and a provider
#              vanishing. Plus the real Dashboards manifest when it is on this
#              machine, which is the one provider that exists today.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import json
import logging
import os
import threading
import time
import types
from collections import deque

import pytest

from mcp_server.common.tool_cache import ToolCache
from mcp_server.external_tools import (
    ExternalToolManager,
    ManifestError,
    WRITE_GATE_MESSAGE,
    derive_prefix,
    discover_manifests,
    invoke_provider_tool,
    manifest_fingerprint,
    manifest_path_for,
    parse_envelope,
    parse_manifest,
)
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager
from mcp_server.security import scope_manager as sm

_LOGGER = logging.getLogger("test-external-tools")

PID = "com.example.widgets"
MANIFEST = {
    "manifest_version": 1,
    "provider": {"plugin_id": PID, "display_name": "Widgets"},
    "tools": [
        {"name": "get_status", "description": "Status.", "write": False, "timeout_seconds": 15,
         "inputSchema": {"type": "object", "properties": {}, "required": []}},
        {"name": "set_mode", "description": "Change mode.", "write": True,
         "inputSchema": {"type": "object",
                         "properties": {"mode": {"type": "string", "enum": ["auto", "manual"]}},
                         "required": ["mode"]}},
    ],
}


def _text(overrides=None, **top):
    m = json.loads(json.dumps(MANIFEST))
    m.update(top)
    if overrides:
        m["tools"][0].update(overrides)
    return json.dumps(m)


def _bundle(tmp_path, pid, manifest_text, name=None):
    folder = tmp_path / (name or pid.rsplit(".", 1)[-1] + ".indigoPlugin")
    res = folder / "Contents" / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "mcp-manifest.json").write_text(manifest_text, encoding="utf-8")
    return types.SimpleNamespace(pluginId=pid, pluginFolderPath=str(folder))


class FakePlugin:
    def __init__(self, reply=None, running=True, raise_exc=None, delay=0.0):
        self.reply, self.running, self.raise_exc, self.delay = reply, running, raise_exc, delay
        self.calls = []

    def isRunning(self):
        return self.running

    def executeAction(self, action_id, deviceId=0, props=None, waitUntilDone=True):
        self.calls.append((action_id, dict(props or {})))
        if self.delay:
            time.sleep(self.delay)
        if self.raise_exc:
            raise self.raise_exc
        return self.reply


# ── manifest parsing ─────────────────────────────────────────────────────

def test_happy_path_and_defaults():
    m = parse_manifest(_text(), PID, path="/x/mcp-manifest.json")
    assert m.plugin_id == PID and m.display_name == "Widgets" and m.prefix == "widgets"
    assert [t.name for t in m.tools] == ["get_status", "set_mode"]
    get, setm = m.tools
    assert get.write is False and get.timeout_seconds == 15 and get.action_id == "mcp_tool_invoke"
    assert setm.write is True and setm.timeout_seconds == 30
    assert m.exposed_name(get) == "widgets_get_status"
    assert m.path == "/x/mcp-manifest.json"


@pytest.mark.parametrize("text,needle", [
    ("not json", "not valid JSON"),
    ("[]", "root must be a JSON object"),
    (_text(manifest_version=2), "manifest_version"),
    (_text(provider={"display_name": "X"}), "provider.plugin_id"),
    (_text(tool_prefix="Bad-Prefix"), "tool_prefix"),
    (_text(invoke_action_id=""), "invoke_action_id"),
    (_text(tools=[]), "non-empty"),
    (_text(tools=["x"]), "tools[0] must be an object"),
    (_text({"name": "Get-Status"}), "tools[0].name"),
    (_text({"description": "  "}), "description is required"),
    (_text({"inputSchema": {"type": "array"}}), "inputSchema"),
    (_text({"write": "no"}), "write must be"),
    (_text({"timeout_seconds": "30"}), "timeout_seconds"),
    (_text({"timeout_seconds": True}), "timeout_seconds"),
    (_text({"action_id": ""}), "action_id"),
])
def test_manifest_refusals_name_the_field(text, needle):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(text, PID)
    assert needle in str(exc.value)


def test_plugin_id_must_match_the_bundle_it_was_found_in():
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_text(), "com.example.other")
    assert "does not match the bundle" in str(exc.value)


def test_duplicate_tool_names_rejected():
    m = json.loads(_text())
    m["tools"].append(dict(m["tools"][0]))
    with pytest.raises(ManifestError, match="duplicate tool name"):
        parse_manifest(json.dumps(m), PID)


def test_write_defaults_to_true_and_timeout_is_clamped():
    m = json.loads(_text())
    del m["tools"][0]["write"]
    m["tools"][0]["timeout_seconds"] = 1
    m["tools"][1]["timeout_seconds"] = 999
    parsed = parse_manifest(json.dumps(m), PID)
    assert parsed.tools[0].write is True, "an undeclared write flag fails safe"
    assert parsed.tools[0].timeout_seconds == 5 and parsed.tools[1].timeout_seconds == 120


def test_declared_prefix_and_per_tool_action_id_are_honoured():
    m = json.loads(_text(tool_prefix="wid", invoke_action_id="custom_invoke"))
    m["tools"][1]["action_id"] = "other_invoke"
    parsed = parse_manifest(json.dumps(m), PID)
    assert parsed.prefix == "wid"
    assert [t.action_id for t in parsed.tools] == ["custom_invoke", "other_invoke"]


@pytest.mark.parametrize("plugin_id,expected", [
    ("com.vtmikel.autolights", "autolights"),
    ("com.foo.example-http-responder", "example_http_responder"),
    ("com.clives.indigoplugin.dashboards", "dashboards"),
    ("com.x.123abc", "abc"),
    ("com.x.___", "plugin"),
    ("com.x." + "a" * 50, "a" * 32),
])
def test_prefix_derivation(plugin_id, expected):
    assert derive_prefix(plugin_id) == expected


# ── discovery ────────────────────────────────────────────────────────────

def test_discovery_reads_valid_manifests_skips_self_and_warns_on_bad(tmp_path, caplog):
    good = _bundle(tmp_path, PID, _text())
    bad  = _bundle(tmp_path, "com.example.bad", "{not json")
    me   = _bundle(tmp_path, "com.clives.indigoplugin.claudebridge", _text(provider={"plugin_id": "com.clives.indigoplugin.claudebridge"}))
    none = types.SimpleNamespace(pluginId="com.example.plain", pluginFolderPath=str(tmp_path / "plain"))
    with caplog.at_level(logging.WARNING):
        found = discover_manifests(_LOGGER, self_plugin_id="com.clives.indigoplugin.claudebridge",
                                   plugin_list=[good, bad, me, none])
    assert [m.plugin_id for m in found] == [PID]
    assert found[0].path == manifest_path_for(good.pluginFolderPath)
    assert any("Ignoring MCP tool manifest" in r.message and "bad" in r.message for r in caplog.records)


def test_fingerprint_changes_when_a_manifest_changes_or_appears(tmp_path):
    a = _bundle(tmp_path, PID, _text())
    fp1 = manifest_fingerprint(plugin_list=[a])
    assert len(fp1) == 1
    assert manifest_fingerprint(plugin_list=[a]) == fp1, "unchanged files give the same fingerprint"
    path = manifest_path_for(a.pluginFolderPath)
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert manifest_fingerprint(plugin_list=[a]) != fp1
    b = _bundle(tmp_path, "com.example.second", _text(provider={"plugin_id": "com.example.second"}))
    assert len(manifest_fingerprint(plugin_list=[a, b])) == 2


# ── manager ──────────────────────────────────────────────────────────────

def _manager(get_plugin=None, gate=None):
    return ExternalToolManager(logger=_LOGGER, self_plugin_id="com.clives.indigoplugin.claudebridge",
                               write_gate_supplier=gate, get_plugin=get_plugin)


def test_entries_are_prefixed_shaped_like_builtins_and_credited(tmp_path):
    entries = _manager().rescan(builtin_names=set(), plugin_list=[_bundle(tmp_path, PID, _text())])
    assert set(entries) == {"widgets_get_status", "widgets_set_mode"}
    e = entries["widgets_get_status"]
    assert set(e) == {"description", "inputSchema", "function", "external_provider", "write"}
    assert e["description"].endswith("[provided by the Widgets plugin]")
    assert e["inputSchema"] == MANIFEST["tools"][0]["inputSchema"]
    assert e["external_provider"] == PID and e["write"] is False
    assert entries["widgets_set_mode"]["write"] is True
    assert e["function"].__name__ == "widgets_get_status"


def test_prefix_is_first_come_and_the_second_manifest_is_rejected_whole(tmp_path, caplog):
    first  = _bundle(tmp_path, PID, _text(), name="first.indigoPlugin")
    second = _bundle(tmp_path, "com.other.widgets", _text(provider={"plugin_id": "com.other.widgets"}),
                     name="second.indigoPlugin")
    mgr = _manager()
    with caplog.at_level(logging.ERROR):
        entries = mgr.rescan(set(), plugin_list=[first, second])
    assert {e["external_provider"] for e in entries.values()} == {PID}
    assert mgr.rejected == ["com.other.widgets"]
    assert any("already claimed" in r.message for r in caplog.records)
    assert any("REJECTED com.other.widgets" in ln for ln in mgr.summary())


def test_a_name_colliding_with_a_builtin_is_skipped(tmp_path, caplog):
    mgr = _manager()
    with caplog.at_level(logging.WARNING):
        entries = mgr.rescan({"widgets_get_status"}, plugin_list=[_bundle(tmp_path, PID, _text())])
    assert "widgets_get_status" not in entries and "widgets_set_mode" in entries
    assert mgr.skipped_names == ["widgets_get_status"]
    assert any("would shadow a built-in" in r.message for r in caplog.records)


def test_write_gate_blocks_write_tools_only_and_is_read_per_call(tmp_path):
    plugin = FakePlugin(reply=json.dumps({"status": "ok", "result": {"done": True}}))
    gate = {"open": False}
    mgr = _manager(get_plugin=lambda pid: plugin, gate=lambda: gate["open"])
    entries = mgr.rescan(set(), plugin_list=[_bundle(tmp_path, PID, _text())])
    refused = json.loads(entries["widgets_set_mode"]["function"](mode="auto"))
    assert refused["success"] is False and refused["error"] == WRITE_GATE_MESSAGE
    assert plugin.calls == [], "a refused write must never reach the provider"
    read = json.loads(entries["widgets_get_status"]["function"]())
    assert read["success"] is True and read["result"] == {"done": True}
    gate["open"] = True
    allowed = json.loads(entries["widgets_set_mode"]["function"](mode="auto"))
    assert allowed["success"] is True
    assert plugin.calls[-1] == ("mcp_tool_invoke", {"tool": "set_mode", "arguments": '{"mode": "auto"}'})


# ── dispatch ─────────────────────────────────────────────────────────────

def _invoke(plugin, timeout=5, name="get_status", args=None):
    return invoke_provider_tool(PID, "mcp_tool_invoke", name, "Widgets", args or {}, timeout,
                                logger=_LOGGER, get_plugin=lambda pid: plugin)


def test_provider_not_running():
    out = _invoke(FakePlugin(running=False))
    assert out["success"] is False and "not running" in out["error"]


def test_ok_envelope_and_the_props_it_was_sent():
    plugin = FakePlugin(reply=json.dumps({"status": "ok", "result": [1, 2]}))
    out = _invoke(plugin, args={"a": None, "$b": 1})
    assert out == {"success": True, "provider": PID, "result": [1, 2]}
    action, props = plugin.calls[0]
    assert action == "mcp_tool_invoke" and props["tool"] == "get_status"
    assert json.loads(props["arguments"]) == {"a": None, "$b": 1}, "arguments cross as a JSON string"


def test_error_envelope_is_mapped_with_type_and_details():
    plugin = FakePlugin(reply=json.dumps({"status": "error", "error": {
        "type": "validation", "message": "mode must be auto|manual", "details": {"path": "mode"}}}))
    out = _invoke(plugin)
    assert out["success"] is False and out["error_type"] == "validation"
    assert out["error"] == "mode must be auto|manual" and out["details"] == {"path": "mode"}


@pytest.mark.parametrize("reply", [None, 42, {"status": "ok"}, "{not json", json.dumps({"result": 1}),
                                   json.dumps({"status": "maybe"}), json.dumps([1])])
def test_protocol_violations_are_reported_not_guessed(reply):
    out = _invoke(FakePlugin(reply=reply))
    assert out["success"] is False and "violated the provider protocol" in out["error"]


def test_execute_action_exception_is_in_band():
    out = _invoke(FakePlugin(raise_exc=RuntimeError("no such action")))
    assert out["success"] is False and "no such action" in out["error"]


def test_get_plugin_failure_is_in_band():
    def boom(pid):
        raise RuntimeError("server gone")
    out = invoke_provider_tool(PID, "a", "t", "Widgets", {}, 5, logger=_LOGGER, get_plugin=boom)
    assert out["success"] is False and "server gone" in out["error"]


def test_timeout_is_reported_and_logged(caplog):
    plugin = FakePlugin(reply=json.dumps({"status": "ok"}), delay=0.6)
    with caplog.at_level(logging.ERROR):
        out = _invoke(plugin, timeout=0.2)
    assert out["success"] is False and out.get("timeout") is True
    assert any("timed out" in r.message for r in caplog.records)


def test_parse_envelope_error_without_message_or_type_still_answers():
    out = parse_envelope(json.dumps({"status": "error", "error": "oops"}), PID, "L", _LOGGER)
    assert out == {"success": False, "provider": PID, "error": "unknown provider error",
                   "error_type": "internal"}


# ── scope classification ─────────────────────────────────────────────────

def test_dynamic_scopes_classify_read_write_and_fail_closed():
    try:
        sm.register_dynamic_scope("zz_read", "read")
        sm.register_dynamic_scope("zz_write", "write")
        sm.register_dynamic_scope("zz_bogus", "admin")        # a provider cannot claim admin either way
        sm.register_dynamic_scope("zz_typo", "wrte")
        assert sm.required_scope_for("zz_read") == "read"
        assert sm.required_scope_for("zz_write") == "write"
        assert sm.required_scope_for("zz_bogus") == "admin"
        assert sm.required_scope_for("zz_typo") == "admin"
        assert sm.required_scope_for("device_turn_on") == "write", "static sets are untouched"
    finally:
        sm.unregister_dynamic_scopes(["zz_read", "zz_write", "zz_bogus", "zz_typo"])
    assert sm.required_scope_for("zz_read") == "admin", "unregistered names fail closed again"


def test_audit_counts_dynamic_tools_as_classified(tmp_path, caplog):
    mgr = ScopeManager(scopes_file=str(tmp_path / "absent.json"), logger=_LOGGER)
    try:
        sm.register_dynamic_scope("zz_ext", "read")
        with caplog.at_level(logging.INFO):
            report = mgr.audit_classification(["device_turn_on", "zz_ext"])
        assert report["unclassified"] == []
        assert any("plugin-provided=1" in r.message for r in caplog.records)
    finally:
        sm.unregister_dynamic_scopes(["zz_ext"])
    report = mgr.audit_classification(["device_turn_on", "zz_ext"])
    assert report["unclassified"] == ["zz_ext"], "without registration the same name is a GAP"


# ── handler integration ──────────────────────────────────────────────────

def _handler(tmp_path, plugin_obj=None, get_plugin=None):
    h = object.__new__(MCPHandler)
    h.logger            = _LOGGER
    h.plugin            = plugin_obj
    h.scope_manager     = ScopeManager(scopes_file=str(tmp_path / "absent.json"), logger=_LOGGER)
    h.rate_limiter      = RateLimiter(logger=_LOGGER)
    h.tool_cache        = ToolCache(default_ttl=0, logger=_LOGGER)
    h._emitter_local    = threading.local()
    h._telemetry_lock   = threading.Lock()
    h._tool_call_log    = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools            = {"device_turn_on": {"description": "built-in", "inputSchema": {"type": "object"},
                                              "function": lambda **k: "{}"}}
    h._resources        = {}
    h._sessions         = {}
    h._sessions_lock    = threading.Lock()
    h._session_idle_ttl = 24 * 3600
    h._session_max      = 500
    h.vector_store_manager = None
    h._builtin_tool_names  = frozenset(h._tools)
    h.external_tools       = ExternalToolManager(logger=_LOGGER, self_plugin_id=h.SELF_PLUGIN_ID,
                                                 write_gate_supplier=h._external_writes_allowed,
                                                 get_plugin=get_plugin)
    h._external_lock        = threading.Lock()
    h._external_fingerprint = None
    h._external_checked_at  = 0.0
    return h


def test_refresh_registers_lists_dispatches_and_forgets(tmp_path):
    plugin = FakePlugin(reply=json.dumps({"status": "ok", "result": {"v": "1.0"}}))
    h = _handler(tmp_path, get_plugin=lambda pid: plugin)
    bundle = _bundle(tmp_path, PID, _text())
    try:
        result = h.refresh_external_tools(plugin_list=[bundle])
        assert result == {"tools": ["widgets_get_status", "widgets_set_mode"],
                          "providers": [PID], "removed": []}
        assert "device_turn_on" in h._tools, "built-ins are untouched"
        assert sm.required_scope_for("widgets_get_status") == "read"
        assert sm.required_scope_for("widgets_set_mode") == "write"

        listed = h._handle_tools_list(1, {})["result"]["tools"]
        names = {t["name"] for t in listed}
        assert {"widgets_get_status", "widgets_set_mode", "device_turn_on"} <= names
        ext = next(t for t in listed if t["name"] == "widgets_set_mode")
        assert ext["inputSchema"]["required"] == ["mode"]

        resp = h._handle_tools_call(2, {"name": "widgets_get_status", "arguments": {}},
                                    headers={"authorization": "Bearer t"})
        body = json.loads(resp["result"]["content"][0]["text"])
        assert body == {"success": True, "provider": PID, "result": {"v": "1.0"}}
        assert plugin.calls[-1][1]["tool"] == "get_status"

        missing = h._handle_tools_call(3, {"name": "widgets_set_mode", "arguments": {}},
                                       headers={"authorization": "Bearer t"})
        assert missing["error"]["code"] == -32602 and "mode" in missing["error"]["message"]
        unknown = h._handle_tools_call(4, {"name": "widgets_set_mode",
                                           "arguments": {"mode": "auto", "speed": 1}},
                                       headers={"authorization": "Bearer t"})
        assert unknown["error"]["code"] == -32602 and "speed" in unknown["error"]["message"]

        # The provider vanishes: its tools go, their scopes fail closed again.
        result = h.refresh_external_tools(plugin_list=[])
        assert result["removed"] == ["widgets_get_status", "widgets_set_mode"]
        assert "widgets_get_status" not in h._tools and "device_turn_on" in h._tools
        assert sm.required_scope_for("widgets_get_status") == "admin"
    finally:
        sm.unregister_dynamic_scopes(["widgets_get_status", "widgets_set_mode"])


def test_write_gate_reads_the_owning_plugins_pref_live(tmp_path):
    plugin = FakePlugin(reply=json.dumps({"status": "ok", "result": None}))
    owner = types.SimpleNamespace(external_tools_allow_writes=False,
                                  subscribe_to_provider_broadcasts=lambda ids: None)
    h = _handler(tmp_path, plugin_obj=owner, get_plugin=lambda pid: plugin)
    try:
        h.refresh_external_tools(plugin_list=[_bundle(tmp_path, PID, _text())])
        resp = h._handle_tools_call(5, {"name": "widgets_set_mode", "arguments": {"mode": "auto"}},
                                    headers={"authorization": "Bearer t"})
        body = json.loads(resp["result"]["content"][0]["text"])
        assert body["success"] is False and body["error"] == WRITE_GATE_MESSAGE
        assert plugin.calls == []
        owner.external_tools_allow_writes = True             # a Configure save, no restart
        resp = h._handle_tools_call(6, {"name": "widgets_set_mode", "arguments": {"mode": "auto"}},
                                    headers={"authorization": "Bearer t"})
        assert json.loads(resp["result"]["content"][0]["text"])["success"] is True
    finally:
        sm.unregister_dynamic_scopes(["widgets_get_status", "widgets_set_mode"])


def test_refresh_asks_the_plugin_to_subscribe_to_each_provider(tmp_path):
    seen = []
    owner = types.SimpleNamespace(external_tools_allow_writes=True,
                                  subscribe_to_provider_broadcasts=lambda ids: seen.append(list(ids)))
    h = _handler(tmp_path, plugin_obj=owner, get_plugin=lambda pid: FakePlugin(reply="{}"))
    try:
        h.refresh_external_tools(plugin_list=[_bundle(tmp_path, PID, _text())])
    finally:
        sm.unregister_dynamic_scopes(["widgets_get_status", "widgets_set_mode"])
    assert seen == [[PID]]


def test_tools_list_rescans_only_when_a_manifest_changed_and_not_more_than_once_a_minute(tmp_path, monkeypatch):
    h = _handler(tmp_path, get_plugin=lambda pid: FakePlugin(reply="{}"))
    calls = []
    monkeypatch.setattr(h, "refresh_external_tools", lambda plugin_list=None: calls.append(1))
    # Consumed only when a stat() actually happens: the throttled second call
    # must not advance it, or the third call would still see ("a",).
    fps = iter([("a",), ("b",)])
    monkeypatch.setattr("mcp_server.mcp_handler.manifest_fingerprint",
                        lambda self_id, plugin_list=None: next(fps))
    h._external_fingerprint = ("a",)
    h._external_checked_at  = 0.0
    h._maybe_rescan_external_tools()                 # same fingerprint -> no rescan
    assert calls == []
    h._maybe_rescan_external_tools()                 # inside the interval -> not even a stat
    assert calls == []
    h._external_checked_at = 0.0
    h._maybe_rescan_external_tools()                 # changed -> rescan
    assert calls == [1]


def test_skeletal_handler_without_the_subsystem_still_lists(tmp_path):
    """Older test skeletons (and a handler whose init failed part-way) have no
    external_tools attribute; tools/list must not care."""
    h = _handler(tmp_path)
    del h.external_tools
    assert h._handle_tools_list(1, {})["result"]["tools"][0]["name"] == "device_turn_on"


# ── the one real provider on this machine ────────────────────────────────

DASHBOARDS_MANIFEST = os.path.expanduser(
    "~/GitHub/Dashboards/Dashboards.indigoPlugin/Contents/Resources/mcp-manifest.json")


def test_the_dashboards_manifest_parses_under_this_reader():
    if not os.path.isfile(DASHBOARDS_MANIFEST):
        pytest.skip("Dashboards repo not on this machine")
    m = parse_manifest(open(DASHBOARDS_MANIFEST, encoding="utf-8").read(),
                       "com.clives.indigoplugin.dashboards", path=DASHBOARDS_MANIFEST)
    assert m.prefix == "dashboards" and len(m.tools) == 8
    assert {t.name for t in m.tools if t.write} == {"set_room_folders", "set_camera", "remove_camera"}
