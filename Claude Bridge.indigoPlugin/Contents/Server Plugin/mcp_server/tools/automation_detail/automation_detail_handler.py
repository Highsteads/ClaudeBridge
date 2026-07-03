"""
Automation introspection handler for ClaudeBridge MCP server.

Tools:
  - get_trigger_details        : full trigger definition incl. action steps
  - get_schedule_details       : full schedule definition incl. timing + steps
  - get_action_group_details   : full action group definition incl. steps
  - find_automation_references : role-tagged reverse lookup for an entity
  - investigate_event          : rank likely causes of a device change

Action steps, conditions and embedded scripts come from the read-only
.indiDb structure store (the IOM does not expose them); live fields
(enabled, next execution) come from the IOM and always win where both exist.
"""

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider
from ...adapters.indidb import IndiDbStructureStore
from . import detail_renderer

AUTOMATION_TYPES = ("trigger", "schedule", "action_group")
REFERENCE_TYPES = ("device", "variable", "action_group")

# Event-log source column values written by automation executions.
AUTOMATION_LOG_SOURCES = {"Trigger", "Schedule", "Action Group"}

# Structural-evidence scoring for investigate_event. Temporal proximity
# contributes at most 1.0, so any structural link outranks timing alone.
STRUCTURAL_SCORE = 3.0
CHAIN_DECAY = 0.8
HEURISTIC_SCORE = 1.0

_QUOTED_NAME_RE = re.compile(r'"([^"]+)"')

_LIVE_COLLECTIONS = {
    "trigger":      "triggers",
    "schedule":     "schedules",
    "action_group": "actionGroups",
}

_DEPENDENCY_NAMESPACES = {
    "device":       "device",
    "variable":     "variable",
    "action_group": "actionGroup",
}


def _parse_log_timestamp(text: Any) -> Optional[datetime.datetime]:
    if not isinstance(text, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_element_name(message: str) -> str:
    """
    Automation log lines carry the element name either bare
    ("Trigger<TAB>Sunset lights") or quoted inside a phrase
    ('Schedule<TAB>schedule "Check lights" (delayed action)').
    """
    quoted = _QUOTED_NAME_RE.search(message)
    if quoted:
        return quoted.group(1)
    return message.strip()


class AutomationDetailHandler(BaseToolHandler):
    """Handler for automation introspection and cause investigation."""

    def __init__(
        self,
        data_provider: DataProvider,
        structure_store: IndiDbStructureStore,
        log_query_handler=None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="automation_detail", logger=logger)
        self.data_provider = data_provider
        self.structure_store = structure_store
        self.log_query_handler = log_query_handler

    # ── Shared resolution helpers ────────────────────────────────────────────

    def _lookup_name(self, kind: str, entity_id: int) -> Optional[str]:
        """Name from the structure store, falling back to the live IOM
        (a freshly created element may not be in the file yet)."""
        name = self.structure_store.lookup_name(kind, entity_id)
        if name is not None:
            return name
        try:
            if kind == "device" and entity_id in indigo.devices:
                return indigo.devices[entity_id].name
            if kind == "variable" and entity_id in indigo.variables:
                return indigo.variables[entity_id].name
            collection_name = _LIVE_COLLECTIONS.get(kind)
            if collection_name is not None:
                collection = getattr(indigo, collection_name)
                if entity_id in collection:
                    return collection[entity_id].name
        except Exception:
            pass
        return None

    def _display_name(self, kind: str, entity_id: Any) -> str:
        if isinstance(entity_id, int):
            name = self._lookup_name(kind, entity_id)
            if name is not None:
                return name
        return str(entity_id)

    def _resolve_structure(
        self, entity_type: str, id_or_name: Union[int, str]
    ) -> Tuple[Optional[int], Optional[dict], Optional[str]]:
        """
        Resolve a db-file structure by numeric ID or (case-insensitive,
        unique) name. Returns (id, record, error_message).
        """
        structures = self.structure_store.get_all_structures(entity_type)
        try:
            entity_id = int(id_or_name)
            record = structures.get(entity_id)
            if record is not None:
                return entity_id, record, None
            return None, None, (
                f"{entity_type} {entity_id} not found in the database file "
                f"(a very recent creation may not be flushed yet)")
        except (ValueError, TypeError):
            pass

        needle = str(id_or_name).lower()
        matches = [(eid, rec) for eid, rec in structures.items()
                   if str(rec.get("Name", "")).lower() == needle]
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None
        if len(matches) > 1:
            ids = ", ".join(str(eid) for eid, _ in matches)
            return None, None, (
                f"Name '{id_or_name}' matches {len(matches)} {entity_type}s "
                f"({ids}) — use the numeric ID")
        return None, None, f"{entity_type} '{id_or_name}' not found"

    def _live_enrichment(self, entity_type: str, entity_id: int) -> Dict[str, Any]:
        """Live IOM fields that beat the (possibly stale) file copy."""
        live: Dict[str, Any] = {}
        try:
            collection = getattr(indigo, _LIVE_COLLECTIONS[entity_type])
            if entity_id not in collection:
                return live
            elem = collection[entity_id]
            live["enabled"] = elem.enabled
            live["name"] = elem.name
            if entity_type == "schedule":
                try:
                    nxt = elem.nextExecution
                    live["next_execution"] = str(nxt) if nxt else None
                except AttributeError:
                    pass
        except Exception:
            pass
        return live

    # ── get_{trigger,schedule,action_group}_details ─────────────────────────

    def get_details(
        self,
        entity_type: str,
        entity_id: Union[int, str],
        include_scripts: bool = True,
    ) -> Dict[str, Any]:
        self.log_incoming_request(f"get_{entity_type}_details",
                                  {"entity_id": entity_id})
        try:
            if entity_type not in AUTOMATION_TYPES:
                return {"success": False,
                        "error": f"Invalid entity_type '{entity_type}' — "
                                 f"valid: {', '.join(AUTOMATION_TYPES)}"}
            resolved_id, record, error = self._resolve_structure(entity_type, entity_id)
            if record is None:
                return {"success": False, "error": error}

            if entity_type == "trigger":
                details = detail_renderer.render_trigger_details(
                    record, self._lookup_name, include_scripts)
            elif entity_type == "schedule":
                details = detail_renderer.render_schedule_details(
                    record, self._lookup_name, include_scripts)
            else:
                details = detail_renderer.render_action_group_details(
                    record, self._lookup_name, include_scripts)

            details.update(self._live_enrichment(entity_type, resolved_id))
            details["success"] = True
            details["structure_source"] = self.structure_store.freshness()
            self.log_tool_outcome(f"get_{entity_type}_details", True,
                                  f"'{details.get('name')}' ({resolved_id})")
            return details
        except Exception as exc:
            return self.handle_exception(exc, f"get_{entity_type}_details")

    # ── find_automation_references ───────────────────────────────────────────

    def find_automation_references(
        self,
        entity_type: str,
        entity_id: Union[int, str],
        include_server_check: bool = True,
    ) -> Dict[str, Any]:
        self.log_incoming_request("find_automation_references",
                                  {"entity_type": entity_type,
                                   "entity_id": entity_id})
        try:
            if entity_type not in REFERENCE_TYPES:
                return {"success": False,
                        "error": f"Invalid entity_type '{entity_type}' — "
                                 f"valid: {', '.join(REFERENCE_TYPES)}"}
            try:
                entity_id = int(entity_id)
            except (ValueError, TypeError):
                return {"success": False,
                        "error": "entity_id must be numeric — use "
                                 "search_entities to find the ID first"}

            references = self.structure_store.find_references(entity_type, entity_id)
            for ref in references:
                ref["name"] = self._display_name(ref["entity_type"], ref["id"])
                ref["source"] = "database_file"
                if "via_action_groups" in ref:
                    ref["via_action_groups"] = [
                        {"id": ag_id,
                         "name": self._display_name("action_group", ag_id)}
                        for ag_id in ref["via_action_groups"]
                    ]

            notes: List[str] = []
            if include_server_check:
                self._merge_server_dependencies(entity_type, entity_id,
                                                references, notes)

            target_name = self._display_name(entity_type, entity_id)
            self.log_tool_outcome("find_automation_references", True,
                                  f"{entity_type} '{target_name}': "
                                  f"{len(references)} references")
            return {
                "success": True,
                "target": {"entity_type": entity_type, "id": entity_id,
                           "name": target_name},
                "count": len(references),
                "references": references,
                "notes": notes,
                "structure_source": self.structure_store.freshness(),
            }
        except Exception as exc:
            return self.handle_exception(exc, "find_automation_references")

    def _merge_server_dependencies(
        self,
        entity_type: str,
        entity_id: int,
        references: List[Dict[str, Any]],
        notes: List[str],
    ) -> None:
        """Cross-check against the server's own dependency graph; anything the
        file scan missed is appended as source='server'."""
        namespace_name = _DEPENDENCY_NAMESPACES.get(entity_type)
        if namespace_name is None:
            return
        try:
            deps = getattr(indigo, namespace_name).getDependencies(entity_id)
        except Exception as exc:
            notes.append(f"Server dependency check unavailable: {exc}")
            return

        seen = {(ref["entity_type"], ref["id"]) for ref in references}
        kind_map = {
            "triggers":     "trigger",
            "schedules":    "schedule",
            "actionGroups": "action_group",
            "devices":      "device",
            "variables":    "variable",
            "controlPages": "control_page",
        }
        for deps_key, kind in kind_map.items():
            try:
                items = list(deps[deps_key] or [])
            except Exception:
                continue
            for item in items:
                try:
                    dep_id, dep_name = item["ID"], item["Name"]
                except Exception:
                    continue
                key = (kind, dep_id)
                if key in seen:
                    for ref in references:
                        if (ref["entity_type"], ref["id"]) == key:
                            ref["source"] = "database_file+server"
                    continue
                seen.add(key)
                references.append({
                    "entity_type": kind,
                    "id": dep_id,
                    "name": dep_name,
                    "role": "referenced",
                    "source": "server",
                })

    # ── investigate_event ────────────────────────────────────────────────────

    def investigate_event(
        self,
        device_id: Optional[Union[int, str]] = None,
        search_text: Optional[str] = None,
        around_time: Optional[str] = None,
        occurrence: int = 1,
        lookback_seconds: int = 60,
        lookahead_seconds: int = 5,
        search_days: int = 2,
    ) -> Dict[str, Any]:
        self.log_incoming_request("investigate_event",
                                  {"device_id": device_id,
                                   "search_text": search_text,
                                   "around_time": around_time})
        try:
            if self.log_query_handler is None:
                return {"success": False,
                        "error": "Event-log reader unavailable"}

            device = None
            if device_id is not None:
                try:
                    device_id = int(device_id)
                except (ValueError, TypeError):
                    return {"success": False, "error": "device_id must be numeric"}
                name = self._lookup_name("device", device_id)
                if name is None:
                    return {"success": False,
                            "error": f"Device {device_id} not found"}
                device = {"id": device_id, "name": name}
                needle = f'"{name}"'
            elif search_text:
                needle = str(search_text)
            else:
                return {"success": False,
                        "error": "Provide device_id or search_text"}

            search_days = max(1, min(int(search_days), 14))
            occurrence = max(1, int(occurrence))
            lookback_seconds = max(1, int(lookback_seconds))
            lookahead_seconds = max(0, int(lookahead_seconds))

            now = datetime.datetime.now()
            window_start = now - datetime.timedelta(days=search_days)
            entries = self.log_query_handler._read_log_range(
                window_start, None, None)

            around_dt = None
            if around_time:
                from ..log_query.log_query_handler import _parse_time_param
                around_dt = _parse_time_param(str(around_time), now.date())
                if around_dt is None:
                    return {"success": False,
                            "error": f"Could not parse around_time "
                                     f"'{around_time}' — use HH:MM[:SS] or "
                                     f"YYYY-MM-DD HH:MM:SS"}

            target = self._locate_target(entries, needle, around_dt, occurrence)
            if target is None:
                return {
                    "success": False,
                    "error": "No matching event-log line found",
                    "searched_for": needle,
                    "searched_days": search_days,
                    "hint": "The change may predate the searched window, or "
                            "the device may log under a different name — try "
                            "search_text with a distinctive fragment.",
                }
            target_ts, target_entry = target

            candidates = [
                (ts, entry) for ts, entry in self._timestamped(entries)
                if entry.get("TypeStr") in AUTOMATION_LOG_SOURCES
                and -lookahead_seconds <= (target_ts - ts).total_seconds() <= lookback_seconds
                and entry is not target_entry
            ]

            ranked = self._rank_candidates(candidates, target_ts,
                                           device_id if device else None,
                                           lookback_seconds)
            notes: List[str] = []
            if not ranked:
                notes.append(
                    "No trigger/schedule/action-group activity logged in the "
                    "window — the change was likely manual/physical control, "
                    "an external app or voice assistant, or a plugin acting "
                    "without an event-log line.")

            result: Dict[str, Any] = {
                "success": True,
                "target_event": {
                    "timestamp": target_entry.get("TimeStamp"),
                    "source": target_entry.get("TypeStr"),
                    "line": target_entry.get("Message"),
                },
                "window": {"lookback_seconds": lookback_seconds,
                           "lookahead_seconds": lookahead_seconds},
                "candidates": ranked,
                "notes": notes,
            }
            if device is not None:
                result["target_event"]["device"] = device
            self.log_tool_outcome("investigate_event", True,
                                  f"{len(ranked)} candidates for {needle}")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "investigate_event")

    @staticmethod
    def _timestamped(entries: List[Dict[str, Any]]):
        for entry in entries:
            ts = _parse_log_timestamp(entry.get("TimeStamp"))
            if ts is not None:
                yield ts, entry

    def _locate_target(
        self,
        entries: List[Dict[str, Any]],
        needle: str,
        around_dt: Optional[datetime.datetime],
        occurrence: int,
    ) -> Optional[Tuple[datetime.datetime, Dict[str, Any]]]:
        needle_lower = needle.lower()
        matches = [
            (ts, entry) for ts, entry in self._timestamped(entries)
            if needle_lower in str(entry.get("Message", "")).lower()
        ]
        if not matches:
            return None
        if around_dt is not None:
            return min(matches,
                       key=lambda m: abs((m[0] - around_dt).total_seconds()))
        # Newest first; occurrence=1 is the most recent match.
        matches.sort(key=lambda m: m[0], reverse=True)
        return matches[min(occurrence, len(matches)) - 1]

    def _rank_candidates(
        self,
        candidates: List[Tuple[datetime.datetime, Dict[str, Any]]],
        target_ts: datetime.datetime,
        device_id: Optional[int],
        lookback_seconds: int,
    ) -> List[Dict[str, Any]]:
        source_to_kind = {"Trigger": "trigger", "Schedule": "schedule",
                          "Action Group": "action_group"}
        references = (self.structure_store.find_references("device", device_id)
                      if device_id else [])
        refs_by_container: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for ref in references:
            refs_by_container.setdefault(
                (ref["entity_type"], ref["id"]), []).append(ref)

        ranked: List[Dict[str, Any]] = []
        seen_keys = set()
        for ts, entry in candidates:
            kind = source_to_kind.get(entry.get("TypeStr"))
            if kind is None:
                continue
            name = _extract_element_name(str(entry.get("Message", "")))
            elem_id = self._unique_id_for_name(kind, name)
            key = (kind, elem_id or name, ts)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            delta = (target_ts - ts).total_seconds()
            evidence: List[str] = []
            if delta >= 0:
                score = max(0.0, 1.0 - delta / lookback_seconds)
                evidence.append(f"fired {delta:.1f}s before the target event")
            else:
                score = 0.5 * max(0.0, 1.0 + delta / lookback_seconds)
                evidence.append(f"logged {-delta:.1f}s after the target event")

            relationship = None
            if elem_id is not None:
                for ref in refs_by_container.get((kind, elem_id), []):
                    if ref["role"] in ("acts_on", "sets"):
                        chain = ref.get("via_action_groups") or []
                        score += STRUCTURAL_SCORE * (CHAIN_DECAY ** len(chain))
                        relationship = {"role": ref["role"]}
                        if chain:
                            relationship["via_action_groups"] = chain
                            chain_names = " -> ".join(
                                str(c.get("name", c)) if isinstance(c, dict)
                                else str(c) for c in chain)
                            evidence.append(
                                f"acts on the device through action group(s): "
                                f"{chain_names}")
                        else:
                            evidence.append(
                                f"directly {ref['role'].replace('_', ' ')} "
                                f"the device")
                        break
                    if (ref["role"] in ("plugin_config_reference",
                                        "script_reference")
                            and relationship is None):
                        score += HEURISTIC_SCORE
                        relationship = {"role": ref["role"]}
                        evidence.append(
                            "the device id appears in this automation's "
                            + ("embedded script"
                               if ref["role"] == "script_reference"
                               else "plugin configuration"))
            if relationship is None:
                evidence.append("temporal proximity only — no structural "
                                "link found")

            candidate: Dict[str, Any] = {
                "entity_type": kind,
                "name": name,
                "score": round(score, 2),
                "log_timestamp": entry.get("TimeStamp"),
                "seconds_before_event": round(delta, 1),
                "evidence": evidence,
            }
            if elem_id is not None:
                candidate["id"] = elem_id
            if relationship is not None:
                candidate["relationship"] = relationship
            ranked.append(candidate)

        ranked.sort(key=lambda c: c["score"], reverse=True)
        for rank, candidate in enumerate(ranked, start=1):
            candidate["rank"] = rank
        return ranked

    def _unique_id_for_name(self, kind: str, name: str) -> Optional[int]:
        structures = self.structure_store.get_all_structures(kind)
        matches = [eid for eid, record in structures.items()
                   if record.get("Name") == name]
        return matches[0] if len(matches) == 1 else None
