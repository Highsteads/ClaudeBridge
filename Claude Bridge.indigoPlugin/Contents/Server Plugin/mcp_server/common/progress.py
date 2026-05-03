"""
Buffered Server-Sent-Events (SSE) progress emitter.

Why "buffered"?
    Indigo's IWS plugin handlers return *one* synchronous response dict per
    request. Real-time chunked streaming would require running our own HTTP
    server on a dedicated port (à la ShellyDirect's port 8178). That's
    roadmapped as a Phase-3 change.

    In the meantime, long tools can push progress events into a per-call
    :class:`ProgressEmitter`; the dispatcher concatenates them as SSE-encoded
    JSON-RPC ``notifications/progress`` messages followed by the final
    ``tools/call`` result, all bundled into a single ``text/event-stream``
    response. The client (``mcp-remote`` / ``indigo_mcp_proxy.py``) already
    knows how to parse multi-event SSE bodies, so the protocol shape is
    correct — Claude sees ordered progress + result. Phase 3 will swap the
    bundled body for true chunked delivery without any client-side change.

Usage from a tool function::

    def _tool_long_audit(self, **kwargs):
        emitter = self._current_emitter      # set by dispatcher per-call
        if emitter:
            emitter.emit("Scanning devices…", progress=0.1)
        # ... do work ...
        if emitter:
            emitter.emit("Cross-referencing variables…", progress=0.6)
        return result_string
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional


class ProgressEmitter:
    """Per-tool-call collector for progress notifications.

    The emitter is created by the dispatcher just before the tool runs and
    handed to the tool via a thread-local on the handler. The dispatcher reads
    :attr:`events` after the tool returns and decides whether to encode the
    response as SSE.
    """

    def __init__(self, request_id: Any, tool_name: str) -> None:
        self.request_id = request_id
        self.tool_name  = tool_name
        self.events: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._counter = 0

    def emit(
        self,
        message: str,
        progress: Optional[float] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a progress notification.

        Args:
            message:   Short human-readable status.
            progress:  Optional float in [0.0, 1.0]; rendered by clients.
            data:      Optional structured payload (counts, partial results …).
        """
        with self._lock:
            self._counter += 1
            entry: Dict[str, Any] = {
                "step":      self._counter,
                "message":   message,
                "timestamp": time.time(),
            }
            if progress is not None:
                try:
                    entry["progress"] = max(0.0, min(1.0, float(progress)))
                except (TypeError, ValueError):
                    pass
            if data:
                entry["data"] = data
            self.events.append(entry)

    @property
    def has_events(self) -> bool:
        return bool(self.events)


# ─── SSE encoding ────────────────────────────────────────────────────────────

def _sse_block(payload: Dict[str, Any]) -> str:
    """Encode a single JSON-RPC message as one SSE ``data:`` block."""
    return "data: " + json.dumps(payload, default=str) + "\n\n"


def encode_sse_response(
    progress_events: List[Dict[str, Any]],
    final_response:  Dict[str, Any],
    request_id:      Any,
) -> str:
    """
    Build a multi-event SSE body:

        data: {progress notification 1}\\n\\n
        data: {progress notification 2}\\n\\n
        ...
        data: {final tools/call response}\\n\\n
        data: [DONE]\\n\\n

    The ``[DONE]`` sentinel matches what indigo_mcp_proxy.py's SSE reader
    already short-circuits on, so existing clients work unchanged.
    """
    blocks: List[str] = []

    for ev in progress_events:
        notif = {
            "jsonrpc": "2.0",
            "method":  "notifications/progress",
            "params": {
                "progressToken": request_id,
                "progress":      ev.get("progress"),
                "message":       ev.get("message"),
                "step":          ev.get("step"),
                **({"data": ev["data"]} if ev.get("data") else {}),
            },
        }
        # Drop None values so clients don't see explicit nulls
        notif["params"] = {k: v for k, v in notif["params"].items() if v is not None}
        blocks.append(_sse_block(notif))

    blocks.append(_sse_block(final_response))
    blocks.append("data: [DONE]\n\n")
    return "".join(blocks)
