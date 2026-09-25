#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_change_log.py
# Description: The permanent change log (3.4.0). Every tools/call that needs
#              write or admin is recorded — worked, failed or refused — with the
#              key's name, the tool, its arguments with secrets blanked (the
#              Python it ran included), the outcome and the time taken. Checks
#              the redaction, the file (monthly, private, append-only), reading
#              it back, the background-job bookkeeping, the fail-closed path
#              and the wiring through _handle_tools_call.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import logging
import os
import stat
import threading
import time
from collections import deque
from datetime import datetime

import pytest

from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager
from mcp_server.security import change_log as cl

_LOGGER = logging.getLogger("test-change-log")
SECRET = "sk-live-0123456789abcdef"
VALUES = {SECRET: "OWM_API_KEY"}


def _log(tmp_path, values=None, clock=None):
    return cl.ChangeLog(str(tmp_path / "change-log"),
                        secret_values=(lambda: dict(values if values is not None else VALUES)),
                        logger=_LOGGER, **({"clock": clock} if clock else {}))


def _entries(log):
    assert log.flush()
    out = []
    for path in log.files():
        with open(path, encoding="utf-8") as fh:
            out += [json.loads(line) for line in fh if line.strip()]
    return out


# ── redaction ───────────────────────────────────────────────────────────────

def test_a_credential_named_argument_is_replaced_whatever_it_holds():
    got = cl.redact_args({"device": 12, "pin": "4821", "api_key": "short"}, {})
    assert got == {"device": 12, "pin": cl.REDACTED_ARG, "api_key": cl.REDACTED_ARG}


def test_a_known_secret_is_blanked_inside_the_python_but_the_rest_is_kept():
    code = f"import requests\nrequests.get(url, params={{'appid': '{SECRET}'}})\nprint('done')"
    got = cl.redact_args({"code": code}, VALUES)["code"]
    assert SECRET not in got
    assert "[redacted OWM_API_KEY]" in got and "print('done')" in got


def test_nested_arguments_are_redacted_too():
    got = cl.redact_args({"props": {"password": "hunter22", "note": f"key {SECRET}"},
                          "list": [SECRET, 3]}, VALUES)
    assert got["props"]["password"] == cl.REDACTED_ARG
    assert SECRET not in json.dumps(got)
    assert got["list"][1] == 3


def test_a_very_long_string_is_capped_and_says_so():
    got = cl.redact_args({"code": "x" * (cl.MAX_STRING_CHARS + 50)}, {})["code"]
    assert got.startswith("x" * 100) and got.endswith("[50 more characters not kept]")


def test_which_calls_count_as_changes():
    assert cl.is_change("write") and cl.is_change("admin") and not cl.is_change("read")
    assert cl.is_collect_only("execute_indigo_python", {"job_id": "ab12"})
    assert cl.is_collect_only("run_script", {"job_id": "ab12", "wait_seconds": 10})
    assert not cl.is_collect_only("execute_indigo_python", {"code": "print(1)"})
    assert not cl.is_collect_only("variable_update", {"job_id": "x"})


# ── the file ────────────────────────────────────────────────────────────────

def test_an_entry_is_written_to_this_months_file_privately(tmp_path):
    log = _log(tmp_path)
    log.record(key="phone-app", tool="variable_update", scope="write",
               args={"variable": "x", "value": SECRET}, outcome="ok", duration_ms=12)
    (e,) = _entries(log)
    assert e["key"] == "phone-app" and e["tool"] == "variable_update" and e["outcome"] == "ok"
    assert e["args"]["value"] == "[redacted OWM_API_KEY]"
    assert e["duration_ms"] == 12 and e["scope"] == "write"
    assert datetime.fromisoformat(e["time"]).tzinfo is not None
    (path,) = log.files()
    assert os.path.basename(path) == f"changes-{datetime.now():%Y-%m}.jsonl"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(log.folder).st_mode) == 0o700
    log.stop()


def test_it_appends_and_never_rewrites(tmp_path):
    log = _log(tmp_path)
    for i in range(3):
        log.record(key="k", tool="fire_trigger", args={"trigger": i}, outcome="ok")
    assert [e["args"]["trigger"] for e in _entries(log)] == [0, 1, 2]
    log.stop()
    again = _log(tmp_path)                     # a restart
    again.record(key="k", tool="fire_trigger", args={"trigger": 3}, outcome="ok")
    assert [e["args"]["trigger"] for e in _entries(again)] == [0, 1, 2, 3]
    again.stop()


def test_each_month_has_its_own_file(tmp_path):
    t = [datetime(2026, 8, 31, 23, 59).timestamp()]
    log = _log(tmp_path, clock=lambda: t[0])
    log.record(key="k", tool="set_enabled", args={}, outcome="ok")
    t[0] = datetime(2026, 9, 1, 0, 1).timestamp()
    log.record(key="k", tool="set_enabled", args={}, outcome="ok")
    assert log.flush()
    assert [os.path.basename(p) for p in log.files()] == ["changes-2026-08.jsonl",
                                                          "changes-2026-09.jsonl"]
    log.stop()


def test_when_the_secrets_cannot_be_read_the_arguments_are_withheld(tmp_path):
    def broken():
        raise OSError("IndigoSecrets.py unreadable")
    log = cl.ChangeLog(str(tmp_path / "cl"), secret_values=broken, logger=_LOGGER)
    log.record(key="k", tool="execute_indigo_python", args={"code": f"x='{SECRET}'"},
               outcome="failed", error=f"boom {SECRET}")
    (e,) = _entries(log)
    assert "args" not in e and "args_withheld" in e
    assert SECRET not in json.dumps(e)
    log.stop()


def test_a_burst_the_writer_cannot_take_is_counted_not_lost_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "QUEUE_MAX", 2)
    gate = threading.Event()

    def slow_values():
        gate.wait(5)
        return {}
    log = cl.ChangeLog(str(tmp_path / "cl"), secret_values=slow_values, logger=_LOGGER)
    for i in range(8):
        log.record(key="k", tool="fire_trigger", args={"i": i}, outcome="ok")
    gate.set()
    log.record(key="k", tool="fire_trigger", args={"i": "after"}, outcome="ok")
    entries = _entries(log)
    assert sum(e.get("missed_before_this", 0) for e in entries) + len(entries) == 9
    assert any(e.get("missed_before_this") for e in entries)
    log.stop()


# ── reading it back ─────────────────────────────────────────────────────────

def test_read_is_newest_first_and_filters(tmp_path):
    log = _log(tmp_path)
    log.record(key="phone", tool="fire_trigger", args={}, outcome="ok")
    log.record(key="default", tool="execute_indigo_python", args={"code": "1"}, outcome="failed",
               error="NameError")
    log.record(key="phone", tool="delete_device", args={}, outcome="refused", error="no")
    assert log.flush()
    got = log.read()
    assert [e["tool"] for e in got["entries"]] == ["delete_device", "execute_indigo_python",
                                                   "fire_trigger"]
    assert [e["tool"] for e in log.read(key="PHONE")["entries"]] == ["delete_device", "fire_trigger"]
    assert [e["tool"] for e in log.read(outcome="failed")["entries"]] == ["execute_indigo_python"]
    one = log.read(limit=1)
    assert len(one["entries"]) == 1 and one["more"] is True
    assert log.read(limit=3)["more"] is False, "an exactly full last page has no more"
    assert log.read(since="2999-01-01")["entries"] == []
    with pytest.raises(ValueError):
        log.read(since="yesterday")
    log.stop()


def test_a_damaged_line_is_counted_and_skipped(tmp_path):
    log = _log(tmp_path)
    log.record(key="k", tool="fire_trigger", args={}, outcome="ok")
    assert log.flush()
    with open(log.files()[0], "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    got = log.read()
    assert len(got["entries"]) == 1 and got["unreadable_lines"] == 1
    log.stop()


def test_describe_reads_as_a_sentence():
    line = cl.describe({"time": "2026-09-25T14:31:05+01:00", "key": "default",
                        "tool": "device_control", "args": {"action": "on"},
                        "outcome": "ok", "duration_ms": 420})
    assert line == "25 Sep 14:31:05  key 'default'  device_control on: done in 0.4 s"


# ── background jobs ─────────────────────────────────────────────────────────

def test_a_job_that_came_back_running_gets_a_finished_entry(tmp_path):
    log = _log(tmp_path)
    log.record(key="default", tool="execute_indigo_python", args={"code": "slow()"},
               outcome="running", job_id="ab12")
    log.record_job_finished(tool="execute_indigo_python", job_id="ab12", ok=False,
                            error=f"boom {SECRET}", seconds=31.5)
    started, finished = _entries(log)
    assert started["outcome"] == "running" and started["job_id"] == "ab12"
    assert finished["event"] == "job finished" and finished["key"] == "default"
    assert finished["outcome"] == "failed" and finished["duration_ms"] == 31500
    assert SECRET not in finished["error"]
    log.stop()


def test_a_job_that_finished_inside_its_call_gets_no_second_entry(tmp_path):
    log = _log(tmp_path)
    log.record_job_finished(tool="run_script", job_id="cd34", ok=True, seconds=0.2)
    log.record(key="default", tool="run_script", args={"script": "x.py"}, outcome="ok")
    (only,) = _entries(log)
    assert only["outcome"] == "ok" and "event" not in only
    log.stop()


def test_a_finish_that_beats_its_running_entry_is_held_for_it(tmp_path):
    log = _log(tmp_path)
    log.record_job_finished(tool="run_script", job_id="ef56", ok=True, seconds=6)
    log.record(key="phone", tool="run_script", args={"script": "x.py"},
               outcome="running", job_id="ef56")
    started, finished = _entries(log)
    assert started["outcome"] == "running"
    assert finished["event"] == "job finished" and finished["key"] == "phone"
    log.stop()


# ── through the real dispatch path ──────────────────────────────────────────

def _tool(fn, properties=None):
    return {"description": "t", "inputSchema": {"type": "object",
                                                "properties": properties or {},
                                                "required": []},
            "function": fn}


def _handler(tmp_path, tools, scopes=None):
    if scopes is not None:
        (tmp_path / "scopes.json").write_text(json.dumps(scopes), encoding="utf-8")
    h = object.__new__(MCPHandler)
    h.logger = _LOGGER
    h.scope_manager = ScopeManager(scopes_file=str(tmp_path / "scopes.json"), logger=_LOGGER)
    h.rate_limiter = RateLimiter(logger=_LOGGER)
    h.tool_cache = ToolCache(default_ttl=0, logger=_LOGGER)
    h._telemetry_lock = threading.Lock()
    h._tool_call_log = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools = tools
    h.entity_index_manager = None
    h.change_log = _log(tmp_path)
    return h


def _call(h, name, args, bearer=None):
    return h._handle_tools_call(1, {"name": name, "arguments": args},
                                headers={"authorization": f"Bearer {bearer}"} if bearer else {})


def test_a_write_call_is_recorded_and_a_read_call_is_not(tmp_path):
    h = _handler(tmp_path, {
        "variable_update": _tool(lambda **kw: '{"success": true}',
                                 {"variable": {"type": "string"}, "value": {"type": "string"}}),
        "list_devices": _tool(lambda **kw: "[]"),
    })
    _call(h, "list_devices", {})
    _call(h, "variable_update", {"variable": "v", "value": SECRET}, bearer="any-key")
    (e,) = _entries(h.change_log)
    assert e["tool"] == "variable_update" and e["outcome"] == "ok" and e["key"] == "default"
    assert e["args"] == {"variable": "v", "value": "[redacted OWM_API_KEY]"}
    assert isinstance(e["duration_ms"], int)
    h.change_log.stop()


def test_the_python_claude_ran_is_kept(tmp_path):
    code = "for d in indigo.devices:\n    print(d.name)\n"
    h = _handler(tmp_path, {
        "execute_indigo_python": _tool(lambda **kw: '{"success": true, "stdout": "x"}',
                                       {"code": {"type": "string"}, "mode": {"type": "string"}}),
    })
    _call(h, "execute_indigo_python", {"code": code, "mode": "exec"})
    (e,) = _entries(h.change_log)
    assert e["args"]["code"] == code and e["scope"] == "admin"
    assert "stdout" not in json.dumps(e), "the reply is never kept"
    h.change_log.stop()


def test_a_failed_call_records_its_error(tmp_path):
    h = _handler(tmp_path, {
        "fire_trigger": _tool(lambda **kw: '{"success": false, "error": "no such trigger"}',
                              {"trigger": {"type": "string"}}),
    })
    _call(h, "fire_trigger", {"trigger": "Nope"})
    (e,) = _entries(h.change_log)
    assert e["outcome"] == "failed" and e["error"] == "no such trigger"
    h.change_log.stop()


def test_a_call_that_raises_records_the_exception(tmp_path):
    def boom(**kw):
        raise RuntimeError("the device went away")
    h = _handler(tmp_path, {"fire_trigger": _tool(boom, {"trigger": {"type": "string"}})})
    _call(h, "fire_trigger", {"trigger": "X"})
    (e,) = _entries(h.change_log)
    assert e["outcome"] == "failed" and "the device went away" in e["error"]
    h.change_log.stop()


def test_a_refused_call_is_recorded_with_the_key_name(tmp_path):
    ran = []
    h = _handler(tmp_path, {
        "variable_update": _tool(lambda **kw: ran.append(1) or "{}",
                                 {"variable": {"type": "string"}}),
    }, scopes={"tokens": {"phone": {"name": "phone-app", "scopes": ["read"]}}})
    _call(h, "variable_update", {"variable": "v"}, bearer="phone")
    (e,) = _entries(h.change_log)
    assert not ran
    assert e["outcome"] == "refused" and e["key"] == "phone-app"
    assert "write" in e["error"]
    assert "phone" not in json.dumps({k: v for k, v in e.items() if k != "key"}), \
        "the key itself is never written"
    h.change_log.stop()


def test_a_running_job_is_recorded_with_its_id_and_a_collect_call_is_not(tmp_path):
    h = _handler(tmp_path, {
        "execute_indigo_python": _tool(
            lambda **kw: '{"status": "running", "job_id": "ab12"}' if "code" in kw
            else '{"success": true}',
            {"code": {"type": "string"}, "job_id": {"type": "string"}}),
    })
    _call(h, "execute_indigo_python", {"code": "slow()"})
    _call(h, "execute_indigo_python", {"job_id": "ab12"})
    _call(h, "execute_indigo_python", {"job_id": "ab12"})
    (e,) = _entries(h.change_log)
    assert e["outcome"] == "running" and e["job_id"] == "ab12"
    h.change_log.stop()


def test_a_handler_without_a_change_log_still_answers(tmp_path):
    h = _handler(tmp_path, {"fire_trigger": _tool(lambda **kw: "{}", {"trigger": {"type": "string"}})})
    h.change_log.stop()
    del h.change_log
    resp = _call(h, "fire_trigger", {"trigger": "X"})
    assert "error" not in resp


def test_the_writer_is_off_the_request_thread(tmp_path):
    gate = threading.Event()

    def slow_values():
        gate.wait(5)
        return {}
    h = _handler(tmp_path, {"fire_trigger": _tool(lambda **kw: "{}", {"trigger": {"type": "string"}})})
    h.change_log.stop()
    h.change_log = cl.ChangeLog(str(tmp_path / "slow"), secret_values=slow_values, logger=_LOGGER)
    t = time.monotonic()
    _call(h, "fire_trigger", {"trigger": "X"})
    assert time.monotonic() - t < 1.0, "a slow redaction must not hold the reply"
    gate.set()
    assert len(_entries(h.change_log)) == 1
    h.change_log.stop()
