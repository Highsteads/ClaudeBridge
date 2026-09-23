#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_history_columns.py
# Description: device_history with no `columns` picks the columns that carry a
#              value in the rows it RETURNS, from one bounded read — not a
#              full-window "IS NOT NULL" scan per column. Column names are
#              quoted, so one that is an SQL keyword cannot break the query.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def handler(tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    db_path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE device_history_9 (id INTEGER PRIMARY KEY, ts TIMESTAMP, '
                 'watts REAL, oldstate REAL, "order" TEXT, neverset REAL)')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(100):
        ts = (now - timedelta(minutes=100 - i)).isoformat(sep=" ")
        # oldstate only has values in the OLDEST 50 rows
        rows.append((i + 1, ts, float(i), float(i) if i < 50 else None, "x", None))
    conn.executemany("INSERT INTO device_history_9 VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mod, "_sql_logger_db", lambda: db_path)

    statements = []
    real_connect = sqlite3.connect

    def _tracing_connect(*a, **k):
        c = real_connect(*a, **k)
        c.set_trace_callback(statements.append)
        return c

    monkeypatch.setattr(mod.sqlite3, "connect", _tracing_connect)
    h = mod.PluginDevToolsHandler(data_provider=None)
    h.statements = statements
    return h


def test_columns_are_the_ones_non_null_in_the_returned_rows(handler):
    out = handler.device_history(9, hours=3, limit=20)
    assert out["success"] is True and out["row_count"] == 20
    assert "watts" in out["columns"] and "order" in out["columns"]
    # oldstate has values in the window, but none in the newest 20 rows
    assert "oldstate" not in out["columns"]
    assert "neverset" not in out["columns"]
    assert out["columns"][0] == "ts"


def test_no_per_column_null_probe_is_run(handler):
    handler.device_history(9, hours=3, limit=20)
    probes = [s for s in handler.statements if "IS NOT NULL" in s]
    assert probes == []


def test_a_keyword_column_can_be_asked_for_by_name(handler):
    out = handler.device_history(9, hours=3, limit=5, columns=["order"])
    assert out["success"] is True
    assert out["rows"][0]["order"] == "x"
