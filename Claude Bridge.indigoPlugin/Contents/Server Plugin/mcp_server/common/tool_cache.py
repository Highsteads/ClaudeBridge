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

# Map mutating tool → buckets to invalidate
_INVALIDATION_MAP: Dict[str, Set[str]] = {
    "device_turn_on":           _DEVICE_TOOLS,
    "device_turn_off":          _DEVICE_TOOLS,
    "device_set_brightness":    _DEVICE_TOOLS,
    "device_control":           _DEVICE_TOOLS,
    "variable_create":          _VARIABLE_TOOLS,
    "variable_update":          _VARIABLE_TOOLS,
    "action_execute_group":     _ACTION_TOOLS | _DEVICE_TOOLS,
    "enable_schedule":          _SCHEDULE_TOOLS,
    "disable_schedule":         _SCHEDULE_TOOLS,
    "enable_trigger":           _TRIGGER_TOOLS,
    "disable_trigger":          _TRIGGER_TOOLS,
    "plugin_control":           _PLUGIN_TOOLS,
    "restart_plugin":           _PLUGIN_TOOLS,
    "write_script":             _SCRIPT_TOOLS,
    "create_script":            _SCRIPT_TOOLS,
    "delete_script":            _SCRIPT_TOOLS,
    "remember":                 _MEMORY_TOOLS,
    "forget":                   _MEMORY_TOOLS,
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

        # Lifetime stats — surfaced via /health
        self.hits   = 0
        self.misses = 0
        self.invalidations = 0

    # ── Public API ────────────────────────────────────────────────────────

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
    ) -> Tuple[Any, bool]:
        """
        Return ``(value, cache_hit)``. If the tool is not cacheable or the
        client requested ``Cache-Control: no-cache``, ``compute()`` runs and
        the result is *not* stored.
        """
        if no_cache or not self.is_cacheable(tool_name) or self.default_ttl == 0:
            return compute(), False

        key = self.make_key(tool_name, args)
        now = time.monotonic()

        # Fast path — read under lock
        with self._lock:
            entry = self._store.get(key)
            if entry and entry[0] > now:
                self.hits += 1
                return entry[1], True
            elif entry:
                # expired
                self._store.pop(key, None)

        # Miss — compute outside the lock to avoid serialising callers
        result = compute()
        with self._lock:
            self._store[key] = (now + self.default_ttl, result)
            self.misses += 1
        return result, False

    def invalidate_for_tool(self, mutating_tool: str) -> int:
        """
        Drop every cached entry sourced from a tool in the bucket(s) mapped
        from *mutating_tool*. Returns the count of dropped entries.
        """
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
