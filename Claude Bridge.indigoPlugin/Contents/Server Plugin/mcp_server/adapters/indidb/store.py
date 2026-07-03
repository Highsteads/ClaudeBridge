"""
Cached, read-only access to the parsed .indiDb automation structures.

The Indigo server rewrites the database file within minutes of any change,
so a parse is cached on (mtime, size) and refreshed lazily. A failed parse
(torn mid-rewrite read) keeps the last good snapshot; the next access
retries. os.stat checks are throttled so bursts of tool calls don't hammer
the filesystem.
"""

import datetime
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .parser import ParsedDb, parse_indidb
from .reverse_index import build_reverse_index

_KIND_TO_ATTR = {
    "trigger":      "triggers",
    "schedule":     "schedules",
    "action_group": "action_groups",
}

FRESHNESS_NOTE = (
    "Action steps and conditions are read from Indigo's database file, which "
    "the server rewrites within minutes of changes — very recent edits may "
    "not be reflected yet."
)


class IndiDbStructureStore:
    """Lazy, mtime-cached, strictly read-only view of the database file."""

    def __init__(
        self,
        db_path_supplier: Callable[[], Optional[str]],
        logger: Optional[logging.Logger] = None,
        stat_throttle_seconds: float = 2.0,
    ):
        """
        Args:
            db_path_supplier: returns the .indiDb path — in production a
                lambda around indigo.server.getDbFilePath(), in tests a
                fixture path. May return None when unavailable.
            logger: plugin logger.
            stat_throttle_seconds: minimum interval between os.stat checks.
        """
        self._db_path_supplier = db_path_supplier
        self.logger = logger or logging.getLogger("Plugin")
        self._stat_throttle_seconds = stat_throttle_seconds
        self._lock = threading.Lock()
        self._snapshot: Optional[ParsedDb] = None
        self._last_stat_time = 0.0

    # ── Public accessors — degrade to None/empty rather than raising ────────

    def get_structure(self, kind: str, entity_id: int) -> Optional[dict]:
        """Decoded record dict for one trigger / schedule / action_group."""
        snapshot = self._refresh_if_stale()
        attr = _KIND_TO_ATTR.get(kind)
        if snapshot is None or attr is None:
            return None
        return getattr(snapshot, attr).get(entity_id)

    def get_all_structures(self, kind: str) -> Dict[int, dict]:
        snapshot = self._refresh_if_stale()
        attr = _KIND_TO_ATTR.get(kind)
        if snapshot is None or attr is None:
            return {}
        return getattr(snapshot, attr)

    def find_references(self, entity_kind: str, entity_id: int) -> List[Dict[str, Any]]:
        """Role-tagged containers referencing (entity_kind, entity_id)."""
        snapshot = self._refresh_if_stale()
        if snapshot is None or snapshot.reverse_index is None:
            return []
        return snapshot.reverse_index.references_to(entity_kind, entity_id)

    def lookup_name(self, entity_kind: str, entity_id: int) -> Optional[str]:
        """Name resolution from the file (devices/variables/automations)."""
        snapshot = self._refresh_if_stale()
        if snapshot is None:
            return None
        if entity_kind == "device":
            return snapshot.device_names.get(entity_id)
        if entity_kind == "variable":
            return snapshot.variable_names.get(entity_id)
        attr = _KIND_TO_ATTR.get(entity_kind)
        if attr is not None:
            record = getattr(snapshot, attr).get(entity_id)
            if isinstance(record, dict):
                return record.get("Name")
        return None

    def freshness(self) -> Dict[str, Any]:
        """Provenance metadata attached to tool responses."""
        snapshot = self._refresh_if_stale()
        if snapshot is None:
            return {"available": False,
                    "note": "Indigo database file not readable — action steps "
                            "and conditions unavailable."}
        return {
            "available": True,
            "file_modified": datetime.datetime.fromtimestamp(snapshot.mtime).isoformat(),
            "counts": snapshot.counts(),
            "note": FRESHNESS_NOTE,
        }

    # ── Cache management ─────────────────────────────────────────────────────

    def _refresh_if_stale(self) -> Optional[ParsedDb]:
        with self._lock:
            now = time.monotonic()
            if (self._snapshot is not None
                    and (now - self._last_stat_time) < self._stat_throttle_seconds):
                return self._snapshot

            try:
                path = self._db_path_supplier()
            except Exception as exc:
                self.logger.debug(f"[indidb] db path lookup failed: {exc}")
                return self._snapshot
            if not path or not os.path.isfile(path):
                return self._snapshot

            self._last_stat_time = now
            try:
                stat = os.stat(path)
            except OSError as exc:
                self.logger.debug(f"[indidb] stat failed: {exc}")
                return self._snapshot

            if (self._snapshot is not None
                    and stat.st_mtime == self._snapshot.mtime
                    and stat.st_size == self._snapshot.size):
                return self._snapshot

            try:
                started = time.monotonic()
                parsed = parse_indidb(path)
                parsed.mtime = stat.st_mtime
                parsed.size = stat.st_size
                parsed.reverse_index = build_reverse_index(parsed)
                self._snapshot = parsed
                elapsed_ms = (time.monotonic() - started) * 1000
                self.logger.debug(
                    f"[indidb] parsed in {elapsed_ms:.0f}ms: {parsed.counts()}")
            except Exception as exc:
                # A mid-rewrite read can hand us a torn file. Keep the last
                # good snapshot; the next access retries.
                self.logger.debug(f"[indidb] parse failed (mid-rewrite?): {exc}")
            return self._snapshot
