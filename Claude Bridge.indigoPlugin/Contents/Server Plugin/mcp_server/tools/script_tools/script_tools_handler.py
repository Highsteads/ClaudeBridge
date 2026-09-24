"""
Script tools handler for ClaudeBridge MCP server.

Provides read, write, create, run, and log access to the Indigo Scripts folders,
allowing Claude to inspect, debug, update, and execute automation scripts directly.

The active scripts folder is resolved at runtime:
  1. <PA base>/Python Scripts — primary location (preferred, ~35 scripts)
  2. <PA base>/Scripts        — secondary location (rarely used)

For reads, both folders are searched (Python Scripts first).

Tools:
  - read_script(name)               : return full content of a script
  - write_script(name, content)     : overwrite a script (auto-backup created)
  - create_script(name, content)    : create a new script (fails if exists) —
                                      both reached through the write_script tool
  - delete_script(name)             : move a script to the _backups/_archived subfolder
  - list_script_backups(name)       : list auto-backups for a script
  - run_script(name)                : execute a script in the Indigo Python context
  - log_message(message, level)     : write a message to the Indigo on-screen log
"""

import logging
import os
import re
import shutil
import stat as _stat
import tempfile
import traceback as _traceback
from datetime import datetime
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
from ...common.log_levels import resolve as resolve_level

BACKUP_DIR_NAME = "_backups"
MAX_BACKUPS_PER_SCRIPT = 5
NEW_SCRIPT_MODE = 0o644


def _backup_name_re(stem: str) -> "re.Pattern":
    """Matches ONLY "<stem>.<timestamp>.py", the names _make_backup writes.

    One pattern for pruning and listing: a plain startswith("<stem>.") also
    matches a SIBLING script whose name starts with this one plus a dot (e.g.
    'foo' would sweep up 'foo.bar' backups)."""
    return re.compile(r"^" + re.escape(stem) + r"\.\d{8}_\d{6}(?:_\d+)?\.py$")


def _script_stem(name: str) -> str:
    """'MyScript.py' -> 'MyScript'. Only a trailing .py goes: replace(".py", "")
    also cut it out of the MIDDLE of a name ('a.py_old.py' -> 'a_old')."""
    base = os.path.basename((name or "").strip())
    return base[:-3] if base.endswith(".py") else base


def _exit_failure(exc: SystemExit) -> Optional[str]:
    """None when sys.exit() meant success (no code, None or 0), else the
    failure text. sys.exit(1) and sys.exit("message") are failures, and used to
    be reported as a clean run."""
    code = exc.code
    if code is None or code == 0:
        return None
    return f"SystemExit: {code}"



def _scripts_dir() -> str:
    """
    Return the primary Indigo Python scripts folder (used for new writes).

    Resolution order:
      1. <PA base>/Python Scripts — primary location (~35 scripts, preferred)
      2. <PA base>/Scripts        — secondary / fallback
      3. <PA base>/Python Scripts — default if neither exists (created on first write)
    """
    pa_base        = os.path.dirname(indigo.server.getInstallFolderPath())
    python_scripts = os.path.join(pa_base, "Python Scripts")
    scripts        = os.path.join(pa_base, "Scripts")
    if os.path.isdir(python_scripts):
        return python_scripts
    if os.path.isdir(scripts):
        return scripts
    return python_scripts  # default — will be created on first write


def _all_scripts_dirs() -> list:
    """Return all script folders that exist, Python Scripts first."""
    pa_base        = os.path.dirname(indigo.server.getInstallFolderPath())
    python_scripts = os.path.join(pa_base, "Python Scripts")
    scripts        = os.path.join(pa_base, "Scripts")
    return [d for d in [python_scripts, scripts] if os.path.isdir(d)]


def _backup_dir() -> str:
    return os.path.join(_scripts_dir(), BACKUP_DIR_NAME)


def _resolve(name: str) -> str:
    """
    Return full path for a script name (adds .py if missing).

    The client-supplied name is forced to a flat basename so it can never
    traverse out of the script folders ('../../etc/foo', an absolute path, or a
    nested subdir all collapse to the leaf name), and the resolved real path is
    asserted to live inside one of the allowed folders as belt-and-braces
    (catches a symlink pointing outside). Searches Python Scripts first, then
    Scripts; falls back to the primary folder for new file paths.
    """
    # Strip directory components — defends against path traversal and
    # absolute-path injection from the MCP client.
    name = os.path.basename((name or "").strip())
    if not name or name in (".", ".."):
        raise ValueError("Invalid script name")
    if not name.endswith(".py"):
        name = name + ".py"

    allowed = [os.path.realpath(d) for d in (_all_scripts_dirs() + [_scripts_dir()])]

    def _contained(path: str) -> bool:
        full = os.path.realpath(path)
        return any(full == a or full.startswith(a + os.sep) for a in allowed)

    for folder in _all_scripts_dirs():
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate) and _contained(candidate):
            return candidate
    # Not found in any folder — return path in primary folder for creation
    target = os.path.join(_scripts_dir(), name)
    if not _contained(target):
        raise ValueError("Resolved script path escapes the scripts folder")
    return target


def _make_backup(script_path: str) -> Optional[str]:
    """
    Copy script_path to _backups/<name>.YYYYMMDD_HHMMSS.py.
    Prunes oldest backups beyond MAX_BACKUPS_PER_SCRIPT.
    Returns backup path or None on failure.
    """
    backup_dir = _backup_dir()
    os.makedirs(backup_dir, exist_ok=True)

    base = os.path.basename(script_path)          # e.g. MyScript.py
    stem = base[:-3]                               # e.g. MyScript
    # Microsecond precision so two writes in the same second cannot collide and
    # silently overwrite the earlier backup.
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = os.path.join(backup_dir, f"{stem}.{ts}.py")

    try:
        shutil.copy2(script_path, dest)
    except OSError:
        return None

    # Prune old backups for this script. Match ONLY "<stem>.<timestamp>.py" — a
    # plain startswith("<stem>.") also matches a SIBLING script whose name starts
    # with this one plus a dot (e.g. pruning 'foo' would sweep 'foo.bar' backups,
    # or delete the backup just created). Requiring a timestamp after the dot
    # confines the prune to this script's own backups.
    try:
        ts_re = _backup_name_re(stem)
        backups = sorted(
            [e.path for e in os.scandir(backup_dir) if ts_re.match(e.name)],
        )
        while len(backups) > MAX_BACKUPS_PER_SCRIPT:
            try:
                os.remove(backups.pop(0))
            except OSError:
                break
    except OSError:
        pass

    return dest


class ScriptToolsHandler(BaseToolHandler):
    """Handler for reading, writing, and managing Indigo Python scripts."""

    def __init__(
        self,
        data_provider: "IndigoDataProvider",
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="script_tools", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # read_script
    # ────────────────────────────────────────────────────────────────────────

    def read_script(self, name: str) -> Dict[str, Any]:
        """Return the full content of a Python script by name."""
        self.log_incoming_request("read_script", {"name": name})
        try:
            path = _resolve(name)
            if not os.path.isfile(path):
                return {"success": False,
                        "error": f"Script '{name}' not found at {path}"}
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            stat = os.stat(path)
            result = {
                "success":      True,
                "name":         os.path.basename(path),
                "path":         path,
                "scripts_dir":  _scripts_dir(),
                "size_kb":      round(stat.st_size / 1024, 1),
                "modified":     datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "lines":        content.count("\n") + 1,
                "content":      content,
            }
            self.log_tool_outcome("read_script", True,
                                  f"Read {result['lines']} lines from '{name}'")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "read_script")

    # ────────────────────────────────────────────────────────────────────────
    # write_script
    # ────────────────────────────────────────────────────────────────────────

    def write_script(self, name: str, content: str) -> Dict[str, Any]:
        """
        Overwrite an existing script with new content.
        A timestamped backup is created in _backups/ before writing.
        Fails if the script does not already exist — write_script(create=true) makes new ones.
        """
        self.log_incoming_request("write_script", {"name": name})
        try:
            path = _resolve(name)
            if not os.path.isfile(path):
                return {"success": False,
                        "error": (f"Script '{name}' does not exist. To create a new "
                                  f"script, call write_script with create=true.")}

            # Refuse to overwrite a live script if the pre-write backup failed —
            # the whole point of the auto-backup is to make this reversible. A
            # silent backup failure followed by a successful overwrite is
            # unrecoverable data loss.
            backup = _make_backup(path)
            if backup is None:
                msg = (f"Refusing to overwrite '{name}' — the pre-write backup "
                       f"failed (disk full or permissions?). No changes made.")
                self.log_tool_outcome("write_script", False, msg)
                return {"success": False, "error": msg}

            # Atomic write: stage to a temp file in the SAME directory, then
            # os.replace() so an interrupted write can never leave the live
            # script truncated. The confirmed backup is kept on any failure.
            tmp_path = None
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=os.path.dirname(path), prefix=".cb_write_", suffix=".tmp"
                )
                # mkstemp makes the file 0600, and os.replace keeps the temp
                # file's mode — so every write left the script readable by its
                # owner only. Carry the existing script's mode across.
                os.fchmod(fd, _stat.S_IMODE(os.stat(path).st_mode))
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.replace(tmp_path, path)
            except OSError as e:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                msg = (f"Write failed for '{name}': {e}. The original is intact; "
                       f"a backup was saved at {backup}.")
                self.log_tool_outcome("write_script", False, msg)
                return {"success": False, "error": msg}

            lines = content.count("\n") + 1
            result = {
                "success": True,
                "name":    os.path.basename(path),
                "path":    path,
                "lines":   lines,
                "backup":  backup,
                "message": f"Script '{name}' updated ({lines} lines). Backup: {backup}",
            }
            self.log_tool_outcome("write_script", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "write_script")

    # ────────────────────────────────────────────────────────────────────────
    # create_script
    # ────────────────────────────────────────────────────────────────────────

    def create_script(self, name: str, content: str) -> Dict[str, Any]:
        """
        Create a new Python script in the Indigo Scripts folder.
        Fails if a script with that name already exists.
        """
        self.log_incoming_request("create_script", {"name": name})
        try:
            path = _resolve(name)
            if os.path.isfile(path):
                return {"success": False,
                        "error": (f"Script '{name}' already exists. To update it, "
                                  f"call write_script without create (a backup is kept).")}

            os.makedirs(os.path.dirname(path), exist_ok=True)
            # "x" fails if the file appeared since the check above, rather than
            # overwriting a script someone else has just written.
            try:
                with open(path, "x", encoding="utf-8") as fh:
                    os.fchmod(fh.fileno(), NEW_SCRIPT_MODE)
                    fh.write(content)
            except FileExistsError:
                return {"success": False,
                        "error": (f"Script '{name}' already exists. To update it, "
                                  f"call write_script without create (a backup is kept).")}

            lines = content.count("\n") + 1
            result = {
                "success": True,
                "name":    os.path.basename(path),
                "path":    path,
                "lines":   lines,
                "message": f"Script '{name}' created ({lines} lines)",
            }
            self.log_tool_outcome("create_script", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "create_script")

    # ────────────────────────────────────────────────────────────────────────
    # delete_script
    # ────────────────────────────────────────────────────────────────────────

    def delete_script(self, name: str) -> Dict[str, Any]:
        """
        Safely archive a script by moving it to _backups/_archived/.
        Does not permanently delete — can be manually recovered.
        """
        self.log_incoming_request("delete_script", {"name": name})
        try:
            path = _resolve(name)
            if not os.path.isfile(path):
                return {"success": False,
                        "error": f"Script '{name}' not found"}

            archive_dir = os.path.join(_backup_dir(), "_archived")
            os.makedirs(archive_dir, exist_ok=True)
            dest = os.path.join(archive_dir, os.path.basename(path))
            # Avoid overwriting existing archive
            if os.path.exists(dest):
                ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = os.path.basename(path)[:-3]
                dest = os.path.join(archive_dir, f"{stem}.{ts}.py")

            shutil.move(path, dest)
            result = {
                "success":  True,
                "name":     os.path.basename(path),
                "archived": dest,
                "message":  f"Script '{name}' archived to {dest}",
            }
            self.log_tool_outcome("delete_script", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "delete_script")

    # ────────────────────────────────────────────────────────────────────────
    # list_script_backups
    # ────────────────────────────────────────────────────────────────────────

    # ────────────────────────────────────────────────────────────────────────
    # run_script
    # ────────────────────────────────────────────────────────────────────────

    def run_script(self, name: Optional[str] = None, wait_seconds: Any = None,
                   job_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a Python script in the Indigo Python context, as a job.

        The script is looked up in Python Scripts (then Scripts) and executed
        via exec() with the `indigo` module pre-injected into globals — bare
        references like `indigo.devices.iter(...)` work without an explicit
        `import indigo`, matching Indigo's own GUI action runner. stdout and
        stderr are captured. The call waits up to wait_seconds; a script still
        running after that returns a job_id to collect it with (see
        common/exec_lock.py).
        """
        from ...common import exec_lock

        self.log_incoming_request("run_script", {"name": name, "job_id": job_id})
        try:
            if job_id:
                if name:
                    return {"success": False,
                            "error": "give either name (a new run) or job_id (collect one), not both"}
                return exec_lock.collect("run_script", job_id, wait_seconds)
            if not name:
                return {"success": False, "error": "name is required"}
            path = _resolve(name)
            if not os.path.isfile(path):
                return {"success": False,
                        "error": f"Script '{name}' not found at {path}"}

            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()

            import io
            import sys as _sys

            def _work() -> Dict[str, Any]:
                captured_out = io.StringIO()
                captured_err = io.StringIO()
                error_msg = tb_text = None
                # Restore each stream only if it is still the one installed
                # here, so a late finisher cannot clobber a healthy stdout.
                old_stdout, old_stderr = _sys.stdout, _sys.stderr
                _sys.stdout, _sys.stderr = captured_out, captured_err
                try:
                    code = compile(source, path, "exec")
                    ns = {"__file__": path, "__name__": "__main__", "indigo": indigo}
                    try:
                        exec(code, ns)  # noqa: S102
                    except SystemExit as exc:
                        # sys.exit() / sys.exit(0) is a clean finish; any other
                        # code is the script saying it failed.
                        error_msg = _exit_failure(exc)
                    except Exception as exc:
                        # Type included: a KeyError used to arrive as just 'foo'.
                        error_msg = f"{type(exc).__name__}: {exc}"
                        tb_text = _traceback.format_exc()
                except SyntaxError as exc:
                    error_msg = f"{type(exc).__name__}: {exc}"
                    tb_text = _traceback.format_exc()
                finally:
                    if _sys.stdout is captured_out:
                        _sys.stdout = old_stdout
                    if _sys.stderr is captured_err:
                        _sys.stderr = old_stderr

                result = {"success": error_msg is None,
                          "name": os.path.basename(path), "path": path}
                clip_into(result, "stdout", captured_out.getvalue(), 4000)
                clip_into(result, "stderr", captured_err.getvalue(), 2000)
                if error_msg:
                    result["error"] = error_msg
                    clip_into(result, "traceback", tb_text, 4000, keep="tail")
                # A failure here is the SCRIPT's, reported to the caller in the
                # reply — not a fault in Claude Bridge — so it logs at DEBUG and
                # never reaches the event log as a red error.
                self.log_tool_outcome(
                    "run_script", result["success"],
                    f"Ran '{name}'" + (f" — ERROR: {error_msg}" if error_msg else ""),
                    level=logging.DEBUG)
                return result

            job, busy = exec_lock.start("run_script", f"'{os.path.basename(path)}'", _work)
            if busy:
                self.log_tool_outcome("run_script", False,
                                      f"refused — job {busy['running_job_id']} holds the capture",
                                      level=logging.DEBUG)
                return busy
            return exec_lock.wait(job, wait_seconds)
        except Exception as exc:
            return self.handle_exception(exc, "run_script")

    # ────────────────────────────────────────────────────────────────────────
    # log_message
    # ────────────────────────────────────────────────────────────────────────

    def log_message(self, message: str, level: str = "INFO") -> Dict[str, Any]:
        """
        Write a message to the Indigo on-screen event log.

        Level can be: INFO (default), WARNING, ERROR, DEBUG.
        The message appears immediately in the Indigo Log Viewer.
        """
        self.log_incoming_request("log_message", {"message": message, "level": level})
        try:
            level_upper = (level or "INFO").upper()
            # indigo.server.log(level=...) wants a Python logging INT. A STRING is
            # silently ignored and the line logs as plain Info — so passing
            # level_upper straight through meant every WARNING/DEBUG request was
            # echoed back as honoured while the log line was actually Info.
            level_int = resolve_level(level_upper)
            if level_int >= logging.ERROR:
                indigo.server.log(message, level=level_int, isError=True)
            else:
                indigo.server.log(message, level=level_int)
            result = {"success": True, "message": message, "level": level_upper}
            self.log_tool_outcome("log_message", True, f"Logged [{level_upper}] {message[:60]}")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "log_message")

    # ────────────────────────────────────────────────────────────────────────
    # list_script_backups
    # ────────────────────────────────────────────────────────────────────────

    def list_script_backups(self, name: str) -> Dict[str, Any]:
        """List auto-backups available for a given script name."""
        self.log_incoming_request("list_script_backups", {"name": name})
        try:
            backup_dir = _backup_dir()
            ts_re      = _backup_name_re(_script_stem(name))

            backups = []
            if os.path.isdir(backup_dir):
                for entry in sorted(os.scandir(backup_dir), key=lambda e: e.name):
                    if ts_re.match(entry.name):
                        stat = entry.stat()
                        backups.append({
                            "filename": entry.name,
                            "path":     entry.path,
                            "size_kb":  round(stat.st_size / 1024, 1),
                            "created":  datetime.fromtimestamp(
                                stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        })

            result = {
                "success": True,
                "script":  name,
                "count":   len(backups),
                "backups": list(reversed(backups)),   # newest first
            }
            self.log_tool_outcome("list_script_backups", True,
                                  f"{len(backups)} backups for '{name}'")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "list_script_backups")
