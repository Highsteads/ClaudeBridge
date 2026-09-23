#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_audit_api_coverage.py
# Description: audit_api_coverage reports methods added to and removed from the IOM.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v290_tools.py (v2.9.0)


import sys
import types
from unittest.mock import MagicMock

from mcp_server.tools.system_tools.system_tools_handler import SystemToolsHandler

from test_dispatch import _LOGGER


# ── audit_api_coverage drift detection ────────────────────────────────────────

def test_audit_api_coverage_detects_additions_and_removals(monkeypatch):
    ind = sys.modules["indigo"]

    def ns(**fns):
        return types.SimpleNamespace(**fns)

    f = lambda: None  # noqa: E731 — any callable will do
    # A tiny live surface: one genuinely-new method + one baseline method,
    # with everything else absent → most of the baseline reads as "removed".
    monkeypatch.setattr(ind, "device", ns(turnOn=f, fakeNewMethod=f), raising=False)
    for missing in ["dimmer", "relay", "sensor", "thermostat", "sprinkler",
                    "speedcontrol", "iodevice", "variable", "trigger", "schedule",
                    "actionGroup", "controlPage", "zwave", "insteon",
                    "devices", "variables", "triggers", "schedules",
                    "actionGroups", "controlPages"]:
        monkeypatch.delattr(ind, missing, raising=False)
    monkeypatch.setattr(ind, "server", ns(version="2025.2.0"), raising=False)

    h = SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)
    result = h.audit_api_coverage()
    assert result["success"] is True
    assert "device.fakeNewMethod" in result["new_since_baseline"]
    assert "device.turnOn" not in result["removed_since_baseline"]
    assert "device.beep" in result["removed_since_baseline"]   # absent from fake live
