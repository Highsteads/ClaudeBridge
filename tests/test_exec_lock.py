#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_exec_lock.py
# Description: The 3.0 job mechanism behind execute_indigo_python and
#              run_script — finish inline, go to the background, collect,
#              refuse a second run naming the first, expire an uncollected
#              result, and call a run past the hard ceiling wedged. Real
#              threads, short sleeps.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     2.0

import builtins
import io
import json
import logging
import sys
import threading
import time

import pytest

from mcp_server.common import exec_lock
from mcp_server.tools.scripting_shell.scripting_shell_handler import ScriptingShellHandler

_LOGGER = logging.getLogger("test-exec-jobs")


@pytest.fixture(autouse=True)
def _clean_jobs(monkeypatch):
    """Every test starts with no job, and a gate its code can wait on."""
    gate = threading.Event()
    monkeypatch.setattr(builtins, "_cb_gate", gate, raising=False)
    monkeypatch.setattr(builtins, "_cb_marker", [], raising=False)
    exec_lock.reset_for_tests()
    yield gate
    gate.set()                                   # let any gated worker finish
    deadline = time.monotonic() + 5
    while exec_lock.status()["running"] and time.monotonic() < deadline:
        time.sleep(0.01)
    exec_lock.reset_for_tests()


def _shell():
    return ScriptingShellHandler(data_provider=None, logger=_LOGGER)


GATED = "import builtins\nbuiltins._cb_gate.wait(5)\nprint('released')\n"


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── Finish inline ────────────────────────────────────────────────────────────

def test_a_quick_run_returns_its_result_exactly_as_before():
    out = _shell().execute_indigo_python("print('hello')", wait_seconds=5)
    assert out["success"] is True
    assert out["stdout"] == "hello\n"
    assert "job_id" not in out and "status" not in out
    assert exec_lock.status() == {"running": None, "uncollected": []}, \
        "a collected-inline run must hold nothing afterwards"


def test_stdout_is_restored_after_the_run():
    before = sys.stdout
    _shell().execute_indigo_python("print('x')", wait_seconds=5)
    assert sys.stdout is before


def test_eval_mode_and_a_failure_keep_their_shape():
    shell = _shell()
    assert shell.execute_indigo_python("6 * 7", mode="eval", wait_seconds=5)["value"] == "42"
    bad = shell.execute_indigo_python("{}['nope']", wait_seconds=5)
    assert bad["success"] is False
    assert bad["error"] == "KeyError: 'nope'"
    assert bad["traceback"].rstrip().endswith("KeyError: 'nope'")


# ── Go to the background, then collect ───────────────────────────────────────

def test_a_slow_run_hands_back_a_job_and_frees_the_caller(_clean_jobs):
    shell = _shell()
    started = time.monotonic()
    first = shell.execute_indigo_python(GATED, wait_seconds=0.2)
    assert time.monotonic() - started < 2, "the request thread must be freed"
    assert first["status"] == "running"
    job_id = first["job_id"]
    assert "job_id='" + job_id + "'" in first["note"]
    assert first["elapsed_seconds"] >= 0

    # Still running: collecting reports the same job again.
    again = shell.execute_indigo_python(job_id=job_id, wait_seconds=0.1)
    assert again["status"] == "running" and again["job_id"] == job_id

    _clean_jobs.set()
    done = shell.execute_indigo_python(job_id=job_id, wait_seconds=5)
    assert done["success"] is True
    assert done["stdout"] == "released\n"
    assert "status" not in done

    # Collected once, forgotten: a second collect is a clear error.
    gone = shell.execute_indigo_python(job_id=job_id, wait_seconds=0)
    assert gone["success"] is False and job_id in gone["error"]


def test_an_unknown_job_id_is_a_clear_error():
    out = _shell().execute_indigo_python(job_id="deadbeef", wait_seconds=0)
    assert out["success"] is False
    assert "deadbeef" in out["error"] and "expired" in out["error"]


def test_code_and_job_id_together_are_refused():
    out = _shell().execute_indigo_python("print(1)", job_id="deadbeef")
    assert out["success"] is False and "not both" in out["error"]


# ── Busy refusal ─────────────────────────────────────────────────────────────

def test_a_second_run_is_refused_at_once_naming_the_first(_clean_jobs):
    shell = _shell()
    first = shell.execute_indigo_python(GATED, wait_seconds=0.1)
    job_id = first["job_id"]

    started = time.monotonic()
    second = shell.execute_indigo_python(
        "import builtins\nbuiltins._cb_marker.append(1)\n", wait_seconds=5)
    assert time.monotonic() - started < 1, "a refusal must not wait"
    assert second["success"] is False and second["busy"] is True
    assert second["running_job_id"] == job_id
    assert job_id in second["error"] and "did NOT run" in second["error"]
    assert "execute_indigo_python" in second["error"]
    assert builtins._cb_marker == [], "the refused code must not have run"

    # The sibling tool is refused by the same slot.
    busy = exec_lock.busy_error("run_script")
    assert busy["running_job_id"] == job_id

    _clean_jobs.set()
    assert shell.execute_indigo_python(job_id=job_id, wait_seconds=5)["success"] is True
    # Once it has finished the slot is free again.
    assert shell.execute_indigo_python("print(2)", wait_seconds=5)["stdout"] == "2\n"


def test_a_finished_but_uncollected_run_does_not_hold_the_slot(_clean_jobs):
    shell = _shell()
    first = shell.execute_indigo_python(GATED, wait_seconds=0)
    _clean_jobs.set()
    assert _wait_until(lambda: exec_lock.status()["running"] is None)
    assert first["job_id"] in exec_lock.status()["uncollected"]
    assert shell.execute_indigo_python("print(3)", wait_seconds=5)["success"] is True
    # ... and the earlier result can still be collected.
    assert shell.execute_indigo_python(job_id=first["job_id"])["stdout"] == "released\n"


def test_a_job_is_collected_only_by_the_tool_that_started_it(_clean_jobs):
    job = _shell().execute_indigo_python(GATED, wait_seconds=0)["job_id"]
    out = exec_lock.collect("run_script", job, 0)
    assert out["success"] is False
    assert f"execute_indigo_python(job_id='{job}')" in out["error"]


# ── Expiry and the hard ceiling ──────────────────────────────────────────────

def test_an_uncollected_result_expires(_clean_jobs, monkeypatch):
    monkeypatch.setattr(exec_lock, "RESULT_TTL_SECONDS", 0.05)
    shell = _shell()
    job_id = shell.execute_indigo_python(GATED, wait_seconds=0)["job_id"]
    _clean_jobs.set()
    assert _wait_until(lambda: exec_lock.status()["running"] is None)
    time.sleep(0.15)
    out = shell.execute_indigo_python(job_id=job_id, wait_seconds=0)
    assert out["success"] is False and "expired" in out["error"]
    assert exec_lock.status()["uncollected"] == []


def test_a_run_past_the_ceiling_is_wedged_and_keeps_the_slot(_clean_jobs, monkeypatch, tmp_path):
    monkeypatch.setattr(exec_lock, "HARD_CEILING_SECONDS", 0.2)
    shell = _shell()
    job_id = shell.execute_indigo_python(GATED, wait_seconds=0)["job_id"]
    time.sleep(0.3)

    report = shell.execute_indigo_python(job_id=job_id, wait_seconds=0)
    assert report["wedged"] is True and report["timed_out"] is True
    assert report["success"] is False
    assert "Indigo Plugins menu" in report["error"]

    refused = shell.execute_indigo_python("print(1)", wait_seconds=0)
    assert refused["busy"] is True and refused["wedged"] is True
    assert "Indigo Plugins menu" in refused["error"]
    assert "do NOT restart Claude Bridge" in refused["error"]

    info = exec_lock.wedged_info()
    assert info["job_id"] == job_id and info["worker_alive"] is True
    assert "thread" not in info, "a Thread object cannot be serialised for /health"

    # /health says so.
    from test_dispatch import _make_handler
    handler = _make_handler(tmp_path)
    handler._sessions_lock = threading.Lock()
    handler._sessions = {}
    handler._resources = {}
    health = handler.get_health_data()
    assert health["status"] == "degraded" and health["exec"]["wedged"] is True
    assert health["exec"]["jobs"]["running"]["job_id"] == job_id
    json.dumps(health)

    # When it does finish, it clears itself and the result is collectable.
    _clean_jobs.set()
    assert _wait_until(lambda: exec_lock.status()["running"] is None)
    assert exec_lock.wedged_info() is None
    assert shell.execute_indigo_python(job_id=job_id)["stdout"] == "released\n"


def test_health_is_ok_with_nothing_running(tmp_path):
    from test_dispatch import _make_handler
    handler = _make_handler(tmp_path)
    handler._sessions_lock = threading.Lock()
    handler._sessions = {}
    handler._resources = {}
    health = handler.get_health_data()
    assert health["status"] == "ok" and health["exec"]["wedged"] is False


# ── The pieces ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    (None, 5.0), (3, 3.0), ("2.5", 2.5), (-4, 0.0), (999, 20.0), ("soon", 5.0), (True, 5.0),
])
def test_wait_seconds_is_clamped(given, expected):
    assert exec_lock.clamp_wait(given) == expected


def test_work_that_raises_becomes_a_failure_result():
    def _boom():
        raise RuntimeError("worker fell over")
    job, busy = exec_lock.start("execute_indigo_python", "test", _boom)
    assert busy is None
    out = exec_lock.wait(job, 5)
    assert out == {"success": False, "error": "RuntimeError: worker fell over"}
    assert exec_lock.status()["running"] is None


def test_abandoned_worker_cannot_clobber_a_healthy_stdout():
    """A late-finishing worker must not restore over a newer owner's stream —
    the identity guard both handlers' workers carry."""
    real_stdout = sys.stdout
    a_buf, b_buf = io.StringIO(), io.StringIO()
    a_saved = sys.stdout
    sys.stdout = a_buf
    sys.stdout = b_buf                   # a later owner installs its own buffer
    try:
        if sys.stdout is a_buf:          # False — B owns it now
            sys.stdout = a_saved
        assert sys.stdout is b_buf, "abandoned worker clobbered the live stdout"
    finally:
        sys.stdout = real_stdout


# ── run_script uses the same jobs ────────────────────────────────────────────

def test_run_script_goes_to_the_background_and_is_collected(_clean_jobs, tmp_path, monkeypatch):
    from mcp_server.tools.script_tools import script_tools_handler as sth
    script = tmp_path / "Slow.py"
    script.write_text(GATED, encoding="utf-8")
    monkeypatch.setattr(sth, "_resolve", lambda name: str(script))
    handler = sth.ScriptToolsHandler(data_provider=None, logger=_LOGGER)

    first = handler.run_script("Slow.py", wait_seconds=0.1)
    assert first["status"] == "running"
    refused = _shell().execute_indigo_python("print(1)", wait_seconds=0)
    assert refused["running_job_id"] == first["job_id"]
    assert "run_script" in refused["error"] and "Slow.py" in refused["error"]

    _clean_jobs.set()
    done = handler.run_script(job_id=first["job_id"], wait_seconds=5)
    assert done["success"] is True and done["name"] == "Slow.py"
    assert done["stdout"] == "released\n"


def test_run_script_failure_keeps_the_traceback_tail(tmp_path, monkeypatch):
    from mcp_server.tools.script_tools import script_tools_handler as sth
    script = tmp_path / "Bad.py"
    script.write_text("x = {}\nx['missing']\n", encoding="utf-8")
    monkeypatch.setattr(sth, "_resolve", lambda name: str(script))
    out = sth.ScriptToolsHandler(data_provider=None, logger=_LOGGER).run_script("Bad.py")
    assert out["success"] is False and out["error"] == "KeyError: 'missing'"
    assert out["traceback"].rstrip().endswith("KeyError: 'missing'")


# ── A collected failure is still redacted on the way out ─────────────────────

def test_a_collected_failure_goes_through_redaction(_clean_jobs, tmp_path):
    from mcp_server import registry
    from test_error_redaction import _make_handler, _redactor

    r, _ = _redactor(tmp_path)
    h = _make_handler(tmp_path, {}, r)
    h.scripting_shell_handler = _shell()
    spec = registry.spec_for("execute_indigo_python")
    h._tools = {spec.name: {"description": spec.description, "inputSchema": spec.input_schema,
                            "function": h._tool_function(spec)}}

    code = "import builtins\nbuiltins._cb_gate.wait(5)\nraise KeyError('hunter2-mqtt')\n"
    first = h._handle_tools_call(1, {"name": "execute_indigo_python",
                                     "arguments": {"code": code, "wait_seconds": 0}})
    running = json.loads(first["result"]["content"][0]["text"])
    assert running["status"] == "running"

    _clean_jobs.set()
    resp = h._handle_tools_call(2, {"name": "execute_indigo_python",
                                    "arguments": {"job_id": running["job_id"],
                                                  "wait_seconds": 5}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["success"] is False
    assert "hunter2-mqtt" not in json.dumps(body)
    assert body["traceback"].rstrip().endswith("KeyError: '[redacted MQTT_PASSWORD]'")


def test_the_busy_refusal_keeps_its_job_id_through_the_full_scrub():
    """If the redactor cannot load, the whole-payload scrub still has to tell
    the caller WHICH job to collect."""
    from mcp_server.mcp_handler import MCPHandler
    raw = json.dumps({"success": False, "busy": True, "running_job_id": "ab12cd34",
                      "elapsed_seconds": 12.0, "error": "secret-laden text"})
    out = json.loads(MCPHandler._scrub_error_result(raw))
    assert out["running_job_id"] == "ab12cd34" and out["busy"] is True
    assert "secret" not in out["error"]
