"""Serialisation for the tools that reassign the PROCESS-GLOBAL sys.stdout/stderr.

execute_indigo_python (scripting_shell) and run_script (script_tools) capture
output by swapping sys.stdout/sys.stderr for a StringIO. That swap is global to
the whole plugin process, so two overlapping runs would interleave and one
run's restore would point stdout at the other's dead StringIO.

WHY THE LOCK IS STILL NEEDED, GIVEN DISPATCH IS SINGLE-THREADED
---------------------------------------------------------------
Indigo dispatches every plugin callback AND every IWS endpoint handler on the
plugin's MainThread — measured live with threading.enumerate(). So two tool
calls never overlap, and the original justification for this lock ("the MCP
handler dispatches tools/call concurrently on IWS threads") was simply wrong.

The lock earns its place for a different reason: both tools run the user's code
in a WORKER thread and join with a timeout, so a runaway script leaves a second
thread alive after the handler has returned. That abandoned worker is a genuine
concurrent writer to sys.stdout.

WHAT WENT WRONG BEFORE
----------------------
The worker acquired the lock itself and released it in a finally. When the join
expired the worker kept running, so the lock was never released and stdout
stayed pointed at an abandoned StringIO. Every later exec call then blocked on
acquire() for its full 60s/120s budget and returned a timeout error about a
script that had never run — one runaway script turned every subsequent call into
a full-plugin freeze with a misleading message.

THE SHAPE THAT FIXES IT
-----------------------
  * The CALLER acquires, with a short timeout, BEFORE spawning the worker. If it
    can't get the lock, it returns immediately and honestly instead of freezing.
  * The worker never acquires. Its finally restores the streams only if they are
    still the ones it installed, so a late-finishing abandoned worker cannot
    clobber a healthy stdout.
  * The caller releases only when the worker actually finished. On timeout the
    lock is deliberately left held and the wedge is recorded, which is what makes
    every later call fail fast rather than slow.

A reentrant lock is used so a nested exec on the same thread can't self-deadlock.
"""

import threading
import time

STDOUT_SWAP_LOCK = threading.RLock()

# How long a caller waits for a previous exec to finish before giving up. Short
# on purpose: the whole point is to fail fast rather than freeze the plugin.
LOCK_WAIT_SECONDS = 2.0

# Set when a worker is abandoned mid-run and the lock is left held. Read by the
# health endpoint and by the error message every later exec call returns.
_wedge_lock = threading.Lock()
_wedged = None


def acquire_for_exec(timeout: float = LOCK_WAIT_SECONDS) -> bool:
    """Try to take the stdout-swap lock. False means a previous exec still holds it."""
    return STDOUT_SWAP_LOCK.acquire(timeout=timeout)


def release_after_exec() -> None:
    """Release the lock after a worker completed normally."""
    try:
        STDOUT_SWAP_LOCK.release()
    except RuntimeError:
        # Not held by this thread — nothing to release; never mask the real error.
        pass


def mark_wedged(tool: str, detail: str = "") -> None:
    """Record that a worker was abandoned and the lock is deliberately held."""
    global _wedged
    with _wedge_lock:
        _wedged = {
            "tool":         tool,
            "detail":       detail,
            "since_epoch":  time.time(),
            "since_local":  time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def wedged_info():
    """Return the wedge record, or None if the exec path is healthy."""
    with _wedge_lock:
        return dict(_wedged) if _wedged else None


def clear_wedge() -> None:
    """Forget a recorded wedge (used by the Clear Cache / reset menu paths)."""
    global _wedged
    with _wedge_lock:
        _wedged = None


def busy_error(tool: str) -> dict:
    """The standard result for 'a previous exec is still running'.

    Names the stuck run and its start time so the message can't be mistaken for
    'YOUR script was too slow', which is what the old code wrongly reported.
    """
    info = wedged_info()
    if info:
        detail = (f"A previous {info['tool']} call was abandoned at "
                  f"{info['since_local']} and is still running")
        if info.get("detail"):
            detail += f" ({info['detail']})"
    else:
        detail = "Another script is running right now"
    return {
        "success": False,
        "busy":    True,
        "error": (
            f"{detail}. {tool} did NOT run — your code was not executed. Python "
            f"cannot kill a running thread, so clearing this needs a plugin reload "
            f"from the Indigo Plugins menu (do NOT restart Claude Bridge from an "
            f"MCP tool)."
        ),
        "wedged_since": (info or {}).get("since_local"),
    }
