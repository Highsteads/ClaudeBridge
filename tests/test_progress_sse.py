#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_progress_sse.py
# Description: Tests for the buffered-SSE progress path: ProgressEmitter event
#              collection (step numbering, progress clamping) and
#              encode_sse_response framing. The proxy's SSE reader depends on
#              the exact "data: {...}\n\n" block shape and the "data: [DONE]"
#              terminator — drift here breaks every long-running tool.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import json

from mcp_server.common.progress import ProgressEmitter, encode_sse_response


# ── ProgressEmitter ───────────────────────────────────────────────────────────

def test_emit_numbers_steps_and_records_messages():
    e = ProgressEmitter(request_id=42, tool_name="audit_home")
    assert e.has_events is False
    e.emit("Scanning devices…", progress=0.1)
    e.emit("Cross-referencing…", progress=0.6, data={"devices": 200})
    assert e.has_events is True
    assert [ev["step"] for ev in e.events] == [1, 2]
    assert e.events[0]["message"] == "Scanning devices…"
    assert e.events[1]["data"] == {"devices": 200}


def test_progress_is_clamped_to_unit_interval():
    e = ProgressEmitter(request_id=1, tool_name="t")
    e.emit("over", progress=1.7)
    e.emit("under", progress=-0.3)
    assert e.events[0]["progress"] == 1.0
    assert e.events[1]["progress"] == 0.0


def test_non_numeric_progress_is_dropped_not_fatal():
    e = ProgressEmitter(request_id=1, tool_name="t")
    e.emit("odd", progress="halfway")
    assert "progress" not in e.events[0]
    assert e.events[0]["message"] == "odd"


# ── encode_sse_response framing ───────────────────────────────────────────────

def _parse_blocks(body):
    """Split an SSE body into its data payloads (raw strings)."""
    blocks = [b for b in body.split("\n\n") if b]
    assert all(b.startswith("data: ") for b in blocks)
    return [b[len("data: "):] for b in blocks]


def test_sse_body_shape_and_terminator():
    e = ProgressEmitter(request_id=7, tool_name="t")
    e.emit("step one", progress=0.5)
    e.emit("step two")
    final = {"jsonrpc": "2.0", "id": 7, "result": {"content": []}}

    body = encode_sse_response(e.events, final, request_id=7)

    assert body.endswith("data: [DONE]\n\n")     # proxy short-circuits on this
    payloads = _parse_blocks(body)
    assert len(payloads) == 4                     # 2 progress + final + [DONE]
    assert payloads[-1] == "[DONE]"

    notif1 = json.loads(payloads[0])
    assert notif1["method"] == "notifications/progress"
    assert notif1["params"]["progressToken"] == 7
    assert notif1["params"]["progress"] == 0.5
    assert notif1["params"]["step"] == 1

    # Second event had no progress value — the key must be absent, not null.
    notif2 = json.loads(payloads[1])
    assert "progress" not in notif2["params"]

    assert json.loads(payloads[2]) == final       # final response verbatim


def test_sse_with_no_events_is_just_final_plus_done():
    final = {"jsonrpc": "2.0", "id": 1, "result": {}}
    payloads = _parse_blocks(encode_sse_response([], final, request_id=1))
    assert len(payloads) == 2
    assert json.loads(payloads[0]) == final
    assert payloads[1] == "[DONE]"
