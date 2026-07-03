"""
TTL cache for read-only MCP tool results.

When Claude is iterating on a problem it often calls the same read tool many
times in quick succession (``list_devices``, ``get_devices_by_type``,
``home_status``, etc.). Caching those results for a short TTL — keyed by
(tool_name, arguments) — saves Indigo round-trips without making the data
meaningfully stale.

The cache is conservative by design:
  - Only tools in the explicit ``CACHEABLE_TOOLS`` allow-list are cached.
  - Default TTL is 60 seconds (configurable, max 300).
  - Clients can opt out per request via ``Cache-Control: no-cache``.
  - Mutating tools (anything in the WRITE/ADMIN scope sets) invalidate
    related cache buckets — see :meth:`invalidate_for_tool`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple


# ─── Cacheable tools allow-list ──────────────────────────────────────────────

CACHEABLE_TOOLS: Set[str] = {
    # Search / list
    "search_entities",
    "get_devices_by_type", "get_devices_by_state",
    "list_devices", "list_variables", "list_action_groups",
    "list_schedules", "list_triggers", "list_plugins",
    "list_python_scripts", "list_subscriptions", "list_script_backups",
    "list_variable_folders",
    # Get-by-id
    "get_device_by_id", "get_variable_by_id", "get_action_group_by_id",
    "get_plugin_by_id", "get_plugin_status",
    # Audits / find / health
    "audit_home", "audit_variables", "system_health",
    "find_devices_in_error", "find_low_battery", "find_stale_devices",
    "find_orphaned_scripts", "find_orphaned_plugin_data", "find_large_files",
    "find_conflicts", "dependency_map",
    # Status reports
    "home_status", "home_status_report",
    "energy_status", "heating_status", "security_status",
    # Memory recall
    "recall", "recall_topics",
    # Read scripts
    "read_script",
    # Energy
    "energy_log_days", "energy_daily_summary", "energy_compare",
}


# Buckets used for invalidation. When a write tool fires, every cached entry
# whose source tool sits in the matching bucket(s) is dropped.
_DEVICE_TOOLS = {
    "search_entities", "get_devices_by_type", "get_devices_by_state",
    "list_devices", "get_device_by_id",
    "audit_home", "find_devices_in_error", "find_low_battery", "find_stale_devices",
    "home_status", "home_status_report", "dependency_map",
}
_VARIABLE_TOOLS = {
    "list_variables", "list_variable_folders", "get_variable_by_id",
    "audit_variables",
}
_ACTION_TOOLS = {"list_action_groups", "get_action_group_by_id"}
_SCHEDULE_TOOLS = {"list_schedules"}
_TRIGGER_TOOLS = {"list_triggers"}
_PLUGIN_TOOLS = {"list_plugins", "get_plugin_by_id", "get_plugin_status"}
_SCRIPT_TOOLS = {"list_python_scripts", "list_script_backups", "read_script",
                 "find_orphaned_scripts"}
_MEMORY_TOOLS = {"recall", "recall_topics"}
_SUBSCRIPTION_TOOLS = {"list_subscriptions"}

# Arbitrary-mutation tools whose effect on cached state can't be scoped to a
# single entity bucket — invalidate EVERYTHING for these.
_CLEAR_ALL_TOOLS: Set[str] = {
    "execute_indigo_python",
    "run_script",
}

# Map mutating tool → buckets to invalidate
_INVALIDATION_MAP: Dict[str, Set[str]] = {
    # ── Device on/off/brightness/colour ─────────────────────────────────
    "device_turn_on":           _DEVICE_TOOLS,
    "device_turn_off":          _DEVICE_TOOLS,
    "device_set_brightness":    _DEVICE_TOOLS,
    "device_control":           _DEVICE_TOOLS,
    "device_toggle":            _DEVICE_TOOLS,
    "dimmer_brighten_by":       _DEVICE_TOOLS,
    "dimmer_dim_by":            _DEVICE_TOOLS,
    "set_color":                _DEVICE_TOOLS,
    "lock_device":              _DEVICE_TOOLS,
    "unlock_device":            _DEVICE_TOOLS,
    "request_status_update":    _DEVICE_TOOLS,
    # ── Thermostat / fan / speed ────────────────────────────────────────
    "set_heat_setpoint":        _DEVICE_TOOLS,
    "increase_heat_setpoint":   _DEVICE_TOOLS,
    "decrease_heat_setpoint":   _DEVICE_TOOLS,
    "set_cool_setpoint":        _DEVICE_TOOLS,
    "set_hvac_mode":            _DEVICE_TOOLS,
    "set_fan_mode":             _DEVICE_TOOLS,
    "set_fan_speed":            _DEVICE_TOOLS,
    "speedcontrol_set_index":   _DEVICE_TOOLS,
    "speedcontrol_increase":    _DEVICE_TOOLS,
    "speedcontrol_decrease":    _DEVICE_TOOLS,
    # ── Sprinkler ───────────────────────────────────────────────────────
    "sprinkler_run":            _DEVICE_TOOLS,
    "sprinkler_stop":           _DEVICE_TOOLS,
    "sprinkler_pause":          _DEVICE_TOOLS,
    "sprinkler_resume":         _DEVICE_TOOLS,
    "sprinkler_set_zone":       _DEVICE_TOOLS,
    "sprinkler_next_zone":      _DEVICE_TOOLS,
    "sprinkler_previous_zone":  _DEVICE_TOOLS,
    # ── Device lifecycle / metadata ─────────────────────────────────────
    "enable_device":            _DEVICE_TOOLS,
    "rename_device":            _DEVICE_TOOLS,
    "move_device_to_folder":    _DEVICE_TOOLS,
    "duplicate_device":         _DEVICE_TOOLS,
    "delete_device":            _DEVICE_TOOLS,
    # ── v2.9.0 additions ────────────────────────────────────────────────
    "reset_energy_accumulator": _DEVICE_TOOLS,
    "device_remove_delayed_actions": _DEVICE_TOOLS,
    "all_lights_off":           _DEVICE_TOOLS,
    "all_lights_on":            _DEVICE_TOOLS,
    "all_devices_off":          _DEVICE_TOOLS,
    "delete_device_folder":     _DEVICE_TOOLS,
    "delete_variable_folder":   _VARIABLE_TOOLS,
    # beep_device / ping_device deliberately absent — they change no cached state.
    # ── Variables ───────────────────────────────────────────────────────
    "variable_create":          _VARIABLE_TOOLS,
    "variable_update":          _VARIABLE_TOOLS,
    "variable_delete":          _VARIABLE_TOOLS,
    "variable_move_to_folder":  _VARIABLE_TOOLS,
    "create_variable_folder":   _VARIABLE_TOOLS,   # shows up in list_variable_folders
    "create_device_folder":     _DEVICE_TOOLS,
    # ── Subscriptions (change list_subscriptions output) ────────────────
    "subscribe":                _SUBSCRIPTION_TOOLS,
    "unsubscribe":              _SUBSCRIPTION_TOOLS,
    # ── Action groups ───────────────────────────────────────────────────
    "action_execute_group":     _ACTION_TOOLS | _DEVICE_TOOLS,
    "duplicate_action_group":   _ACTION_TOOLS,
    "delete_action_group":      _ACTION_TOOLS,
    # ── Schedules ───────────────────────────────────────────────────────
    "enable_schedule":          _SCHEDULE_TOOLS,
    "disable_schedule":         _SCHEDULE_TOOLS,
    "duplicate_schedule":       _SCHEDULE_TOOLS,
    "delete_schedule":          _SCHEDULE_TOOLS,
    # Firing a schedule runs its actions, which can move device/variable state.
    "execute_schedule_now":     _SCHEDULE_TOOLS | _DEVICE_TOOLS | _VARIABLE_TOOLS,
    "schedule_remove_delayed_actions": _SCHEDULE_TOOLS,
    "remove_all_delayed_actions":      _SCHEDULE_TOOLS,
    # ── Triggers ────────────────────────────────────────────────────────
    "enable_trigger":           _TRIGGER_TOOLS,
    "disable_trigger":          _TRIGGER_TOOLS,
    "move_trigger_to_folder":   _TRIGGER_TOOLS,
    "delete_trigger":           _TRIGGER_TOOLS,
    "fire_trigger":             _DEVICE_TOOLS | _VARIABLE_TOOLS,  # may cause side-effects
    # ── Plugins ─────────────────────────────────────────────────────────
    "restart_plugin":           _PLUGIN_TOOLS,
    # ── Scripts ─────────────────────────────────────────────────────────
    "write_script":             _SCRIPT_TOOLS,
    "create_script":            _SCRIPT_TOOLS,
    "delete_script":            _SCRIPT_TOOLS,
    # ── Memory ──────────────────────────────────────────────────────────
    "remember":                 _MEMORY_TOOLS,
    "forget":                   _MEMORY_TOOLS,
    # ── Events ──────────────────────────────────────────────────────────
    "fire_indigo_event":        _DEVICE_TOOLS | _VARIABLE_TOOLS,  # may cause side-effects
}


# ─── Cache implementation ────────────────────────────────────────────────────

class ToolCache:
    """Thread-safe TTL cache for read-only tool results."""

    DEFAULT_TTL = 60   # seconds
    MAX_TTL     = 300  # cap to keep "stale" honest

    def __init__(
        self,
        default_ttl: int = DEFAULT_TTL,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.default_ttl = max(0, min(int(default_ttl), self.MAX_TTL))
        self.logger      = logger or logging.getLogger("Plugin")

        # key = (tool_name, args_json) → (expires_at, result_str)
        self._store: Dict[Tuple[str, str], Tuple[float, Any]] = {}
        self._lock  = threading.Lock()
        self._last_sweep = 0.0   # monotonic ts of last expired-entry sweep

        # Per-key in-flight state so concurrent identical misses share one
        # compute() (avoids the thundering-herd duplicate the cache exists to
        # prevent). Each entry is [lock, waiter_count]; the entry is removed
        # once the last waiter has finished, so it never leaks. Guarded by
        # _lock for creation/cleanup.
        self._inflight: Dict[Tuple[str, str], list] = {}

        # Lifetime stats — surfaced via /health
        self.hits   = 0
        self.misses = 0
        self.invalidations = 0

    # ── Public API ────────────────────────────────────────────────────────

    def _sweep_expired_locked(self, now: float) -> None:
        """
        Drop entries whose TTL has lapsed. Expired entries are normally removed
        on re-read, but a key that is never requested again would otherwise sit
        in the dict forever. Runs at most once per TTL window so it adds no
        meaningful cost to the hot path. MUST be called with _lock held.
        """
        if now - self._last_sweep < max(self.default_ttl, 1):
            return
        self._last_sweep = now
        expired = [k for k, (expires_at, _) in self._store.items() if expires_at <= now]
        for k in expired:
            del self._store[k]

    @staticmethod
    def is_cacheable(tool_name: str) -> bool:
        return tool_name in CACHEABLE_TOOLS

    @staticmethod
    def make_key(tool_name: str, args: Dict[str, Any]) -> Tuple[str, str]:
        """Stable cache key — args sorted so {a:1,b:2} matches {b:2,a:1}."""
        try:
            args_json = json.dumps(args or {}, sort_keys=True, default=str)
        except Exception:
            args_json = repr(args)
        return (tool_name, args_json)

    def get_or_compute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        compute: Callable[[], Any],
        no_cache: bool = False,
        cache_ok: Optional[Callable[[Any], bool]] = None,
    ) -> Tuple[Any, bool]:
        """
        Return ``(value, cache_hit)``. If the tool is not cacheable or the
        client requested ``Cache-Control: no-cache``, ``compute()`` runs and
        the result is *not* stored.

        ``cache_ok`` is an optional predicate on the computed value: when it
        returns False the value is returned to the caller but NOT stored. The
        dispatch layer uses this so a tool that returns an error result (tools
        return an ``{"error": ...}`` payload instead of raising) is never cached
        and re-served as a "hit" for the full TTL.
        """
        if no_cache or not self.is_cacheable(tool_name) or self.default_ttl == 0:
            return compute(), False

        key = self.make_key(tool_name, args)

        # Fast path — read under lock
        with self._lock:
            now = time.monotonic()
            self._sweep_expired_locked(now)
            entry = self._store.get(key)
            if entry and entry[0] > now:
                self.hits += 1
                return entry[1], True
            elif entry:
                # expired
                self._store.pop(key, None)
            # Reserve (or join) the per-key in-flight slot for this miss so
            # concurrent identical misses don't all run compute(). slot is
            # [lock, waiter_count]; waiter_count tracks how many callers still
            # hold a reference, so the slot can be removed only by the last one.
            slot = self._inflight.get(key)
            if slot is None:
                slot = [threading.Lock(), 0]
                self._inflight[key] = slot
            slot[1] += 1
            inflight = slot[0]

        # Miss — serialise only callers for the SAME key (other keys still run
        # concurrently). The first to acquire computes; the rest then find the
        # freshly cached value.
        try:
            with inflight:
                with self._lock:
                    entry = self._store.get(key)
                    now = time.monotonic()
                    if entry and entry[0] > now:
                        self.hits += 1
                        # We waited on another caller that already computed this.
                        return entry[1], True

                # Compute outside the store lock to avoid serialising callers
                # for other keys.
                result = compute()
                store_it = cache_ok is None or cache_ok(result)
                with self._lock:
                    if store_it:
                        # Stamp expiry from AFTER compute() so a slow compute does
                        # not shorten the effective TTL.
                        self._store[key] = (time.monotonic() + self.default_ttl, result)
                    self.misses += 1
                return result, False
        finally:
            # Drop our reference; remove the slot once the last waiter is done.
            with self._lock:
                slot = self._inflight.get(key)
                if slot is not None:
                    slot[1] -= 1
                    if slot[1] <= 0:
                        self._inflight.pop(key, None)

    def invalidate_for_tool(self, mutating_tool: str) -> int:
        """
        Drop every cached entry sourced from a tool in the bucket(s) mapped
        from *mutating_tool*. Returns the count of dropped entries.

        Arbitrary-mutation tools (execute_indigo_python, run_script) can change
        any entity, so they clear the whole cache rather than a single bucket.
        """
        if mutating_tool in _CLEAR_ALL_TOOLS:
            n = self.clear()
            if n:
                with self._lock:
                    self.invalidations += n
            return n

        buckets = _INVALIDATION_MAP.get(mutating_tool)
        if not buckets:
            return 0
        with self._lock:
            keys_to_drop = [k for k in self._store if k[0] in buckets]
            for k in keys_to_drop:
                del self._store[k]
            if keys_to_drop:
                self.invalidations += len(keys_to_drop)
            return len(keys_to_drop)

    def clear(self) -> int:
        """Drop everything. Returns count cleared."""
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "ttl_seconds":   self.default_ttl,
                "entries":       len(self._store),
                "hits":          self.hits,
                "misses":        self.misses,
                "invalidations": self.invalidations,
                "hit_rate": (
                    round(self.hits / (self.hits + self.misses), 3)
                    if (self.hits + self.misses) else 0
                ),
            }

    def set_ttl(self, ttl_seconds: int) -> None:
        """Live-update TTL from PluginConfig changes. 0 disables caching."""
        self.default_ttl = max(0, min(int(ttl_seconds), self.MAX_TTL))
        if self.default_ttl == 0:
            self.clear()
