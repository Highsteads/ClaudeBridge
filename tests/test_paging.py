#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_paging.py
# Description: Paging for the five list tools (3.5.0). list_devices with no
#              arguments returned every device in full (245 KB for 210 devices,
#              measured 25-09-2026) and the other lists had no bound at all. Each
#              now sorts by name then id, takes limit and offset, and says total,
#              count and next_offset. Walking the pages must visit every item
#              exactly once.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

from types import SimpleNamespace

import pytest

from conftest import call_tool
from mcp_server.common import paging

ROWS = [{"id": i, "name": n} for i, n in
        [(5, "beta"), (2, "Alpha"), (9, "alpha"), (1, "gamma"), (7, "Beta"), (3, "delta")]]


# ── the helper ──────────────────────────────────────────────────────────────

def test_sorted_by_name_ignoring_case_then_id():
    chunk, _ = paging.page(ROWS, 0, 100)
    assert [(r["name"], r["id"]) for r in chunk] == [
        ("Alpha", 2), ("alpha", 9), ("beta", 5), ("Beta", 7), ("delta", 3), ("gamma", 1)]


@pytest.mark.parametrize("size", [1, 2, 4, 5, 6, 7])
def test_walking_the_pages_visits_every_row_once(size):
    seen, offset, pages = [], 0, 0
    while offset is not None:
        assert pages <= len(ROWS), "next_offset never came back null: the walk would not end"
        chunk, meta = paging.page(ROWS, offset, size)
        assert meta["total"] == len(ROWS) and meta["count"] == len(chunk)
        assert meta["truncated"] is (meta["next_offset"] is not None)
        seen += [r["id"] for r in chunk]
        offset = meta["next_offset"]
        pages += 1
    assert sorted(seen) == sorted(r["id"] for r in ROWS) and len(seen) == len(ROWS)
    assert pages == -(-len(ROWS) // size)


def test_the_last_page_has_no_next_offset_even_when_exactly_full():
    _, meta = paging.page(ROWS, 3, 3)
    assert meta["count"] == 3 and meta["next_offset"] is None


def test_an_offset_past_the_end_says_so():
    chunk, meta = paging.page(ROWS, 50, 10)
    assert chunk == [] and meta["next_offset"] is None and "past the end" in meta["note"]


def test_an_empty_list_is_one_empty_page():
    chunk, meta = paging.page([], 0, 10)
    assert chunk == [] and meta["total"] == 0 and meta["next_offset"] is None
    assert "note" not in meta


@pytest.mark.parametrize("offset,limit,want", [
    (None, None, (0, 50, None)),
    (10, 20, (10, 20, None)),
    ("10", "20", (10, 20, None)),
    (0, 5000, (0, paging.MAX_PAGE, None)),
])
def test_paging_args_accepts(offset, limit, want):
    assert paging.paging_args(offset, limit, 50) == want


@pytest.mark.parametrize("offset,limit,word", [
    (-1, None, "offset"), (None, 0, "limit"), (1.5, None, "offset"),
    (True, None, "offset"), ("next", None, "offset"), (None, "all", "limit"),
])
def test_paging_args_refuses(offset, limit, word):
    _, _, problem = paging.paging_args(offset, limit, 50)
    assert problem and word in problem


def test_paged_reply_keeps_other_keys_and_replaces_stale_counts():
    out = paging.paged_reply(ROWS, "triggers", 0, 2,
                             base={"success": True, "count": 99, "triggers": ["stale"],
                                   "query": "x"})
    assert out["count"] == 2 and out["total"] == 6 and out["query"] == "x"
    assert [r["id"] for r in out["triggers"]] == [2, 9]


# ── the five tools ──────────────────────────────────────────────────────────

def _ctx():
    rows = [dict(r) for r in ROWS]
    lh = SimpleNamespace(list_all_devices=lambda: rows, list_all_variables=lambda: rows,
                         list_all_action_groups=lambda: rows)
    sch = SimpleNamespace(
        list_triggers=lambda: {"success": True, "count": len(rows), "triggers": rows},
        list_schedules=lambda: {"success": True, "count": len(rows), "schedules": rows})
    return SimpleNamespace(list_handlers=lh, schedule_control_handler=sch)


@pytest.mark.parametrize("tool,key", [
    ("list_devices", "devices"), ("list_variables", "variables"),
    ("list_action_groups", "action_groups"), ("list_triggers", "triggers"),
    ("list_schedules", "schedules"),
])
def test_every_list_tool_pages(tool, key):
    first = call_tool(_ctx(), tool, limit=4)
    assert first["success"] is True and first["total"] == 6
    assert [r["id"] for r in first[key]] == [2, 9, 5, 7]
    assert first["next_offset"] == 4
    rest = call_tool(_ctx(), tool, limit=4, offset=first["next_offset"])
    assert [r["id"] for r in rest[key]] == [3, 1] and rest["next_offset"] is None
    assert "offset" in call_tool(_ctx(), tool, offset=-3)["error"]


@pytest.mark.parametrize("tool,default", [
    ("list_devices", 50), ("list_variables", 200), ("list_action_groups", 200),
    ("list_triggers", 200), ("list_schedules", 200),
])
def test_default_page_sizes(tool, default):
    assert call_tool(_ctx(), tool)["limit"] == default


def test_a_handler_failure_passes_through_unpaged():
    ctx = _ctx()
    ctx.schedule_control_handler.list_triggers = lambda: {"success": False, "error": "boom"}
    assert call_tool(ctx, "list_triggers") == {"success": False, "error": "boom"}
