"""
Base handler class for MCP server tools with standardized logging and common functionality.
"""

import logging
import re
import sqlite3
from typing import Optional


class CallerError(ValueError):
    """A request that cannot be carried out as asked (an ambiguous name, an
    argument out of range). handle_exception reports it to the caller and logs
    a WARNING, not an ERROR: nothing is wrong with the plugin."""


# The whole message Indigo 2025.2 gave, and nothing wider (measured 19-11-2026).
_NOT_ENABLED = re.compile(r"interface (.+?) is not enabled\.?", re.I)

# DB-API 2.0 drivers name a class InterfaceError too: sqlite3.InterfaceError is
# one, and the SQL Logger's PostgreSQL driver has its own. A class from one of
# these modules is a database fault, never Indigo refusing a command.
_DB_MODULES = frozenset({"sqlite3", "_sqlite3", "postgresql", "psycopg", "psycopg2",
                         "pg8000", "asyncpg", "pymysql", "MySQLdb", "mysql"})


def _from_a_database(e: Exception) -> bool:
    if isinstance(e, sqlite3.Error):
        return True
    return any(set((cls.__module__ or "").split(".")) & _DB_MODULES
               for cls in type(e).__mro__)


def interface_refusal(e: Exception, sent_nothing: bool = False) -> Optional[dict]:
    """Plain words for Indigo refusing a command because an interface is
    turned off, or None for anything else.

    Measured on Indigo 2025.2 (19-11-2026): with Interfaces > Z-Wave turned
    off, sendRaw (device= form), sendConfigParm (nodeId= form),
    exitInclusionExclusionMode and stopNetworkOptimize each raised
    InterfaceError "interface Z-Wave is not enabled" within a millisecond, and
    sent and logged nothing. That is the house's state, not a fault in the
    plugin, so it is a refusal (a WARNING), never a red Error.

    Only that measured case is a refusal: the class must be named
    InterfaceError somewhere in its MRO (the record names the class only, and
    Indigo offers it as indigo.PluginBase.InterfaceError, which this module
    does not import), must not come from a database driver, and its message
    must be "interface <name> is not enabled" and nothing else. Every other
    InterfaceError stays an Error.

    sent_nothing: the caller's command is one of those measured to send
    nothing; only then does the reply say "Nothing was sent". For any other
    command (a ping, starting a heal, entering inclusion or exclusion) Indigo
    refusing it is fact, and whether it sent nothing is not measured."""
    if not any(cls.__name__ == "InterfaceError" for cls in type(e).__mro__):
        return None
    if _from_a_database(e):
        return None
    said = str(e).strip()
    match = _NOT_ENABLED.fullmatch(said)
    if not match:
        return None
    name = match.group(1).strip()
    what = (f"Nothing was sent: {name} is turned off in Indigo." if sent_nothing
            else f"{name} is turned off in Indigo.")
    return {
        "success": False,
        "refused": "interface_not_enabled",
        "interface": name,
        "indigo_error": f"InterfaceError: {said}",
        "error": (f"Indigo refused it ({said}). {what} Interfaces > {name} > Enable in "
                  f"the Indigo client turns it back on, but leave it off if it was turned "
                  f"off on purpose, for example while a controller backup runs."),
    }


class BaseToolHandler:
    """Base class for all MCP tool handlers with standardized logging."""

    # handle_exception contexts whose Indigo call was measured to send nothing
    # when its interface is turned off (see interface_refusal). Empty here; a
    # handler names its own measured methods.
    SENT_NOTHING_MEASURED: frozenset = frozenset()

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
        if logger is not None:
            self.logger = logger
        else:
            # Fall back to the shared 'Plugin' logger, but make the missing
            # wiring visible — a handler built without the plugin's configured
            # logger won't carry its timestamp/format filter.
            self.logger = logging.getLogger("Plugin")
            self.logger.warning(
                f"[{tool_name}] constructed without a logger — using the shared "
                f"'Plugin' logger (timestamp formatting may differ)"
            )
    
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
        refusal = interface_refusal(e, sent_nothing=context in self.SENT_NOTHING_MEASURED)
        if refusal is not None:
            where = f"{self.tool_name} ({context})" if context else self.tool_name
            self.logger.warning(f"[{where}]: {refusal['error']}")
            return {**refusal, "tool": self.tool_name, "context": context}

        error_message = f"Error in {self.tool_name}"
        if context:
            error_message += f" ({context})"
        error_message += f": {str(e)}"

        if isinstance(e, CallerError):
            self.warning_log(error_message)
        else:
            self.error_log(error_message)
        
        return {
            "error": str(e),
            "tool": self.tool_name,
            "context": context,
            "success": False
        }
    
    def log_incoming_request(self, operation: str, params: dict = None) -> None:
        """
        Log an incoming tool request (concise).

        Args:
            operation: The operation being performed
            params: Optional parameters for the request (not logged for brevity)
        """
        # Concise logging - parameters will be shown in outcome if needed
        pass
    
    def log_tool_outcome(self, operation: str, success: bool, details: str = "", count: int = None,
                         query_info: dict = None, level: Optional[int] = None) -> None:
        """
        Log the outcome of a tool operation with enhanced context and emojis.

        Levels (3.0.2), following the house rule that INFO says what changed
        and an Error means something is wrong with the plugin:
          * success -> DEBUG. A read changed nothing, and a command's effect is
            logged by Indigo itself ("sent ... on").
          * failure -> WARNING. Most failures are a caller asking for something
            that cannot be done (unknown id, bad argument). They used to be red
            Errors, and Log_Error_Watch triaged 32 of them as faults.
          * `level` overrides both, e.g. DEBUG for a caller's own code raising
            inside execute_indigo_python. Genuine faults still reach ERROR
            through handle_exception().

        Args:
            operation: The operation that was performed
            success: Whether the operation succeeded
            details: Optional additional details about the outcome
            count: Optional count of items returned/affected
            query_info: Optional dictionary with query context (filters, types, etc.)
            level: Optional logging level to use instead of the default
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
        
        if level is None:
            level = logging.DEBUG if success else logging.WARNING
        self.logger.log(level, f"[{self.tool_name}]: {message}")
    
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
