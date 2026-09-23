#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_search_entity_types.py
# Description: search_entities accepts the plural and alias spellings callers
#              actually use ("devices", "variables", "action_groups") and its
#              schema names the valid values. 18 of 129 calls failed on this in
#              ten weeks (measured 23-09-2026).
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import logging
from unittest.mock import MagicMock

import pytest

from mcp_server.common.indigo_device_types import IndigoEntityType
from mcp_server.mcp_handler import MCPHandler


@pytest.mark.parametrize("given, expected", [
    ("device", "device"), ("devices", "device"), ("Devices ", "device"),
    ("variable", "variable"), ("variables", "variable"), ("vars", "variable"),
    ("action", "action"), ("actions", "action"), ("action_groups", "action"),
    ("actionGroups", "action"),
])
def test_normalise_maps_plurals_and_aliases(given, expected):
    assert IndigoEntityType.normalise(given) == expected


def test_unknown_type_passes_through_for_validation_to_name():
    assert IndigoEntityType.normalise("trigger") == "trigger"
    assert not IndigoEntityType.is_valid_type(IndigoEntityType.normalise("trigger"))


def test_enum_has_no_stray_members():
    # A dict declared inside a str Enum becomes a member; the alias table must
    # live outside it.
    assert IndigoEntityType.get_all_types() == ["device", "variable", "action"]


def _handler():
    h = object.__new__(MCPHandler)
    h.logger = logging.getLogger("test-search-types")
    h.search_handler = MagicMock()
    h.search_handler.search.return_value = {"devices": []}
    return h


def test_plural_entity_types_reach_the_search_as_canonical_values():
    h = _handler()
    out = json.loads(h._tool_search_entities("lamp", entity_types=["devices", "variables"]))
    assert "error" not in out
    args = h.search_handler.search.call_args[0]
    assert args[2] == ["device", "variable"]


def test_a_bare_string_is_accepted_as_one_type():
    h = _handler()
    h._tool_search_entities("lamp", entity_types="devices")
    assert h.search_handler.search.call_args[0][2] == ["device"]


def test_invalid_type_error_lists_the_valid_ones():
    h = _handler()
    out = json.loads(h._tool_search_entities("x", entity_types=["triggers"]))
    assert "triggers" in out["error"]
    for valid in ("device", "variable", "action"):
        assert valid in out["error"]
    h.search_handler.search.assert_not_called()


def test_schema_enumerates_the_valid_entity_types():
    h = object.__new__(MCPHandler)
    h._tools = {}
    h._register_tools()   # needs nothing but an empty registry on self
    items = h._tools["search_entities"]["inputSchema"]["properties"]["entity_types"]["items"]
    assert items["enum"] == IndigoEntityType.get_all_types()
