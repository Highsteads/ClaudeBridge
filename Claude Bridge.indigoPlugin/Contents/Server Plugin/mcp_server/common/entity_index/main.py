"""
In-memory entity index for Indigo devices, variables and action groups.

Plain fuzzy text search with difflib — no embeddings, no model and no
database. The package was called "vector_store" until the September 2026
spring clean, a name left over from the LanceDB store it replaced.
"""

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from .synonyms import variants_for_query
from .type_aliases import aliases_for

# A synonym-variant match scores this fraction of the direct-query score, so
# a literal hit on what the user actually typed always outranks an expansion
# ("telly" scoring the TV Plug just below a device literally named telly).
_SYNONYM_DISCOUNT = 0.9


class EntityIndex:
    """Lightweight in-memory entity index with fuzzy text search."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger  = logger or logging.getLogger("Plugin")
        self._store: Dict[str, List[Dict[str, Any]]] = {
            "devices":   [],
            "variables": [],
            "actions":   [],
        }
        self.logger.info("Entity index initialised")

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def load_entities(
        self,
        devices:   List[Dict[str, Any]],
        variables: List[Dict[str, Any]],
        actions:   List[Dict[str, Any]],
    ) -> None:
        """Store entity lists for search. Called by EntityIndexManager."""
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

        # Type-alias category bridge: e.g. "light" -> a dimmer's aliases,
        # "plug" -> a relay's, "motion" -> an occupancy sensor's. Aliases are
        # computed here (not stored), never appear in results, and rank below
        # name/description matches so a real name hit always wins.
        aliases = aliases_for(entity)
        if aliases:
            if q in aliases:
                return 0.7
            if words and all(w in aliases for w in words):
                return 0.7

        # Partial word matches across name + description + aliases
        if words:
            matched = sum(1 for w in words if w in name or w in desc or w in aliases)
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
            (results, metadata) — metadata carries total_found,
            total_returned and truncated
        """
        if entity_types is None:
            entity_types = ["devices", "variables", "actions"]

        # Query-time synonym expansion: "telly" also tries "tv"/"television",
        # "lounge" also tries "living room". Computed ONCE per search; each
        # variant scores with a small discount so literal matches win.
        variants = variants_for_query(query)

        results = []
        for et in entity_types:
            if et not in self._store:
                continue
            for entity in self._store[et]:
                score = self._score(query, entity)
                for variant in variants:
                    if score >= 1.0:
                        break  # already a perfect literal hit
                    variant_score = self._score(variant, entity) * _SYNONYM_DISCOUNT
                    if variant_score > score:
                        score = variant_score
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
    # Stats / lifecycle
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        return {
            "tables": {k: len(v) for k, v in self._store.items()},
        }

    def close(self) -> None:
        self._store = {"devices": [], "variables": [], "actions": []}
        self.logger.debug("Entity index closed")
