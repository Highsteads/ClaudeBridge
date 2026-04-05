"""
Events handler for ClaudeBridge MCP server.

Implements a subscription queue model:
  - ClaudeBridge plugin.py calls queue_event() from deviceUpdated /
    variableUpdated / triggerStartProcessing callbacks
  - Claude polls with get_events() to drain the queue
  - Claude can subscribe to specific device/variable IDs or all changes

Tools:
  - subscribe(entity_type, entity_id=None) : register interest in changes
  - unsubscribe(subscription_id)           : remove a subscription
  - get_events(since=None, limit=50)       : drain queued events
  - list_subscriptions()                   : show active subscriptions
  - clear_events()                         : flush the event queue
"""

import logging
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Union

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

MAX_QUEUE   = 500     # ring buffer size
MAX_SUBS    = 50      # maximum simultaneous subscriptions


class EventsHandler(BaseToolHandler):
    """
    Handler for the Indigo → Claude event subscription queue.
    Thread-safe: queue_event() is called from Indigo's main thread via plugin
    callbacks; get_events() is called from IWS request handler threads.
    Uses a deque as a lock-free ring buffer (GIL-protected in CPython).
    """

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="events", logger=logger)
        self.data_provider  = data_provider
        self._queue: Deque[Dict[str, Any]] = deque(maxlen=MAX_QUEUE)
        self._subscriptions: Dict[int, Dict[str, Any]] = {}
        self._next_sub_id   = 1

    # ────────────────────────────────────────────────────────────────────────
    # Called by plugin.py callbacks (NOT a Claude tool)
    # ────────────────────────────────────────────────────────────────────────

    def queue_event(self, event: Dict[str, Any]) -> None:
        """
        Enqueue an event. Called from Indigo main-thread callbacks.
        Accepts "id" or "entity_id" for the entity identifier (normalises both).
        Stamps every event with timestamp_epoch for since-filtering.
        Deduplicates rapid state changes for the same entity within 1 second:
        only the first and last value are kept (merged in-place).
        Only queued if at least one matching subscription exists.
        """
        if not self._subscriptions:
            return   # no active subscriptions — nothing to queue

        # Normalise: accept both "id" and "entity_id" from callers
        entity_id = event.get("entity_id") or event.get("id")
        if entity_id is not None:
            event["entity_id"] = entity_id

        entity_type = event.get("type", "")

        # Stamp with epoch for since-filtering and human timestamp
        now_ts = time.time()
        event.setdefault("timestamp_epoch", now_ts)
        event.setdefault(
            "timestamp",
            datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Deduplication: merge into the most recent event for the same entity
        # if it arrived within the last second.
        DEDUP_WINDOW_S = 1.0
        if entity_id is not None and entity_type in (
            "device_updated", "variable_updated"
        ):
            for existing in reversed(self._queue):
                if (
                    existing.get("entity_id") == entity_id
                    and existing.get("type") == entity_type
                ):
                    age = now_ts - existing.get("timestamp_epoch", 0)
                    if age < DEDUP_WINDOW_S:
                        # Merge: keep old "old" values, update "new" values
                        if entity_type == "device_updated":
                            merged = dict(existing.get("changed_states", {}))
                            for k, v in event.get("changed_states", {}).items():
                                merged[k] = {
                                    "old": merged[k]["old"] if k in merged else v["old"],
                                    "new": v["new"],
                                }
                            existing["changed_states"] = merged
                        else:  # variable_updated
                            existing["new_value"] = event.get("new_value")
                        existing["timestamp_epoch"] = now_ts
                        existing["timestamp"]       = event["timestamp"]
                        return  # merged in-place, no new entry needed
                    break  # found same entity but outside window — fall through

        for sub in self._subscriptions.values():
            sub_type = sub.get("entity_type", "all")
            sub_id   = sub.get("entity_id")   # None = all of that type

            type_match = (sub_type == "all" or sub_type == entity_type
                          or entity_type.startswith(sub_type))
            id_match   = (sub_id is None or sub_id == entity_id)

            if type_match and id_match:
                self._queue.append(event)
                break   # queue once even if multiple subscriptions match

    # ────────────────────────────────────────────────────────────────────────
    # subscribe
    # ────────────────────────────────────────────────────────────────────────

    def subscribe(
        self,
        entity_type: str = "all",
        entity_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Register interest in Indigo change events.

        entity_type: "device", "variable", "trigger", or "all"
        entity_id:   specific device/variable ID to watch, or None for all
        """
        self.log_incoming_request("subscribe",
                                  {"entity_type": entity_type, "entity_id": entity_id})
        try:
            if len(self._subscriptions) >= MAX_SUBS:
                return {"success": False,
                        "error": f"Maximum {MAX_SUBS} subscriptions reached"}

            sub_id = self._next_sub_id
            self._next_sub_id += 1
            self._subscriptions[sub_id] = {
                "id":          sub_id,
                "entity_type": entity_type,
                "entity_id":   int(entity_id) if entity_id else None,
                "created":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            label = (f"type={entity_type}"
                     + (f", id={entity_id}" if entity_id else " (all)"))
            result = {
                "success":         True,
                "subscription_id": sub_id,
                "watching":        label,
                "message": (f"Subscribed to {label}. "
                            f"Use get_events() to poll for changes."),
            }
            self.log_tool_outcome("subscribe", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "subscribe")

    # ────────────────────────────────────────────────────────────────────────
    # unsubscribe
    # ────────────────────────────────────────────────────────────────────────

    def unsubscribe(self, subscription_id: int) -> Dict[str, Any]:
        """Remove a subscription by ID."""
        self.log_incoming_request("unsubscribe",
                                  {"subscription_id": subscription_id})
        try:
            sid = int(subscription_id)
            if sid in self._subscriptions:
                del self._subscriptions[sid]
                result = {"success": True,
                          "message": f"Subscription {sid} removed"}
            else:
                result = {"success": False,
                          "error": f"Subscription {sid} not found"}
            self.log_tool_outcome("unsubscribe", result["success"],
                                  result.get("message", ""))
            return result
        except Exception as exc:
            return self.handle_exception(exc, "unsubscribe")

    # ────────────────────────────────────────────────────────────────────────
    # get_events
    # ────────────────────────────────────────────────────────────────────────

    def get_events(
        self,
        since: Optional[float] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Return queued events, optionally filtered to those after `since`
        (Unix timestamp). Drains returned events from the queue.

        Typical usage: call once, process results, store the timestamp of
        the last event, then pass it as `since` on the next call.
        """
        self.log_incoming_request("get_events",
                                  {"since": since, "limit": limit})
        try:
            events: List[Dict[str, Any]] = []
            remaining: Deque[Dict[str, Any]] = deque(maxlen=MAX_QUEUE)

            while self._queue:
                evt = self._queue.popleft()
                ts  = evt.get("timestamp_epoch", 0)
                if since is None or ts > since:
                    if len(events) < limit:
                        events.append(evt)
                    else:
                        remaining.append(evt)   # keep overflow
                # else: discard old events

            # Put overflow back
            self._queue.extendleft(reversed(remaining))

            result = {
                "success":            True,
                "count":              len(events),
                "queue_remaining":    len(self._queue),
                "active_subscriptions": len(self._subscriptions),
                "events":             events,
            }
            if events:
                result["latest_timestamp"] = events[-1].get("timestamp_epoch")
            self.log_tool_outcome("get_events", True,
                                  f"{len(events)} events returned")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "get_events")

    # ────────────────────────────────────────────────────────────────────────
    # list_subscriptions
    # ────────────────────────────────────────────────────────────────────────

    def list_subscriptions(self) -> Dict[str, Any]:
        """Return all active subscriptions and queue depth."""
        self.log_incoming_request("list_subscriptions", {})
        try:
            result = {
                "success":       True,
                "count":         len(self._subscriptions),
                "queue_depth":   len(self._queue),
                "subscriptions": list(self._subscriptions.values()),
            }
            self.log_tool_outcome("list_subscriptions", True,
                                  f"{len(self._subscriptions)} subscriptions")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "list_subscriptions")

    # ────────────────────────────────────────────────────────────────────────
    # clear_events
    # ────────────────────────────────────────────────────────────────────────

    def clear_events(self) -> Dict[str, Any]:
        """Flush all queued events without returning them."""
        self.log_incoming_request("clear_events", {})
        try:
            count = len(self._queue)
            self._queue.clear()
            result = {
                "success": True,
                "cleared": count,
                "message": f"Flushed {count} queued events",
            }
            self.log_tool_outcome("clear_events", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "clear_events")
