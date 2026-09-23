#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2200_high_fixes.py
# Description: Regression tests for the three high-severity findings of the
#              09-Aug-2026 deep review — the unsavable config dialog, the
#              reentrant exec lock that refused nothing, and the entity-name
#              validator that failed open into the InfluxQL builder.
# Author:      CliveS & Claude Opus 5
# Date:        09-08-2026
# Version:     1.0

import ast
import os
import threading

import pytest

from conftest import SERVER_PLUGIN


# ── H1: the Configure dialog must still validate what it holds ───────────────
#
# (The Anthropic key this section once guarded went in the September 2026
# spring clean.) Asserted against the parsed source rather than by importing
# plugin.py, which needs the full Indigo host to construct.

def _validate_prefs_source() -> str:
    path = os.path.join(SERVER_PLUGIN, "plugin.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "validatePrefsConfigUi":
            return ast.unparse(node)
    raise AssertionError("validatePrefsConfigUi not found in plugin.py")


def test_other_prefs_are_still_validated():
    """Removing the key check must not have gutted the rest of the validator."""
    src = _validate_prefs_source()
    assert "errors_dict['log_level']" in src


# ── H2: a wedged exec must actually refuse the next call ─────────────────────
#
# STDOUT_SWAP_LOCK is an RLock and dispatch is single-threaded, so the next
# caller is the same thread that wedged it: acquire() alone always succeeds and
# refused nothing. The wedge record, tested for liveness, is what refuses.

def _drain_lock():
    """Release EVERY level this thread holds.

    These tests deliberately leave the lock held (that is what a wedge is), and
    the lock is reentrant — so releasing once is not enough. A single release
    leaves the deeper level held and the next test's holder thread blocks for
    ever, which is exactly how a stale hold leaks across a whole suite.
    """
    from mcp_server.common import exec_lock
    exec_lock.clear_wedge()
    for _ in range(100):
        try:
            exec_lock.STDOUT_SWAP_LOCK.release()
        except RuntimeError:
            return


@pytest.fixture(autouse=True)
def _clean_lock():
    _drain_lock()
    yield
    _drain_lock()


def test_same_thread_is_refused_while_the_abandoned_worker_runs():
    """The exact production sequence, on ONE thread — as Indigo dispatches it.

    Fails against the pre-fix code: the reentrant acquire returns True and the
    second run swaps stdout out from under the still-live worker.
    """
    from mcp_server.common import exec_lock

    keep_running = threading.Event()
    worker_started = threading.Event()

    def _runaway():
        worker_started.set()
        keep_running.wait(10)

    # Call A: caller acquires, spawns, times out, records the wedge and holds.
    assert exec_lock.acquire_for_exec(timeout=1.0) is True
    worker = threading.Thread(target=_runaway, daemon=True, name="mcp-exec")
    worker.start()
    assert worker_started.wait(5)
    exec_lock.mark_wedged("execute_indigo_python", "exceeded 60s", thread=worker)

    try:
        # Call B: same thread. Must be refused, not waved through.
        assert exec_lock.acquire_for_exec(timeout=0.25) is False
        assert exec_lock.busy_error("run_script")["busy"] is True
    finally:
        keep_running.set()
        worker.join(5)


def test_wedge_clears_itself_once_the_worker_finishes():
    """A finished runaway must not leave the exec path refused for ever.

    The worker's own finally has restored the streams by then, so the record is
    stale — and the orphaned recursion level must be dropped, or the count would
    creep up by one per wedge and hold the lock for the plugin's lifetime.
    """
    from mcp_server.common import exec_lock

    done = threading.Event()
    worker = threading.Thread(target=done.wait, args=(10,), daemon=True)

    assert exec_lock.acquire_for_exec(timeout=1.0) is True
    worker.start()
    exec_lock.mark_wedged("run_script", "'Stuck.py' exceeded 120s", thread=worker)
    assert exec_lock.acquire_for_exec(timeout=0.25) is False

    done.set()
    worker.join(5)

    assert exec_lock.acquire_for_exec(timeout=1.0) is True
    assert exec_lock.wedged_info() is None
    exec_lock.release_after_exec()

    # Balanced: the lock is genuinely free, not held at a deeper recursion level.
    assert exec_lock.STDOUT_SWAP_LOCK.acquire(timeout=0) is True
    exec_lock.STDOUT_SWAP_LOCK.release()


def test_health_view_reports_worker_liveness_and_hides_the_thread():
    """/health must stay JSON-serialisable and say whether the run is still going."""
    from mcp_server.common import exec_lock

    done = threading.Event()
    worker = threading.Thread(target=done.wait, args=(10,), daemon=True)
    worker.start()
    exec_lock.mark_wedged("run_script", "'Stuck.py' exceeded 120s", thread=worker)

    info = exec_lock.wedged_info()
    assert "thread" not in info, "a Thread object cannot be serialised for /health"
    assert info["worker_alive"] is True

    done.set()
    worker.join(5)
    assert exec_lock.wedged_info()["worker_alive"] is False
