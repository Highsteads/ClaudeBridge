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
            return max(pct, 1) if states.get("batteryLow") else None
        if pct == 0:
            return None
        return pct
    nat = getattr(dev, "batteryLevel", None)
    if nat not in (None, ""):
        try:
            return int(nat)
        except (ValueError, TypeError):
            pass
    return None
