"""
Subscription manager — stores subscriptions and evaluates Indigo state changes
against them with transition detection.

Transition detection is the core idea: a subscription fires only when the NEW
state matches its condition AND the OLD state did NOT (a transition INTO match).
That turns "battery below 20%" into a single alert when it crosses the line,
not a flood on every reading while it stays low. Reverting the condition cancels
any pending dwell timer.

Entity dicts are whatever `dict(indigo.Device)` / `dict(indigo.Variable)` yield
(id, name, deviceTypeId, onState, brightness, states{...}, value) — the plugin
passes those straight in, so this module stays pure-dict and unit-testable. Match
conditions reuse CB's existing StateFilter (bare state names, {op: val} comparators);
the special condition {"any_change": true} fires on any change to the entity.

Original ClaudeBridge implementation.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..common.state_filter import StateFilter
from .event_model import Event
from .subscription_model import Subscription
from .subscription_store import SubscriptionStore
from .dwell_timer import DwellTimerQueue


class SubscriptionManager:
    """Thread-safe store + transition-detecting evaluator for subscriptions."""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        store: Optional[SubscriptionStore] = None,
        dispatch_callback: Optional[Callable[[Subscription, Event], None]] = None,
    ):
        self._logger = logger or logging.getLogger(__name__)
        self._subs: Dict[str, Subscription] = {}
        self._lock = threading.Lock()
        self._store = store
        self._dwell: Optional[DwellTimerQueue] = None
        if dispatch_callback:
            self.set_dispatch_callback(dispatch_callback)

    def set_dispatch_callback(self, callback: Callable[[Subscription, Event], None]) -> None:
        """Wire the callback a dwell timer fires when its duration elapses."""
        self._dwell = DwellTimerQueue(on_elapsed=callback, logger=self._logger)

    # ------------------------------------------------------------------
    # CRUD + persistence
    # ------------------------------------------------------------------

    def add(self, sub: Subscription) -> Subscription:
        with self._lock:
            self._subs[sub.subscription_id] = sub
        self._save()
        self._logger.info(
            f"Webhook subscription added: {sub.subscription_id} "
            f"({sub.entity_type}{':' + str(sub.entity_id) if sub.entity_id is not None else ''}) "
            f"-> {sub.webhook_url}"
        )
        return sub

    def delete(self, subscription_id: str) -> bool:
        with self._lock:
            sub = self._subs.pop(subscription_id, None)
        if sub is None:
            return False
        # Cancel ALL of this subscription's dwell timers (covers wildcard subs
        # whose timers are keyed by the per-event entity id, not sub.entity_id).
        if self._dwell:
            self._dwell.cancel_subscription(subscription_id)
        self._save()
        self._logger.info(f"Webhook subscription deleted: {subscription_id}")
        return True

    def get(self, subscription_id: str) -> Optional[Subscription]:
        with self._lock:
            return self._subs.get(subscription_id)

    def list_all(self) -> List[Subscription]:
        with self._lock:
            return list(self._subs.values())

    def count(self) -> int:
        with self._lock:
            return len(self._subs)

    def load_from_store(self) -> int:
        if self._store is None:
            return 0
        loaded = self._store.load()
        with self._lock:
            for sub in loaded:
                self._subs[sub.subscription_id] = sub
        if loaded:
            self._logger.info(f"Loaded {len(loaded)} webhook subscription(s) from disk")
        return len(loaded)

    def save(self) -> None:
        self._save()

    def _save(self) -> None:
        if self._store is None:
            return
        with self._lock:
            snapshot = list(self._subs.values())
        try:
            self._store.save(snapshot)
        except Exception as e:
            self._logger.error(f"Failed to persist webhook subscriptions: {e}")

    def shutdown(self) -> None:
        if self._dwell:
            self._dwell.cancel_all()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_device_change(
        self, orig_dev: Dict[str, Any], new_dev: Dict[str, Any]
    ) -> List[Tuple[Subscription, Event]]:
        """Return (sub, event) pairs whose condition just transitioned into match."""
        if not self._device_changed(orig_dev, new_dev):
            return []
        device_id = new_dev.get("id")
        with self._lock:
            subs = [s for s in self._subs.values()
                    if s.enabled and s.entity_type == "device"]
        return self._evaluate(subs, orig_dev, new_dev, device_id, self._build_device_event)

    def evaluate_variable_change(
        self, orig_var: Dict[str, Any], new_var: Dict[str, Any]
    ) -> List[Tuple[Subscription, Event]]:
        """Same transition detection for variables; value change is the trigger."""
        if orig_var.get("value") == new_var.get("value"):
            return []
        var_id = new_var.get("id")
        with self._lock:
            subs = [s for s in self._subs.values()
                    if s.enabled and s.entity_type == "variable"]
        return self._evaluate(subs, orig_var, new_var, var_id, self._build_variable_event)

    def _evaluate(self, subs, orig, new, entity_id, build_event):
        matches: List[Tuple[Subscription, Event]] = []
        for sub in subs:
            if sub.entity_id is not None and sub.entity_id != entity_id:
                continue

            if sub.conditions.get("any_change"):
                # The quick-reject above already proved a real change happened.
                self._emit(sub, build_event(orig, new, sub), entity_id, matches)
                continue

            new_match = StateFilter.matches_state(new, sub.conditions)
            old_match = StateFilter.matches_state(orig, sub.conditions)
            if new_match and not old_match:
                self._emit(sub, build_event(orig, new, sub), entity_id, matches)
            elif old_match and not new_match:
                if sub.duration_seconds and self._dwell:
                    self._dwell.cancel(sub.subscription_id, entity_id)
        return matches

    def _emit(self, sub, event, entity_id, matches):
        """Either fire now, or arm a dwell timer if the subscription is duration-gated."""
        if sub.duration_seconds and self._dwell:
            self._dwell.start(sub, event, sub.duration_seconds, entity_id)
        else:
            matches.append((sub, event))

    # ------------------------------------------------------------------
    # Change detection + event building
    # ------------------------------------------------------------------

    @staticmethod
    def _device_changed(orig: Dict[str, Any], new: Dict[str, Any]) -> bool:
        for key in ("onState", "onOffState", "brightness", "brightnessLevel"):
            if orig.get(key) != new.get(key):
                return True
        return orig.get("states", {}) != new.get("states", {})

    @staticmethod
    def _changed_keys(orig: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
        changed = []
        for key in ("onState", "onOffState", "brightness", "brightnessLevel", "value"):
            if key in new and orig.get(key) != new.get(key):
                changed.append(key)
        o_states = orig.get("states", {}) or {}
        n_states = new.get("states", {}) or {}
        for key in set(o_states) | set(n_states):
            if o_states.get(key) != n_states.get(key):
                changed.append(f"states.{key}")
        return changed

    def _build_device_event(self, orig, new, sub) -> Event:
        device_id = new.get("id")
        name = new.get("name", "Unknown")
        changed = self._changed_keys(orig, new)
        old_state, new_state = {}, {}
        for key in changed:
            if key.startswith("states."):
                sk = key[7:]
                old_state[key] = (orig.get("states", {}) or {}).get(sk)
                new_state[key] = (new.get("states", {}) or {}).get(sk)
            else:
                old_state[key] = orig.get(key)
                new_state[key] = new.get(key)
        primary = changed[0] if changed else "state"
        summary = ", ".join(f"{k}={new_state.get(k)}" for k in changed[:3])
        return Event(
            event_type="device.state_changed",
            dedupe_key=f"indigo:device:{device_id}:{primary}:{new_state.get(primary, '')}",
            entity={"kind": "device", "id": device_id, "name": name,
                    "device_type": new.get("deviceTypeId", "device")},
            state={"changed": changed, "old": old_state, "new": new_state},
            trigger={"subscription_id": sub.subscription_id, "conditions": sub.conditions},
            human={"title": f"{name} changed", "summary": f"{name}: {summary}"},
        )

    def _build_variable_event(self, orig, new, sub) -> Event:
        var_id = new.get("id")
        name = new.get("name", "Unknown")
        old_value = orig.get("value")
        new_value = new.get("value")
        return Event(
            event_type="variable.value_changed",
            dedupe_key=f"indigo:variable:{var_id}:value:{new_value}",
            entity={"kind": "variable", "id": var_id, "name": name},
            state={"changed": ["value"], "old": {"value": old_value}, "new": {"value": new_value}},
            trigger={"subscription_id": sub.subscription_id, "conditions": sub.conditions},
            human={"title": f"{name} changed", "summary": f"{name}: {old_value} -> {new_value}"},
        )
