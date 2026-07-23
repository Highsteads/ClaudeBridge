"""Live device-capability awareness for Claude Bridge.

Indigo exposes what a device can do as live boolean attributes on the device
object itself — ``dev.supportsRGB``, ``dev.supportsWhiteTemperature``,
``dev.supportsHeatSetpoint`` and so on. This module reads them straight off
the live device, so capability awareness works on ANY install, for ANY
device, and is always current — no catalogue, no snapshot, no data to
maintain. (An earlier version vendored a generated catalogue; it was a
cache of exactly these live flags, so it was removed as redundant.)

Two uses:
  * enrich device detail with a capabilities block, and
  * let control tools REFUSE a colour/white/setpoint command the device
    can't do, with a message naming what it DOES support — instead of
    firing it and relaying a cryptic failure.

DISCIPLINE — refuse ONLY on an explicit live ``False``. A device that does
not expose the flag at all (``getattr`` → None) is never blocked: awareness
only ever ADDS a helpful refusal where the device positively says it can't,
it never takes away control on missing information.
"""

from typing import Any, Dict, Optional

# Human labels for the supports* flags, used only to phrase a refusal's
# "it supports …" tail readably.
_FLAG_LABELS = {
    "supportsOnState": "on/off",
    "supportsStatusRequest": "status requests",
    "supportsSensorValue": "a sensor reading",
    "supportsColor": "colour",
    "supportsRGB": "RGB colour",
    "supportsWhite": "a white channel",
    "supportsWhiteTemperature": "white temperature",
    "supportsTwoWhiteLevels": "two white levels",
    "supportsHeatSetpoint": "a heat setpoint",
    "supportsCoolSetpoint": "a cool setpoint",
    "supportsHvacOperationMode": "an HVAC mode",
    "supportsHvacFanMode": "a fan mode",
}


def live_capabilities(dev: Any) -> Dict[str, bool]:
    """Every ``supports*`` boolean the device exposes, read live. {} if none."""
    caps: Dict[str, bool] = {}
    for attr in dir(dev):
        if not attr.startswith("supports"):
            continue
        try:
            value = getattr(dev, attr)
        except Exception:
            continue
        if isinstance(value, bool):
            caps[attr] = value
    return caps


def refusal(dev: Any, flag: str, action_label: str) -> Optional[str]:
    """A refusal message if the device's live ``flag`` is explicitly False,
    else None (proceed).

    Fires ONLY when ``getattr(dev, flag)`` is exactly ``False``. A flag the
    device doesn't expose (None), or a True flag, returns None. The message
    names what the device DOES support so the caller corrects course.
    """
    try:
        value = getattr(dev, flag, None)
    except Exception:
        return None
    if value is not False:
        return None

    supported = sorted(
        _FLAG_LABELS.get(name, name)
        for name, val in live_capabilities(dev).items() if val is True)
    if supported:
        does = "It supports " + ", ".join(supported) + "."
    else:
        does = "It has no controllable capabilities."
    model = getattr(dev, "model", "") or "this device"
    return (f"{action_label} is not supported by this device — {model} reports "
            f"{flag}=false. {does}")
