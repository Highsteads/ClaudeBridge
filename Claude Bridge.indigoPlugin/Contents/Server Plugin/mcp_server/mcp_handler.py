"""
MCP Handler for Indigo IWS integration.
Implements standards-compliant MCP protocol over Indigo's built-in web server.
"""

import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Union

from .adapters.data_provider import DataProvider
from .common.indigo_device_types import IndigoDeviceType, IndigoEntityType, DeviceTypeResolver
from .common.json_encoder import safe_json_dumps
from .common.progress import ProgressEmitter, encode_sse_response
from .common.tool_cache import ToolCache
from .common.vector_store.vector_store_manager import VectorStoreManager
from .handlers.list_handlers import ListHandlers
from .security import RateLimiter, RateLimitExceeded, ScopeManager, ScopeDenied, required_scope_for
from .tools.action_control import ActionControlHandler
from .tools.device_control import DeviceControlHandler
from .tools.device_control.color_names import parse_color
from .tools.get_devices_by_type import GetDevicesByTypeHandler
from .tools.historical_analysis import HistoricalAnalysisHandler
from .tools.log_query import LogQueryHandler
from .tools.plugin_control import PluginControlHandler
from .tools.search_entities import SearchEntitiesHandler
from .tools.variable_control import VariableControlHandler
from .tools.system_tools import SystemToolsHandler
from .tools.schedule_control import ScheduleControlHandler
from .tools.audit import AuditHandler
from .tools.memory import MemoryHandler
from .tools.script_tools import ScriptToolsHandler
from .tools.events import EventsHandler
from .tools.home_status import HomeStatusHandler
from .tools.energy_tools import EnergyToolsHandler
from .tools.scripting_shell import ScriptingShellHandler
from .tools.extended_tools import ExtendedToolsHandler
from .tools.plugin_dev_tools import PluginDevToolsHandler


class MCPHandler:
    """Handles MCP protocol requests through Indigo IWS."""
    
    # MCP Protocol version we support
    PROTOCOL_VERSION = "2025-06-18"

    # Tools whose exception text can embed secrets/credentials/internal paths or
    # executed code. Their raw error is scrubbed from the client response (which
    # can travel over the reflector); full detail stays in the server event log.
    _SENSITIVE_ERROR_TOOLS = frozenset({
        "send_email", "send_notification", "execute_indigo_python",
        "run_script", "scaffold_automation_script", "write_script", "create_script",
        "webhook_create", "webhook_list", "webhook_delete",
    })

    def __init__(
        self,
        data_provider: DataProvider,
        logger: Optional[logging.Logger] = None,
        plugin=None,
        rate_limit_per_minute: int = 120,
        rate_limit_per_day:    int = 5_000,
        cache_ttl_seconds:     int = 60,
        scopes_file:           Optional[str] = None,
    ):
        """
        Initialize the MCP handler.

        Args:
            data_provider: Data provider for accessing entity data
            logger: Optional logger instance
            plugin: Owning Plugin instance — used for triggerEvent() calls
                    and tool-call telemetry. May be None in test contexts.
            rate_limit_per_minute: Per-session sliding-window cap (default 120).
            rate_limit_per_day:    Per-session daily cap (default 5000).
            cache_ttl_seconds:     TTL for cacheable read tools, 0 disables.
            scopes_file: Optional path to scopes.json for per-token authorisation.
        """
        self.data_provider = data_provider
        self.logger = logger or logging.getLogger("Plugin")
        self.plugin = plugin

        # Session management. _sessions_lock guards every read/write/iteration
        # of _sessions under concurrent IWS dispatch.
        self._sessions = {}  # session_id -> {created, last_seen, client_info}
        self._sessions_lock = threading.Lock()
        self._session_idle_ttl = 24 * 3600   # prune sessions idle longer than this
        self._session_max = 500              # hard cap as a backstop

        # Tool-call telemetry — rolling window of recent calls for /health metrics.
        # deque(maxlen) is append-atomic and self-trimming; _telemetry_lock guards
        # the snapshot reads in get_health_data and the error counter.
        # Each entry: {"name": str, "duration_ms": int, "ok": bool, "ts": float}
        self._tool_call_log: "deque[Dict[str, Any]]" = deque(maxlen=200)
        self._telemetry_lock = threading.Lock()
        self._tool_error_count = 0

        # ── Phase 2 hardening ─────────────────────────────────────────────
        self.rate_limiter = RateLimiter(
            per_minute=rate_limit_per_minute,
            per_day=rate_limit_per_day,
            logger=self.logger,
        )
        self.tool_cache = ToolCache(
            default_ttl=cache_ttl_seconds,
            logger=self.logger,
        )
        self.scope_manager = ScopeManager(
            scopes_file=scopes_file or "",
            logger=self.logger,
        )
        # Per-call ProgressEmitter — stored per-thread so concurrent tools/call
        # requests cannot clobber each other's emitter (was a shared attribute).
        self._emitter_local = threading.local()

        # Get database path from the in-process runtime config (moved off
        # os.environ in v2.4.1 — see mcp_server/runtime_config.py).
        from mcp_server import runtime_config
        db_path = runtime_config.get("db_file")
        if not db_path:
            raise ValueError("db_file must be configured via runtime_config")

        # Initialize vector store manager
        self.vector_store_manager = VectorStoreManager(
            data_provider=data_provider,
            db_path=db_path,
            logger=self.logger,
            update_interval=300,  # 5 minutes
        )

        # Start vector store manager in background. The DB connection is
        # opened synchronously so handlers wire up fine, but the slow initial
        # embedding rebuild (60-90s on a 400-device install) runs on a daemon
        # thread. Without this, every restart left the MCP endpoint routable
        # but blocked until embeddings finished. See VectorStoreManager.start_async()
        # for the split. v2.6.2 fix.
        self.vector_store_manager.start_async()

        # Initialize handlers
        self._init_handlers()

        # Register tools and resources
        self._tools = {}
        self._resources = {}
        self._register_tools()
        self._register_resources()

        # Deny-by-default self-check: every registered tool must be classified
        # into exactly one scope bucket. Logs an ERROR for any unclassified tool
        # (which then fails closed to admin) so a new tool can never silently
        # land in READ. See ScopeManager.audit_classification().
        self.scope_manager.audit_classification(list(self._tools.keys()))

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
        self.system_tools_handler = SystemToolsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.schedule_control_handler = ScheduleControlHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.audit_handler = AuditHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.memory_handler = MemoryHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.script_tools_handler = ScriptToolsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.events_handler = EventsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.home_status_handler = HomeStatusHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.energy_tools_handler = EnergyToolsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.scripting_shell_handler = ScriptingShellHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.extended_tools_handler = ExtendedToolsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )
        self.plugin_dev_tools_handler = PluginDevToolsHandler(
            data_provider=self.data_provider,
            logger=self.logger
        )

    def stop(self):
        """Stop the MCP handler and cleanup resources."""
        if self.vector_store_manager:
            self.vector_store_manager.stop()

    ########################################
    # Health / Diagnostics
    ########################################

    def _prune_sessions_locked(self, now_ts: float) -> None:
        """
        Evict idle sessions so _sessions cannot grow unbounded. MUST be called
        with _sessions_lock held. Also clears each evicted session's
        rate-limiter buckets. Applies an idle TTL plus a hard-cap backstop.
        """
        stale = [
            sid for sid, info in self._sessions.items()
            if (now_ts - info.get("last_seen", 0)) > self._session_idle_ttl
        ]
        # Hard cap: if still over the limit, drop the oldest by last_seen.
        if (len(self._sessions) - len(stale)) > self._session_max:
            remaining = sorted(
                (s for s in self._sessions if s not in stale),
                key=lambda s: self._sessions[s].get("last_seen", 0),
            )
            overflow = len(self._sessions) - len(stale) - self._session_max
            stale.extend(remaining[:overflow])
        for sid in stale:
            self._sessions.pop(sid, None)
            try:
                self.rate_limiter.reset_session(sid)
            except Exception:
                pass

    def get_health_data(self, plugin_start_time: float = None) -> Dict[str, Any]:
        """
        Return a snapshot of plugin health for the /health endpoint.
        Includes uptime, session count, tool inventory, recent tool latencies,
        and vector-store status. Cheap to compute — safe to call frequently.
        """
        now = time.time()

        # Snapshot the telemetry under the lock, then aggregate off-lock.
        with self._telemetry_lock:
            call_log = list(self._tool_call_log)
            error_count = self._tool_error_count
        with self._sessions_lock:
            session_count = len(self._sessions)

        # Per-tool latency aggregates over the rolling window
        per_tool: Dict[str, Dict[str, Any]] = {}
        for entry in call_log:
            agg = per_tool.setdefault(entry["name"], {"calls": 0, "errors": 0, "total_ms": 0, "max_ms": 0})
            agg["calls"]    += 1
            agg["errors"]   += 0 if entry["ok"] else 1
            agg["total_ms"] += entry["duration_ms"]
            agg["max_ms"]    = max(agg["max_ms"], entry["duration_ms"])
        for name, agg in per_tool.items():
            agg["avg_ms"] = round(agg["total_ms"] / agg["calls"], 1) if agg["calls"] else 0

        # Vector store status (best-effort) — read via the manager's own get_stats()
        vs_status = {"available": False}
        try:
            if self.vector_store_manager:
                stats = self.vector_store_manager.get_stats()
                vs_status["available"]       = True
                vs_status["last_update"]     = stats.get("last_update")
                vs_status["update_interval"] = stats.get("update_interval")
                vs_status["is_running"]      = self.vector_store_manager.is_running
        except Exception as e:
            vs_status["error"] = str(e)

        return {
            "status":           "ok",
            "plugin":           "Claude Bridge",
            "protocol_version": self.PROTOCOL_VERSION,
            "uptime_seconds":   round(now - plugin_start_time, 1) if plugin_start_time else None,
            "sessions":         session_count,
            "tools":            len(self._tools),
            "resources":        len(self._resources),
            "tool_calls": {
                "total_in_window": len(call_log),
                "errors_lifetime": error_count,
                "per_tool":        per_tool,
                "recent": [
                    {"name": e["name"], "duration_ms": e["duration_ms"], "ok": e["ok"],
                     "cache_hit": e.get("cache_hit", False),
                     "ago_seconds": round(now - e["ts"], 1)}
                    for e in call_log[-10:]
                ],
            },
            "vector_store": vs_status,
            "rate_limiter": {
                "per_minute":   self.rate_limiter.per_minute,
                "per_day":      self.rate_limiter.per_day,
                "per_session":  self.rate_limiter.snapshot(),
            },
            "cache":  self.tool_cache.stats(),
            "scopes": self.scope_manager.summary(),
        }

    def get_tool_explorer_html(self, endpoint_url: str = "") -> str:
        """
        Render an HTML page listing every registered MCP tool: description, args,
        required fields. Useful for plugin testing / public release docs / debugging.
        Pure stdlib — no template engine.
        """
        # Sort tools alphabetically for stable browsing
        tools_sorted = sorted(self._tools.items(), key=lambda kv: kv[0])

        rows = []
        for name, info in tools_sorted:
            schema = info.get("inputSchema", {}) or {}
            props  = (schema.get("properties") or {})
            required = set(schema.get("required") or [])

            param_lines = []
            for pname, pinfo in props.items():
                ptype = pinfo.get("type") or " | ".join(
                    t.get("type", "?") for t in pinfo.get("anyOf", [])
                ) or "?"
                req_marker = " <em>(required)</em>" if pname in required else ""
                desc = (pinfo.get("description") or "").replace("<", "&lt;").replace(">", "&gt;")
                param_lines.append(
                    f"<li><code>{pname}</code> <span class='ptype'>{ptype}</span>{req_marker}<br><span class='pdesc'>{desc}</span></li>"
                )
            params_html = f"<ul class='params'>{''.join(param_lines)}</ul>" if param_lines else "<em class='no-params'>(no arguments)</em>"

            description = (info.get("description") or "").replace("<", "&lt;").replace(">", "&gt;")
            rows.append(f"""
              <details class='tool'>
                <summary><code class='tname'>{name}</code> — {description}</summary>
                {params_html}
              </details>
            """)

        endpoint_note = (
            f"<p class='endpoint'>Endpoint: <code>{endpoint_url}</code></p>"
            if endpoint_url else ""
        )

        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Claude Bridge — Tool Explorer</title>
<style>
 body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 980px; margin: 2em auto; padding: 0 1em; color: #222; }}
 h1 {{ border-bottom: 2px solid #444; padding-bottom: 0.3em; }}
 .meta {{ color: #666; font-size: 0.9em; margin-bottom: 1.5em; }}
 .tool {{ margin: 0.6em 0; padding: 0.6em 0.9em; background: #f6f6f8; border-radius: 6px; border: 1px solid #e2e2e8; }}
 .tool summary {{ cursor: pointer; font-size: 1em; }}
 .tname {{ background: #2b6cb0; color: white; padding: 1px 6px; border-radius: 3px; font-weight: 600; }}
 .params {{ list-style: none; padding-left: 0.5em; margin-top: 0.6em; }}
 .params li {{ margin: 0.4em 0; padding: 0.3em 0.5em; background: white; border-left: 3px solid #2b6cb0; }}
 .ptype {{ color: #888; font-style: italic; font-size: 0.85em; }}
 .pdesc {{ color: #555; font-size: 0.9em; }}
 .no-params {{ color: #888; }}
 code {{ font-family: ui-monospace, "SF Mono", Monaco, monospace; font-size: 0.92em; }}
 .endpoint code {{ background: #fff3cd; padding: 1px 4px; border-radius: 3px; }}
</style></head>
<body>
 <h1>🌉 Claude Bridge — Tool Explorer</h1>
 <p class='meta'>{len(self._tools)} tools • {len(self._resources)} resources • protocol {self.PROTOCOL_VERSION}</p>
 {endpoint_note}
 {''.join(rows)}
</body></html>
"""
    
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

            # Buffered SSE response path — used by tools that emitted progress
            # events. The body already contains valid SSE blocks ending in
            # "data: [DONE]\n\n", which indigo_mcp_proxy.py's reader handles.
            if isinstance(resp, dict) and "_sse_body" in resp:
                return {
                    "status": resp.get("_status", 200),
                    "headers": {
                        "Content-Type":  "text/event-stream; charset=utf-8",
                        "Cache-Control": "no-cache",
                        "Connection":    "keep-alive",
                        **extra_headers,
                    },
                    "content": resp["_sse_body"],
                }

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
        
        # MCP 2025-06-18 requires MCP-Protocol-Version header for HTTP transport.
        # A PRESENT-but-mismatched version is always wrong, so enforce this
        # independently of the session-store state below. (Previously this was
        # also gated on `and self._sessions`, so the empty-_sessions reconnect
        # window after a restart silently accepted a mismatched protocol version.)
        # A missing header is still tolerated — only a wrong one is rejected.
        protocol_version_header = headers.get("mcp-protocol-version")
        if method != "initialize" and not method.startswith("notifications/"):
            if protocol_version_header and protocol_version_header != self.PROTOCOL_VERSION:
                self.logger.debug(f"Invalid protocol version: {protocol_version_header}")
                return self._json_error(msg_id, -32600, f"Unsupported protocol version: {protocol_version_header}")

        # Session validation (skip for initialize and notifications).
        # NOTE: the `and self._sessions` grace clause is deliberately retained —
        # after a ClaudeBridge restart the proxy still holds the pre-restart
        # session id and does not re-initialise on a session error, so the
        # empty-store grace is what lets the client reconnect. Removing it would
        # lock the client out after every restart.
        session_id = headers.get("mcp-session-id")
        if method != "initialize" and not method.startswith("notifications/") and self._sessions:
            with self._sessions_lock:
                known = bool(session_id) and session_id in self._sessions
                if known:
                    self._sessions[session_id]["last_seen"] = time.time()
            if not known:
                self.logger.debug(f"Invalid session ID for {method}")
                return self._json_error(msg_id, -32600, "Missing or invalid Mcp-Session-Id")

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
            return self._handle_tools_call(msg_id, params, headers)
        
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
            now_ts = time.time()
            with self._sessions_lock:
                self._prune_sessions_locked(now_ts)
                self._sessions[session_id] = {
                    "created": now_ts,
                    "last_seen": now_ts,
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
                        "version": (self.plugin.pluginVersion
                                    if self.plugin and hasattr(self.plugin, "pluginVersion")
                                    else "unknown")
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
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Handle tools/call request with rate-limiting, per-token scope checks,
        TTL caching of read-only tools, and optional buffered-SSE responses
        for tools that emit progress events.
        """
        headers   = headers or {}
        tool_name = params.get("name")
        tool_args = params.get("arguments", {}) or {}

        if tool_name not in self._tools:
            return self._json_error(msg_id, -32602, f"Unknown tool: {tool_name}")

        # ── Bearer / session identification ─────────────────────────────
        bearer = self._extract_bearer(headers)
        session_id = headers.get("mcp-session-id", "")
        no_cache   = "no-cache" in (headers.get("cache-control") or "").lower()

        # ── Rate limit (admin scope gets 10x by default) ─────────────────
        # Key on the bearer first (stable per credential) so a session-rotating
        # client shares one bucket per token rather than escaping the limit.
        scopes = self.scope_manager.scopes_for_token(bearer)
        try:
            self.rate_limiter.check(bearer or session_id or "anonymous", scopes)
        except RateLimitExceeded as rle:
            self.logger.warning(f"⛔ Rate limit hit ({rle.window}) for {tool_name}")
            return self._json_error(
                msg_id, -32099,
                f"Rate limit exceeded: {rle.window}={rle.limit}; retry in {int(rle.retry_after)}s"
            )

        # ── Scope gate ──────────────────────────────────────────────────
        try:
            self.scope_manager.check(bearer, tool_name)
        except ScopeDenied as sd:
            self.logger.warning(
                f"⛔ Scope denied for tool '{tool_name}' "
                f"(token='{self.scope_manager.name_for_token(bearer)}', has={sd.granted})"
            )
            return self._json_error(msg_id, -32099, str(sd))

        # ── Argument validation (required keys present) ──────────────────
        # A lightweight check against the tool's declared inputSchema so a
        # missing required field returns a clear -32602 naming the field rather
        # than surfacing as an opaque -32603 from the **kwargs call below.
        schema   = self._tools[tool_name].get("inputSchema") or {}
        required = set(schema.get("required") or [])
        missing  = [k for k in required if k not in tool_args]
        if missing:
            return self._json_error(
                msg_id, -32602,
                f"Missing required argument(s) for {tool_name}: {', '.join(sorted(missing))}"
            )

        # ── Per-call progress emitter (used by long-running tools) ───────
        emitter = ProgressEmitter(request_id=msg_id, tool_name=tool_name)
        self._emitter_local.emitter = emitter

        start = time.time()
        ok = False
        cache_hit = False
        try:
            # Cache-aware dispatch — only for tools in the read allow-list
            def _compute():
                return self._tools[tool_name]["function"](**tool_args)

            result, cache_hit = self.tool_cache.get_or_compute(
                tool_name, tool_args, _compute, no_cache=no_cache
            )
            ok = True

            # Mutating tools invalidate related cache buckets
            if not cache_hit:
                dropped = self.tool_cache.invalidate_for_tool(tool_name)
                if dropped:
                    self.logger.debug(
                        f"Cache: dropped {dropped} entries after {tool_name}"
                    )

            response = {
                "jsonrpc": "2.0",
                "id":      msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": result}
                    ],
                    # Hint to clients: 'cache-hit' lets Claude know the data
                    # is up to TTL seconds stale; useful when debugging.
                    "_meta": {
                        "cache_hit": cache_hit,
                        "tool":      tool_name,
                    },
                },
            }

            # If the tool emitted progress events, return as buffered SSE so
            # the client sees ordered notifications/progress + final result.
            if emitter.has_events:
                sse_body = encode_sse_response(emitter.events, response, msg_id)
                return {
                    "_sse_body": sse_body,
                    "_status":   200,
                }
            return response

        except Exception as e:
            with self._telemetry_lock:
                self._tool_error_count += 1
            self.logger.error(f"Tool {tool_name} error: {e}")
            # Don't echo a secret-bearing tool's raw exception back to the client
            # (the response can travel over the reflector). Full detail is logged
            # above; the client gets a generic pointer to the log.
            if tool_name in self._SENSITIVE_ERROR_TOOLS:
                detail = "see the Claude Bridge event log for details"
            else:
                detail = str(e)
            return self._json_error(
                msg_id, -32603, f"Tool '{tool_name}' execution failed: {detail}"
            )
        finally:
            self._emitter_local.emitter = None
            duration_ms = int((time.time() - start) * 1000)
            # deque(maxlen) self-trims; append is atomic but lock anyway so the
            # health snapshot never reads a torn list.
            with self._telemetry_lock:
                self._tool_call_log.append({
                    "name":        tool_name,
                    "duration_ms": duration_ms,
                    "ok":          ok,
                    "cache_hit":   cache_hit,
                    "ts":          time.time(),
                })

    @staticmethod
    def _extract_bearer(headers: Dict[str, str]) -> Optional[str]:
        """Pull the Bearer token out of the Authorization header (case-insensitive)."""
        for key in ("authorization", "Authorization"):
            val = headers.get(key)
            if val:
                parts = val.split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    return parts[1].strip()
        return None
    
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

        self._tools["set_heat_setpoint"] = {
            "description": "Set the heat setpoint on a thermostat/TRV device (e.g. RAMSES, Evohome). "
                           "Value is in degrees Celsius.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The thermostat device ID"
                    },
                    "setpoint": {
                        "type": "number",
                        "description": "Target temperature in degrees Celsius"
                    }
                },
                "required": ["device_id", "setpoint"]
            },
            "function": self._tool_set_heat_setpoint
        }

        self._tools["set_cool_setpoint"] = {
            "description": "Set the cool setpoint on a thermostat device. Value is in degrees Celsius.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The thermostat device ID"
                    },
                    "setpoint": {
                        "type": "number",
                        "description": "Target cool temperature in degrees Celsius"
                    }
                },
                "required": ["device_id", "setpoint"]
            },
            "function": self._tool_set_cool_setpoint
        }

        self._tools["set_hvac_mode"] = {
            "description": "Set the HVAC operating mode on a thermostat device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The thermostat device ID"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["heat", "cool", "auto", "off",
                                 "programHeat", "programCool", "programAuto"],
                        "description": "HVAC mode to set"
                    }
                },
                "required": ["device_id", "mode"]
            },
            "function": self._tool_set_hvac_mode
        }

        self._tools["lock_device"] = {
            "description": "Lock a Z-Wave or other lock device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The lock device ID"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_lock_device
        }

        self._tools["unlock_device"] = {
            "description": "Unlock a Z-Wave or other lock device, optionally with a PIN code.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The lock device ID"
                    },
                    "code": {
                        "type": "string",
                        "description": "Optional PIN code for the lock"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_unlock_device
        }

        self._tools["set_color"] = {
            "description": "Set the colour of an RGB or RGBW light dimmer. Provide EITHER a 'color' string (a hex code like '#FF8000' or '#F80', or a CSS/X11 colour name like 'dodgerblue' — 148 names, British 'grey' spellings accepted) OR explicit red/green/blue channels (0-255 each). 'color' takes precedence if both are given.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The dimmer device ID"
                    },
                    "color": {
                        "type": "string",
                        "description": "Hex code (#RRGGBB, #RGB, with or without #) or a CSS colour name (e.g. 'dodgerblue', 'tomato', 'rebeccapurple'). Resolves to red/green/blue; takes precedence over the individual channels."
                    },
                    "red":   {"type": "number", "description": "Red channel 0-255 (ignored if 'color' is given)"},
                    "green": {"type": "number", "description": "Green channel 0-255 (ignored if 'color' is given)"},
                    "blue":  {"type": "number", "description": "Blue channel 0-255 (ignored if 'color' is given)"},
                    "white": {"type": "number", "description": "White channel 0-255 (RGBW only)"},
                    "white_temperature": {
                        "type": "number",
                        "description": "Colour temperature in Kelvin (e.g. 2700-6500)"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_set_color
        }

        self._tools["set_fan_speed"] = {
            "description": "Set the speed level on a fan or speed-control device (0-100%).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The speed-control device ID"
                    },
                    "speed": {
                        "type": "number",
                        "description": "Speed level 0-100"
                    }
                },
                "required": ["device_id", "speed"]
            },
            "function": self._tool_set_fan_speed
        }

        self._tools["request_status_update"] = {
            "description": "Request an immediate status update from a device (polls the device for current state).",
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
            "function": self._tool_request_status_update
        }

        self._tools["increase_heat_setpoint"] = {
            "description": (
                "Increase the heat setpoint on a thermostat/TRV by a given delta "
                "(default 0.5 degC). Use for small step adjustments."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The thermostat device ID"
                    },
                    "delta": {
                        "type": "number",
                        "description": "Degrees Celsius to increase by (default 0.5)"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_increase_heat_setpoint
        }

        self._tools["decrease_heat_setpoint"] = {
            "description": (
                "Decrease the heat setpoint on a thermostat/TRV by a given delta "
                "(default 0.5 degC). Use for small step adjustments."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "The thermostat device ID"
                    },
                    "delta": {
                        "type": "number",
                        "description": "Degrees Celsius to decrease by (default 0.5)"
                    }
                },
                "required": ["device_id"]
            },
            "function": self._tool_decrease_heat_setpoint
        }

        self._tools["get_device_by_name"] = {
            "description": (
                "Find a device by name and return its full state in one round trip. "
                "Tries exact match, then case-insensitive, then partial match. "
                "Returns all device states, properties, and current values."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Device name (exact, partial, or case-insensitive)"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_get_device_by_name
        }

        self._tools["log_message"] = {
            "description": (
                "Write a message to the Indigo on-screen event log (Log Viewer). "
                "The message appears immediately. Use for status updates, confirmations, "
                "or debug output that the user can see in the Indigo UI."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message text to log"
                    },
                    "level": {
                        "type": "string",
                        "enum": ["INFO", "WARNING", "ERROR", "DEBUG"],
                        "description": "Log level (default INFO)"
                    }
                },
                "required": ["message"]
            },
            "function": self._tool_log_message
        }

        self._tools["send_notification"] = {
            "description": (
                "Send a Pushover push notification to the user's device. "
                "Use for important alerts, confirmations, or proactive updates."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Notification title"
                    },
                    "message": {
                        "type": "string",
                        "description": "Notification body text"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["-2", "-1", "0", "1"],
                        "description": "Priority: -2=silent, -1=quiet, 0=normal (default), 1=high"
                    },
                    "sound": {
                        "type": "string",
                        "description": "Notification sound (default 'vibrate')"
                    }
                },
                "required": ["title", "message"]
            },
            "function": self._tool_send_notification
        }

        self._tools["send_email"] = {
            "description": (
                "Send an email via Indigo's configured SMTP device. "
                "Use for detailed reports, logs, or non-urgent notifications."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text (plain text or HTML)"
                    }
                },
                "required": ["recipient", "subject", "body"]
            },
            "function": self._tool_send_email
        }

        self._tools["run_script"] = {
            "description": (
                "Execute a Python script from the Python Scripts folder in the "
                "Indigo Python context. The script runs with full access to the "
                "indigo module. Use for triggering automation logic, one-off tasks, "
                "or testing scripts. Returns stdout/stderr output."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Script filename (with or without .py extension)"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_run_script
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
            "description": "Find devices where a specific state matches a value. E.g. state_key='heatIsOn' state_value='true' to find heating zones, or state_key='onState' state_value='true' for devices that are on.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "state_key": {
                        "type": "string",
                        "description": "The state key to match, e.g. 'heatIsOn', 'onState', 'hvacHeaterIsOn'"
                    },
                    "state_value": {
                        "type": "string",
                        "description": "The value to match as a string, e.g. 'true', 'false', '21.0'"
                    },
                    "device_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional device types to filter, e.g. ['thermostat'], ['relay'], ['dimmer']"
                    }
                },
                "required": ["state_key", "state_value"]
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
            "description": (
                "Query Indigo server event log entries. "
                "Without after/before returns the most recent line_count entries. "
                "With after/before reads from the on-disk log files and returns "
                "all entries in that time window (useful for investigating past events). "
                "Time formats: 'HH:MM:SS' (today assumed), 'YYYY-MM-DDTHH:MM:SS' (full)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "line_count": {
                        "type": "number",
                        "description": "Max entries to return (default: 20)"
                    },
                    "show_timestamp": {
                        "type": "boolean",
                        "description": "Include timestamps in entries (default: true)"
                    },
                    "after": {
                        "type": "string",
                        "description": (
                            "Return only entries after this time. "
                            "Format: 'HH:MM:SS' for today, or 'YYYY-MM-DDTHH:MM:SS' "
                            "for a specific date. Example: '07:45:00'"
                        )
                    },
                    "before": {
                        "type": "string",
                        "description": (
                            "Return only entries before this time. "
                            "Format: 'HH:MM:SS' for today, or 'YYYY-MM-DDTHH:MM:SS'. "
                            "Example: '07:52:00'"
                        )
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

        # ── System / housekeeping tools ────────────────────────────────────

        self._tools["system_health"] = {
            "description": (
                "Return a snapshot of Mac Mini system health: macOS version, "
                "Python version, disk usage (total/used/free/%), RAM summary, "
                "and uptime. No parameters required."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_system_health
        }

        self._tools["list_python_scripts"] = {
            "description": (
                "List all Python scripts (.py files) in the Indigo Scripts "
                "folder. Returns name, size, last-modified date, and full path."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_list_python_scripts
        }

        self._tools["find_orphaned_scripts"] = {
            "description": (
                "Scan all Python scripts in the Indigo Scripts folder and "
                "report any that reference device or variable IDs which no longer "
                "exist in Indigo. Useful for finding stale scripts after devices "
                "or variables have been deleted."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_find_orphaned_scripts
        }

        self._tools["find_orphaned_plugin_data"] = {
            "description": (
                "Compare Preferences/Plugins subdirectories against installed "
                "plugin bundle IDs. Returns any prefs directories that belong to "
                "plugins that are no longer installed, along with their size on "
                "disk. Safe to delete orphaned entries to recover disk space."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_find_orphaned_plugin_data
        }

        self._tools["find_large_files"] = {
            "description": (
                "Walk a directory tree and return files exceeding a size threshold, "
                "sorted largest first. Defaults to scanning the entire Indigo "
                "install folder for files >= 10 MB."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory to scan. Defaults to the Indigo install "
                            "folder if omitted or empty."
                        )
                    },
                    "min_mb": {
                        "type": "number",
                        "description": "Minimum file size in MB to report (default 10)"
                    },
                    "max_results": {
                        "type": "number",
                        "description": "Maximum number of files to return (default 50)"
                    }
                },
                "required": []
            },
            "function": self._tool_find_large_files
        }

        # ── Schedule / trigger tools ───────────────────────────────────────

        self._tools["list_schedules"] = {
            "description": (
                "List all Indigo schedules with their ID, name, enabled state, "
                "and next scheduled execution time."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_list_schedules
        }

        self._tools["enable_schedule"] = {
            "description": "Enable an Indigo schedule by ID or name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Schedule ID (number) or name (string)"
                    }
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_enable_schedule
        }

        self._tools["disable_schedule"] = {
            "description": "Disable an Indigo schedule by ID or name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Schedule ID (number) or name (string)"
                    }
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_disable_schedule
        }

        self._tools["list_triggers"] = {
            "description": (
                "List all Indigo triggers with their ID, name, enabled state, "
                "and plugin type information."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_list_triggers
        }

        self._tools["enable_trigger"] = {
            "description": "Enable an Indigo trigger by ID or name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trigger_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Trigger ID (number) or name (string)"
                    }
                },
                "required": ["trigger_id"]
            },
            "function": self._tool_enable_trigger
        }

        self._tools["disable_trigger"] = {
            "description": "Disable an Indigo trigger by ID or name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trigger_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Trigger ID (number) or name (string)"
                    }
                },
                "required": ["trigger_id"]
            },
            "function": self._tool_disable_trigger
        }

    # ── Audit tools ───────────────────────────────────────────────────────

        self._tools["audit_home"] = {
            "description": (
                "Run a comprehensive Indigo configuration health check. Returns "
                "devices in error, low-battery devices, stale devices (no change "
                "in 7+ days), empty/null variables, disabled triggers and schedules, "
                "and automation counts. Use this for a quick health overview."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_audit_home
        }
        self._tools["find_devices_in_error"] = {
            "description": "Return all Indigo devices currently in an error or fault state.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_find_devices_in_error
        }
        self._tools["find_low_battery"] = {
            "description": (
                "Return all devices with a batteryLevel state below the given "
                "threshold (default 20%). Sorted lowest battery first."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": "Battery % threshold (default 20)"
                    }
                }
            },
            "function": self._tool_find_low_battery
        }
        self._tools["find_stale_devices"] = {
            "description": (
                "Return enabled devices whose state has not changed in more than "
                "N days (default 7). Helps identify dead or forgotten hardware."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "number",
                        "description": "Inactivity threshold in days (default 7)"
                    }
                }
            },
            "function": self._tool_find_stale_devices
        }
        self._tools["audit_variables"] = {
            "description": (
                "Report variables not referenced in any Python script (potentially "
                "unused), and variables with empty, None, or 'null' values."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_audit_variables
        }
        self._tools["dependency_map"] = {
            "description": (
                "Show everything that references a given device or variable. "
                "Returns which Python scripts reference it by ID, plus a full "
                "list of all triggers and action groups (Indigo's API does not "
                "expose their internal conditions, so content filtering is not "
                "possible — the full list is returned for manual review)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Device or variable ID (number) or name (string)"
                    }
                },
                "required": ["entity_id"]
            },
            "function": self._tool_dependency_map
        }
        self._tools["find_conflicts"] = {
            "description": (
                "Detect configuration conflicts in Indigo. Checks for: duplicate "
                "device names, devices sharing the same hardware address, triggers "
                "with duplicate names, Python scripts referencing deleted device/"
                "variable IDs (orphaned refs), and multiple scripts writing to the "
                "same variable (potential race condition)."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_find_conflicts
        }

        # ── Memory tools ───────────────────────────────────────────────────

        self._tools["remember"] = {
            "description": (
                "Store a persistent note under a topic, accessible across future "
                "Claude sessions. Examples: remember(topic='devices', note='Back "
                "door sensor false-positives in direct sunlight') or "
                "remember(topic='energy', note='Bias factor was 1.5 as of April 2026')."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Category for this note (e.g. devices, energy, heating)"
                    },
                    "note": {
                        "type": "string",
                        "description": "The note to store"
                    }
                },
                "required": ["topic", "note"]
            },
            "function": self._tool_remember
        }
        self._tools["recall"] = {
            "description": (
                "Retrieve stored memories. Pass a topic to filter, or omit to "
                "return all memories. Results are newest first."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to filter by (omit for all)"
                    }
                }
            },
            "function": self._tool_recall
        }
        self._tools["recall_topics"] = {
            "description": "List all memory topics and how many notes each has.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_recall_topics
        }
        self._tools["forget"] = {
            "description": "Delete a specific memory entry by its ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "number",
                        "description": "Memory ID to delete (from recall results)"
                    }
                },
                "required": ["memory_id"]
            },
            "function": self._tool_forget
        }

        # ── Script tools ───────────────────────────────────────────────────

        self._tools["read_script"] = {
            "description": (
                "Read the full content of a Python script from the Indigo "
                "Scripts folder."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Script filename (with or without .py)"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_read_script
        }
        self._tools["write_script"] = {
            "description": (
                "Overwrite an existing Python script with new content. A timestamped "
                "backup is created automatically before writing. Use this to fix or "
                "update a script. For new scripts, use create_script instead."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name":    {"type": "string",
                                "description": "Script filename (with or without .py)"},
                    "content": {"type": "string",
                                "description": "Full Python source code"}
                },
                "required": ["name", "content"]
            },
            "function": self._tool_write_script
        }
        self._tools["create_script"] = {
            "description": (
                "Create a new Python script in the Indigo Scripts folder. "
                "Fails if the file already exists — use write_script to update."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name":    {"type": "string",
                                "description": "Script filename (with or without .py)"},
                    "content": {"type": "string",
                                "description": "Full Python source code"}
                },
                "required": ["name", "content"]
            },
            "function": self._tool_create_script
        }
        self._tools["delete_script"] = {
            "description": (
                "Safely archive a Python script (moves to _backups/_archived/). "
                "Does not permanently delete — can be recovered manually."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Script filename to archive"}
                },
                "required": ["name"]
            },
            "function": self._tool_delete_script
        }
        self._tools["list_script_backups"] = {
            "description": "List auto-backups available for a given script.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Script filename"}
                },
                "required": ["name"]
            },
            "function": self._tool_list_script_backups
        }
        self._tools["scaffold_automation_script"] = {
            "description": (
                "Generate and save a complete Python script template to the Indigo "
                "Scripts folder. Pre-fills the standard header, log() helper, and "
                "named constants for any supplied device/variable IDs (names looked "
                "up live). Ready to open in Indigo and add logic. "
                "Fails if the script already exists."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "script_name": {
                        "type": "string",
                        "description": "Filename (with or without .py extension)"
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line description for the file header"
                    },
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Indigo device IDs to include as named constants"
                    },
                    "variable_ids": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Indigo variable IDs to include as named constants"
                    }
                },
                "required": ["script_name"]
            },
            "function": self._tool_scaffold_automation_script
        }

        # ── Event subscription tools ───────────────────────────────────────

        self._tools["subscribe"] = {
            "description": (
                "Subscribe to Indigo device or variable change events. ClaudeBridge "
                "will queue any matching state changes. Use get_events() to poll "
                "the queue. entity_type: 'device', 'variable', or 'all'. "
                "entity_id: specific ID to watch, or omit for all of that type."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["device", "variable", "all"],
                        "description": "Type to watch"
                    },
                    "entity_id": {
                        "type": "number",
                        "description": "Specific device/variable ID (omit for all)"
                    }
                }
            },
            "function": self._tool_subscribe
        }
        self._tools["unsubscribe"] = {
            "description": "Remove an event subscription by its ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "number",
                        "description": "Subscription ID from subscribe()"
                    }
                },
                "required": ["subscription_id"]
            },
            "function": self._tool_unsubscribe
        }
        self._tools["get_events"] = {
            "description": (
                "Drain queued Indigo change events. Pass `since` (Unix timestamp) "
                "to get only events after a previous call. Returns up to `limit` "
                "events (default 50). Requires at least one active subscription."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "since": {
                        "type": "number",
                        "description": "Unix timestamp — only return events after this"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max events to return (default 50)"
                    }
                }
            },
            "function": self._tool_get_events
        }
        self._tools["list_subscriptions"] = {
            "description": "List active event subscriptions and current queue depth.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_list_subscriptions
        }
        self._tools["clear_events"] = {
            "description": "Flush the event queue without returning its contents.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_clear_events
        }

        # ── Home status tools ──────────────────────────────────────────────

        self._tools["home_status"] = {
            "description": (
                "Return a comprehensive snapshot of the home: all devices grouped "
                "by type, key variable values, energy status, active alerts (errors/"
                "low battery), and automation counts. Ideal for a full status report."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_home_status
        }
        self._tools["energy_status"] = {
            "description": (
                "Return a live energy snapshot from SigenEnergyManager device states: "
                "battery SOC, solar generation, grid import/export, tariff, and "
                "related variable values."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_energy_status
        }
        self._tools["heating_status"] = {
            "description": (
                "Return all heating/thermostat device states — RAMSES ESP TRVs "
                "(12 zones), with setpoints, current temperatures, and zone modes."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_heating_status
        }
        self._tools["security_status"] = {
            "description": (
                "Return all contact sensors (open doors/windows), active motion "
                "sensors, and active leak/smoke/CO alerts."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_security_status
        }
        self._tools["home_status_report"] = {
            "description": (
                "Generate a configurable markdown prose report of home status, "
                "suitable for presenting directly to the user. "
                "Specify sections to include (any of: energy, heating, security, "
                "devices, alerts, automation), or omit for the full report. "
                "Example: home_status_report(sections=['energy','alerts'])"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["energy", "heating", "security",
                                     "devices", "alerts", "automation"]
                        },
                        "description": "Sections to include (omit for all)"
                    }
                }
            },
            "function": self._tool_home_status_report
        }

        # ── Energy intelligence tools ──────────────────────────────────────

        self._tools["energy_log_days"] = {
            "description": (
                "Return raw SigenEnergyManager log lines for the last N days "
                "(max 14). Useful for asking Claude to reason about specific "
                "events, decisions, or anomalies."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "number",
                        "description": "Number of days to retrieve (default 3, max 14)"
                    }
                }
            },
            "function": self._tool_energy_log_days
        }
        self._tools["energy_daily_summary"] = {
            "description": (
                "Parse SigenEnergyManager daily log files into per-day kWh totals: "
                "PV generated, grid imported, grid exported, home consumption, "
                "max/min SOC, and overall self-sufficiency percentage."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "number",
                        "description": "Number of days to summarise (default 14, max 90)"
                    }
                }
            },
            "function": self._tool_energy_daily_summary
        }
        self._tools["energy_compare"] = {
            "description": (
                "Compare two energy periods. Default: this week vs last week. "
                "Returns kWh deltas and % changes for PV, import, export, "
                "home consumption, and self-sufficiency."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_days":     {"type": "number",
                                          "description": "Length of period A in days (default 7)"},
                    "period_b_days":     {"type": "number",
                                          "description": "Length of period B in days (default 7)"},
                    "period_b_offset":   {"type": "number",
                                          "description": "Days ago period B ends (default 7)"},
                }
            },
            "function": self._tool_energy_compare
        }

        # ── Plugin Event firing (Indigo eventData mechanism) ──────────────
        self._tools["fire_indigo_event"] = {
            "description": (
                "Fire all Indigo Triggers of type 'Claude Bridge → Claude Event' with "
                "a structured payload. Use this to drive Indigo automations from a Claude "
                "tool call. Inside the user's Trigger actions, the payload is available "
                "as %%eventData:name%%, %%eventData:data%%, %%eventData:source%%. Users "
                "filter on event name via standard Trigger Conditions."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short event name (e.g. 'sunset_routine', 'leak_detected'). "
                                       "Triggers can filter on this via %%eventData:name%%."
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional structured payload. Serialised to JSON and exposed "
                                       "as %%eventData:data%%."
                    },
                    "source": {
                        "type": "string",
                        "description": "Origin label, default 'claude'. Useful when multiple agents "
                                       "or scripts share the event channel."
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_fire_indigo_event
        }

        # ── Trigger firing by ID/name ─────────────────────────────────────
        self._tools["fire_trigger"] = {
            "description": (
                "Execute a single Indigo trigger directly by ID or name "
                "(indigo.trigger.execute). Use this when you want to invoke "
                "a specific trigger's actions without going through the event "
                "system used by fire_indigo_event."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trigger_id": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "description": "Trigger ID (number) or trigger name (string)"
                    }
                },
                "required": ["trigger_id"]
            },
            "function": self._tool_fire_trigger
        }

        # ── Reflector URL ─────────────────────────────────────────────────
        self._tools["get_reflector_url"] = {
            "description": (
                "Return the Indigo Reflector remote-access URL if configured "
                "on this server (indigo.server.getReflectorURL)."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_get_reflector_url
        }

        # ── Folder creation ───────────────────────────────────────────────
        self._tools["create_device_folder"] = {
            "description": (
                "Create a new device folder. Returns the existing folder if one "
                "with the same name already exists (idempotent)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Folder name to create"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_create_device_folder
        }

        self._tools["create_variable_folder"] = {
            "description": (
                "Create a new variable folder. Returns the existing folder if one "
                "with the same name already exists (idempotent)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Folder name to create"
                    }
                },
                "required": ["name"]
            },
            "function": self._tool_create_variable_folder
        }

        # ── Arbitrary Indigo-context Python ───────────────────────────────
        self._tools["execute_indigo_python"] = {
            "description": (
                "Run arbitrary Python in this plugin's Indigo context. Has full "
                "access to the `indigo` module (devices, variables, triggers, "
                "thermostat.setHeatSetpoint, etc). mode='exec' runs a statement "
                "block and returns captured stdout/stderr. mode='eval' evaluates a "
                "single expression and returns its repr in 'value'. ADMIN scope — "
                "treat as arbitrary code execution on the Indigo server."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python source. For 'exec' use print() to surface output."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["exec", "eval"],
                        "description": "exec (default) for statements, eval for a single expression"
                    }
                },
                "required": ["code"]
            },
            "function": self._tool_execute_indigo_python
        }

        # ── Plugin menu item via AppleScript ──────────────────────────────
        self._tools["execute_plugin_menu_item"] = {
            "description": (
                "Click a plugin's menu item under the Indigo client's Plugins menu "
                "(e.g. plugin_name='Zigbee2MQTT Bridge', menu_item_name='Refresh "
                "Device Capabilities'). Uses AppleScript GUI scripting — requires "
                "the Indigo GUI client to be running and System Events permission "
                "granted. ADMIN scope."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {
                        "type": "string",
                        "description": "The name shown under the Plugins menu"
                    },
                    "menu_item_name": {
                        "type": "string",
                        "description": "The menu item label to click"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "osascript timeout in seconds (default 15)"
                    }
                },
                "required": ["plugin_name", "menu_item_name"]
            },
            "function": self._tool_execute_plugin_menu_item
        }

        # ══════════════════════════════════════════════════════════════════
        # v2.5.0 — Extended IOM wrappers (35+ tools)
        # All implementations live in tools/extended_tools/extended_tools_handler.py
        # ══════════════════════════════════════════════════════════════════

        # ── Device CRUD + folder ops ──────────────────────────────────────
        self._tools["delete_device"] = {
            "description": "Permanently delete a device. Destructive — cannot be undone.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}],
                                  "description": "Device ID"}
                },
                "required": ["device_id"]
            },
            "function": self._tool_delete_device
        }
        self._tools["duplicate_device"] = {
            "description": "Duplicate a device. Optional new_name — Indigo defaults to 'Copy of <name>'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}],
                                  "description": "Source device ID"},
                    "new_name":  {"type": "string", "description": "Optional name for the copy"}
                },
                "required": ["device_id"]
            },
            "function": self._tool_duplicate_device
        }
        self._tools["move_device_to_folder"] = {
            "description": "Move a device to a different folder. folder_id=0 means root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "folder_id": {"anyOf": [{"type": "number"}, {"type": "string"}],
                                  "description": "Target folder ID (0 = root)"}
                },
                "required": ["device_id", "folder_id"]
            },
            "function": self._tool_move_device_to_folder
        }
        self._tools["enable_device"] = {
            "description": ("Enable or disable a device's communication. NOT the same as on/off "
                            "— this controls whether Indigo polls/listens to the device at all."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "value":     {"type": "boolean",
                                  "description": "True to enable, False to disable (default True)"}
                },
                "required": ["device_id"]
            },
            "function": self._tool_enable_device
        }
        self._tools["rename_device"] = {
            "description": "Rename a device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "new_name":  {"type": "string", "description": "New device name"}
                },
                "required": ["device_id", "new_name"]
            },
            "function": self._tool_rename_device
        }
        self._tools["device_toggle"] = {
            "description": "Toggle on/off state. Auto-detects dimmer/relay/speedcontrol.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["device_id"]
            },
            "function": self._tool_device_toggle
        }
        self._tools["dimmer_brighten_by"] = {
            "description": "Increase dimmer brightness by N percent. Clamps at 100.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "amount":    {"type": "number", "description": "Percent points (1-100)"}
                },
                "required": ["device_id", "amount"]
            },
            "function": self._tool_dimmer_brighten_by
        }
        self._tools["dimmer_dim_by"] = {
            "description": "Decrease dimmer brightness by N percent. Clamps at 0.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "amount":    {"type": "number", "description": "Percent points (1-100)"}
                },
                "required": ["device_id", "amount"]
            },
            "function": self._tool_dimmer_dim_by
        }

        # ── Variable gaps ─────────────────────────────────────────────────
        self._tools["variable_delete"] = {
            "description": "Permanently delete a variable. Destructive — cannot be undone.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variable_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["variable_id"]
            },
            "function": self._tool_variable_delete
        }
        self._tools["variable_move_to_folder"] = {
            "description": "Move a variable to a different folder. folder_id=0 means root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variable_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "folder_id":   {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["variable_id", "folder_id"]
            },
            "function": self._tool_variable_move_to_folder
        }

        # ── Schedule CRUD ─────────────────────────────────────────────────
        self._tools["delete_schedule"] = {
            "description": "Permanently delete a schedule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_delete_schedule
        }
        self._tools["duplicate_schedule"] = {
            "description": "Duplicate a schedule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "new_name":    {"type": "string"}
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_duplicate_schedule
        }
        self._tools["execute_schedule_now"] = {
            "description": ("Execute a schedule immediately. ignore_conditions=True bypasses "
                            "the schedule's own conditions."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id":       {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "ignore_conditions": {"type": "boolean"}
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_execute_schedule_now
        }
        self._tools["schedule_remove_delayed_actions"] = {
            "description": "Remove any pending delayed actions for a schedule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_schedule_remove_delayed_actions
        }
        self._tools["schedule_get_dependencies"] = {
            "description": ("Get dependents of a schedule (which devices/variables it "
                            "references). Useful before deleting."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schedule_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["schedule_id"]
            },
            "function": self._tool_schedule_get_dependencies
        }

        # ── Trigger CRUD ──────────────────────────────────────────────────
        self._tools["delete_trigger"] = {
            "description": "Permanently delete a trigger.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trigger_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["trigger_id"]
            },
            "function": self._tool_delete_trigger
        }
        self._tools["move_trigger_to_folder"] = {
            "description": "Move a trigger to a different folder. folder_id=0 means root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trigger_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "folder_id":  {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["trigger_id", "folder_id"]
            },
            "function": self._tool_move_trigger_to_folder
        }

        # ── Action group CRUD ─────────────────────────────────────────────
        self._tools["delete_action_group"] = {
            "description": "Permanently delete an action group.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_delete_action_group
        }
        self._tools["duplicate_action_group"] = {
            "description": "Duplicate an action group.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "new_name":        {"type": "string"}
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_duplicate_action_group
        }
        self._tools["enable_action_group"] = {
            "description": "Enable or disable an action group.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "value":           {"type": "boolean", "description": "True to enable"}
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_enable_action_group
        }
        self._tools["disable_action_group"] = {
            "description": "Disable an action group (convenience for enable_action_group value=False).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_disable_action_group
        }
        self._tools["action_group_get_dependencies"] = {
            "description": "Get dependents of an action group. Useful before deleting.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_group_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["action_group_id"]
            },
            "function": self._tool_action_group_get_dependencies
        }

        # ── Sprinkler suite ───────────────────────────────────────────────
        self._tools["sprinkler_set_zone"] = {
            "description": "Set the active zone on a sprinkler device (1-based index).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id":  {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "zone_index": {"type": "number", "description": "Zone index (1-based)"}
                },
                "required": ["device_id", "zone_index"]
            },
            "function": self._tool_sprinkler_set_zone
        }
        self._tools["sprinkler_run"] = {
            "description": "Run a sprinkler programme.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_run
        }
        self._tools["sprinkler_stop"] = {
            "description": "Stop the sprinkler.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_stop
        }
        self._tools["sprinkler_pause"] = {
            "description": "Pause the sprinkler.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_pause
        }
        self._tools["sprinkler_resume"] = {
            "description": "Resume a paused sprinkler.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_resume
        }
        self._tools["sprinkler_next_zone"] = {
            "description": "Advance to the next sprinkler zone.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_next_zone
        }
        self._tools["sprinkler_previous_zone"] = {
            "description": "Go back to the previous sprinkler zone.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_sprinkler_previous_zone
        }

        # ── Thermostat fan mode ───────────────────────────────────────────
        self._tools["set_fan_mode"] = {
            "description": "Set thermostat fan mode. mode ∈ {auto, alwaysOn}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "mode":      {"type": "string", "enum": ["auto", "alwaysOn", "always_on"]}
                },
                "required": ["device_id", "mode"]
            },
            "function": self._tool_set_fan_mode
        }

        # ── Speed control ─────────────────────────────────────────────────
        self._tools["speedcontrol_set_index"] = {
            "description": "Set speed index on a speed-control device (0=off, 1=low, 2=med, 3=high).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "index":     {"type": "number"}
                },
                "required": ["device_id", "index"]
            },
            "function": self._tool_speedcontrol_set_index
        }
        self._tools["speedcontrol_increase"] = {
            "description": "Increase speed index by one.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_speedcontrol_increase
        }
        self._tools["speedcontrol_decrease"] = {
            "description": "Decrease speed index by one.",
            "inputSchema": {
                "type": "object",
                "properties": {"device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                "required": ["device_id"]
            },
            "function": self._tool_speedcontrol_decrease
        }

        # ── Server-level tools ────────────────────────────────────────────
        self._tools["server_speak"] = {
            "description": "Speak text through Indigo server (macOS text-to-speech).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "wait": {"type": "boolean", "description": "Block until speech done"}
                },
                "required": ["text"]
            },
            "function": self._tool_server_speak
        }
        self._tools["calculate_sunrise"] = {
            "description": "Sunrise for today (default) or YYYY-MM-DD date_iso.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date_iso": {"type": "string", "description": "Optional YYYY-MM-DD"}
                }
            },
            "function": self._tool_calculate_sunrise
        }
        self._tools["calculate_sunset"] = {
            "description": "Sunset for today (default) or YYYY-MM-DD date_iso.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date_iso": {"type": "string", "description": "Optional YYYY-MM-DD"}
                }
            },
            "function": self._tool_calculate_sunset
        }
        self._tools["get_latitude_longitude"] = {
            "description": "Return the latitude/longitude configured in Indigo preferences.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_get_latitude_longitude
        }
        self._tools["get_web_server_url"] = {
            "description": "Return the local Indigo web server URL.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_get_web_server_url
        }
        self._tools["get_deprecated_elements"] = {
            "description": ("Scan for deprecated Indigo objects. "
                            "include_warnings=True also surfaces warning-level items."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_warnings": {"type": "boolean"}
                }
            },
            "function": self._tool_get_deprecated_elements
        }
        self._tools["remove_all_delayed_actions"] = {
            "description": ("Remove every pending delayed action across all schedules. "
                            "Destructive — confirm with the user first."),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_remove_all_delayed_actions
        }

        # ── Control pages ─────────────────────────────────────────────────
        self._tools["list_control_pages"] = {
            "description": "List all control pages with id/name/folder/etc.",
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_list_control_pages
        }
        self._tools["get_control_page"] = {
            "description": "Return a control page's properties (and controls if available).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page_id": {"anyOf": [{"type": "number"}, {"type": "string"}]}
                },
                "required": ["page_id"]
            },
            "function": self._tool_get_control_page
        }

        # ── Cross-plugin update sweep ─────────────────────────────────────
        self._tools["check_plugin_updates"] = {
            "description": ("Sweep every installed plugin and report which have a "
                            "compatible update available. Single call replaces N "
                            "get_plugin_status calls."),
            "inputSchema": {"type": "object", "properties": {}},
            "function": self._tool_check_plugin_updates
        }

        # ══════════════════════════════════════════════════════════════════
        # v2.6.0 — Plugin-development helpers (7 tools)
        # All implementations live in tools/plugin_dev_tools/plugin_dev_tools_handler.py
        # ══════════════════════════════════════════════════════════════════
        self._tools["plugin_diff_source_vs_installed"] = {
            "description": ("Diff a plugin's source repo bundle against its installed "
                            "bundle. Catches static-asset stale-sync, gutted Packages dir, "
                            "version-bump mismatches and any drift between dev and runtime."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string",
                                    "description": "Plugin display name or .indigoPlugin dir name"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_diff_source_vs_installed
        }
        self._tools["plugin_refresh_deps"] = {
            "description": ("Delete the pip-install success marker so Indigo re-runs "
                            "requirements.txt on next plugin restart. restart=true also "
                            "triggers the restart immediately."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string"},
                    "restart":     {"type": "boolean", "description": "Restart plugin after (default false)"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_refresh_deps
        }
        self._tools["plugin_show_packages_versions"] = {
            "description": ("Walk a plugin's Contents/Packages/*.dist-info and return the "
                            "{name: version} map of every bundled third-party library. "
                            "Useful for diagnosing wrong-version-of-paho-mqtt class bugs."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_show_packages_versions
        }
        self._tools["plugin_validate_xml"] = {
            "description": ("Parse Devices/Actions/Events/MenuItems/PluginConfig XML and "
                            "check Indigo naming rules: state IDs must be camelCase ASCII "
                            "(no underscores), Actions uiPath must have no spaces, "
                            "batteryLevel is reserved."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_validate_xml
        }
        self._tools["plugin_node_check_html"] = {
            "description": ("Run `node --check` on every inline <script> block in any "
                            "HTML file under the plugin's Contents/Resources/. Catches "
                            "stale-paste JS syntax bugs in 50ms per block."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_node_check_html
        }
        self._tools["plugin_lint"] = {
            "description": ("Lint plugin.py against CliveS-plugin conventions: header "
                            "format, log() helper, no bare print(), open() of .py needs "
                            "encoding='utf-8', no hardcoded Indigo version paths, "
                            "subscribeToChanges needs the pluginId loop-guard."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plugin_name": {"type": "string"}
                },
                "required": ["plugin_name"]
            },
            "function": self._tool_plugin_lint
        }
        self._tools["device_history"] = {
            "description": ("Read recent SQL Logger history for one device. Returns "
                            "timestamp + non-null state columns. Far cheaper than "
                            "analyze_historical_data for a focused trend query."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "hours":     {"type": "number", "description": "Lookback in hours (default 24)"},
                    "limit":     {"type": "number", "description": "Max rows (default 500, max 5000)"},
                    "columns":   {"type": "array", "items": {"type": "string"},
                                  "description": "Optional list of column names to return"}
                },
                "required": ["device_id"]
            },
            "function": self._tool_device_history
        }

        # ── Outbound webhook subscription tools (ADMIN; ship dark) ─────────
        self._tools["webhook_create"] = {
            "description": ("Register an OUTBOUND webhook: the home POSTs a signed JSON event to an "
                            "APPROVED external URL when a device/variable condition is met. ADMIN. The "
                            "target must be on the egress allow-list (default-deny — private/LAN ranges "
                            "need an explicit CIDR opt-in). Returns a one-time HMAC signing key — capture "
                            "it. Requires 'Enable Event Webhooks' in the plugin config."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "webhook_url": {"type": "string", "description": "https URL to POST events to (must be allow-listed)"},
                    "entity_type": {"type": "string", "enum": ["device", "variable"], "description": "What to watch"},
                    "conditions": {"type": "object", "description": "Match using bare Indigo state names, e.g. {\"onState\": true}, {\"battery\": {\"lt\": 20}}, or {\"any_change\": true}. Fires on transition INTO match."},
                    "entity_id": {"anyOf": [{"type": "number"}, {"type": "string"}], "description": "Optional specific device/variable id; omit to watch all of the type"},
                    "auth_token": {"type": "string", "description": "Optional extra bearer token sent to the receiver"},
                    "verify_ssl": {"type": "boolean", "description": "Verify the receiver's TLS cert (default true)"},
                    "duration_seconds": {"type": "number", "description": "Optional dwell: condition must hold this long before firing"},
                    "max_fires": {"type": "number", "description": "Optional auto-delete after this many deliveries"},
                    "max_body_bytes": {"type": "number", "description": "Optional per-event body cap (default 65536, max 1048576)"},
                    "description": {"type": "string", "description": "Optional human label"}
                },
                "required": ["webhook_url", "entity_type", "conditions"]
            },
            "function": self._tool_webhook_create
        }
        self._tools["webhook_list"] = {
            "description": ("List outbound webhook subscriptions with delivery-health stats. ADMIN. "
                            "Secrets are redacted (signing key omitted, bearer token shown as ***)."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "Optional: return just this one"}
                }
            },
            "function": self._tool_webhook_list
        }
        self._tools["webhook_delete"] = {
            "description": "Delete an outbound webhook subscription by id. ADMIN.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "description": "The subscription id to remove"}
                },
                "required": ["subscription_id"]
            },
            "function": self._tool_webhook_delete
        }

    # ── Plugin Event dispatch ──────────────────────────────────────────────

    def _tool_fire_indigo_event(self, name: str, data: dict = None, source: str = "claude") -> str:
        """Fire claudeEvent Triggers via the owning plugin instance."""
        if not self.plugin or not hasattr(self.plugin, "fire_claude_event"):
            return safe_json_dumps({
                "error": "Plugin reference unavailable — cannot fire events"
            })
        try:
            result = self.plugin.fire_claude_event(name, data, source)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"fire_indigo_event error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Outbound webhook dispatch (reach the plugin-owned handler lazily) ───

    def _tool_webhook_create(self, **kwargs) -> str:
        return self._webhook_call("create_subscription", kwargs)

    def _tool_webhook_list(self, subscription_id: str = None) -> str:
        return self._webhook_call("list_subscriptions", {"subscription_id": subscription_id})

    def _tool_webhook_delete(self, subscription_id: str = "") -> str:
        return self._webhook_call("delete_subscription", {"subscription_id": subscription_id})

    def _webhook_call(self, method: str, kwargs: dict) -> str:
        handler = getattr(self.plugin, "webhook_handler", None) if self.plugin else None
        if handler is None:
            return safe_json_dumps({"success": False,
                                    "error": "webhook subsystem not initialised"})
        try:
            return safe_json_dumps(getattr(handler, method)(**kwargs))
        except Exception as e:
            self.logger.error(f"{method} error: {e}")
            return safe_json_dumps({"success": False, "error": str(e)})

    def _tool_fire_trigger(self, trigger_id) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.fire_trigger(trigger_id))
        except Exception as e:
            self.logger.error(f"fire_trigger error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_get_reflector_url(self) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.get_reflector_url())
        except Exception as e:
            self.logger.error(f"get_reflector_url error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_create_device_folder(self, name: str) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.create_device_folder(name))
        except Exception as e:
            self.logger.error(f"create_device_folder error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_create_variable_folder(self, name: str) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.create_variable_folder(name))
        except Exception as e:
            self.logger.error(f"create_variable_folder error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_execute_indigo_python(self, code: str, mode: str = "exec") -> str:
        try:
            return safe_json_dumps(
                self.scripting_shell_handler.execute_indigo_python(code, mode)
            )
        except Exception as e:
            self.logger.error(f"execute_indigo_python error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_execute_plugin_menu_item(
        self,
        plugin_name: str,
        menu_item_name: str,
        timeout: int = 15,
    ) -> str:
        try:
            return safe_json_dumps(
                self.scripting_shell_handler.execute_plugin_menu_item(
                    plugin_name, menu_item_name, timeout
                )
            )
        except Exception as e:
            self.logger.error(f"execute_plugin_menu_item error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ══════════════════════════════════════════════════════════════════════
    # v2.5.0 extended IOM dispatch methods — thin wrappers around
    # extended_tools_handler. Each follows the established try/safe_json_dumps
    # pattern so all errors come through the same channel.
    # ══════════════════════════════════════════════════════════════════════

    def _ext_call(self, method_name: str, *args, **kwargs) -> str:
        """Shared dispatch: call extended_tools_handler.<method_name> and jsonify."""
        try:
            fn = getattr(self.extended_tools_handler, method_name)
            return safe_json_dumps(fn(*args, **kwargs))
        except Exception as e:
            self.logger.error(f"{method_name} error: {e}")
            return safe_json_dumps({"error": str(e), "tool": method_name})

    # Device CRUD ----------------------------------------------------------
    def _tool_delete_device(self, device_id) -> str:
        return self._ext_call("delete_device", device_id)
    def _tool_duplicate_device(self, device_id, new_name: str = None) -> str:
        return self._ext_call("duplicate_device", device_id, new_name=new_name)
    def _tool_move_device_to_folder(self, device_id, folder_id) -> str:
        return self._ext_call("move_device_to_folder", device_id, folder_id)
    def _tool_enable_device(self, device_id, value: bool = True) -> str:
        return self._ext_call("enable_device", device_id, value=value)
    def _tool_rename_device(self, device_id, new_name: str) -> str:
        return self._ext_call("rename_device", device_id, new_name)
    def _tool_device_toggle(self, device_id) -> str:
        return self._ext_call("device_toggle", device_id)
    def _tool_dimmer_brighten_by(self, device_id, amount: int) -> str:
        return self._ext_call("dimmer_brighten_by", device_id, amount)
    def _tool_dimmer_dim_by(self, device_id, amount: int) -> str:
        return self._ext_call("dimmer_dim_by", device_id, amount)

    # Variable gaps --------------------------------------------------------
    def _tool_variable_delete(self, variable_id) -> str:
        return self._ext_call("variable_delete", variable_id)
    def _tool_variable_move_to_folder(self, variable_id, folder_id) -> str:
        return self._ext_call("variable_move_to_folder", variable_id, folder_id)

    # Schedule CRUD --------------------------------------------------------
    def _tool_delete_schedule(self, schedule_id) -> str:
        return self._ext_call("delete_schedule", schedule_id)
    def _tool_duplicate_schedule(self, schedule_id, new_name: str = None) -> str:
        return self._ext_call("duplicate_schedule", schedule_id, new_name=new_name)
    def _tool_execute_schedule_now(self, schedule_id, ignore_conditions: bool = False) -> str:
        return self._ext_call("execute_schedule_now", schedule_id,
                              ignore_conditions=ignore_conditions)
    def _tool_schedule_remove_delayed_actions(self, schedule_id) -> str:
        return self._ext_call("schedule_remove_delayed_actions", schedule_id)
    def _tool_schedule_get_dependencies(self, schedule_id) -> str:
        return self._ext_call("schedule_get_dependencies", schedule_id)

    # Trigger CRUD ---------------------------------------------------------
    def _tool_delete_trigger(self, trigger_id) -> str:
        return self._ext_call("delete_trigger", trigger_id)
    def _tool_move_trigger_to_folder(self, trigger_id, folder_id) -> str:
        return self._ext_call("move_trigger_to_folder", trigger_id, folder_id)

    # Action group CRUD ---------------------------------------------------
    def _tool_delete_action_group(self, action_group_id) -> str:
        return self._ext_call("delete_action_group", action_group_id)
    def _tool_duplicate_action_group(self, action_group_id, new_name: str = None) -> str:
        return self._ext_call("duplicate_action_group", action_group_id, new_name=new_name)
    def _tool_enable_action_group(self, action_group_id, value: bool = True) -> str:
        return self._ext_call("enable_action_group", action_group_id, value=value)
    def _tool_disable_action_group(self, action_group_id) -> str:
        return self._ext_call("disable_action_group", action_group_id)
    def _tool_action_group_get_dependencies(self, action_group_id) -> str:
        return self._ext_call("action_group_get_dependencies", action_group_id)

    # Sprinkler suite ------------------------------------------------------
    def _tool_sprinkler_set_zone(self, device_id, zone_index: int) -> str:
        return self._ext_call("sprinkler_set_zone", device_id, zone_index)
    def _tool_sprinkler_run(self, device_id) -> str:
        return self._ext_call("sprinkler_run", device_id)
    def _tool_sprinkler_stop(self, device_id) -> str:
        return self._ext_call("sprinkler_stop", device_id)
    def _tool_sprinkler_pause(self, device_id) -> str:
        return self._ext_call("sprinkler_pause", device_id)
    def _tool_sprinkler_resume(self, device_id) -> str:
        return self._ext_call("sprinkler_resume", device_id)
    def _tool_sprinkler_next_zone(self, device_id) -> str:
        return self._ext_call("sprinkler_next_zone", device_id)
    def _tool_sprinkler_previous_zone(self, device_id) -> str:
        return self._ext_call("sprinkler_previous_zone", device_id)

    # Thermostat fan mode --------------------------------------------------
    def _tool_set_fan_mode(self, device_id, mode: str) -> str:
        return self._ext_call("set_fan_mode", device_id, mode)

    # Speed control -------------------------------------------------------
    def _tool_speedcontrol_set_index(self, device_id, index: int) -> str:
        return self._ext_call("speedcontrol_set_index", device_id, index)
    def _tool_speedcontrol_increase(self, device_id) -> str:
        return self._ext_call("speedcontrol_increase", device_id)
    def _tool_speedcontrol_decrease(self, device_id) -> str:
        return self._ext_call("speedcontrol_decrease", device_id)

    # Server tools --------------------------------------------------------
    def _tool_server_speak(self, text: str, wait: bool = False) -> str:
        return self._ext_call("server_speak", text, wait=wait)
    def _tool_calculate_sunrise(self, date_iso: str = None) -> str:
        return self._ext_call("calculate_sunrise", date_iso=date_iso)
    def _tool_calculate_sunset(self, date_iso: str = None) -> str:
        return self._ext_call("calculate_sunset", date_iso=date_iso)
    def _tool_get_latitude_longitude(self) -> str:
        return self._ext_call("get_latitude_longitude")
    def _tool_get_web_server_url(self) -> str:
        return self._ext_call("get_web_server_url")
    def _tool_get_deprecated_elements(self, include_warnings: bool = False) -> str:
        return self._ext_call("get_deprecated_elements", include_warnings=include_warnings)
    def _tool_remove_all_delayed_actions(self) -> str:
        return self._ext_call("remove_all_delayed_actions")

    # Control pages -------------------------------------------------------
    def _tool_list_control_pages(self) -> str:
        return self._ext_call("list_control_pages")
    def _tool_get_control_page(self, page_id) -> str:
        return self._ext_call("get_control_page", page_id)

    # Plugin updates ------------------------------------------------------
    def _tool_check_plugin_updates(self) -> str:
        return self._ext_call("check_plugin_updates")

    # ══════════════════════════════════════════════════════════════════════
    # v2.6.0 plugin-development helper dispatch methods
    # ══════════════════════════════════════════════════════════════════════

    def _pd_call(self, method_name: str, *args, **kwargs) -> str:
        """Shared dispatch for plugin_dev_tools_handler — same shape as _ext_call."""
        try:
            fn = getattr(self.plugin_dev_tools_handler, method_name)
            return safe_json_dumps(fn(*args, **kwargs))
        except Exception as e:
            self.logger.error(f"{method_name} error: {e}")
            return safe_json_dumps({"error": str(e), "tool": method_name})

    def _tool_plugin_diff_source_vs_installed(self, plugin_name: str) -> str:
        return self._pd_call("plugin_diff_source_vs_installed", plugin_name)
    def _tool_plugin_refresh_deps(self, plugin_name: str, restart: bool = False) -> str:
        return self._pd_call("plugin_refresh_deps", plugin_name, restart=restart)
    def _tool_plugin_show_packages_versions(self, plugin_name: str) -> str:
        return self._pd_call("plugin_show_packages_versions", plugin_name)
    def _tool_plugin_validate_xml(self, plugin_name: str) -> str:
        return self._pd_call("plugin_validate_xml", plugin_name)
    def _tool_plugin_node_check_html(self, plugin_name: str) -> str:
        return self._pd_call("plugin_node_check_html", plugin_name)
    def _tool_plugin_lint(self, plugin_name: str) -> str:
        return self._pd_call("plugin_lint", plugin_name)
    def _tool_device_history(self, device_id, hours: int = 24,
                             limit: int = 500, columns=None) -> str:
        return self._pd_call("device_history", device_id,
                             hours=hours, limit=limit, columns=columns)

    # ── System / housekeeping dispatch methods ─────────────────────────────

    def _tool_system_health(self) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.system_health())
        except Exception as e:
            self.logger.error(f"system_health error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_python_scripts(self) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.list_python_scripts())
        except Exception as e:
            self.logger.error(f"list_python_scripts error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_orphaned_scripts(self) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.find_orphaned_scripts())
        except Exception as e:
            self.logger.error(f"find_orphaned_scripts error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_orphaned_plugin_data(self) -> str:
        try:
            return safe_json_dumps(self.system_tools_handler.find_orphaned_plugin_data())
        except Exception as e:
            self.logger.error(f"find_orphaned_plugin_data error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_large_files(
        self,
        path: str = "",
        min_mb: float = 10.0,
        max_results: int = 50,
    ) -> str:
        try:
            return safe_json_dumps(
                self.system_tools_handler.find_large_files(path, min_mb, max_results)
            )
        except Exception as e:
            self.logger.error(f"find_large_files error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Schedule / trigger dispatch methods ────────────────────────────────

    def _tool_list_schedules(self) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.list_schedules())
        except Exception as e:
            self.logger.error(f"list_schedules error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_enable_schedule(self, schedule_id) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.enable_schedule(schedule_id))
        except Exception as e:
            self.logger.error(f"enable_schedule error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_disable_schedule(self, schedule_id) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.disable_schedule(schedule_id))
        except Exception as e:
            self.logger.error(f"disable_schedule error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_triggers(self) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.list_triggers())
        except Exception as e:
            self.logger.error(f"list_triggers error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_enable_trigger(self, trigger_id) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.enable_trigger(trigger_id))
        except Exception as e:
            self.logger.error(f"enable_trigger error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_disable_trigger(self, trigger_id) -> str:
        try:
            return safe_json_dumps(self.schedule_control_handler.disable_trigger(trigger_id))
        except Exception as e:
            self.logger.error(f"disable_trigger error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Audit dispatch methods ──────────────────────────────────────────────

    def _emit(self, message: str, progress: float = None, data: dict = None) -> None:
        """
        Helper for tools that want to surface progress notifications.
        Safe to call from any tool — does nothing if no emitter is active
        (e.g. when invoked via direct method call rather than tools/call).
        """
        emitter = getattr(self._emitter_local, "emitter", None)
        if emitter is not None:
            try:
                emitter.emit(message, progress=progress, data=data)
            except Exception:
                pass

    def _tool_audit_home(self) -> str:
        try:
            return safe_json_dumps(self.audit_handler.audit_home())
        except Exception as e:
            self.logger.error(f"audit_home error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_devices_in_error(self) -> str:
        try:
            return safe_json_dumps(self.audit_handler.find_devices_in_error())
        except Exception as e:
            self.logger.error(f"find_devices_in_error error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_low_battery(self, threshold: int = 20) -> str:
        try:
            return safe_json_dumps(self.audit_handler.find_low_battery(threshold))
        except Exception as e:
            self.logger.error(f"find_low_battery error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_stale_devices(self, days: int = 7) -> str:
        try:
            return safe_json_dumps(self.audit_handler.find_stale_devices(days))
        except Exception as e:
            self.logger.error(f"find_stale_devices error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_audit_variables(self) -> str:
        try:
            return safe_json_dumps(self.audit_handler.audit_variables())
        except Exception as e:
            self.logger.error(f"audit_variables error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_dependency_map(self, entity_id: int = None) -> str:
        try:
            return safe_json_dumps(self.audit_handler.dependency_map(entity_id))
        except Exception as e:
            self.logger.error(f"dependency_map error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_find_conflicts(self) -> str:
        try:
            return safe_json_dumps(self.audit_handler.find_conflicts())
        except Exception as e:
            self.logger.error(f"find_conflicts error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Memory dispatch methods ─────────────────────────────────────────────

    def _tool_remember(self, topic: str, note: str) -> str:
        try:
            return safe_json_dumps(self.memory_handler.remember(topic, note))
        except Exception as e:
            self.logger.error(f"remember error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_recall(self, topic: str = None) -> str:
        try:
            return safe_json_dumps(self.memory_handler.recall(topic))
        except Exception as e:
            self.logger.error(f"recall error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_recall_topics(self) -> str:
        try:
            return safe_json_dumps(self.memory_handler.recall_topics())
        except Exception as e:
            self.logger.error(f"recall_topics error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_forget(self, memory_id: int) -> str:
        try:
            return safe_json_dumps(self.memory_handler.forget(memory_id))
        except Exception as e:
            self.logger.error(f"forget error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Script tools dispatch methods ───────────────────────────────────────

    def _tool_read_script(self, name: str) -> str:
        try:
            return safe_json_dumps(self.script_tools_handler.read_script(name))
        except Exception as e:
            self.logger.error(f"read_script error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_write_script(self, name: str, content: str) -> str:
        try:
            return safe_json_dumps(self.script_tools_handler.write_script(name, content))
        except Exception as e:
            self.logger.error(f"write_script error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_create_script(self, name: str, content: str) -> str:
        try:
            return safe_json_dumps(self.script_tools_handler.create_script(name, content))
        except Exception as e:
            self.logger.error(f"create_script error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_delete_script(self, name: str) -> str:
        try:
            return safe_json_dumps(self.script_tools_handler.delete_script(name))
        except Exception as e:
            self.logger.error(f"delete_script error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_script_backups(self, name: str) -> str:
        try:
            return safe_json_dumps(self.script_tools_handler.list_script_backups(name))
        except Exception as e:
            self.logger.error(f"list_script_backups error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_scaffold_automation_script(
        self,
        script_name: str,
        description: str = "",
        device_ids: list = None,
        variable_ids: list = None,
    ) -> str:
        try:
            return safe_json_dumps(
                self.script_tools_handler.scaffold_automation_script(
                    script_name, description, device_ids, variable_ids
                )
            )
        except Exception as e:
            self.logger.error(f"scaffold_automation_script error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Events dispatch methods ─────────────────────────────────────────────

    def _tool_subscribe(self, entity_type: str = "all", entity_id: int = None) -> str:
        try:
            return safe_json_dumps(self.events_handler.subscribe(entity_type, entity_id))
        except Exception as e:
            self.logger.error(f"subscribe error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_unsubscribe(self, subscription_id: int) -> str:
        try:
            return safe_json_dumps(self.events_handler.unsubscribe(subscription_id))
        except Exception as e:
            self.logger.error(f"unsubscribe error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_get_events(
        self,
        since: float = None,
        limit: int = 50,
    ) -> str:
        try:
            return safe_json_dumps(
                self.events_handler.get_events(since, limit)
            )
        except Exception as e:
            self.logger.error(f"get_events error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_list_subscriptions(self) -> str:
        try:
            return safe_json_dumps(self.events_handler.list_subscriptions())
        except Exception as e:
            self.logger.error(f"list_subscriptions error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_clear_events(self) -> str:
        try:
            return safe_json_dumps(self.events_handler.clear_events())
        except Exception as e:
            self.logger.error(f"clear_events error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Home status dispatch methods ────────────────────────────────────────

    def _tool_home_status(self) -> str:
        try:
            return safe_json_dumps(self.home_status_handler.home_status())
        except Exception as e:
            self.logger.error(f"home_status error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_energy_status(self) -> str:
        try:
            return safe_json_dumps(self.home_status_handler.energy_status())
        except Exception as e:
            self.logger.error(f"energy_status error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_heating_status(self) -> str:
        try:
            return safe_json_dumps(self.home_status_handler.heating_status())
        except Exception as e:
            self.logger.error(f"heating_status error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_security_status(self) -> str:
        try:
            return safe_json_dumps(self.home_status_handler.security_status())
        except Exception as e:
            self.logger.error(f"security_status error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_home_status_report(self, sections: list = None) -> str:
        try:
            return safe_json_dumps(
                self.home_status_handler.home_status_report(sections)
            )
        except Exception as e:
            self.logger.error(f"home_status_report error: {e}")
            return safe_json_dumps({"error": str(e)})

    # ── Energy intelligence dispatch methods ────────────────────────────────

    def _tool_energy_log_days(self, days: int = 3) -> str:
        try:
            return safe_json_dumps(self.energy_tools_handler.energy_log_days(days))
        except Exception as e:
            self.logger.error(f"energy_log_days error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_energy_daily_summary(self, days: int = 14) -> str:
        try:
            return safe_json_dumps(self.energy_tools_handler.energy_daily_summary(days))
        except Exception as e:
            self.logger.error(f"energy_daily_summary error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _tool_energy_compare(
        self,
        period_a_days: int = 7,
        period_b_days: int = 7,
        period_b_offset: int = 7,
    ) -> str:
        try:
            return safe_json_dumps(
                self.energy_tools_handler.energy_compare(
                    period_a_days, period_b_days, period_b_offset
                )
            )
        except Exception as e:
            self.logger.error(f"energy_compare error: {e}")
            return safe_json_dumps({"error": str(e)})

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

    def _tool_set_heat_setpoint(self, device_id: int, setpoint: float) -> str:
        """Set heat setpoint tool implementation."""
        try:
            result = self.device_control_handler.set_heat_setpoint(device_id, setpoint)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Set heat setpoint error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_set_cool_setpoint(self, device_id: int, setpoint: float) -> str:
        """Set cool setpoint tool implementation."""
        try:
            result = self.device_control_handler.set_cool_setpoint(device_id, setpoint)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Set cool setpoint error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_set_hvac_mode(self, device_id: int, mode: str) -> str:
        """Set HVAC mode tool implementation."""
        try:
            result = self.device_control_handler.set_hvac_mode(device_id, mode)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Set HVAC mode error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_lock_device(self, device_id: int) -> str:
        """Lock device tool implementation."""
        try:
            result = self.device_control_handler.lock_device(device_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Lock device error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_unlock_device(self, device_id: int, code: str = None) -> str:
        """Unlock device tool implementation."""
        try:
            result = self.device_control_handler.unlock_device(device_id, code=code)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Unlock device error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_set_color(self, device_id: int, red: int = None, green: int = None,
                        blue: int = None, color: str = None,
                        white: int = None, white_temperature: int = None) -> str:
        """Set colour tool implementation. Accepts either a `color` string (hex
        like #FF8000 or a CSS name like 'dodgerblue') or explicit red/green/blue
        channels (0-255). `color` takes precedence when supplied."""
        try:
            if color is not None:
                try:
                    red, green, blue = parse_color(color)
                except ValueError as ce:
                    return safe_json_dumps({"error": str(ce), "success": False})
            if red is None or green is None or blue is None:
                return safe_json_dumps({
                    "error": "Provide either a 'color' string (hex or CSS name) "
                             "or all three of red/green/blue (0-255).",
                    "success": False
                })
            result = self.device_control_handler.set_color(
                device_id, red, green, blue,
                white=white, white_temperature=white_temperature
            )
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Set colour error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_set_fan_speed(self, device_id: int, speed: int) -> str:
        """Set fan speed tool implementation."""
        try:
            result = self.device_control_handler.set_fan_speed(device_id, speed)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Set fan speed error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_request_status_update(self, device_id: int) -> str:
        """Request device status update tool implementation."""
        try:
            result = self.device_control_handler.request_status_update(device_id)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Request status update error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_increase_heat_setpoint(self, device_id: int, delta: float = 0.5) -> str:
        """Increase heat setpoint tool implementation."""
        try:
            result = self.device_control_handler.increase_heat_setpoint(device_id, delta)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Increase heat setpoint error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_decrease_heat_setpoint(self, device_id: int, delta: float = 0.5) -> str:
        """Decrease heat setpoint tool implementation."""
        try:
            result = self.device_control_handler.decrease_heat_setpoint(device_id, delta)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Decrease heat setpoint error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_get_device_by_name(self, name: str) -> str:
        """Get device by name tool implementation."""
        try:
            result = self.data_provider.get_device_by_name(name)
            if result is None:
                return safe_json_dumps({"error": f"No device found matching '{name}'",
                                        "success": False})
            return safe_json_dumps({"success": True, "device": result})
        except Exception as e:
            self.logger.error(f"Get device by name error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_log_message(self, message: str, level: str = "INFO") -> str:
        """Log message tool implementation."""
        try:
            result = self.script_tools_handler.log_message(message, level)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Log message error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_send_notification(
        self,
        title: str,
        message: str,
        priority: str = "0",
        sound: str = "vibrate",
    ) -> str:
        """Send notification tool implementation."""
        try:
            result = self.data_provider.send_notification(title, message, priority, sound)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Send notification error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_send_email(self, recipient: str, subject: str, body: str) -> str:
        """Send email tool implementation."""
        try:
            result = self.data_provider.send_email(recipient, subject, body)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Send email error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

    def _tool_run_script(self, name: str) -> str:
        """Run script tool implementation."""
        try:
            result = self.script_tools_handler.run_script(name)
            return safe_json_dumps(result)
        except Exception as e:
            self.logger.error(f"Run script error: {e}")
            return safe_json_dumps({"error": str(e), "success": False})

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
        state_key: str,
        state_value: str,
        device_types: List[str] = None
    ) -> str:
        """Get devices by state tool implementation."""
        try:
            # Convert flat key/value params to conditions dict, coercing common types
            _val = str(state_value).strip()
            if _val.lower() == "true":
                _coerced = True
            elif _val.lower() == "false":
                _coerced = False
            else:
                try:
                    _coerced = int(_val)
                except ValueError:
                    try:
                        _coerced = float(_val)
                    except ValueError:
                        _coerced = _val
            state_conditions = {state_key: _coerced}
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
        line_count:     int  = 20,
        show_timestamp: bool = True,
        after:          str  = None,
        before:         str  = None,
    ) -> str:
        """Query event log tool implementation."""
        try:
            result = self.log_query_handler.query(
                line_count=line_count,
                show_timestamp=show_timestamp,
                after=after,
                before=before,
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