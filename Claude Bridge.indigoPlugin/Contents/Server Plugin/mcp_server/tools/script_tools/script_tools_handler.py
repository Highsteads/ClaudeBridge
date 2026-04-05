"""
Script tools handler for ClaudeBridge MCP server.

Provides read, write, and create access to the Indigo Scripts folder,
allowing Claude to inspect, debug, and update automation scripts directly.

The active scripts folder is resolved at runtime:
  1. <PA base>/Scripts        — standard Indigo location (preferred)
  2. <PA base>/Python Scripts — legacy/custom fallback if Scripts does not exist

Tools:
  - read_script(name)               : return full content of a script
  - write_script(name, content)     : overwrite a script (auto-backup created)
  - create_script(name, content)    : create a new script (fails if exists)
  - delete_script(name)             : move a script to the _archive subfolder
  - list_script_backups(name)       : list auto-backups for a script
"""

import logging
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

BACKUP_DIR_NAME = "_backups"
MAX_BACKUPS_PER_SCRIPT = 5


def _scripts_dir() -> str:
    """
    Return the active Indigo scripts folder.

    Resolution order:
      1. <PA base>/Scripts        — standard Indigo location, present on all installations
      2. <PA base>/Python Scripts — legacy / custom fallback
      3. <PA base>/Scripts        — default if neither exists (created on first write)
    """
    pa_base = os.path.dirname(indigo.server.getInstallFolderPath())
    scripts        = os.path.join(pa_base, "Scripts")
    python_scripts = os.path.join(pa_base, "Python Scripts")
    if os.path.isdir(scripts):
        return scripts
    if os.path.isdir(python_scripts):
        return python_scripts
    return scripts  # default — will be created on first write


def _backup_dir() -> str:
    return os.path.join(_scripts_dir(), BACKUP_DIR_NAME)


def _resolve(name: str) -> str:
    """Return full path for a script name (adds .py if missing)."""
    if not name.endswith(".py"):
        name = name + ".py"
    return os.path.join(_scripts_dir(), name)


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
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"{stem}.{ts}.py")

    try:
        shutil.copy2(script_path, dest)
    except OSError:
        return None

    # Prune old backups for this script
    try:
        pattern = f"{stem}."
        backups = sorted(
            [e.path for e in os.scandir(backup_dir)
             if e.name.startswith(pattern) and e.name.endswith(".py")],
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
        data_provider: DataProvider,
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
        Fails if the script does not already exist — use create_script for new scripts.
        """
        self.log_incoming_request("write_script", {"name": name})
        try:
            path = _resolve(name)
            if not os.path.isfile(path):
                return {"success": False,
                        "error": (f"Script '{name}' does not exist. "
                                  f"Use create_script to create a new script.")}

            backup = _make_backup(path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

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
                        "error": (f"Script '{name}' already exists. "
                                  f"Use write_script to update an existing script.")}

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

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
    # scaffold_automation_script
    # ────────────────────────────────────────────────────────────────────────

    def scaffold_automation_script(
        self,
        script_name: str,
        description: str = "",
        device_ids: Optional[List[int]] = None,
        variable_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Generate and save a complete Python script template to the Indigo
        Scripts folder. The scaffold includes:
          - Standard file header (CliveS convention)
          - log() helper function
          - Named constants for every supplied device/variable ID
            (names looked up live from Indigo so they're correct)
          - Skeleton main() function with safe error handling
        Fails if a script with that name already exists.
        """
        self.log_incoming_request("scaffold_automation_script",
                                  {"script_name": script_name,
                                   "device_ids": device_ids,
                                   "variable_ids": variable_ids})
        try:
            path = _resolve(script_name)
            if os.path.isfile(path):
                return {
                    "success": False,
                    "error": (f"Script '{script_name}' already exists. "
                              "Use write_script to update it."),
                }

            # Resolve device names from Indigo
            device_lines: List[str] = []
            if device_ids:
                try:
                    import indigo as _indigo
                    for did in device_ids:
                        try:
                            dname = _indigo.devices[int(did)].name
                        except Exception:
                            dname = f"Device_{did}"
                        const = dname.upper().replace(" ", "_").replace("-", "_")
                        const = "".join(c if c.isalnum() or c == "_" else "_"
                                        for c in const)
                        device_lines.append(
                            f"DEVICE_{const:<30} = {did}  # {dname}"
                        )
                except ImportError:
                    for did in device_ids:
                        device_lines.append(f"DEVICE_ID_{did:<25} = {did}")

            # Resolve variable names from Indigo
            variable_lines: List[str] = []
            if variable_ids:
                try:
                    import indigo as _indigo
                    for vid in variable_ids:
                        try:
                            vname = _indigo.variables[int(vid)].name
                        except Exception:
                            vname = f"Variable_{vid}"
                        const = vname.upper().replace(" ", "_").replace("-", "_")
                        const = "".join(c if c.isalnum() or c == "_" else "_"
                                        for c in const)
                        variable_lines.append(
                            f"VARIABLE_{const:<28} = {vid}  # {vname}"
                        )
                except ImportError:
                    for vid in variable_ids:
                        variable_lines.append(f"VARIABLE_ID_{vid:<21} = {vid}")

            now     = datetime.now()
            stem    = os.path.basename(path)[:-3]
            desc    = description or f"{stem} automation script"

            ids_block = ""
            if device_lines or variable_lines:
                ids_block = "\n# ── Device / Variable IDs ────────────────────────────────────────────────\n"
                if device_lines:
                    ids_block += "\n".join(device_lines) + "\n"
                if variable_lines:
                    ids_block += "\n".join(variable_lines) + "\n"
                ids_block += "\n"

            content = f"""\
#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    {os.path.basename(path)}
# Description: {desc}
# Author:      CliveS & Claude Sonnet 4.6
# Date:        {now.strftime("%d-%m-%Y")}
# Version:     1.0

# ── Imports ───────────────────────────────────────────────────────────────────
from datetime import datetime
import indigo  # noqa

{ids_block}
# ── Helpers ───────────────────────────────────────────────────────────────────

def log(message, level="INFO"):
    indigo.server.log(f"[{{datetime.now().strftime('%H:%M:%S')}}] {{message}}",
                      level=level)


# ── Main logic ────────────────────────────────────────────────────────────────

def main():
    \"\"\"
    {desc}
    \"\"\"
    try:
        log("Script started")

        # ── TODO: add your logic here ──────────────────────────────────────


        log("Script complete")
    except Exception as exc:
        indigo.server.log(f"ERROR in {stem}: {{exc}}", level="ERROR")
        raise


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
"""

            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

            lines_count = content.count("\n") + 1
            result = {
                "success":      True,
                "name":         os.path.basename(path),
                "path":         path,
                "lines":        lines_count,
                "device_ids":   device_ids or [],
                "variable_ids": variable_ids or [],
                "message":      (f"Scaffold '{script_name}' created "
                                 f"({lines_count} lines). "
                                 f"Edit in Indigo or use write_script to update."),
            }
            self.log_tool_outcome("scaffold_automation_script", True,
                                  result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "scaffold_automation_script")

    def list_script_backups(self, name: str) -> Dict[str, Any]:
        """List auto-backups available for a given script name."""
        self.log_incoming_request("list_script_backups", {"name": name})
        try:
            backup_dir = _backup_dir()
            stem       = name.replace(".py", "")
            pattern    = f"{stem}."

            backups = []
            if os.path.isdir(backup_dir):
                for entry in sorted(os.scandir(backup_dir), key=lambda e: e.name):
                    if entry.name.startswith(pattern) and entry.name.endswith(".py"):
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
