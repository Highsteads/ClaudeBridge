#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_toolsets.py
# Description: Action routing and refusals for every consolidated 3.0 tool.
#              Each tool is run through the real registry wrapper against a
#              context of recording stand-ins, so the test sees exactly which
#              handler method a choice reaches, with which arguments — and that
#              a wrong or stray argument is refused before anything is called.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import logging
from types import SimpleNamespace

import pytest

from conftest import call_tool


class Recorder:
    """Stands in for a handler: every method call is recorded and answers
    {"success": True, "via": <method>} unless told otherwise."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __getattr__(self, method):
        if method.startswith("__"):
            raise AttributeError(method)

        def _call(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            reply = self.replies.get(method, {"success": True, "via": method})
            return reply(*args, **kwargs) if callable(reply) else dict(reply)
        return _call


class Search:
    """The search handler device names resolve through."""

    def __init__(self, devices):
        self.devices = devices

    def search(self, query=None, entity_types=None, detail=None, **_):
        return {"results": {"devices": self.devices}}


def _ctx(devices=None, **overrides):
    ctx = SimpleNamespace(
        logger=logging.getLogger("test-toolsets"),
        plugin=None,
        search_handler=Search(devices or []),
    )
    for name in ("device_control_handler", "extended_tools_handler", "list_handlers",
                 "get_devices_by_type_handler", "automation_detail_handler",
                 "schedule_control_handler", "home_status_handler", "energy_tools_handler",
                 "system_tools_handler", "audit_handler", "script_tools_handler",
                 "scripting_shell_handler", "plugin_control_handler",
                 "plugin_dev_tools_handler", "variable_control_handler",
                 "action_control_handler", "log_query_handler", "data_provider"):
        setattr(ctx, name, overrides.get(name, Recorder()))
    return ctx


def _only_call(recorder):
    assert len(recorder.calls) == 1, recorder.calls
    return recorder.calls[0]


def _nothing_called(ctx):
    for value in vars(ctx).values():
        if isinstance(value, Recorder):
            assert value.calls == [], value.calls


# ── device_control ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,handler,method,call_args", [
    ({"action": "on"}, "device_control_handler", "turn_on", ((5,), {"delay": 0, "duration": 0})),
    ({"action": "on", "duration": 600}, "device_control_handler", "turn_on",
     ((5,), {"delay": 0, "duration": 600})),
    ({"action": "off", "delay": 30}, "device_control_handler", "turn_off",
     ((5,), {"delay": 30, "duration": 0})),
    ({"action": "toggle"}, "extended_tools_handler", "device_toggle", ((5,), {})),
    ({"action": "brightness", "value": 40}, "device_control_handler", "set_brightness", ((5, 40), {})),
    ({"action": "brighten", "value": 10}, "extended_tools_handler", "dimmer_brighten_by", ((5, 10), {})),
    ({"action": "dim", "value": 10}, "extended_tools_handler", "dimmer_dim_by", ((5, 10), {})),
    ({"action": "color", "red": 1, "green": 2, "blue": 3}, "device_control_handler", "set_color",
     ((5, 1, 2, 3), {"white": None, "white_temperature": None})),
    ({"action": "color", "color": "#ff8000", "white": 9}, "device_control_handler", "set_color",
     ((5, 255, 128, 0), {"white": 9, "white_temperature": None})),
    ({"action": "status_request"}, "device_control_handler", "request_status_update", ((5,), {})),
    ({"action": "beep"}, "extended_tools_handler", "beep_device", ((5,), {})),
    ({"action": "ping"}, "extended_tools_handler", "ping_device", ((5,), {})),
    ({"action": "reset_energy"}, "extended_tools_handler", "reset_energy_accumulator", ((5,), {})),
])
def test_device_control_routes_every_action(args, handler, method, call_args):
    ctx = _ctx()
    out = call_tool(ctx, "device_control", device=5, **args)
    assert out["via"] == method
    assert _only_call(getattr(ctx, handler)) == (method, *call_args)


def test_device_control_resolves_a_name_and_says_what_it_matched():
    ctx = _ctx(devices=[{"id": 77, "name": "Hall Lamp", "relevance_score": 1.0},
                        {"id": 78, "name": "Hall Lamp Two", "relevance_score": 0.4}])
    out = call_tool(ctx, "device_control", device="hall lamp", action="on")
    assert ctx.device_control_handler.calls[0][1] == (77,)
    assert out["matched_device"] == "Hall Lamp" and "elapsed_ms" in out


def test_device_control_refuses_an_ambiguous_name():
    ctx = _ctx(devices=[{"id": 1, "name": "Hall Lamp Left", "relevance_score": 1.0},
                        {"id": 2, "name": "Hall Lamp Right", "relevance_score": 1.0}])
    out = call_tool(ctx, "device_control", device="hall lamp", action="off")
    assert out["success"] is False and "matches 2 devices" in out["error"]
    assert [c["id"] for c in out["candidates"]] == [1, 2]
    _nothing_called(ctx)


@pytest.mark.parametrize("args,needle", [
    ({"action": "on", "value": 50}, "value"),
    ({"action": "toggle", "delay": 5}, "delay"),
    ({"action": "brightness"}, "needs value"),
    ({"action": "explode"}, "action must be one of"),
    ({"action": "color"}, "red/green/blue"),
    ({"action": "color", "color": "not-a-colour"}, "not-a-colour"),
])
def test_device_control_refusals(args, needle):
    ctx = _ctx()
    out = call_tool(ctx, "device_control", device=5, **args)
    assert out["success"] is False and needle in out["error"]
    _nothing_called(ctx)


@pytest.mark.parametrize("device", [True, "", None, 4.5])
def test_device_control_refuses_a_non_device(device):
    ctx = _ctx()
    out = call_tool(ctx, "device_control", device=device, action="on")
    assert out["success"] is False
    _nothing_called(ctx)


# ── thermostat_control ───────────────────────────────────────────────────────

def test_thermostat_control_applies_every_change_in_order():
    ctx = _ctx()
    out = call_tool(ctx, "thermostat_control", device=9, fan_mode="auto", hvac_mode="heat",
                    heat_delta=-0.5, cool_setpoint=24, heat_setpoint=20, cool_delta=1)
    assert out["success"] is True
    assert [d["step"] for d in out["done"]] == ["heat_setpoint", "cool_setpoint", "heat_delta",
                                                "cool_delta", "hvac_mode", "fan_mode"]
    methods = [c[0] for c in ctx.device_control_handler.calls]
    assert methods == ["set_heat_setpoint", "set_cool_setpoint", "decrease_heat_setpoint",
                       "increase_cool_setpoint", "set_hvac_mode"]
    assert ctx.device_control_handler.calls[2][1] == (9, 0.5), "a negative delta steps DOWN"
    assert _only_call(ctx.extended_tools_handler)[0] == "set_fan_mode"


def test_thermostat_control_stops_at_the_first_failure():
    dc = Recorder({"set_cool_setpoint": {"success": False, "error": "out of range"}})
    ctx = _ctx(device_control_handler=dc)
    out = call_tool(ctx, "thermostat_control", device=9, heat_setpoint=20, cool_setpoint=99,
                    hvac_mode="cool")
    assert out["success"] is False and "cool_setpoint failed: out of range" in out["error"]
    assert [d["step"] for d in out["done"]] == ["heat_setpoint"]
    assert out["not_attempted"] == ["hvac_mode"]
    assert [c[0] for c in dc.calls] == ["set_heat_setpoint", "set_cool_setpoint"]


@pytest.mark.parametrize("args,needle", [({}, "at least one"), ({"heat_delta": 0}, "must not be 0")])
def test_thermostat_control_refusals(args, needle):
    ctx = _ctx()
    out = call_tool(ctx, "thermostat_control", device=9, **args)
    assert out["success"] is False and needle in out["error"]
    _nothing_called(ctx)


# ── speed, sprinkler, broadcasts, locks ──────────────────────────────────────

@pytest.mark.parametrize("args,handler,method", [
    ({"level": 60}, "device_control_handler", "set_fan_speed"),
    ({"index": 2}, "extended_tools_handler", "speedcontrol_set_index"),
    ({"step": 1}, "extended_tools_handler", "speedcontrol_increase"),
    ({"step": -1}, "extended_tools_handler", "speedcontrol_decrease"),
])
def test_speed_control_routes(args, handler, method):
    ctx = _ctx()
    call_tool(ctx, "speed_control", device=3, **args)
    assert _only_call(getattr(ctx, handler))[0] == method


@pytest.mark.parametrize("args", [{}, {"level": 50, "index": 1}, {"step": 2}])
def test_speed_control_refusals(args):
    ctx = _ctx()
    assert call_tool(ctx, "speed_control", device=3, **args)["success"] is False
    _nothing_called(ctx)


@pytest.mark.parametrize("action", ["run", "stop", "pause", "resume", "next_zone", "previous_zone"])
def test_sprinkler_control_routes(action):
    ctx = _ctx()
    call_tool(ctx, "sprinkler_control", device=4, action=action)
    assert _only_call(ctx.extended_tools_handler) == (f"sprinkler_{action}", (4,), {})


def test_sprinkler_set_zone_needs_a_zone_and_nothing_else_takes_one():
    ctx = _ctx()
    call_tool(ctx, "sprinkler_control", device=4, action="set_zone", zone=3)
    assert _only_call(ctx.extended_tools_handler) == ("sprinkler_set_zone", (4, 3), {})
    ctx = _ctx()
    assert "needs zone" in call_tool(ctx, "sprinkler_control", device=4, action="set_zone")["error"]
    assert "zone" in call_tool(ctx, "sprinkler_control", device=4, action="run", zone=2)["error"]
    _nothing_called(ctx)


@pytest.mark.parametrize("action,method", [("lights_on", "all_lights_on"),
                                           ("lights_off", "all_lights_off"),
                                           ("all_off", "all_devices_off")])
def test_all_devices_routes(action, method):
    ctx = _ctx()
    call_tool(ctx, "all_devices", action=action)
    assert _only_call(ctx.extended_tools_handler)[0] == method


def test_all_devices_refuses_an_unknown_broadcast():
    ctx = _ctx()
    assert call_tool(ctx, "all_devices", action="everything_on")["success"] is False
    _nothing_called(ctx)


def test_lock_control_routes_and_takes_no_pin():
    """indigo.device.unlock has no code parameter (official docs), so the tool
    no longer offers one: the schema lists device and action only."""
    from mcp_server import registry
    ctx = _ctx()
    call_tool(ctx, "lock_control", device=8, action="lock")
    call_tool(ctx, "lock_control", device=8, action="unlock")
    assert ctx.device_control_handler.calls == [("lock_device", (8,), {}),
                                                ("unlock_device", (8,), {})]
    assert "code" not in registry.spec_for("lock_control").properties


# ── list_devices ─────────────────────────────────────────────────────────────

def test_list_devices_routes_each_combination():
    ctx = _ctx(list_handlers=Recorder({
        "list_all_devices": lambda *a, **k: [{"id": 1}],
        "get_devices_by_state": lambda *a, **k: {"devices": [{"id": i} for i in range(5)],
                                                  "count": 5}}))
    everything = call_tool(ctx, "list_devices")
    assert everything == [{"id": 1}]

    call_tool(ctx, "list_devices", device_type="light", limit=7)
    assert _only_call(ctx.get_devices_by_type_handler) == ("get_devices", ("light",), {"limit": 7})

    out = call_tool(ctx, "list_devices", state_filter={"onState": True}, device_type="switch",
                    limit=2)
    method, args, _ = ctx.list_handlers.calls[-1]
    assert method == "get_devices_by_state" and args == ({"onState": True}, ["relay"])
    assert out["count"] == 2 and out["total_matched"] == 5 and out["truncated"] is True


def test_list_devices_refusals():
    ctx = _ctx()
    assert "limit" in call_tool(ctx, "list_devices", limit=5)["error"]
    bad = call_tool(ctx, "list_devices", state_filter={"onState": True}, device_type="toaster")
    assert "Invalid device types" in bad["error"]
    _nothing_called(ctx)


# ── automations ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["trigger", "schedule", "action_group"])
def test_get_automation_routes(kind):
    ctx = _ctx()
    call_tool(ctx, "get_automation", kind=kind, id="Front door", include_scripts=False)
    assert _only_call(ctx.automation_detail_handler) == (
        "get_details", (kind, "Front door"), {"include_scripts": False})


@pytest.mark.parametrize("tool,args", [
    ("get_automation", {"kind": "device", "id": 1}),
    ("update_automation", {"kind": "variable", "id": 1, "fields": {}}),
    ("delete_automation", {"kind": "folder", "id": 1}),
    ("set_enabled", {"kind": "action_group", "id": 1, "enabled": True}),
    ("get_dependencies", {"kind": "plugin", "id": 1}),
])
def test_a_wrong_kind_is_refused(tool, args):
    ctx = _ctx()
    out = call_tool(ctx, tool, **args)
    assert out["success"] is False and "kind must be one of" in out["error"]
    _nothing_called(ctx)


def test_get_dependencies_routes_and_points_devices_at_references():
    ctx = _ctx()
    out = call_tool(ctx, "get_dependencies", kind="device", id=12)
    assert _only_call(ctx.extended_tools_handler) == ("get_dependencies", ("device", 12), {})
    assert "find_automation_references" in out["see_also"]
    ctx = _ctx()
    assert "see_also" not in call_tool(ctx, "get_dependencies", kind="schedule", id=12)


@pytest.mark.parametrize("kind,enabled,method", [
    ("trigger", True, "enable_trigger"), ("trigger", False, "disable_trigger"),
    ("schedule", True, "enable_schedule"), ("schedule", "false", "disable_schedule"),
])
def test_set_enabled_routes_and_keeps_the_timing(kind, enabled, method):
    ctx = _ctx()
    call_tool(ctx, "set_enabled", kind=kind, id=3, enabled=enabled, duration_seconds=1800)
    assert _only_call(ctx.schedule_control_handler) == (
        method, (3,), {"delay_seconds": None, "duration_seconds": 1800})


@pytest.mark.parametrize("kind", ["trigger", "schedule", "action_group"])
def test_update_and_delete_automation_route(kind):
    ctx = _ctx()
    call_tool(ctx, "update_automation", kind=kind, id=6, fields={"name": "x"})
    assert _only_call(ctx.schedule_control_handler) == (f"update_{kind}", (6, {"name": "x"}), {})
    call_tool(ctx, "delete_automation", kind=kind, id=6)
    assert _only_call(ctx.extended_tools_handler) == (f"delete_{kind}", (6,), {})


def test_remove_delayed_actions_routes_and_refuses(monkeypatch):
    from mcp_server.toolsets import automations
    monkeypatch.setattr(automations, "_resolve_schedule",
                        lambda i: SimpleNamespace(id=int(i)) if str(i) == "6" else None)
    monkeypatch.setattr(automations, "_resolve_trigger",
                        lambda i: SimpleNamespace(id=71) if i == "Porch motion" else None)
    ctx = _ctx()
    call_tool(ctx, "remove_delayed_actions", kind="device", id=5)
    call_tool(ctx, "remove_delayed_actions", kind="schedule", id=6)
    call_tool(ctx, "remove_delayed_actions", kind="trigger", id="Porch motion")
    call_tool(ctx, "remove_delayed_actions", kind="all")
    assert [c[:2] for c in ctx.extended_tools_handler.calls] == [
        ("device_remove_delayed_actions", (5,)), ("schedule_remove_delayed_actions", (6,)),
        ("trigger_remove_delayed_actions", (71,)), ("remove_all_delayed_actions", ())]
    ctx = _ctx()
    assert "No trigger matches" in call_tool(ctx, "remove_delayed_actions", kind="trigger",
                                             id="nope")["error"]
    ctx = _ctx()
    assert "does not apply" in call_tool(ctx, "remove_delayed_actions", kind="all", id=5)["error"]
    assert "needs id" in call_tool(ctx, "remove_delayed_actions", kind="device")["error"]
    _nothing_called(ctx)


# ── organising ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["device", "schedule", "action_group"])
def test_duplicate_routes(kind):
    ctx = _ctx()
    call_tool(ctx, "duplicate", kind=kind, id=2, new_name="Copy")
    assert _only_call(ctx.extended_tools_handler) == (f"duplicate_{kind}", (2,), {"new_name": "Copy"})


@pytest.mark.parametrize("kind,method", [("device", "move_device_to_folder"),
                                         ("variable", "variable_move_to_folder"),
                                         ("trigger", "move_trigger_to_folder")])
def test_move_to_folder_routes(kind, method):
    ctx = _ctx()
    call_tool(ctx, "move_to_folder", kind=kind, id=2, folder_id=0)
    assert _only_call(ctx.extended_tools_handler) == (method, (2, 0), {})


@pytest.mark.parametrize("kind", ["device", "variable"])
def test_folders_route(kind):
    ctx = _ctx()
    call_tool(ctx, "create_folder", kind=kind, name="Garage")
    call_tool(ctx, "delete_folder", kind=kind, folder="Garage", delete_children="false")
    assert ctx.system_tools_handler.calls == [(f"create_{kind}_folder", ("Garage",), {}),
                                              (f"delete_{kind}_folder", ("Garage", False), {})]


@pytest.mark.parametrize("tool,args", [
    ("duplicate", {"kind": "variable", "id": 1}),
    ("move_to_folder", {"kind": "schedule", "id": 1, "folder_id": 0}),
    ("create_folder", {"kind": "trigger", "name": "x"}),
    ("delete_folder", {"kind": "trigger", "folder": "x"}),
])
def test_organising_refuses_a_kind_it_cannot_handle(tool, args):
    ctx = _ctx()
    assert "kind must be one of" in call_tool(ctx, tool, **args)["error"]
    _nothing_called(ctx)


# ── server reads ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section,method,args", [
    ("summary", "home_status", ()), ("energy", "energy_status", ()),
    ("heating", "heating_status", ()), ("security", "security_status", ()),
    ("report", "home_status_report", (["alerts"],)),
])
def test_home_status_routes(section, method, args):
    ctx = _ctx()
    extra = {"report_sections": ["alerts"]} if section == "report" else {}
    call_tool(ctx, "home_status", section=section, **extra)
    assert _only_call(ctx.home_status_handler) == (method, args, {})


def test_home_status_default_is_the_summary_and_report_sections_need_a_report():
    ctx = _ctx()
    call_tool(ctx, "home_status")
    assert _only_call(ctx.home_status_handler)[0] == "home_status"
    ctx = _ctx()
    assert "report_sections" in call_tool(ctx, "home_status", report_sections=["energy"])["error"]
    assert "section must be" in call_tool(ctx, "home_status", section="garden")["error"]
    _nothing_called(ctx)


def test_energy_history_routes_and_refuses():
    ctx = _ctx()
    call_tool(ctx, "energy_history")
    call_tool(ctx, "energy_history", days=7, compare=True)
    call_tool(ctx, "energy_history", days=7, compare=True, compare_offset_days=364)
    assert ctx.energy_tools_handler.calls == [("energy_daily_summary", (14,), {}),
                                              ("energy_compare", (7, 7, None), {}),
                                              ("energy_compare", (7, 7, 364), {})]
    ctx = _ctx()
    assert "compare=true" in call_tool(ctx, "energy_history", compare_offset_days=3)["error"]
    _nothing_called(ctx)


def test_server_info_assembles_one_reply_and_guards_a_missing_reflector():
    st = Recorder({
        "get_indigo_paths": {"success": True, "paths": {"install_folder": "/x"}},
        "get_reflector_url": {"success": True, "configured": False, "url": ""},
        "get_reflector_status": {"success": False, "error": "no reflector"},
    })
    ext = Recorder({
        "get_web_server_url": {"success": True, "url": "http://localhost:8176"},
        "get_latitude_longitude": {"success": True, "latitude": 54.9, "longitude": -1.8},
        "calculate_sunrise": {"success": True, "sunrise": "2026-09-23T06:50:00"},
        "calculate_sunset": {"success": True, "sunset": "2026-09-23T19:05:00"},
    })
    out = call_tool(_ctx(system_tools_handler=st, extended_tools_handler=ext),
                    "server_info", date_iso="2026-09-23")
    assert out["success"] is True
    assert out["paths"] == {"install_folder": "/x"}
    assert out["web_server_url"] == "http://localhost:8176"
    assert out["reflector"] == {"url": None, "status": None}
    assert out["errors"] == {"reflector_status": "no reflector"}
    assert out["location"] == {"latitude": 54.9, "longitude": -1.8}
    assert out["sun"]["sunrise"].startswith("2026-09-23T06")
    assert ("calculate_sunrise", ("2026-09-23",), {}) in ext.calls


@pytest.mark.parametrize("check,args,handler,method,kwargs", [
    ("home", {}, "audit_handler", "audit_home", {}),
    ("errors", {}, "audit_handler", "find_devices_in_error", {}),
    ("low_battery", {"threshold": 15}, "audit_handler", "find_low_battery", {"threshold": 15}),
    ("stale", {"days": 3}, "audit_handler", "find_stale_devices", {"days": 3}),
    ("variables", {}, "audit_handler", "audit_variables", {}),
    ("conflicts", {}, "audit_handler", "find_conflicts", {}),
    ("orphaned_scripts", {}, "system_tools_handler", "find_orphaned_scripts", {}),
    ("orphaned_plugin_data", {}, "system_tools_handler", "find_orphaned_plugin_data", {}),
    ("deprecated", {"include_warnings": True}, "extended_tools_handler",
     "get_deprecated_elements", {"include_warnings": True}),
    ("api_coverage", {}, "system_tools_handler", "audit_api_coverage", {}),
    ("large_files", {"min_mb": 50, "path": "/tmp"}, "system_tools_handler", "find_large_files",
     {"min_mb": 50, "path": "/tmp"}),
])
def test_audit_routes_every_check(check, args, handler, method, kwargs):
    ctx = _ctx()
    call_tool(ctx, "audit", check=check, **args)
    assert _only_call(getattr(ctx, handler)) == (method, (), kwargs)


def test_audit_refuses_an_argument_its_check_does_not_use():
    ctx = _ctx()
    out = call_tool(ctx, "audit", check="home", threshold=10)
    assert out["success"] is False and "threshold" in out["error"] and "'home'" in out["error"]
    assert "check must be one of" in call_tool(ctx, "audit", check="everything")["error"]
    _nothing_called(ctx)


def test_control_pages_lists_or_reads_one():
    ctx = _ctx()
    call_tool(ctx, "control_pages")
    call_tool(ctx, "control_pages", page_id=44)
    assert ctx.extended_tools_handler.calls == [("list_control_pages", (), {}),
                                                ("get_control_page", (44,), {})]


# ── scripts and plugins ──────────────────────────────────────────────────────

def test_list_python_scripts_or_one_scripts_backups():
    ctx = _ctx()
    call_tool(ctx, "list_python_scripts")
    call_tool(ctx, "list_python_scripts", backups_for="Night.py")
    assert _only_call(ctx.system_tools_handler)[0] == "list_python_scripts"
    assert _only_call(ctx.script_tools_handler) == ("list_script_backups", ("Night.py",), {})


def test_write_script_create_flag_picks_the_right_guard():
    ctx = _ctx()
    call_tool(ctx, "write_script", name="a.py", content="x")
    call_tool(ctx, "write_script", name="b.py", content="y", create=True)
    assert ctx.script_tools_handler.calls == [("write_script", ("a.py", "x"), {}),
                                              ("create_script", ("b.py", "y"), {})]


def test_write_script_keeps_both_existence_refusals(tmp_path, monkeypatch):
    """create=false refuses a missing file; create=true refuses an existing one."""
    from mcp_server.tools.script_tools import script_tools_handler as sth
    target = tmp_path / "Thing.py"
    monkeypatch.setattr(sth, "_resolve", lambda name: str(target))
    ctx = _ctx(script_tools_handler=sth.ScriptToolsHandler(data_provider=None,
                                                           logger=logging.getLogger("t")))
    missing = call_tool(ctx, "write_script", name="Thing.py", content="print(1)\n")
    assert missing["success"] is False and "create=true" in missing["error"]
    made = call_tool(ctx, "write_script", name="Thing.py", content="print(1)\n", create=True)
    assert made["success"] is True and target.read_text() == "print(1)\n"
    again = call_tool(ctx, "write_script", name="Thing.py", content="print(2)\n", create=True)
    assert again["success"] is False and "already exists" in again["error"]
    assert target.read_text() == "print(1)\n"


def test_plugin_check_runs_every_check_and_one_failure_stops_nothing():
    dev = Recorder({"plugin_lint": lambda name: (_ for _ in ()).throw(RuntimeError("lint broke"))})
    out = call_tool(_ctx(plugin_dev_tools_handler=dev), "plugin_check", plugin_name="Widgets")
    assert [c[0] for c in dev.calls] == ["plugin_validate_xml", "plugin_node_check_html",
                                         "plugin_lint", "plugin_diff_source_vs_installed",
                                         "plugin_show_packages_versions"]
    assert out["success"] is True and out["failed_checks"] == ["lint"]
    assert out["checks"]["lint"]["error"] == "RuntimeError: lint broke"
    assert out["checks"]["xml"]["via"] == "plugin_validate_xml"


def test_plugin_check_subset_all_failing_and_unknown():
    dev = Recorder({"plugin_lint": {"success": False, "error": "no plugin.py"}})
    out = call_tool(_ctx(plugin_dev_tools_handler=dev), "plugin_check",
                    plugin_name="Widgets", checks=["lint"])
    assert out["success"] is False and "every check failed" in out["error"]
    ctx = _ctx()
    assert "unknown check" in call_tool(ctx, "plugin_check", plugin_name="W",
                                        checks=["xml", "spelling"])["error"]
    _nothing_called(ctx)


def test_get_plugin_status_reports_running_from_the_real_handler(monkeypatch):
    """get_plugin_status absorbed get_plugin_by_id: it must still say `running`."""
    from mcp_server.tools.plugin_control import plugin_control_handler as pch
    handler = pch.PluginControlHandler(data_provider=None, logger=logging.getLogger("t"))
    handler._get_cached_plugins = lambda include_disabled: [
        {"id": "com.example.widgets", "name": "Widgets", "version": "1.2", "path": "/p"}]
    fake = SimpleNamespace(isEnabled=lambda: True, isRunning=lambda: False,
                           pluginDisplayName="Widgets")
    monkeypatch.setattr(pch.indigo.server, "getPlugin", lambda pid: fake, raising=False)
    out = call_tool(_ctx(plugin_control_handler=handler), "get_plugin_status",
                    plugin_id="com.example.widgets")
    assert out["status"]["running"] is False and out["status"]["version"] == "1.2"
    missing = call_tool(_ctx(plugin_control_handler=handler), "get_plugin_status",
                        plugin_id="com.example.nothing")
    assert missing["success"] is False and "not found" in missing["error"]


def test_restart_plugin_still_refuses_claude_bridge_itself():
    from mcp_server.tools.plugin_control import plugin_control_handler as pch
    handler = pch.PluginControlHandler(data_provider=None, logger=logging.getLogger("t"))
    out = call_tool(_ctx(plugin_control_handler=handler), "restart_plugin",
                    plugin_id="com.clives.indigoplugin.claudebridge")
    assert out["success"] is False and "Plugins menu" in out["error"]


def test_the_menu_tools_keep_their_self_guards():
    from mcp_server.tools.scripting_shell.scripting_shell_handler import ScriptingShellHandler
    shell = ScriptingShellHandler(data_provider=None, logger=logging.getLogger("t"))
    ctx = _ctx(scripting_shell_handler=shell)
    one = call_tool(ctx, "execute_plugin_menu_item", plugin_name="Claude Bridge",
                    menu_item_name="Reload")
    assert one["success"] is False and "Claude Bridge" in one["error"]
    two = call_tool(ctx, "execute_client_menu_item", path=["Plugins", "Claude Bridge", "Reload"])
    assert two["success"] is False


# ── zwave and webhooks ───────────────────────────────────────────────────────

@pytest.mark.parametrize("action,args,method,call", [
    ("set_config_parameter", {"device_id": 7, "param_index": 3, "param_size": 1, "param_value": 5},
     "zwave_send_config_parameter",
     ((7,), {"param_index": 3, "param_size": 1, "param_value": 5, "wait_for_ack": False})),
    ("start_optimize", {"device_id": 7}, "zwave_start_network_optimize", ((7,), {})),
    ("start_optimize", {}, "zwave_start_network_optimize", ((None,), {})),
    ("stop_optimize", {}, "zwave_stop_network_optimize", ((), {})),
    ("enter_inclusion", {"use_encryption": True}, "zwave_enter_inclusion_mode",
     ((), {"use_encryption": True})),
    ("enter_exclusion", {}, "zwave_enter_exclusion_mode", ((), {})),
    ("exit_inclusion_exclusion", {}, "zwave_exit_inclusion_exclusion_mode", ((), {})),
])
def test_zwave_routes(action, args, method, call):
    ctx = _ctx()
    call_tool(ctx, "zwave", action=action, **args)
    assert _only_call(ctx.extended_tools_handler) == (method, *call)


def test_zwave_refusals():
    ctx = _ctx()
    assert "needs param_size, param_value" in call_tool(
        ctx, "zwave", action="set_config_parameter", device_id=7, param_index=1)["error"]
    assert "use_encryption" in call_tool(
        ctx, "zwave", action="enter_exclusion", use_encryption=True)["error"]
    _nothing_called(ctx)


def test_webhooks_route_to_the_plugins_handler_or_refuse():
    ctx = _ctx()
    assert "not initialised" in call_tool(ctx, "webhook_list")["error"]
    ctx.plugin = SimpleNamespace(webhook_handler=Recorder())
    call_tool(ctx, "webhook_list", subscription_id="s1")
    call_tool(ctx, "webhook_delete", subscription_id="s1")
    assert ctx.plugin.webhook_handler.calls == [
        ("list_subscriptions", (), {"subscription_id": "s1"}),
        ("delete_subscription", (), {"subscription_id": "s1"})]


def test_an_exception_in_a_tool_becomes_a_failure_payload():
    ctx = _ctx(device_control_handler=Recorder(
        {"turn_on": lambda *a, **k: (_ for _ in ()).throw(KeyError("gone"))}))
    out = call_tool(ctx, "device_control", device=1, action="on")
    assert out == {"success": False, "error": "KeyError: 'gone'"}
