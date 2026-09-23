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
from typing import Any, Dict, Optional

from . import registry
from typing import TYPE_CHECKING

if TYPE_CHECKING:   # type hint only — importing it here would be circular
    from .adapters.indigo_data_provider import IndigoDataProvider
from .common.arg_coercion import coerce_to_schema
from .common.json_encoder import safe_json_dumps
from .common.tool_cache import ToolCache
from .common.entity_index import EntityIndexManager
from .handlers.list_handlers import ListHandlers
from .security import (RateLimiter, RateLimitExceeded, ScopeManager, ScopeDenied,
                       delete_gate, DeleteDenied)
from .tools.action_control import ActionControlHandler
from .tools.device_control import DeviceControlHandler
from .tools.get_devices_by_type import GetDevicesByTypeHandler
from .tools.log_query import LogQueryHandler
from .tools.plugin_control import PluginControlHandler
from .tools.search_entities import SearchEntitiesHandler
from .tools.variable_control import VariableControlHandler
from .tools.system_tools import SystemToolsHandler
from .tools.schedule_control import ScheduleControlHandler
from .tools.audit import AuditHandler
from .tools.script_tools import ScriptToolsHandler
from .tools.home_status import HomeStatusHandler
from .tools.energy_tools import EnergyToolsHandler
from .tools.scripting_shell import ScriptingShellHandler
from .tools.extended_tools import ExtendedToolsHandler
from .tools.plugin_dev_tools import PluginDevToolsHandler
from .tools.automation_detail import AutomationDetailHandler
from .adapters.indidb import IndiDbStructureStore
from .external_tools import ExternalToolManager, manifest_fingerprint
from .security.scope_manager import register_dynamic_scope, unregister_dynamic_scopes
from .security.secret_redactor import SecretRedactor


class MCPHandler:
    """Handles MCP protocol requests through Indigo IWS."""
    
    # MCP Protocol version we support
    PROTOCOL_VERSION = "2025-06-18"

    # This plugin's own id — never a provider to itself (v2.26.0).
    SELF_PLUGIN_ID = "com.clives.indigoplugin.claudebridge"
    # tools/list checks for a new, changed or vanished provider manifest at
    # most this often (one stat() per installed bundle).
    EXTERNAL_RESCAN_MIN_INTERVAL = 60.0

    # Which tools scrub or redact a failure, which refresh the search index,
    # which are gated deletes, which are cached — all of it is declared on each
    # tool in mcp_server/toolsets/ and read from mcp_server/registry.py. Nothing
    # here repeats it. A plugin-provided tool is not in the registry, so it gets
    # the plain defaults: its errors pass through, it is never cached.

    def __init__(
        self,
        data_provider: "IndigoDataProvider",
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
        self._secret_redactor: Optional[SecretRedactor] = None   # built on first failure

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
        # In-memory entity index behind search_entities, rebuilt every 300 s.
        self.entity_index_manager = EntityIndexManager(
            data_provider=data_provider,
            logger=self.logger,
            update_interval=300,  # 5 minutes
        )

        # The empty index is created synchronously so handlers wire up fine,
        # but the initial load (an IOM walk of every entity) runs on a daemon
        # thread so a restart does not leave the MCP endpoint routable but
        # blocked. See EntityIndexManager.start_async(). v2.6.2 fix.
        self.entity_index_manager.start_async()

        # Initialize handlers
        self._init_handlers()

        # Register tools and resources. Every built-in tool comes from the
        # registry: one decorated function per tool in mcp_server/toolsets/.
        self._tools = self._build_tools()
        self._resources = {}
        self._register_resources()

        # Deny-by-default self-check. Every registry tool carries a scope by
        # construction, so this now guards the one way a gap can still open:
        # something in _tools that did not come from the registry.
        self.scope_manager.audit_classification(list(self._tools.keys()))

        # Plugin-provided tools (v2.26.0): other plugins' manifests, registered
        # AFTER the audit so the audit judges the built-in set, and each
        # external tool is classified read/write as it is registered.
        self._builtin_tool_names = frozenset(self._tools)
        self.external_tools = ExternalToolManager(
            logger=self.logger,
            self_plugin_id=self.SELF_PLUGIN_ID,
            write_gate_supplier=self._external_writes_allowed,
        )
        self._external_lock        = threading.Lock()
        self._external_fingerprint = None
        self._external_checked_at  = 0.0
        try:
            self.refresh_external_tools()
        except Exception as _ext_e:
            self.logger.error(f"\t❌ Plugin-provided tool scan failed: {_ext_e}")

        self.logger.info(f"\t🚀 Claude Bridge ready ({len(self._tools)} tools, {len(self._resources)} resources)")
        self.logger.info("\t🌐 Endpoint: /message/com.clives.indigoplugin.claudebridge/mcp/")
        
    def _init_handlers(self):
        """Initialize all handler instances."""
        # Search handler over the in-memory entity index
        self.search_handler = SearchEntitiesHandler(
            data_provider=self.data_provider,
            entity_index=self.entity_index_manager.get_entity_index(),
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
        self.script_tools_handler = ScriptToolsHandler(
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
        # Read-only view of the .indiDb for action steps / conditions the
        # IOM never exposes. The lambda defers getDbFilePath() to first use
        # (and lets tests substitute a fixture path).
        self.indidb_store = IndiDbStructureStore(
            db_path_supplier=self._get_db_file_path,
            logger=self.logger,
        )
        self.automation_detail_handler = AutomationDetailHandler(
            data_provider=self.data_provider,
            structure_store=self.indidb_store,
            log_query_handler=self.log_query_handler,
            logger=self.logger,
        )

    def _build_tools(self) -> Dict[str, Dict[str, Any]]:
        """The tools/list entries for every registry tool, each with a function
        that calls the tool with this handler as its context."""
        return {name: {"description": spec.description,
                       "inputSchema": spec.input_schema,
                       "function": self._tool_function(spec)}
                for name, spec in registry.load().items()}

    def _tool_function(self, spec: "registry.ToolSpec"):
        """Wrap one registry tool: call it with this handler as ctx, serialise a
        dict result, and turn an exception into a failure payload (after logging
        it) so it flows through the same error handling as a returned error."""
        def _call(**args):
            try:
                result = spec.func(self, **args)
            except Exception as exc:
                self.logger.error(f"{spec.name} error: {type(exc).__name__}: {exc}")
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            return result if isinstance(result, str) else safe_json_dumps(result)
        _call.__name__ = spec.name
        return _call

    @staticmethod
    def _get_db_file_path():
        """Path of Indigo's active database file (None outside Indigo)."""
        try:
            import indigo
            return indigo.server.getDbFilePath()
        except Exception:
            return None

    def stop(self):
        """Stop the MCP handler and cleanup resources."""
        if self.entity_index_manager:
            self.entity_index_manager.stop()

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
        and entity-index status. Cheap to compute — safe to call frequently.
        """
        now = time.time()

        # Snapshot the telemetry under the lock, then aggregate off-lock.
        with self._telemetry_lock:
            call_log = list(self._tool_call_log)
            error_count = self._tool_error_count
        with self._sessions_lock:
            session_count = len(self._sessions)

        # Per-tool latency + payload aggregates over the rolling window
        per_tool: Dict[str, Dict[str, Any]] = {}
        for entry in call_log:
            agg = per_tool.setdefault(entry["name"], {"calls": 0, "errors": 0, "total_ms": 0,
                                                      "max_ms": 0, "total_bytes": 0, "max_bytes": 0})
            agg["calls"]       += 1
            agg["errors"]      += 0 if entry["ok"] else 1
            agg["total_ms"]    += entry["duration_ms"]
            agg["max_ms"]       = max(agg["max_ms"], entry["duration_ms"])
            agg["total_bytes"] += entry.get("bytes", 0)
            agg["max_bytes"]    = max(agg["max_bytes"], entry.get("bytes", 0))
        for name, agg in per_tool.items():
            agg["avg_ms"]    = round(agg["total_ms"] / agg["calls"], 1) if agg["calls"] else 0
            agg["avg_bytes"] = round(agg["total_bytes"] / agg["calls"]) if agg["calls"] else 0

        # Entity index status (best-effort) — read via the manager's own get_stats()
        index_status = {"available": False}
        try:
            if self.entity_index_manager:
                stats = self.entity_index_manager.get_stats()
                index_status["available"]       = True
                index_status["last_update"]     = stats.get("last_update")
                index_status["update_interval"] = stats.get("update_interval")
                index_status["is_running"]      = self.entity_index_manager.is_running
        except Exception as e:
            index_status["error"] = str(e)

        # Exec path. A job past the hard ceiling is WEDGED: it keeps the output
        # capture and every execute_indigo_python / run_script call is refused,
        # so surface it here rather than leaving the operator to infer it from
        # repeated "busy" errors. A job merely running is normal and reported.
        exec_status: Dict[str, Any] = {"wedged": False}
        try:
            from .common import exec_lock
            wedge = exec_lock.wedged_info()
            if wedge:
                exec_status = {"wedged": True, **wedge}
            exec_status["jobs"] = exec_lock.status()
        except Exception as e:
            exec_status["error"] = str(e)

        return {
            "status":           "degraded" if exec_status["wedged"] else "ok",
            "plugin":           "Claude Bridge",
            "protocol_version": self.PROTOCOL_VERSION,
            "exec":             exec_status,
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
            "entity_index": index_status,
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

            return {
                "status": 200,
                "headers": {
                    "Content-Type": "application/json; charset=utf-8",
                    **extra_headers
                },
                "content": json.dumps(resp)
            }
                
        except Exception:
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
            self.logger.debug("Invalid JSON-RPC message structure")
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
            return self._handle_resources_list(msg_id, params, headers)
        elif method == "resources/read":
            return self._handle_resources_read(msg_id, params, headers)
        
        # Prompt methods (stubs for now)
        elif method == "prompts/list":
            from .prompts import list_prompts
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"prompts": list_prompts()}
            }
        elif method == "prompts/get":
            from .prompts import get_prompt
            p = (params or {})
            result = get_prompt(p.get("name", ""), p.get("arguments") or {})
            if result is None:
                return self._json_error(msg_id, -32602, f"Unknown prompt: {p.get('name')!r}")
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        
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
                    # ONLY what this server can actually honour. There is no
                    # push channel to a client: IWS answers one request with
                    # one plain JSON response, never an open stream. So a
                    # `listChanged` notification can never be sent, and
                    # `logging` (server-initiated notifications/message, plus a
                    # logging/setLevel this server does not implement) can
                    # never be honoured either.
                    #
                    # Advertising them was not harmless. A client told it will
                    # be notified when the tool list changes has no reason to
                    # re-read it — which is exactly why a session connected
                    # before v2.24.0 went on stripping the new `confirm`
                    # argument for hours while the plugin refused calls that
                    # were correctly made (29-08-2026). The honest declaration
                    # makes a client re-read on its own terms instead of
                    # waiting for a message that will never arrive.
                    #
                    # `subscribe: False` STAYS: that is an accurate statement
                    # that resource subscription is unsupported. If a real push
                    # channel is ever added, the claims can come back with it.
                    "capabilities": {
                        "prompts": {},
                        "resources": {"subscribe": False},
                        "tools": {}
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
        self._maybe_rescan_external_tools()
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
        TTL caching of read-only tools and cache invalidation after mutators.
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

        spec = registry.spec_for(tool_name)   # None for a plugin-provided tool

        # ── Irreversible-delete gate ─────────────────────────────────────
        # Sits AFTER the scope check and is independent of it. Admin scope
        # says the caller is trusted; it cannot say anyone meant to destroy
        # this particular object. Central here rather than in each handler so
        # a new delete tool cannot be added without the gate applying.
        try:
            delete_gate.check(tool_name, tool_args)
        except DeleteDenied as dd:
            self.logger.warning(f"⛔ Delete refused for '{tool_name}': {dd}")
            return self._json_error(msg_id, -32099, str(dd))
        if spec is not None and spec.destructive:
            # Consumed by the gate above. The handlers are called with
            # **tool_args and none of them takes a `confirm` parameter, so it
            # has to come out here or every gated delete TypeErrors.
            tool_args = {k: v for k, v in tool_args.items() if k != "confirm"}

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

        # ── Unknown-argument rejection (v2.12.1) ─────────────────────────
        # A misnamed argument must FAIL LOUDLY, never silently vanish: a
        # dropped/unknown kwarg either TypeErrors in the **kwargs call below or
        # — worse, when a client strips non-schema properties before sending —
        # the parameter's DEFAULT silently wins and the tool does the opposite
        # of what the caller asked (live-hit 17-Jul-2026: enable_device called
        # with enable=false ran with value=True and re-enabled the device while
        # reporting success). Name the unknowns AND the valid names in the error.
        props = schema.get("properties") or {}
        if props:
            unknown = [k for k in tool_args if k not in props]
            if unknown:
                return self._json_error(
                    msg_id, -32602,
                    f"Unknown argument(s) for {tool_name}: {', '.join(sorted(unknown))} "
                    f"— valid arguments: {', '.join(sorted(props))}"
                )

        # ── Schema-aware argument coercion (v2.27.3) ─────────────────────
        # Moved here from the proxy, which could not see the schemas and so
        # turned a string property's "21.50" into 21.5 and '{"a":1}' into a
        # dict. A property declared as a string now gets exactly what was sent.
        tool_args = coerce_to_schema(tool_args, props)

        start = time.time()
        ok = False
        cache_hit = False
        resp_bytes = 0
        try:
            # Cache-aware dispatch — only for tools in the read allow-list
            def _compute():
                return self._tools[tool_name]["function"](**tool_args)

            # Tools return an {"error": ...} payload instead of raising, so the
            # cache must NOT store an error result (it would be replayed as a
            # "hit" for the full TTL). cache_ok gates storage on a healthy result.
            result, cache_hit = self.tool_cache.get_or_compute(
                tool_name, tool_args, _compute, no_cache=no_cache,
                cache_ok=self._result_ok,
            )
            # A result that carries an error is a FAILED call. The earlier
            # except-only handling never saw it (the tool swallowed its own
            # exception and returned an error dict), so telemetry counted it as a
            # success and the sensitive-tool scrub never fired. Correct both here.
            ok = self._result_ok(result)
            if not ok:
                with self._telemetry_lock:
                    self._tool_error_count += 1
                if spec is not None and spec.redact:
                    result = self._redact_error_result(result)
                elif spec is not None and spec.sensitive:
                    result = self._scrub_error_result(result)
            # Payload size — the real cost driver is how much the CLIENT has to
            # read, not server latency; surfaced per-tool via /health.
            resp_bytes = len(result) if isinstance(result, (str, bytes)) else 0

            # Mutating tools invalidate related cache buckets
            if not cache_hit:
                dropped = self.tool_cache.invalidate_for_tool(tool_name)
                if dropped:
                    self.logger.debug(
                        f"Cache: dropped {dropped} entries after {tool_name}"
                    )
                # If the tool changed entity STRUCTURE (added/removed/renamed a
                # device/variable/action, or ran arbitrary code), refresh the
                # search index now instead of waiting up to update_interval.
                if spec is not None and spec.refresh_search and self.entity_index_manager:
                    self.entity_index_manager.refresh_async()

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
            return response

        except Exception as e:
            with self._telemetry_lock:
                self._tool_error_count += 1
            self.logger.error(f"Tool {tool_name} error: {e}")
            # Don't echo a secret-bearing tool's raw exception back to the client
            # (the response can travel over the reflector). Full detail is logged
            # above; the client gets a generic pointer to the log.
            if spec is not None and spec.redact:
                detail = self._redact_error_text(str(e))
            elif spec is not None and spec.sensitive:
                detail = "see the Claude Bridge event log for details"
            else:
                detail = str(e)
            return self._json_error(
                msg_id, -32603, f"Tool '{tool_name}' execution failed: {detail}"
            )
        finally:
            duration_ms = int((time.time() - start) * 1000)
            # deque(maxlen) self-trims; append is atomic but lock anyway so the
            # health snapshot never reads a torn list.
            with self._telemetry_lock:
                self._tool_call_log.append({
                    "name":        tool_name,
                    "duration_ms": duration_ms,
                    "ok":          ok,
                    "cache_hit":   cache_hit,
                    "bytes":       resp_bytes,
                    "ts":          time.time(),
                })

    @staticmethod
    def _result_ok(result: Any) -> bool:
        """True if a tool result string does NOT represent an error.

        Tool wrappers return safe_json_dumps({"error":..,"success":False}) on
        failure instead of raising, so the dispatch layer must inspect the
        payload — otherwise error results get cached and replayed for the full
        TTL, counted as successes in telemetry, and (for sensitive tools) leak
        raw error text the except-branch scrub was meant to strip.
        """
        if not isinstance(result, str):
            return True
        s = result.lstrip()
        if not s.startswith("{"):
            return True
        try:
            obj = json.loads(result)
        except (ValueError, TypeError):
            return True
        if not isinstance(obj, dict):
            return True
        if obj.get("success") is False:
            return False
        # A top-level "error" without an explicit success:True also means failure.
        if "error" in obj and obj.get("success") is not True:
            return False
        return True

    @staticmethod
    def _scrub_error_result(result: Any) -> str:
        """Replace a sensitive tool's raw error text with a generic pointer.

        The real error is already logged server-side by the tool wrapper; only
        the client copy (which can travel over the reflector) is scrubbed.
        """
        try:
            obj = json.loads(result) if isinstance(result, str) else {}
        except (ValueError, TypeError):
            obj = {}
        if not isinstance(obj, dict):
            obj = {}
        # Build from a WHITELIST rather than overwriting two keys of the original.
        # These tools' failure payloads carry `traceback` (whose last line is the
        # very error text being scrubbed, plus code context), `stderr`, `stdout`
        # and, for run_script, the full script path — so a scrub that only
        # replaced `error` shipped the same secret by another name, and more of
        # it than the exception path ever exposed.
        scrubbed = {
            "success": False,
            "error":   "see the Claude Bridge event log for details",
        }
        # Carried through deliberately: control-flow flags a client needs to act
        # on (a busy refusal must still say WHICH job to collect), none of which
        # can hold tool output or credentials.
        for key in ("timed_out", "busy", "wedged", "wedged_since", "status", "job_id",
                    "running_job_id", "elapsed_seconds"):
            if key in obj:
                scrubbed[key] = obj[key]
        return safe_json_dumps(scrubbed)

    def _get_secret_redactor(self) -> SecretRedactor:
        """Build the redactor on first use. Paths are derived from the running
        server, never typed: IndigoSecrets.py sits at the Perceptive Automation
        root, secrets.json under the versioned folder's Preferences."""
        if self._secret_redactor is None:
            import indigo
            install = indigo.server.getInstallFolderPath()
            plugin = self.plugin

            def _plugin_prefs():
                prefs = getattr(plugin, "pluginPrefs", None) if plugin else None
                return dict(prefs) if prefs else {}

            self._secret_redactor = SecretRedactor(
                secrets_py_path=os.path.join(os.path.dirname(install), "IndigoSecrets.py"),
                iws_secrets_path=os.path.join(install, "Preferences", "secrets.json"),
                extra_values=_plugin_prefs,
            )
        return self._secret_redactor

    def _redact_error_result(self, result: Any) -> str:
        """Keep a code-running tool's failure output, minus every known secret
        value. Fails closed: any problem loading the values or parsing the
        result falls back to the whole-payload scrub."""
        try:
            values = self._get_secret_redactor().load()
            obj = json.loads(result) if isinstance(result, str) else result
            if not isinstance(obj, dict):
                raise ValueError("failure payload is not a JSON object")
            return safe_json_dumps(SecretRedactor.redact_obj(obj, values))
        except Exception as exc:
            self.logger.warning(
                f"Error redaction unavailable ({type(exc).__name__}); "
                f"returning the scrubbed form instead"
            )
            return self._scrub_error_result(result)

    def _redact_error_text(self, text: str) -> str:
        """String form of _redact_error_result, for the raised-exception path."""
        try:
            return SecretRedactor.redact_text(text, self._get_secret_redactor().load())
        except Exception:
            return "see the Claude Bridge event log for details"

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
    
    def _resources_scope_denied(self, msg_id, headers):
        """Resources expose the same read-only data as the READ tools, so they
        must require the 'read' scope too — they previously bypassed the gate
        entirely. Returns a JSON-RPC error dict if denied, else None."""
        bearer = self._extract_bearer(headers or {})
        scopes = self.scope_manager.scopes_for_token(bearer)
        if "read" not in scopes:
            self.logger.warning(
                f"⛔ Scope denied for resources (token="
                f"'{self.scope_manager.name_for_token(bearer)}', has={sorted(scopes)})"
            )
            return self._json_error(msg_id, -32099,
                                    "Resource access requires 'read' scope")
        return None

    def _handle_resources_list(
        self,
        msg_id: Any,
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Handle resources/list request."""
        denied = self._resources_scope_denied(msg_id, headers)
        if denied:
            return denied
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
        params: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Handle resources/read request."""
        denied = self._resources_scope_denied(msg_id, headers)
        if denied:
            return denied
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
    
    # ── Plugin-provided tools (v2.26.0) ─────────────────────────────────

    def _external_writes_allowed(self) -> bool:
        """The Configure checkbox, read at every write call so a save applies
        at once. With no owning plugin (tests) writes are allowed."""
        if self.plugin is None:
            return True
        return bool(getattr(self.plugin, "external_tools_allow_writes", True))

    def refresh_external_tools(self, plugin_list=None) -> Dict[str, Any]:
        """Re-read every provider manifest and rebuild the external entries in
        the registry. The registry dict is REBOUND whole rather than mutated,
        so a tools/list iterating the old dict on the dispatch thread never
        sees a change under its feet. Returns what changed."""
        with self._external_lock:
            entries   = self.external_tools.rescan(self._builtin_tool_names, plugin_list=plugin_list)
            old_names = [n for n, t in self._tools.items() if t.get("external_provider")]
            unregister_dynamic_scopes(old_names)
            new_tools = {n: t for n, t in self._tools.items() if not t.get("external_provider")}
            for name, entry in entries.items():
                register_dynamic_scope(name, "write" if entry.get("write") else "read")
                new_tools[name] = entry
            self._tools = new_tools
            try:
                self._external_fingerprint = manifest_fingerprint(
                    self.SELF_PLUGIN_ID, plugin_list=plugin_list)
            except Exception:
                self._external_fingerprint = None
            self._external_checked_at = time.time()
        providers = self.external_tools.provider_ids()
        removed   = sorted(set(old_names) - set(entries))
        if entries:
            prefixes = ", ".join(sorted({m.prefix for m in self.external_tools.manifests}))
            self.logger.info(f"\t🔌 Plugin-provided tools: {len(entries)} from "
                             f"{len(providers)} provider(s) — {prefixes}")
        elif old_names:
            self.logger.info("\t🔌 Plugin-provided tools: none — the last provider has gone")
        else:
            self.logger.debug("\t🔌 Plugin-provided tools: none found")
        # A provider is only known after discovery, so the owning plugin
        # subscribes to each one's "mcp_tools_updated" broadcast from here.
        if self.plugin is not None and hasattr(self.plugin, "subscribe_to_provider_broadcasts"):
            try:
                self.plugin.subscribe_to_provider_broadcasts(providers)
            except Exception as exc:
                self.logger.warning(f"\t⚠️  Provider broadcast subscription failed: {exc}")
        return {"tools": sorted(entries), "providers": providers, "removed": removed}

    def _maybe_rescan_external_tools(self) -> None:
        """On tools/list: if a manifest appeared, vanished or changed since the
        last look, rescan. One stat() per installed bundle, at most once per
        EXTERNAL_RESCAN_MIN_INTERVAL, on the dispatch thread — no watcher
        thread, nothing to stop, and a new provider shows up on the next
        session's first listing."""
        if getattr(self, "external_tools", None) is None:
            return
        now = time.time()
        if now - self._external_checked_at < self.EXTERNAL_RESCAN_MIN_INTERVAL:
            return
        self._external_checked_at = now
        try:
            fp = manifest_fingerprint(self.SELF_PLUGIN_ID)
        except Exception:
            return
        if fp != self._external_fingerprint:
            try:
                self.refresh_external_tools()
            except Exception as exc:
                self.logger.error(f"\t❌ Plugin-provided tool rescan failed: {exc}")

    def _register_resources(self):
        """Register all available resources."""
        # Device resources
        self._resources["indigo://devices"] = {
            "name": "Devices",
            "description": "List all Indigo devices",
            "function": self._resource_list_devices
        }

        # Live event-log tail as a readable resource (server-wide, all plugins).
        self._resources["indigo://logs/recent"] = {
            "name": "Recent event log",
            "description": "The last 200 Indigo event-log lines (all plugins), newest last",
            "function": self._resource_recent_logs
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

        # Automation resources. Triggers and schedules were reachable only
        # through tools, so a client had a stable read path for the objects it
        # could NOT mutate and none for the ones it could. These reuse the same
        # handlers as the tools — a resource that renders automations its own
        # way is a second contract to keep in step.
        self._resources["indigo://triggers"] = {
            "name": "Triggers",
            "description": "List all Indigo triggers",
            "function": self._resource_list_triggers
        }

        self._resources["indigo://triggers/{trigger_id}"] = {
            "name": "Trigger",
            "description": "Full definition of one trigger: event, conditions and action steps",
            "function": self._resource_get_trigger
        }

        self._resources["indigo://schedules"] = {
            "name": "Schedules",
            "description": "List all Indigo schedules, with each one's next run time",
            "function": self._resource_list_schedules
        }

        self._resources["indigo://schedules/{schedule_id}"] = {
            "name": "Schedule",
            "description": "Full definition of one schedule: timing, conditions and action steps",
            "function": self._resource_get_schedule
        }
    
    # Resource implementation methods
    def _resource_list_devices(self) -> str:
        """List all devices resource."""
        try:
            devices = self.list_handlers.list_all_devices()
            return safe_json_dumps(devices)
        except Exception as e:
            self.logger.error(f"Resource list devices error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _resource_recent_logs(self) -> str:
        """Recent Indigo event-log lines (server-wide) as a readable resource.

        Backed by indigo.server.getEventLogList — the same proven API query_event_log
        uses — so no fragile live-broadcast subscription. TimeStamp is a LOCAL naive
        datetime (not JSON-serialisable), so it's formatted to a string here. TypeVal:
        1=Error, 3=Warning, 8=Info.
        """
        import indigo
        _LEVELS = {1: "Error", 3: "Warning", 8: "Info"}
        try:
            rows = indigo.server.getEventLogList(returnAsList=True, lineCount=200)
            lines = []
            for r in rows:
                ts = r.get("TimeStamp")
                lines.append({
                    "time":    ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts),
                    "source":  r.get("TypeStr", ""),
                    "level":   _LEVELS.get(r.get("TypeVal"), str(r.get("TypeVal", ""))),
                    "message": r.get("Message", ""),
                })
            return safe_json_dumps({"count": len(lines), "lines": lines})
        except Exception as e:
            self.logger.error(f"Resource recent logs error: {e}")
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
    
    def _resource_list_triggers(self) -> str:
        """List triggers — same source as the list_triggers tool."""
        try:
            return safe_json_dumps(self.schedule_control_handler.list_triggers())
        except Exception as e:
            self.logger.error(f"Resource list triggers error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _resource_get_trigger(self, trigger_id: str) -> str:
        """One trigger, through the same renderer as get_automation.

        Scripts are included, as they are for the tool's default. A resource is
        a read, and a caller that fetched a trigger to find out what it does is
        not helped by a body with the body left out.
        """
        try:
            return safe_json_dumps(self.automation_detail_handler.get_details(
                "trigger", int(trigger_id), include_scripts=True))
        except Exception as e:
            self.logger.error(f"Resource get trigger error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _resource_list_schedules(self) -> str:
        """List schedules — same source as the list_schedules tool."""
        try:
            return safe_json_dumps(self.schedule_control_handler.list_schedules())
        except Exception as e:
            self.logger.error(f"Resource list schedules error: {e}")
            return safe_json_dumps({"error": str(e)})

    def _resource_get_schedule(self, schedule_id: str) -> str:
        """One schedule, through the same renderer as get_automation."""
        try:
            return safe_json_dumps(self.automation_detail_handler.get_details(
                "schedule", int(schedule_id), include_scripts=True))
        except Exception as e:
            self.logger.error(f"Resource get schedule error: {e}")
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