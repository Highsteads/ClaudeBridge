#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    script_refs.py
# Description: Single owner of the Indigo script-folder scan used by every
#              reverse-dependency tool (dependency_map, audit_variables,
#              find_automation_references).
# Author:      CliveS & Claude Opus 5
# Date:        26-08-2026
# Version:     1.0

"""
Scan the Indigo script folders for references to an entity.

getDependencies() is the authoritative reverse-dependency API, but it covers
only triggers, schedules, action groups, control pages, devices and variables.
A Python script that drives a device is invisible to it, and so is a plugin
that hard-codes the ID in its own source.

This module owns the script half of that answer. It lives in common/ rather
than in one tool package because three separate tools need the same scan, and
the last time a folder list was duplicated per-tool one copy silently returned
a single folder — which made audit_variables report the whole estate as
unreferenced.
"""

import os
import re
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

try:
    import indigo
except ImportError:  # pragma: no cover - exercised only outside Indigo
    indigo = None


# An Indigo entity ID is 8-12 digits. Anchored on word boundaries so a longer
# number containing this one does not match.
_ID_DIGITS = re.compile(r"\b(\d{8,12})\b")


def scripts_dirs() -> List[str]:
    """
    Return EVERY existing Indigo script folder.

    Both sibling folders can hold automation that references entity IDs:
      - <PA base>/Scripts        — scripts called directly by schedules/triggers
      - <PA base>/Python Scripts — the main automation-logic folder (the bulk)

    They sit at the Perceptive Automation ROOT, one level above the versioned
    install folder, so they survive an Indigo upgrade.
    """
    if indigo is None:
        return []
    pa_base = os.path.dirname(indigo.server.getInstallFolderPath())
    candidates = [
        os.path.join(pa_base, "Scripts"),
        os.path.join(pa_base, "Python Scripts"),
    ]
    return [d for d in candidates if os.path.isdir(d)]


def iter_script_files(script_dirs) -> Iterator[Tuple[str, str]]:
    """
    Yield (display_name, content) for every .py file across the given folders.

    The display name carries the folder prefix when more than one folder is in
    play, so a caller can tell two same-named scripts apart. open() forces
    UTF-8 (Indigo's embedded Python defaults to ASCII) and tolerates the odd
    bad byte rather than aborting the whole scan on one file.
    """
    if isinstance(script_dirs, str):
        script_dirs = [script_dirs]
    present = [d for d in script_dirs if os.path.isdir(d)]
    multi = len(present) > 1
    for d in present:
        folder = os.path.basename(d)
        for entry in sorted(os.scandir(d), key=lambda e: e.name.lower()):
            if not entry.name.endswith(".py") or not entry.is_file():
                continue
            name = f"{folder}/{entry.name}" if multi else entry.name
            try:
                with open(entry.path, "r", encoding="utf-8", errors="replace") as fh:
                    yield name, fh.read()
            except OSError:
                continue


def scan_scripts_for_ids(script_dirs) -> Dict[int, List[str]]:
    """
    Bulk scan: {numeric_id: [script_name, ...]} for every 8-12 digit ID found.

    Use this when sweeping the whole estate (audit_variables, find_conflicts).
    For a single entity, find_script_references is cheaper to read and carries
    line numbers.
    """
    id_map: Dict[int, List[str]] = {}
    for name, content in iter_script_files(script_dirs):
        for match in _ID_DIGITS.findall(content):
            iid = int(match)
            id_map.setdefault(iid, [])
            if name not in id_map[iid]:
                id_map[iid].append(name)
    return id_map


def _quoted_name_re(entity_name: str) -> re.Pattern:
    """Match the name only inside a quoted string.

    An unquoted match would fire on any prose mentioning the device in a
    comment. Requiring quotes does not make a name match certain — a quoted
    "TV" can still appear in unrelated text — which is why every name match is
    reported with matched_by='name' for the caller to judge.
    """
    escaped = re.escape(entity_name)
    return re.compile(rf"""["']{escaped}["']""")


def find_script_references(
    entity_id: int,
    entity_name: Optional[str] = None,
    script_dirs: Optional[Sequence[str]] = None,
) -> List[Dict[str, object]]:
    """
    Find every script referencing one entity, by numeric ID and by quoted name.

    Returns one entry per script:
        {"script": "Python Scripts/Kitchen_Lights_Off.py",
         "lines": [64],
         "matched_by": ["id"]}

    Line numbers are 1-indexed. A script matching both ways reports both in
    matched_by with the line numbers merged.
    """
    if script_dirs is None:
        script_dirs = scripts_dirs()

    id_pattern = re.compile(rf"\b{entity_id}\b")
    name_pattern = _quoted_name_re(entity_name) if entity_name else None

    found: List[Dict[str, object]] = []
    for name, content in iter_script_files(script_dirs):
        lines: Dict[int, None] = {}
        matched_by: List[str] = []
        for lineno, line in enumerate(content.splitlines(), start=1):
            if id_pattern.search(line):
                lines[lineno] = None
                if "id" not in matched_by:
                    matched_by.append("id")
            elif name_pattern is not None and name_pattern.search(line):
                lines[lineno] = None
                if "name" not in matched_by:
                    matched_by.append("name")
        if matched_by:
            found.append({
                "script":     name,
                "lines":      sorted(lines),
                "matched_by": matched_by,
            })
    return found
