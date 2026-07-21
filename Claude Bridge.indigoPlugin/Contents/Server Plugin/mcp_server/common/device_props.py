#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    device_props.py
# Description: Reliable reads of ANOTHER plugin's device properties.
# Author:      CliveS & Claude Opus 4.8
# Date:        21-07-2026
# Version:     1.0
#
# WHY THIS EXISTS
# ---------------
# Read from inside Claude Bridge's own plugin host, `dev.pluginProps` is EMPTY
# for most devices owned by a DIFFERENT plugin. Measured live on 21-Jul-2026:
# 18 of 19 ShellyDirect devices returned {} from `dev.pluginProps` while
# `dev.globalProps[dev.pluginId]` returned the full 11-12 key dictionary for
# all 19. `dict(dev)` carries the same empty copy, so every tool that
# serialised a device inherited the hole.
#
# `dev.ownerProps` also returns data, but it can be STALE — on 21-Jul-2026 it
# lagged several saved-prop versions on an ApplianceMonitor device. It is
# therefore a fallback, never the first choice.
#
# The failure is silent and it reads as "the property is not set", which is the
# dangerous part. A duplicate-IP audit reported "no duplicates" while a real
# clash was corrupting energy data, and a plugin-review finding was nearly
# given the wrong severity off the same empty read.
#
# RULE: never read a foreign device's props directly. Call device_props(dev).

from typing import Any, Dict, Optional, Tuple

# Property keys that plugins commonly use to hold a network address. Checked in
# order, after the native `dev.address` attribute. Many plugins leave the native
# attribute EMPTY and keep the real address here — live-confirmed 21-Jul-2026:
# all 19 ShellyDirect devices have an empty `dev.address` and carry the IP in
# the `ip_address` plugin prop, so an address audit reading only the native
# attribute is blind to them.
ADDRESS_PROP_KEYS = (
    "address", "ip_address", "ipAddress", "ip",
    "host", "hostname", "hostName", "deviceAddress",
)


def _safe_getattr(obj: Any, name: str) -> Any:
    """getattr that swallows ANY exception, not just AttributeError.

    These attributes are properties on the Indigo objects, so a failing one
    raises whatever it likes. A props read must never propagate into a tool
    response — an unreliable read is the whole reason this module exists.
    """
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _as_plain_dict(value: Any) -> Optional[Dict[str, Any]]:
    """Coerce an indigo.Dict (or anything mapping-like) to a plain dict.

    Returns None when the value is missing or not mapping-like, so the caller
    can tell "absent" from "present but empty".
    """
    if value is None:
        return None
    try:
        return dict(value)
    except Exception:
        return None


def device_props_with_source(dev) -> Tuple[Dict[str, Any], str]:
    """Return (props, source) for a device, preferring the reliable read.

    Order: globalProps[pluginId] -> pluginProps -> ownerProps.

    globalProps is first because it is the only one measured correct for every
    foreign device. pluginProps comes next because when it IS populated it is
    the owning plugin's live view. ownerProps is last because it can be stale.

    `source` is one of "globalProps", "pluginProps", "ownerProps" or "empty",
    and is what lets a caller report "no properties found" honestly instead of
    silently treating an empty read as "property absent".
    """
    if dev is None:
        return {}, "empty"

    plugin_id = _safe_getattr(dev, "pluginId") or ""
    if plugin_id:
        global_props = _safe_getattr(dev, "globalProps")
        if global_props is not None:
            try:
                scoped = global_props[plugin_id]
            except Exception:
                scoped = None
            props = _as_plain_dict(scoped)
            if props:
                return props, "globalProps"

    props = _as_plain_dict(_safe_getattr(dev, "pluginProps"))
    if props:
        return props, "pluginProps"

    # Last resort. Can lag the saved props, so only used when nothing else has
    # anything at all.
    props = _as_plain_dict(_safe_getattr(dev, "ownerProps"))
    if props:
        return props, "ownerProps"

    return {}, "empty"


def device_props(dev) -> Dict[str, Any]:
    """Return a device's plugin properties, reliably, as a plain dict."""
    return device_props_with_source(dev)[0]


def device_prop(dev, key: str, default: Any = None) -> Any:
    """Read a single plugin property from a device."""
    return device_props(dev).get(key, default)


def device_address(dev) -> str:
    """Return a device's network/bus address, native attribute or props.

    The native `dev.address` wins when set. Otherwise the first populated key
    in ADDRESS_PROP_KEYS is used, so devices whose plugin keeps the address in
    its own props are not invisible to address auditing.
    """
    native = _safe_getattr(dev, "address") or ""
    native = str(native).strip()
    if native:
        return native

    props = device_props(dev)
    for key in ADDRESS_PROP_KEYS:
        value = props.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return ""


def device_dict(dev) -> Dict[str, Any]:
    """dict(dev), with `pluginProps` repaired and its source recorded.

    Drop-in replacement for `dict(dev)` anywhere a device is serialised for a
    tool response or the vector store. Adds `pluginPropsSource` so an empty
    result is explicit rather than being read as "this device has no props".
    """
    try:
        data = dict(dev)
    except Exception:
        return {}

    props, source = device_props_with_source(dev)
    data["pluginProps"] = props
    data["pluginPropsSource"] = source

    # Keep the derived address alongside the native one. Callers auditing
    # addresses should use this rather than `address`.
    try:
        data["resolvedAddress"] = device_address(dev)
    except Exception:
        pass

    return data
