"""
Scripting shell handler for ClaudeBridge MCP server.

Tools:
  - execute_indigo_python    : run arbitrary Python in this plugin's Indigo context
                               (in-process exec, captures stdout/stderr, returns value
                               of last expression if 'eval' mode requested)
  - execute_plugin_menu_item : invoke a plugin menu item via AppleScript GUI scripting
                               (only viable while the Indigo client GUI is running)
  - execute_client_menu_item : the same, for ANY menu in the client's menu bar, given
                               the full path (e.g. Interfaces -> Z-Wave -> Disable)

execute_indigo_python runs in-process via exec() — the same pattern used by
script_tools.run_script — so it has full access to `indigo.*` without IPC.
Scope: ADMIN (arbitrary code execution).

execute_plugin_menu_item uses macOS System Events to click a menu item under
Plugins -> <Plugin Name>. This is the only known way to fire a third-party
plugin's <MenuItem> callback from outside that plugin, since the public
indigo.server.getPlugin() wrapper exposes no menu API.
Scope: ADMIN.

execute_client_menu_item generalises that to the whole menu bar, because plenty
of the client's own commands have no API at all. The case that prompted it:
indigo.zwave exposes isEnabled() and nothing that sets it, so Interfaces ->
Z-Wave -> Disable is the ONLY way to make Indigo release the Z-Wave stick, which
is what every controller-backup run needs. Listing a menu is as useful as
clicking one, since several of these labels are toggles that rename themselves
(the Z-Wave item reads "Disable" when on and "Enable" when off), so a caller
that cannot read the menu cannot reliably drive it.
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

from ...common.output_clip import clip_into
from ..base_handler import BaseToolHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from ...adapters.indigo_data_provider import IndigoDataProvider

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


# Menu paths execute_client_menu_item refuses outright, matched case-insensitively
# on the whole path. Two kinds, and both are the same lesson as the self-restart
# guard below: a general tool reaches every route the specific ones were fenced off
# from, so the fences have to be rebuilt here rather than inherited.
#   * Quitting the client removes the GUI this tool works through, so it is the one
#     click that cannot be undone by another click.
#   * The Plugins -> Claude Bridge submenu is handled separately by
#     _path_targets_self(), which catches it at any depth.
_FORBIDDEN_PATH_PREFIXES = (
    ("file", "quit"),
)


def _is_forbidden_path(path) -> bool:
    """True for a path this tool will not click whatever the caller says."""
    lowered = tuple((seg or "").strip().lower() for seg in path)
    for bad in _FORBIDDEN_PATH_PREFIXES:
        if lowered[:len(bad)] == bad:
            return True
    # "Indigo 2025.2 -> Quit Indigo 2025.2" — the application menu, whose first
    # segment carries the version, so it cannot be matched literally.
    if len(lowered) >= 2 and lowered[0].startswith("indigo") and lowered[1].startswith("quit"):
        return True
    return False


def _path_targets_self(path) -> bool:
    """True if a menu path reaches Claude Bridge's own submenu, at any depth.

    execute_plugin_menu_item refuses plugin_name='Claude Bridge' because reloading
    the bridge kills the session running the tool. A full-path tool can reach the
    identical item as ("Plugins", "Claude Bridge", "Reload"), so the same refusal
    has to exist here — the guard has to cover every route to the capability.
    """
    return any(_is_self_plugin_name(seg) for seg in path)


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
        data_provider: "IndigoDataProvider",
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="scripting_shell", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # execute_indigo_python
    # ────────────────────────────────────────────────────────────────────────

    def execute_indigo_python(
        self,
        code: Optional[str] = None,
        mode: str = "exec",
        wait_seconds: Any = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run Python code in the plugin's Indigo Python context, as a job.

        mode='exec' (default): run as a statement block. Use print() to surface
            output. Result includes captured stdout/stderr.
        mode='eval': evaluate a single expression and include its repr in
            'value'. Raises if code is multi-line or contains statements.

        The run waits up to wait_seconds; one still going after that returns a
        job_id to collect it with (see common/exec_lock.py).
        """
        from ...common import exec_lock

        self.log_incoming_request(
            "execute_indigo_python",
            {"code_len": len(code or ""), "mode": mode, "job_id": job_id},
        )
        if job_id:
            if code:
                return {"success": False,
                        "error": "give either code (a new run) or job_id (collect one), not both"}
            return exec_lock.collect("execute_indigo_python", job_id, wait_seconds)
        if not code or not code.strip():
            return {"success": False, "error": "code is required"}
        if mode not in ("exec", "eval"):
            return {"success": False,
                    "error": f"mode must be 'exec' or 'eval', got {mode!r}"}

        def _work() -> Dict[str, Any]:
            captured_out = io.StringIO()
            captured_err = io.StringIO()
            ns: Dict[str, Any] = {"__name__": "__mcp_exec__", "indigo": indigo}
            error_msg = tb_text = value_repr = None
            # Restore each stream only if it is still the one installed here, so
            # a worker that finishes late cannot point stdout at its dead buffer.
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = captured_out, captured_err
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
                except SystemExit as exc:
                    # sys.exit() / sys.exit(0) is a clean finish; sys.exit(1)
                    # or sys.exit("message") is the code saying it failed.
                    if exc.code is not None and exc.code != 0:
                        error_msg = f"SystemExit: {exc.code}"
                except Exception as exc:
                    error_msg = f"{type(exc).__name__}: {exc}"
                    tb_text = traceback.format_exc()
            finally:
                if sys.stdout is captured_out:
                    sys.stdout = old_stdout
                if sys.stderr is captured_err:
                    sys.stderr = old_stderr

            result: Dict[str, Any] = {"success": error_msg is None, "mode": mode}
            clip_into(result, "stdout", captured_out.getvalue(), 8000)
            clip_into(result, "stderr", captured_err.getvalue(), 4000)
            if mode == "eval" and value_repr is not None:
                clip_into(result, "value", value_repr, 4000)
            if error_msg:
                result["error"] = error_msg
                # Keep the TAIL: the exception itself is the last line, and a deep
                # traceback cut from the front used to lose exactly that line.
                clip_into(result, "traceback", tb_text, 4000, keep="tail")
            # A failure here is the CALLER's code, returned in the reply — not a
            # fault in Claude Bridge — so it logs at DEBUG. At WARNING/ERROR it
            # filled the event log (and Log_Error_Watch) with red lines.
            self.log_tool_outcome(
                "execute_indigo_python", result["success"],
                f"mode={mode}" + (f" — ERROR: {error_msg}" if error_msg else ""),
                level=logging.DEBUG)
            return result

        job, busy = exec_lock.start("execute_indigo_python", f"mode={mode}", _work)
        if busy:
            self.log_tool_outcome("execute_indigo_python", False,
                                  f"refused — job {busy['running_job_id']} holds the capture",
                                  level=logging.DEBUG)
            return busy
        return exec_lock.wait(job, wait_seconds)

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
                # The plugin host's locale is ASCII, so without this the first
                # em-dash in a menu's output raised UnicodeDecodeError (2.27.1).
                encoding="utf-8", errors="replace",
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

    # ────────────────────────────────────────────────────────────────────────
    # execute_client_menu_item
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _menu_path_applescript(path) -> str:
        """The System Events reference for a menu path, innermost first.

        ["Interfaces", "Z-Wave", "Disable"] becomes

            menu item "Disable" of menu "Z-Wave" of menu item "Z-Wave"
            of menu "Interfaces" of menu bar item "Interfaces" of menu bar 1

        Every level below the first contributes a menu/menu-item pair, because a
        submenu and the item that opens it are two different objects with the
        same name.
        """
        def esc(text: str) -> str:
            return str(text).replace("\\", "\\\\").replace('"', '\\"')

        ref = f'menu item "{esc(path[-1])}"'
        for seg in reversed(path[1:-1]):
            ref += f' of menu "{esc(seg)}" of menu item "{esc(seg)}"'
        ref += f' of menu "{esc(path[0])}" of menu bar item "{esc(path[0])}" of menu bar 1'
        return ref

    def execute_client_menu_item(
        self,
        path,
        list_only: bool = False,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """
        Click (or list) any item in the Indigo client's own menu bar.

        path       — the full menu path, outermost first, e.g.
                     ["Interfaces", "Z-Wave", "Disable"]. For list_only the path
                     names the MENU to read rather than an item to click, e.g.
                     ["Interfaces", "Z-Wave"], or [] for the menu-bar titles.
        list_only  — read the menu instead of clicking it. Read-only, and the way
                     to find out what a toggling label currently says.

        Requires the Indigo GUI client to be running and System Events GUI
        scripting permission granted to whatever invokes osascript.
        """
        if isinstance(path, str):
            path = [path]
        path = [str(seg).strip() for seg in (path or []) if str(seg).strip()]

        self.log_incoming_request(
            "execute_client_menu_item",
            {"path": path, "list_only": bool(list_only)},
        )

        if not list_only and len(path) < 2:
            return {"success": False,
                    "error": ("path needs at least a menu and an item, e.g. "
                              "[\"Interfaces\", \"Z-Wave\", \"Disable\"]")}
        if list_only and len(path) > 2:
            return {"success": False,
                    "error": "list_only reads a menu or submenu, so path is at most two levels"}

        if not list_only and _path_targets_self(path):
            return {
                "success": False,
                "error": (
                    "Refusing to click a Claude Bridge menu item from within its own "
                    "MCP session — reloading or reconfiguring the bridge kills the "
                    "session running this tool. Use the Indigo Plugins menu directly."
                ),
            }
        if not list_only and _is_forbidden_path(path):
            return {
                "success": False,
                "error": (
                    "Refusing to quit the Indigo client: it is the GUI this tool works "
                    "through, so nothing could start it again from here."
                ),
            }

        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = _MENU_ITEM_TIMEOUT_DEFAULT
        timeout = max(1, min(timeout, _MENU_ITEM_TIMEOUT_MAX))

        app = _indigo_app_name()

        def esc(text: str) -> str:
            return str(text).replace("\\", "\\\\").replace('"', '\\"')

        if list_only:
            # Read-only, so the client is NOT activated — no window is taken from
            # whatever the user is doing just to enumerate a menu.
            if not path:
                target = "name of every menu bar item of menu bar 1"
            elif len(path) == 1:
                target = (f'name of every menu item of menu "{esc(path[0])}" '
                          f'of menu bar item "{esc(path[0])}" of menu bar 1')
            else:
                target = (f'name of every menu item of menu "{esc(path[1])}" '
                          f'of menu item "{esc(path[1])}" of menu "{esc(path[0])}" '
                          f'of menu bar item "{esc(path[0])}" of menu bar 1')
            # One title per line. The default list-to-text join uses ", ", which
            # also appears INSIDE titles ("Save, As..."), so splitting on it cut
            # one item into two. A menu title cannot contain a line feed.
            script = f'''
            tell application "System Events"
                tell process "{esc(app)}"
                    set theNames to {target}
                end tell
            end tell
            set out to {{}}
            repeat with n in theNames
                set v to contents of n
                if v is missing value then
                    set end of out to "missing value"
                else
                    set end of out to (v as text)
                end if
            end repeat
            set AppleScript's text item delimiters to linefeed
            return out as text
            '''
        else:
            script = f'''
            tell application "{esc(app)}" to activate
            delay 0.4
            tell application "System Events"
                tell process "{esc(app)}"
                    click {self._menu_path_applescript(path)}
                end tell
            end tell
            '''

        try:
            proc = subprocess.run(
                [_OSASCRIPT, "-e", script],
                capture_output=True, text=True, timeout=timeout,
                # The plugin host's locale is ASCII, so without this the first
                # em-dash in a menu's output raised UnicodeDecodeError (2.27.1).
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"success": False,
                    "error": f"osascript timed out after {timeout}s"}
        except Exception as exc:
            return self.handle_exception(exc, "execute_client_menu_item")

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        ok     = proc.returncode == 0

        result: Dict[str, Any] = {
            "success":   ok,
            "app":       app,
            "path":      path,
            "list_only": bool(list_only),
            "stdout":    stdout[:2000],
            "stderr":    stderr[:2000],
        }
        if list_only and ok:
            # One title per line (see the script above). A separator reads
            # "missing value", which is how a menu separator looks from here.
            result["items"] = [seg.strip() for seg in stdout.split("\n") if seg.strip()]
        if not ok:
            result["error"] = stderr or f"osascript exited {proc.returncode}"

        self.log_tool_outcome(
            "execute_client_menu_item", ok,
            ("listed " if list_only else "clicked ") + " -> ".join(path or ["(menu bar)"])
            + (f" — ERROR: {stderr}" if not ok and stderr else ""),
        )
        return result
