"""
InfluxDB query builder and utilities.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union
from .time_utils import TimeFormatter


class InfluxDBQueryBuilder:
    """Builder for InfluxDB queries with support for common patterns."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize query builder.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger("Plugin")
        self.time_formatter = TimeFormatter()
    
    def build_device_history_query(
        self,
        device_name: str,
        device_property: str,
        time_range_days: int = 60,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query for device historical data.
        
        Args:
            device_name: Name of the device
            device_property: Property to query (e.g., "onState", "brightness")
            time_range_days: Number of days to look back
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        # Calculate time range
        now = datetime.now()
        start_time = now - timedelta(days=time_range_days)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        # Build query with proper escaping
        query = (
            f'SELECT "{device_property}" FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}' "
            f"AND time >= {start_time_ms}ms "
            f'GROUP BY "name" '
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built device history query: {query}")
        return query
    
    def build_device_latest_query(
        self,
        device_name: str,
        device_property: str,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query for the latest device state.
        
        Args:
            device_name: Name of the device
            device_property: Property to query
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        query = (
            f'SELECT LAST("{device_property}") FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}' "
            f'GROUP BY "name"'
        )
        
        self.logger.debug(f"Built latest device query: {query}")
        return query
    
    def build_devices_summary_query(
        self,
        device_names: List[str],
        time_range_hours: int = 24,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query for multiple devices summary.
        
        Args:
            device_names: List of device names
            time_range_hours: Number of hours to look back
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        # Calculate time range
        now = datetime.now()
        start_time = now - timedelta(hours=time_range_hours)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        # Build device name filter
        device_filter = " OR ".join([f"\"name\" = '{name}'" for name in device_names])
        
        query = (
            f'SELECT * FROM "{measurement}" '
            f"WHERE ({device_filter}) "
            f"AND time >= {start_time_ms}ms "
            f'GROUP BY "name" '
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built devices summary query: {query}")
        return query
    
    def build_aggregation_query(
        self,
        device_name: str,
        device_property: str,
        aggregation: str,
        time_range_days: int = 7,
        group_by_time: str = "1d",
        measurement: str = "device_changes"
    ) -> str:
        """
        Build an aggregation query for device data.
        
        Args:
            device_name: Name of the device
            device_property: Property to aggregate
            aggregation: Aggregation function (MEAN, SUM, COUNT, etc.)
            time_range_days: Number of days to look back
            group_by_time: Time grouping interval (1h, 1d, etc.)
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        # Calculate time range
        now = datetime.now()
        start_time = now - timedelta(days=time_range_days)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        query = (
            f'SELECT {aggregation}("{device_property}") FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}' "
            f"AND time >= {start_time_ms}ms "
            f"GROUP BY time({group_by_time}), \"name\" "
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built aggregation query: {query}")
        return query
    
    def build_pattern_detection_query(
        self,
        device_name: str,
        device_property: str,
        pattern_value: Union[str, int, float],
        time_range_days: int = 30,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query to detect patterns in device behavior.
        
        Args:
            device_name: Name of the device
            device_property: Property to analyze
            pattern_value: Value to detect patterns for
            time_range_days: Number of days to analyze
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        # Calculate time range
        now = datetime.now()
        start_time = now - timedelta(days=time_range_days)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        # Handle string vs numeric values
        if isinstance(pattern_value, str):
            value_condition = f'"{device_property}" = \'{pattern_value}\''
        else:
            value_condition = f'"{device_property}" = {pattern_value}'
        
        query = (
            f'SELECT * FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}' "
            f"AND {value_condition} "
            f"AND time >= {start_time_ms}ms "
            f'GROUP BY "name" '
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built pattern detection query: {query}")
        return query
    
    def build_time_range_query(
        self,
        device_name: str,
        device_property: str,
        start_time: datetime,
        end_time: datetime,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query for a specific time range.
        
        Args:
            device_name: Name of the device
            device_property: Property to query
            start_time: Start of time range
            end_time: End of time range
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)
        
        query = (
            f'SELECT "{device_property}" FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}' "
            f"AND time >= {start_time_ms}ms "
            f"AND time <= {end_time_ms}ms "
            f'GROUP BY "name" '
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built time range query: {query}")
        return query
    
    def get_available_properties_query(
        self,
        device_name: str,
        measurement: str = "device_changes"
    ) -> str:
        """
        Build a query to discover available properties for a device.
        
        Args:
            device_name: Name of the device
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        query = (
            f'SHOW FIELD KEYS FROM "{measurement}" '
            f"WHERE \"name\" = '{device_name}'"
        )
        
        self.logger.debug(f"Built properties discovery query: {query}")
        return query
    
    def build_variable_history_query(
        self,
        variable_name: str,
        time_range_days: int = 60,
        measurement: str = "variable_changes"
    ) -> str:
        """
        Build a query for variable historical data.
        
        Args:
            variable_name: Name of the variable
            time_range_days: Number of days to look back
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        # Calculate time range
        now = datetime.now()
        start_time = now - timedelta(days=time_range_days)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        # Build query for variable changes (uses 'value' field and 'varname' tag)
        query = (
            f'SELECT "value" FROM "{measurement}" '
            f"WHERE \"varname\" = '{variable_name}' "
            f"AND time >= {start_time_ms}ms "
            f'GROUP BY "varname" '
            f"ORDER BY time ASC"
        )
        
        self.logger.debug(f"Built variable history query: {query}")
        return query
    
    def build_variable_latest_query(
        self,
        variable_name: str,
        measurement: str = "variable_changes"
    ) -> str:
        """
        Build a query for the latest variable value.
        
        Args:
            variable_name: Name of the variable
            measurement: InfluxDB measurement name
            
        Returns:
            InfluxQL query string
        """
        query = (
            f'SELECT LAST("value") FROM "{measurement}" '
            f"WHERE \"varname\" = '{variable_name}' "
            f'GROUP BY "varname"'
        )
        
        self.logger.debug(f"Built latest variable query: {query}")
        return query