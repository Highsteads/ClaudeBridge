"""
System tools handler for ClaudeBridge MCP server.

Provides Mac Mini system health reporting and Indigo housekeeping tools:
  - system_health          : disk, RAM, uptime, macOS/Python versions
  - list_python_scripts    : enumerate Python Scripts folder
  - find_orphaned_scripts  : scripts referencing device/variable IDs that no longer exist
  - find_orphaned_plugin_data : Preferences/Plugins dirs with no matching installed plugin
  - find_large_files       : files over a size threshold in a given path
  - get_reflector_url      : Indigo Reflector remote URL (if configured)
  - create_device_folder   : create a new device folder
  - create_variable_folder : create a new variable folder

All filesystem paths are derived from indigo.server.getInstallFolderPath() at
call time — no hardcoded paths.
"""

import logging
import os
import plistlib
import re
import shutil
import subprocess
import platform
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider


# ── Indigo path helpers ──────────────────────────────────────────────────────

def _indigo_base() -> str:
    """Return the Indigo install folder (e.g. .../Indigo 2025.2 — version resolved at runtime)."""
    return indigo.server.getInstallFolderPath()

def _prefs_plugins_dir() -> str:
    return os.path.join(_indigo_base(), "Preferences", "Plugins")

def _plugins_dir() -> str:
    return os.path.join(_indigo_base(), "Plugins")

def _plugins_disabled_dir() -> str:
    return os.path.join(_indigo_base(), "Plugins (Disabled)")

def _scripts_dir() -> str:
    """
    Return the primary Indigo Python scripts folder (Python Scripts takes precedence).

    Resolution order:
      1. <PA base>/Python Scripts — primary location (~35 scripts, preferred)
      2. <PA base>/Scripts        — secondary / fallback
      3. <PA base>/Python Scripts — default if neither exists
    """
    pa_base        = os.path.dirname(_indigo_base())
    python_scripts = os.path.join(pa_base, "Python Scripts")
    scripts        = os.path.join(pa_base, "Scripts")
    if os.path.isdir(python_scripts):
        return python_scripts
    if os.path.isdir(scripts):
        return scripts
    return python_scripts  # default


def _all_scripts_dirs() -> list:
    """Return both script folders that exist, Python Scripts first."""
    pa_base        = os.path.dirname(_indigo_base())
    python_scripts = os.path.join(pa_base, "Python Scripts")
    scripts        = os.path.join(pa_base, "Scripts")
    return [d for d in [python_scripts, scripts] if os.path.isdir(d)]


# ── System helpers ───────────────────────────────────────────────────────────

def _run(cmd: List[str], timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception:
        return ""

def _parse_ram() -> Dict[str, Any]:
    """Parse vm_stat output for a RAM summary."""
    out = _run(["vm_stat"])
    page_size = 4096
    for line in out.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of")[1].split()[0])
            except (ValueError, IndexError):
                pass

    pages: Dict[str, int] = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            try:
                pages[k.strip()] = int(v.strip().rstrip("."))
            except ValueError:
                pass

    free     = pages.get("Pages free",       0)
    active   = pages.get("Pages active",     0)
    inactive = pages.get("Pages inactive",   0)
    wired    = pages.get("Pages wired down", 0)
    total    = free + active + inactive + wired

    def _gb(p: int) -> float:
        return round(p * page_size / 1_073_741_824, 1)

    return {
        "total_gb": _gb(total),
        "used_gb":  _gb(active + wired),
        "free_gb":  _gb(free),
    }


# ── Plugin bundle ID helpers ─────────────────────────────────────────────────

def _bundle_id_from_plist(plugin_path: str) -> Optional[str]:
    """Read CFBundleIdentifier from a .indigoPlugin's Info.plist."""
    plist_path = os.path.join(plugin_path, "Contents", "Info.plist")
    try:
        with open(plist_path, "rb") as fh:
            info = plistlib.load(fh)
        return info.get("CFBundleIdentifier") or info.get("PluginVersion")
    except Exception:
        return None

def _installed_bundle_ids() -> set:
    """Return CFBundleIdentifiers of all installed (active + disabled) plugins."""
    ids: set = set()
    for plugins_dir in (_plugins_dir(), _plugins_disabled_dir()):
        if not os.path.isdir(plugins_dir):
            continue
        for entry in os.scandir(plugins_dir):
            if entry.name.endswith(".indigoPlugin") and entry.is_dir():
                bid = _bundle_id_from_plist(entry.path)
                if bid:
                    ids.add(bid)
    return ids


class SystemToolsHandler(BaseToolHandler):
    """Handler for Mac Mini system health and Indigo housekeeping tools."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="system_tools", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # system_health
    # ────────────────────────────────────────────────────────────────────────

    def system_health(self) -> Dict[str, Any]:
        """Return a snapshot of Mac Mini system health."""
        self.log_incoming_request("system_health", {})
        try:
            disk  = shutil.disk_usage("/")
            ram   = _parse_ram()
            uname = platform.uname()

            result = {
                "success":    True,
                "hostname":   uname.node,
                "macos":      platform.mac_ver()[0],
                "python":     platform.python_version(),
                "arch":       uname.machine,
                "disk": {
                    "total_gb": round(disk.total / 1_073_741_824, 1),
                    "used_gb":  round(disk.used  / 1_073_741_824, 1),
                    "free_gb":  round(disk.free  / 1_073_741_824, 1),
                    "used_pct": round(disk.used / disk.total * 100, 1),
                },
                "ram": ram,
                "uptime": _run(["uptime"]) or "unavailable",
            }
            self.log_tool_outcome("system_health", True, "Health snapshot retrieved")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "system_health")

    # ────────────────────────────────────────────────────────────────────────
    # list_python_scripts
    # ────────────────────────────────────────────────────────────────────────

    def list_python_scripts(self) -> Dict[str, Any]:
        """List all .py files in the Indigo Python Scripts and Scripts folders."""
        self.log_incoming_request("list_python_scripts", {})
        try:
            all_dirs = _all_scripts_dirs()
            if not all_dirs:
                return {"success": True, "scripts": [],
                        "note": "No scripts folders found"}

            scripts = []
            for scripts_dir in all_dirs:
                for entry in sorted(os.scandir(scripts_dir), key=lambda e: e.name.lower()):
                    if not entry.name.endswith(".py") or not entry.is_file():
                        continue
                    if entry.name.startswith("_"):
                        continue  # skip backups/archived files in subdirs
                    stat = entry.stat()
                    scripts.append({
                        "name":     entry.name,
                        "size_kb":  round(stat.st_size / 1024, 1),
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "path":     entry.path,
                        "folder":   scripts_dir,
                    })

            result = {
                "success": True,
                "count":   len(scripts),
                "folders": all_dirs,
                "scripts": scripts,
            }
            self.log_tool_outcome("list_python_scripts", True, f"{len(scripts)} scripts found")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "list_python_scripts")

    # ────────────────────────────────────────────────────────────────────────
    # find_orphaned_scripts
    # ────────────────────────────────────────────────────────────────────────

    def find_orphaned_scripts(self) -> Dict[str, Any]:
        """
        Scan Python Scripts folder for scripts that reference device or
        variable IDs which no longer exist in Indigo.

        Reports the script name, which IDs were found in the script, and
        which of those IDs are no longer present.
        """
        self.log_incoming_request("find_orphaned_scripts", {})
        try:
            # Gather live Indigo IDs
            live_device_ids  = {dev["id"] for dev in
                                 (self.data_provider.get_all_devices_unfiltered() or [])}
            live_var_ids     = {v["id"]   for v in
                                 (self.data_provider.get_all_variables_unfiltered() or [])}
            live_ids         = live_device_ids | live_var_ids

            all_dirs = _all_scripts_dirs()
            if not all_dirs:
                return {"success": True, "orphaned": [],
                        "note": "No scripts folders found"}

            # Indigo IDs are typically 8–10 digit integers
            id_pattern = re.compile(r"\b(\d{8,12})\b")

            orphaned   = []
            clean      = []

            for scripts_dir in all_dirs:
                for entry in sorted(os.scandir(scripts_dir), key=lambda e: e.name.lower()):
                    if not entry.name.endswith(".py") or not entry.is_file():
                        continue
                    try:
                        with open(entry.path, "r", encoding="utf-8", errors="replace") as fh:
                            content = fh.read()
                    except OSError:
                        continue

                    found_ids = {int(m) for m in id_pattern.findall(content)}
                    dead_ids  = found_ids - live_ids

                    if dead_ids:
                        orphaned.append({
                            "script":   entry.name,
                            "folder":   scripts_dir,
                            "dead_ids": sorted(dead_ids),
                            "note":     "Contains references to IDs not found in Indigo",
                        })
                    elif found_ids:
                        clean.append(entry.name)

            result = {
                "success":          True,
                "orphaned_count":   len(orphaned),
                "clean_count":      len(clean),
                "live_device_ids":  len(live_device_ids),
                "live_var_ids":     len(live_var_ids),
                "orphaned":         orphaned,
            }
            self.log_tool_outcome("find_orphaned_scripts", True,
                                  f"{len(orphaned)} scripts with dead IDs")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_orphaned_scripts")

    # ────────────────────────────────────────────────────────────────────────
    # find_orphaned_plugin_data
    # ────────────────────────────────────────────────────────────────────────

    def find_orphaned_plugin_data(self) -> Dict[str, Any]:
        """
        Compare Preferences/Plugins subdirectories against installed plugin
        bundle IDs.  Any prefs directory whose name is not a current bundle ID
        is orphaned — the plugin was removed but its data was not cleaned up.
        """
        self.log_incoming_request("find_orphaned_plugin_data", {})
        try:
            prefs_dir = _prefs_plugins_dir()
            if not os.path.isdir(prefs_dir):
                return {"success": True, "orphaned": [],
                        "note": f"Preferences/Plugins not found: {prefs_dir}"}

            installed = _installed_bundle_ids()

            orphaned = []
            active   = []

            for entry in sorted(os.scandir(prefs_dir), key=lambda e: e.name.lower()):
                if not entry.is_dir():
                    continue
                bid = entry.name
                # Calculate total size of the orphaned data directory
                total_size = 0
                for dirpath, _, filenames in os.walk(entry.path):
                    for fname in filenames:
                        try:
                            total_size += os.path.getsize(os.path.join(dirpath, fname))
                        except OSError:
                            pass

                info = {
                    "bundle_id": bid,
                    "path":      entry.path,
                    "size_kb":   round(total_size / 1024, 1),
                }
                if bid in installed:
                    active.append(info)
                else:
                    orphaned.append(info)

            result = {
                "success":             True,
                "orphaned_count":      len(orphaned),
                "active_count":        len(active),
                "installed_plugins":   len(installed),
                "orphaned":            orphaned,
                "active":              active,
            }
            self.log_tool_outcome("find_orphaned_plugin_data", True,
                                  f"{len(orphaned)} orphaned prefs dirs found")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_orphaned_plugin_data")

    # ────────────────────────────────────────────────────────────────────────
    # find_large_files
    # ────────────────────────────────────────────────────────────────────────

    def find_large_files(
        self,
        path: str = "",
        min_mb: float = 10.0,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        """
        Walk a directory tree and return files exceeding min_mb megabytes,
        sorted largest first.

        Default path is the entire Indigo install folder.
        """
        self.log_incoming_request("find_large_files",
                                  {"path": path, "min_mb": min_mb})
        try:
            scan_path = path.strip() if path.strip() else _indigo_base()
            if not os.path.isdir(scan_path):
                return {"success": False,
                        "error": f"Path not found or not a directory: {scan_path}"}

            min_bytes = min_mb * 1_048_576
            found: List[Dict[str, Any]] = []

            for dirpath, _, filenames in os.walk(scan_path):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        size = os.path.getsize(fpath)
                        if size >= min_bytes:
                            found.append({
                                "path":    fpath,
                                "size_mb": round(size / 1_048_576, 2),
                            })
                    except OSError:
                        pass

            found.sort(key=lambda x: x["size_mb"], reverse=True)
            truncated = len(found) > max_results
            found = found[:max_results]

            result = {
                "success":    True,
                "scan_path":  scan_path,
                "min_mb":     min_mb,
                "count":      len(found),
                "truncated":  truncated,
                "files":      found,
            }
            self.log_tool_outcome("find_large_files", True,
                                  f"{len(found)} files >= {min_mb} MB")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "find_large_files")

    # ────────────────────────────────────────────────────────────────────────
    # get_reflector_url
    # ────────────────────────────────────────────────────────────────────────

    def get_reflector_url(self) -> Dict[str, Any]:
        """Return the configured Indigo Reflector URL, if any."""
        self.log_incoming_request("get_reflector_url", {})
        try:
            url = ""
            try:
                url = indigo.server.getReflectorURL() or ""
            except AttributeError:
                return {"success": False,
                        "error": "indigo.server.getReflectorURL() unavailable on this Indigo version"}
            result = {
                "success":   True,
                "configured": bool(url),
                "url":       url,
            }
            self.log_tool_outcome("get_reflector_url", True,
                                  "configured" if url else "not configured")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "get_reflector_url")

    # ────────────────────────────────────────────────────────────────────────
    # create_device_folder / create_variable_folder
    # ────────────────────────────────────────────────────────────────────────

    def create_device_folder(self, name: str) -> Dict[str, Any]:
        """Create a new device folder. Idempotent — returns existing folder if name matches."""
        self.log_incoming_request("create_device_folder", {"name": name})
        try:
            name = (name or "").strip()
            if not name:
                return {"success": False, "error": "Folder name is required"}

            for existing in indigo.devices.folders:
                if existing.name.lower() == name.lower():
                    return {
                        "success":   True,
                        "created":   False,
                        "folder_id": existing.id,
                        "name":      existing.name,
                        "message":   f"Device folder '{existing.name}' already exists",
                    }

            folder = indigo.devices.folder.create(name)
            result = {
                "success":   True,
                "created":   True,
                "folder_id": folder.id,
                "name":      folder.name,
                "message":   f"Device folder '{folder.name}' created (ID {folder.id})",
            }
            self.log_tool_outcome("create_device_folder", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "create_device_folder")

    def create_variable_folder(self, name: str) -> Dict[str, Any]:
        """Create a new variable folder. Idempotent — returns existing folder if name matches."""
        self.log_incoming_request("create_variable_folder", {"name": name})
        try:
            name = (name or "").strip()
            if not name:
                return {"success": False, "error": "Folder name is required"}

            for existing in indigo.variables.folders:
                if existing.name.lower() == name.lower():
                    return {
                        "success":   True,
                        "created":   False,
                        "folder_id": existing.id,
                        "name":      existing.name,
                        "message":   f"Variable folder '{existing.name}' already exists",
                    }

            folder = indigo.variables.folder.create(name)
            result = {
                "success":   True,
                "created":   True,
                "folder_id": folder.id,
                "name":      folder.name,
                "message":   f"Variable folder '{folder.name}' created (ID {folder.id})",
            }
            self.log_tool_outcome("create_variable_folder", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "create_variable_folder")
