"""
MCP Handler for Indigo IWS integration.
Implements standards-compliant MCP protocol over Indigo's built-in web server.
"""

import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Union

from .adapters.data_provider import DataProvider
from .common.indigo_device_types import IndigoDeviceType, IndigoEntityType, DeviceTypeResolver
from .common.json_encoder import safe_json_dumps
from .common.vector_store.vector_store_manager import VectorStoreManager
from .handlers.list_handlers import ListHandlers
from .tools.action_control import ActionControlHandler
from .tools.device_control import DeviceControlHandler
from .tools.get_devices_by_type import GetDevicesByTypeHandler
from .tools.historical_analysis import HistoricalAnalysisHandler
from .tools.log_query import LogQueryHandler
from .tools.plugin_control import PluginControlHandler
from .tools.search_entities import SearchEntitiesHandler
from .tools.variable_control import VariableControlHandler


class MCPHandler:
    """Handles MCP protocol requests through Indigo IWS."""
    
    # MCP Protocol version we support
    PROTOCOL_VERSION = "2025-06-18"
    
    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the MCP handler.
        
        Args:
            data_provider: Data provider for accessing entity data
            logger: Optional logger instance
        """
        self.data_provider = data_provider
        self.logger = logger or logging.getLogger("Plugin")

        # Session management
        self._sessions = {}  # session_id -> {created, last_seen, client_info}

        # Get database path from environment variable
        db_path = os.environ.get("DB_FILE")
        if not db_path:
            raise ValueError("DB_FILE environment variable must be set")

        # Initialize vector store manager
        self.vector_store_manager = VectorStoreManager(
            data_provider=data_provider,
            db_path=db_path,
            logger=self.logger,
            update_interval=300,  # 5 minutes
        )

        # Start vector store manager (it will log its own progress)
        self.vector_store_manager.start()

        # Initialize handlers
        self._init_handlers()

        # Register tools and resources
        self._tools = {}
        self._resources = {}
        self._register_tools()
        self._register_resources()

        self.logger.info(f"\t🚀 Claude Bridge ready ({len(self._tools)} tools, {len(self._resources)} resources)")
        self.logger.info(f"\t🌐 Endpoint: /message/com.clives.indigoplugin.claudebridge/mcp/")
        
    def _init_handlers(self):
        """Initialize all handler instances."""
        # Search handler with vector store
        self.search_handler = SearchEntitiesHandler(
            data_provider=self.data_provider,
            vector_store=self.vector_store_manager.get_vector_store(),
            logger=self.logger,
        )
        
        # Get devices by type handler
        self.get_devices_by_type_handler = GetDevicesByTypeHandler(
            data_provider=self.data_provider, 
            logger=self.logger
        )
        
        # List handlers for shared logic
        self.list_handlers = ListHandlers(
            data_provider=self.data_provider, 
            logger=self.logger
        )
        
        # Control handlers
        self.device_control_handler = DeviceControlHandler(
            data_provider=self.data_provider, 
            logger=self.logger
        )
        self.variable_control_handler = VariableControlHandler(
            data_provider=self.data_provider, 
            logger=self.logger
        )
        self.action_control_handler = ActionControlHandler(
            data_provider=self.data_provider, 
            logger=self.logger
        )
        self.historical_analysis_handler = HistoricalAnalysisHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.log_query_handler = LogQueryHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.plugin_control_handler = PluginControlHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
    
    def stop(self):
        """Stop the MCP handler and cleanup resources."""
        if self.vector_store_manager:
            self.vector_store_manager.stop()
    
    def handle_request(
        self,
        method: str,
        headers: Dict[str, str],
        body: str
    ) -> Dict[str, Any]:
        """
        Handle an MCP request from Indigo IWS.

        Args:
            method: HTTP method (GET, POST, etc.)
            headers: Request headers
            body: Request body as string

        Returns:
            Dict with status, headers, and content for IWS response
        """
        # Normalize headers to lowercase
        headers = {k.lower(): v for k, v in headers.items()}
        accept = headers.get("accept", "")
        
        # Only support POST
        if method != "POST":
            return {
                "status": 405,
                "headers": {"Allow": "POST"},
                "content": ""
            }

        # Check Accept header - client must accept json or event-stream
        if "application/json" not in accept and "text/event-stream" not in accept:
            self.logger.debug(f"Invalid Accept header: '{accept}'")
            return {"status": 406, "content": "Not Acceptable"}

        # Parse JSON body
        try:
            payload = json.loads(body) if body else None
        except Exception as e:
            self.logger.error(f"Failed to parse JSON body: {e}")
            return self._json_response(
                self._json_error(None, -32700, "Parse error"),
                status=200
            )

        # Handle empty or invalid payload
        if not payload:
            return self._json_response(
                self._json_error(None, -32600, "Invalid Request"),
                status=200
            )

        # MCP 2025-06-18 spec removes support for JSON-RPC batching
        if isinstance(payload, list):
            self.logger.debug("Batch requests not supported")
            return self._json_response(
                self._json_error(None, -32600, "Batch requests not supported"),
                status=200
            )
        
        # Process single message
        try:
            # Single message
            resp = self._dispatch_message(payload, headers)
            
            # If it was a notification (no id), return 200 with empty JSON for IWS compatibility
            if isinstance(payload, dict) and "id" not in payload:
                return {
                    "status": 200, 
                    "headers": {"Content-Type": "application/json; charset=utf-8"},
                    "content": "{}"
                }
            
            # Check for session ID in response
            extra_headers = {}
            if isinstance(resp, dict) and "_mcp_session_id" in resp:
                session_id = resp.pop("_mcp_session_id")
                extra_headers["Mcp-Session-Id"] = session_id
            
            return {
                "status": 200,
                "headers": {
                    "Content-Type": "application/json; charset=utf-8",
                    **extra_headers
                },
                "content": json.dumps(resp)
            }
                
        except Exception as e:
            self.logger.exception("Unhandled MCP error")
            return self._json_response(
                self._json_error(None, -32603, "Internal error"),
                status=200
            )
    
    def _dispatch_message(
        self,
        msg: Dict[str, Any],
        headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """
        Dispatch a single JSON-RPC message.

        Args:
            msg: JSON-RPC message
            headers: Request headers

        Returns:
            JSON-RPC response or None for notifications
        """
        # Validate JSON-RPC structure
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            self.logger.debug(f"Invalid JSON-RPC message structure")
            return self._json_error(msg.get("id"), -32600, "Invalid Request")

        msg_id = msg.get("id")  # May be None for notifications
        method = msg["method"]
        params = msg.get("params") or {}

        # Log incoming request at INFO level (concise)
        session_id = headers.get("mcp-session-id", "")
        session_short = session_id[:8] if session_id else "none"

        # Format method for logging
        if method.startswith("notifications/"):
            log_method = method.replace("notifications/", "notify:")
        elif "/" in method:
            log_method = method.replace("/", ":")
        else:
            log_method = method

        self.logger.info(f"📨 {log_method} | session: {session_short}")
        
        # MCP 2025-06-18 requires MCP-Protocol-Version header for HTTP transport
        protocol_version_header = headers.get("mcp-protocol-version")
        if method != "initialize" and not method.startswith("notifications/") and self._sessions:
            if protocol_version_header and protocol_version_header != self.PROTOCOL_VERSION:
                self.logger.debug(f"Invalid protocol version: {protocol_version_header}")
                return self._json_error(msg_id, -32600, f"Unsupported protocol version: {protocol_version_header}")

        # Session validation (skip for initialize and notifications)
        session_id = headers.get("mcp-session-id")
        if method != "initialize" and not method.startswith("notifications/") and self._sessions:
            if not session_id or session_id not in self._sessions:
                self.logger.debug(f"Invalid session ID for {method}")
                return self._json_error(msg_id, -32600, "Missing or invalid Mcp-Session-Id")
            # Update last seen
            self._sessions[session_id]["last_seen"] = time.time()

        # Route to appropriate handler
        if method == "initialize":
            return self._handle_initialize(msg_id, params)
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        elif method == "notifications/cancelled":
            self._handle_cancelled(params)
            return None
        elif method == "notifications/initialized":
            return None
        
        # Tool methods
        elif method == "tools/list":
            return self._handle_tools_list(msg_id, params)
        elif method == "tools/call":
            return self._handle_tools_call(msg_id, params)
        
        # Resource methods
        elif method == "resources/list":
            return self._handle_resources_list(msg_id, params)
        elif method == "resources/read":
            return self._handle_resources_read(msg_id, params)
        
        # Prompt methods (stubs for now)
        elif method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"prompts": []}
            }
        elif method == "prompts/get":
            return self._json_error(msg_id, -32602, "Unknown prompt")
        
        # Unknown method
        else:
            if method.startswith("notifications/"):
                # Unknown notifications ignored gracefully
                return None
            else:
                self.logger.debug(f"Unknown method: {method}")
                return self._json_error(msg_id, -32601, "Method not found")
    
    def _handle_initialize(
        self,
        msg_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle initialize request."""
        requested_version = str(params.get("protocolVersion") or "")
        client_info = params.get("clientInfo", {})
        client_name = client_info.get("name", "Unknown")

        # Check if we support the requested version
        if requested_version == self.PROTOCOL_VERSION:
            # Create new session
            session_id = secrets.token_urlsafe(24)
            self._sessions[session_id] = {
                "created": time.time(),
                "last_seen": time.time(),
                "client_info": client_info
            }

            result = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {
                        "logging": {},
                        "prompts": {"listChanged": True},
                        "resources": {"subscribe": False, "listChanged": True},
                        "tools": {"listChanged": True}
                    },
                    "serverInfo": {
                        "name": "Indigo Claude Bridge",
                        "version": "2025.0.1"
                    }
                }
            }

            # Add session ID for header
            result["_mcp_session_id"] = session_id

            self.logger.info(f"\t✅ Client initialized: {client_name} | session: {session_id[:8]}")

            return result
        else:
            # Unsupported version
            self.logger.debug(f"Unsupported protocol version: {requested_version}")

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32602,
                    "message": "Unsupported protocol version",
                    "data": {
                        "supported": [self.PROTOCOL_VERSION],
                        "requested": requested_version
                    }
                }
            }
    
    def _handle_cancelled(self, params: Dict[str, Any]):
        """Handle cancellation notification."""
        # In a synchronous implementation, we can't really cancel ongoing work
        # This is for async implementations only
        pass
    
    def _handle_tools_list(
        self, 
        msg_id: Any, 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle tools/list request."""
        # Convert tool functions to tool descriptions
        tools = []
        for name, info in self._tools.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"]
            })
        
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": tools
            }
        }
    
    def _handle_tools_call(
        self, 
        msg_id: Any, 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        
        if tool_name not in self._tools:
            return self._json_error(msg_id, -32602, f"Unknown tool: {tool_name}")
        
        try:
            # Call the tool function
            result = self._tools[tool_name]["function"](**tool_args)
            
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result
                        }
                    ]
                }
            }
        except Exception as e:
            self.logger.error(f"Tool {tool_name} error: {e}")
            return self._json_error(
                msg_id, 
                -32603, 
                f"Tool execution failed: {str(e)}"
            )
    
    def _handle_resources_list(
        self, 
        msg_id: Any, 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle resources/list request."""
        resources = []
        for uri, info in self._resources.items():
            resources.append({
                "uri": uri,
                "name": info["name"],
                "description": info["description"],
                "mimeType": "application/json"
            })
        
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "resources": resources
            }
        }
    
    def _handle_resources_read(
        self, 
        msg_id: Any, 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        
        if not uri:
            return self._json_error(msg_id, -32602, "Missing uri parameter")
        
        # Try exact match first
        if uri in self._resources:
            try:
                content = self._resources[uri]["function"]()
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": content
                            }
                        ]
                    }
                }
            except Exception as e:
                self.logger.error(f"Resource {uri} error: {e}")
                return self._json_error(
                    msg_id, 
                    -32603, 
                    f"Resource read failed: {str(e)}"
                )
        
        # Try pattern matching for parameterized resources
        for pattern, info in self._resources.items():
            if "{" in pattern:  # Has parameters
                # Simple pattern matching (e.g., "indigo://devices/{id}")
                base_pattern = pattern.split("{")[0]
                if uri.startswith(base_pattern):
                    # Extract parameter value
                    param_value = uri[len(base_pattern):]
                    if param_value:
                        try:
                            content = info["function"](param_value)
                            return {
                                "jsonrpc": "2.0",
                                "id": msg_id,
                                "result": {
                                    "contents": [
                                        {
                                            "uri": uri,
                                            "mimeType": "application/json",
                                            "text": content
                                        }
                                    ]
                                }
                            }
                        except Exception as e:
                            self.logger.error(f"Resource {uri} error: {e}")
                            return self._json_error(
                                msg_id, 
                                -32603, 
                                f"Resource read failed: {str(e)}"
                            )
        
        return self._json_error(msg_id, -32002, f"Resource not found: {uri}")
    
    def _register_tools(self):
        """Register all available tools."""
        # Search entities tool
        self._tools["search_entities"] = {
            "description": "Search for Indigo entities using natural language. Results are slim by default (id, name, state, lastChanged). Use detail='full' only when you need complete device properties such as Z-Wave config or plugin props.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query"
                    },
                    "device_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional device types to filter. Valid types: dimmer, relay, sensor, multiio, speedcontrol, sprinkler, thermostat, device. Common aliases supported: light→dimmer, switch→relay, motion→sensor, fan→speedcontrol, etc."
                    },
                    "entity_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional entity types to search"
                    },
                    "state_filter": {
                        "type": "object",
                        "description": "Optional state conditions to filter results"
                    },
                    "detail": {
                        "type": "string",
                        "enum": ["slim", "full"],
                        "description": "Result detail level. 'slim' (default) returns id/name/state/lastChanged only — fast. 'full' returns complete device objects including all plugin and Z-Wave properties."
                    }
                },
                "required": ["query"]
            },
            "function": self._tool_search_entities
        }
        
        # Get devices by type
        self._tools["get_devices_by_type"] = {
            "description": "Get all devices of a specific type",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_type": {
                        "type": "string",
                        "description": "Device type. Valid types: dimmer, relay, sensor, multiio, speedcontrol, sprinkler, thermostat, device. Aliases supported: light→dimmer, switch→relay, motion→sensor, fan→speedcontrol, etc."
                    }
                },
                "required": ["device_type"]
            },
            "function": self._tool_get_devices_by_type
        }
        
        # Device control tools
        self._tools["device_turn_on"] = {
            "description": "Turn on a device",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The ID of the device to turn on"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_device_turn_on
        }
        
        self._tools["device_turn_off"] = {
            "description": "Turn off a device",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The ID of the device to turn off"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_device_turn_off
        }
        
        self._tools["device_set_brightness"] = {
            "description": "Set device brightness level",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The ID of the device"
                    },
                    "brightness": {
                        "type": "number",
                        "description": "Brightness level (0-1 or 0-100)"
                    }
                },
                "required": ["device_id", "brightness"]
            },
            "function": self._tool_device_set_brightness
        }
        
        # Combined find + control tool (single round trip)
        self._tools["device_control"] = {
            "description": "Find a device by name and control it in one step — faster than search_entities + device_turn_on/off. Use this for all simple on/off/brightness commands.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Device name or description (e.g. 'conservatory lamp', 'hall light')"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["turn_on", "turn_off", "toggle", "set_brightness"],
                        "description": "Action to perform"
                    },
                    "brightness": {
                        "type": "number",
                        "description": "Brightness level 0-100 (required only for set_brightness)"
                    }
                },
                "required": ["name", "action"]
            },
            "function": self._tool_device_control
        }

        # Variable control
        self._tools["variable_update"] = {
            "description": "Update a variable's value",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variable_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The ID of the variable"
                    },
                    "value": {
                        "type": "string",
                        "description": "The new value for the variable"
                    }
                },
                "required": ["variable_id", "value"]
            },
            "function": self._tool_variable_update
        }

        # Variable creation
        self._tools["variable_create"] = {
            "description": "Create a new variable",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the variable (required)"
                    },
                    "value": {
                        "type": "string",
                        "description": "Initial value for the variable (optional, defaults to empty string)"
                    },
                    "folder_id": {
                        "type": "number",
                        "description": "Folder ID for organization (optional, defaults to 0 = root)"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_variable_create
        }

        # Action group control
        self._tools["action_execute_group"] = {
            "description": "Execute an action group",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The ID of the action group"
                    },
                    "delay": {
                        "type": "number",
                        "description": "Optional delay in seconds"
                    }
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_action_execute_group
        }
        
        # Historical analysis
        self._tools["analyze_historical_data"] = {
            "description": "Analyze historical data patterns and trends for specific devices using AI-powered insights. IMPORTANT: Requires EXACT device names - use 'search_entities' or 'list_devices' first to find correct device names. Only works if InfluxDB historical data logging is enabled.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query about what you want to analyze (e.g., 'show state changes', 'analyze usage patterns', 'track temperature trends'). This helps the system select the right device properties to analyze."
                    },
                    "device_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "EXACT device names to analyze (case-sensitive). Must match device names exactly as they appear in Indigo. Use 'search_entities' or 'list_devices' first to find correct names. Examples: ['Living Room Lamp', 'Front Door Sensor', 'Master Bedroom Thermostat']"
                    },
                    "time_range_days": {
                        "type": "number",
                        "description": "Number of days to analyze (1-365, default: 30). Larger ranges take longer to process."
                    }
                },
                "required": ["query", "device_names"]
            },
            "function": self._tool_analyze_historical_data
        }
        
        # List tools
        self._tools["list_devices"] = {
            "description": "List all devices with optional state filtering",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "state_filter": {
                        "type": "object",
                        "description": "Optional state conditions to filter devices"
                    }
                }
            },
            "function": self._tool_list_devices
        }
        
        self._tools["list_variables"] = {
            "description": "List all variables with id, name, and folder (when not in root)",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "function": self._tool_list_variables
        }
        
        self._tools["list_action_groups"] = {
            "description": "List all action groups",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "function": self._tool_list_action_groups
        }

        # List variable folders tool
        self._tools["list_variable_folders"] = {
            "description": "List all variable folders for organization",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "function": self._tool_list_variable_folders
        }

        # State-based queries
        self._tools["get_devices_by_state"] = {
            "description": "Get devices by state conditions",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "state_conditions": {
                        "type": "object",
                        "description": "State conditions to match"
                    },
                    "device_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional device types to filter. Valid types: dimmer, relay, sensor, multiio, speedcontrol, sprinkler, thermostat, device. Common aliases supported: light→dimmer, switch→relay, motion→sensor, fan→speedcontrol, etc."
                    }
                },
                "required": ["state_conditions"]
            },
            "function": self._tool_get_devices_by_state
        }
        
        # Direct lookup tools
        self._tools["get_device_by_id"] = {
            "description": "Get a specific device by ID",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The device ID"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_get_device_by_id
        }

        self._tools["get_variable_by_id"] = {
            "description": "Get a specific variable by ID",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variable_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The variable ID"
                    }
                },
                "required": ["variable_id"]
            },
            "function": self._tool_get_variable_by_id
        }
        
        self._tools["get_action_group_by_id"] = {
            "description": "Get a specific action group by ID",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The action group ID"
                    }
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_get_action_group_by_id
        }

        # Log query tool
        self._tools["query_event_log"] = {
            "description": "Query recent Indigo server event log entries",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "line_count": {
                        "type": "number",
                        "description": "Number of log entries to return (default: 20)"
                    },
                    "show_timestamp": {
                        "type": "boolean",
                        "description": "Include timestamps in log entries (default: true)"
                    }
                }
            },
            "function": self._tool_query_event_log
        }

        # Plugin control tools
        self._tools["list_plugins"] = {
            "description": "List all Indigo plugins",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_disabled": {
                        "type": "boolean",
                        "description": "Whether to include disabled plugins (default: False)"
                    }
                }
            },
            "function": self._tool_list_plugins
        }

        self._tools["get_plugin_by_id"] = {
            "description": "Get specific plugin information by ID",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_id": {
                        "type": "string",
                        "description": "Plugin bundle identifier (e.g., 'com.clives.indigoplugin.claudebridge')"
                    }
                },
                "required": ["plugin_id"]
            },
            "function": self._tool_get_plugin_by_id
        }

        self._tools["restart_plugin"] = {
            "description": "Restart an Indigo plugin",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_id": {
                        "type": "string",
                        "description": "Plugin bundle identifier"
                    }
                },
                "required": ["plugin_id"]
            },
            "function": self._tool_restart_plugin
        }

        self._tools["get_plugin_status"] = {
            "description": "Get detailed plugin status",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_id": {
                        "type": "string",
                        "description": "Plugin bundle identifier"
                    }
                },
                "required": ["plugin_id"]
            },
            "function": self._tool_get_plugin_status
        }

    def _register_resources(self):
        """Register all available resources."""
        # Device resources
        self._resources["indigo://devices"] = {
            "name": "Devices",
            "description": "List all Indigo devices",
            "function": self._resource_list_devices
        }
        
        self._resources["indigo://devices/{device_id}"] = {
            "name": "Device",
            "description": "Get a specific device",
            "function": self._resource_get_device
        }
        
        # Variable resources
        self._resources["indigo://variables"] = {
            "name": "Variables",
            "description": "List all Indigo variables",
            "function": self._resource_list_variables
        }
        
        self._resources["indigo://variables/{variable_id}"] = {
            "name": "Variable",
            "description": "Get a specific variable",
            "function": self._resource_get_variable
        }
        
        # Action resources
        self._resources["indigo://actions"] = {
            "name": "Action Groups",
            "description": "List all action groups",
            "function": self._resource_list_actions
        }
        
        self._resources["indigo://actions/{action_id}"] = {
            "name": "Action Group",
            "description": "Get a specific action group",
            "function": self._resource_get_action
        }
    
    # Tool implementation methods
    def _tool_search_entities(
        self,
        query: str,
        device_types: List[str] = None,
        entity_types: List[str] = None,
        state_filter: Dict = None,
        detail: str = "slim"
    ) -> str:
        """Search entities tool implementation."""
        try:
            # Validate device types
            if device_types:
                resolved_types, invalid_device_types = DeviceTypeResolver.resolve_device_types(device_types)
                if invalid_device_types:
                    # Generate helpful error message with suggestions
                    error_parts = [f"Invalid device types: {invalid_device_types}"]
                    error_parts.append(f"Valid types: {IndigoDeviceType.get_all_types()}")

                    # Add suggestions for each invalid type
                    for invalid_type in invalid_device_types:
                        suggestions = DeviceTypeResolver.get_suggestions_for_invalid_type(invalid_type)
                        if suggestions:
                            error_parts.append(f"Did you mean: {', '.join(suggestions)}")

                    return safe_json_dumps({
                        "error": " | ".join(error_parts),
                        "query": query
                    })

                # Use resolved types for the search
                device_types = resolved_types
            
            # Validate entity types
            if entity_types:
                invalid_entity_types = [
                    et for et in entity_types
                    if not IndigoEntityType.is_valid_type(et)
                ]
                if invalid_entity_types:
                    return safe_json_dumps({
                        "error": f"Invalid entity types: {invalid_entity_types}",
                        "query": query
                    })
            
            self.logger.info(
                f"[search_entities]: query: '{query}', "
                f"device_types: {device_types}, "
                f"entity_types: {entity_types}, "
                f"state_filter: {state_filter}"
            )
            
            results = self.search_handler.search(
                query, device_types, entity_types, state_filter, detail=detail
            )
            return safe_json_dumps(results)
            
        except Exception as e:
            self.logger.error(f"[search_entities]: Error - {e}")
            return safe_json_dumps({"error": str(e), "query": query})
    
    def _tool_get_devices_by_type(self, device_type: str) -> str:
        """Get devices by type tool implementation."""
        try:
            result = self.get_devices_by_type_handler.get_devices(device_type)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Get devices by type error: {e}")
            return safe_json_dumps({"error": str(e), "device_type": device_type})
    
    def _tool_device_turn_on(self, device_id: int) -> str:
        """Turn on device tool implementation."""
        try:
            result = self.device_control_handler.turn_on(device_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Device turn on error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_device_turn_off(self, device_id: int) -> str:
        """Turn off device tool implementation."""
        try:
            result = self.device_control_handler.turn_off(device_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Device turn off error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_device_set_brightness(self, device_id: int, brightness: float) -> str:
        """Set device brightness tool implementation."""
        try:
            result = self.device_control_handler.set_brightness(device_id, brightness)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Device set brightness error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_device_control(self, name: str, action: str, brightness: float = None) -> str:
        """Find device by name and control it in one round trip."""
        try:
            t_start = time.perf_counter()
            # Search for device by name
            search_result = self.search_handler.search(
                query=name,
                entity_types=["devices"],
                detail="slim"
            )
            devices = search_result.get("results", {}).get("devices", [])
            if not devices:
                return safe_json_dumps({"error": f"No device found matching '{name}'", "success": False})

            top     = devices[0]
            score   = top.get("relevance_score", 0)
            if score < 0.5:
                suggestions = [d["name"] for d in devices[:3]]
                return safe_json_dumps({
                    "error":       f"No confident match for '{name}' (best: '{top['name']}' score={score:.2f})",
                    "success":     False,
                    "suggestions": suggestions
                })

            device_id   = top["id"]
            device_name = top["name"]

            if action == "turn_on":
                result = self.device_control_handler.turn_on(device_id)
            elif action == "turn_off":
                result = self.device_control_handler.turn_off(device_id)
            elif action == "toggle":
                on_state = top.get("onState", False)
                result   = self.device_control_handler.turn_off(device_id) if on_state else self.device_control_handler.turn_on(device_id)
            elif action == "set_brightness":
                if brightness is None:
                    return safe_json_dumps({"error": "brightness required for set_brightness", "success": False})
                result = self.device_control_handler.set_brightness(device_id, brightness)
            else:
                return safe_json_dumps({"error": f"Unknown action: {action}", "success": False})

            result["matched_device"] = device_name
            result["match_score"]    = score
            result["elapsed_ms"]     = round((time.perf_counter() - t_start) * 1000)
            return safe_json_dumps(result)

        except Exception as e:
            self.logger.error(f"Device control error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_variable_update(self, variable_id: int, value: str) -> str:
        """Update variable tool implementation."""
        try:
            result = self.variable_control_handler.update(variable_id, value)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Variable update error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_variable_create(
        self,
        name: str,
        value: str = "",
        folder_id: int = 0
    ) -> str:
        """Create variable tool implementation."""
        try:
            result = self.variable_control_handler.create(name, value, folder_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Variable create error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_action_execute_group(
        self, 
        action_group_id: int, 
        delay: int = None
    ) -> str:
        """Execute action group tool implementation."""
        try:
            result = self.action_control_handler.execute(action_group_id, delay)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Action execute error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_analyze_historical_data(
        self, 
        query: str, 
        device_names: List[str], 
        time_range_days: int = 30
    ) -> str:
        """Analyze historical data tool implementation."""
        try:
            result = self.historical_analysis_handler.analyze_historical_data(
                query, device_names, time_range_days
            )
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Historical analysis error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_list_devices(self, state_filter: Dict = None) -> str:
        """List devices tool implementation."""
        try:
            devices = self.list_handlers.list_all_devices(state_filter)
            return safe_json_dumps(devices)
        except Exception as e:
            self.logger.error(f"List devices error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_list_variables(self) -> str:
        """List variables tool implementation."""
        try:
            variables = self.list_handlers.list_all_variables()
            return safe_json_dumps(variables)
        except Exception as e:
            self.logger.error(f"List variables error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_list_action_groups(self) -> str:
        """List action groups tool implementation."""
        try:
            actions = self.list_handlers.list_all_action_groups()
            return safe_json_dumps(actions)
        except Exception as e:
            self.logger.error(f"List action groups error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_variable_folders(self) -> str:
        """List variable folders tool implementation."""
        try:
            folders = self.list_handlers.list_variable_folders()
            return safe_json_dumps(folders)
        except Exception as e:
            self.logger.error(f"List variable folders error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_get_devices_by_state(
        self, 
        state_conditions: Dict, 
        device_types: List[str] = None
    ) -> str:
        """Get devices by state tool implementation."""
        try:
            # Validate device types if provided
            if device_types:
                resolved_types, invalid_types = DeviceTypeResolver.resolve_device_types(device_types)
                if invalid_types:
                    # Generate helpful error message with suggestions
                    error_parts = [f"Invalid device types: {invalid_types}"]
                    error_parts.append(f"Valid types: {IndigoDeviceType.get_all_types()}")

                    # Add suggestions for each invalid type
                    for invalid_type in invalid_types:
                        suggestions = DeviceTypeResolver.get_suggestions_for_invalid_type(invalid_type)
                        if suggestions:
                            error_parts.append(f"Did you mean: {', '.join(suggestions)}")

                    return safe_json_dumps({
                        "error": " | ".join(error_parts)
                    })

                # Use resolved types for the query
                device_types = resolved_types
            
            devices = self.list_handlers.get_devices_by_state(
                state_conditions, device_types
            )
            return safe_json_dumps(devices)
        except Exception as e:
            self.logger.error(f"Get devices by state error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_get_device_by_id(self, device_id) -> str:
        """Get device by ID tool implementation."""
        try:
            device_id = int(device_id)
            device = self.data_provider.get_device(device_id)
            if device is None:
                return safe_json_dumps({
                    "error": f"Device {device_id} not found"
                })
            return safe_json_dumps(device)
        except Exception as e:
            self.logger.error(f"Get device by ID error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_get_variable_by_id(self, variable_id) -> str:
        """Get variable by ID tool implementation."""
        try:
            variable_id = int(variable_id)
            variable = self.data_provider.get_variable(variable_id)
            if variable is None:
                return safe_json_dumps({
                    "error": f"Variable {variable_id} not found"
                })
            return safe_json_dumps(variable)
        except Exception as e:
            self.logger.error(f"Get variable by ID error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _tool_get_action_group_by_id(self, action_group_id) -> str:
        """Get action group by ID tool implementation."""
        try:
            action_group_id = int(action_group_id)
            action = self.data_provider.get_action_group(action_group_id)
            if action is None:
                return safe_json_dumps({
                    "error": f"Action group {action_group_id} not found"
                })
            return safe_json_dumps(action)
        except Exception as e:
            self.logger.error(f"Get action group by ID error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_query_event_log(
        self,
        line_count: int = 20,
        show_timestamp: bool = True
    ) -> str:
        """Query event log tool implementation."""
        try:
            result = self.log_query_handler.query(
                line_count=line_count,
                show_timestamp=show_timestamp
            )
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Query event log error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_plugins(self, include_disabled: bool = False) -> str:
        """List plugins tool implementation."""
        try:
            result = self.plugin_control_handler.list_plugins(include_disabled)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"List plugins error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_get_plugin_by_id(self, plugin_id: str) -> str:
        """Get plugin by ID tool implementation."""
        try:
            result = self.plugin_control_handler.get_plugin_by_id(plugin_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Get plugin by ID error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_restart_plugin(self, plugin_id: str) -> str:
        """Restart plugin tool implementation."""
        try:
            result = self.plugin_control_handler.restart_plugin(plugin_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Restart plugin error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_get_plugin_status(self, plugin_id: str) -> str:
        """Get plugin status tool implementation."""
        try:
            result = self.plugin_control_handler.get_plugin_status(plugin_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Get plugin status error: {e}")
            return safe_json_dumps({"error": str(e)})

    # Resource implementation methods
    def _resource_list_devices(self) -> str:
        """List all devices resource."""
        try:
            devices = self.list_handlers.list_all_devices()
            return safe_json_dumps(devices)
        except Exception as e:
            self.logger.error(f"Resource list devices error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _resource_get_device(self, device_id: str) -> str:
        """Get specific device resource."""
        try:
            device = self.data_provider.get_device(int(device_id))
            if device is None:
                return safe_json_dumps({
                    "error": f"Device {device_id} not found"
                })
            return safe_json_dumps(device)
        except Exception as e:
            self.logger.error(f"Resource get device error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _resource_list_variables(self) -> str:
        """List all variables resource."""
        try:
            variables = self.list_handlers.list_all_variables()
            return safe_json_dumps(variables)
        except Exception as e:
            self.logger.error(f"Resource list variables error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _resource_get_variable(self, variable_id: str) -> str:
        """Get specific variable resource."""
        try:
            variable = self.data_provider.get_variable(int(variable_id))
            if variable is None:
                return safe_json_dumps({
                    "error": f"Variable {variable_id} not found"
                })
            return safe_json_dumps(variable)
        except Exception as e:
            self.logger.error(f"Resource get variable error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _resource_list_actions(self) -> str:
        """List all action groups resource."""
        try:
            actions = self.list_handlers.list_all_action_groups()
            return safe_json_dumps(actions)
        except Exception as e:
            self.logger.error(f"Resource list actions error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    def _resource_get_action(self, action_id: str) -> str:
        """Get specific action group resource."""
        try:
            action = self.data_provider.get_action_group(int(action_id))
            if action is None:
                return safe_json_dumps({
                    "error": f"Action group {action_id} not found"
                })
            return safe_json_dumps(action)
        except Exception as e:
            self.logger.error(f"Resource get action error: {e}")
            return safe_json_dumps({"error": str(e)})
    
    # Helper methods
    def _json_response(self, obj: Any, status: int = 200) -> Dict[str, Any]:
        """Create JSON response for IWS."""
        return {
            "status": status,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "content": json.dumps(obj)
        }
    
    def _json_error(
        self, 
        msg_id: Any, 
        code: int, 
        message: str, 
        data: Any = None
    ) -> Dict[str, Any]:
        """Create JSON-RPC error response."""
        error = {
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message
            }
        }
        
        if data is not None:
            error["error"]["data"] = data
        
        if msg_id is not None:
            error["id"] = msg_id
        
        return error