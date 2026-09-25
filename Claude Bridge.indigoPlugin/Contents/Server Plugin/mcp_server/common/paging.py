#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    paging.py
# Description: One way to page a long list (3.5.0): list_devices, list_variables,
#              list_triggers, list_schedules and list_action_groups all take
#              limit and offset and say where the next page starts.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

"""
Paging.

`list_devices` with no arguments returned every device in full — 245 KB for
210 devices here (measured 25-09-2026), most of a client's reply budget for
one call. The other lists were small on this house but had no bound at all.

Every list now:

  - sorts by name (ignoring case), then id, so page two starts where page one
    stopped and nothing is skipped or repeated while the house is unchanged;
  - takes `offset` (where to start, default 0) and `limit` (how many);
  - says `total`, `offset`, `limit`, `count` (on this page) and `next_offset`,
    which is None on the last page. `truncated` is next_offset is not None,
    kept for callers that read the older key.

A change to the house between two calls can shift a page by the number of
items added or removed before it; the total on each page shows that it moved.
"""

from typing import Any, Dict, List, Optional, Tuple

MAX_PAGE = 1000


def paging_args(offset: Any, limit: Any, default_limit: int,
                max_limit: int = MAX_PAGE) -> Tuple[int, int, Optional[str]]:
    """(offset, limit, problem). A value that is not a whole number, a
    negative offset or a limit below 1 is a problem, never quietly fixed; a
    limit above max_limit is held to it."""
    try:
        off = 0 if offset is None else _whole(offset, "offset")
        lim = default_limit if limit is None else _whole(limit, "limit")
    except ValueError as exc:
        return 0, default_limit, str(exc)
    if off < 0:
        return 0, default_limit, f"offset must be 0 or more, got {off}"
    if lim < 1:
        return 0, default_limit, f"limit must be 1 or more, got {lim}"
    return off, min(lim, max_limit), None


def _whole(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    if f != f or f != int(f):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    return int(f)


def sort_key(row: Any):
    if isinstance(row, dict):
        return (str(row.get("name", "")).casefold(), _id_key(row.get("id")))
    return ("", 0)


def _id_key(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def page(rows: List[Any], offset: int, limit: int) -> Tuple[List[Any], Dict[str, Any]]:
    """Sort rows by name then id and cut one page out. Returns (page, meta)."""
    ordered = sorted(rows or [], key=sort_key)
    total = len(ordered)
    chunk = ordered[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else None
    meta = {"total": total, "offset": offset, "limit": limit, "count": len(chunk),
            "next_offset": nxt, "truncated": nxt is not None}
    if offset >= total and total:
        meta["note"] = f"offset {offset} is past the end: there are {total}"
    return chunk, meta


def paged_reply(rows: List[Any], key: str, offset: int, limit: int,
                base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A reply carrying one page of rows under `key`, plus the paging facts.
    `base` keeps other keys from an existing reply (success, a query echo)."""
    chunk, meta = page(rows, offset, limit)
    out: Dict[str, Any] = {}
    if base:
        out.update({k: v for k, v in base.items() if k != key})
    out.setdefault("success", True)
    out.update(meta)
    out[key] = chunk
    return out
