"""
Interfaces and abstract base classes for the MCP server components.
"""

from .data_provider import DataProvider
from .vector_store_interface import VectorStoreInterface

__all__ = ['DataProvider', 'VectorStoreInterface']