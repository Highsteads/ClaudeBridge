"""
Abstract vector store interface for semantic search operations.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class VectorStoreInterface(ABC):
    """Abstract interface for vector store operations."""
    
    @abstractmethod
    def search(
        self, 
        query: str, 
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        similarity_threshold: float = 0.7
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Search for entities using semantic similarity.
        
        Args:
            query: Natural language search query
            entity_types: Optional list of entity types to filter ('devices', 'variables', 'actions')
            top_k: Maximum number of results to return
            similarity_threshold: Minimum similarity score threshold
            
        Returns:
            Tuple of (search results with similarity scores, metadata dict)
            Metadata includes: total_found, total_returned, truncated
        """
        pass
    
    @abstractmethod
    def update_embeddings(
        self,
        devices: Optional[List[Dict[str, Any]]] = None,
        variables: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Update vector embeddings for entities.
        
        Args:
            devices: Optional list of device data
            variables: Optional list of variable data
            actions: Optional list of action data
        """
        pass
    
    @abstractmethod
    def add_entity(self, entity_type: str, entity_data: Dict[str, Any]) -> None:
        """
        Add a single entity to the vector store.
        
        Args:
            entity_type: Type of entity ('device', 'variable', 'action')
            entity_data: Entity data dictionary
        """
        pass
    
    @abstractmethod
    def remove_entity(self, entity_type: str, entity_id: int) -> None:
        """
        Remove an entity from the vector store.
        
        Args:
            entity_type: Type of entity ('device', 'variable', 'action')
            entity_id: Entity ID to remove
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the vector store and clean up resources."""
        pass