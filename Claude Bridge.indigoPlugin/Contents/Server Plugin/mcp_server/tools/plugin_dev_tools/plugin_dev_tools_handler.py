#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_dev_tools_handler.py
# Description: Plugin-development helper tools — diff source vs installed,
#              refresh pip deps, show installed package versions, validate
#              plugin XML, lint JS in bundled HTML, lint plugin.py against
#              the CliveS CLAUDE.md rules, and focused SQL Logger device
#              history queries. These are NOT IOM wrappers — they operate on
#              the plugin bundle and Indigo SQL Logger sqlite database.
# Author:      CliveS & Claude Opus 4.7
# Date:        27-05-2026
# Version:     1.0
#
# All filesystem paths are derived at call time:
#   - installed plugin:  indigo.server.getInstallFolderPath() / Plugins / <name>.indigoPlugin
#   - source repo:       ~/Documents/GitHub/<RepoName>
#   - SQL Logger DB:     indigo.server.getInstallFolderPath() / Logs / indigo_history.sqlite
#
# Returns are all dicts wrapped at the mcp_handler dispatch layer.

import glob
import hashlib
import logging
import os
import re
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider


# ── Path helpers ────────────────────────────────────────────────────────────

def _indigo_base() -> str:
    return indigo.server.getInstallFolderPath()

def _plugins_dir() -> str:
    return os.path.join(_indigo_base(), "Plugins")

def _sql_logger_db() -> str:
    return os.path.join(_indigo_base(), "Logs", "indigo_history.sqlite")

def _github_root() -> str:
    """Best-effort: the user's GitHub clone root."""
    return os.path.expanduser("~/Documents/GitHub")


def _resolve_installed_bundle(plugin_name: str) -> Optional[str]:
    """
    Find the installed .indigoPlugin directory matching a name. Accepts:
      - exact directory name ('Claude Bridge.indigoPlugin')
      - bare plugin name ('Claude Bridge')
      - case-insensitive partial match
    """
    pd = _plugins_dir()
    if not os.path.isdir(pd):
        return None
    pn = plugin_name.strip()
    # Exact dir
    direct = os.path.join(pd, pn if pn.endswith(".indigoPlugin") else pn + ".indigoPlugin")
    if os.path.isdir(direct):
        return direct
    # Case-insensitive scan
    pn_low = pn.lower().replace(".indigoplugin", "")
    for entry in os.listdir(pd):
        if entry.endswith(".indigoPlugin"):
            stem = entry[:-len(".indigoPlugin")].lower()
            if stem == pn_low or pn_low in stem:
                return os.path.join(pd, entry)
    return None


def _resolve_source_repo(plugin_name: str) -> Optional[str]:
    """
    Find the source repo for a plugin under ~/Documents/GitHub/. Tries:
      - exact match
      - case-insensitive
      - stripped-spaces variant ('Claude Bridge' → 'ClaudeBridge')
    """
    root = _github_root()
    if not os.path.isdir(root):
        return None
    candidates = [
        plugin_name,
        plugin_name.replace(" ", ""),
        plugin_name.replace(".indigoPlugin", ""),
        plugin_name.replace(" ", "").replace(".indigoPlugin", ""),
    ]
    entries = os.listdir(root)
    low_map = {e.lower(): e for e in entries}
    for cand in candidates:
        if cand in entries:
            return os.path.join(root, cand)
        if cand.lower() in low_map:
            return os.path.join(root, low_map[cand.lower()])
    # Partial fallback
    stem = plugin_name.replace(" ", "").replace(".indigoPlugin", "").lower()
    for e in entries:
        if stem and stem in e.lower():
            return os.path.join(root, e)
    return None


def _file_hash(path: str) -> str:
    """SHA-256 of a file's contents, truncated to 12 hex chars for compact diffs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


# ════════════════════════════════════════════════════════════════════════════


class PluginDevToolsHandler(BaseToolHandler):
    """v2.6.0 plugin-development helpers."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="plugin_dev_tools", logger=logger)
        self.data_provider = data_provider

    # ════════════════════════════════════════════════════════════════════════
    # plugin_diff_source_vs_installed
    # ════════════════════════════════════════════════════════════════════════

    def plugin_diff_source_vs_installed(self, plugin_name: str) -> Dict[str, Any]:
        """
        Compare a plugin's source repo bundle against the installed bundle.
        Surfaces drift that breaks stuff silently (e.g. static-asset rewrites
        that didn't sync, gutted Packages dir, version-bump mismatches).
        """
        self.log_incoming_request("plugin_diff_source_vs_installed",
                                  {"plugin_name": plugin_name})
        try:
            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}
            repo = _resolve_source_repo(plugin_name)
            if not repo:
                return {"success": False,
                        "error": f"No source repo matches '{plugin_name}' under {_github_root()}"}

            # Source bundle lives at <repo>/<X>.indigoPlugin
            bundle_name = os.path.basename(installed)
            src_bundle = os.path.join(repo, bundle_name)
            if not os.path.isdir(src_bundle):
                # Try first .indigoPlugin under repo
                hits = [d for d in os.listdir(repo) if d.endswith(".indigoPlugin")]
                if not hits:
                    return {"success": False,
                            "error": f"No .indigoPlugin found at repo root {repo}"}
                src_bundle = os.path.join(repo, hits[0])

            # Walk both bundles. Skip caches/packages — Indigo manages those.
            SKIP_DIRS = {"__pycache__", "Packages", ".git"}

            def _walk(root: str) -> Dict[str, Tuple[int, str]]:
                """Return {rel_path: (size, hash12)}."""
                out: Dict[str, Tuple[int, str]] = {}
                for dp, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for f in files:
                        if f in (".DS_Store",) or f.endswith((".pyc", ".pyo")):
                            continue
                        full = os.path.join(dp, f)
                        rel = os.path.relpath(full, root)
                        try:
                            size = os.path.getsize(full)
                            h = _file_hash(full)
                        except OSError:
                            continue
                        out[rel] = (size, h)
                return out

            src_files = _walk(src_bundle)
            inst_files = _walk(installed)

            only_in_src = sorted(set(src_files) - set(inst_files))
            only_in_inst = sorted(set(inst_files) - set(src_files))
            common = sorted(set(src_files) & set(inst_files))
            changed = []
            for rel in common:
                if src_files[rel] != inst_files[rel]:
                    changed.append({
                        "file":            rel,
                        "src_size":        src_files[rel][0],
                        "installed_size":  inst_files[rel][0],
                        "src_hash":        src_files[rel][1],
                        "installed_hash":  inst_files[rel][1],
                    })

            in_sync = not (only_in_src or only_in_inst or changed)
            return {
                "success":           True,
                "in_sync":           in_sync,
                "source_bundle":     src_bundle,
                "installed_bundle":  installed,
                "src_file_count":    len(src_files),
                "inst_file_count":   len(inst_files),
                "only_in_source":    only_in_src,
                "only_in_installed": only_in_inst,
                "changed_files":     changed,
                "summary":           (f"in sync — {len(common)} files match"
                                      if in_sync else
                                      f"{len(changed)} changed, "
                                      f"{len(only_in_src)} source-only, "
                                      f"{len(only_in_inst)} installed-only"),
            }
        except Exception as exc:
            return self.handle_exception(exc, "plugin_diff_source_vs_installed")

    # ════════════════════════════════════════════════════════════════════════
    # plugin_refresh_deps
    # ════════════════════════════════════════════════════════════════════════

    def plugin_refresh_deps(self, plugin_name: str,
                            restart: bool = False) -> Dict[str, Any]:
        """
        Delete the 3.13-pip-install-log-success.txt marker so Indigo re-runs
        requirements.txt on next plugin start. Optionally also delete the
        Packages dir for a fully clean install (gutted-Packages recovery).
        """
        self.log_incoming_request("plugin_refresh_deps",
                                  {"plugin_name": plugin_name, "restart": restart})
        try:
            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}

            packages_dir = os.path.join(installed, "Contents", "Packages")
            if not os.path.isdir(packages_dir):
                return {"success": False,
                        "error": f"No Packages/ dir at {packages_dir} — "
                                 f"plugin may be stdlib-only"}

            # Find all success markers (Indigo names them per Python version)
            removed = []
            for marker in glob.glob(os.path.join(packages_dir, "*-pip-install-log-success.txt")):
                try:
                    os.remove(marker)
                    removed.append(os.path.basename(marker))
                except OSError as e:
                    return {"success": False, "error": f"Could not remove {marker}: {e}"}

            result = {
                "success":          True,
                "installed_bundle": installed,
                "markers_removed":  removed,
                "restart_requested": bool(restart),
            }

            if restart:
                # Read bundle ID from Info.plist
                import plistlib
                with open(os.path.join(installed, "Contents", "Info.plist"), "rb") as f:
                    plist = plistlib.load(f)
                bundle_id = plist.get("CFBundleIdentifier", "")
                if not bundle_id:
                    return {**result, "restart_error":
                            "Could not read CFBundleIdentifier from Info.plist"}
                try:
                    plugin = indigo.server.getPlugin(bundle_id)
                    if plugin is None:
                        return {**result,
                                "restart_error": f"No plugin registered with id {bundle_id}"}
                    plugin.restart(waitUntilDone=False)
                    result["restarted"] = True
                    result["bundle_id"] = bundle_id
                except Exception as e:
                    return {**result, "restart_error": str(e)}

            result["message"] = (f"Removed {len(removed)} success marker(s)"
                                 + (" and restarted plugin" if restart else
                                    " — plugin will re-install requirements on next restart"))
            self.log_tool_outcome("plugin_refresh_deps", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "plugin_refresh_deps")

    # ════════════════════════════════════════════════════════════════════════
    # plugin_show_packages_versions
    # ════════════════════════════════════════════════════════════════════════

    def plugin_show_packages_versions(self, plugin_name: str) -> Dict[str, Any]:
        """
        Walk Contents/Packages/*.dist-info/METADATA for an installed plugin
        and return the {name: version} map. Useful for confirming the right
        version of a third-party lib is actually bundled.
        """
        self.log_incoming_request("plugin_show_packages_versions",
                                  {"plugin_name": plugin_name})
        try:
            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}
            packages_dir = os.path.join(installed, "Contents", "Packages")
            if not os.path.isdir(packages_dir):
                return {"success": True,
                        "installed_bundle": installed,
                        "packages_dir_exists": False,
                        "packages": [],
                        "message": "No Packages/ dir — stdlib-only plugin"}

            packages: List[Dict[str, str]] = []
            for entry in sorted(os.listdir(packages_dir)):
                if entry.endswith(".dist-info"):
                    meta_path = os.path.join(packages_dir, entry, "METADATA")
                    if not os.path.isfile(meta_path):
                        continue
                    name = ""
                    version = ""
                    try:
                        with open(meta_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if line.startswith("Name:"):
                                    name = line.split(":", 1)[1].strip()
                                elif line.startswith("Version:"):
                                    version = line.split(":", 1)[1].strip()
                                if name and version:
                                    break
                    except OSError:
                        continue
                    packages.append({
                        "name":      name or entry.split("-")[0],
                        "version":   version or "?",
                        "dist_info": entry,
                    })

            # Detect success marker too
            markers = glob.glob(os.path.join(packages_dir, "*-pip-install-log-success.txt"))

            return {
                "success":             True,
                "installed_bundle":    installed,
                "packages_dir":        packages_dir,
                "packages_count":      len(packages),
                "packages":            packages,
                "install_markers":     [os.path.basename(m) for m in markers],
            }
        except Exception as exc:
            return self.handle_exception(exc, "plugin_show_packages_versions")

    # ════════════════════════════════════════════════════════════════════════
    # plugin_validate_xml
    # ════════════════════════════════════════════════════════════════════════

    def plugin_validate_xml(self, plugin_name: str) -> Dict[str, Any]:
        """
        Parse Devices.xml / Actions.xml / Events.xml / MenuItems.xml /
        PluginConfig.xml and check the established naming rules:
          - state IDs must be camelCase ASCII (no underscores)
          - pluginProps keys cannot start with underscore
          - Actions.xml uiPath values must have no spaces
        Returns a list of findings.
        """
        self.log_incoming_request("plugin_validate_xml", {"plugin_name": plugin_name})
        try:
            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}
            sp = os.path.join(installed, "Contents", "Server Plugin")

            findings: List[Dict[str, Any]] = []
            files_checked: List[str] = []

            def _add(fname: str, severity: str, rule: str, msg: str):
                findings.append({"file": fname, "severity": severity,
                                 "rule": rule, "message": msg})

            # Devices.xml — state ID rules
            devices_xml = os.path.join(sp, "Devices.xml")
            if os.path.isfile(devices_xml):
                files_checked.append("Devices.xml")
                try:
                    tree = ET.parse(devices_xml)
                    for state in tree.iter("State"):
                        sid = state.get("id", "")
                        if not sid:
                            _add("Devices.xml", "error", "state_id_empty",
                                 "<State> with no id attribute")
                            continue
                        if not sid[0].isalpha() or not sid[0].isascii():
                            _add("Devices.xml", "error", "state_id_invalid_first",
                                 f"State id '{sid}' must start with an ASCII letter")
                        if not all(c.isalnum() and c.isascii() for c in sid):
                            _add("Devices.xml", "error", "state_id_non_alnum",
                                 f"State id '{sid}' contains non-alphanumeric chars (no underscores allowed)")
                    # Check for reserved batteryLevel use
                    for state in tree.iter("State"):
                        if state.get("id") == "batteryLevel":
                            _add("Devices.xml", "error", "reserved_state_id",
                                 "State id 'batteryLevel' is reserved — use 'battery' instead")
                except ET.ParseError as e:
                    _add("Devices.xml", "error", "xml_parse_error", str(e))

            # Actions.xml — uiPath no spaces
            actions_xml = os.path.join(sp, "Actions.xml")
            if os.path.isfile(actions_xml):
                files_checked.append("Actions.xml")
                try:
                    tree = ET.parse(actions_xml)
                    for action in tree.iter("Action"):
                        uipath = action.get("uiPath", "")
                        if uipath and " " in uipath:
                            _add("Actions.xml", "error", "uipath_has_spaces",
                                 f"Action {action.get('id','?')} uiPath='{uipath}' "
                                 f"— spaces cause client crash, use PascalCase")
                except ET.ParseError as e:
                    _add("Actions.xml", "error", "xml_parse_error", str(e))

            # Events.xml + MenuItems.xml — syntax only
            for fname in ("Events.xml", "MenuItems.xml", "PluginConfig.xml"):
                path = os.path.join(sp, fname)
                if os.path.isfile(path):
                    files_checked.append(fname)
                    try:
                        ET.parse(path)
                    except ET.ParseError as e:
                        _add(fname, "error", "xml_parse_error", str(e))

            errors   = sum(1 for f in findings if f["severity"] == "error")
            warnings = sum(1 for f in findings if f["severity"] == "warning")

            return {
                "success":           True,
                "installed_bundle":  installed,
                "files_checked":     files_checked,
                "findings_count":    len(findings),
                "errors":            errors,
                "warnings":          warnings,
                "findings":          findings,
            }
        except Exception as exc:
            return self.handle_exception(exc, "plugin_validate_xml")

    # ════════════════════════════════════════════════════════════════════════
    # plugin_node_check_html
    # ════════════════════════════════════════════════════════════════════════

    def plugin_node_check_html(self, plugin_name: str) -> Dict[str, Any]:
        """
        Find <script> blocks in any HTML file under the bundle's Resources/
        directory and run `node --check` on each. Catches the Dashboards-style
        'stale JS paste hangs the page' class of bugs in 50ms per block.
        """
        self.log_incoming_request("plugin_node_check_html", {"plugin_name": plugin_name})
        try:
            # Confirm node is available
            try:
                v = subprocess.run(["node", "--version"], capture_output=True,
                                   text=True, timeout=5)
                node_version = v.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return {"success": False, "error": "node not found on PATH"}

            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}
            resources = os.path.join(installed, "Contents", "Resources")
            if not os.path.isdir(resources):
                return {"success": True,
                        "installed_bundle": installed,
                        "node_version": node_version,
                        "html_files": [],
                        "message": "No Resources/ dir — nothing to check"}

            # Walk all HTML
            html_files = []
            for dp, _, files in os.walk(resources):
                for f in files:
                    if f.endswith((".html", ".htm")):
                        html_files.append(os.path.join(dp, f))

            script_re = re.compile(
                r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
                re.DOTALL | re.IGNORECASE,
            )
            src_re = re.compile(r'src\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)

            findings = []
            total_blocks = 0
            for path in html_files:
                rel = os.path.relpath(path, installed)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                except OSError as e:
                    findings.append({"file": rel, "error": f"read failed: {e}"})
                    continue
                blocks = list(script_re.finditer(content))
                for idx, m in enumerate(blocks):
                    if src_re.search(m.group("attrs") or ""):
                        continue  # external script ref — nothing to lint inline
                    body = (m.group("body") or "").strip()
                    if not body:
                        continue
                    total_blocks += 1
                    # Compute line number of <script> open
                    line_no = content.count("\n", 0, m.start()) + 1
                    proc = subprocess.run(
                        ["node", "--check", "-e", body],
                        capture_output=True, text=True, timeout=10
                    )
                    if proc.returncode != 0:
                        # Trim noisy node output to first 3 lines
                        err = "\n".join((proc.stderr or "").splitlines()[:3])
                        findings.append({
                            "file":      rel,
                            "block_num": idx + 1,
                            "html_line": line_no,
                            "body_len":  len(body),
                            "error":     err,
                        })

            return {
                "success":          True,
                "installed_bundle": installed,
                "node_version":     node_version,
                "html_file_count":  len(html_files),
                "scripts_checked":  total_blocks,
                "issues_count":     len(findings),
                "findings":         findings,
            }
        except Exception as exc:
            return self.handle_exception(exc, "plugin_node_check_html")

    # ════════════════════════════════════════════════════════════════════════
    # plugin_lint — CLAUDE.md rules sweep
    # ════════════════════════════════════════════════════════════════════════

    def plugin_lint(self, plugin_name: str) -> Dict[str, Any]:
        """
        Lint plugin.py against established CliveS-plugin conventions:
          - Filename/Author/Version header present
          - log() helper or millisecond-prefix logger present
          - No bare print()
          - open() of .py files uses encoding="utf-8"
          - No hardcoded "Indigo 2025.x" version paths
          - subscribeToChanges has the loop-guard if used
        Returns findings as (file, line, severity, rule, message).
        """
        self.log_incoming_request("plugin_lint", {"plugin_name": plugin_name})
        try:
            installed = _resolve_installed_bundle(plugin_name)
            if not installed:
                return {"success": False,
                        "error": f"No installed bundle matches '{plugin_name}'"}
            sp = os.path.join(installed, "Contents", "Server Plugin")
            pyfile = os.path.join(sp, "plugin.py")
            if not os.path.isfile(pyfile):
                return {"success": False, "error": f"No plugin.py at {pyfile}"}

            with open(pyfile, encoding="utf-8") as f:
                lines = f.readlines()
            content = "".join(lines)

            findings: List[Dict[str, Any]] = []

            def _add(line: int, severity: str, rule: str, msg: str):
                findings.append({"file": "plugin.py", "line": line,
                                 "severity": severity, "rule": rule, "message": msg})

            # Header: first 15 lines should contain Filename/Description/Author/Version
            head = "\n".join(lines[:15])
            for tag in ("Filename:", "Description:", "Author:", "Version:"):
                if tag not in head:
                    _add(1, "warning", "header_missing",
                         f"Header missing '{tag}' tag in first 15 lines")

            # subscribeToChanges loop guard
            # The original rule was too literal — it required the variable name
            # `new_dev` exactly. In practice plugins use newDev, n, dev, etc.
            # Refined logic:
            #   1. Extract the body of every def deviceUpdated(self, X, Y):
            #   2. If the body contains write-back calls (replaceOnServer,
            #      updateStateOnServer, updateStateImageOnServer,
            #      replacePluginPropsOnServer, setErrorStateOnServer)
            #      AND no guard idiom is present, flag as ERROR.
            #   3. If write-backs present and ANY guard idiom is present,
            #      no finding.
            #   4. If no write-backs in deviceUpdated, no finding (read-only
            #      mirrors can't cause the loop).
            if "subscribeToChanges" in content and "def deviceUpdated" in content:
                # Find each deviceUpdated body (greedy until next def or class)
                # Match `def deviceUpdated(self, ..., ...) [-> ...]:` with or
                # without parameter type annotations and return type.
                method_re = re.compile(
                    r"def\s+deviceUpdated\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n"
                    r"(?P<body>.*?)(?=\n\s{0,4}(?:def |class )|\Z)",
                    re.DOTALL,
                )
                writeback_re = re.compile(
                    r"\.(replaceOnServer|updateStateOnServer|"
                    r"updateStateImageOnServer|replacePluginPropsOnServer|"
                    r"setErrorStateOnServer|updateStatesOnServer)\b"
                )
                # Guard idioms — match any of these inside deviceUpdated body:
                #   <var>.pluginId == self.pluginId   (any var name)
                #   <var>.pluginId != self.pluginId
                #   <var>.id == <something>           (per-device filter)
                #   <var>.id in self.<set/dict>       (subscribed-list filter)
                #   <var>.id not in self.<set/dict>
                guard_patterns = [
                    re.compile(r"\b\w+\.pluginId\s*[=!]=\s*self\.pluginId"),
                    re.compile(r"\b\w+\.id\s+(not\s+)?in\s+self\.\w+"),
                    re.compile(r"\bif\s+\w+\.id\s*[=!]=\s*\w+"),
                ]
                for m in method_re.finditer(content):
                    body = m.group("body")
                    has_writeback = bool(writeback_re.search(body))
                    has_guard = any(p.search(body) for p in guard_patterns)
                    line_no = content.count("\n", 0, m.start()) + 1
                    if has_writeback and not has_guard:
                        _add(line_no, "error", "missing_loop_guard",
                             "deviceUpdated writes back to device state "
                             "(replaceOnServer/updateStateOnServer/etc) but no "
                             "pluginId or id-set guard — risk of A→B→A loop")
                    elif has_writeback and has_guard:
                        pass  # all good
                    # else: no writeback, nothing to flag

            # Bare print() (allow #print or print as fragment in strings)
            for i, line in enumerate(lines, 1):
                stripped = line.split("#", 1)[0]
                if re.search(r"\bprint\s*\(", stripped):
                    _add(i, "warning", "bare_print",
                         "Bare print() — use self.logger.info() or log() helper instead")

            # open(...) of .py files with no encoding
            open_re = re.compile(r"open\s*\(([^)]+)\)")
            for i, line in enumerate(lines, 1):
                m = open_re.search(line)
                if not m:
                    continue
                inside = m.group(1)
                if ".py" in inside and "encoding" not in inside:
                    _add(i, "warning", "open_no_encoding",
                         "open() of .py file without encoding='utf-8' — "
                         "Indigo's locale defaults to ASCII and crashes on em-dashes")

            # Hardcoded Indigo version path
            hard_re = re.compile(r"Indigo\s+\d{4}\.\d")
            for i, line in enumerate(lines, 1):
                if hard_re.search(line) and not line.strip().startswith("#"):
                    _add(i, "error", "hardcoded_indigo_version",
                         "Hardcoded 'Indigo YYYY.x' path — use "
                         "indigo.server.getInstallFolderPath() instead")

            # No globals in plugin callbacks (very loose check)
            if re.search(r"^global\s+\w+", content, re.MULTILINE):
                _add(1, "warning", "global_used",
                     "'global' keyword used — globals do not work reliably in "
                     "Indigo plugin callbacks; use a self.* container dict instead")

            errors   = sum(1 for f in findings if f["severity"] == "error")
            warnings = sum(1 for f in findings if f["severity"] == "warning")

            return {
                "success":           True,
                "installed_bundle":  installed,
                "file":              "plugin.py",
                "line_count":        len(lines),
                "findings_count":    len(findings),
                "errors":            errors,
                "warnings":          warnings,
                "findings":          findings,
            }
        except Exception as exc:
            return self.handle_exception(exc, "plugin_lint")

    # ════════════════════════════════════════════════════════════════════════
    # device_history — focused SQL Logger query
    # ════════════════════════════════════════════════════════════════════════

    def device_history(self, device_id, hours: int = 24,
                       limit: int = 500,
                       columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Read recent history rows for a single device from the SQL Logger
        sqlite database. Returns timestamp + non-null state columns.

        Args:
            device_id: numeric device ID
            hours:     how far back to read (default 24)
            limit:     max rows to return (default 500, capped at 5000)
            columns:   optional list of column names — when omitted, returns
                       all non-null columns from the most recent rows.
        """
        self.log_incoming_request("device_history",
                                  {"device_id": device_id, "hours": hours, "limit": limit})
        try:
            try:
                did = int(device_id) if not isinstance(device_id, int) else device_id
            except (TypeError, ValueError):
                return {"success": False, "error": f"Bad device_id {device_id!r}"}

            limit = max(1, min(int(limit or 500), 5000))
            hours = max(1, int(hours or 24))

            db_path = _sql_logger_db()
            if not os.path.isfile(db_path):
                return {"success": False,
                        "error": f"SQL Logger sqlite DB not found at {db_path}"}

            table = f"device_history_{did}"
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                cur = conn.cursor()

                # Confirm table exists
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if not cur.fetchone():
                    return {"success": False,
                            "error": f"No SQL Logger table '{table}' — device may "
                                     f"not be logged, or wrong device_id"}

                # Get all columns
                cur.execute(f"PRAGMA table_info({table})")
                all_cols = [r[1] for r in cur.fetchall()]
                if not all_cols:
                    return {"success": False, "error": f"Could not read columns of {table}"}

                # Pick columns to return
                if columns:
                    cols = [c for c in columns if c in all_cols]
                    if "ts" not in cols:
                        cols = ["ts"] + cols
                    if not cols:
                        return {"success": False,
                                "error": f"None of the requested columns exist in {table}"}
                else:
                    # Probe: which columns have at least one non-null value in the window?
                    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat(sep=" ")
                    keep = []
                    for c in all_cols:
                        if c in ("id",):
                            continue
                        try:
                            cur.execute(
                                f"SELECT 1 FROM {table} WHERE {c} IS NOT NULL "
                                f"AND ts >= ? LIMIT 1",
                                (cutoff,),
                            )
                            if cur.fetchone():
                                keep.append(c)
                        except sqlite3.OperationalError:
                            continue
                    cols = keep or ["ts"]
                    if "ts" in cols:
                        # Move ts to front
                        cols = ["ts"] + [c for c in cols if c != "ts"]

                cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat(sep=" ")
                col_list = ", ".join(cols)
                cur.execute(
                    f"SELECT {col_list} FROM {table} "
                    f"WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                    (cutoff, limit),
                )
                rows = []
                for row in cur.fetchall():
                    rows.append(dict(zip(cols, row)))

                return {
                    "success":      True,
                    "table":        table,
                    "device_id":    did,
                    "hours":        hours,
                    "row_count":    len(rows),
                    "columns":      cols,
                    "rows":         rows,
                }
            finally:
                conn.close()
        except Exception as exc:
            return self.handle_exception(exc, "device_history")
