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

import os
import plistlib
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, FrozenSet, Optional, Tuple

try:
    import indigo
except ImportError:
    pass

from ..security.secret_redactor import is_credential_name

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


# ── Credential masking ───────────────────────────────────────────────────────
#
# A device's props can hold its plugin's credentials: Email+ keeps the SMTP
# password in serverPassword, UniFiHealth the controller password in password.
# Both are marked secure="true" in their Devices.xml, which the Indigo client
# honours and a raw dict(dev) does not — every read-scope device tool returned
# them in clear. Masked here, where props leave the plugin.

MASK = "********"

# Names the shared credential test misses. It already catches pin, pass, key,
# token and secret; these are the usual spellings it does not.
_EXTRA_CREDENTIAL_NAME = re.compile(r"(pwd|psk|passcode|passphrase)", re.IGNORECASE)

# The dict(dev) keys that carry props: the owner's view, the repaired read,
# the shared set, and globalProps, which holds EVERY plugin's props by id.
_PROP_BLOCKS = ("pluginProps", "ownerProps", "sharedProps")

_SECURE_LOCK = threading.Lock()
_SECURE_BY_PATH: Dict[str, Tuple[float, FrozenSet[str]]] = {}
# Bundle id -> the bundle's Contents folder, for every installed plugin.
_CONTENTS_BY_PLUGIN: Dict[str, str] = {}
# None = never scanned. Not 0.0: time.monotonic() counts from boot, so on a
# Mac up for less than _PLUGIN_RESCAN_SECONDS a 0.0 made the first scan look
# recent and skipped it, leaving secure="true" fields unmasked for the first
# minutes after every reboot (found by CI, whose runners are freshly booted).
_PLUGIN_SCAN_AT: Optional[float] = None
_PLUGIN_RESCAN_SECONDS = 300.0

# Test hook: a folder of .indigoPlugin bundles to use instead of Indigo's own.
PLUGINS_DIR_OVERRIDE: Optional[str] = None


def _is_credential_key(name: Any) -> bool:
    text = str(name or "")
    return is_credential_name(text) or bool(_EXTRA_CREDENTIAL_NAME.search(text))


def _plugins_dir() -> Optional[str]:
    if PLUGINS_DIR_OVERRIDE:
        return PLUGINS_DIR_OVERRIDE
    try:
        base = indigo.server.getInstallFolderPath()
    except Exception:
        return None
    return os.path.join(base, "Plugins") if isinstance(base, str) and base else None


def _contents_for(plugin_id: str) -> Optional[str]:
    """The Contents folder of the plugin with this bundle id. The map is
    rebuilt at most every _PLUGIN_RESCAN_SECONDS, when an id is missing."""
    global _PLUGIN_SCAN_AT
    path = _CONTENTS_BY_PLUGIN.get(plugin_id)
    if path is not None or (_PLUGIN_SCAN_AT is not None
                             and time.monotonic() - _PLUGIN_SCAN_AT < _PLUGIN_RESCAN_SECONDS):
        return path
    _PLUGIN_SCAN_AT = time.monotonic()
    folder = _plugins_dir()
    if not folder or not os.path.isdir(folder):
        return None
    found: Dict[str, str] = {}
    for entry in os.listdir(folder):
        if not entry.endswith(".indigoPlugin"):
            continue
        contents = os.path.join(folder, entry, "Contents")
        try:
            with open(os.path.join(contents, "Info.plist"), "rb") as fh:
                bundle_id = plistlib.load(fh).get("CFBundleIdentifier")
        except Exception:
            continue
        if bundle_id:
            found[str(bundle_id)] = contents
    _CONTENTS_BY_PLUGIN.clear()
    _CONTENTS_BY_PLUGIN.update(found)
    return found.get(plugin_id)


def _secure_fields(plugin_id: str, xml_name: str = "Devices.xml") -> FrozenSet[str]:
    """Field ids the plugin's Devices.xml (or PluginConfig.xml, for its
    settings) marks secure="true", cached by the file's path and mtime. Any
    failure gives an empty set: name-based masking still applies, so a broken
    lookup never un-masks anything."""
    if not plugin_id:
        return frozenset()
    try:
        with _SECURE_LOCK:
            contents = _contents_for(plugin_id)
            path = (os.path.join(contents, "Server Plugin", xml_name)
                    if contents else None)
            if not path or not os.path.isfile(path):
                return frozenset()
            mtime = os.stat(path).st_mtime
            cached = _SECURE_BY_PATH.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
            ids = frozenset(
                str(el.get("id")) for el in ET.parse(path).iter()
                if el.get("id") and str(el.get("secure", "")).strip().lower() == "true")
            _SECURE_BY_PATH[path] = (mtime, ids)
            return ids
    except Exception:
        return frozenset()


def _masked(value: Any) -> bool:
    """Worth masking: a non-empty string or a number (a PIN can be an int)."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, str):
        return value != ""
    return isinstance(value, (int, float))


def redact_props(props: Any, plugin_id: str = "", xml_name: str = "Devices.xml") -> Any:
    """A copy of one plugin's props with credential values replaced by MASK.

    A value is masked when its key reads as a credential name, or when the
    owning plugin's Devices.xml (PluginConfig.xml for plugin settings)
    declares that field secure."""
    if not isinstance(props, dict):
        return props
    secure = _secure_fields(plugin_id, xml_name)
    return {k: (MASK if _masked(v) and (_is_credential_key(k) or str(k) in secure) else v)
            for k, v in props.items()}


def redact_device_data(data: Dict[str, Any], plugin_id: str = "") -> Dict[str, Any]:
    """Mask credentials in every props block of a serialised device, in place."""
    for block in _PROP_BLOCKS:
        if isinstance(data.get(block), dict):
            data[block] = redact_props(data[block], plugin_id)
    gp = data.get("globalProps")
    if gp is not None:
        try:
            plain = {str(pid): _as_plain_dict(scoped) for pid, scoped in dict(gp).items()}
            data["globalProps"] = {pid: redact_props(scoped, pid) if scoped is not None else None
                                   for pid, scoped in plain.items()}
        except Exception:
            data["globalProps"] = {}
    return data


def device_dict(dev) -> Dict[str, Any]:
    """dict(dev), with `pluginProps` repaired and its source recorded, and
    credential values masked (see redact_device_data).

    Drop-in replacement for `dict(dev)` anywhere a device is serialised for a
    tool response or the entity index. Adds `pluginPropsSource` so an empty
    result is explicit rather than being read as "this device has no props".
    """
    try:
        data = dict(dev)
    except Exception:
        return {}

    props, source = device_props_with_source(dev)
    data["pluginProps"] = props
    data["pluginPropsSource"] = source
    redact_device_data(data, str(_safe_getattr(dev, "pluginId") or ""))

    # Keep the derived address alongside the native one. Callers auditing
    # addresses should use this rather than `address`.
    try:
        data["resolvedAddress"] = device_address(dev)
    except Exception:
        pass

    return data
