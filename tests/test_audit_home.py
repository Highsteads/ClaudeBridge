#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_audit_home.py
# Description: audit_home's empty-variable figure counts blank, "none" and
#              "null" values only - never a boolean flag that reads "false".
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# From the 09-Aug-2026 review (test_v2202_low_fixes.py), where it was an AST
# check on the text of audit_home. It now runs audit_home over fake variables.

import logging
from types import SimpleNamespace

from mcp_server.tools.audit import audit_handler as ah


def _audit(monkeypatch, variables):
    fake = SimpleNamespace(
        variables={v.id: v for v in variables},
        triggers={}, schedules={}, devices={}, actionGroups={},
    )
    monkeypatch.setattr(ah, "indigo", fake)
    monkeypatch.setattr(ah, "_iter_script_files", lambda dirs: iter(()))
    monkeypatch.setattr(ah, "_scripts_dirs", lambda: [])
    handler = ah.AuditHandler(data_provider=None, logger=logging.getLogger("t"))
    for collector in ("_collect_device_errors", "_collect_low_battery", "_collect_stale_devices"):
        monkeypatch.setattr(handler, collector, lambda *a, **k: [])
    return handler.audit_home()


def _var(vid, value, read_only=False):
    return SimpleNamespace(id=vid, name=f"var_{vid}", value=value, readOnly=read_only)


def test_false_is_not_an_empty_variable(monkeypatch):
    """Every boolean flag sits at "false" half the time, so counting those made
    the empty-variable total track the state of the house, not anything wrong."""
    result = _audit(monkeypatch, [_var(1, "false"), _var(2, "False"), _var(3, "0")])
    assert result["success"] is True
    assert result["summary"]["empty_variables"] == 0


def test_blank_none_and_null_are_empty(monkeypatch):
    result = _audit(monkeypatch, [_var(1, ""), _var(2, "None"), _var(3, " null "),
                                  _var(4, "on"), _var(5, "", read_only=True)])
    assert result["summary"]["empty_variables"] == 3
    assert {v["id"] for v in result["empty_variables"]} == {1, 2, 3}
