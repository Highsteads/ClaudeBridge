#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin_prefs.py
# Description: Read another plugin's saved settings, with credentials hidden.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

"""
A plugin's saved settings, read from its .indiPref file.

Indigo gives no API for reading another plugin's pluginPrefs, so reading one
meant raw Python and a hand-parsed XML file — which printed every stored
password along with everything else. The file lives at
Preferences/Plugins/<bundle id>.indiPref and is typed XML:

    <Prefs type="dict">
        <holdSeconds type="string">20</holdSeconds>
        <networkSecurityKey type="vector"><Item type="integer">..</Item>...

A value is hidden when its name reads as a credential or when the plugin's
PluginConfig.xml marks the field secure="true". The name test is stricter
about WORDS than the one used on device props: that one matches "pin" inside
"pingInterval" and "pass" inside "compass", which is harmless on a device
reply but would hide half of a plugin's ordinary settings here. Unmistakable
words (password, secret, token...) still match anywhere in the name, so
"serverpassword" is caught; the short ambiguous ones (pass, pin, key, pwd,
psk) must stand as a word of their own, as in "dahuaPass" or "apiKey".
A hidden value is hidden whatever its type, lists and dicts included: a
Z-Wave network key is stored as a list of numbers.

What is on disk is what Indigo last saved — it changes when the plugin saves
its prefs (a Configure dialog, or a clean shutdown), so a value the plugin
changed in memory since may not be there yet.
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, FrozenSet, Optional, Tuple

from . import device_props

MASK = device_props.MASK

# Test hook: a Preferences/Plugins folder to use instead of Indigo's own.
PREFS_DIR_OVERRIDE: Optional[str] = None


def prefs_dir() -> Optional[str]:
    if PREFS_DIR_OVERRIDE:
        return PREFS_DIR_OVERRIDE
    try:
        import indigo
        base = indigo.server.getInstallFolderPath()
    except Exception:
        return None
    return os.path.join(base, "Preferences", "Plugins") if isinstance(base, str) and base else None


def _value(el: ET.Element) -> Any:
    kind = (el.get("type") or "string").lower()
    if kind == "dict":
        return {child.tag: _value(child) for child in el}
    if kind in ("vector", "list", "array"):
        return [_value(child) for child in el]
    text = el.text or ""
    if kind == "bool":
        return text.strip().lower() == "true"
    if kind == "integer":
        try:
            return int(text.strip())
        except ValueError:
            return text
    if kind == "real":
        try:
            return float(text.strip())
        except ValueError:
            return text
    return text


# Match anywhere in the name, whatever the case or spacing.
_STRONG = re.compile(r"password|passwd|passcode|passphrase|secret|token|apikey|credential"
                     r"|bearer|privatekey", re.I)
# Match only as a whole word of the name.
_WEAK = frozenset({"pass", "pin", "key", "pwd", "psk"})
_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def is_secret_name(name: Any) -> bool:
    """Whether a setting's name marks its value as a credential."""
    text = str(name or "")
    if _STRONG.search(text):
        return True
    return any(word.lower() in _WEAK for word in _WORDS.findall(text))


def _hidden(value: Any) -> bool:
    """Worth hiding: anything but an empty value or a plain on/off flag."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def mask(prefs: Dict[str, Any], secure: FrozenSet[str]) -> Tuple[Dict[str, Any], list]:
    """A copy with credential values replaced by MASK, and the names hidden."""
    hidden = []

    def walk(obj: Dict[str, Any], path: str) -> Dict[str, Any]:
        out = {}
        for key, value in obj.items():
            name = f"{path}{key}"
            if (is_secret_name(key) or key in secure) and _hidden(value):
                out[key] = MASK
                hidden.append(name)
            elif isinstance(value, dict):
                out[key] = walk(value, name + ".")
            else:
                out[key] = value
        return out

    return walk(prefs, ""), hidden


def read(plugin_id: str) -> Dict[str, Any]:
    """{"prefs": {...}, "hidden": [...], "path": ...} or {"error": ...}."""
    folder = prefs_dir()
    if not folder:
        return {"error": "Could not find Indigo's Preferences/Plugins folder"}
    name = f"{plugin_id}.indiPref"
    # A bundle id never holds a path separator; refuse one rather than read
    # a file outside the prefs folder.
    if os.sep in plugin_id or plugin_id.startswith("."):
        return {"error": f"'{plugin_id}' is not a plugin bundle id"}
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        return {"error": (f"No saved settings for '{plugin_id}' — a plugin that has never "
                          f"saved its prefs has no {name}")}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"error": f"Could not read {name}: {exc}"}
    raw = _value(root)
    if not isinstance(raw, dict):
        return {"error": f"{name} does not hold a settings dictionary"}
    secure = device_props._secure_fields(plugin_id, "PluginConfig.xml")
    prefs, hidden = mask(raw, secure)
    return {"prefs": prefs, "hidden": sorted(hidden), "path": path}
