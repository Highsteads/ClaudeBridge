"""Battery-level reader that covers every convention on the estate.

Indigo devices carry a battery percentage in one of three places, and no single
one covers everything:
  - native `dev.batteryLevel` property (Z-Wave sensors)
  - a custom `batteryLevel` state
  - a custom `battery` state — the convention CliveS's own plugins use
    (Zigbee2MQTTBridge et al.), because `batteryLevel` is a RESERVED native name
    (writing a custom state called batteryLevel is silently routed to the native
    property). On this estate 43 devices report via `battery` vs only 12 via
    `batteryLevel`, so reading `batteryLevel` alone misses most of the fleet.

Two conventions are NOT percentages and must not be read as one:
  - binary OK/LOW flags: Ecowitt and UniversalZWaveSensor publish `battery` as
    0/1 alongside a `batteryLow` bool that carries the truth (Ecowitt: 0 + False
    = OK; UZWS: 1 + True = LOW). The value alone is ambiguous — honour
    `batteryLow` whenever the reading is 0 or 1 and that state exists.
  - a bare 0 with no `batteryLow` companion means "unknown / externally
    powered" (z2m reports 0 for USB-fed FP300s), not a flat cell. A genuinely
    flat battery stops reporting long before 0, and the stale-device audit is
    what catches that case.

Returns an int percentage, or None if the device has no usable battery reading.
"""

from typing import Any, Optional


def _is_low_flag(value: Any) -> bool:
    """Read a batteryLow companion state as a boolean.

    Indigo hands some custom states back as the STRINGS "True"/"False", and
    bool("false") is True — which would report a healthy sensor as flat. An
    unrecognised value is treated as NOT low, matching the plain-bool default.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _clamp(pct: int) -> Optional[int]:
    """Keep a percentage inside 0-100.

    Sentinels leak out of real hardware — 255 for "unknown" is the classic, and
    negatives turn up on a bad parse. Reporting 255% is obvious nonsense, but
    reporting it in a LOW-battery sweep is worse: it sorts as healthy and hides
    a sensor that may genuinely be failing. Out of range means unknown.
    """
    if pct < 0 or pct > 100:
        return None
    return pct


def battery_pct(dev: Any) -> Optional[int]:
    states = getattr(dev, "states", {}) or {}
    for key in ("batteryLevel", "battery"):
        v = states.get(key)
        if v in (None, ""):
            continue
        try:
            pct = int(float(v))
        except (ValueError, TypeError):
            continue
        if pct <= 1 and "batteryLow" in states:
            return max(pct, 1) if _is_low_flag(states.get("batteryLow")) else None
        if pct == 0:
            return None
        return _clamp(pct)
    nat = getattr(dev, "batteryLevel", None)
    if nat not in (None, ""):
        try:
            return _clamp(int(float(nat)))
        except (ValueError, TypeError):
            pass
    return None
