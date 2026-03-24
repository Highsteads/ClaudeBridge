"""
Query parser for natural language search queries.
Enhanced with LLM-based query expansion for better semantic matching.
"""

import hashlib
import logging
import re
from typing import Dict, Any, List, Optional
from ...common.state_filter import StateFilter

logger = logging.getLogger("Plugin")

# Global cache for query expansions
_query_expansion_cache = {}


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
            "top_k": 10,  # Reasonable default for most searches
            "threshold": 0.15,  # Lower threshold to capture more relevant results
            "minimal_fields": False  # Full fields by default
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
    
    def expand_query(self, query: str, enable_llm: bool = True) -> str:
        """
        Expand query with synonyms and related terms for better semantic matching.
        
        Args:
            query: Original search query
            enable_llm: Whether to use LLM for query expansion
            
        Returns:
            Expanded query string with additional terms
        """
        try:
            if not enable_llm or not query.strip():
                logger.debug(f"Query expansion skipped (LLM disabled or empty query)")
                return query
            
            # Check cache first
            cache_key = hashlib.sha256(query.encode()).hexdigest()
            if cache_key in _query_expansion_cache:
                expanded = _query_expansion_cache[cache_key]
                logger.debug(f"Using cached query expansion for: '{query}'")
                return expanded
            
            # Generate expanded query with LLM
            expanded = self._generate_llm_query_expansion(query)
            if expanded and expanded != query:
                _query_expansion_cache[cache_key] = expanded
                logger.debug(f"Query expanded: '{query}' -> '{expanded}'")
                return expanded
            
            return query
            
        except Exception as e:
            logger.warning(f"Query expansion failed for '{query}': {e}")
            return query
    
    def _generate_llm_query_expansion(self, query: str) -> str:
        """
        Use LLM to generate expanded query with synonyms and related terms.
        
        Args:
            query: Original search query
            
        Returns:
            Expanded query or original query if expansion fails
        """
        try:
            # Import here to avoid circular imports
            from ...common.openai_client.main import perform_completion, SMALL_MODEL
            
            # Create prompt for query expansion
            prompt = f"""Expand this home automation search query with relevant synonyms and related terms:

Original query: "{query}"

Generate an expanded version that includes:
- Synonyms for device types (light/lamp/illumination, switch/control, sensor/detector)
- Related location terms (living room/lounge/family room)
- Function synonyms (dimmer/brightness/lighting)

Keep the expansion concise and focused. Return only the expanded query text, no explanations.
Example: "living room light" -> "living room light lamp illumination lighting fixture"
"""

            # Call LLM with small model for efficiency
            response = perform_completion(
                messages=prompt,
                model=SMALL_MODEL,
                response_token_reserve=50
            )
            
            if not response:
                logger.debug(f"Empty LLM response for query expansion")
                return query
            
            # Use standardized response handling utility
            from ...common.response_utils import extract_text_content
            
            expanded = extract_text_content(response, f"query_expansion[{query[:50]}...]")
            
            if not expanded or not expanded.strip():
                # If extraction failed or returned empty string, fallback to original query
                logger.debug(f"LLM expansion extraction failed, using original query")
                expanded = query
            else:
                # Clean up the expanded query
                expanded = expanded.strip().strip('"').strip("'")
            
            # Validate and potentially truncate the expansion if too long
            max_length = min(len(query) * 6, 250)  # Allow up to 250 chars or 6x original, whichever is smaller
            if len(expanded) > max_length:
                # Truncate at word boundary to preserve meaning
                truncated = expanded[:max_length].rstrip()
                # Find the last space to avoid cutting words in half
                last_space = truncated.rfind(' ')
                if last_space > max_length * 0.8:  # Only use word boundary if we don't lose too much
                    truncated = truncated[:last_space]
                
                expanded = truncated
            
            # Check for obvious malformed content (but allow reasonable punctuation)
            if any(char in expanded for char in ['<', '>', '{', '}', '[', ']', '|']):
                return query
            
            return expanded
            
        except Exception as e:
            logger.warning(f"LLM query expansion failed: {e}")
            return query


def clear_query_expansion_cache():
    """Clear the query expansion cache. Useful for testing."""
    global _query_expansion_cache
    _query_expansion_cache.clear()
    logger.debug("Cleared query expansion cache")