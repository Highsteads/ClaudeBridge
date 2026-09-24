#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_automation_arguments.py
# Description: Argument handling from the 3.0.1 review. A null means "not
#              given": coerce_bool(None) was False, so set_enabled(enabled=null)
#              DISABLED an automation and a null include_server_check switched
#              a check off. Also: whole-second timing, action groups by name,
#              Z-Wave parameter widths, energy comparison windows, and an id
#              argument that must not accept true as 1.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
from types import SimpleNamespace

import pytest

from conftest import call_tool
from test_toolsets import _ctx, _nothing_called

from mcp_server.toolsets._schema import coerce_bool


# ── coerce_bool ──────────────────────────────────────────────────────────────

def test_none_takes_the_default():
    assert coerce_bool(None) is False
    assert coerce_bool(None, default=True) is True
    assert coerce_bool("false", default=True) is False
    assert coerce_bool(True, default=False) is True


def test_extended_tools_uses_the_one_coercion():
    from mcp_server.tools.extended_tools import extended_tools_handler as eth
    assert eth._coerce_bool is coerce_bool


# ── automation tools: null is "not given" ────────────────────────────────────

def test_set_enabled_refuses_a_null_rather_than_disabling():
    ctx = _ctx()
    out = call_tool(ctx, "set_enabled", kind="trigger", id=3, enabled=None)
    assert out["success"] is False and "enabled is required" in out["error"]
    _nothing_called(ctx)


def test_null_checks_keep_their_default_of_on():
    ctx = _ctx()
    call_tool(ctx, "find_automation_references", entity_type="device", entity_id=5,
              include_server_check=None, include_scripts=None)
    assert ctx.automation_detail_handler.calls[0][2] == {"include_server_check": True,
                                                         "include_scripts": True}
    call_tool(ctx, "get_automation", kind="trigger", id=4, include_scripts=None)
    assert ctx.automation_detail_handler.calls[1][2] == {"include_scripts": True}


def test_investigate_event_nulls_take_the_defaults():
    ctx = _ctx()
    call_tool(ctx, "investigate_event", device_id=5, occurrence=None, lookback_seconds=None,
              lookahead_seconds=None, search_days=None)
    kwargs = ctx.automation_detail_handler.calls[0][2]
    assert (kwargs["occurrence"], kwargs["lookback_seconds"], kwargs["lookahead_seconds"],
            kwargs["search_days"]) == (1, 60, 5, 2)


@pytest.mark.parametrize("field,value", [("delay_seconds", -5), ("duration_seconds", 2.5),
                                         ("duration_seconds", True),
                                         ("delay_seconds", "soon")])
def test_set_enabled_refuses_timing_that_is_not_whole_seconds(field, value):
    ctx = _ctx()
    out = call_tool(ctx, "set_enabled", kind="schedule", id=3, enabled=True, **{field: value})
    assert out["success"] is False and field in out["error"]
    _nothing_called(ctx)


def test_set_enabled_accepts_a_whole_float():
    ctx = _ctx()
    out = call_tool(ctx, "set_enabled", kind="schedule", id=3, enabled=True,
                    duration_seconds=600.0)
    assert out["success"] is True


# ── action groups by name ────────────────────────────────────────────────────

def test_an_action_group_name_is_resolved(monkeypatch):
    from mcp_server.toolsets import automations
    monkeypatch.setattr(automations, "_resolve_action_group",
                        lambda n: SimpleNamespace(id=42) if n == "Bedtime" else None)
    ctx = _ctx()
    call_tool(ctx, "action_execute_group", action_group_id="Bedtime")
    assert ctx.action_control_handler.calls == [("execute", (42, None), {})]
    ctx = _ctx()
    out = call_tool(ctx, "action_execute_group", action_group_id="Nothing Here")
    assert out["success"] is False and "No action group" in out["error"]
    _nothing_called(ctx)
    ctx = _ctx()
    call_tool(ctx, "action_execute_group", action_group_id="17")
    assert ctx.action_control_handler.calls == [("execute", ("17", None), {})]


# ── webhook ids ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [(True, "error"), (2.7, "error"), ("hall", "error"),
                                            (5.0, 5), ("12", 12), (None, None)])
def test_webhook_opt_int(value, expected):
    from mcp_server.tools.webhooks.webhook_handler import WebhookHandler
    got = WebhookHandler._opt_int(value, "entity_id")
    if expected == "error":
        assert isinstance(got, dict) and got["success"] is False
    else:
        assert got == expected


# ── Z-Wave configuration parameters ──────────────────────────────────────────

class _ZWave:
    def __init__(self, reply=None):
        self.calls, self.reply = [], reply

    def sendConfigParm(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.fixture()
def zw(monkeypatch):
    import indigo
    from mcp_server.tools.extended_tools.extended_tools_handler import ExtendedToolsHandler

    def _make(reply=None):
        z = _ZWave(reply)
        monkeypatch.setattr(indigo, "devices", {9: SimpleNamespace(id=9, name="Sensor")})
        monkeypatch.setattr(indigo, "zwave", z, raising=False)
        return ExtendedToolsHandler(None, logger=logging.getLogger("t")), z
    return _make


@pytest.mark.parametrize("size,value", [(1, 256), (1, -129), (2, 65536), (4, 2 ** 32)])
def test_a_value_wider_than_the_parameter_is_refused(zw, size, value):
    ext, z = zw()
    out = ext.zwave_send_config_parameter(9, 3, size, value)
    assert out["success"] is False and "does not fit" in out["error"]
    assert z.calls == []


def test_the_default_is_not_to_wait_for_an_ack(zw):
    ext, z = zw()
    out = ext.zwave_send_config_parameter(9, 3, 1, 255)
    assert z.calls[0]["waitUntilAck"] is False
    assert out["success"] is True and out["acknowledged"] is None


def test_a_refused_ack_is_reported_as_a_failure(zw):
    ext, z = zw(reply={"success": False})
    out = ext.zwave_send_config_parameter(9, 3, 2, -1, wait_for_ack=True)
    assert z.calls[0]["waitUntilAck"] is True
    assert out["success"] is False and out["acknowledged"] is False


def test_the_zwave_tool_passes_false_when_wait_is_not_given():
    ctx = _ctx()
    call_tool(ctx, "zwave", action="set_config_parameter", device_id=7, param_index=3,
              param_size=1, param_value=5, wait_for_ack=None)
    assert ctx.extended_tools_handler.calls[0][2]["wait_for_ack"] is False


# ── energy comparison windows ────────────────────────────────────────────────

@pytest.fixture()
def energy(monkeypatch):
    from mcp_server.tools.energy_tools import energy_tools_handler as eth
    h = eth.EnergyToolsHandler(None, logger=logging.getLogger("t"))
    monkeypatch.setattr(h, "_history", lambda: {})
    return h


def test_the_default_offset_follows_the_clamped_period(energy):
    out = energy.energy_compare(200, 200)
    assert out["period_a"]["label"] == "last 90 complete days"
    assert "90 days ending 90 days before" in out["period_b"]["label"]
    assert any("period_a_days 200" in n for n in out["notes"])


def test_overlapping_windows_are_named(energy):
    out = energy.energy_compare(7, 7, 3)
    assert any("overlap" in n and "share 4 day" in n for n in out["notes"])


def test_side_by_side_windows_carry_no_notes(energy):
    assert "notes" not in energy.energy_compare(7, 7, 7)
