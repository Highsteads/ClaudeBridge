"""
Time formatting utilities for InfluxDB data.
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional
from zoneinfo import ZoneInfo


class TimeFormatter:
    """Utility class for formatting and working with time data from InfluxDB."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize time formatter.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger("Plugin")
    
    def convert_to_local_timezone(self, datetime_str: str) -> datetime:
        """
        Convert an ISO formatted UTC datetime string to local timezone.
        
        Args:
            datetime_str: Datetime string in ISO format (ending with 'Z')
            
        Returns:
            Local timezone-aware datetime object
        """
        try:
            # Handle both 'Z' suffix and without
            if datetime_str.endswith('Z'):
                datetime_str = datetime_str.rstrip('Z')
            
            # Parse the datetime and set UTC timezone
            utc_datetime = datetime.fromisoformat(datetime_str).replace(tzinfo=ZoneInfo("UTC"))
            
            # Convert to local timezone
            local_datetime = utc_datetime.astimezone()
            
            return local_datetime
            
        except ValueError as e:
            self.logger.error(f"Failed to parse datetime string '{datetime_str}': {e}")
            # Return current time as fallback
            return datetime.now().astimezone()
    
    def get_delta_summary(self, start_time: datetime, end_time: datetime) -> Tuple[int, int, int]:
        """
        Calculate the difference between two datetime objects.
        
        Args:
            start_time: The start time
            end_time: The end time
            
        Returns:
            Tuple of (hours, minutes, seconds)
        """
        try:
            delta = end_time - start_time
            
            # Handle negative deltas
            if delta.total_seconds() < 0:
                self.logger.warning(f"Negative time delta: {start_time} to {end_time}")
                return (0, 0, 0)
            
            total_seconds = int(delta.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            return (hours, minutes, seconds)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate time delta: {e}")
            return (0, 0, 0)
    
    def format_duration(self, hours: int, minutes: int, seconds: int) -> str:
        """
        Format duration components into a human-readable string.
        
        Args:
            hours: Number of hours
            minutes: Number of minutes
            seconds: Number of seconds
            
        Returns:
            Formatted duration string
        """
        parts = []
        
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        if seconds > 0 or not parts:  # Always show seconds if nothing else
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        else:
            return f"{', '.join(parts[:-1])}, and {parts[-1]}"
    
    def format_device_state_message(
        self,
        device_name: str,
        state: str,
        start_time: datetime,
        end_time: datetime,
        property_name: str = None
    ) -> str:
        """
        Format a device state change message with duration.
        
        Args:
            device_name: Name of the device
            state: Device state (e.g., "on", "off")
            start_time: When the state started
            end_time: When the state ended
            property_name: Optional property name for context
            
        Returns:
            Formatted message string
        """
        try:
            hours, minutes, seconds = self.get_delta_summary(start_time, end_time)
            duration = self.format_duration(hours, minutes, seconds)
            
            # Format timestamps for display with timezone abbreviation
            # Use timezone abbreviation if available, otherwise offset
            start_str = self._format_timestamp_with_tz(start_time)
            end_str = self._format_timestamp_with_tz(end_time)
            
            # Include property name if provided
            if property_name:
                device_label = f"{device_name}.{property_name}"
            else:
                device_label = device_name
            
            message = (
                f"{device_label} was {state} for {duration}, "
                f"from {start_str} to {end_str}"
            )
            
            return message
            
        except Exception as e:
            self.logger.error(f"Failed to format device state message: {e}")
            return f"{device_name} state change (formatting error)"
    
    def _format_timestamp_with_tz(self, timestamp: datetime) -> str:
        """
        Format timestamp with proper timezone display.
        
        Args:
            timestamp: Datetime object to format
            
        Returns:
            Formatted timestamp string with timezone
        """
        try:
            # Try to get timezone abbreviation (e.g., EST, PST)
            tz_name = timestamp.strftime("%Z")
            if tz_name and tz_name not in ['UTC', '']:
                # Use abbreviation if available
                return timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
            else:
                # Fall back to offset format
                return timestamp.strftime("%Y-%m-%d %H:%M:%S %z")
        except Exception:
            # Ultimate fallback
            return str(timestamp)
    
    def get_time_range_for_period(self, days: int) -> Tuple[datetime, datetime]:
        """
        Get start and end times for a period going back N days.
        
        Args:
            days: Number of days to go back
            
        Returns:
            Tuple of (start_time, end_time) in local timezone
        """
        try:
            end_time = datetime.now().astimezone()
            start_time = end_time - timedelta(days=days)
            
            return (start_time, end_time)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate time range: {e}")
            # Return a safe default of last 24 hours
            end_time = datetime.now().astimezone()
            start_time = end_time - timedelta(days=1)
            return (start_time, end_time)
    
    def format_timestamp_for_display(self, timestamp: datetime) -> str:
        """
        Format a timestamp for user display.
        
        Args:
            timestamp: Datetime object to format
            
        Returns:
            Formatted timestamp string
        """
        try:
            return timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            self.logger.error(f"Failed to format timestamp: {e}")
            return str(timestamp)
    
    def parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """
        Parse relative time strings like "1 hour ago", "2 days ago".
        
        Args:
            time_str: Relative time string
            
        Returns:
            Datetime object or None if parsing fails
        """
        try:
            time_str = time_str.lower().strip()
            now = datetime.now().astimezone()
            
            if "hour" in time_str:
                if time_str.startswith("1 hour"):
                    return now - timedelta(hours=1)
                elif time_str.startswith("2 hour"):
                    return now - timedelta(hours=2)
                # Add more patterns as needed
            
            elif "day" in time_str:
                if time_str.startswith("1 day"):
                    return now - timedelta(days=1)
                elif time_str.startswith("2 day"):
                    return now - timedelta(days=2)
                elif time_str.startswith("7 day") or "week" in time_str:
                    return now - timedelta(days=7)
                # Add more patterns as needed
            
            elif "minute" in time_str:
                if time_str.startswith("30 minute"):
                    return now - timedelta(minutes=30)
                elif time_str.startswith("15 minute"):
                    return now - timedelta(minutes=15)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to parse relative time '{time_str}': {e}")
            return None