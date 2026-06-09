#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    indigo_mcp_proxy.py
# Description: stdio-to-HTTP proxy for Indigo MCP Server plugin (no OAuth)
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.4
#
# v1.4 (09-06-2026): make the proxy resilient to the two failure modes that
#   survived v1.3 (broken pipe / connection reset / "Missing or invalid
#   Mcp-Session-Id" after idle gaps or an IWS reload).
#   1. Proactive idle-reconnect: if the cached keep-alive has been idle longer
#      than IDLE_RECONNECT_SECONDS it has very likely been closed by IWS, so we
#      drop it and open a fresh connection BEFORE writing. This removes the
#      dominant "first call after a long idle gap" race with zero risk of
#      double-executing a side-effecting call.
#   2. RemoteDisconnected retry: a stale keep-alive often surfaces at
#      getresponse() (the write buffered, then the server returned zero bytes)
#      as http.client.RemoteDisconnected. Zero bytes back means the server never
#      processed the request, so it is safe to retry on a fresh connection even
#      for a non-idempotent tools/call. v1.3 only retried failures raised before
#      the write completed; this closes the after-write-but-not-processed case.
#   3. Transparent session re-handshake: when IWS invalidates our session id the
#      server replies (HTTP 200) with JSON-RPC error -32600 "Missing or invalid
#      Mcp-Session-Id". The proxy now caches the initialize handshake, replays it
#      to mint a fresh session, then replays the original request once — instead
#      of surfacing the error to Claude Code.
#
# v1.3 (09-06-2026): retry a tools/call after a stale keep-alive drop when the
# failure happened BEFORE the request was sent (request never reached the server,
# so it didn't execute — safe to retry on a fresh connection). Fixes the
# intermittent "Connection error (not retried) [Errno 32] Broken pipe / [Errno 54]
# reset" seen on the first MCP call after a long idle gap or a plugin reload.

import sys
import json
import time
import http.client

INDIGO_HOST            = "localhost"
INDIGO_PORT            = 8176
INDIGO_MCP_PATH        = "/message/com.clives.indigoplugin.claudebridge/mcp/"
# BEARER_TOKEN is patched in by the plugin at install time.  The plugin's
# _setup_claude_code_integration() reads the live IWS token from
# <install>/Preferences/secrets.json (with IndigoSecrets.py
# CLAUDEBRIDGE_BEARER_TOKEN as a fallback) and rewrites this line in the
# destination copy at /Library/Application Support/Perceptive
# Automation/Scripts/indigo_mcp_proxy.py.  The placeholder value below is
# deliberately invalid — running this bundled file directly will fail
# authentication, which is the intended behaviour.  The deployed copy is
# chmod 600 by the plugin so the token is not group/world readable.
BEARER_TOKEN           = "REPLACE_AT_INSTALL"
INDIGO_PROTOCOL_VER    = "2025-06-18"

# A persistent keep-alive that has sat idle longer than this is assumed dead
# (IWS closes idle keep-alives), so we reconnect fresh before writing rather
# than risk a write to a half-closed socket. Localhost reconnects are cheap.
IDLE_RECONNECT_SECONDS = 10.0

session_id     = None    # current Mcp-Session-Id (captured from responses)
_connection    = None    # reused persistent HTTP connection
_last_exchange = None    # time.monotonic() of the last completed exchange
_last_init     = None    # cached initialize request, replayed to re-handshake


class _SendFailed(Exception):
    """A connection failure the proxy deliberately did NOT retry: it happened
    after the request was written, on a connection we cannot prove the server
    failed to process, for a non-idempotent method. Replaying could double a
    side effect, so we surface it instead."""


def _get_connection():
    """Return a reusable persistent HTTP connection."""
    global _connection
    if _connection is None:
        # 300s: long-running tools (vector-store warmup, semantic search, a
        # sleeping execute_indigo_python) can exceed a 60s ceiling.
        _connection = http.client.HTTPConnection(INDIGO_HOST, INDIGO_PORT, timeout=300)
    return _connection


def _drop_connection():
    """Close and forget the cached connection (best effort)."""
    global _connection
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None


def _coerce_args(args: dict) -> dict:
    """
    Convert string args that are genuinely structured (JSON arrays/objects) or
    plain numbers to native types, WITHOUT corrupting ordinary strings.

    Deliberately conservative: 'true'/'false'/'null' and other bare words are
    left as strings (a variable value of "true" must stay "true"), and a
    leading-zero / leading-'+' token is left as a string (a code like "0123" is
    not the number 123). Only [..]/{..} JSON and unambiguous numbers are coerced.
    """
    coerced = {}
    for key, val in args.items():
        if isinstance(val, str):
            stripped = val.strip()
            # Structured args some tools expect (lists/objects).
            if stripped[:1] in ('[', '{'):
                try:
                    coerced[key] = json.loads(stripped)
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass
            # Plain integer — but never a leading-zero or leading-'+' form.
            digits = stripped.lstrip("-")
            if (digits.isdigit()
                    and stripped[:1] != "+"
                    and not (len(digits) > 1 and digits[0] == "0")):
                try:
                    coerced[key] = int(stripped)
                    continue
                except ValueError:
                    pass
            # Plain float — only when it actually looks like one ('.'/exponent),
            # so a leading-zero code or an IP address is never turned numeric.
            if any(c in stripped for c in (".", "e", "E")):
                try:
                    coerced[key] = float(stripped)
                    continue
                except ValueError:
                    pass
        coerced[key] = val
    return coerced


# JSON-RPC methods safe to auto-retry after a dropped keep-alive connection —
# they are idempotent. A tools/call must NOT be retried on an ambiguous failure:
# the first attempt may already have executed server-side and replaying it would
# double a side effect (toggle a light twice, fire an event twice, run code
# twice). The RemoteDisconnected case below is the exception — there the server
# returned zero bytes, proving it never processed the request.
_IDEMPOTENT_METHODS = {
    "initialize", "ping", "tools/list",
    "resources/list", "resources/read", "prompts/list", "prompts/get",
}


def _build_headers() -> dict:
    headers = {
        "Content-Type":  "application/json",
        "Accept":        "application/json, text/event-stream",
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Connection":    "keep-alive",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _read_response(resp):
    """
    Read a full MCP HTTP response. Capture any Mcp-Session-Id from the header,
    then parse the body into JSON-RPC messages, handling both plain JSON and the
    server's buffered SSE (text/event-stream) form. The Indigo MCP server buffers
    its SSE body fully before sending (it is not a live progressive stream), so
    reading it in one go loses nothing.

    Returns (messages, emit_lines):
      messages   — list of parsed JSON-RPC dicts (for the caller to inspect,
                   e.g. to detect a -32600 session error)
      emit_lines — the newline-terminated strings to write to stdout verbatim if
                   the caller decides to pass this response straight through
    """
    global session_id
    sid = resp.getheader("Mcp-Session-Id")
    if sid:
        session_id = sid

    content_type = resp.getheader("Content-Type", "")
    messages = []
    emit_lines = []

    if "text/event-stream" in content_type:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    msg = json.loads(payload)
                    messages.append(msg)
                    emit_lines.append(json.dumps(msg) + "\n")
                except json.JSONDecodeError:
                    pass
    else:
        body_str = resp.read().decode("utf-8").strip()
        if body_str:
            try:
                messages.append(json.loads(body_str))
            except json.JSONDecodeError:
                pass
            emit_lines.append(body_str + "\n")

    return messages, emit_lines


def _attempt(body: bytes, headers: dict, method, is_notification: bool):
    """
    Send one JSON-RPC request and read the response, transparently recovering
    from a stale keep-alive drop. Returns (messages, emit_lines). Raises
    _SendFailed for a deliberately-not-retried failure, or the underlying
    exception if even the safe retry fails.
    """
    global _connection, _last_exchange

    # Proactive: a keep-alive idle longer than IDLE_RECONNECT_SECONDS has very
    # likely been closed by IWS. Reconnect fresh BEFORE writing so the common
    # "first call after an idle gap" never lands on a dead socket.
    if (_connection is not None
            and _last_exchange is not None
            and (time.monotonic() - _last_exchange) > IDLE_RECONNECT_SECONDS):
        _drop_connection()

    reused = _connection is not None
    sent = False
    try:
        conn = _get_connection()
        conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
        sent = True
        result = _read_response(conn.getresponse())
        _last_exchange = time.monotonic()
        return result
    except (http.client.HTTPException, OSError) as e:
        _drop_connection()
        # Safe to retry only when the request did NOT execute server-side:
        #   not sent                       — the write never completed
        #   RemoteDisconnected on a reused — server closed an idle keep-alive
        #     connection                     and returned zero bytes, so it never
        #                                     processed the request
        #   idempotent method / notification — replay is harmless anyway
        safe_to_retry = (
            (not sent)
            or is_notification
            or method in _IDEMPOTENT_METHODS
            or (reused and isinstance(e, http.client.RemoteDisconnected))
        )
        if not safe_to_retry:
            raise _SendFailed(
                f"Connection error after the request was sent (not retried — "
                f"'{method}' may have already executed): {e}"
            ) from e
        # One retry on a guaranteed-fresh connection.
        conn = _get_connection()
        conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
        result = _read_response(conn.getresponse())
        _last_exchange = time.monotonic()
        return result


def _is_session_error(messages) -> bool:
    """True if any message is a JSON-RPC -32600 about the session id (the
    'Missing or invalid Mcp-Session-Id' reply after an IWS reload). Other -32600s
    ('Invalid Request', 'Batch requests not supported', 'Unsupported protocol
    version') are genuine and must NOT trigger a re-handshake."""
    for m in messages:
        if not isinstance(m, dict):
            continue
        err = m.get("error")
        if isinstance(err, dict) and err.get("code") == -32600:
            text = str(err.get("message", "")).lower()
            if "session" in text or "mcp-session-id" in text:
                return True
    return False


def _rehandshake() -> bool:
    """
    Mint a fresh MCP session by replaying the cached initialize handshake, used
    to transparently recover after IWS invalidated our session. Returns True if
    a new session id was obtained.
    """
    global session_id
    if _last_init is None:
        return False
    session_id = None  # force a clean initialize
    try:
        _attempt(json.dumps(_last_init).encode("utf-8"),
                 _build_headers(), "initialize", is_notification=False)
    except Exception:
        return False
    if not session_id:  # server returned no new id — give up, surface original error
        return False
    # Complete the handshake. The server ignores this, but it keeps us spec-correct.
    try:
        _attempt(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8"),
                 _build_headers(), "notifications/initialized", is_notification=True)
    except Exception:
        pass
    return True


def _emit(emit_lines, is_notification: bool):
    """Write a passed-through response to stdout (nothing for a notification —
    MCP forbids responding to one)."""
    if is_notification:
        return
    for line in emit_lines:
        sys.stdout.write(line)
    sys.stdout.flush()


def post_message(data: dict):
    """POST a JSON-RPC message to Indigo MCP and write the response to stdout."""
    global _last_init

    # Notifications have no "id" — MCP spec forbids sending them a response.
    is_notification = "id" not in data
    method          = data.get("method")

    # Downgrade protocol version (Claude Code sends newer than Indigo supports)
    # and cache the handshake so we can replay it to recover a lost session.
    if method == "initialize" and "params" in data:
        data["params"]["protocolVersion"] = INDIGO_PROTOCOL_VER
        _last_init = json.loads(json.dumps(data))  # deep copy for later replay

    # Coerce tool arguments: strings → native types (int, float, list)
    if method == "tools/call" and "params" in data:
        data["params"]["arguments"] = _coerce_args(data["params"].get("arguments", {}))

    body = json.dumps(data).encode("utf-8")

    try:
        messages, emit_lines = _attempt(body, _build_headers(), method, is_notification)
    except _SendFailed as e:
        if not is_notification:
            _write_error(data.get("id"), str(e))
        return
    except Exception as e:
        if not is_notification:
            _write_error(data.get("id"), f"Connection error: {e}")
        return

    # Transparent session recovery: the server rejected our stale session id
    # (IWS reloaded, or our session was pruned). Re-handshake with the cached
    # initialize, then replay this request ONCE with the new session id. Only
    # attempted once — if the replay still errors we surface whatever came back.
    if (not is_notification
            and method != "initialize"
            and _is_session_error(messages)
            and _last_init is not None
            and _rehandshake()):
        try:
            messages, emit_lines = _attempt(body, _build_headers(), method, is_notification)
        except _SendFailed as e:
            _write_error(data.get("id"), str(e))
            return
        except Exception as e:
            _write_error(data.get("id"), f"Connection error after re-handshake: {e}")
            return

    _emit(emit_lines, is_notification)


def _write_error(req_id, message: str):
    err = {
        "jsonrpc": "2.0",
        "id":      req_id,
        "error":   {"code": -32603, "message": message},
    }
    sys.stdout.write(json.dumps(err) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        post_message(data)


if __name__ == "__main__":
    main()
