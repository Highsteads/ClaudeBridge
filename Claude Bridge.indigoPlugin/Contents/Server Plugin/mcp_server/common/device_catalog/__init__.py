"""Advisory device-capability catalogue for Claude Bridge.

Wraps the vendored snapshot of CliveS's own indigo-device-catalog and
answers "what can this device actually do?" — capabilities that Indigo's
scripting API exposes only indirectly (a plugin knows its dimmer does
colour; the IOM makes you infer it). Two uses:

  * enrich device detail with a capabilities block, and
  * let control tools REFUSE a colour/white/setpoint command the
    catalogue says can't work, with a message naming what the device
    DOES support — instead of firing it and relaying a cryptic failure.

CORE DISCIPLINE — advisory, never a gate on missing data. A refusal is
returned ONLY when a profile exists for the device AND that profile
explicitly carries the flag as False. An uncataloged device, an
unreadable device, or a profile with no such flag all pass through
untouched: the catalogue only ever ADDS knowledge, it never blocks
control it lacks data for.

The snapshot import is guarded — a corrupt or missing generated file
degrades to an empty catalogue (every lookup misses) with a logged
error, because this module is imported on the tool-registration path
and an unguarded failure here would take the whole tool surface down.
"""

import logging
from typing import Any, Dict, Optional, Tuple

_logger = logging.getLogger("Plugin.device_catalog")

try:
    from . import catalog_snapshot as _snapshot
    _PROFILES = dict(_snapshot.PROFILES)
    _META = dict(_snapshot.SNAPSHOT_META)
except Exception:  # noqa: BLE001 — a corrupt generated file can raise anything
    _logger.exception(
        "device catalogue snapshot failed to load — capability awareness "
        "disabled (all profile lookups will miss). Regenerate with "
        "scripts/generate_catalog_snapshot.py")
    _PROFILES = {}
    _META = {}


def _ids(dev: Any) -> Tuple[str, str]:
    """(pluginId, deviceTypeId) from a live Indigo device OR a serialised
    device dict. Non-string / missing ids come back as ('', '')."""
    if isinstance(dev, dict):
        plugin_id = dev.get("pluginId", "")
        type_id = dev.get("deviceTypeId", "")
    else:
        plugin_id = getattr(dev, "pluginId", "")
        type_id = getattr(dev, "deviceTypeId", "")
    if not isinstance(plugin_id, str) or not isinstance(type_id, str):
        return "", ""
    return plugin_id, type_id


def profile_for(dev: Any) -> Optional[Dict[str, Any]]:
    """Catalogue profile for a device, or None when uncataloged.

    Built-in / interface devices (empty pluginId) and unknown
    (pluginId, deviceTypeId) pairs miss cleanly rather than raising.
    """
    plugin_id, type_id = _ids(dev)
    if not plugin_id or not type_id:
        return None
    return _PROFILES.get((plugin_id, type_id))


def capabilities(dev: Any) -> Dict[str, Any]:
    """The capability flag map for a device ({} when uncataloged)."""
    profile = profile_for(dev)
    if not profile:
        return {}
    caps = profile.get("capabilities")
    return dict(caps) if isinstance(caps, dict) else {}


def refusal(dev: Any, flag: str, action_label: str) -> Optional[str]:
    """A refusal message if the catalogue says this device can't do
    `action_label`, else None (proceed).

    Returns a message ONLY when a profile exists AND `flag` is present
    and explicitly False. Every other case — uncataloged device, profile
    without that flag, flag True — returns None so the command proceeds.
    The message names what the device DOES support so the caller can
    correct course or report it plainly.
    """
    profile = profile_for(dev)
    if not profile:
        return None
    caps = profile.get("capabilities")
    if not isinstance(caps, dict) or caps.get(flag) is not False:
        return None

    supported = sorted(
        _FLAG_LABELS.get(name, name)
        for name, value in caps.items() if value is True)
    if supported:
        does = "it supports " + ", ".join(supported)
    else:
        does = "the catalogue lists no controllable capabilities for it"
    model = profile.get("model") or _ids(dev)[1] or "this device type"
    return (f"{action_label} is not supported by this device — the device "
            f"catalogue lists {flag}=false for {model}. {does[0].upper()}{does[1:]}.")


# Human labels for the supports* flags, used only to phrase a refusal's
# "it supports …" tail readably.
_FLAG_LABELS = {
    "supportsOnState": "on/off",
    "supportsStatusRequest": "status requests",
    "supportsSensorValue": "a sensor reading",
    "supportsColor": "colour",
    "supportsRGB": "RGB colour",
    "supportsWhite": "a white channel",
    "supportsWhiteTemperature": "white-temperature",
    "supportsHeatSetpoint": "a heat setpoint",
    "supportsCoolSetpoint": "a cool setpoint",
    "supportsHvacOperationMode": "an HVAC mode",
    "supportsHvacFanMode": "a fan mode",
}


def meta() -> Dict[str, Any]:
    """Snapshot provenance ({} when the snapshot failed to load — the
    diagnosable signal that the vendored catalogue itself is broken)."""
    return dict(_META)


def profile_count() -> int:
    return len(_PROFILES)
