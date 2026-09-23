#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_energy_tools.py
# Description: energy_daily_summary / energy_compare read SigenEnergyManager's
#              daily_history.json. Until 2.27.3 they parsed "[Daily]" log lines
#              the plugin never writes, so every total came back null.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import logging
from datetime import date, timedelta

import pytest

from mcp_server.tools.energy_tools import energy_tools_handler as eth


def _rec(day, pv, imp, exp, home, partial=False):
    # Shape copied from a real record (field names only; values invented).
    return {"date": day.isoformat(), "month": day.strftime("%Y-%m"),
            "pv_kwh": pv, "grid_import_kwh": imp, "grid_export_kwh": exp,
            "home_kwh": home, "peak_soc": 100.0, "min_soc": 40.0,
            "energy_partial": partial, "tariff": "flux", "vpp_event": False}


@pytest.fixture
def history(tmp_path, monkeypatch):
    today = date.today()
    recs = [_rec(today - timedelta(days=i), 30.0 + i, 2.0, 10.0, 20.0)
            for i in range(1, 15)]
    recs[0]["energy_partial"] = True
    path = tmp_path / "daily_history.json"
    path.write_text(json.dumps(recs), encoding="utf-8")
    monkeypatch.setattr(eth, "_daily_history_path", lambda: str(path))
    monkeypatch.setattr(eth, "_today_so_far", lambda: {"pv_kwh": 5.0})
    return recs


def _handler():
    h = object.__new__(eth.EnergyToolsHandler)
    h.logger = logging.getLogger("t")
    h.tool_name = "energy_tools"
    return h


def test_summary_returns_real_totals(history):
    out = _handler().energy_daily_summary(days=7)
    assert out["success"] is True
    assert out["days_found"] == 7
    totals = out["period_totals"]
    assert totals["import_kwh"] == 14.0
    assert totals["home_kwh"] == 140.0
    assert totals["self_sufficiency_pct"] == 90.0
    assert totals["partial_days"] == 1
    assert out["daily"][-1]["date"] == (date.today() - timedelta(days=1)).isoformat()
    assert out["today_so_far"] == {"pv_kwh": 5.0}


def test_missing_days_are_named_not_zero_filled(history, tmp_path, monkeypatch):
    gappy = [r for r in history if r["date"] != (date.today() - timedelta(days=2)).isoformat()]
    path = tmp_path / "gappy.json"
    path.write_text(json.dumps(gappy), encoding="utf-8")
    monkeypatch.setattr(eth, "_daily_history_path", lambda: str(path))
    out = _handler().energy_daily_summary(days=3)
    assert out["days_found"] == 2
    assert out["missing_dates"] == [(date.today() - timedelta(days=2)).isoformat()]


def test_compare_this_week_against_last(history):
    out = _handler().energy_compare(7, 7, 7)
    a, b = out["period_a"], out["period_b"]
    assert a["to"] == (date.today() - timedelta(days=1)).isoformat()
    assert b["to"] == (date.today() - timedelta(days=8)).isoformat()
    assert a["days_found"] == 7 and b["days_found"] == 7
    # pv is 30+i per day, so last week's days carry 7 more each
    assert out["comparison"]["pv_kwh"]["delta"] == -49.0


def test_a_missing_field_is_never_counted_as_zero():
    rows = [{"date": "2026-01-01", "pv_kwh": None, "import_kwh": 1.0, "home_kwh": None}]
    totals = eth.summarise(rows)
    assert totals["pv_kwh"] is None
    assert totals["self_sufficiency_pct"] is None


def test_no_history_file_is_an_error(monkeypatch):
    monkeypatch.setattr(eth, "_daily_history_path", lambda: None)
    out = _handler().energy_daily_summary()
    assert out["success"] is False and "daily_history.json" in out["error"]
