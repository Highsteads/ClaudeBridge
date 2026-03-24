"""
Result formatter for search results.
"""

from typing import Dict, Any, List, Optional
from ...common.json_encoder import filter_json, KEYS_TO_KEEP_MINIMAL_DEVICES
from ...common.state_filter import StateFilter


class ResultFormatter:
    """Formats search results for different output requirements."""
    
    def format_search_results(
        self, 
        results: Dict[str, List[Dict]], 
        query: str,
        minimal_fields: bool = False,
        search_metadata: Optional[Dict[str, Any]] = None,
        state_detected: bool = False
    ) -> Dict[str, Any]:
        """
        Format search results for output.
        
        Args:
            results: Raw search results from vector store
            query: Original search query
            minimal_fields: Whether to use minimal fields for devices
            search_metadata: Metadata from vector store search
            
        Returns:
            Formatted results dictionary
        """
        # Count total results
        total_count = sum(len(entities) for entities in results.values())
        
        # Create summary with metadata information
        summary = self._create_summary(results, total_count, minimal_fields, search_metadata, state_detected)
        
        # Format individual results
        formatted = {
            "query": query,
            "summary": summary,
            "total_count": total_count,
            "results": {}
        }
        
        # Add state query suggestion if appropriate
        if state_detected and search_metadata and search_metadata.get("truncated", False):
            formatted["suggestion"] = "State-based query detected with truncated results. Consider using list_devices(state_filter={...}) or get_devices_by_state() for complete state information."
        
        # Add results for each entity type
        for entity_type, entities in results.items():
            formatted["results"][entity_type] = self._format_entity_list(entity_type, entities, minimal_fields)
        
        return formatted
    
    def _create_summary(
        self, 
        results: Dict[str, List[Dict]], 
        total_count: int, 
        minimal_fields: bool = False,
        search_metadata: Optional[Dict[str, Any]] = None,
        state_detected: bool = False
    ) -> str:
        """Create a summary text for the search results."""
        summary = []
        for entity_type, entities in results.items():
            if entities:
                summary.append(f"{len(entities)} {entity_type}")

        # Base summary
        if search_metadata and search_metadata.get("truncated", False):
            # Results were truncated by top_k
            total_found = search_metadata.get("total_found", total_count)
            summary_text = f"Found {total_found} entities (showing top {total_count}"
            if minimal_fields:
                summary_text += " with minimal fields"
            summary_text += " - use more specific query for additional results)"
        else:
            # All results shown
            summary_text = f"Found {total_count} entities"
            if minimal_fields:
                summary_text += " (minimal fields)"

        if summary:
            summary_text += f" ({', '.join(summary)})"

        return summary_text
    
    def _format_entity_list(self, entity_type: str, entities: List[Dict], minimal_fields: bool = False) -> List[Dict[str, Any]]:
        """Format a list of entities for a specific type."""
        formatted_entities = []
        
        for entity in entities:
            # Extract similarity score
            score = entity.pop("_similarity_score", 0.0)
            
            # Create base formatted entry
            formatted_entry = {
                "id": entity.get("id"),
                "name": entity.get("name", "Unknown"),
                "relevance_score": round(score, 3)
            }
            
            # Add type-specific fields
            if entity_type == "devices":
                formatted_entry.update(self._format_device_fields(entity, minimal_fields))
            elif entity_type == "variables":
                formatted_entry.update(self._format_variable_fields(entity))
            elif entity_type == "actions":
                formatted_entry.update(self._format_action_fields(entity))
            
            formatted_entities.append(formatted_entry)
        
        return formatted_entities
    
    def _format_device_fields(self, device: Dict[str, Any], minimal_fields: bool = False) -> Dict[str, Any]:
        """Format device-specific fields - return all or minimal properties except internal ones."""
        if minimal_fields:
            # Use minimal fields + states for large result sets
            minimal_keys = KEYS_TO_KEEP_MINIMAL_DEVICES + ["states"]
            filtered_device = filter_json(device, minimal_keys)
            # Remove internal fields
            return {k: v for k, v in filtered_device.items() if not k.startswith('_')}
        else:
            # Return all device properties except internal ones (starting with _)
            return {k: v for k, v in device.items() if not k.startswith('_')}
    
    def _format_variable_fields(self, variable: Dict[str, Any]) -> Dict[str, Any]:
        """Format variable-specific fields."""
        return {
            "value": variable.get("value", ""),
            "folder_id": variable.get("folderId", 0),
            "read_only": variable.get("readOnly", False)
        }
    
    def _format_action_fields(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Format action-specific fields."""
        return {
            "folder_id": action.get("folderId", 0),
            "description": action.get("description", "")
        }