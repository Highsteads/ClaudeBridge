#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    orphan_prefs.py
# Description: Removes stored plugin settings that no longer belong to any field
#              of the Configure dialog (PluginConfig.xml)
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Indigo keeps every value a Configure dialog ever saved, so a field removed
# from PluginConfig.xml lives on in the user's prefs for ever. After the 3.0
# spring clean that meant an Anthropic key and the InfluxDB login, still stored
# in plain text for a feature that no longer exists. What is allowed is read
# from the XML itself, so there is no list of old names to keep up to date.

import xml.etree.ElementTree as ET
from typing import Iterable, List, Optional, Set

# Settings the plugin writes itself, outside any dialog field. Never removed.
#   timestampEnabled - the "Toggle Timestamps in Log" menu item
PLUGIN_OWNED_KEYS = frozenset({"timestampEnabled"})


def config_field_ids(xml_path: str) -> Optional[Set[str]]:
    """Every <Field id="..."> in the dialog, or None when the XML cannot be
    read. None means "do not purge": an unreadable file must never look like
    a dialog with no fields, which would wipe every setting."""
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return None
    ids = {f.get("id") for f in root.iter("Field") if f.get("id")}
    return ids or None


def purge_orphan_prefs(prefs, xml_path: str,
                       keep: Iterable[str] = PLUGIN_OWNED_KEYS) -> List[str]:
    """Delete from ``prefs`` every key that is neither a dialog field nor in
    ``keep``, and return the removed keys, sorted. Works on an indigo.Dict (del
    is supported) and on a plain dict. Values are never read."""
    allowed = config_field_ids(xml_path)
    if allowed is None:
        return []
    allowed |= set(keep)
    orphans = sorted(k for k in list(prefs.keys()) if k not in allowed)
    removed = []
    for key in orphans:
        try:
            del prefs[key]
            removed.append(key)
        except Exception:
            pass   # one stubborn key must not stop the rest
    return removed
