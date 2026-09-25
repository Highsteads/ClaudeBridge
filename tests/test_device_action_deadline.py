#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_action_deadline.py
# Description: execute_device_action runs the plugin's executeAction on a
#              thread with a deadline, so a slow or hung action cannot hold
#              Indigo's web server, and refuses Claude Bridge's own plugin id,
#              which would re-enter the plugin serving the request.
# Author:      CliveS
# Date:        25-09-2026
# Version:     1.0

import logging
import threading
import time
from types import SimpleNamespace

import pytest

from mcp_server.tools.plugin_control import plugin_control_handler as pch
from mcp_server.tools.plugin_control.plugin_control_handler import PluginControlHandler

OWN_ID = "com.clives.indigoplugin.claudebridge"


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class FakePlugin:
    def __init__(self, folder, action):
        self.pluginFolderPath = str(folder)   # no Actions.xml: dispatched unguarded
        self._action = action
        self.calls = []

    def isRunning(self):
        return True

    def isEnabled(self):
        return True

    def executeAction(self, action_type_id, **kwargs):
        self.calls.append((action_type_id, kwargs))
        return self._action()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    log = logging.getLogger(f"test-device-action-{tmp_path.name}")
    log.setLevel(logging.DEBUG)
    rec = _Records()
    log.addHandler(rec)
    handler = PluginControlHandler(data_provider=None, logger=log)
    handler.ACTION_DEADLINE_SECONDS = 0.3
    fetched = []

    def _install(action):
        plugin = FakePlugin(tmp_path, action)

        def _get(pid):
            fetched.append(pid)
            return plugin
        monkeypatch.setattr(pch.indigo.server, "getPlugin", _get, raising=False)
        return plugin
    return SimpleNamespace(handler=handler, install=_install, fetched=fetched, rec=rec)


def test_a_quick_action_returns_its_result(rig):
    plugin = rig.install(lambda: {"ok": 1})
    out = rig.handler.execute_device_action("pulse", plugin_id="com.acme.valves")
    assert out["success"] is True
    assert out["plugin_returned"] == {"ok": 1}
    assert plugin.calls == [("pulse", {"waitUntilDone": True})]


def test_a_hung_action_is_abandoned_at_the_deadline(rig):
    release = threading.Event()
    rig.install(lambda: release.wait(5) and "late")
    started = time.monotonic()
    out = rig.handler.execute_device_action("open_valve", plugin_id="com.acme.valves")
    took = time.monotonic() - started
    try:
        assert took < 2.0, "the request thread was held past the deadline"
        assert out["success"] is False
        assert out["timed_out"] is True and out["still_running"] is True
        assert "may still be running" in out["error"]
    finally:
        release.set()
    # The late outcome is logged when it lands, not lost.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not any("after its reply" in m
                                                  for m in rig.rec.lines):
        time.sleep(0.02)
    assert any("after its reply" in m for m in rig.rec.lines)


def test_an_action_that_raises_is_a_failure(rig):
    def _boom():
        raise RuntimeError("valve controller offline")
    rig.install(_boom)
    out = rig.handler.execute_device_action("open_valve", plugin_id="com.acme.valves")
    assert out["success"] is False
    assert "valve controller offline" in out["error"]


def test_claude_bridge_itself_is_refused_by_plugin_id(rig):
    plugin = rig.install(lambda: None)
    out = rig.handler.execute_device_action("anything", plugin_id=OWN_ID)
    assert out["success"] is False
    assert "Claude Bridge" in out["error"]
    assert plugin.calls == [] and rig.fetched == []


def test_claude_bridge_itself_is_refused_through_its_device(rig, monkeypatch):
    plugin = rig.install(lambda: None)
    own_device = SimpleNamespace(id=42, name="Claude Bridge", pluginId=OWN_ID)
    monkeypatch.setattr(rig.handler, "_resolve_device", lambda d: (own_device, ""))
    out = rig.handler.execute_device_action("anything", device_id=42)
    assert out["success"] is False and plugin.calls == []
