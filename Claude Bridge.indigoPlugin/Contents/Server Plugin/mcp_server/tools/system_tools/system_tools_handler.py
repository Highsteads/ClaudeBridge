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
import time
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

# Absolute paths — Indigo's plugin-host PATH omits /usr/sbin, so a bare name
# raises FileNotFoundError, _run() logs it at debug and returns "", and the
# caller silently degrades. Resolve here, once, and fall back to the bare name
# only if the expected location is missing.
def _bin(path: str) -> str:
    return path if os.path.exists(path) else os.path.basename(path)


_VM_STAT = _bin("/usr/bin/vm_stat")
_SYSCTL  = _bin("/usr/sbin/sysctl")
_UPTIME  = _bin("/usr/bin/uptime")

# Wall-clock budget for find_large_files' directory walk. Every plugin callback
# and every other MCP tool call is blocked while it runs (Indigo dispatches them
# all on one thread), so a deep tree must degrade to a partial, clearly-labelled
# answer rather than freezing the plugin.
_WALK_BUDGET_SECONDS = 10


def _run(cmd: List[str], timeout: int = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception as e:
        # Don't fail silently — a missing binary or timeout otherwise looks like
        # an empty/zero metric in system_health with no breadcrumb.
        logging.getLogger("Plugin").debug(
            f"_run({cmd[0] if cmd else '?'}) failed: {type(e).__name__}: {e}"
        )
        return ""

def _parse_ram() -> Dict[str, Any]:
    """Return a RAM summary matching what Activity Monitor shows.

    Total comes from hw.memsize — the installed RAM, no arithmetic. Deriving it
    by summing vm_stat buckets (the old approach) silently omitted compressed
    memory, which understated an 8 GB Mac as 4.4 GB and got worse the busier the
    machine became, because compression rises under pressure.

    Used follows macOS's own definition:
        app memory = anonymous - purgeable
        used       = app memory + wired + compressed
    and free is whatever is left of the installed total. Reporting "Pages free"
    as free memory (the old behaviour) reports the free list, not what is
    actually available, so a healthy Mac looked like it had 0.1 GB left.

    Both binaries are called by ABSOLUTE path. Indigo's plugin-host PATH omits
    /usr/sbin, so a bare "sysctl" raises FileNotFoundError, _run() swallows it,
    and the total silently drops to the fallback estimate — which is exactly
    what shipped in 2.16.1 and read 7.5 GB on an 8 GB Mac.
    """
    out = _run([_VM_STAT])
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

    wired      = pages.get("Pages wired down",             0)
    compressed = pages.get("Pages occupied by compressor", 0)
    anonymous  = pages.get("Anonymous pages",              0)
    purgeable  = pages.get("Pages purgeable",              0)
    app        = max(anonymous - purgeable, 0)
    used_bytes = (app + wired + compressed) * page_size

    total_bytes = 0
    try:
        total_bytes = int(_run([_SYSCTL, "-n", "hw.memsize"]) or 0)
    except ValueError:
        total_bytes = 0

    if total_bytes <= 0:
        # sysctl unavailable — fall back to the page sum, this time WITH the
        # compressor and speculative buckets so the estimate lands close rather
        # than silently short.
        total_bytes = (
            pages.get("Pages free",        0)
            + pages.get("Pages active",    0)
            + pages.get("Pages inactive",  0)
            + pages.get("Pages speculative", 0)
            + wired
            + compressed
        ) * page_size

    # Never report more used than installed, and never a negative free.
    used_bytes = min(used_bytes, total_bytes)
    free_bytes = max(total_bytes - used_bytes, 0)

    def _gb(b: int) -> float:
        return round(b / 1_073_741_824, 1)

    return {
        "total_gb": _gb(total_bytes),
        "used_gb":  _gb(used_bytes),
        "free_gb":  _gb(free_bytes),
        "used_pct": round(used_bytes / total_bytes * 100, 1) if total_bytes else 0.0,
    }


# ── Plugin bundle ID helpers ─────────────────────────────────────────────────

def _bundle_id_from_plist(plugin_path: str) -> Optional[str]:
    """Read CFBundleIdentifier from a .indigoPlugin's Info.plist."""
    plist_path = os.path.join(plugin_path, "Contents", "Info.plist")
    try:
        with open(plist_path, "rb") as fh:
            info = plistlib.load(fh)
        # CFBundleIdentifier only — the old `or PluginVersion` fallback returned
        # a version string masquerading as a bundle id when the key was missing.
        return info.get("CFBundleIdentifier")
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
                "uptime": _run([_UPTIME]) or "unavailable",
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
            # Also treat action-group / schedule / trigger IDs as live so a
            # script referencing one is not mis-flagged as orphaned. Best-effort
            # — only included if the data provider exposes the getter.
            for _getter in ("get_all_actions", "get_all_action_groups",
                            "get_all_schedules", "get_all_triggers"):
                _fn = getattr(self.data_provider, _getter, None)
                if callable(_fn):
                    try:
                        live_ids |= {x["id"] for x in (_fn() or [])
                                     if isinstance(x, dict) and "id" in x}
                    except Exception:
                        pass

            all_dirs = _all_scripts_dirs()
            if not all_dirs:
                return {"success": True, "orphaned": [],
                        "note": "No scripts folders found"}

            # Match an 8–12 digit number ONLY in an ID-ish context — e.g.
            # indigo.devices[NNN], DEVICE_ID = NNN, id=NNN. A bare digit run
            # (epoch timestamp, port, hash fragment) is no longer treated as a
            # device ID, which previously produced false "dead ID" positives.
            id_pattern = re.compile(
                r"(?:indigo\.(?:devices|variables|actionGroups|schedules|triggers)\s*\[\s*"
                r"|(?:device|variable|var|dev|action|schedule|trigger)[_ ]?id\w*\s*[=:]\s*"
                r"|\bid\s*[=:]\s*)"
                r"(\d{8,12})\b",
                re.IGNORECASE,
            )

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
                            "note":     ("Advisory — references IDs not found among live "
                                         "devices/variables/action-groups/schedules/triggers; "
                                         "verify (plugins may hard-code IDs) before deleting"),
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
            # Guard client-supplied numerics (a string/blank arg must not raise).
            try:
                min_mb = float(min_mb)
            except (TypeError, ValueError):
                min_mb = 10.0
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                max_results = 50
            max_results = max(1, min(max_results, 1000))

            # Confine the walk to the Indigo install folder + the two script
            # folders. A read-scoped client must not be able to enumerate the
            # whole filesystem via an arbitrary absolute/relative path.
            base = os.path.realpath(_indigo_base())
            pa   = os.path.dirname(base)
            allowed = [base]
            for _d in ("Python Scripts", "Scripts"):
                _p = os.path.realpath(os.path.join(pa, _d))
                if os.path.isdir(_p):
                    allowed.append(_p)

            raw_path  = path.strip() if (path or "").strip() else base
            scan_path = os.path.realpath(raw_path)
            if not any(scan_path == a or scan_path.startswith(a + os.sep) for a in allowed):
                return {"success": False,
                        "error": ("Path not permitted — find_large_files is confined to the "
                                  f"Indigo install and script folders, got: {raw_path}")}
            if not os.path.isdir(scan_path):
                return {"success": False,
                        "error": f"Path not found or not a directory: {scan_path}"}

            min_bytes = min_mb * 1_048_576
            found: List[Dict[str, Any]] = []

            # Budget the walk. Each file costs only a stat, so a big FILE is
            # cheap (and finding the 1.5GB history DB is the point of this tool)
            # — it is a big COUNT that hurts: Packages trees and Backups can run
            # to tens of thousands of entries, and this walk runs on the single
            # dispatch thread, blocking every other tool call while it goes.
            deadline    = time.time() + _WALK_BUDGET_SECONDS
            scanned     = 0
            walk_capped = False

            for dirpath, dirnames, filenames in os.walk(scan_path):
                # Skip caches that are pure noise in a "what's using disk" answer.
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fname in filenames:
                    scanned += 1
                    if scanned % 2000 == 0 and time.time() > deadline:
                        walk_capped = True
                        break
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
                if walk_capped:
                    break

            found.sort(key=lambda x: x["size_mb"], reverse=True)
            truncated = len(found) > max_results
            found = found[:max_results]

            result = {
                "success":       True,
                "scan_path":     scan_path,
                "min_mb":        min_mb,
                "count":         len(found),
                "truncated":     truncated,
                "files":         found,
                "files_scanned": scanned,
                "walk_capped":   walk_capped,
            }
            if walk_capped:
                # Never let a partial sweep read as a complete one.
                result["note"] = (
                    f"Stopped after {_WALK_BUDGET_SECONDS}s and {scanned} files — the tree was "
                    f"not fully scanned, so this is NOT the complete set of large files. "
                    f"Re-run against a narrower path."
                )
                self.logger.warning(f"[system_tools]: find_large_files hit its "
                                    f"{_WALK_BUDGET_SECONDS}s budget after {scanned} files "
                                    f"under {scan_path}")
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

    def get_reflector_status(self) -> Dict[str, Any]:
        """Return the full reflector status dict (connection state, not just the
        URL) via indigo.server.getReflectorStatus()."""
        self.log_incoming_request("get_reflector_status", {})
        try:
            try:
                status = indigo.server.getReflectorStatus()
            except AttributeError:
                return {"success": False,
                        "error": "indigo.server.getReflectorStatus() unavailable on this Indigo version"}
            # It's an indigo.Dict — convert to a plain dict for JSON.
            status = dict(status) if status else {}
            self.log_tool_outcome("get_reflector_status", True, "ok")
            return {"success": True, "status": status}
        except Exception as exc:
            return self.handle_exception(exc, "get_reflector_status")

    def get_indigo_paths(self) -> Dict[str, Any]:
        """Return the key filesystem paths of this Indigo install — the install
        folder, Logs folder, and the SQL Logger history DB (file + name). Lets a
        client locate the history DB it queries and the logs it reads without
        hardcoding a version-specific path."""
        self.log_incoming_request("get_indigo_paths", {})
        try:
            def _try(fn):
                try:
                    return fn()
                except Exception:
                    return None
            paths = {
                "install_folder": _try(indigo.server.getInstallFolderPath),
                "logs_folder":    _try(indigo.server.getLogsFolderPath),
                "db_file":        _try(indigo.server.getDbFilePath),
                "db_name":        _try(indigo.server.getDbName),
            }
            self.log_tool_outcome("get_indigo_paths", True, "ok")
            return {"success": True, "paths": paths}
        except Exception as exc:
            return self.handle_exception(exc, "get_indigo_paths")

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

    # ────────────────────────────────────────────────────────────────────────
    # v2.9.0 — folder deletion + API coverage audit
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_folder(collection, folder):
        """Resolve a folder by numeric ID or (case-insensitive) name."""
        try:
            fid = int(str(folder).strip())
            for f in collection.folders:
                if f.id == fid:
                    return f
        except (TypeError, ValueError):
            pass
        name = str(folder).strip().lower()
        for f in collection.folders:
            if f.name.lower() == name:
                return f
        return None

    def delete_device_folder(self, folder, delete_children: bool = False) -> Dict[str, Any]:
        """Delete a device folder by ID or name. Refuses a non-empty folder
        unless delete_children=True (which deletes the devices inside it!)."""
        self.log_incoming_request("delete_device_folder",
                                  {"folder": folder, "delete_children": delete_children})
        try:
            f = self._find_folder(indigo.devices, folder)
            if f is None:
                return {"success": False, "error": f"Device folder {folder!r} not found"}
            members = [d.name for d in indigo.devices.iter() if d.folderId == f.id]
            if members and not delete_children:
                return {"success": False,
                        "error": f"Folder '{f.name}' contains {len(members)} device(s) — "
                                 f"refusing to delete. Move them out first, or pass "
                                 f"delete_children=true to delete the devices too.",
                        "members": members[:20]}
            indigo.devices.folder.delete(f, deleteAllChildren=bool(members))
            msg = (f"Deleted device folder '{f.name}'"
                   + (f" and its {len(members)} device(s)" if members else ""))
            self.log_tool_outcome("delete_device_folder", True, msg)
            return {"success": True, "message": msg, "deleted_children": len(members)}
        except Exception as exc:
            return self.handle_exception(exc, "delete_device_folder")

    def delete_variable_folder(self, folder, delete_children: bool = False) -> Dict[str, Any]:
        """Delete a variable folder by ID or name. Refuses a non-empty folder
        unless delete_children=True (which deletes the variables inside it!)."""
        self.log_incoming_request("delete_variable_folder",
                                  {"folder": folder, "delete_children": delete_children})
        try:
            f = self._find_folder(indigo.variables, folder)
            if f is None:
                return {"success": False, "error": f"Variable folder {folder!r} not found"}
            members = [v.name for v in indigo.variables.iter() if v.folderId == f.id]
            if members and not delete_children:
                return {"success": False,
                        "error": f"Folder '{f.name}' contains {len(members)} variable(s) — "
                                 f"refusing to delete. Move them out first, or pass "
                                 f"delete_children=true to delete the variables too.",
                        "members": members[:20]}
            indigo.variables.folder.delete(f, deleteAllChildren=bool(members))
            msg = (f"Deleted variable folder '{f.name}'"
                   + (f" and its {len(members)} variable(s)" if members else ""))
            self.log_tool_outcome("delete_variable_folder", True, msg)
            return {"success": True, "message": msg, "deleted_children": len(members)}
        except Exception as exc:
            return self.handle_exception(exc, "delete_variable_folder")

    def audit_api_coverage(self) -> Dict[str, Any]:
        """Diff the LIVE indigo.* command namespaces against the frozen baseline
        captured at build time. After an Indigo upgrade this reports any new
        callables (candidate tools Claude Bridge hasn't surfaced yet) and any
        removals (tools that may now be broken). Regenerate the baseline by
        re-running the walker in api_baseline.py's header after an upgrade."""
        self.log_incoming_request("audit_api_coverage", {})
        try:
            from .api_baseline import API_BASELINE
            namespaces = ["device", "dimmer", "relay", "sensor", "thermostat",
                          "sprinkler", "speedcontrol", "iodevice", "variable",
                          "trigger", "schedule", "actionGroup", "controlPage",
                          "zwave", "insteon", "server"]
            live = set()
            for ns in namespaces:
                obj = getattr(indigo, ns, None)
                if obj is None:
                    continue
                for n in dir(obj):
                    if not n.startswith("_") and callable(getattr(obj, n, None)):
                        live.add(f"{ns}.{n}")
            for ns in ["devices", "variables", "triggers", "schedules",
                       "actionGroups", "controlPages"]:
                obj = getattr(indigo, ns, None)
                fold = getattr(obj, "folder", None) if obj is not None else None
                if fold is not None:
                    for n in dir(fold):
                        if not n.startswith("_") and callable(getattr(fold, n, None)):
                            live.add(f"{ns}.folder.{n}")
            # Top-level functions sit at indigo.<name>, OUTSIDE every namespace
            # above, so a namespace-only walk reports a clean sweep while missing
            # them entirely — that is how the five rawServer* functions stayed
            # invisible until 06-Aug-2026. Keyed by bare name; namespace entries
            # all contain a dot, so the two can never collide. Classes are
            # excluded to match the namespace walk, which enumerates methods.
            import inspect as _inspect
            for n in dir(indigo):
                if n.startswith("_"):
                    continue
                obj = getattr(indigo, n, None)
                if obj is None or not callable(obj):
                    continue
                if _inspect.isclass(obj) or _inspect.ismodule(obj):
                    continue
                live.add(n)
            added   = sorted(live - API_BASELINE)
            removed = sorted(API_BASELINE - live)
            msg = (f"API coverage audit: {len(live)} live callables vs "
                   f"{len(API_BASELINE)} baseline — {len(added)} new, {len(removed)} removed")
            self.log_tool_outcome("audit_api_coverage", True, msg)
            return {"success": True, "indigo_version": str(indigo.server.version),
                    "live_count": len(live), "baseline_count": len(API_BASELINE),
                    "new_since_baseline": added, "removed_since_baseline": removed,
                    "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "audit_api_coverage")

    # Only READ-side request names are reachable. indigo.rawServerCommand
    # MUTATES server state and is deliberately not exposed here at all; a
    # request name that is not a Get is refused rather than tried, because
    # these are undocumented internals and the blast radius of guessing at
    # a name is unknown. Do NOT relax this to "try it and see".
    RAW_REQUEST_PREFIX = "Get"

    def raw_server_request(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a READ-ONLY raw named request to the Indigo server.

        indigo.rawServerRequest reaches the server's own command set directly.
        It is UNDOCUMENTED and UNSUPPORTED — Perceptive Automation's own
        utils.py uses exactly one call, rawServerRequest("GetControlPage",
        {"ID": <id>, "GetPageFlags": 65538}) — so treat any use as fragile
        across Indigo upgrades and verify against the running version.
        """
        self.log_incoming_request("raw_server_request", {"name": name, "args": args})
        try:
            if not isinstance(name, str) or not name.isidentifier():
                return {"success": False,
                        "error": "name must be a plain identifier, e.g. GetControlPage"}
            if not name.startswith(self.RAW_REQUEST_PREFIX):
                return {"success": False,
                        "error": (f"refused: only read-side '{self.RAW_REQUEST_PREFIX}*' "
                                  f"requests are exposed, and {name!r} is not one. "
                                  "Mutating raw server commands are deliberately "
                                  "unreachable through this tool.")}
            if args is not None and not isinstance(args, dict):
                return {"success": False, "error": "args must be an object or omitted"}

            fn = getattr(indigo, "rawServerRequest", None)
            if fn is None:
                return {"success": False,
                        "error": "indigo.rawServerRequest is not present on this Indigo version"}

            raw = fn(name, args) if args is not None else fn(name)

            from ...common.indigo_plain import to_plain
            result = to_plain(raw)
            msg = f"raw_server_request {name} returned {type(raw).__name__}"
            self.log_tool_outcome("raw_server_request", True, msg)
            return {"success": True, "request": name, "args": args,
                    "result": result, "result_type": type(raw).__name__,
                    "note": ("Undocumented Indigo internal — unsupported and may "
                             "change without warning between versions."),
                    "message": msg}
        except Exception as exc:
            return self.handle_exception(exc, "raw_server_request")
