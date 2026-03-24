#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    indigo_mcp_proxy.py
# Description: stdio-to-HTTP proxy for Indigo MCP Server plugin (no OAuth)
# Author:      CliveS & Claude Sonnet 4.6
# Date:        24-03-2026
# Version:     1.1

import sys
import json
import http.client

INDIGO_HOST            = "localhost"
INDIGO_PORT            = 8176
INDIGO_MCP_PATH        = "/message/com.clives.indigoplugin.claudebridge/mcp/"
BEARER_TOKEN           = "eoLRHTH2wgwhuoFIfm2Vsx2i5NdYzFfI1dKWUffkDDY"
INDIGO_PROTOCOL_VER    = "2025-06-18"

session_id  = None
_connection = None


def _get_connection():
    """Return a reusable persistent HTTP connection."""
    global _connection
    if _connection is None:
        _connection = http.client.HTTPConnection(INDIGO_HOST, INDIGO_PORT, timeout=60)
    return _connection


def _coerce_args(args: dict) -> dict:
    """Convert string values that should be numbers or arrays to their native types."""
    coerced = {}
    for key, val in args.items():
        if isinstance(val, str):
            # Try JSON parse first (handles arrays, booleans, quoted numbers)
            stripped = val.strip()
            if stripped and stripped[0] in ('[', '{', 't', 'f', 'n'):
                try:
                    coerced[key] = json.loads(stripped)
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass
            # Plain integer
            if stripped.lstrip("-").isdigit():
                coerced[key] = int(stripped)
                continue
            # Plain float
            try:
                coerced[key] = float(stripped)
                continue
            except ValueError:
                pass
        coerced[key] = val
    return coerced


def post_message(data: dict):
    """POST a JSON-RPC message to Indigo MCP and write response to stdout."""
    global session_id, _connection

    # Downgrade protocol version (Claude Code sends newer than Indigo supports)
    if data.get("method") == "initialize" and "params" in data:
        data["params"]["protocolVersion"] = INDIGO_PROTOCOL_VER

    # Coerce tool arguments: strings → native types (int, float, list, bool)
    if data.get("method") == "tools/call" and "params" in data:
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

    try:
        conn = _get_connection()
        conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
        resp = conn.getresponse()

        # Capture session ID
        sid = resp.getheader("Mcp-Session-Id")
        if sid:
            session_id = sid

        content_type = resp.getheader("Content-Type", "")

        if "text/event-stream" in content_type:
            # SSE stream — each "data: {...}" line is a JSON-RPC message
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        msg = json.loads(payload)
                        sys.stdout.write(json.dumps(msg) + "\n")
                        sys.stdout.flush()
                    except json.JSONDecodeError:
                        pass
        else:
            body_bytes = resp.read()
            body_str   = body_bytes.decode("utf-8").strip()
            if body_str:
                sys.stdout.write(body_str + "\n")
                sys.stdout.flush()

    except (http.client.HTTPException, OSError):
        # Connection dropped — reset and retry once
        _connection = None
        try:
            conn = _get_connection()
            conn.request("POST", INDIGO_MCP_PATH, body=body, headers=headers)
            resp = conn.getresponse()
            body_str = resp.read().decode("utf-8").strip()
            if body_str:
                sys.stdout.write(body_str + "\n")
                sys.stdout.flush()
        except Exception as e:
            _write_error(data.get("id"), f"Connection error: {e}")
    except Exception as e:
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
