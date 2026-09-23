"""
TTL cache for read-only MCP tool results.

When Claude is iterating on a problem it often calls the same read tool many
times in quick succession (``list_devices``, ``audit``,
``home_status``, etc.). Caching those results for a short TTL — keyed by
(tool_name, arguments) — saves Indigo round-trips without making the data
meaningfully stale.

The cache is conservative by design:
  - Only tools declared cacheable=True in the registry are cached.
  - Default TTL is 60 seconds (configurable, max 300).
  - Clients can opt out per request via ``Cache-Control: no-cache``.
  - Mutating tools invalidate the buckets they declare — see
    :meth:`invalidate_for_tool`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


# ─── What is cached, and what drops it ───────────────────────────────────────
#
# Declared on each tool in mcp_server/toolsets/ and derived from the registry
# (mcp_server/registry.py) — nothing is listed here by hand. Until 3.0 this
# module held a cacheable allow-list, seven bucket sets and a 70-line
# invalidation map, kept in step with the tools by hand; the update_* writers
# were once missing from it and a renamed trigger read under its old name for
# the whole TTL.
#
#   cacheable=True, reads={...}   a read tool whose answer may be cached; reads
#                                 names the buckets that answer depends on
#   invalidates={...}             a mutating tool drops every cached answer whose
#                                 reads meet these buckets; {"*"} drops them all
#
# ─── Real-world change tracking ──────────────────────────────────────────────
#
# The invalidation above only covers ClaudeBridge's OWN mutating tools. But the
# world changes without asking us: a light switched at the wall, by a Z-Wave
# association, by an Indigo trigger, or by any other plugin. The plugin sees
# every one of those in deviceUpdated / variableUpdated. Rather than drop
# entries eagerly on each (a presence-sensor storm would thrash the store under
# a lock), the "device" and "variable" buckets each carry a counter that those
# callbacks bump — O(1), no iteration. A cached entry records the counters it
# was computed under, and a read whose stamp no longer matches is a miss.
_DOMAIN_DEVICE   = "device"
_DOMAIN_VARIABLE = "variable"
_DOMAIN_ACTION_GROUP = "action_group"
_DOMAINS = (_DOMAIN_DEVICE, _DOMAIN_VARIABLE, _DOMAIN_ACTION_GROUP)


def _registry():
    from .. import registry
    return registry


def __getattr__(name: str):
    """The pre-3.0 module constants, derived from the registry on access."""
    reg = _registry()
    if name == "CACHEABLE_TOOLS":
        return set(reg.cacheable_names())
    if name == "_INVALIDATION_MAP":
        return {k: set(v) for k, v in reg.invalidation_map().items()}
    if name == "_CLEAR_ALL_TOOLS":
        return set(reg.clear_all_names())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        # Bumped on every invalidation/clear. A compute() that spans a bump ran
        # against now-invalidated state, so its result must NOT be stored — else
        # a read that started before a mutation could reinstate a stale entry
        # AFTER the invalidation dropped it (a TOCTOU that would survive to TTL).
        self._generation = 0

        # Per-domain change counters, bumped by note_external_change() from the
        # plugin's deviceUpdated / variableUpdated callbacks.
        self._domain_gen: Dict[str, int] = {d: 0 for d in _DOMAINS}

        # Lifetime stats — surfaced via /health
        self.hits   = 0
        self.misses = 0
        self.invalidations = 0
        self.stale_drops   = 0   # entries dropped because the world moved on

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
        expired = [k for k, entry in self._store.items() if entry[0] <= now]
        for k in expired:
            del self._store[k]

    @staticmethod
    def is_cacheable(tool_name: str) -> bool:
        spec = _registry().spec_for(tool_name)
        return bool(spec is not None and spec.cacheable)

    def _domain_stamp_locked(self, tool_name: str) -> Tuple:
        """Snapshot the change counters this tool's answer depends on.

        MUST be called with _lock held. A tool that reads neither domain (system
        health, script listings) is unaffected by device or variable traffic and
        gets an empty stamp.
        """
        domains = _registry().reads_of(tool_name) & set(_DOMAINS)
        if not domains:
            return ()
        return tuple(sorted((d, self._domain_gen.get(d, 0)) for d in domains))

    def note_external_change(self, domain: str) -> None:
        """Record that the real world changed under us.

        Called from the plugin's deviceUpdated / variableUpdated callbacks for
        changes this plugin did NOT make. Deliberately O(1): a busy estate fires
        these constantly, so this must never walk the store.
        """
        if domain not in self._domain_gen:
            return
        with self._lock:
            self._domain_gen[domain] += 1

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

        with self._lock:
            now = time.monotonic()
            self._sweep_expired_locked(now)
            entry = self._store.get(key)
            stamp_at_start = self._domain_stamp_locked(tool_name)
            if entry and entry[0] > now and entry[2] == stamp_at_start:
                self.hits += 1
                return entry[1], True
            elif entry:
                # Expired, or a device/variable changed since it was computed.
                if entry[0] > now:
                    self.stale_drops += 1
                self._store.pop(key, None)
            gen_at_start = self._generation

        # Miss. No per-key coalescing: Indigo dispatches every IWS request on
        # the plugin's one MainThread (see common/exec_lock.py), so two calls
        # for the same key can never be computing at once. Compute outside
        # the lock all the same, so the lock is never held across tool code.
        result = compute()
        store_it = cache_ok is None or cache_ok(result)
        with self._lock:
            # If an invalidation/clear happened WHILE we were computing, our
            # result reflects pre-mutation state — do not store it, or it
            # would reinstate a stale entry the invalidation just dropped.
            if self._generation != gen_at_start:
                store_it = False
            # Same reasoning for real-world changes: if a device or variable
            # moved WHILE we were computing, the result is already pre-change.
            stamp_now = self._domain_stamp_locked(tool_name)
            if stamp_now != stamp_at_start:
                store_it = False
            if store_it:
                # Stamp expiry from AFTER compute() so a slow compute does not
                # shorten the effective TTL.
                self._store[key] = (time.monotonic() + self.default_ttl,
                                    result, stamp_now)
            self.misses += 1
        return result, False

    def invalidate_for_tool(self, mutating_tool: str) -> int:
        """
        Drop every cached entry sourced from a tool in the bucket(s) mapped
        from *mutating_tool*. Returns the count of dropped entries.

        Arbitrary-mutation tools (execute_indigo_python, run_script) can change
        any entity, so they clear the whole cache rather than a single bucket.
        """
        spec = _registry().spec_for(mutating_tool)
        changed = spec.invalidates if spec is not None else frozenset()
        if "*" in changed:
            n = self.clear()
            if n:
                with self._lock:
                    self.invalidations += n
            return n

        if not changed:
            return 0
        reads_of = _registry().reads_of
        with self._lock:
            # Bump generation for EVERY real invalidation, even if nothing is
            # cached right now — an in-flight compute for one of these buckets
            # must still be prevented from storing its pre-mutation result.
            self._generation += 1
            keys_to_drop = [k for k in self._store if reads_of(k[0]) & changed]
            for k in keys_to_drop:
                del self._store[k]
            if keys_to_drop:
                self.invalidations += len(keys_to_drop)
            return len(keys_to_drop)

    def clear(self) -> int:
        """Drop everything. Returns count cleared."""
        with self._lock:
            self._generation += 1
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
                "stale_drops":   self.stale_drops,
                "domain_gen":    dict(self._domain_gen),
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
