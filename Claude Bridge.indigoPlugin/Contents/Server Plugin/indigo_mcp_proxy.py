#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    indigo_mcp_proxy.py
# Description: stdio-to-HTTP proxy for Indigo MCP Server plugin (no OAuth)
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.3
#
# v1.3 (09-06-2026): retry a tools/call after a stale keep-alive drop when the
# failure happened BEFORE the request was sent (request never reached the server,
# so it didn't execute — safe to retry on a fresh connection). Fixes the
# intermittent "Connection error (not retried) [Errno 32] Broken pipe / [Errno 54]
# reset" seen on the first MCP call after a long idle gap or a plugin reload.

import sys
import json
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

session_id  = None
_connection = None


def _get_connection():
    """Return a reusable persistent HTTP connection."""
    global _connection
    if _connection is None:
        # 300s: long-running tools (vector-store warmup, semantic search, a
        # sleeping execute_indigo_python) can exceed a 60s ceiling.
        _connection = http.client.HTTPConnection(INDIGO_HOST, INDIGO_PORT, timeout=300)
    return _connection


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
# they are idempotent. A tools/call must NOT be retried: the first attempt may
# already have executed server-side and replaying it would double a side effect
# (toggle a light twice, fire an event twice, run code twice).
_IDEMPOTENT_METHODS = {
    "initialize", "ping", "tools/list",
    "resources/list", "resources/read", "prompts/list", "prompts/get",
}


def _handle_response(resp, is_notification: bool):
    """
    Capture the session id and stream the response to stdout, handling both
    plain JSON and SSE (text/event-stream). Writes nothing for a notification
    (MCP forbids responding to one). Shared by the primary and retry paths so
    SSE is parsed identically in both.
    """
    global session_id
    sid = resp.getheader("Mcp-Session-Id")
    if sid:
        session_id = sid

    content_type = resp.getheader("Content-Type", "")
    if "text/event-stream" in content_type:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    msg = json.loads(payload)
                    if not is_notification:
                        sys.stdout.write(json.dumps(msg) + "\n")
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    pass
    else:
        body_str = resp.read().decode("utf-8").strip()
        if body_str and not is_notification:
            sys.stdout.write(body_str + "\n")
            sys.stdout.flush()


def post_message(data: dict):
    """POST a JSON-RPC message to Indigo MCP and write response to stdout."""
    global _connection

    # Notifications have no "id" — MCP spec forbids sending them a response.
    is_notification = "id" not in data
    method          = data.get("method")

    # Downgrade protocol version (Claude Code sends newer than Indigo supports)
    if method == "initialize" and "params" in data:
        data["params"]["protocolVersion"] = INDIGO_PROTOCOL_VER

    # Coerce tool arguments: strings → native types (int, float, list)
    if method == "tools/call" and "params" in data:
        data["params"]["arguments"] = _coerce_args(data["params"].get("arguments", {}))

    body = json.dumps(data).encode("utf-8")
    headers = {
        "Content-Type":  "application/json",
        "Accept":        "application/json, text/event-stream",
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Connection":    "keep-alive",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    # Distinguish a SEND failure from a RECEIVE failure so a tools/call can be
    # retried safely after a stale keep-alive drop. `sent` flips True only once
    # conn.request() has written the request to the socket. A failure raised
    # BEFORE that (sent is False) means the request never reached the server —
    # the common case: IWS closed the idle keep-alive, or the plugin was reloaded,
    # and our write hit a dead socket — so the call did NOT execute and is safe to
    # retry for ANY method (a fresh connection is made on the retry). A failure
    # AFTER the send may mean a non-idempotent call already ran, so keep the
    # conservative no-retry there.
    sent = False
    try:
        conn = _get_connection()
        conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
        sent = True
        _handle_response(conn.getresponse(), is_notification)
        return
    except (http.client.HTTPException, OSError) as e:
        _connection = None
        if (not sent) or is_notification or method in _IDEMPOTENT_METHODS:
            try:
                conn = _get_connection()
                conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
                _handle_response(conn.getresponse(), is_notification)
            except Exception as e2:
                if not is_notification:
                    _write_error(data.get("id"), f"Connection error after retry: {e2}")
        elif not is_notification:
            _write_error(
                data.get("id"),
                f"Connection error after the request was sent (not retried — "
                f"'{method}' may have already executed): {e}",
            )
    except Exception as e:
        if not is_notification:
            _write_error(data.get("id"), str(e))


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
