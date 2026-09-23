#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_error_redaction.py
# Description: A failed execute_indigo_python / run_script keeps its traceback,
#              stdout and stderr, with every known credential VALUE replaced —
#              and falls back to the whole-payload scrub if the values cannot
#              be loaded. Also covers keeping the TAIL of a long traceback.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import logging
import os
import threading
from collections import deque
from unittest.mock import MagicMock

from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler
from mcp_server.security import RateLimiter, ScopeManager
from mcp_server.security.secret_redactor import (
    MIN_SECRET_LENGTH, SecretRedactor, credential_values_from_source,
)

_LOGGER = logging.getLogger("test-redaction")

_SECRETS_SOURCE = '''
OWM_API_KEY      = "owm-key-0123456789"
MQTT_BROKER      = "192.168.1.50"
MQTT_USERNAME    = "mqttuser"
MQTT_PASSWORD    = "hunter2-mqtt"
SHORT_TOKEN      = "abc"
SMLIGHT_PASSWORD = "smlight-pass-9"
UNIFI_PASSWORD   = SMLIGHT_PASSWORD
DOOR_USER_PINS   = {"alice": "73519024", "bob": "1234"}
MQTT_PORT        = 1883
'''


# ── Which values count as secret ──────────────────────────────────────────────

def test_only_credential_named_settings_are_collected():
    found = credential_values_from_source(_SECRETS_SOURCE)
    assert found["owm-key-0123456789"] == "OWM_API_KEY"
    assert found["hunter2-mqtt"] == "MQTT_PASSWORD"
    # Addresses and usernames are not secrets; redacting them would only
    # blind the traceback.
    assert "192.168.1.50" not in found
    assert "mqttuser" not in found


def test_alias_assignment_is_followed():
    found = credential_values_from_source(_SECRETS_SOURCE)
    # UNIFI_PASSWORD = SMLIGHT_PASSWORD: the value is found under both names,
    # the later one winning the label.
    assert found["smlight-pass-9"] == "UNIFI_PASSWORD"


def test_nested_values_under_a_credential_name_are_collected():
    found = credential_values_from_source(_SECRETS_SOURCE)
    assert found["73519024"] == "DOOR_USER_PINS"


def test_short_values_are_skipped():
    found = credential_values_from_source(_SECRETS_SOURCE)
    assert "abc" not in found and "1234" not in found
    assert all(len(v) >= MIN_SECRET_LENGTH for v in found)


def test_source_is_parsed_not_executed(tmp_path):
    marker = tmp_path / "executed"
    src = f'import pathlib\npathlib.Path({str(marker)!r}).write_text("x")\nAPI_KEY = "k-123456789"\n'
    found = credential_values_from_source(src)
    assert found == {"k-123456789": "API_KEY"}
    assert not marker.exists()


# ── The redactor itself ──────────────────────────────────────────────────────

def _redactor(tmp_path, extra=None):
    sp = tmp_path / "IndigoSecrets.py"
    sp.write_text(_SECRETS_SOURCE, encoding="utf-8")
    iws = tmp_path / "secrets.json"
    iws.write_text(json.dumps(["iws-api-key-abcdef123456"]), encoding="utf-8")
    return SecretRedactor(str(sp), str(iws), extra_values=extra), sp


def test_redacts_every_field_and_keeps_the_rest(tmp_path):
    r, _ = _redactor(tmp_path)
    values = r.load()
    payload = {
        "success":   False,
        "error":     "401 for key owm-key-0123456789",
        "traceback": "Traceback...\nRuntimeError: login hunter2-mqtt refused",
        "stdout":    "connecting to 192.168.1.50 with iws-api-key-abcdef123456",
        "stderr":    "",
    }
    out = SecretRedactor.redact_obj(payload, values)
    text = json.dumps(out)
    for secret in ("owm-key-0123456789", "hunter2-mqtt", "iws-api-key-abcdef123456"):
        assert secret not in text
    assert "[redacted OWM_API_KEY]" in out["error"]
    assert "RuntimeError: login [redacted MQTT_PASSWORD] refused" in out["traceback"]
    assert "192.168.1.50" in out["stdout"]      # the diagnosis survives
    assert out["success"] is False


def test_extra_values_only_use_credential_names(tmp_path):
    r, _ = _redactor(tmp_path, extra=lambda: {
        "anthropic_api_key": "sk-ant-extra-000111",
        "tokenLabel":        "readonly",           # credential-shaped name, harmless
        "serverName":        "not-a-secret-value",
    })
    values = r.load()
    assert values["sk-ant-extra-000111"] == "anthropic_api_key"
    assert "not-a-secret-value" not in values


def test_a_rotated_key_is_picked_up_without_a_restart(tmp_path):
    r, sp = _redactor(tmp_path)
    assert "owm-key-0123456789" in r.load()
    sp.write_text('OWM_API_KEY = "owm-rotated-key-999"\n', encoding="utf-8")
    st = os.stat(sp)
    os.utime(sp, (st.st_atime, st.st_mtime + 5))   # mtime granularity
    values = r.load()
    assert "owm-rotated-key-999" in values
    assert "owm-key-0123456789" not in values


def test_longer_secret_containing_a_shorter_one_is_removed_whole():
    values = {"abcdef": "SHORT_KEY", "abcdef-and-more": "LONG_KEY"}
    out = SecretRedactor.redact_text("x abcdef-and-more y", values)
    assert out == "x [redacted LONG_KEY] y"


def test_unreadable_source_raises_so_the_caller_can_fail_closed(tmp_path):
    sp = tmp_path / "IndigoSecrets.py"
    sp.write_text("this is ( not python", encoding="utf-8")
    r = SecretRedactor(str(sp), None)
    try:
        r.load()
    except SyntaxError:
        return
    raise AssertionError("a broken secrets file must raise, not return no values")


def test_missing_files_mean_no_values(tmp_path):
    r = SecretRedactor(str(tmp_path / "absent.py"), str(tmp_path / "absent.json"))
    assert r.load() == {}


# ── Through the dispatch chokepoint ──────────────────────────────────────────

def _make_handler(tmp_path, tools, redactor):
    h = object.__new__(MCPHandler)
    h.logger          = _LOGGER
    h.scope_manager   = ScopeManager(scopes_file=str(tmp_path / "scopes.json"), logger=_LOGGER)
    h.rate_limiter    = RateLimiter(per_minute=120, per_day=5_000,
                                    admin_multiplier=1.0, logger=_LOGGER)
    h.tool_cache      = ToolCache(default_ttl=0, logger=_LOGGER)
    h._telemetry_lock = threading.Lock()
    h._tool_call_log  = deque(maxlen=200)
    h._tool_error_count = 0
    h._tools          = tools
    h._secret_redactor = redactor
    h.plugin          = None
    # Both code-running tools trigger a search-index refresh afterwards.
    h.entity_index_manager = MagicMock()
    return h


def _tool(fn):
    return {"description": "t", "inputSchema": {"type": "object", "properties": {}},
            "function": fn}


def _failure(**kw):
    return json.dumps({
        "success":   False,
        "mode":      "exec",
        "stdout":    "step 1 done",
        "stderr":    "",
        "error":     "KeyError: 'hunter2-mqtt'",
        "traceback": "Traceback (most recent call last):\nKeyError: 'hunter2-mqtt'",
    })


def test_exec_failure_keeps_its_diagnosis(tmp_path):
    r, _ = _redactor(tmp_path)
    h = _make_handler(tmp_path, {"execute_indigo_python": _tool(_failure)}, r)
    resp = h._handle_tools_call(1, {"name": "execute_indigo_python", "arguments": {}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["success"] is False
    assert body["stdout"] == "step 1 done"
    assert body["traceback"].endswith("KeyError: '[redacted MQTT_PASSWORD]'")
    assert "hunter2-mqtt" not in json.dumps(body)


def test_run_script_failure_is_redacted_too(tmp_path):
    r, _ = _redactor(tmp_path)
    h = _make_handler(tmp_path, {"run_script": _tool(_failure)}, r)
    resp = h._handle_tools_call(2, {"name": "run_script", "arguments": {}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert "traceback" in body and "hunter2-mqtt" not in json.dumps(body)


class _BrokenRedactor:
    def load(self):
        raise OSError("cannot read secrets")


def test_redaction_failure_falls_back_to_the_full_scrub(tmp_path):
    h = _make_handler(tmp_path, {"execute_indigo_python": _tool(_failure)}, _BrokenRedactor())
    resp = h._handle_tools_call(3, {"name": "execute_indigo_python", "arguments": {}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body == {"success": False, "error": "see the Claude Bridge event log for details"}


def test_raised_exception_text_is_redacted_not_hidden(tmp_path):
    r, _ = _redactor(tmp_path)

    def _boom(**kw):
        raise RuntimeError("auth failed with hunter2-mqtt at step 3")

    h = _make_handler(tmp_path, {"execute_indigo_python": _tool(_boom)}, r)
    resp = h._handle_tools_call(4, {"name": "execute_indigo_python", "arguments": {}})
    msg = resp["error"]["message"]
    assert "hunter2-mqtt" not in msg
    assert "auth failed with [redacted MQTT_PASSWORD] at step 3" in msg


def test_other_sensitive_tools_keep_the_whole_scrub(tmp_path):
    r, _ = _redactor(tmp_path)
    h = _make_handler(tmp_path, {"send_notification": _tool(_failure)}, r)
    resp = h._handle_tools_call(5, {"name": "send_notification", "arguments": {}})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert "traceback" not in body and "stdout" not in body


def test_successful_calls_are_untouched(tmp_path):
    r, _ = _redactor(tmp_path)
    ok = json.dumps({"success": True, "stdout": "hunter2-mqtt"})
    h = _make_handler(tmp_path, {"execute_indigo_python": _tool(lambda **kw: ok)}, r)
    resp = h._handle_tools_call(6, {"name": "execute_indigo_python", "arguments": {}})
    assert resp["result"]["content"][0]["text"] == ok


# ── A long traceback keeps its last line ─────────────────────────────────────

def test_long_traceback_keeps_the_exception_line():
    from mcp_server.tools.scripting_shell.scripting_shell_handler import ScriptingShellHandler
    h = object.__new__(ScriptingShellHandler)
    h.logger = _LOGGER
    h.log_tool_outcome = lambda *a, **k: None
    # Distinct functions, because Python folds repeated identical frames into
    # "[Previous line repeated N more times]" and the traceback stays short.
    depth = 120
    code = "".join(f"def f{i}():\n    return f{i + 1}()\n" for i in range(depth))
    code += f"def f{depth}():\n    return {{}}['the-missing-key']\nf0()\n"
    res = h.execute_indigo_python(code=code)
    assert res["success"] is False
    assert len(res["traceback"]) <= 4000 + len("...[truncated]\n")
    assert res["traceback"].startswith("...[truncated]")
    assert "the-missing-key" in res["traceback"].splitlines()[-1]


# ── Shortened output says so (2.27.3) ────────────────────────────────────────

def test_long_stdout_is_flagged_as_truncated():
    from mcp_server.tools.scripting_shell.scripting_shell_handler import ScriptingShellHandler
    h = object.__new__(ScriptingShellHandler)
    h.logger = _LOGGER
    h.log_tool_outcome = lambda *a, **k: None
    res = h.execute_indigo_python(code="print('x' * 9000)")
    assert res["success"] is True
    assert res["stdout_truncated"] == {"shown": 8000, "total": 9001}
    assert res["stdout"].endswith("...[truncated]")


def test_short_stdout_carries_no_flag():
    from mcp_server.tools.scripting_shell.scripting_shell_handler import ScriptingShellHandler
    h = object.__new__(ScriptingShellHandler)
    h.logger = _LOGGER
    h.log_tool_outcome = lambda *a, **k: None
    res = h.execute_indigo_python(code="print('ok')")
    assert res["stdout"] == "ok\n" and "stdout_truncated" not in res


def test_run_script_error_keeps_its_type_and_traceback(tmp_path, monkeypatch):
    from mcp_server.tools.script_tools import script_tools_handler as sth
    script = tmp_path / "Broken.py"
    script.write_text("print('started')\n{}['missing-key']\n", encoding="utf-8")
    monkeypatch.setattr(sth, "_resolve", lambda name: str(script))
    h = object.__new__(sth.ScriptToolsHandler)
    h.logger = _LOGGER
    h.log_tool_outcome = lambda *a, **k: None
    h.log_incoming_request = lambda *a, **k: None
    res = h.run_script("Broken.py")
    assert res["success"] is False
    assert res["error"] == "KeyError: 'missing-key'"
    assert res["traceback"].rstrip().endswith("KeyError: 'missing-key'")
    assert res["stdout"] == "started\n"


# ── return-vs-raise cluster: error results detected, not cached, scrubbed ────

def test_result_ok_detects_error_payloads():
    from mcp_server.mcp_handler import MCPHandler
    assert MCPHandler._result_ok('{"success": true, "devices": []}') is True
    assert MCPHandler._result_ok('{"success": false, "error": "boom"}') is False
    assert MCPHandler._result_ok('{"error": "not found"}') is False
    # A plain (non-JSON, non-dict) string is a normal result, not an error.
    assert MCPHandler._result_ok("just some text") is True
    assert MCPHandler._result_ok('{"success": true, "error": null}') is True


def test_scrub_error_result_removes_raw_text():
    from mcp_server.mcp_handler import MCPHandler
    raw = '{"success": false, "error": "SMTP auth failed for user bob@example.com via mail.host:587"}'
    scrubbed = json.loads(MCPHandler._scrub_error_result(raw))
    assert scrubbed["success"] is False
    assert "bob@example.com" not in scrubbed["error"]
    assert "event log" in scrubbed["error"]


# ── A sensitive tool's failure must not ship the secret by another name ──────

def test_error_scrub_drops_traceback_and_output():
    """Replacing only `error` left `traceback` carrying the same text verbatim."""
    import json

    from mcp_server.mcp_handler import MCPHandler

    raw = json.dumps({
        "success":   False,
        "error":     "auth failed for sk-secret-123",
        "traceback": "Traceback...\nRuntimeError: auth failed for sk-secret-123",
        "stdout":    "printing sk-secret-123",
        "stderr":    "sk-secret-123",
        "path":      "/Library/.../Nightly.py",
        "timed_out": True,
    })
    out = json.loads(MCPHandler._scrub_error_result(raw))

    assert out["success"] is False
    assert out["timed_out"] is True          # control flow survives
    for leaked in ("traceback", "stdout", "stderr", "path"):
        assert leaked not in out, f"{leaked} survived the scrub"
    assert "sk-secret-123" not in json.dumps(out)
