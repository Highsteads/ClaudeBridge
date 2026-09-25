#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_health_access.py
# Description: /health names the configured keys and their scopes and lists
#              recent tool calls, so only an admin key gets the full snapshot;
#              any other key gets the basic status and its own rate limits.
#              Either way the rate limits reported are the ones enforced.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

import json
import threading
from types import SimpleNamespace

from conftest import load_plugin_module
from test_dispatch import _make_handler, _tool

SCOPES = {"tokens": {
    "desk-admin-key": {"name": "desk", "scopes": ["read", "write", "admin"]},
    "phone-read-key": {"name": "phone", "scopes": ["read"]},
}}


def _handler(tmp_path, scopes=SCOPES):
    h = _make_handler(tmp_path, scopes_data=scopes,
                      tools={"list_devices": _tool(lambda **kw: "[]")})
    h._sessions_lock = threading.Lock()
    h._sessions = {}
    h._resources = {}
    h.rate_limiter.admin_multiplier = 10.0
    h._handle_tools_call(1, {"name": "list_devices", "arguments": {}},
                         {"authorization": "Bearer desk-admin-key"})
    return h


def test_an_admin_key_gets_the_full_snapshot(tmp_path):
    data = _handler(tmp_path).health_for_caller({"Authorization": "Bearer desk-admin-key"})
    assert data["scopes"]["names"]
    assert data["tool_calls"]["recent"][0]["name"] == "list_devices"


def test_a_read_key_gets_the_basic_status_only(tmp_path):
    data = _handler(tmp_path).health_for_caller({"Authorization": "Bearer phone-read-key"})
    text = json.dumps(data)
    assert data["status"] == "ok"
    for leak in ("desk", "phone", "list_devices"):
        assert leak not in text, leak
    for section in ("scopes", "tool_calls", "rate_limiter", "sessions"):
        assert section not in data, section
    assert data["rate_limit"] == {"counted_per": "access key", "per_minute": 120,
                                  "per_day": 5_000}


def test_the_report_states_the_limits_in_force(tmp_path):
    rl = _handler(tmp_path).get_health_data()["rate_limiter"]
    assert rl["counted_per"] == "access key"
    assert rl["configured"] == {"per_minute": 120, "per_day": 5_000}
    assert rl["effective"]["admin"] == {"per_minute": 1_200, "per_day": 50_000}
    assert rl["every_key_is_admin"] is False
    (entry,) = rl["per_key"].values()
    assert entry["admin"] is True and entry["limit_per_minute"] == 1_200


def test_without_scopes_json_every_key_is_admin_and_says_so(tmp_path):
    h = _make_handler(tmp_path)
    h._sessions_lock = threading.Lock()
    h._sessions = {}
    h._resources = {}
    rl = h.get_health_data()["rate_limiter"]
    assert rl["every_key_is_admin"] is True
    assert "every key is admin" in rl["note"]
    # And with no scopes.json any key is admin, so it still sees everything:
    # nothing changes for an install that never made one.
    assert "scopes" in h.health_for_caller({"Authorization": "Bearer anything"})


def test_the_endpoint_reads_the_callers_key(tmp_path):
    module = load_plugin_module()
    plugin = object.__new__(module.Plugin)
    plugin.mcp_handler = _handler(tmp_path)
    plugin._start_time = 0
    plugin.logger = SimpleNamespace(error=lambda *a, **k: None)
    action = SimpleNamespace(props={"headers": {"Authorization": "Bearer phone-read-key"}})
    reply = plugin.handle_health_endpoint(action)
    assert reply["status"] == 200
    assert "tool_calls" not in json.loads(reply["content"])
