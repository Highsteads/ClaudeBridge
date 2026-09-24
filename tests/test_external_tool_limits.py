#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_external_tool_limits.py
# Description: Plugin-provided tools cannot hold Indigo's web server thread
#              past exec_lock.MAX_WAIT_SECONDS, a manifest whose inputSchema
#              properties or required list has the wrong shape is refused at
#              load, and two providers whose names meet after prefixing
#              cannot overwrite each other.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import logging
import threading
import time
import types

import pytest

from mcp_server.common import exec_lock
from mcp_server.external_tools import ExternalToolManager, ManifestError, parse_manifest
from mcp_server.external_tools.dispatch import invoke_provider_tool

_LOG = logging.getLogger("test-external-tool-limits")
PID = "com.example.widgets"


class _SlowPlugin:
    def __init__(self, release, reply):
        self.release, self.reply = release, reply

    def isRunning(self):
        return True

    def executeAction(self, action_id, deviceId=0, props=None, waitUntilDone=True):
        self.release.wait(5)
        return self.reply


def test_the_default_cap_is_the_exec_lock_maximum():
    import inspect
    from mcp_server.external_tools import dispatch
    assert dispatch.MAX_WAIT_SECONDS == exec_lock.MAX_WAIT_SECONDS == 20
    assert inspect.signature(invoke_provider_tool).parameters["max_wait_seconds"].default is None


def test_a_call_past_the_cap_reports_running_and_logs_its_late_outcome(caplog):
    release = threading.Event()
    plugin = _SlowPlugin(release, json.dumps({"status": "ok", "result": 1}))
    started = time.monotonic()
    with caplog.at_level(logging.INFO, logger=_LOG.name):
        out = invoke_provider_tool(PID, "mcp_tool_invoke", "slow", "Widgets", {}, 120,
                                   logger=_LOG, get_plugin=lambda pid: plugin,
                                   max_wait_seconds=0.2)
        waited = time.monotonic() - started
        assert waited < 2, "the request thread was held past the cap"
        assert out["status"] == "running" and "success" not in out and "error" not in out
        assert "still working" in out["note"]
        release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
                "succeeded" in r.getMessage() for r in caplog.records):
            time.sleep(0.02)
    assert any("after its reply had gone back, and succeeded" in r.getMessage()
               for r in caplog.records)


def test_a_declared_deadline_under_the_cap_still_times_out():
    release = threading.Event()
    plugin = _SlowPlugin(release, json.dumps({"status": "ok"}))
    try:
        out = invoke_provider_tool(PID, "a", "slow", "Widgets", {}, 0.2, logger=_LOG,
                                   get_plugin=lambda pid: plugin, max_wait_seconds=5)
    finally:
        release.set()
    assert out["success"] is False and out["timeout"] is True


# ── manifest shape ───────────────────────────────────────────────────────────

def _manifest(schema, pid=PID, name="get_status", prefix=None):
    m = {"manifest_version": 1, "provider": {"plugin_id": pid, "display_name": "W"},
         "tools": [{"name": name, "description": "d", "inputSchema": schema}]}
    if prefix:
        m["tool_prefix"] = prefix
    return json.dumps(m)


@pytest.mark.parametrize("schema,needle", [
    ({"type": "object", "properties": "mode"}, "properties"),
    ({"type": "object", "properties": ["mode"]}, "properties"),
    ({"type": "object", "properties": {"mode": "string"}}, "properties"),
    ({"type": "object", "required": "mode"}, "required"),
    ({"type": "object", "required": [1]}, "required"),
])
def test_a_misshapen_input_schema_is_refused(schema, needle):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(_manifest(schema), PID)
    assert needle in str(exc.value)


def test_a_well_formed_schema_still_loads():
    m = parse_manifest(_manifest({"type": "object", "properties": {"m": {"type": "string"}},
                                  "required": ["m"]}), PID)
    assert m.tools[0].name == "get_status"


# ── exposed-name collisions across providers ─────────────────────────────────

def _bundle(tmp_path, pid, text, folder):
    res = tmp_path / folder / "Contents" / "Resources"
    res.mkdir(parents=True)
    (res / "mcp-manifest.json").write_text(text, encoding="utf-8")
    return types.SimpleNamespace(pluginId=pid, pluginFolderPath=str(tmp_path / folder))


def test_the_second_provider_to_expose_a_name_is_skipped(tmp_path, caplog):
    schema = {"type": "object", "properties": {}}
    a = _bundle(tmp_path, "com.a.one", _manifest(schema, "com.a.one", "b_c", prefix="a"), "one.indigoPlugin")
    b = _bundle(tmp_path, "com.b.two", _manifest(schema, "com.b.two", "c", prefix="a_b"), "two.indigoPlugin")
    mgr = ExternalToolManager(logger=_LOG, self_plugin_id="com.clives.indigoplugin.claudebridge")
    with caplog.at_level(logging.ERROR):
        entries = mgr.rescan(set(), plugin_list=[a, b])
    assert list(entries) == ["a_b_c"]
    assert entries["a_b_c"]["external_provider"] == "com.a.one"
    assert mgr.skipped_names == ["a_b_c"]
    assert any("same name as one from com.a.one" in r.getMessage() for r in caplog.records)
