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

        captured_out = io.StringIO()
        captured_err = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err

        ns: Dict[str, Any] = {
            "__name__": "__mcp_exec__",
            "indigo":   indigo,
        }

        error_msg: Optional[str] = None
        tb_text:   Optional[str] = None
        value_repr: Optional[str] = None

        try:
            try:
                if mode == "eval":
                    value = eval(compile(code, "<mcp_exec>", "eval"), ns)  # noqa: S307
                    try:
                        value_repr = repr(value)
                    except Exception as repr_exc:
                        value_repr = f"<repr failed: {repr_exc}>"
                else:
                    exec(compile(code, "<mcp_exec>", "exec"), ns)  # noqa: S102
            except SystemExit:
                pass  # treat sys.exit() as normal completion
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                tb_text   = traceback.format_exc()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

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
                ["osascript", "-e", script],
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
