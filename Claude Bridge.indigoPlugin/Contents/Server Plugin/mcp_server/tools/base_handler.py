"""
Base handler class for MCP server tools with standardized logging and common functionality.
"""

import inspect
import logging
from typing import Optional, Any


class BaseToolHandler:
    """Base class for all MCP tool handlers with standardized logging."""
    
    def __init__(
        self,
        tool_name: str,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the base tool handler.
        
        Args:
            tool_name: Name of the tool (used for logging)
            logger: Optional logger instance
        """
        self.tool_name = tool_name
        self.logger = logger or logging.getLogger("Plugin")
    
    def info_log(self, message: str) -> None:
        """
        Log an info message with standardized format.
        
        Args:
            message: The message to log
        """
        self.logger.info(f"[{self.tool_name}]: {message}")
    
    def debug_log(self, message: str) -> None:
        """
        Log a debug message with standardized format.

        Args:
            message: The message to log
        """
        self.logger.debug(f"[{self.tool_name}]: {message}")
    
    def warning_log(self, message: str) -> None:
        """
        Log a warning message with standardized format.
        
        Args:
            message: The message to log
        """
        self.logger.warning(f"[{self.tool_name}]: {message}")
    
    def error_log(self, message: str) -> None:
        """
        Log an error message with standardized format.
        
        Args:
            message: The message to log
        """
        self.logger.error(f"[{self.tool_name}]: {message}")
    
    def handle_exception(self, e: Exception, context: str = "") -> dict:
        """
        Handle exceptions with standardized error reporting.
        
        Args:
            e: The exception that occurred
            context: Additional context about when the error occurred
            
        Returns:
            Dictionary with error information
        """
        error_message = f"Error in {self.tool_name}"
        if context:
            error_message += f" ({context})"
        error_message += f": {str(e)}"
        
        self.error_log(error_message)
        
        return {
            "error": str(e),
            "tool": self.tool_name,
            "context": context,
            "success": False
        }
    
    def create_success_response(self, data: Any, message: str = "") -> dict:
        """
        Create a standardized success response.
        
        Args:
            data: The data to include in the response
            message: Optional success message
            
        Returns:
            Dictionary with success response
        """
        response = {
            "success": True,
            "tool": self.tool_name,
            "data": data
        }
        
        if message:
            response["message"] = message
            self.info_log(message)
        
        return response
    
    def validate_required_params(self, params: dict, required_keys: list) -> Optional[dict]:
        """
        Validate that required parameters are present.
        
        Args:
            params: Dictionary of parameters to validate
            required_keys: List of required parameter keys
            
        Returns:
            None if valid, error dictionary if invalid
        """
        missing_keys = [key for key in required_keys if key not in params or params[key] is None]
        
        if missing_keys:
            error_msg = f"Missing required parameters: {', '.join(missing_keys)}"
            self.error_log(error_msg)
            return {
                "error": error_msg,
                "tool": self.tool_name,
                "missing_parameters": missing_keys,
                "success": False
            }
        
        return None
    
    def log_incoming_request(self, operation: str, params: dict = None) -> None:
        """
        Log an incoming tool request (concise).

        Args:
            operation: The operation being performed
            params: Optional parameters for the request (not logged for brevity)
        """
        # Concise logging - parameters will be shown in outcome if needed
        pass
    
    def log_tool_outcome(self, operation: str, success: bool, details: str = "", count: int = None, query_info: dict = None) -> None:
        """
        Log the outcome of a tool operation with enhanced context and emojis.
        
        Args:
            operation: The operation that was performed
            success: Whether the operation succeeded
            details: Optional additional details about the outcome
            count: Optional count of items returned/affected
            query_info: Optional dictionary with query context (filters, types, etc.)
        """
        status = "completed successfully" if success else "failed"
        
        # Add emoji based on operation type
        emoji = self._get_operation_emoji(operation)
        message = f"{operation} {status}"
        
        if count is not None:
            message += f" - {count} item{'s' if count != 1 else ''}"
        
        # Add query specifics if provided
        if query_info:
            query_details = self._format_query_info(query_info)
            if query_details:
                message += f" ({query_details})"
        
        if details:
            message += f" - {details}"
        
        # Add emoji at the end for visual appeal
        if emoji:
            message = f"{emoji} {message}"
        
        if success:
            self.info_log(message)
        else:
            self.error_log(message)
    
    def _get_operation_emoji(self, operation: str) -> str:
        """
        Get an appropriate emoji for the operation type.
        
        Args:
            operation: The operation name
            
        Returns:
            Emoji string or empty string if no match
        """
        emoji_map = {
            # Device operations
            "list_devices": "💡",
            "turn_on": "🟢", 
            "turn_off": "🔴",
            "set_brightness": "🔆",
            
            # Variable operations  
            "list_variables": "📊",
            "update": "📝",
            
            # Action operations
            "list_action_groups": "🎬",
            "execute": "▶️",
            
            # Search operations
            "search": "🔍",
            "search_devices": "🔍",
            "search_variables": "🔍", 
            "search_actions": "🔍",
        }
        
        return emoji_map.get(operation, "")
    
    def _format_query_info(self, query_info: dict) -> str:
        """
        Format query information for logging with appropriate emojis.
        
        Args:
            query_info: Dictionary containing query context
            
        Returns:
            Formatted string with query details
        """
        if not query_info:
            return ""
        
        parts = []
        
        # Handle state filters
        if "state_filter" in query_info and query_info["state_filter"]:
            state_filter = query_info["state_filter"]
            if isinstance(state_filter, dict):
                state_parts = []
                for key, value in state_filter.items():
                    if key == "onState":
                        emoji = "🟢" if value else "🔴"
                        state_parts.append(f"{emoji} {key}={value}")
                    elif "brightness" in key.lower():
                        state_parts.append(f"🔆 {key}={value}")
                    elif "temperature" in key.lower():
                        state_parts.append(f"🌡️ {key}={value}")
                    else:
                        state_parts.append(f"{key}={value}")
                
                if state_parts:
                    parts.append(f"states: {', '.join(state_parts)}")
        
        # Handle device types
        if "device_types" in query_info and query_info["device_types"]:
            device_types = query_info["device_types"]
            type_parts = []
            
            for device_type in device_types:
                emoji = self._get_device_type_emoji(device_type)
                if emoji:
                    type_parts.append(f"{emoji} {device_type}")
                else:
                    type_parts.append(device_type)
            
            if type_parts:
                parts.append(f"types: {', '.join(type_parts)}")
        
        # Handle search query
        if "search_query" in query_info and query_info["search_query"]:
            parts.append(f"query: '{query_info['search_query']}'")
        
        return ", ".join(parts)
    
    def _get_device_type_emoji(self, device_type: str) -> str:
        """
        Get an emoji for a device type.
        
        Args:
            device_type: The device type name
            
        Returns:
            Emoji string or empty string if no match
        """
        type_emoji_map = {
            "dimmer": "💡",
            "relay": "🔌", 
            "sensor": "📡",
            "thermostat": "🌡️",
            "sprinkler": "💧",
            "io": "🔗",
            "multiio": "🔗",
            "speedcontrol": "⚙️",
            "device": "📱",
        }
        
        return type_emoji_map.get(device_type, "")