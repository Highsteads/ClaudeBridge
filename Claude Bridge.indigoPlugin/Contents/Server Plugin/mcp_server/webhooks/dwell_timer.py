"""
Dwell timers for duration-gated subscriptions.

When a subscription sets `duration_seconds`, the matched condition must HOLD for
that long before the webhook fires ("garage open for 10 minutes"). Each pending
dwell is a threading.Timer keyed by subscription+entity; if the condition
reverts before the timer expires, the timer is cancelled and nothing fires.

Pending timers are intentionally NOT persisted — on a plugin restart they simply
re-arm the next time the condition transitions into match. Original ClaudeBridge
implementation, stdlib only.
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional


class DwellTimerQueue:
    """Tracks pending dwell timers and fires a callback when one elapses."""

    def __init__(
        self,
        on_elapsed: Callable[[Any, Any], None],
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            on_elapsed: called as on_elapsed(subscription, event) when a dwell
                        timer completes without being cancelled.
            logger: optional logger.
        """
        self._on_elapsed = on_elapsed
        self._logger = logger or logging.getLogger(__name__)
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(subscription_id: str, entity_id: Any) -> str:
        return f"{subscription_id}:{entity_id}"

    def start(self, subscription: Any, event: Any, seconds: int, entity_id: Any) -> None:
        """Arm a dwell timer. If one is already pending for this
        subscription+entity, leave it running (the condition was already
        matching) rather than restarting the clock."""
        key = self._key(subscription.subscription_id, entity_id)
        with self._lock:
            if key in self._timers:
                return

            def _fire():
                with self._lock:
                    self._timers.pop(key, None)
                try:
                    self._on_elapsed(subscription, event)
                except Exception:
                    self._logger.exception(f"Dwell callback failed for {key}")

            timer = threading.Timer(seconds, _fire)
            timer.daemon = True
            self._timers[key] = timer
            timer.start()
            self._logger.debug(f"Dwell timer armed: {key} ({seconds}s)")

    def cancel(self, subscription_id: str, entity_id: Any) -> None:
        """Cancel a pending dwell timer (the condition reverted before expiry)."""
        key = self._key(subscription_id, entity_id)
        with self._lock:
            timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()
            self._logger.debug(f"Dwell timer cancelled: {key}")

    def cancel_subscription(self, subscription_id: str) -> None:
        """Cancel every pending timer belonging to a subscription. Needed for
        wildcard subs (entity_id=None) whose timers are keyed by the actual
        per-event entity id, so a single (sub_id, entity_id) cancel can't reach
        them — without this they'd orphan and could fire after delete()."""
        prefix = f"{subscription_id}:"
        with self._lock:
            keys = [k for k in self._timers if k.startswith(prefix)]
            timers = [self._timers.pop(k) for k in keys]
        for timer in timers:
            timer.cancel()
        if timers:
            self._logger.debug(f"Cancelled {len(timers)} dwell timer(s) for {subscription_id}")

    def cancel_all(self) -> None:
        """Cancel every pending timer (called on shutdown)."""
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        if timers:
            self._logger.debug(f"Cancelled {len(timers)} pending dwell timers")

    def pending(self) -> int:
        with self._lock:
            return len(self._timers)
