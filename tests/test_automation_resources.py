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


def test_automation_resources_reuse_the_tool_handlers(resources):
    """A resource rendering automations its own way is a second contract."""
    import inspect
    for uri, attr in (("indigo://triggers/{trigger_id}", "automation_detail_handler"),
                      ("indigo://schedules/{schedule_id}", "automation_detail_handler"),
                      ("indigo://triggers", "schedule_control_handler"),
                      ("indigo://schedules", "schedule_control_handler")):
        source = inspect.getsource(resources[uri]["function"])
        assert attr in source, f"{uri} does not go through self.{attr}"
