"""
InfluxDB client and utilities for MCP server.

This module provides the main interface for InfluxDB operations, following
the common library pattern with main.py as the primary entry point.
"""

import logging
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from .client import InfluxDBClient
from .queries import InfluxDBQueryBuilder
from .time_utils import TimeFormatter

# Module-level logger
logger = logging.getLogger("Plugin")

# Export the main classes for easy import
__all__ = [
    'InfluxDBClient',
    'InfluxDBQueryBuilder', 
    'TimeFormatter',
    'create_influxdb_client',
    'is_influxdb_enabled'
]


def create_influxdb_client(logger_instance: Optional[logging.Logger] = None) -> InfluxDBClient:
    """
    Create a new InfluxDB client instance.
    
    Args:
        logger_instance: Optional logger instance
        
    Returns:
        InfluxDBClient instance
    """
    return InfluxDBClient(logger=logger_instance or logger)


def is_influxdb_enabled() -> bool:
    """
    Check if InfluxDB integration is enabled.
    
    Returns:
        True if InfluxDB is enabled via environment variables
    """
    client = create_influxdb_client()
    return client.is_enabled()


# Convenience functions for common operations
def get_query_builder() -> InfluxDBQueryBuilder:
    """
    Get a new query builder instance.
    
    Returns:
        InfluxDBQueryBuilder instance
    """
    return InfluxDBQueryBuilder()


def get_time_formatter() -> TimeFormatter:
    """
    Get a new time formatter instance.
    
    Returns:
        TimeFormatter instance
    """
    return TimeFormatter()


@contextmanager
def influxdb_connection(logger_instance: Optional[logging.Logger] = None):
    """
    Context manager for InfluxDB connections.
    
    Args:
        logger_instance: Optional logger instance
        
    Yields:
        InfluxDBClient: Connected client instance
        
    Example:
        with influxdb_connection() as client:
            if client.is_enabled():
                results = client.query("SELECT * FROM devices")
    """
    client = create_influxdb_client(logger_instance)
    try:
        yield client
    finally:
        # Client cleanup is handled internally
        pass