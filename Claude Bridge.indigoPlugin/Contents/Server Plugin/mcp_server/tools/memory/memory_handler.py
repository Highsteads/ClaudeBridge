"""
Memory handler for ClaudeBridge MCP server.

Provides persistent key/value memory across Claude Code sessions.
Notes are stored as a JSON file in the ClaudeBridge preferences folder.

Tools:
  - remember(topic, note)  : store a timestamped note under a topic
  - recall(topic=None)     : retrieve all notes, optionally filtered by topic
  - forget(memory_id)      : delete a specific note by its ID
  - recall_topics()        : list all topics that have notes
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import indigo
except ImportError:
    pass

from ..base_handler import BaseToolHandler
from ...adapters.data_provider import DataProvider

MAX_MEMORIES = 200   # oldest auto-expire beyond this limit


def _memory_path() -> str:
    base = indigo.server.getInstallFolderPath()
    prefs = os.path.join(base, "Preferences", "Plugins",
                         "com.clives.indigoplugin.claudebridge")
    os.makedirs(prefs, exist_ok=True)
    return os.path.join(prefs, "memory.json")


def _load(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save(path: str, memories: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(memories, fh, indent=2, ensure_ascii=False)


class MemoryHandler(BaseToolHandler):
    """Handler for persistent cross-session memory."""

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(tool_name="memory", logger=logger)
        self.data_provider = data_provider

    # ────────────────────────────────────────────────────────────────────────
    # remember
    # ────────────────────────────────────────────────────────────────────────

    def remember(self, topic: str, note: str) -> Dict[str, Any]:
        """Store a note under a topic. Returns the assigned memory ID."""
        self.log_incoming_request("remember", {"topic": topic})
        try:
            path      = _memory_path()
            memories  = _load(path)
            memory_id = int(time.time() * 1000)  # ms epoch as unique ID

            memories.append({
                "id":        memory_id,
                "topic":     topic.strip(),
                "note":      note.strip(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

            # Auto-expire oldest if over limit
            if len(memories) > MAX_MEMORIES:
                memories = memories[-MAX_MEMORIES:]

            _save(path, memories)
            result = {
                "success":   True,
                "memory_id": memory_id,
                "topic":     topic.strip(),
                "message":   f"Remembered under topic '{topic.strip()}'",
            }
            self.log_tool_outcome("remember", True, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "remember")

    # ────────────────────────────────────────────────────────────────────────
    # recall
    # ────────────────────────────────────────────────────────────────────────

    def recall(self, topic: Optional[str] = None) -> Dict[str, Any]:
        """
        Return stored memories. If topic is given, filter to that topic only.
        Results are sorted newest first.
        """
        self.log_incoming_request("recall", {"topic": topic})
        try:
            path     = _memory_path()
            memories = _load(path)

            if topic:
                topic_lower = topic.strip().lower()
                memories = [m for m in memories
                            if m.get("topic", "").lower() == topic_lower]

            memories = list(reversed(memories))  # newest first

            result = {
                "success":  True,
                "count":    len(memories),
                "topic":    topic or "all",
                "memories": memories,
            }
            self.log_tool_outcome("recall", True, f"{len(memories)} memories returned")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "recall")

    # ────────────────────────────────────────────────────────────────────────
    # forget
    # ────────────────────────────────────────────────────────────────────────

    def forget(self, memory_id: int) -> Dict[str, Any]:
        """Delete a memory entry by its ID."""
        self.log_incoming_request("forget", {"memory_id": memory_id})
        try:
            path     = _memory_path()
            memories = _load(path)
            before   = len(memories)
            memories = [m for m in memories if m.get("id") != int(memory_id)]
            removed  = before - len(memories)
            _save(path, memories)

            result = {
                "success": removed > 0,
                "removed": removed,
                "message": (f"Memory {memory_id} deleted"
                            if removed else f"Memory ID {memory_id} not found"),
            }
            self.log_tool_outcome("forget", removed > 0, result["message"])
            return result
        except Exception as exc:
            return self.handle_exception(exc, "forget")

    # ────────────────────────────────────────────────────────────────────────
    # recall_topics
    # ────────────────────────────────────────────────────────────────────────

    def recall_topics(self) -> Dict[str, Any]:
        """Return a list of all topics that have at least one memory, with counts."""
        self.log_incoming_request("recall_topics", {})
        try:
            path     = _memory_path()
            memories = _load(path)

            counts: Dict[str, int] = {}
            for m in memories:
                t = m.get("topic", "uncategorised")
                counts[t] = counts.get(t, 0) + 1

            topics = [{"topic": t, "count": c}
                      for t, c in sorted(counts.items())]

            result = {
                "success":      True,
                "total_memories": len(memories),
                "topic_count":  len(topics),
                "topics":       topics,
            }
            self.log_tool_outcome("recall_topics", True,
                                  f"{len(topics)} topics")
            return result
        except Exception as exc:
            return self.handle_exception(exc, "recall_topics")
