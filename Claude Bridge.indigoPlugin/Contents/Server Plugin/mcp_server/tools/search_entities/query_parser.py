"""
Query parser for natural language search queries.
"""

import logging
import re
from typing import Dict, Any, List, Optional
from ...common.state_filter import StateFilter

logger = logging.getLogger("Plugin")


class QueryParser:
    """Parses natural language queries to extract search parameters."""
    
    def parse(
        self, 
        query: str, 
        device_types: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Parse query to extract search parameters.
        
        Args:
            query: Natural language search query
            device_types: Optional list of device types to filter by
            entity_types: Optional list of entity types to search
            
        Returns:
            Dictionary with search parameters:
            - entity_types: List of entity types to search (plural form for vector store)
            - device_types: List of device types to filter by
            - top_k: Maximum number of results
            - threshold: Similarity threshold
            - minimal_fields: Whether to use minimal fields for large result sets
        """
        # Default parameters
        params = {
            "entity_types": ["devices", "variables", "actions"],
            "device_types": device_types or [],
            "top_k": 3,   # Return top 3 by default; exact matches short-circuit to 1
            "threshold": 0.15,  # Lower threshold to capture more relevant results
            "minimal_fields": True   # Slim by default for speed
        }
        
        # Convert to lowercase for analysis
        query_lower = query.lower()
        
        # Determine entity types to search
        # If device_types is provided, we only search devices
        if device_types is not None and len(device_types) > 0:
            params["entity_types"] = ["devices"]
        # Otherwise use explicit entity_types parameter if provided
        elif entity_types is not None:
            # Convert singular entity types to plural for vector store compatibility
            plural_mapping = {
                "device": "devices",
                "variable": "variables", 
                "action": "actions"
            }
            params["entity_types"] = [plural_mapping.get(et, et) for et in entity_types]
        # Finally, parse from query if no explicit parameters
        else:
            params["entity_types"] = self._extract_entity_types(query_lower)
        
        # Adjust result count and field detail based on query
        params["top_k"], params["minimal_fields"] = self._extract_result_count_and_fields(query_lower)
        
        # Check for state requirements and adjust parameters accordingly
        if StateFilter.has_state_keywords(query):
            # State queries need more results to find matches after filtering
            params["top_k"] = max(params["top_k"], 50)
            params["state_detected"] = True
        else:
            params["state_detected"] = False

        # A device_types filter is applied AFTER the store truncates to top_k
        # (SearchEntities.search -> _filter_devices_by_type). Over-fetch so the
        # type filter sees a full candidate set — otherwise a query that also
        # fuzzy-matches many other-type entities can truncate the matching-type
        # devices away and the filtered result comes back short or empty. Mirrors
        # the state-filter over-fetch above.
        if device_types is not None and len(device_types) > 0:
            params["top_k"] = max(params["top_k"], 50)
        
        # Adjust threshold for specific queries
        params["threshold"] = self._extract_similarity_threshold(query_lower)
        
        return params
    
    def _extract_entity_types(self, query_lower: str) -> List[str]:
        """Extract entity types to search from query."""
        # Always search all entity types to ensure comprehensive results
        # This prevents missing relevant actions or variables due to keyword ambiguity
        return ["devices", "variables", "actions"]
    
    def _extract_result_count_and_fields(self, query_lower: str) -> tuple[int, bool]:
        """Extract desired result count and whether to use minimal fields from query."""
        if re.search(r'\ball\b', query_lower):
            return 50, True  # Many results with minimal fields
        elif re.search(r'\bmany\b', query_lower) or re.search(r'\blist\b', query_lower):
            return 20, True  # Moderate results with minimal fields
        elif re.search(r'\bfew\b', query_lower) or re.search(r'\bsome\b', query_lower):
            return 5, False  # Few results with full fields
        elif re.search(r'\bone\b', query_lower) or re.search(r'\bsingle\b', query_lower):
            return 1, False  # Single result with full fields
        
        # Default result count with full fields
        return 10, False
    
    def _extract_similarity_threshold(self, query_lower: str) -> float:
        """Extract similarity threshold from query."""
        if re.search(r'\bexact\b', query_lower) or re.search(r'\bspecific\b', query_lower):
            return 0.7
        elif re.search(r'\bsimilar\b', query_lower) or re.search(r'\blike\b', query_lower):
            return 0.2
        elif re.search(r'\brelated\b', query_lower) or re.search(r'\bclose\b', query_lower):
            return 0.4
        
        # Default threshold
        return 0.15