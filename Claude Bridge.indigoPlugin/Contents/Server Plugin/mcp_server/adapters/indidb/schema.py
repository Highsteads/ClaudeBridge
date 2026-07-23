"""
Decode tables for Indigo's .indiDb database records.

Every table here comes from the first-hand harvest of a live 2025.2 database
(224 devices, 90+ triggers/schedules) documented in the indigo-reference
library (file-formats.md, 12-Jun-2026). Codes marked "(unverified)" are
inferred from enum gaps and have never been observed in a real database —
they decode with the caveat attached so downstream output stays honest.
"""

from typing import Any, Dict, Optional

# ── Trigger record Class codes (TriggerList) ─────────────────────────────────
TRIGGER_CLASSES: Dict[int, str] = {
    501: "device state changed",
    502: "variable changed",
    509: "server startup",
    598: "plugin-defined event",
}

# ── DeviceStateChange codes (trigger Class 501) ──────────────────────────────
DEVICE_STATE_CHANGE_CODES: Dict[int, str] = {
    110: "becomes on/true",
    111: "becomes off/false",
    112: "becomes equal to value",
    113: "becomes not equal to value (unverified)",
    114: "becomes greater than value (unverified)",
    115: "becomes less than value",
    116: "changes (any change)",
}

# ── VarChange codes (trigger Class 502) ──────────────────────────────────────
VAR_CHANGE_CODES: Dict[int, str] = {
    0: "becomes true",
    1: "becomes false",
}

# ── Condition dict Type codes (shared by Trigger / TDTrigger / ActionGroup) ──
CONDITION_TYPES: Dict[int, str] = {
    0:   "always",
    1:   "only if dark (night)",
    2:   "only if daylight",
    3:   "variable comparison",
    5:   "time/date window",
    7:   "device state comparison",
    100: "compound",
}

# VarState codes inside a Type 3 condition.
VAR_STATE_CODES: Dict[int, str] = {
    0: "variable is true",
    1: "variable is false",
}

# DevComp codes inside a Type 7 condition.
DEV_COMP_CODES: Dict[int, str] = {
    0: "is on/true",
    1: "is off/false",
    5: "numeric comparison against value",
}

# TimeDateCompareOperator codes inside a Type 5 condition.
TIME_DATE_OPERATORS: Dict[int, str] = {
    2: "is after start time",
    4: "is between start and end",
    5: "is not between start and end",
}

# Logic code inside a Type 100 compound condition.
# Live-verified 23-Jul-2026 by semantics: a trigger with two DISJOINT time
# windows (21:00-24:00 / 00:00-06:00) stores Logic 0 — only OR can satisfy
# that — while "var A false AND var B false" pairs store Logic 1. The
# previous {0: AND} assignment was inverted (mis-inferred from a survey
# where every sampled compound happened to be single-condition or AND).
CONDITION_LOGIC: Dict[int, str] = {
    0: "OR (any)",
    1: "AND (all)",
}

# ── Action step Class codes (<Action> entries in ActionSteps) ────────────────
ACTION_CLASS_DEVICE       = 1
ACTION_CLASS_THERMOSTAT   = 3
ACTION_CLASS_UNIVERSAL    = 9
ACTION_CLASS_EXEC_GROUP   = 100
ACTION_CLASS_SCRIPT       = 101
ACTION_CLASS_VARIABLE     = 201
ACTION_CLASS_PLUGIN       = 999

ACTION_CLASSES: Dict[int, str] = {
    ACTION_CLASS_DEVICE:     "device action",
    ACTION_CLASS_THERMOSTAT: "thermostat action",
    ACTION_CLASS_UNIVERSAL:  "device utility action",
    ACTION_CLASS_EXEC_GROUP: "execute action group",
    ACTION_CLASS_SCRIPT:     "execute script",
    ACTION_CLASS_VARIABLE:   "set variable",
    ACTION_CLASS_PLUGIN:     "plugin action",
}

# DeviceAction codes — verified 23-Jul-2026 against the live runtime enum
# (indigo.kDeviceAction dump). NB Lock=28/Unlock=29: the earlier 29=lock
# claim came from misreading LockManager trigger NAMES ("Lock <person>
# Front Door Unlock Code") — those PIN triggers unlock, and store 29.
DEVICE_ACTION_CODES: Dict[int, str] = {
    0:  "all off",
    1:  "all lights on",
    2:  "all lights off",
    4:  "turn on",
    5:  "turn off",
    6:  "toggle",
    7:  "set brightness",          # DeviceActionValue is 0-1000 (TENTHS of a %)
    8:  "brighten by",
    9:  "dim by",
    10: "set colour levels",
    11: "request status",
    28: "lock",
    29: "unlock",
    30: "open",
    31: "close",
}

# HVACAction codes on Class 3 steps (indigo.kThermostatAction, runtime dump
# 23-Jul-2026).
THERMOSTAT_ACTION_CODES: Dict[int, str] = {
    0:   "set heat setpoint",
    1:   "set cool setpoint",
    2:   "increase heat setpoint",
    3:   "increase cool setpoint",
    4:   "decrease heat setpoint",
    5:   "decrease cool setpoint",
    7:   "request status (all)",
    8:   "request mode",
    9:   "request equipment state",
    10:  "request temperatures",
    11:  "request humidities",
    12:  "request deadbands",
    13:  "request setpoints",
    100: "set HVAC mode",
    101: "set fan mode",
}

# DeviceAction codes on Class 9 steps (indigo.kUniversalAction, runtime dump
# 23-Jul-2026).
UNIVERSAL_ACTION_CODES: Dict[int, str] = {
    11:  "request status",
    30:  "beep",
    100: "energy usage update",
    101: "energy accumulator reset",
}

# VarAction codes (action Class 201).
VAR_ACTION_CODES: Dict[int, str] = {
    0: "set to value",
}

# ── Schedule (TDTrigger) timing codes ────────────────────────────────────────
TIME_TYPES: Dict[int, str] = {
    0: "absolute time of day",     # Time = seconds since midnight
    1: "sunrise-relative (unverified)",
    2: "sun-relative",             # SunDelta = signed seconds offset (sunset observed)
    3: "repeating interval",       # Countdown = interval in seconds
}

DATE_TYPES: Dict[int, str] = {
    0: "every day",
    2: "specific/start date",
}


def label(table: Dict[int, str], code: Any, prefix: str = "code") -> str:
    """Human label for a code, always carrying the raw code for traceability."""
    if not isinstance(code, int):
        return f"unknown ({prefix} {code!r})"
    name = table.get(code)
    if name is None:
        return f"unknown ({prefix} {code})"
    return f"{name} ({prefix} {code})"


def seconds_to_hhmm(seconds: Any) -> Optional[str]:
    """Seconds-since-midnight -> 'HH:MM' (None if not a sane int)."""
    if not isinstance(seconds, int) or seconds < 0 or seconds >= 86400:
        return None
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"
