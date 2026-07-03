"""Shared lock for tools that reassign the PROCESS-GLOBAL sys.stdout/stderr.

execute_indigo_python (scripting_shell) and run_script (script_tools) both
capture output by swapping sys.stdout/sys.stderr for a StringIO and restoring
them in a finally. The MCP handler dispatches tools/call concurrently on IWS
threads, and Claude Code routinely fires parallel tool calls — so two overlapping
exec/run calls would interleave the swaps and one thread's finally would restore
stdout to the OTHER thread's (now dead) StringIO, permanently corrupting stdout
for the whole plugin process.

Both call sites acquire this single module-level lock around the swap so they
can never interleave. A reentrant lock is used so a script that itself calls
back into another exec path can't self-deadlock.
"""

import threading

STDOUT_SWAP_LOCK = threading.RLock()
