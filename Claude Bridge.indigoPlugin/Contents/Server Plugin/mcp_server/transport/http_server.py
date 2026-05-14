####################################################################################
# Filename:    http_server.py
# Author:      CliveS & Claude Sonnet 4.6
# Version:     0.1
# Date:        2026-05-14
# Description: Phase 3 — own-port chunked-SSE HTTP server (stub).
####################################################################################
"""
Phase 3 Streaming HTTP Server — DESIGN NOTES (stub, not yet implemented)
=========================================================================

OVERVIEW
--------
This module will host a stdlib ThreadingHTTPServer on a user-configurable port
(default 8179, exposed as ``streaming_port`` in PluginConfig.xml).  It runs
entirely inside the Indigo plugin process, launched via plugin.py's
runConcurrentThread() so the Indigo event loop is never blocked.

The goal is to replace the v2.2 "buffered SSE" technique (where a single IWS
synchronous response dict bundled multiple SSE events into one payload) with
*true* chunked Transfer-Encoding streaming, so progress events from long-running
tools reach the MCP client in real time rather than all at once after completion.

WHY A SEPARATE PORT
-------------------
Indigo Web Server (IWS) plugin handlers must return a single Python dict per
request; there is no hook for writing to the raw socket or flushing partial
responses.  Running our own server on port 8179 gives us direct control of the
socket, so we can call flush() after each ``data:`` SSE frame.

This approach mirrors the ShellyDirect plugin (port 8178), which bypasses IWS
Digest Auth for the same reason:
    /Library/Application Support/Perceptive Automation/
        Indigo 2025.1/Plugins/ShellyDirect.indigoPlugin

ROUTES (mirroring the existing IWS Action endpoints)
-----------------------------------------------------
    POST /mcp/          — JSON-RPC 2.0 MCP dispatch (text/event-stream when streaming)
    GET  /health/       — liveness probe, returns {"status": "ok"}
    GET  /explorer/     — Swagger / tool-explorer HTML page

AUTH
----
Same Bearer-token pool as the IWS path (``IndigoSecrets.py``).  The Authorization
header is validated before any route handler runs; 401 on failure.

CHUNKED STREAMING
-----------------
When the request's Accept header includes ``text/event-stream`` (or the tool is
known to be long-running), the response is sent as:
    Transfer-Encoding: chunked
    Content-Type: text/event-stream

Each progress event is written as an HTTP chunk and flushed immediately so the
client receives it without waiting for the tool to complete.

THREAD LIFECYCLE
----------------
plugin.py will call StreamingHTTPServer.start() from runConcurrentThread().
A threading.Event (stop_event) is used to signal shutdown; stop() sets the event
and calls server.shutdown(), then the thread joins cleanly.  The IWS endpoints
remain fully active — Phase 3 *adds* the streaming path, never replaces it.

TOOLS TO INSTRUMENT (emit progress via self._emit)
---------------------------------------------------
    - historical_analysis
    - audit_home
    - energy_compare
    - vector_store_manager (rebuild)

BACKWARD COMPATIBILITY
----------------------
IWS endpoints continue to work unchanged.  The streaming port is opt-in via
``streaming_enabled`` checkbox in PluginConfig.xml.  Reflector / reverse-proxy
users will need to expose port 8179 in addition to the IWS port.

TODO
----
* Implement ThreadingHTTPServer subclass and BaseHTTPRequestHandler
* Wire auth, route dispatch, and chunked flush logic
* Add streaming_port / streaming_enabled to PluginConfig.xml
* Instrument long-running tools with _emit() progress calls
* Write parity tests (IWS path vs streaming path, same final JSON-RPC result)
* Document endpoint URLs in show_mcp_client_info_menu
* Update README: port-forwarding note + security note on shared Bearer pool
"""


class StreamingHTTPServer:
    """Stub for the Phase 3 own-port chunked-SSE HTTP server.

    Args:
        host:        Interface to bind (e.g. '0.0.0.0' or '127.0.0.1').
        port:        TCP port (default 8179, configured in PluginConfig.xml).
        mcp_handler: Reference to the plugin's MCPHandler instance for dispatch.
        logger:      Indigo plugin logger (indigo.server.log or self.logger).
    """

    def __init__(self, host: str, port: int, mcp_handler, logger):
        self.host = host
        self.port = port
        self.mcp_handler = mcp_handler
        self.logger = logger
        self._server = None
        self._thread = None
        self._stop_event = None  # threading.Event — set by stop() to trigger shutdown

    def start(self) -> None:
        """Start the ThreadingHTTPServer in a daemon thread.

        Called from plugin.py's runConcurrentThread(); must return quickly.
        """
        raise NotImplementedError(
            "TODO: instantiate http.server.ThreadingHTTPServer, bind to "
            "(self.host, self.port), set allow_reuse_address=True, "
            "and launch self._thread = threading.Thread(target=self._server.serve_forever)."
        )

    def stop(self) -> None:
        """Signal the server to stop and join the thread.

        Called from plugin.py's stopConcurrentThread() or plugin shutdown path.
        Sets stop_event, calls server.shutdown(), then joins the thread with a
        reasonable timeout so Indigo's watchdog is not triggered.
        """
        raise NotImplementedError(
            "TODO: set self._stop_event, call self._server.shutdown(), "
            "and self._thread.join(timeout=5)."
        )

    def _serve_request(self, handler) -> None:
        """Dispatch a single HTTP request from the BaseHTTPRequestHandler.

        Validates Bearer token, routes to the appropriate handler method,
        and writes chunked SSE frames or a plain JSON response body.

        Args:
            handler: The http.server.BaseHTTPRequestHandler instance for this
                     request.  Provides .path, .headers, .rfile, .wfile.
        """
        raise NotImplementedError(
            "TODO: implement Bearer auth check, route table dispatch "
            "(/mcp/, /health/, /explorer/), and chunked flush loop for "
            "text/event-stream responses."
        )
