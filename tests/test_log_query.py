#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_log_query.py
# Description: query_event_log's file-scan path: the first second of a window
#              is kept, the reply is capped even when line_count is null, a
#              whole-number float line_count is accepted, and multi-line
#              entries stay together. (Third most-called tool; had no tests.)
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import logging
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.log_query import log_query_handler as lq

DAY = "2026-09-20"


@pytest.fixture
def handler(tmp_path, monkeypatch):
    lines = [
        f"{DAY} 07:44:59.900\tApplication\tbefore the window",
        f"{DAY} 07:45:00.312\tApplication\tfirst second of the window",
        f"{DAY} 07:45:01.000\tPlugin\tTraceback follows",
        "  File \"x.py\", line 1",
        "KeyError: 'k'",
        f"{DAY} 07:52:00.000\tApplication\tat the end boundary",
    ]
    (tmp_path / f"{DAY} Events.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(lq, "_LOG_ROOT", str(tmp_path))
    h = lq.LogQueryHandler(MagicMock(), logger=logging.getLogger("t"))
    return h


def test_the_first_second_of_the_window_is_kept(handler):
    out = handler.query(after=f"{DAY}T07:45:00", before=f"{DAY}T07:52:00")
    msgs = [e["Message"] for e in out["entries"]]
    assert msgs[0] == "first second of the window"
    assert "before the window" not in msgs
    assert "at the end boundary" not in msgs


def test_continuation_lines_stay_with_their_entry(handler):
    out = handler.query(after=f"{DAY}T07:45:00", before=f"{DAY}T07:52:00")
    tb = next(e for e in out["entries"] if e["Message"].startswith("Traceback"))
    assert tb["Message"].endswith("KeyError: 'k'")


def test_whole_number_float_line_count_is_accepted(handler):
    out = handler.query(line_count=2.0, after=f"{DAY}T07:00:00", before=f"{DAY}T08:00:00")
    assert out["success"] is True and out["count"] == 2


def test_fractional_line_count_is_still_refused(handler):
    out = handler.query(line_count=2.5, after=f"{DAY}T07:00:00")
    assert out["success"] is False


def test_null_line_count_is_capped(handler, monkeypatch):
    monkeypatch.setattr(lq, "_MAX_ENTRIES", 2)
    out = handler.query(line_count=None, after=f"{DAY}T07:00:00", before=f"{DAY}T08:00:00")
    assert out["count"] == 2
    assert out["range"]["truncated"] is True
    assert out["range"]["matched_before_limit"] == 4
