"""
Role-tagged reverse-reference index over a ParsedDb.

Answers "which triggers / schedules / action groups reference entity X, and
in what role?" using the action steps and conditions that the IOM never
exposes. Roles:

  watches                 trigger fires on this device/variable changing
  condition_reads         a condition compares this device/variable
  acts_on                 an action step commands this device
  sets                    an action step writes this variable
  executes                an action step runs this action group
  script_reference        the entity's id appears in an EMBEDDED script's
                          source (heuristic — id-shaped match)
  plugin_config_reference the entity's id appears in a plugin action's or
                          plugin trigger's config props (heuristic)

Compound conditions (Type 100) are recursed. Action-group execution chains
are followed transitively (cycle-safe, bounded) so "trigger T acts on device
D via AG A → AG B" comes back with the chain attached.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from . import schema

# Bound on AG→AG chain walking; deeper nesting than this is pathological
# (Indigo's own NestedActionLimit default is 20, real databases use 1-2).
MAX_CHAIN_DEPTH = 5

# Entity ids are large random integers. Ignore id-shaped values below this
# floor so ports, delays and percentages never match the heuristics.
MIN_HEURISTIC_ID = 100000

# id-shaped numbers inside embedded script source (6-10 digit standalone ints).
_SCRIPT_ID_RE = re.compile(r"(?<![\dA-Za-z_.])(\d{6,10})(?![\dA-Za-z_.])")

TargetKey = Tuple[str, int]  # ("device"|"variable"|"action_group", id)


@dataclass
class Reference:
    """One container (trigger/schedule/action group) referencing one target."""

    container_kind: str  # "trigger" | "schedule" | "action_group"
    container_id: int
    role: str
    detail: str = ""
    confidence: str = "exact"  # "exact" | "heuristic"

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "entity_type": self.container_kind,
            "id":          self.container_id,
            "role":        self.role,
        }
        if self.detail:
            d["detail"] = self.detail
        if self.confidence != "exact":
            d["confidence"] = self.confidence
        return d


@dataclass
class ReverseIndex:
    """Direct references plus the AG→AG execution graph for chain expansion."""

    direct: Dict[TargetKey, List[Reference]] = field(default_factory=dict)
    # action_group_id -> [(container_kind, container_id), ...] with an
    # execute-action-group step targeting it
    exec_parents: Dict[int, List[Tuple[str, int]]] = field(default_factory=dict)

    def add(self, target: TargetKey, ref: Reference) -> None:
        refs = self.direct.setdefault(target, [])
        # Collapse duplicates (same container + role) — a trigger with three
        # "turn on X" steps is one acts_on reference, not three.
        for existing in refs:
            if (existing.container_kind == ref.container_kind
                    and existing.container_id == ref.container_id
                    and existing.role == ref.role):
                return
        refs.append(ref)

    def references_to(self, entity_kind: str, entity_id: int) -> List[Dict[str, Any]]:
        """
        All references to (entity_kind, entity_id) — direct ones, plus
        containers that reach it transitively through AG execution chains.
        """
        direct_refs = self.direct.get((entity_kind, entity_id), [])
        results = [ref.as_dict() for ref in direct_refs]

        for ref in direct_refs:
            if ref.container_kind != "action_group":
                continue
            for parent_kind, parent_id, chain in self._exec_ancestors(ref.container_id):
                entry = ref.as_dict()
                entry["entity_type"] = parent_kind
                entry["id"] = parent_id
                entry["via_action_groups"] = chain
                results.append(entry)
        return results

    def _exec_ancestors(self, ag_id: int) -> List[Tuple[str, int, List[int]]]:
        """
        Containers that (transitively) execute action group `ag_id`.
        Returns (kind, id, chain) with chain = intermediate AG ids ending at
        `ag_id`. Cycle-safe, bounded at MAX_CHAIN_DEPTH.
        """
        found: List[Tuple[str, int, List[int]]] = []
        seen: Set[Tuple[str, int]] = set()
        frontier: List[Tuple[int, List[int]]] = [(ag_id, [ag_id])]
        for _ in range(MAX_CHAIN_DEPTH):
            next_frontier: List[Tuple[int, List[int]]] = []
            for current_ag, chain in frontier:
                for parent_kind, parent_id in self.exec_parents.get(current_ag, []):
                    key = (parent_kind, parent_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append((parent_kind, parent_id, chain))
                    if parent_kind == "action_group":
                        next_frontier.append((parent_id, [parent_id] + chain))
            if not next_frontier:
                break
            frontier = next_frontier
        return found


def build_reverse_index(parsed) -> ReverseIndex:
    """Build the full index in one pass over a ParsedDb."""
    index = ReverseIndex()
    known_ids = _known_entity_ids(parsed)

    for trigger_id, trigger in parsed.triggers.items():
        _index_trigger_event(index, trigger_id, trigger, known_ids)
        _index_container(index, "trigger", trigger_id, trigger, known_ids)
    for schedule_id, sched in parsed.schedules.items():
        _index_container(index, "schedule", schedule_id, sched, known_ids)
    for ag_id, ag in parsed.action_groups.items():
        _index_conditions(index, "action_group", ag_id, ag.get("Condition"))
        _index_action_steps(index, "action_group", ag_id,
                            ag.get("ActionSteps") or [], known_ids)
    return index


def _known_entity_ids(parsed) -> Dict[int, str]:
    """id -> entity kind, for the id-shaped-value heuristics."""
    known: Dict[int, str] = {}
    for dev_id in parsed.device_names:
        known[dev_id] = "device"
    for var_id in parsed.variable_names:
        known[var_id] = "variable"
    for ag_id in parsed.action_groups:
        known[ag_id] = "action_group"
    return known


def _index_trigger_event(
    index: ReverseIndex, trigger_id: int, trigger: dict, known_ids: Dict[int, str]
) -> None:
    """What a trigger WATCHES (its event source)."""
    trigger_class = trigger.get("Class")
    if trigger_class == 501 and isinstance(trigger.get("DeviceID"), int):
        detail = schema.label(schema.DEVICE_STATE_CHANGE_CODES,
                              trigger.get("DeviceStateChange"))
        selector = trigger.get("DeviceStateSelector")
        if selector:
            detail = f"state '{selector}' {detail}"
        index.add(("device", trigger["DeviceID"]),
                  Reference("trigger", trigger_id, "watches", detail=detail))
    elif trigger_class == 502 and isinstance(trigger.get("VarID"), int):
        detail = schema.label(schema.VAR_CHANGE_CODES, trigger.get("VarChange"))
        index.add(("variable", trigger["VarID"]),
                  Reference("trigger", trigger_id, "watches", detail=detail))
    elif trigger_class == 598:
        _index_plugin_props(index, "trigger", trigger_id,
                            trigger.get("MetaProps"), known_ids)


def _index_container(
    index: ReverseIndex,
    container_kind: str,
    container_id: int,
    container: dict,
    known_ids: Dict[int, str],
) -> None:
    """Conditions + inline action steps of a trigger or schedule record."""
    _index_conditions(index, container_kind, container_id, container.get("Condition"))
    inline_group = container.get("ActionGroup") or {}
    steps = inline_group.get("ActionSteps") if isinstance(inline_group, dict) else None
    _index_action_steps(index, container_kind, container_id, steps or [], known_ids)


def _index_conditions(
    index: ReverseIndex, container_kind: str, container_id: int, condition: Any
) -> None:
    """Index one Condition dict, recursing into Type 100 compounds."""
    if not isinstance(condition, dict):
        return
    cond_type = condition.get("Type")
    if cond_type == 3:
        for key in ("VarID", "VarID2"):
            var_id = condition.get(key)
            if isinstance(var_id, int) and var_id > 0:
                index.add(("variable", var_id),
                          Reference(container_kind, container_id, "condition_reads"))
    elif cond_type == 7:
        dev_id = condition.get("DevID")
        if isinstance(dev_id, int) and dev_id > 0:
            state = condition.get("DevState") or ""
            index.add(("device", dev_id),
                      Reference(container_kind, container_id, "condition_reads",
                                detail=f"state '{state}'" if state else ""))
    elif cond_type == 100:
        nested = (condition.get("ConditionList") or {}).get("Conditions") or []
        for item in nested:
            _index_conditions(index, container_kind, container_id, item)


def _index_action_steps(
    index: ReverseIndex,
    container_kind: str,
    container_id: int,
    steps: List[Any],
    known_ids: Dict[int, str],
) -> None:
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_class = step.get("Class")

        if step_class == schema.ACTION_CLASS_DEVICE and isinstance(step.get("DeviceID"), int):
            detail = schema.label(schema.DEVICE_ACTION_CODES, step.get("DeviceAction"))
            index.add(("device", step["DeviceID"]),
                      Reference(container_kind, container_id, "acts_on", detail=detail))

        elif step_class == schema.ACTION_CLASS_VARIABLE and isinstance(step.get("VarID"), int):
            index.add(("variable", step["VarID"]),
                      Reference(container_kind, container_id, "sets"))

        elif step_class == schema.ACTION_CLASS_EXEC_GROUP and isinstance(
                step.get("ActionGroupID"), int):
            ag_id = step["ActionGroupID"]
            index.add(("action_group", ag_id),
                      Reference(container_kind, container_id, "executes"))
            parents = index.exec_parents.setdefault(ag_id, [])
            if (container_kind, container_id) not in parents:
                parents.append((container_kind, container_id))

        elif step_class == schema.ACTION_CLASS_SCRIPT:
            source = step.get("ScriptSource")
            if isinstance(source, str) and source:
                _index_script_source(index, container_kind, container_id,
                                     source, known_ids)

        elif step_class == schema.ACTION_CLASS_PLUGIN:
            # A plugin step can command a device directly (step-level
            # DeviceID) in addition to whatever its config props reference.
            if isinstance(step.get("DeviceID"), int) and step["DeviceID"] > 0:
                detail = (step.get("TypeLabelPlugin") or step.get("PluginID")
                          or "plugin action")
                index.add(("device", step["DeviceID"]),
                          Reference(container_kind, container_id, "acts_on",
                                    detail=str(detail)))
            _index_plugin_props(index, container_kind, container_id,
                                step.get("MetaProps"), known_ids)


def _index_script_source(
    index: ReverseIndex,
    container_kind: str,
    container_id: int,
    source: str,
    known_ids: Dict[int, str],
) -> None:
    """Embedded-script heuristic: id-shaped ints matching known entities."""
    seen: Set[int] = set()
    for match in _SCRIPT_ID_RE.finditer(source):
        candidate = int(match.group(1))
        if candidate < MIN_HEURISTIC_ID or candidate in seen:
            continue
        seen.add(candidate)
        kind = known_ids.get(candidate)
        if kind is not None:
            index.add((kind, candidate),
                      Reference(container_kind, container_id, "script_reference",
                                detail="id found in embedded script",
                                confidence="heuristic"))


def _index_plugin_props(
    index: ReverseIndex,
    container_kind: str,
    container_id: int,
    props: Any,
    known_ids: Dict[int, str],
    _seen: Optional[Set[TargetKey]] = None,
) -> None:
    """Plugin-config heuristic: id-shaped values matching known entities."""
    if _seen is None:
        _seen = set()

    if isinstance(props, dict):
        values = props.values()
    elif isinstance(props, list):
        values = props
    else:
        return

    for value in values:
        if isinstance(value, (dict, list)):
            _index_plugin_props(index, container_kind, container_id, value,
                                known_ids, _seen)
            continue
        candidate: Optional[int] = None
        if isinstance(value, int) and not isinstance(value, bool):
            candidate = value
        elif isinstance(value, str) and value.isdigit() and 6 <= len(value) <= 10:
            candidate = int(value)
        if candidate is None or candidate < MIN_HEURISTIC_ID:
            continue
        kind = known_ids.get(candidate)
        if kind is None:
            continue
        target: TargetKey = (kind, candidate)
        if target in _seen:
            continue
        _seen.add(target)
        index.add(target,
                  Reference(container_kind, container_id,
                            "plugin_config_reference", confidence="heuristic"))
