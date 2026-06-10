"""
InfluxDB client management for MCP server.
"""

import logging
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from influxdb import InfluxDBClient as InfluxClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError


class InfluxDBClient:
    """Wrapper for InfluxDB client with environment-based configuration."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize InfluxDB client wrapper.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger("Plugin")
        self._client = None
    
    def is_enabled(self) -> bool:
        """
        Check if InfluxDB is enabled via the runtime config store.

        (Moved off os.environ in v2.4.1 — see mcp_server/runtime_config.py
        for the secrets-policy reasoning.)

        Returns:
            True if InfluxDB is enabled and configured
        """
        from mcp_server import runtime_config
        return runtime_config.is_influx_enabled()

    def get_connection_info(self) -> Dict[str, str]:
        """
        Get InfluxDB connection information from the runtime config store.

        Returns:
            Dictionary with connection parameters
        """
        from mcp_server import runtime_config
        try:
            port = int(runtime_config.get("influxdb_port") or 8086)
        except (ValueError, TypeError):
            self.logger.warning(
                "Invalid influxdb_port in runtime config; falling back to 8086"
            )
            port = 8086
        return {
            "host":     runtime_config.get("influxdb_host"),
            "port":     port,
            "username": runtime_config.get("influxdb_username"),
            "password": runtime_config.get("influxdb_password"),
            "database": runtime_config.get("influxdb_database"),
        }
    
    @contextmanager
    def get_client(self):
        """
        Context manager for InfluxDB client connections.
        
        Yields:
            InfluxDBClient instance
            
        Raises:
            RuntimeError: If InfluxDB is not enabled or connection fails
        """
        if not self.is_enabled():
            raise RuntimeError("InfluxDB is not enabled")
        
        client = None
        try:
            conn_info = self.get_connection_info()

            if not conn_info["host"]:
                raise RuntimeError("InfluxDB host is not configured")

            client = InfluxClient(
                host=conn_info["host"],
                port=conn_info["port"],
                username=conn_info["username"] if conn_info["username"] else None,
                password=conn_info["password"] if conn_info["password"] else None,
                database=conn_info["database"],
                timeout=30
            )
            
            # Test connection
            if not client.ping():
                raise RuntimeError("InfluxDB ping failed")
            
            yield client
            
        except Exception as e:
            self.logger.error(f"InfluxDB connection error: {e}")
            raise
        finally:
            if client:
                try:
                    client.close()
                except Exception as e:
                    self.logger.warning(f"Error closing InfluxDB connection: {e}")
    
    def test_connection(self) -> bool:
        """
        Test InfluxDB connection.
        
        Returns:
            True if connection is successful
        """
        if not self.is_enabled():
            return False
        
        try:
            with self.get_client() as client:
                # Try to list databases as an additional test
                client.get_list_database()
                return True
        except Exception as e:
            self.logger.error(f"InfluxDB connection test failed: {e}")
            return False
    
    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute a query against InfluxDB.
        
        Args:
            query: InfluxQL query string
            
        Returns:
            List of result dictionaries
            
        Raises:
            RuntimeError: If InfluxDB is not enabled or query fails
        """
        if not self.is_enabled():
            raise RuntimeError("InfluxDB is not enabled")
        
        try:
            with self.get_client() as client:
                result = client.query(query)
                
                # Convert result to list of dictionaries
                formatted_results = []
                for point in result.get_points():
                    formatted_results.append(dict(point))
                
                return formatted_results
                
        except (InfluxDBClientError, InfluxDBServerError) as e:
            self.logger.error(f"InfluxDB query error: {e}")
            raise RuntimeError(f"InfluxDB query failed: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error executing InfluxDB query: {e}")
            raise RuntimeError(f"Query execution failed: {e}")
    
    def get_database_list(self) -> List[str]:
        """
        Get list of available databases.
        
        Returns:
            List of database names
        """
        if not self.is_enabled():
            return []
        
        try:
            with self.get_client() as client:
                databases = client.get_list_database()
                return [db['name'] for db in databases]
        except Exception as e:
            self.logger.error(f"Failed to get database list: {e}")
            return []
    
    def get_measurement_list(self) -> List[str]:
        """
        Get list of available measurements in the configured database.
        
        Returns:
            List of measurement names
        """
        if not self.is_enabled():
            return []
        
        try:
            with self.get_client() as client:
                measurements = client.get_list_measurements()
                return [m['name'] for m in measurements]
        except Exception as e:
            self.logger.error(f"Failed to get measurement list: {e}")
            return []