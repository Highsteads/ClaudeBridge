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

Returns an int percentage, or None if the device has no usable battery reading.
"""

from typing import Any, Optional


def battery_pct(dev: Any) -> Optional[int]:
    states = getattr(dev, "states", {}) or {}
    for key in ("batteryLevel", "battery"):
        v = states.get(key)
        if v not in (None, ""):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                pass
    nat = getattr(dev, "batteryLevel", None)
    if nat not in (None, ""):
        try:
            return int(nat)
        except (ValueError, TypeError):
            pass
    return None
