#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    indigo_mcp_proxy.py
# Description: stdio-to-HTTP proxy for Indigo MCP Server plugin (no OAuth)
# Author:      CliveS & Claude Opus 5; Claude Opus 5.5 (1.6, 1.7)
# Date:        25-09-2026
# Version:     1.8
#
# v1.8 (25-09-2026): follows the plugin's MCP Streamable HTTP status codes
#   (3.3.0+). A session the server does not know now comes back as HTTP 404,
#   and a missing one as 400, where it used to be 200 with a JSON-RPC -32600;
#   either one re-handshakes and replays the request once, exactly as the
#   -32600 did (still recognised, for an older plugin). A notification is now
#   answered 202 Accepted with no body instead of 200 "{}". After a plugin
#   restart the old session id is still let through until some client
#   initializes, and from then on it gets the 404 and re-handshakes, so the
#   proxy carries on across a restart either way. The web server's scheme,
#   host and port are patched in by the plugin like the token, so an
#   HTTPS-only or non-default-port web server works.
#
# v1.7 (24-09-2026): every request gets a JSON-RPC answer. A reply that parsed
#   as JSON but was not JSON-RPC — the plugin's own 503 "MCP server unavailable"
#   body, a 500 — was passed through verbatim, so the client never saw an answer
#   for its request id and waited until its own timeout. Any HTTP status of 400
#   or more, and any body that is not a JSON-RPC message, now becomes a JSON-RPC
#   error for the pending id. So does a request answered with nothing at all.
#
# v1.6 (23-09-2026): tool arguments pass through UNTOUCHED. The proxy used to
#   convert any string that looked numeric or like JSON, without seeing the
#   tool's schema, so variable_update(value="21.50") stored "21.5" and a JSON
#   string value became a Python dict repr — all reporting success. The plugin
#   (2.27.3+) now converts against each tool's declared schema instead.
#
# v1.5 (04-08-2026): survive the boot race. An MCP client can start before
#   Indigo's web server is listening — most obviously after a Mac reboot, where
#   the app comes up seconds ahead of Indigo. The proxy's POST was refused, it
#   answered the initialize handshake with JSON-RPC -32603, and the client gave
#   up ("Could not attach to MCP server indigo-mcp"). The handshake now waits
#   for IWS to appear, up to BOOT_RETRY_SECONDS, and only while the failure is
#   "nothing is listening yet" — every other failure still surfaces at once.
#   Measured here on 04-08-2026: the app attached at 20:26:44 and IWS answered
#   at 20:27:07, a 23-second gap. Every occurrence of this error (09-07, 25-07,
#   04-08) fell within a minute of a reboot.
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

import errno
import ipaddress
import sys
import json
import ssl
import time
import http.client

# INDIGO_SCHEME, INDIGO_HOST and INDIGO_PORT are patched in by the plugin at
# start-up, like BEARER_TOKEN below, from indigo.server.getWebServerURL(): the
# host stays "localhost" when the web server is on this Mac. These are the
# defaults when it cannot tell.
INDIGO_SCHEME          = "http"
INDIGO_HOST            = "localhost"
INDIGO_PORT            = 8176
INDIGO_MCP_PATH        = "/message/com.clives.indigoplugin.claudebridge/mcp/"
# BEARER_TOKEN is patched in by the plugin at start-up.  The plugin's
# mcp_server/client_setup.py (setup_claude_code_integration) reads the live
# IWS token from
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

# How long the initialize handshake waits for IWS to start listening, and how
# often it re-tries while it waits. Only the handshake waits: a tools/call must
# never stall for the best part of a minute, and by then IWS is up anyway.
# 45s comfortably covers the 23s measured here on a cold boot. Clients apply
# their own attach timeout (Claude Code allows 30s), so the wait cannot hold an
# attach open indefinitely — and a client that does give up is no worse off
# than with the instant failure this replaces.
BOOT_RETRY_SECONDS     = 45.0
BOOT_RETRY_INTERVAL    = 2.0

# errno values meaning "nothing is listening on that port YET", as opposed to a
# request that reached IWS and failed there. Only these are worth waiting out.
_BOOT_ERRNOS = {
    errno.ECONNREFUSED,   # 61 — the ordinary "IWS is not up yet"
    errno.ENETDOWN,       # 50 — network still coming up after a reboot
    errno.ENETUNREACH,    # 51
    errno.EHOSTDOWN,      # 64
    errno.EHOSTUNREACH,   # 65
}

session_id     = None    # current Mcp-Session-Id (captured from responses)
_connection    = None    # reused persistent HTTP connection
_last_exchange = None    # time.monotonic() of the last completed exchange
_last_init     = None    # cached initialize request, replayed to re-handshake


class _HttpError(Exception):
    """The server answered, but not with JSON-RPC — an HTTP-level failure.

    A 401 (the placeholder token was never patched in), a 404 (wrong plugin id
    in the URL) or an IWS 500 all return an HTML or plain-text body. Writing that
    body to stdout would corrupt the client's JSON-RPC stream AND leave the
    pending request id unanswered, so the client waits for a reply that never
    comes. Raising instead turns it into a proper JSON-RPC error for that id.
    """

    def __init__(self, status: int, body: str = "", messages=None):
        self.status   = status
        self.body     = body
        self.messages = messages or []   # any JSON-RPC messages the body held
        hint = ""
        if status == 401:
            hint = (" — the bearer token was rejected. Check that the plugin "
                    "patched a real token into this proxy (Claude Bridge logs "
                    "an error if it could not).")
        elif status == 404:
            hint = (" — not found: the session has expired, or the endpoint is missing. "
                    "Is the Claude Bridge plugin enabled?")
        elif status == 503:
            hint = (" — Claude Bridge is running but its MCP server did not start. "
                    "The Indigo event log says why; reload the plugin once it is fixed.")
        detail = f": {body.strip()[:200]}" if body.strip() else ""
        super().__init__(f"HTTP {status} from Indigo's web server{hint}{detail}")


class _SendFailed(Exception):
    """A connection failure the proxy deliberately did NOT retry: it happened
    after the request was written, on a connection we cannot prove the server
    failed to process, for a non-idempotent method. Replaying could double a
    side effect, so we surface it instead."""


def _is_loopback_host(host: str) -> bool:
    if str(host).lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        return False


def _tls_context() -> ssl.SSLContext:
    """The TLS settings for an HTTPS web server. Over loopback the certificate
    is not checked: Indigo's certificate names the Mac's network name (or is
    self-signed), never "localhost", and a loopback connection never leaves
    this Mac, so there is nobody in the middle for the check to catch. To any
    other host the certificate is verified as normal."""
    context = ssl.create_default_context()
    if _is_loopback_host(INDIGO_HOST):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _get_connection():
    """Return a reusable persistent HTTP connection."""
    global _connection
    if _connection is None:
        # 300s: long-running tools (vector-store warmup, semantic search, a
        # sleeping execute_indigo_python) can exceed a 60s ceiling.
        if INDIGO_SCHEME == "https":
            _connection = http.client.HTTPSConnection(INDIGO_HOST, INDIGO_PORT, timeout=300,
                                                      context=_tls_context())
        else:
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

    status = resp.status

    if "text/event-stream" in content_type:
        done = False
        for raw in resp:
            if done:
                continue          # keep consuming so the response reaches EOF
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    # Do NOT break. An un-drained response leaves the keep-alive
                    # connection mid-message, so the NEXT getresponse() raises
                    # ResponseNotReady after that request has already been sent —
                    # which for a tools/call is reported as "may have already
                    # executed" while its real reply is lost.
                    done = True
                    continue
                try:
                    msg = json.loads(payload)
                    messages.append(msg)
                    emit_lines.append(json.dumps(msg) + "\n")
                except json.JSONDecodeError:
                    pass
        try:
            resp.read()           # belt and braces if the server stopped early
        except Exception:
            pass
    else:
        body_str = resp.read().decode("utf-8").strip()
        if body_str:
            try:
                parsed = json.loads(body_str)
            except json.JSONDecodeError:
                raise _HttpError(status, body_str[:400])
            # "{}" is how a plugin before 3.3.0 acknowledged a notification —
            # nothing to pass on. (3.3.0 answers 202 with no body, which is the
            # empty case above.) Anything else is checked below: only a
            # JSON-RPC message is passed through to stdout. An HTML page, or
            # JSON that is not JSON-RPC, written verbatim corrupts the client's
            # stream AND leaves the pending request id unanswered.
            if not (isinstance(parsed, dict) and not parsed and status < 400):
                messages.append(parsed)
                emit_lines.append(body_str + "\n")

    if status >= 400:
        raise _HttpError(status, _error_text(messages), messages)
    for m in messages:
        if not _is_jsonrpc(m):
            raise _HttpError(status, json.dumps(m)[:400])

    return messages, emit_lines


def _is_jsonrpc(msg) -> bool:
    return isinstance(msg, dict) and msg.get("jsonrpc") == "2.0"


def _error_text(messages) -> str:
    """The most useful line from an error body: a JSON-RPC error message, a
    plain {"error": ...}, or the body itself."""
    for m in messages:
        if not isinstance(m, dict):
            continue
        err = m.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
    return json.dumps(messages[0])[:400] if messages else ""


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


def _is_not_listening(exc) -> bool:
    """True if the exception means nothing is accepting connections on the port
    yet — the boot race — rather than a request that reached IWS and failed."""
    if isinstance(exc, ConnectionRefusedError):
        return True
    return isinstance(exc, OSError) and exc.errno in _BOOT_ERRNOS


def _attempt_initialize(body: bytes, headers: dict):
    """
    _attempt() for the handshake, tolerant of a client that started before
    Indigo's web server. Waits only while the failure is "nothing is listening
    yet" and only up to BOOT_RETRY_SECONDS; anything else (a bad token, an IWS
    500, a hang that exhausts the socket timeout) is raised straight away, so a
    genuine fault still fails fast instead of stalling the attach.
    """
    deadline = time.monotonic() + BOOT_RETRY_SECONDS
    waited   = False
    while True:
        try:
            result = _attempt(body, headers, "initialize", is_notification=False)
        except Exception as e:
            if not _is_not_listening(e) or time.monotonic() >= deadline:
                raise
            if not waited:
                waited = True
                # One line to the client's MCP log so the wait is diagnosable.
                sys.stderr.write(
                    f"indigo_mcp_proxy: nothing listening on "
                    f"{INDIGO_HOST}:{INDIGO_PORT} — waiting up to "
                    f"{BOOT_RETRY_SECONDS:.0f}s for Indigo's web server (boot race)\n"
                )
                sys.stderr.flush()
            _drop_connection()
            time.sleep(BOOT_RETRY_INTERVAL)
            continue
        if waited:
            sys.stderr.write("indigo_mcp_proxy: Indigo's web server answered — attaching\n")
            sys.stderr.flush()
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


def _is_session_expired(exc: "_HttpError") -> bool:
    """True if an HTTP error means our session is gone and a fresh initialize
    will fix it: 404 Not Found for a session the server does not know, or 400
    naming the missing session id (MCP Streamable HTTP). A 404 that is really
    a missing endpoint is harmless here: the re-handshake gets the same 404,
    fails, and the original error is reported."""
    if session_id is None and exc.status == 404:
        return False          # nothing was sent that could have expired
    return exc.status == 404 or (exc.status == 400 and _is_session_error(exc.messages))


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

    body = json.dumps(data).encode("utf-8")
    # Transparent session recovery is for a request whose session the server
    # no longer knows (the plugin restarted, or pruned an idle session).
    can_recover = (not is_notification and method != "initialize"
                   and _last_init is not None)

    try:
        if method == "initialize":
            # The one method allowed to wait for IWS to come up (see v1.5).
            messages, emit_lines = _attempt_initialize(body, _build_headers())
        else:
            messages, emit_lines = _attempt(body, _build_headers(), method, is_notification)
    except _SendFailed as e:
        if not is_notification:
            _write_error(data.get("id"), str(e))
        return
    except _HttpError as e:
        # A 404 for an unknown session, or a 400 for a missing one (v1.8):
        # re-handshake and replay once, as for the older -32600 below.
        if can_recover and _is_session_expired(e) and _rehandshake():
            _replay(data, body, method)
            return
        # Answered, but not with JSON-RPC. Report it against the request id
        # rather than as a connection fault — the connection was fine.
        if not is_notification:
            _write_error(data.get("id"), str(e))
        return
    except Exception as e:
        if not is_notification:
            _write_error(data.get("id"), f"Connection error: {e}")
        return

    if not is_notification and not emit_lines:
        # A request must always be answered, or the client waits for ever.
        _write_error(data.get("id"), "Indigo's web server sent an empty reply")
        return

    # Transparent session recovery, as a plugin before 3.3.0 reported it: HTTP
    # 200 with JSON-RPC -32600 "Missing or invalid Mcp-Session-Id". Re-handshake
    # with the cached initialize, then replay this request ONCE with the new
    # session id. Only attempted once — if the replay still errors we surface
    # whatever came back.
    if can_recover and _is_session_error(messages) and _rehandshake():
        _replay(data, body, method)
        return

    _emit(emit_lines, is_notification)


def _replay(data: dict, body: bytes, method):
    """Send a request again after a re-handshake and write whatever comes back.
    Once only: a second session error is reported, not chased."""
    try:
        messages, emit_lines = _attempt(body, _build_headers(), method, False)
    except (_SendFailed, _HttpError) as e:
        _write_error(data.get("id"), str(e))
        return
    except Exception as e:
        _write_error(data.get("id"), f"Connection error after re-handshake: {e}")
        return
    if not emit_lines:
        _write_error(data.get("id"), "Indigo's web server sent an empty reply")
        return
    _emit(emit_lines, False)


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
