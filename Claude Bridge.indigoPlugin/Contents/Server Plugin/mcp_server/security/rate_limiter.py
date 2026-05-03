"""
Per-session sliding-window rate limiter for Claude Bridge MCP requests.

Two limits, both sliding-window (more accurate than fixed buckets):
  - Per-minute  (default 120)
  - Per-day     (default 5000)

Limits are configurable per scope: 'admin' tokens get 10x the default.
A ``RateLimitExceeded`` exception is raised on overflow; the dispatcher
converts it into a JSON-RPC error (-32099 in the server-defined range).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple


class RateLimitExceeded(Exception):
    """Raised when a session has exhausted its quota for the current window."""

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
    Sliding-window limiter keyed by session id.

    Args:
        per_minute:   Max requests per 60-second window (per session).
        per_day:      Max requests per 86400-second window.
        admin_multiplier: Limit multiplier for sessions whose scopes include 'admin'.
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

        # session_id → deque of timestamps (oldest first)
        self._minute_log: Dict[str, Deque[float]] = defaultdict(deque)
        self._day_log:    Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _limits_for_scope(self, scopes: set) -> Tuple[int, int]:
        if "admin" in scopes:
            return (
                int(self.per_minute * self.admin_multiplier),
                int(self.per_day    * self.admin_multiplier),
            )
        return self.per_minute, self.per_day

    def check(self, session_id: str, scopes: set) -> None:
        """
        Record the current request and raise RateLimitExceeded if quota blown.
        Always called *before* tool dispatch so a denied request consumes nothing.
        """
        if not session_id:
            session_id = "anonymous"

        now = time.monotonic()
        per_minute, per_day = self._limits_for_scope(scopes or set())

        with self._lock:
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
                raise RateLimitExceeded("session", "per_minute", per_minute, retry)
            if len(day_log) >= per_day:
                retry = self.DAY - (now - day_log[0])
                raise RateLimitExceeded("session", "per_day", per_day, retry)

            # Record
            min_log.append(now)
            day_log.append(now)

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        """Return current usage per session — used by /health endpoint."""
        with self._lock:
            return {
                sid: {
                    "minute": len(self._minute_log.get(sid, ())),
                    "day":    len(self._day_log.get(sid, ())),
                }
                for sid in set(self._minute_log) | set(self._day_log)
            }

    def reset_session(self, session_id: str) -> None:
        """Forget a session's history — call when a session terminates."""
        with self._lock:
            self._minute_log.pop(session_id, None)
            self._day_log.pop(session_id, None)
