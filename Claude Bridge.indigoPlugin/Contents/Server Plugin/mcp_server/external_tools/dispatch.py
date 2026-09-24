#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    dispatch.py
# Description: Calls one plugin-provided tool through Indigo's cross-plugin
#              executeAction and maps the provider's reply to Claude Bridge's
#              house result shape. The contract: the call carries props
#              {"tool": <bare name>, "arguments": <JSON string>} and the
#              provider returns a JSON-string envelope, {"status": "ok",
#              "result": ...} or {"status": "error", "error": {type, message,
#              details}}. Arguments and results cross as JSON strings because
#              indigo.Dict cannot hold None or $-prefixed keys.
#              executeAction has no timeout of its own and raises one
#              undifferentiated Exception on failure, so every call runs on a
#              short-lived thread joined with the tool's declared deadline.
#              A call that overruns is abandoned — it cannot be cancelled —
#              and the thread is left to finish; that leak is bounded by the
#              deadline and is logged loudly.
#              1.1 (24-09-2026): the wait on the request thread is capped at
#              exec_lock.MAX_WAIT_SECONDS (20 s). That thread is Indigo's web
#              server thread too, so a provider allowed 120 s used to freeze
#              every dashboard for up to two minutes. A call still going at
#              the cap is reported as running, honestly, and its outcome is
#              logged when it lands.
# Author:      CliveS & Claude Fable 5.1; Claude Opus 5.5 (1.1)
# Date:        24-09-2026
# Version:     1.1

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..common.exec_lock import MAX_WAIT_SECONDS

try:
    import indigo
except ImportError:      # unit tests run outside the plugin host
    indigo = None


def _default_get_plugin(plugin_id: str):
    return indigo.server.getPlugin(plugin_id)


def invoke_provider_tool(
    provider_id: str,
    action_id: str,
    bare_name: str,
    display_name: str,
    arguments: Dict[str, Any],
    timeout_seconds: float,
    logger: Optional[logging.Logger] = None,
    get_plugin: Optional[Callable[[str], Any]] = None,
    max_wait_seconds: Optional[float] = None,
) -> dict:
    """Run one provider tool. Never raises: every failure comes back as
    {"success": False, "provider": ..., "error": ...} so the AI can read it.

    The request thread waits at most max_wait_seconds (default
    exec_lock.MAX_WAIT_SECONDS). A call still running then is NOT a failure:
    the reply says so, and the late outcome is logged when it arrives."""
    logger = logger or logging.getLogger("Plugin")
    cap = MAX_WAIT_SECONDS if max_wait_seconds is None else max(0.0, float(max_wait_seconds))
    wait = min(float(timeout_seconds), cap)
    get_plugin = get_plugin or _default_get_plugin
    label = f"{display_name}: {bare_name}"

    try:
        plugin = get_plugin(provider_id)
        running = bool(plugin.isRunning())
    except Exception as exc:
        return {"success": False, "provider": provider_id,
                "error": f"could not reach the {display_name} plugin: {exc}"}
    # isRunning(), not isEnabled(): a plugin that hit a fatal error stays
    # enabled but is not running, and executeAction would only raise.
    if not running:
        return {"success": False, "provider": provider_id,
                "error": (f"The {display_name} plugin is not running, so its tools are "
                          f"unavailable. Enable or restart it in Indigo and try again.")}

    props = {"tool": bare_name, "arguments": json.dumps(arguments or {})}
    slot: Dict[str, Any] = {}
    handoff = threading.Lock()
    started = time.monotonic()

    def _run():
        try:
            slot["value"] = plugin.executeAction(action_id, props=props, waitUntilDone=True)
        except Exception as exc:          # undifferentiated by design of the platform
            slot["exception"] = exc
        with handoff:
            slot["done"] = True
            abandoned = slot.get("abandoned", False)
        if abandoned:
            _log_late_outcome(slot, provider_id, label, time.monotonic() - started, logger)

    worker = threading.Thread(target=_run, name=f"ext-tool-{provider_id}-{bare_name}", daemon=True)
    worker.start()
    worker.join(wait)

    with handoff:
        still_running = not slot.get("done", False)
        if still_running:
            slot["abandoned"] = True
    if still_running:
        if wait < timeout_seconds:
            # Capped, not timed out: the provider is inside its declared
            # deadline and may well finish.
            logger.warning(f"⏱ {label} still running after {wait:g}s — replying now so the "
                           f"web server is not held; its outcome will be logged when it lands")
            return {"status": "running", "provider": provider_id,
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "note": (f"{label} is still working after {wait:g}s. Claude Bridge will "
                             f"not hold Indigo's web server any longer than that, so this "
                             f"reply comes back now. The call cannot be cancelled: it keeps "
                             f"running inside {display_name} and may still finish, including "
                             f"any change it makes. Its outcome is written to the Claude "
                             f"Bridge event log when it lands; check that (or read the state "
                             f"it changes) before trying again.")}
        logger.error(f"⏱ {label} timed out after {timeout_seconds}s — the call is still "
                     f"running inside {display_name} and cannot be cancelled")
        return {"success": False, "provider": provider_id, "timeout": True,
                "error": (f"{label} did not reply within {timeout_seconds}s. The provider "
                          f"may be busy or hung; check its plugin.log.")}

    if "exception" in slot:
        exc = slot["exception"]
        logger.error(f"❌ {label} raised: {exc}")
        return {"success": False, "provider": provider_id,
                "error": (f"{label} failed: {exc}. Possible causes: the provider does not "
                          f"define action '{action_id}', it crashed mid-call, or its handler "
                          f"raised — check the provider's plugin.log.")}

    return parse_envelope(slot.get("value"), provider_id, label, logger)


def _log_late_outcome(slot: Dict[str, Any], provider_id: str, label: str,
                      elapsed: float, logger: logging.Logger) -> None:
    """One line for a call whose reply had already gone back as "running"."""
    try:
        if "exception" in slot:
            logger.warning(f"{label} finished after {elapsed:.0f}s, after its reply had "
                           f"gone back, and FAILED: {slot['exception']}")
            return
        outcome = parse_envelope(slot.get("value"), provider_id, label, logger)
        if outcome.get("success"):
            logger.info(f"{label} finished after {elapsed:.0f}s, after its reply had gone "
                        f"back, and succeeded")
        else:
            logger.warning(f"{label} finished after {elapsed:.0f}s, after its reply had "
                           f"gone back, and FAILED: {outcome.get('error')}")
    except Exception:      # noqa: BLE001 — a log line must never kill the thread
        pass


def parse_envelope(raw: Any, provider_id: str, label: str,
                   logger: Optional[logging.Logger] = None) -> dict:
    """The provider's JSON-string envelope, mapped to the house result shape.
    A reply that is not a JSON string with a valid status is a protocol
    violation, reported as such rather than guessed at."""
    logger = logger or logging.getLogger("Plugin")
    if not isinstance(raw, str):
        logger.error(f"❌ {label} returned {type(raw).__name__} instead of a JSON string")
        return {"success": False, "provider": provider_id,
                "error": (f"{label} violated the provider protocol: expected a JSON string "
                          f"reply, got {type(raw).__name__}.")}
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"❌ {label} returned invalid JSON: {exc}")
        return {"success": False, "provider": provider_id,
                "error": f"{label} violated the provider protocol: reply is not valid JSON ({exc})."}

    status = envelope.get("status") if isinstance(envelope, dict) else None
    if status == "ok":
        return {"success": True, "provider": provider_id, "result": envelope.get("result")}
    if status == "error":
        error = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
        out = {"success": False, "provider": provider_id,
               "error": error.get("message") or "unknown provider error",
               "error_type": error.get("type") or "internal"}
        if error.get("details") is not None:
            out["details"] = error["details"]
        return out

    logger.error(f"❌ {label} returned an envelope without a valid status")
    return {"success": False, "provider": provider_id,
            "error": (f"{label} violated the provider protocol: the reply must be "
                      f'{{"status": "ok"|"error", ...}}.')}
