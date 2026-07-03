"""
Read-only streaming parser for Indigo's .indiDb database file.

The file is one large <Database type="dict"> XML document. Elements carry a
`type` attribute (string / integer / real / bool / dict / vector) that drives
decoding into plain Python values. Triggers (TriggerList), schedules
(TDTriggerList — "Time/Date trigger" is Indigo's internal name) and action
groups (ActionGroupList) are kept as full decoded dicts; DeviceList and
VariableList are reduced to id→name maps for name resolution and the
reverse index's id-match heuristic.

iterparse + per-record clear() keeps memory flat regardless of database size.
This module never writes: the server holds the whole model in memory and
flushes it over this file, so the database is strictly read-only for us.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ParsedDb:
    """One decoded snapshot of the database file's automation structures."""

    mtime: float = 0.0
    size: int = 0
    triggers: Dict[int, dict] = field(default_factory=dict)
    schedules: Dict[int, dict] = field(default_factory=dict)
    action_groups: Dict[int, dict] = field(default_factory=dict)
    device_names: Dict[int, str] = field(default_factory=dict)
    variable_names: Dict[int, str] = field(default_factory=dict)
    reverse_index: Optional[Any] = None  # attached by the store after parsing

    def counts(self) -> Dict[str, int]:
        return {
            "triggers":      len(self.triggers),
            "schedules":     len(self.schedules),
            "action_groups": len(self.action_groups),
        }


def decode_typed_element(elem: ET.Element) -> Any:
    """
    Decode one typed .indiDb XML element into a plain Python value.

    Missing/unknown `type` attributes degrade gracefully: an element with
    children decodes as a dict, a leaf as its text.
    """
    elem_type = elem.get("type")
    if elem_type == "vector":
        return [decode_typed_element(child) for child in elem]
    if elem_type == "dict" or (elem_type is None and len(elem) > 0):
        return {child.tag: decode_typed_element(child) for child in elem}

    text = elem.text or ""
    if elem_type == "integer":
        try:
            return int(text)
        except ValueError:
            return text
    if elem_type == "real":
        try:
            return float(text)
        except ValueError:
            return text
    if elem_type == "bool":
        return text.strip().lower() == "true"
    return text


# Second-level vectors decoded in full, keyed to ParsedDb attributes.
_FULL_LISTS = {
    "TriggerList":     "triggers",
    "TDTriggerList":   "schedules",
    "ActionGroupList": "action_groups",
}

# Second-level vectors reduced to id→name maps.
_NAME_LISTS = {
    "DeviceList":   "device_names",
    "VariableList": "variable_names",
}


def parse_indidb(path: str) -> ParsedDb:
    """
    Stream-parse the database file at `path` into a ParsedDb.

    Raises on unreadable or malformed XML (a torn mid-rewrite read) — the
    caller keeps its previous good snapshot in that case. Records without a
    usable integer ID are skipped.
    """
    parsed = ParsedDb()
    active_list: Optional[str] = None
    depth = 0

    for event, elem in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            depth += 1
            if depth == 2 and (elem.tag in _FULL_LISTS or elem.tag in _NAME_LISTS):
                active_list = elem.tag
            continue

        depth -= 1
        if depth == 2 and active_list is not None:
            # One complete record inside a list we care about.
            if active_list in _FULL_LISTS:
                record = decode_typed_element(elem)
                record_id = record.get("ID") if isinstance(record, dict) else None
                if isinstance(record_id, int):
                    getattr(parsed, _FULL_LISTS[active_list])[record_id] = record
            else:
                # Name lists: pull ID/Name without decoding the whole record
                # (device records are by far the bulk of the file).
                try:
                    record_id = int(elem.findtext("ID"))
                except (TypeError, ValueError):
                    record_id = None
                name = elem.findtext("Name")
                if record_id is not None and name is not None:
                    getattr(parsed, _NAME_LISTS[active_list])[record_id] = name
            elem.clear()
        elif depth == 1:
            active_list = None
            elem.clear()

    return parsed
