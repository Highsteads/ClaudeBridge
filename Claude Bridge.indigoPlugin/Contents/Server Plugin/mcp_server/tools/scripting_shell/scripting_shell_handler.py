"""
Scripting shell handler for ClaudeBridge MCP server.

Tools:
  - execute_indigo_python    : run arbitrary Python in this plugin's Indigo context
                               (in-process exec, captures stdout/stderr, returns value
                               of last expression if 'eval' mode requested)
  - execute_plugin_menu_item : invoke a plugin menu item via AppleScript GUI scripting
                               (only viable while the Indigo client GUI is running)

execute_indigo_python runs in-process via exec() — the same pattern used by
script_tools.run_script — so it has full access to `indigo.*` without IPC.
Scope: ADMIN (arbitrary code execution).

execute_plugin_menu_item uses macOS System Events to click a menu item under
Plugins -> <Plugin Name>. This is the only known way to fire a third-party
plugin's <MenuItem> callback from outside that plugin, since the public
indigo.server.getPlugin() wrapper exposes no menu API.
Scope: ADMIN.
"""

import io
import logging
import os
import subprocess
import sys
import traceback
from typing import Any, Dict, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

# Best-effort wall-clock limit for a single execute_indigo_python call. A runaway
# script past this frees the IWS thread with a timeout error (the worker thread is
# orphaned — Python can't kill a thread — but the server keeps serving). Generous
# so normal sub-second usage is never affected.
_EXEC_TIMEOUT_SECONDS = 60

# Ceiling for execute_plugin_menu_item's caller-supplied timeout. Dispatch is
# single-threaded, so this subprocess.run blocks EVERY other tool call and every
# device callback for its whole duration — an uncapped caller value (timeout=3600)
# was a one-hour freeze of the entire plugin. The AppleScript also activates the
# Indigo GUI, so a modal dialog or a permissions prompt holds it for the full
# budget rather than erroring.
_MENU_ITEM_TIMEOUT_MAX     = 60
_MENU_ITEM_TIMEOUT_DEFAULT = 15

# Absolute path — the plugin host's PATH is not the shell's, so a bare binary
# name can raise FileNotFoundError. Fall back to the bare name only if the
# expected location is missing. (Matches _bin() in system_tools_handler.)
_OSASCRIPT = ("/usr/bin/osascript" if os.path.exists("/usr/bin/osascript")
              else "osascript")


# The name Claude Bridge shows under the Indigo client's Plugins menu
# (CFBundleDisplayName), plus the spellings a caller might plausibly send.
_SELF_MENU_NAMES = {"claude bridge", "claudebridge", "claude-bridge"}


def _is_self_plugin_name(name: str) -> bool:
    """True if this menu name refers to Claude Bridge itself.

    Compared loosely on purpose: the caller types a display name rather than a
    bundle id, so exact matching would let a near-miss through and a near-miss
    still kills the session running the tool.
    """
    return (name or "").strip().lower() in _SELF_MENU_NAMES


def _indigo_app_name() -> str:
    """
    Derive the running Indigo .app name (e.g. 'Indigo 2025.2') from the
    install folder path.  Falls back to 'Indigo' if it can't be parsed.
    """
    try:
        base = indigo.server.getInstallFolderPath()
        # Path ends with "...Perceptive Automation/Indigo 2025.2"
        leaf = base.rstrip("/").split("/")[-1]
        return leaf if leaf.startswith("Indigo") else "Indigo"
    except Exception:
        return "Indigo"


class ScriptingShellHandler(BaseToolHandler):
    """Arbitrary-Python and plugin-menu-item execution."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="scripting_shell", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # execute_indigo_python
    # ────────────────────────────────────────────────────────────────────────

    def execute_indigo_python(
        self,
        code: str,
        mode: str = "exec",
    ) -> Dict[str, Any]:
        """
        Run Python code in the plugin's Indigo Python context.

        mode='exec' (default): run as a statement block. Use print() to surface
            output. Result includes captured stdout/stderr.
        mode='eval': evaluate a single expression and include its repr in
            'value'. Raises if code is multi-line or contains statements.
        """
        self.log_incoming_request(
            "execute_indigo_python",
            {"code_len": len(code or ""), "mode": mode},
        )
        if not code or not code.strip():
            return {"success": False, "error": "code is required"}
        if mode not in ("exec", "eval"):
            return {"success": False,
                    "error": f"mode must be 'exec' or 'eval', got {mode!r}"}

        import threading
        from ...common import exec_lock

        # Take the stdout-swap lock BEFORE spawning. If a previous run was
        # abandoned mid-flight it still holds the lock, and waiting the full
        # 60s budget for it would freeze the whole plugin (dispatch is
        # single-threaded) only to return a misleading "your script timed out".
        # Fail fast and say what is actually wrong instead.
        if not exec_lock.acquire_for_exec():
            self.log_tool_outcome("execute_indigo_python", False,
                                  "refused — previous exec still holds the stdout lock")
            return exec_lock.busy_error("execute_indigo_python")

        captured_out = io.StringIO()
        captured_err = io.StringIO()

        ns: Dict[str, Any] = {
            "__name__": "__mcp_exec__",
            "indigo":   indigo,
        }

        res: Dict[str, Any] = {"error_msg": None, "tb_text": None, "value_repr": None}

        # Run the exec in a worker thread and join with a timeout so a runaway
        # script (e.g. an infinite loop) does NOT wedge the request thread
        # forever — the handler returns a timeout error and frees the thread. The
        # fast path (normal sub-second code) is unaffected.
        #
        # The worker does NOT touch the lock — the caller already owns it (see
        # common/exec_lock.py). Its finally restores the streams only if they are
        # still the ones it installed, so a worker that finishes long after being
        # abandoned cannot point stdout at its own dead buffer.
        def _worker():
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = captured_out, captured_err
            try:
                try:
                    if mode == "eval":
                        value = eval(compile(code, "<mcp_exec>", "eval"), ns)  # noqa: S307
                        try:
                            res["value_repr"] = repr(value)
                        except Exception as repr_exc:
                            res["value_repr"] = f"<repr failed: {repr_exc}>"
                    else:
                        exec(compile(code, "<mcp_exec>", "exec"), ns)  # noqa: S102
                except SystemExit:
                    pass  # treat sys.exit() as normal completion
                except Exception as exc:
                    res["error_msg"] = f"{type(exc).__name__}: {exc}"
                    res["tb_text"]   = traceback.format_exc()
            finally:
                if sys.stdout is captured_out:
                    sys.stdout = old_stdout
                if sys.stderr is captured_err:
                    sys.stderr = old_stderr

        _t = threading.Thread(target=_worker, daemon=True, name="mcp-exec")
        try:
            _t.start()
        except Exception as exc:
            # Never leak the lock on a failure to spawn — nothing is running, so
            # the next call must not be told the exec path is wedged.
            exec_lock.release_after_exec()
            return self.handle_exception(exc, "execute_indigo_python")
        _t.join(timeout=_EXEC_TIMEOUT_SECONDS)
        if _t.is_alive():
            # Deliberately do NOT release the lock: the worker is still writing
            # to captured_out, and a later run must not swap stdout underneath
            # it. Record the wedge so every later call fails fast with a message
            # that names THIS run rather than blaming the next caller's script.
            exec_lock.mark_wedged("execute_indigo_python",
                                  f"exceeded {_EXEC_TIMEOUT_SECONDS}s",
                                  thread=_t)
            self.log_tool_outcome("execute_indigo_python", False,
                                  f"timed out after {_EXEC_TIMEOUT_SECONDS}s")
            return {
                "success": False, "mode": mode, "timed_out": True,
                "error": (f"Execution exceeded the {_EXEC_TIMEOUT_SECONDS}s limit and was left "
                          "running in the background so the request thread could be freed. "
                          "Until it finishes, further execute_indigo_python / run_script calls "
                          "are refused immediately rather than queued. A genuinely infinite "
                          "script needs a plugin reload from the Indigo Plugins menu."),
                "stdout": captured_out.getvalue()[:8000],
            }
        exec_lock.release_after_exec()

        error_msg  = res["error_msg"]
        tb_text    = res["tb_text"]
        value_repr = res["value_repr"]
        out = captured_out.getvalue()
        err = captured_err.getvalue()

        result: Dict[str, Any] = {
            "success": error_msg is None,
            "mode":    mode,
            "stdout":  out[:8000] if out else "",
            "stderr":  err[:4000] if err else "",
        }
        if mode == "eval" and value_repr is not None:
            result["value"] = value_repr[:4000]
        if error_msg:
            result["error"]     = error_msg
            result["traceback"] = (tb_text or "")[:4000]

        self.log_tool_outcome(
            "execute_indigo_python",
            result["success"],
            f"mode={mode}" + (f" — ERROR: {error_msg}" if error_msg else ""),
        )
        return result

    # ────────────────────────────────────────────────────────────────────────
    # execute_plugin_menu_item
    # ────────────────────────────────────────────────────────────────────────

    def execute_plugin_menu_item(
        self,
        plugin_name: str,
        menu_item_name: str,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """
        Click a plugin's menu item under the Indigo client's Plugins menu.

        Requires the Indigo GUI client to be running on this Mac.  System
        Events GUI-scripting permission must be granted to the process
        invoking osascript (Indigo, or whatever parent of the plugin host).

        plugin_name     — the name shown under Plugins menu (e.g.
                          "Zigbee2MQTT Bridge")
        menu_item_name  — the menu item to click (e.g.
                          "Refresh Device Capabilities")
        """
        self.log_incoming_request(
            "execute_plugin_menu_item",
            {"plugin_name": plugin_name, "menu_item_name": menu_item_name},
        )

        plugin_name    = (plugin_name or "").strip()
        menu_item_name = (menu_item_name or "").strip()
        if not plugin_name or not menu_item_name:
            return {"success": False,
                    "error": "plugin_name and menu_item_name are required"}

        # Self-restart guard. restart_plugin and plugin_refresh_deps both refuse
        # to restart Claude Bridge from inside its own MCP session (a live
        # attempt wedged it for 4m37s), but this tool could reach the same
        # outcome by clicking Claude Bridge's own Reload item — the guard has to
        # cover every route to the capability, not just the obvious two.
        if _is_self_plugin_name(plugin_name):
            return {
                "success": False,
                "error": (
                    "Refusing to click a Claude Bridge menu item from within its own "
                    "MCP session — reloading or reconfiguring the bridge kills the "
                    "session running this tool. Use the Indigo Plugins menu directly."
                ),
            }

        # Clamp the caller's timeout: this call blocks the whole plugin.
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = _MENU_ITEM_TIMEOUT_DEFAULT
        timeout = max(1, min(timeout, _MENU_ITEM_TIMEOUT_MAX))

        app = _indigo_app_name()

        # AppleScript escapes: double the embedded double-quotes.
        def _esc(s: str) -> str:
            return s.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "{_esc(app)}" to activate
        delay 0.4
        tell application "System Events"
            tell process "{_esc(app)}"
                click menu item "{_esc(menu_item_name)}" of menu of menu item "{_esc(plugin_name)}" of menu "Plugins" of menu bar 1
            end tell
        end tell
        '''

        try:
            proc = subprocess.run(
                [_OSASCRIPT, "-e", script],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"success": False,
                    "error": f"osascript timed out after {timeout}s"}
        except Exception as exc:
            return self.handle_exception(exc, "execute_plugin_menu_item")

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        ok     = proc.returncode == 0

        result: Dict[str, Any] = {
            "success":        ok,
            "app":            app,
            "plugin_name":    plugin_name,
            "menu_item_name": menu_item_name,
            "stdout":         stdout[:2000],
            "stderr":         stderr[:2000],
        }
        if not ok:
            result["error"] = stderr or f"osascript exited {proc.returncode}"

        self.log_tool_outcome(
            "execute_plugin_menu_item", ok,
            f"{plugin_name} -> {menu_item_name}"
            + (f" — ERROR: {stderr}" if not ok and stderr else ""),
        )
        return result
