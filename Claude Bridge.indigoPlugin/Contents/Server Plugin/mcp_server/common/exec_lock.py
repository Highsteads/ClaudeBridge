#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    exec_lock.py
# Description: Background jobs for the two tools that swap the PROCESS-GLOBAL
#              sys.stdout/stderr (execute_indigo_python and run_script): one
#              run at a time, and a long run no longer holds the request thread.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026 (3.0 rewrite; the lock itself dates from 25-07-2026)
# Version:     2.0

"""
Why these two tools are serialised
----------------------------------
Both capture output by swapping sys.stdout / sys.stderr for a StringIO. That
swap is global to the whole plugin process, so two overlapping runs would
interleave, and one run's restore would point stdout at the other's dead
buffer. So exactly one run may hold the capture at a time — the "slot" below.

Why they run as jobs (3.0)
--------------------------
Indigo dispatches every IWS request and every plugin callback on the plugin's
one MainThread, and the web server shares it. Measured 23-09-2026: while a
10-second execute_indigo_python ran, a static /public request stalled 9.9 s —
a long exec froze every dashboard. 85 of 1,576 calls in ten weeks ran longer
than 10 s.

So the code runs in a worker thread and the caller waits at most wait_seconds
(default 8, clamped to 0-55). A run that finishes in time is returned exactly
as before. One that does not is left running in the background and the caller
gets {"status": "running", "job_id": ...} at once, which frees the request
thread. Calling the tool again with that job_id waits a little longer and then
hands back the finished result (and forgets the job) or the running status.

The rules
---------
* The slot is held from start until the worker FINISHES. A second run while it
  is held is refused at once, naming the running job and how long it has run —
  never queued, never blocking.
* The slot is released by the worker itself, as its last act. Nothing waits on
  a lock, so the old failure — every later call blocking its whole budget on a
  lock an abandoned worker would never release — cannot happen.
* A finished result is kept RESULT_TTL_SECONDS (10 minutes) for collection and
  then dropped. It does not hold the slot: the capture was restored when the
  worker finished, so a new run is safe as soon as the old one ends.
* A worker still running after HARD_CEILING_SECONDS (30 minutes) is reported as
  wedged. Python cannot kill a thread, so it keeps the slot (its buffer is still
  live) and the advice is a plugin reload from the Indigo Plugins menu.
* The worker restores each stream only if it is still the one it installed
  (see the handlers), so a late finisher cannot clobber a healthy stdout.
"""

import secrets
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

DEFAULT_WAIT_SECONDS = 8
MAX_WAIT_SECONDS = 55
RESULT_TTL_SECONDS = 600
HARD_CEILING_SECONDS = 1800

RELOAD_ADVICE = ("Python cannot kill a running thread, so clearing this needs a plugin "
                 "reload from the Indigo Plugins menu (do NOT restart Claude Bridge from "
                 "an MCP tool).")

_now = time.monotonic   # indirection so tests can move the clock


class Job:
    """One background run of execute_indigo_python or run_script."""

    def __init__(self, tool: str, label: str):
        self.job_id = secrets.token_hex(4)
        self.tool = tool
        self.label = label
        self.started = _now()
        self.started_local = time.strftime("%Y-%m-%d %H:%M:%S")
        self.thread: Optional[threading.Thread] = None
        self.done = threading.Event()
        self.result: Optional[Dict[str, Any]] = None
        self.finished_at: Optional[float] = None

    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else _now()
        return round(end - self.started, 1)

    def describe(self) -> str:
        return f"{self.tool}" + (f" {self.label}" if self.label else "")


_lock = threading.Lock()
_running: Optional[Job] = None
_finished: Dict[str, Job] = {}


def clamp_wait(value: Any, default: float = DEFAULT_WAIT_SECONDS) -> float:
    """wait_seconds as a number in 0..MAX_WAIT_SECONDS; junk means the default."""
    if value is None or isinstance(value, bool):
        return float(default)
    try:
        return max(0.0, min(float(value), float(MAX_WAIT_SECONDS)))
    except (TypeError, ValueError):
        return float(default)


def _sweep_locked() -> None:
    """Drop finished results nobody collected within RESULT_TTL_SECONDS."""
    now = _now()
    for job_id, job in list(_finished.items()):
        if job.finished_at is not None and now - job.finished_at > RESULT_TTL_SECONDS:
            del _finished[job_id]


def _is_wedged(job: Job) -> bool:
    return not job.done.is_set() and (_now() - job.started) > HARD_CEILING_SECONDS


def _busy_locked(tool: str) -> Dict[str, Any]:
    job = _running
    elapsed = job.elapsed()
    reply: Dict[str, Any] = {
        "success": False,
        "busy": True,
        "running_job_id": job.job_id,
        "elapsed_seconds": elapsed,
    }
    if _is_wedged(job):
        reply["wedged"] = True
        reply["wedged_since"] = job.started_local
        reply["error"] = (
            f"{tool} did NOT run — your code was not executed. Job {job.job_id} "
            f"({job.describe()}) started at {job.started_local} and is still running after "
            f"{int(elapsed)}s, so it is treated as wedged and keeps the output capture. "
            + RELOAD_ADVICE)
    else:
        reply["error"] = (
            f"{tool} did NOT run — your code was not executed. Job {job.job_id} "
            f"({job.describe()}) has been running for {int(elapsed)}s and holds the output "
            f"capture, which only one run can use at a time. Collect it with "
            f"{job.tool}(job_id='{job.job_id}'), then try again.")
    return reply


def busy_error(tool: str) -> Optional[Dict[str, Any]]:
    """The refusal a new run gets while another holds the slot, else None."""
    with _lock:
        return _busy_locked(tool) if _running is not None else None


def start(tool: str, label: str,
          work: Callable[[], Dict[str, Any]]) -> Tuple[Optional[Job], Optional[Dict[str, Any]]]:
    """Claim the slot and run work() in a worker thread.

    Returns (job, None), or (None, refusal) when another run holds the slot.
    work() returns the tool's finished result dict; an exception it raises is
    turned into a failure result rather than lost with the thread.
    """
    global _running
    with _lock:
        _sweep_locked()
        if _running is not None:
            return None, _busy_locked(tool)
        job = Job(tool, label)
        _running = job

    def _run():
        global _running
        try:
            result = work()
        except BaseException as exc:          # noqa: BLE001 — a thread must not die silently
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        with _lock:
            job.result = result
            job.finished_at = _now()
            if _running is job:
                _running = None
            _finished[job.job_id] = job
        job.done.set()

    job.thread = threading.Thread(target=_run, daemon=True, name=f"mcp-{tool}-{job.job_id}")
    try:
        job.thread.start()
    except Exception:
        with _lock:
            if _running is job:
                _running = None
        raise
    return job, None


def _report(job: Job) -> Dict[str, Any]:
    """The finished result (forgetting the job), or where it has got to."""
    with _lock:
        if job.done.is_set():
            _finished.pop(job.job_id, None)
            return job.result
        elapsed = job.elapsed()
        if _is_wedged(job):
            return {
                "success": False,
                "timed_out": True,
                "wedged": True,
                "job_id": job.job_id,
                "elapsed_seconds": elapsed,
                "wedged_since": job.started_local,
                "error": (f"Job {job.job_id} ({job.describe()}) has run for {int(elapsed)}s, "
                          f"past the {HARD_CEILING_SECONDS // 60}-minute ceiling, and is "
                          f"treated as wedged. It still holds the output capture, so further "
                          f"execute_indigo_python / run_script calls are refused. "
                          + RELOAD_ADVICE),
            }
        return {
            "status": "running",
            "job_id": job.job_id,
            "elapsed_seconds": elapsed,
            "note": (f"call {job.tool} again with job_id='{job.job_id}' to collect; the "
                     f"result is kept for {RESULT_TTL_SECONDS // 60} minutes after it finishes"),
        }


def wait(job: Job, wait_seconds: Any = DEFAULT_WAIT_SECONDS) -> Dict[str, Any]:
    """Wait up to wait_seconds for the job, then report it."""
    job.done.wait(clamp_wait(wait_seconds))
    return _report(job)


def collect(tool: str, job_id: str, wait_seconds: Any = DEFAULT_WAIT_SECONDS) -> Dict[str, Any]:
    """Wait on a job started earlier and hand back its result or status."""
    with _lock:
        _sweep_locked()
        job = _running if (_running is not None and _running.job_id == job_id) \
            else _finished.get(job_id)
    if job is None:
        return {"success": False,
                "error": (f"No job '{job_id}' — it is unknown, was already collected, or its "
                          f"result expired (results are kept for "
                          f"{RESULT_TTL_SECONDS // 60} minutes after the run finishes).")}
    if job.tool != tool:
        return {"success": False,
                "error": (f"Job '{job_id}' was started by {job.tool}; collect it with "
                          f"{job.tool}(job_id='{job_id}').")}
    return wait(job, wait_seconds)


def wedged_info() -> Optional[Dict[str, Any]]:
    """Details of a run past the hard ceiling, or None. Read by /health."""
    with _lock:
        job = _running
        if job is None or not _is_wedged(job):
            return None
        return {"tool": job.tool, "job_id": job.job_id, "detail": job.label,
                "since_local": job.started_local, "elapsed_seconds": job.elapsed(),
                "worker_alive": bool(job.thread and job.thread.is_alive())}


def status() -> Dict[str, Any]:
    """The whole picture for /health: what is running and what awaits collection."""
    with _lock:
        _sweep_locked()
        running = None
        if _running is not None:
            running = {"job_id": _running.job_id, "tool": _running.tool,
                       "detail": _running.label, "elapsed_seconds": _running.elapsed(),
                       "wedged": _is_wedged(_running)}
        return {"running": running, "uncollected": sorted(_finished)}


def reset_for_tests() -> None:
    """Forget every job. Only for tests, and only once their workers have ended."""
    global _running
    with _lock:
        _running = None
        _finished.clear()
