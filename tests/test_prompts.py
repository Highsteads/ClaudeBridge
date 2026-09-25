#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_prompts.py
# Description: The MCP prompts: listed with the required shape, arguments filled in.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v211_tools.py (v2.11.0)


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
    plugin = get_prompt("recover_wedged_plugin", {"plugin": "Dashboards"})
    assert "Dashboards" in plugin["messages"][0]["content"]["text"]


def test_a_missing_required_argument_is_refused_by_name():
    """It used to be filled with a "<plugin>" placeholder, which sent Claude
    looking for a plugin literally called that."""
    import pytest
    from mcp_server.prompts import MissingPromptArguments, get_prompt
    for args in ({}, {"plugin": ""}, {"plugin": None}):
        with pytest.raises(MissingPromptArguments) as exc:
            get_prompt("recover_wedged_plugin", args)
        assert exc.value.missing == ["plugin"]


def test_prompts_get_answers_a_missing_argument_with_32602(tmp_path):
    import json
    from test_protocol_handle_request import _make_handler
    h = _make_handler(tmp_path)
    resp = h.handle_request("POST", {"accept": "application/json"}, json.dumps(
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/get",
         "params": {"name": "zwave_tune_sensor", "arguments": {}}}))
    err = json.loads(resp["content"])
    assert err["id"] == 3
    assert err["error"]["code"] == -32602
    assert "device" in err["error"]["message"]


def test_prompt_get_unknown_returns_none():
    from mcp_server.prompts import get_prompt
    assert get_prompt("does_not_exist", {}) is None
