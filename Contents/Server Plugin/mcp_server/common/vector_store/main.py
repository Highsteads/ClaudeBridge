"""
Simple in-memory text search store for Indigo entities.
Replaces the original LanceDB vector store — no embeddings required.
Uses difflib fuzzy matching for natural-language entity search.
"""

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from ...adapters.vector_store_interface import VectorStoreInterface


class VectorStore(VectorStoreInterface):
    """
    Lightweight in-memory entity store with fuzzy text search.
    Implements VectorStoreInterface so all callers work unchanged.
    """

    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self.db_path = db_path  # Retained for interface compatibility
        self.logger  = logger or logging.getLogger("Plugin")
        self._store: Dict[str, List[Dict[str, Any]]] = {
            "devices":   [],
            "variables": [],
            "actions":   [],
        }
        self.logger.info("Text search store initialised (no embeddings required)")

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def update_embeddings(
        self,
        devices:   List[Dict[str, Any]],
        variables: List[Dict[str, Any]],
        actions:   List[Dict[str, Any]],
    ) -> None:
        """Store entity lists for search. Called by VectorStoreManager."""
        self._store["devices"]   = list(devices)
        self._store["variables"] = list(variables)
        self._store["actions"]   = list(actions)
        self.logger.debug(
            f"Store updated: {len(devices)} devices, "
            f"{len(variables)} variables, {len(actions)} actions"
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, query: str, entity: Dict[str, Any]) -> float:
        """Return a 0.0-1.0 relevance score for an entity against a query."""
        q     = query.lower().strip()
        name  = str(entity.get("name",        "")).lower()
        desc  = str(entity.get("description", "")).lower()
        model = str(entity.get("model",       "")).lower()
        words = q.split()

        # Exact substring in name
        if q in name:
            return 1.0

        # All query words present in name
        if words and all(w in name for w in words):
            return 0.95

        # Fuzzy ratio on name
        ratio = SequenceMatcher(None, q, name).ratio()
        if ratio >= 0.6:
            return ratio

        # Exact substring in description or model
        if q in desc or q in model:
            return 0.75

        # Partial word matches across name + description
        if words:
            matched = sum(1 for w in words if w in name or w in desc)
            if matched:
                return 0.5 * (matched / len(words))

        return 0.0

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query:                str,
        entity_types:         Optional[List[str]] = None,
        top_k:                int   = 10,
        similarity_threshold: float = 0.3,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Search entities using fuzzy text matching.

        Args:
            query:                Natural language search query
            entity_types:         Entity types to search ('devices', 'variables', 'actions')
            top_k:                Maximum results to return
            similarity_threshold: Minimum score (0-1) to include a result

        Returns:
            (results, metadata) matching the VectorStoreInterface contract
        """
        if entity_types is None:
            entity_types = ["devices", "variables", "actions"]

        results = []
        for et in entity_types:
            if et not in self._store:
                continue
            for entity in self._store[et]:
                score = self._score(query, entity)
                if score >= similarity_threshold:
                    item = dict(entity)
                    item["_similarity_score"] = score
                    item["_entity_type"]      = et.rstrip("s")  # 'devices' -> 'device'
                    results.append(item)

        results.sort(key=lambda x: x["_similarity_score"], reverse=True)
        limited  = results[:top_k]
        total    = len(results)
        metadata = {
            "total_found":    total,
            "total_returned": len(limited),
            "truncated":      total > top_k,
        }
        return limited, metadata

    # ------------------------------------------------------------------
    # Single-entity helpers
    # ------------------------------------------------------------------

    def add_entity(self, entity_type: str, entity_data: Dict[str, Any]) -> None:
        table = entity_type if entity_type.endswith("s") else entity_type + "s"
        if table in self._store:
            eid = entity_data.get("id")
            self._store[table] = [e for e in self._store[table] if e.get("id") != eid]
            self._store[table].append(entity_data)

    def remove_entity(self, entity_type: str, entity_id: int) -> None:
        table = entity_type if entity_type.endswith("s") else entity_type + "s"
        if table in self._store:
            self._store[table] = [
                e for e in self._store[table] if e.get("id") != entity_id
            ]

    # ------------------------------------------------------------------
    # Stats / lifecycle
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        return {
            "database_path": self.db_path,
            "dimension":     0,
            "tables":        {k: len(v) for k, v in self._store.items()},
        }

    def close(self) -> None:
        self._store = {"devices": [], "variables": [], "actions": []}
        self.logger.debug("Text search store closed")
