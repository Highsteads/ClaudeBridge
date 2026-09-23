#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_automation_resources.py
# Description: Triggers and schedules as first-class MCP resources, routed
#              through the same handlers as their tools (v2.24.0).
# Author:      CliveS & Claude Opus 5
# Date:        29-08-2026
# Version:     1.0

import pytest

from mcp_server.mcp_handler import MCPHandler

EXPECTED = [
    "indigo://triggers",
    "indigo://triggers/{trigger_id}",
    "indigo://schedules",
    "indigo://schedules/{schedule_id}",
]


@pytest.fixture()
def resources():
    """_register_resources only builds a URI table — no data provider needed."""
    h = object.__new__(MCPHandler)
    h._resources = {}
    h._register_resources()
    return h._resources


@pytest.mark.parametrize("uri", EXPECTED)
def test_resource_is_registered(resources, uri):
    assert uri in resources
    assert callable(resources[uri]["function"])
    assert resources[uri].get("description")


def test_collection_and_item_uris_do_not_shadow_each_other(resources):
    """The reader prefix-matches on everything before the '{'.

    'indigo://triggers' must stay an exact match and 'indigo://triggers/7' must
    reach the item handler — a collection URI ending in '/' would swallow both.
    """
    for uri in EXPECTED:
        if "{" in uri:
            base = uri.split("{")[0]
            assert base.endswith("/")
            assert base.rstrip("/") in resources, "the collection URI must also exist"


def test_item_prefixes_are_unambiguous(resources):
    """No parameterised base may prefix another, or the wrong one wins."""
    bases = [u.split("{")[0] for u in resources if "{" in u]
    for a in bases:
        for b in bases:
            if a != b:
                assert not a.startswith(b), f"{a} is shadowed by {b}"


def test_automation_resources_reuse_the_tool_handlers():
    """A resource rendering automations its own way is a second contract.

    This read each resource function's source for the handler's name; it now
    calls each one against recording handlers and checks which was used.
    """
    import json
    from unittest.mock import MagicMock

    h = object.__new__(MCPHandler)
    h._resources = {}
    h._register_resources()
    h.logger = MagicMock()
    h.automation_detail_handler = MagicMock()
    h.automation_detail_handler.get_details.return_value = {"via": "automation_detail"}
    h.schedule_control_handler = MagicMock()
    h.schedule_control_handler.list_triggers.return_value = {"via": "list_triggers"}
    h.schedule_control_handler.list_schedules.return_value = {"via": "list_schedules"}

    fn = {uri: h._resources[uri]["function"] for uri in EXPECTED}
    assert json.loads(fn["indigo://triggers"]()) == {"via": "list_triggers"}
    assert json.loads(fn["indigo://schedules"]()) == {"via": "list_schedules"}
    assert json.loads(fn["indigo://triggers/{trigger_id}"]("7")) == {"via": "automation_detail"}
    h.automation_detail_handler.get_details.assert_called_with("trigger", 7, include_scripts=True)
    assert json.loads(fn["indigo://schedules/{schedule_id}"]("9")) == {"via": "automation_detail"}
    h.automation_detail_handler.get_details.assert_called_with("schedule", 9, include_scripts=True)
