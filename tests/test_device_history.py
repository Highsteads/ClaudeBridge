#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_history.py
# Description: device_history: the column allowlist, the PK-range window and
#              query_only (v2.13.0, moved from test_v2130_borrows.py); and with
#              no `columns`, the columns that carry a value in the rows it
#              RETURNS, from one bounded read — not a full-window "IS NOT NULL"
#              scan per column. Column names are quoted, so one that is an SQL
#              keyword cannot break the query.
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


# ── device_history: allowlist, PK-range, query_only ──────────────────────────

@pytest.fixture()
def history_handler(tmp_path, monkeypatch):
    """PluginDevToolsHandler wired at a synthetic SQL Logger database."""
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    db_path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE device_history_123 ("
        "id INTEGER PRIMARY KEY, ts TIMESTAMP, batterysoc REAL, pvpower REAL)")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(200):
        ts = (now - timedelta(minutes=200 - i)).isoformat(sep=" ")
        rows.append((i + 1, ts, 50.0 + i * 0.1, None if i % 2 else i * 10.0))
    conn.executemany("INSERT INTO device_history_123 VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()

    monkeypatch.setattr(mod, "_sql_logger_db", lambda: db_path)
    handler = mod.PluginDevToolsHandler(data_provider=None)
    return handler


def test_history_unknown_column_is_hard_error(history_handler):
    result = history_handler.device_history(123, columns=["batterySoc"])
    assert result["success"] is False
    assert "batterySoc" in result["error"]
    assert "batterysoc" in result["error"]  # valid set named, lowercase


def test_history_valid_columns_and_window(history_handler):
    result = history_handler.device_history(123, hours=1,
                                            columns=["batterysoc"])
    assert result["success"] is True
    assert result["columns"][0] == "ts"
    # 1-hour window over minute-spaced rows: about 60, never all 200.
    assert 50 <= result["row_count"] <= 65
    assert all(row["batterysoc"] is not None for row in result["rows"])


def test_history_probe_branch_uses_window(history_handler):
    result = history_handler.device_history(123, hours=1)
    assert result["success"] is True
    assert "batterysoc" in result["columns"]
    assert "pvpower" in result["columns"]


def test_history_empty_window(history_handler, monkeypatch):
    # All rows are older than a tiny window anchored far in the future is
    # impossible here, so instead: request rows newer than now+1h via a
    # 0-hour... hours is clamped to >=1; simulate instead a device whose
    # rows all predate the window by shrinking to 1 hour on an old-only table.
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod
    db_path = mod._sql_logger_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE device_history_456 ("
        "id INTEGER PRIMARY KEY, ts TIMESTAMP, watts REAL)")
    old = (datetime.now(timezone.utc).replace(tzinfo=None)
           - timedelta(days=30)).isoformat(sep=" ")
    conn.execute("INSERT INTO device_history_456 VALUES (1, ?, 42.0)", (old,))
    conn.commit()
    conn.close()
    result = history_handler.device_history(456, hours=1, columns=["watts"])
    assert result["success"] is True
    assert result["row_count"] == 0


def test_rowid_floor_binary_search(history_handler):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod
    db_path = mod._sql_logger_db()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = (now - timedelta(minutes=30)).isoformat(sep=" ")
    floor_id = history_handler._rowid_floor_for_ts(cur, "device_history_123", cutoff)
    # Row ids are minute-spaced ending ~now: the floor should sit ~30 rows
    # from the top (id 200), i.e. around id 171.
    assert 168 <= floor_id <= 174
    cur.execute("SELECT MIN(ts) FROM device_history_123 WHERE id >= ?", (floor_id,))
    assert cur.fetchone()[0] >= cutoff
    conn.close()
