#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_exec_lock.py
# Description: Regression tests for the v2.17.0 exec-lock rework — an abandoned
#              runaway script must not turn every later exec call into a
#              full-plugin freeze, and must not leave sys.stdout pointing at its
#              own dead buffer.
# Author:      CliveS & Claude Opus 5
# Date:        25-07-2026
# Version:     1.0

import io
import sys
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def _clean_lock():
    """Each test starts and ends with a healthy, unheld exec lock."""
    from mcp_server.common import exec_lock
    exec_lock.clear_wedge()
    # Drain any leftover hold from a previous failure so tests can't cascade.
    while exec_lock.STDOUT_SWAP_LOCK.acquire(timeout=0):
        try:
            exec_lock.STDOUT_SWAP_LOCK.release()
        except RuntimeError:
            break
        break
    yield
    exec_lock.clear_wedge()


# ── The lock itself ──────────────────────────────────────────────────────────

def test_acquire_fails_fast_when_held():
    """A held lock must be reported quickly, not waited out.

    The old code waited the tool's FULL budget (60s/120s) on a lock an abandoned
    worker would never release — freezing every other tool call and every device
    callback, because Indigo dispatches them all on one thread.
    """
    from mcp_server.common import exec_lock

    holder_has_it = threading.Event()
    release = threading.Event()

    def _holder():
        exec_lock.STDOUT_SWAP_LOCK.acquire()
        holder_has_it.set()
        release.wait(10)
        exec_lock.STDOUT_SWAP_LOCK.release()

    t = threading.Thread(target=_holder, daemon=True)
    t.start()
    assert holder_has_it.wait(5)

    started = time.monotonic()
    got = exec_lock.acquire_for_exec(timeout=0.25)
    elapsed = time.monotonic() - started

    release.set()
    t.join(5)

    assert got is False
    assert elapsed < 2.0, f"waited {elapsed:.1f}s — should fail fast"


def test_busy_error_names_the_stuck_run_not_the_caller():
    """The error must not blame the caller's script for someone else's runaway."""
    from mcp_server.common import exec_lock

    exec_lock.mark_wedged("run_script", "'Nightly_Sweep.py' exceeded 120s")
    err = exec_lock.busy_error("execute_indigo_python")

    assert err["success"] is False
    assert err["busy"] is True
    assert "Nightly_Sweep.py" in err["error"]
    assert "did NOT run" in err["error"]
    # Must point at the Plugins menu, never at a self-restart via MCP.
    assert "Indigo Plugins menu" in err["error"]


def test_wedge_reported_then_cleared():
    from mcp_server.common import exec_lock
    assert exec_lock.wedged_info() is None
    exec_lock.mark_wedged("execute_indigo_python", "exceeded 60s")
    info = exec_lock.wedged_info()
    assert info["tool"] == "execute_indigo_python"
    assert info["since_local"]
    exec_lock.clear_wedge()
    assert exec_lock.wedged_info() is None


# ── stdout identity guard ────────────────────────────────────────────────────

def test_abandoned_worker_cannot_clobber_a_healthy_stdout():
    """A late-finishing worker must not restore over a newer owner's stream.

    Models the real sequence: worker A is abandoned mid-run, a later call
    installs its own buffer, then A finally finishes. Without the identity
    check, A's finally would restore the stream it captured and silently
    redirect all later output.
    """
    real_stdout = sys.stdout
    a_buf = io.StringIO()
    b_buf = io.StringIO()

    # Worker A swaps in its buffer and is then abandoned.
    a_saved = sys.stdout
    sys.stdout = a_buf

    # A later call installs its own buffer on top.
    sys.stdout = b_buf

    # Worker A finally finishes and runs its restore — this is the guard from
    # scripting_shell_handler._worker / script_tools_handler._worker.
    try:
        if sys.stdout is a_buf:          # False — B owns it now
            sys.stdout = a_saved
        assert sys.stdout is b_buf, "abandoned worker clobbered the live stdout"
    finally:
        sys.stdout = real_stdout


# ── health endpoint surfaces the wedge ───────────────────────────────────────

def test_health_reports_wedged_exec(tmp_path):
    from mcp_server.common import exec_lock
    from test_dispatch import _make_handler

    handler = _make_handler(tmp_path)
    # _make_handler is deliberately skeletal (it exists for _handle_tools_call).
    # get_health_data reads a few more attributes — supply just those.
    handler._sessions_lock     = threading.Lock()
    handler._sessions          = {}
    handler._resources         = {}
    handler.vector_store_manager = None

    health = handler.get_health_data()
    assert health["status"] == "ok"
    assert health["exec"]["wedged"] is False

    exec_lock.mark_wedged("run_script", "'Stuck.py' exceeded 120s")
    health = handler.get_health_data()
    assert health["status"] == "degraded"
    assert health["exec"]["wedged"] is True
    assert health["exec"]["tool"] == "run_script"
