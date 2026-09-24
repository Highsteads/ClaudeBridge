#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    restart_watch.py
# Description: Watch the event log across a plugin restart and say how it went.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

"""
What a plugin logged while it restarted.

restart_plugin used to return "restart requested" and nothing else, so every
restart was followed by a status check and a log search to learn whether it
had come back and what it said on the way. This module remembers where the
day's log file ended when the restart was asked for, reads only what was
written after that, and picks out the lines that belong to the plugin:
Indigo's own "Stopping/Starting/Started plugin" lines, and everything the
plugin logged under its own name ("Sigenergy Manager", "Sigenergy Manager
Error"...).
"""

import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\t([^\t]*)\t(.*)$")
_PROBLEM_RE = re.compile(r"\b(error|warning)\b", re.I)

# Indigo writes these under the "Application" source, naming the plugin as
# "<display name> <version>" in quotes.
_STARTED_RE = re.compile(r'^Started plugin "(?P<label>.+)"')


def _day_file(log_root: str, day: date) -> str:
    return os.path.join(log_root, f"{day.strftime('%Y-%m-%d')} Events.txt")


def log_position(log_root: str, today: Optional[date] = None) -> Tuple[date, int]:
    """Where today's log ends right now: (day, byte offset)."""
    day = today or date.today()
    try:
        return day, os.path.getsize(_day_file(log_root, day))
    except OSError:
        return day, 0


def read_since(log_root: str, position: Tuple[date, int],
               today: Optional[date] = None) -> List[Dict[str, str]]:
    """Every log entry written after `position`, continuation lines folded in.

    Crosses midnight: when the day has changed it reads the rest of the old
    file and then the new one from its start.
    """
    start_day, offset = position
    now_day = today or date.today()
    files = [(_day_file(log_root, start_day), offset)]
    if now_day != start_day:
        files.append((_day_file(log_root, now_day), 0))
    entries: List[Dict[str, str]] = []
    for path, from_byte in files:
        try:
            with open(path, "rb") as fh:
                fh.seek(from_byte)
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        last: Optional[Dict[str, str]] = None
        for line in text.splitlines():
            m = _LINE_RE.match(line)
            if m:
                last = {"TimeStamp": m.group(1), "TypeStr": m.group(2),
                        "Message": m.group(3)}
                entries.append(last)
            elif last is not None:
                last["Message"] += "\n" + line
    return entries


# What Indigo appends to a plugin's name for its non-Info log lines.
_LEVEL_SUFFIXES = frozenset({"Error", "Warning", "Debug", "Critical"})


def _names_plugin(message: str, display_name: str) -> bool:
    """Whether an Application line quotes "<display name> <version>". The
    version holds no space, so "Widget Pro 2.0" is not "Widget"."""
    return re.search('"' + re.escape(display_name) + r' [^" ]+"', message) is not None


def _belongs(entry: Dict[str, str], display_name: str) -> bool:
    source = entry.get("TypeStr", "")
    if source == display_name:
        return True
    if source.startswith(display_name + " ") and \
            source[len(display_name) + 1:] in _LEVEL_SUFFIXES:
        return True
    # Indigo's own lines about the plugin quote it with its version — under
    # "Application" normally, "Error" when a start fails.
    return _names_plugin(entry.get("Message", ""), display_name)


def summarise(entries: List[Dict[str, str]], display_name: str) -> Dict[str, Any]:
    """The plugin's own lines from a restart, and what they add up to."""
    own = [e for e in entries if _belongs(e, display_name)]
    started_label = None
    for e in own:
        m = _STARTED_RE.match(e.get("Message", ""))
        if m and e.get("TypeStr", "").startswith("Application"):
            started_label = m.group("label")
    version = None
    if started_label and started_label.startswith(display_name + " "):
        version = started_label[len(display_name) + 1:].strip() or None
    problems = [e for e in own if _PROBLEM_RE.search(e.get("TypeStr", ""))]
    return {
        "started":  started_label is not None,
        "version":  version,
        "errors":   sum(1 for e in problems if re.search(r"\berror\b", e["TypeStr"], re.I)),
        "warnings": sum(1 for e in problems if not re.search(r"\berror\b", e["TypeStr"], re.I)),
        "log":      own,
    }
