#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    _schema.py
# Description: Schema fragments and small argument helpers shared by the
#              toolset modules, so "a device, by id or name" is written once.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from typing import Any, Dict, Iterable, Optional

ID_OR_NAME = {"anyOf": [{"type": "number"}, {"type": "string"}]}


def id_or_name(description: str) -> Dict[str, Any]:
    return {**ID_OR_NAME, "description": description}


def enum(values: Iterable[str], description: str) -> Dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": description}


def number(description: str) -> Dict[str, Any]:
    return {"type": "number", "description": description}


def integer(description: str) -> Dict[str, Any]:
    return {"type": "integer", "description": description}


def boolean(description: str) -> Dict[str, Any]:
    return {"type": "boolean", "description": description}


def string(description: str) -> Dict[str, Any]:
    return {"type": "string", "description": description}


DEVICE = id_or_name(
    "Device id, or its name. A name must match exactly, or match one device "
    "confidently; an ambiguous name is refused with the candidates."
)
DELAY = number("Seconds to wait before acting (default 0 = now)")
DURATION = number("Seconds until the change reverts automatically (default 0 = stays)")
FOLDER_ID = id_or_name("Target folder id (0 = root)")

AUTOMATION_KINDS = ("trigger", "schedule", "action_group")
AUTOMATION_KIND = enum(AUTOMATION_KINDS, "Which kind of automation")
AUTOMATION_ID = id_or_name("Numeric id (preferred) or exact name")


def refuse(message: str, **extra) -> Dict[str, Any]:
    """The standard failure reply."""
    return {"success": False, "error": message, **extra}


def bad_choice(field: str, value: Any, choices: Iterable[str]) -> Dict[str, Any]:
    return refuse(f"{field} must be one of {', '.join(choices)} — got {value!r}")


def unused_args(tool: str, choice: str, given: Dict[str, Any],
                allowed: Iterable[str]) -> Optional[Dict[str, Any]]:
    """Refuse arguments the chosen action does not use.

    A consolidated tool carries every action's arguments in one schema, so the
    dispatch layer's unknown-argument check cannot see that `threshold` means
    nothing to audit(check="home"). Silently ignoring it is the fault that check
    exists to stop: the caller thinks the value applied. None-valued arguments
    count as not given, since some clients send every property.
    """
    allowed = set(allowed)
    stray = sorted(k for k, v in given.items() if v is not None and k not in allowed)
    if not stray:
        return None
    return refuse(
        f"{tool}: argument(s) {', '.join(stray)} do not apply to {choice!r}"
        + (f" — it takes {', '.join(sorted(allowed))}" if allowed else " — it takes none")
    )


def coerce_bool(value: Any) -> bool:
    """A JSON true is True; the STRING "false" is False (bool("false") is True)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")
