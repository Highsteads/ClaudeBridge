#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_coerce.py
# Description: Tool-argument coercion. From 2.27.3 it happens on the server,
#              against each tool's declared schema: a string property gets
#              exactly what was sent; numeric/array properties still accept
#              stringified values. The proxy must pass arguments untouched.
# Author:      CliveS & Claude Opus 4.8; Claude Opus 5.5 (2.0)
# Date:        23-09-2026
# Version:     2.0

import importlib.util
import json
import os

import pytest

from conftest import SERVER_PLUGIN
from mcp_server.common.arg_coercion import allowed_types, coerce_to_schema, coerce_value

_PROXY_PATH = os.path.join(SERVER_PLUGIN, "indigo_mcp_proxy.py")

STR    = {"type": "string"}
INT    = {"type": "integer"}
NUM    = {"type": "number"}
ARR    = {"type": "array", "items": {"type": "integer"}}
BOOL   = {"type": "boolean"}
ID     = {"anyOf": [{"type": "number"}, {"type": "string"}]}
ANY    = {}


# ── A string property is never altered (the bug this replaced) ───────────────

@pytest.mark.parametrize("val", ['{"mode":"away"}', "21.50", "1.10", "1e3", "42",
                                 "[1, 2]", "0123", "true", "  spaced  "])
def test_string_property_receives_exactly_what_was_sent(val):
    assert coerce_value(val, allowed_types(STR)) == val


def test_variable_update_value_keeps_its_json_text():
    props = {"variable_id": ID, "value": STR}
    out = coerce_to_schema({"variable_id": "123", "value": '{"mode":"away"}'}, props)
    assert out == {"variable_id": 123, "value": '{"mode":"away"}'}


def test_string_enum_is_treated_as_a_string():
    assert coerce_value("1", allowed_types({"enum": ["1", "2"]})) == "1"


# ── Numeric and structured properties still accept strings ───────────────────

def test_plain_integer_coerced():
    assert coerce_value("12345678", allowed_types(INT)) == 12345678


def test_negative_integer_coerced():
    assert coerce_value("-5", allowed_types(NUM)) == -5


def test_float_coerced_for_number():
    assert coerce_value("21.5", allowed_types(NUM)) == 21.5


def test_float_not_forced_into_an_integer_property():
    assert coerce_value("21.5", allowed_types(INT)) == "21.5"


def test_json_array_coerced():
    assert coerce_value("[1, 2, 3]", allowed_types(ARR)) == [1, 2, 3]


def test_json_object_not_forced_into_an_array_property():
    assert coerce_value('{"a": 1}', allowed_types(ARR)) == '{"a": 1}'


def test_id_or_name_property_turns_digits_into_an_id():
    assert coerce_value("1455635812", allowed_types(ID)) == 1455635812
    assert coerce_value("Kitchen Lamp", allowed_types(ID)) == "Kitchen Lamp"


@pytest.mark.parametrize("val, expected", [("true", True), ("False", False)])
def test_boolean_property_accepts_true_false_text(val, expected):
    assert coerce_value(val, allowed_types(BOOL)) is expected


# ── Undeclared properties keep the old conservative rules ────────────────────

def test_undeclared_plain_integer_coerced():
    assert coerce_value("12345678", allowed_types(ANY)) == 12345678


@pytest.mark.parametrize("val", ["true", "false", "null", "0123", "+5", "--5",
                                 "192.168.1.71", "Kitchen Lamp"])
def test_undeclared_words_and_codes_left_as_strings(val):
    assert coerce_value(val, allowed_types(ANY)) == val


def test_non_strings_pass_through():
    assert coerce_to_schema({"a": 5, "b": [1], "c": None}, {"a": STR, "b": STR, "c": STR}) \
        == {"a": 5, "b": [1], "c": None}


# ── The proxy no longer touches arguments ────────────────────────────────────

def _load_proxy():
    spec = importlib.util.spec_from_file_location("cb_proxy_under_test", _PROXY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_proxy_sends_tool_arguments_unchanged(monkeypatch):
    proxy = _load_proxy()
    assert not hasattr(proxy, "_coerce_args")
    sent = {}

    def _fake_attempt(body, headers, method, is_notification):
        sent["body"] = json.loads(body)
        return [], []

    monkeypatch.setattr(proxy, "_attempt", _fake_attempt)
    monkeypatch.setattr(proxy, "_emit", lambda *a, **k: None)
    args = {"variable_id": "123", "value": "21.50", "code": "42"}
    proxy.post_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "variable_update", "arguments": dict(args)}})
    assert sent["body"]["params"]["arguments"] == args


# ── Through the dispatch chokepoint ──────────────────────────────────────────

def test_dispatch_coerces_against_the_tool_schema(tmp_path):
    import logging
    import threading
    from collections import deque

    from mcp_server.common.tool_cache import ToolCache
    from mcp_server.mcp_handler import MCPHandler
    from mcp_server.security import RateLimiter, ScopeManager

    got = {}

    def _fn(**kw):
        got.update(kw)
        return '{"success": true}'

    log = logging.getLogger("t")
    h = object.__new__(MCPHandler)
    h.logger, h._tool_error_count = log, 0
    h.scope_manager = ScopeManager(scopes_file=str(tmp_path / "s.json"), logger=log)
    h.rate_limiter  = RateLimiter(per_minute=120, per_day=5000, admin_multiplier=1.0, logger=log)
    h.tool_cache    = ToolCache(default_ttl=0, logger=log)
    h._emitter_local, h._telemetry_lock = threading.local(), threading.Lock()
    h._tool_call_log = deque(maxlen=10)
    h._tools = {"variable_update": {
        "description": "t", "function": _fn,
        "inputSchema": {"type": "object", "properties": {"variable_id": ID, "value": STR}}}}
    h._handle_tools_call(1, {"name": "variable_update",
                             "arguments": {"variable_id": "77", "value": "21.50"}})
    assert got == {"variable_id": 77, "value": "21.50"}
