"""
Per-access-key sliding-window rate limiter for Claude Bridge MCP requests.

Two limits, both sliding-window (more accurate than fixed buckets):
  - Per-minute  (default 120)
  - Per-day     (default 5000)

The limits count calls per ACCESS KEY (the bearer token), not per session: a
client that opens a new session keeps its key's count. A key with the 'admin'
scope gets 10x the configured figures — and with no scopes.json every key is
admin, so on a stock install the limits actually applied are 1,200 a minute
and 50,000 a day. /health reports the limits in force for each key.
A ``RateLimitExceeded`` exception is raised on overflow; the dispatcher
converts it into a JSON-RPC error (-32099 in the server-defined range).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional, Tuple


class RateLimitExceeded(Exception):
    """Raised when an access key has used up its quota for the current window."""

    def __init__(self, scope: str, window: str, limit: int, retry_after: float):
        self.scope       = scope
        self.window      = window
        self.limit       = limit
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded ({window}={limit} for scope={scope}); "
            f"retry in {retry_after:.0f}s"
        )


class RateLimiter:
    """
    Sliding-window limiter keyed by caller: the dispatcher passes the bearer
    token when there is one (so a client that rotates sessions still shares
    one bucket per credential), else the Mcp-Session-Id, else "anonymous".

    Args:
        per_minute:   Max requests per 60-second window (per caller).
        per_day:      Max requests per 86400-second window.
        admin_multiplier: Limit multiplier for keys whose scopes include 'admin'.
                          Defaults to 10x — admin tooling shouldn't be throttled hard.
        logger:       Optional logger.
    """

    MINUTE = 60
    DAY    = 86_400

    def __init__(
        self,
        per_minute: int = 120,
        per_day:    int = 5_000,
        admin_multiplier: float = 10.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.per_minute       = max(1, int(per_minute))
        self.per_day          = max(1, int(per_day))
        self.admin_multiplier = max(1.0, float(admin_multiplier))
        self.logger           = logger or logging.getLogger("Plugin")

        # caller key (bearer, session id or "anonymous") → deque of timestamps (oldest first)
        self._minute_log: Dict[str, Deque[float]] = defaultdict(deque)
        self._day_log:    Dict[str, Deque[float]] = defaultdict(deque)
        # caller key → whether its last call was counted at the admin limits
        self._key_admin:  Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0   # monotonic ts of last stale-key sweep

    def _limits_for_scope(self, scopes: set) -> Tuple[int, int]:
        return self._limits(admin="admin" in scopes)

    def _limits(self, admin: bool) -> Tuple[int, int]:
        if admin:
            return (
                int(self.per_minute * self.admin_multiplier),
                int(self.per_day    * self.admin_multiplier),
            )
        return self.per_minute, self.per_day

    def effective_limits(self) -> Dict[str, Dict[str, int]]:
        """The limits actually applied, by kind of key — what Configure's two
        figures become once the admin multiplier is in."""
        out = {}
        for label, admin in (("admin", True), ("read_or_write", False)):
            per_minute, per_day = self._limits(admin)
            out[label] = {"per_minute": per_minute, "per_day": per_day}
        return out

    def _sweep_locked(self, now: float) -> None:
        """
        Drop keys whose day-window is fully expired. Runs at most once a minute
        so the per-key dicts cannot grow unbounded from rotating session ids.
        MUST hold _lock.
        """
        if now - self._last_sweep < self.MINUTE:
            return
        self._last_sweep = now
        day_cutoff = now - self.DAY
        for sid in list(self._day_log.keys()):
            dl = self._day_log[sid]
            while dl and dl[0] < day_cutoff:
                dl.popleft()
            if not dl:
                self._day_log.pop(sid, None)
                self._minute_log.pop(sid, None)   # minute entries are older still
                self._key_admin.pop(sid, None)

    def check(self, session_id: str, scopes: set) -> None:
        """
        Record the current request and raise RateLimitExceeded if quota blown.
        Always called *before* tool dispatch so a denied request consumes nothing.
        """
        if not session_id:
            session_id = "anonymous"

        now = time.monotonic()
        is_admin = "admin" in (scopes or set())
        per_minute, per_day = self._limits(is_admin)
        kind = "admin" if is_admin else "read_or_write"

        with self._lock:
            self._sweep_locked(now)
            self._key_admin[session_id] = is_admin
            min_log = self._minute_log[session_id]
            day_log = self._day_log[session_id]

            # Drop expired entries
            min_cutoff = now - self.MINUTE
            day_cutoff = now - self.DAY
            while min_log and min_log[0] < min_cutoff:
                min_log.popleft()
            while day_log and day_log[0] < day_cutoff:
                day_log.popleft()

            # Enforce
            if len(min_log) >= per_minute:
                retry = self.MINUTE - (now - min_log[0])
                raise RateLimitExceeded(kind, "per_minute", per_minute, retry)
            if len(day_log) >= per_day:
                retry = self.DAY - (now - day_log[0])
                raise RateLimitExceeded(kind, "per_day", per_day, retry)

            # Record
            min_log.append(now)
            day_log.append(now)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Return current usage per access key, with the limits that key is
        held to — used by the /health endpoint.

        The bucket key is the RAW bearer token (see check(): keyed on
        `bearer or session_id`). /health is only IWS-bearer-gated, travels over
        the reflector, and the Show Health menu writes it to the event log — so
        the key MUST be masked here or a low-privilege token holder could harvest
        another client's admin bearer. We publish a non-reversible short digest,
        which still uniquely distinguishes callers for the usage counts.
        """
        with self._lock:
            out: Dict[str, Dict[str, Any]] = {}
            for sid in set(self._minute_log) | set(self._day_log):
                is_admin = self._key_admin.get(sid, False)
                per_minute, per_day = self._limits(is_admin)
                out[self._mask_key(sid)] = {
                    "minute":           len(self._minute_log.get(sid, ())),
                    "day":              len(self._day_log.get(sid, ())),
                    "limit_per_minute": per_minute,
                    "limit_per_day":    per_day,
                    "admin":            is_admin,
                }
            return out

    @staticmethod
    def _mask_key(key: str) -> str:
        """Non-reversible label for a rate-limit key (bearer token/session id)."""
        if not key or key == "anonymous":
            return key or "anonymous"
        return "token-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]

    def reset_session(self, session_id: str) -> None:
        """Forget one caller key's history."""
        with self._lock:
            self._minute_log.pop(session_id, None)
            self._day_log.pop(session_id, None)
            self._key_admin.pop(session_id, None)
