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
    lock is left held and the wedge is RECORDED, with the abandoned thread.

WHY THE WEDGE RECORD — NOT THE LOCK — IS WHAT REFUSES THE NEXT CALL
------------------------------------------------------------------
A reentrant lock is used so a nested exec on the same thread can't self-deadlock.
But that reentrancy also means a held lock CANNOT refuse the next caller: every
tool call arrives on the same MainThread that wedged it, and an RLock re-acquired
by its owning thread succeeds instantly whatever the timeout. Relying on acquire()
to block was therefore a no-op — the refusal never fired, a second run swapped
stdout underneath the still-live worker, and the plugin's real stdout could be
lost until a reload.

So acquire_for_exec() consults the WEDGE RECORD first:
  * wedged and the recorded worker still alive  -> refuse (busy_error).
  * wedged but the worker has since finished    -> its guarded finally has already
    restored the streams (or safely declined to), so the wedge is stale: drop the
    orphaned recursion level, clear the record, and carry on.
This is also why the recursion level must be released explicitly — otherwise each
wedge-and-recover cycle would leave the count one higher for ever.
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
    """Try to take the stdout-swap lock. False means a previous exec still holds it.

    The wedge record is checked BEFORE the lock, because the lock alone cannot
    refuse anything: dispatch is single-threaded, so the next caller is the same
    thread that wedged it and a reentrant acquire always succeeds. See the module
    docstring.
    """
    with _wedge_lock:
        if _wedged is not None:
            worker = _wedged.get("thread")
            if worker is None or worker.is_alive():
                # Still running — refuse. A record with NO thread is refused too:
                # liveness cannot be tested, and guessing "it has probably
                # finished" risks the stdout corruption this whole module exists
                # to prevent. Both real call sites record the thread, so this
                # arm only covers a hand-made record; clear_wedge() releases it.
                return False
            # The worker has since finished, so its guarded finally has already
            # restored the streams (or safely declined to). The record is stale.
            _release_orphaned_level()
            _clear_wedge_locked()
    return STDOUT_SWAP_LOCK.acquire(timeout=timeout)


def _release_orphaned_level() -> None:
    """Drop the recursion level left behind by a wedged-then-finished worker.

    Only ever called with a stale wedge record, i.e. the caller that abandoned the
    worker never released. Without this the count creeps up by one per wedge and
    the lock is held for the rest of the plugin's life.
    """
    try:
        STDOUT_SWAP_LOCK.release()
    except RuntimeError:
        # Not held by this thread (or not held at all) — nothing orphaned.
        pass


def release_after_exec() -> None:
    """Release the lock after a worker completed normally."""
    try:
        STDOUT_SWAP_LOCK.release()
    except RuntimeError:
        # Not held by this thread — nothing to release; never mask the real error.
        pass


def mark_wedged(tool: str, detail: str = "", thread=None) -> None:
    """Record that a worker was abandoned and the lock is deliberately held.

    ``thread`` is the abandoned worker. It is what later calls test to tell a run
    that is still going from one that has since finished — without it the wedge
    would look permanent and every later exec would be refused for ever.
    """
    global _wedged
    with _wedge_lock:
        _wedged = {
            "tool":         tool,
            "detail":       detail,
            "since_epoch":  time.time(),
            "since_local":  time.strftime("%Y-%m-%d %H:%M:%S"),
            "thread":       thread,
        }


def wedged_info():
    """Return the wedge record, or None if the exec path is healthy.

    The Thread object is stripped (it does not serialise for /health) and replaced
    with ``worker_alive``, which is the part a reader actually wants: a wedge whose
    worker has finished no longer blocks anything.
    """
    with _wedge_lock:
        if not _wedged:
            return None
        info = {k: v for k, v in _wedged.items() if k != "thread"}
        worker = _wedged.get("thread")
        info["worker_alive"] = bool(worker is not None and worker.is_alive())
        return info


def clear_wedge() -> None:
    """Forget a recorded wedge (used by the Clear Cache / reset menu paths)."""
    with _wedge_lock:
        _clear_wedge_locked()


def _clear_wedge_locked() -> None:
    """Clear the record. Caller must already hold _wedge_lock."""
    global _wedged
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
