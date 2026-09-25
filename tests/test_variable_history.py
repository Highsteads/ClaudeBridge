#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_variable_history.py
# Description: variable_history (3.5.0): one variable's SQL Logger history,
#              read like device_history (primary-key range, never a ts scan),
#              with the value in force when the window opened, and a summary
#              of how long each value held. The logger writes only on change,
#              so without value_before "how long was it true today" cannot be
#              answered from the rows alone.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import call_tool

VID = 760364002


def _utc(dt):
    return dt.isoformat(sep=" ", timespec="seconds")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    path = str(tmp_path / "indigo_history.sqlite")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE variable_history_{VID} (id INTEGER PRIMARY KEY, "
                 f"ts TIMESTAMP, value TEXT)")
    conn.executemany(f"INSERT INTO variable_history_{VID} VALUES (?,?,?)", [
        (1, _utc(now - timedelta(hours=30)), "false"),   # before a 24 h window
        (2, _utc(now - timedelta(hours=22)), "true"),
        (3, _utc(now - timedelta(hours=19)), "false"),
        (4, _utc(now - timedelta(hours=2)), "true"),
    ])
    conn.execute("CREATE TABLE variable_history_5 (id INTEGER PRIMARY KEY, ts TIMESTAMP, "
                 "value TEXT)")
    conn.executemany("INSERT INTO variable_history_5 VALUES (?,?,?)", [
        (1, _utc(now - timedelta(hours=48)), "20"),
        (2, _utc(now - timedelta(hours=12)), "22"),
    ])
    conn.execute("CREATE TABLE variable_history_6 (id INTEGER PRIMARY KEY, ts TIMESTAMP, "
                 "value TEXT)")
    conn.executemany("INSERT INTO variable_history_6 VALUES (?,?,?)", [
        (1, _utc(now - timedelta(hours=6)), "on"),        # nothing before the window
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr(mod, "_sql_logger_db", lambda: path)

    statements = []
    real_connect = sqlite3.connect

    def tracing(*a, **k):
        c = real_connect(*a, **k)
        c.set_trace_callback(statements.append)
        return c
    monkeypatch.setattr(mod.sqlite3, "connect", tracing)
    h = mod.PluginDevToolsHandler(data_provider=None)
    return SimpleNamespace(h=h, mod=mod, path=path, statements=statements, now=now)


def _local(mod, dt):
    return mod._utc_text_to_local(_utc(dt))


def test_rows_are_newest_first_in_local_time_with_the_value_before(db):
    out = db.h.variable_history(VID, hours=24)
    assert out["success"] is True and out["row_count"] == 3 and out["truncated"] is False
    assert [r["value"] for r in out["rows"]] == ["true", "false", "true"]
    assert out["rows"][0]["ts"] == _local(db.mod, db.now - timedelta(hours=2))
    assert out["value_before"] == {"ts": _local(db.mod, db.now - timedelta(hours=30)),
                                   "value": "false"}
    assert out["ts_timezone"] == "local"


def test_limit_keeps_the_newest_and_says_so(db):
    out = db.h.variable_history(VID, hours=24, limit=2)
    assert [r["value"] for r in out["rows"]] == ["true", "false"]
    assert out["truncated"] is True and "NEWEST 2" in out["note"]


def test_a_quiet_window_says_what_the_value_has_been(db):
    out = db.h.variable_history(VID, hours=1)
    assert out["rows"] == [] and out["value_before"]["value"] == "true"
    assert "No change in the last 1 hours" in out["note"] and "'true'" in out["note"]


def test_a_variable_the_logger_never_saw_is_an_error(db):
    out = db.h.variable_history(123, hours=24)
    assert out["success"] is False and "variable_history_123" in out["error"]


def test_summary_says_how_long_each_value_held(db):
    out = db.h.variable_history(VID, hours=24, summary=True)
    vals = {v["value"]: v for v in out["values"]}
    # false 24h->22h, true 22h->19h, false 19h->2h, true 2h->now
    assert out["changes"] == 3 and out["distinct_values"] == 2
    assert abs(vals["true"]["seconds_held"] - 5 * 3600) <= 5
    assert abs(vals["false"]["seconds_held"] - 19 * 3600) <= 5
    assert vals["true"]["times_set"] == 2 and vals["false"]["times_set"] == 1
    assert abs(vals["false"]["share_of_window"] - 19 / 24) < 0.01
    assert out["values"][0]["value"] == "false", "longest held first"
    assert "numeric" not in out and "unknown_seconds" not in out


def test_summary_of_a_number_gives_a_time_weighted_mean(db):
    out = db.h.variable_history(5, hours=24, summary=True)
    # 20 for the first 12 h of the window, 22 for the last 12
    assert out["numeric"]["min"] == 20 and out["numeric"]["max"] == 22
    assert abs(out["numeric"]["time_weighted_mean"] - 21.0) < 0.01


def test_summary_says_when_the_start_of_the_window_is_unknown(db):
    out = db.h.variable_history(6, hours=24, summary=True)
    assert abs(out["unknown_seconds"] - 18 * 3600) <= 5
    assert "unknown" in out["unknown_note"]


def test_every_read_uses_the_primary_key_never_a_full_scan(db):
    db.h.variable_history(VID, hours=24)
    db.h.variable_history(VID, hours=24, summary=True)
    conn = sqlite3.connect(db.path)
    try:
        table = f"variable_history_{VID}"
        checked = 0
        for stmt in db.statements:
            if not stmt.lstrip().upper().startswith("SELECT") or table not in stmt:
                continue
            plan = [row[-1] for row in conn.execute("EXPLAIN QUERY PLAN " + stmt)]
            assert not any(step.strip() == f"SCAN {table}" for step in plan), (stmt, plan)
            checked += 1
        assert checked >= 4
    finally:
        conn.close()


def test_hours_is_capped_at_a_month(db):
    out = db.h.variable_history(VID, hours=24 * 400)
    assert out["hours"] == 24 * 31 and out["hours_capped"] is True and "hours_note" in out


# ── the tool: finding the variable ──────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.calls = []

    def variable_history(self, vid, **kw):
        self.calls.append((vid, kw))
        return {"success": True}


def _ctx(names):
    rows = [{"id": i, "name": n} for i, n in names]
    return SimpleNamespace(data_provider=SimpleNamespace(get_all_variables=lambda: rows),
                           plugin_dev_tools_handler=_Recorder())


def test_found_by_exact_name_then_ignoring_case():
    ctx = _ctx([(1, "heating_on"), (2, "Heating_On_Legacy")])
    call_tool(ctx, "variable_history", variable="heating_on")
    call_tool(ctx, "variable_history", variable="HEATING_ON_LEGACY", summary=True)
    assert ctx.plugin_dev_tools_handler.calls == [
        (1, {"hours": 24, "limit": 500, "summary": False, "name": "heating_on"}),
        (2, {"hours": 24, "limit": 500, "summary": True, "name": "Heating_On_Legacy"}),
    ]


def test_an_id_is_used_even_for_a_deleted_variable():
    ctx = _ctx([(1, "heating_on")])
    call_tool(ctx, "variable_history", variable=437369347)
    assert ctx.plugin_dev_tools_handler.calls[0][0] == 437369347
    assert ctx.plugin_dev_tools_handler.calls[0][1]["name"] is None


@pytest.mark.parametrize("names,asked,words", [
    ([(1, "a")], "missing", "No variable called"),
    ([(1, "Dup"), (2, "dup")], "DUP", "2 variables are called"),
    ([(1, "a")], "  ", "empty"),
])
def test_what_cannot_be_found_is_refused_by_name(names, asked, words):
    ctx = _ctx(names)
    out = call_tool(ctx, "variable_history", variable=asked)
    assert out["success"] is False and words in out["error"]
    assert ctx.plugin_dev_tools_handler.calls == []
