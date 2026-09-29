#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    protocol_era.py
# Description: The two MCP protocol eras Claude Bridge serves side by side:
#              the 2025-06-18 initialize handshake (legacy) and revision
#              2026-07-28 (modern), where there is no handshake and no session
#              and every request carries its protocol version and client
#              capabilities in params._meta. Pure functions, no Indigo.
# Author:      CliveS & Claude Opus 5.5
# Date:        29-09-2026
# Version:     1.0
#
# Read from the specification source itself (modelcontextprotocol/
# modelcontextprotocol, docs/specification/2026-07-28 and schema/2026-07-28),
# 29-09-2026: basic/versioning, basic/index (_meta, error codes),
# basic/transports/streamable-http (headers, status codes), server/discover,
# server/utilities/caching.

import base64
import binascii
from typing import Any, Dict, Optional, Tuple

MODERN_VERSIONS    = ("2026-07-28",)
LEGACY_VERSION     = "2025-06-18"
# Newest first. A dual-era server names both, as the specification's own
# UnsupportedProtocolVersionError example does. The legacy one is reached
# through initialize, never through per-request _meta.
SUPPORTED_VERSIONS = MODERN_VERSIONS + (LEGACY_VERSION,)

META_PROTOCOL_VERSION    = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO         = "io.modelcontextprotocol/clientInfo"
META_SERVER_INFO         = "io.modelcontextprotocol/serverInfo"

# Codes the specification defines. -32020 to -32099 is reserved for it, and a
# modern server MUST NOT send anything else from that range.
HEADER_MISMATCH              = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
_SPEC_RESERVED               = range(-32099, -32019)      # -32099 .. -32020
_SPEC_DEFINED                = {-32020, -32021, -32022}
# 2025-11-25 and earlier used -32002 for "resource not found". A modern
# server MUST NOT send it; the same failure is -32602 now.
_LEGACY_RESOURCE_NOT_FOUND   = -32002

# The methods a modern client may call here. The rest of the legacy set is
# gone from 2026-07-28: initialize and notifications/initialized (no
# handshake), ping, logging/setLevel. subscriptions/listen is not offered
# (no list-changed channel is advertised), so it is an unknown method too.
MODERN_METHODS = (
    "server/discover",
    "tools/list", "tools/call",
    "resources/list", "resources/read", "resources/templates/list",
    "prompts/list", "prompts/get",
)

# Mcp-Name mirrors this body field, and is required, for these methods.
NAME_FIELD = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}

# Cacheable results MUST carry ttlMs and cacheScope. The lists change only
# when a plugin adds or drops tools, so five minutes; nothing here pushes a
# list-changed notification, so the TTL is what makes a client look again.
# A resource read is live house data, stale at once. Every one is "private":
# the endpoint needs a bearer token, and a shared cache must never serve one
# key's answer to another.
CACHE_TTL_MS = {
    "server/discover":          300_000,
    "tools/list":               300_000,
    "prompts/list":             300_000,
    "resources/list":           300_000,
    "resources/templates/list": 300_000,
    "resources/read":           0,
}
CACHE_SCOPE = "private"

_B64_PREFIX = "=?base64?"
_B64_SUFFIX = "?="


def request_meta(params: Any) -> Optional[Dict[str, Any]]:
    """The request's _meta if it marks a modern request, else None. The
    protocol version key is what distinguishes the eras: a legacy request may
    carry _meta (a progressToken) but never that key."""
    if not isinstance(params, dict):
        return None
    meta = params.get("_meta")
    if isinstance(meta, dict) and META_PROTOCOL_VERSION in meta:
        return meta
    return None


def decode_header_value(value: str) -> Tuple[bool, Optional[str]]:
    """(ok, text) for an Mcp-Name or Mcp-Param-* header. A value between
    =?base64? and ?= is the UTF-8 text Base64-encoded; anything else must be
    plain visible ASCII, space or tab."""
    if value.startswith(_B64_PREFIX) and value.endswith(_B64_SUFFIX) \
            and len(value) >= len(_B64_PREFIX) + len(_B64_SUFFIX):
        inner = value[len(_B64_PREFIX):-len(_B64_SUFFIX)]
        try:
            return True, base64.b64decode(inner, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return False, None
    if all(ch == "\t" or 0x20 <= ord(ch) <= 0x7E for ch in value):
        return True, value
    return False, None


def header_problem(method: str, params: Dict[str, Any], version: str,
                   headers: Dict[str, str]) -> Optional[str]:
    """Why the HTTP headers of a modern request fail validation, or None.
    `headers` has lower-case names. MCP-Protocol-Version and Mcp-Method are
    required on every request, Mcp-Name on tools/call, resources/read and
    prompts/get, and each must match the body."""
    pv = headers.get("mcp-protocol-version")
    if pv is None:
        return "the MCP-Protocol-Version header is missing"
    if pv != version:
        return (f"the MCP-Protocol-Version header {pv!r} does not match the "
                f"body's {version!r}")
    hm = headers.get("mcp-method")
    if hm is None:
        return "the Mcp-Method header is missing"
    if hm != method:
        return f"the Mcp-Method header {hm!r} does not match the body's {method!r}"
    field = NAME_FIELD.get(method)
    if field:
        body_value = params.get(field)
        hn = headers.get("mcp-name")
        if hn is None:
            if body_value is None:
                return None          # the method's own check reports the missing field
            return "the Mcp-Name header is missing"
        ok, decoded = decode_header_value(hn)
        if not ok:
            return "the Mcp-Name header holds characters a header cannot carry"
        if body_value is None or decoded != str(body_value):
            return (f"the Mcp-Name header value {decoded!r} does not match the "
                    f"body's {field} {body_value!r}")
    return None


def decorate_result(method: str, result: Dict[str, Any],
                    server_info: Dict[str, Any]) -> Dict[str, Any]:
    """Add what every modern result carries: resultType, the server's
    identity in _meta, and the caching hints on the cacheable methods."""
    result.setdefault("resultType", "complete")
    meta = result.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    meta[META_SERVER_INFO] = server_info
    result["_meta"] = meta
    if method in CACHE_TTL_MS:
        result.setdefault("ttlMs", CACHE_TTL_MS[method])
        result.setdefault("cacheScope", CACHE_SCOPE)
    return result


def modern_error_code(code: Any) -> Any:
    """The code a modern client should receive for one Claude Bridge sends.
    -32002 becomes -32602, and a code in the specification's reserved range
    that it does not define becomes -32600. Everything else passes."""
    if code == _LEGACY_RESOURCE_NOT_FOUND:
        return -32602
    if isinstance(code, int) and code in _SPEC_RESERVED and code not in _SPEC_DEFINED:
        return -32600
    return code


def is_reserved_refusal(code: Any) -> bool:
    """True for a code Claude Bridge uses for its own refusals (-32099: rate
    limit, scope, delete gate) that a modern client must not receive."""
    return isinstance(code, int) and code in _SPEC_RESERVED and code not in _SPEC_DEFINED
