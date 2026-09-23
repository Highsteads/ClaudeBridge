#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_client_menu_item.py
# Description: Contract tests for execute_client_menu_item — the AppleScript path it
#              builds, and the two things it must refuse. No client is driven here.
# Author:      CliveS & Claude Opus 5
# Date:        14-09-2026
# Version:     1.0

import pytest

# conftest puts the bundle's Server Plugin on sys.path, so this is the same file
# the bundle ships. It uses relative imports, so it has to come in as a package
# member rather than by path.
from mcp_server.tools.scripting_shell import scripting_shell_handler as mod

build = mod.ScriptingShellHandler._menu_path_applescript


# ── the AppleScript reference ──────────────────────────────────────────────

def test_three_level_path_matches_what_the_client_actually_accepts():
    """This exact string was run against a live Indigo 2025.2 on 14-09-2026 and
    enumerated the Z-Wave menu, so it is a recorded fact rather than a guess."""
    assert build(["Interfaces", "Z-Wave", "Disable"]) == (
        'menu item "Disable" of menu "Z-Wave" of menu item "Z-Wave" '
        'of menu "Interfaces" of menu bar item "Interfaces" of menu bar 1'
    )


def test_two_level_path_has_no_intermediate_pair():
    assert build(["File", "New Device"]) == (
        'menu item "New Device" of menu "File" of menu bar item "File" of menu bar 1'
    )


def test_each_extra_level_adds_one_menu_and_one_menu_item():
    ref = build(["Plugins", "Some Plugin", "Sub", "Item"])
    assert ref.count("of menu item ") == 2      # Some Plugin, Sub
    assert ref.startswith('menu item "Item"')
    assert ref.endswith('of menu bar item "Plugins" of menu bar 1')


def test_quotes_in_a_label_are_escaped_not_passed_through():
    ref = build(["A", 'He said "hi"'])
    assert r'menu item "He said \"hi\""' in ref


# ── the refusals ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    ["Plugins", "Claude Bridge", "Reload"],
    ["Plugins", "claude bridge", "Configure..."],
    ["Plugins", "ClaudeBridge", "Anything"],
])
def test_it_refuses_its_own_submenu_at_any_spelling(path):
    """execute_plugin_menu_item refuses plugin_name='Claude Bridge' because the
    reload kills the session running the tool. A full-path tool reaches the same
    item, so the guard has to be rebuilt here — it is not inherited."""
    assert mod._path_targets_self(path) is True


def test_an_ordinary_plugin_path_is_not_caught_by_that_guard():
    assert mod._path_targets_self(["Plugins", "Zigbee2MQTT Bridge", "Permit Join"]) is False
    assert mod._path_targets_self(["Interfaces", "Z-Wave", "Disable"]) is False


@pytest.mark.parametrize("path", [
    ["File", "Quit"],
    ["Indigo 2025.2", "Quit Indigo 2025.2"],
    ["indigo 2026.1", "Quit Indigo 2026.1"],
])
def test_it_refuses_to_quit_the_client_that_it_works_through(path):
    assert mod._is_forbidden_path(path) is True


def test_quit_guard_does_not_swallow_ordinary_items():
    assert mod._is_forbidden_path(["File", "New Device"]) is False
    assert mod._is_forbidden_path(["Interfaces", "Z-Wave", "Disable"]) is False
    # "Indigo ..." first segment alone is not enough - only Quit under it
    assert mod._is_forbidden_path(["Indigo 2025.2", "About Indigo"]) is False


# ── argument handling, without touching osascript ──────────────────────────

class _Handler(mod.ScriptingShellHandler):
    def __init__(self):
        pass                                   # no DataProvider needed for the guards
    def log_incoming_request(self, *a, **k):
        pass
    def log_tool_outcome(self, *a, **k):
        pass


def test_a_click_needs_at_least_two_levels():
    r = _Handler().execute_client_menu_item(["Interfaces"])
    assert r["success"] is False and "at least" in r["error"]


def test_a_refused_path_never_reaches_osascript(monkeypatch):
    """The refusal must come before the subprocess, not after it."""
    def _boom(*a, **k):
        raise AssertionError("osascript was invoked for a refused path")
    monkeypatch.setattr(mod.subprocess, "run", _boom)
    r = _Handler().execute_client_menu_item(["Plugins", "Claude Bridge", "Reload"])
    assert r["success"] is False and "Claude Bridge" in r["error"]
    r = _Handler().execute_client_menu_item(["File", "Quit"])
    assert r["success"] is False and "quit" in r["error"].lower()


def test_listing_more_than_two_levels_is_refused():
    r = _Handler().execute_client_menu_item(["A", "B", "C"], list_only=True)
    assert r["success"] is False and "two levels" in r["error"]


# ── non-ASCII output (2.27.1) ──────────────────────────────────────────────
#
# Inside an Indigo plugin host the locale encoding is ASCII, so a bare
# subprocess.run(..., text=True) decodes osascript's output as ASCII and raises
# "'ascii' codec can't decode byte 0xe2" on the first em-dash. Hit live on
# Device Health Monitor -> Scan Now (18-09-2026). These tests reproduce the
# host's condition for real: the default text encoding is forced to ASCII and a
# genuine child process writes UTF-8 bytes, so what is being tested is the
# decode subprocess itself performs, not a stand-in for it.

import sys as _sys

_UTF8_OUTPUT = "Scan complete — 3 devices checked, café lamp OK"


def _host_like_run(monkeypatch, target_module):
    """Make target_module.subprocess behave as it does inside the plugin host:
    ASCII default decoding, and a child that prints UTF-8 in place of osascript."""
    real_run = target_module.subprocess.run
    monkeypatch.setattr(target_module.subprocess, "_text_encoding", lambda: "ascii")
    child = [_sys.executable, "-c",
             "import sys; sys.stdout.buffer.write(%r.encode('utf-8'))" % _UTF8_OUTPUT]

    def _run(cmd, *a, **k):
        return real_run(child, *a, **k)
    monkeypatch.setattr(target_module.subprocess, "run", _run)


def test_the_host_condition_is_really_reproduced(monkeypatch):
    """Guard for the guard: a bare text=True run under this harness must fail
    exactly as the plugin host did, or the two tests below prove nothing."""
    _host_like_run(monkeypatch, mod)
    with pytest.raises(UnicodeDecodeError):
        mod.subprocess.run(["osascript"], capture_output=True, text=True, timeout=10)


def test_plugin_menu_item_survives_non_ascii_output(monkeypatch):
    _host_like_run(monkeypatch, mod)
    r = _Handler().execute_plugin_menu_item("Device Health Monitor", "Scan Now")
    assert r["success"] is True, r
    assert r["stdout"] == _UTF8_OUTPUT


def test_client_menu_item_survives_non_ascii_output(monkeypatch):
    _host_like_run(monkeypatch, mod)
    r = _Handler().execute_client_menu_item(["Interfaces", "Z-Wave"], list_only=True)
    assert r["success"] is True, r
    assert r["stdout"] == _UTF8_OUTPUT


def test_system_tools_run_survives_non_ascii_output(monkeypatch):
    """system_health / find_large_files read du, ps and friends through _run();
    a file or process name with an accent must not blank the metric."""
    from mcp_server.tools.system_tools import system_tools_handler as sys_mod
    _host_like_run(monkeypatch, sys_mod)
    assert sys_mod._run(["du", "-sh", "/nowhere"], timeout=10) == _UTF8_OUTPUT


def test_every_text_mode_subprocess_call_in_the_bundle_names_its_encoding():
    """The fix above has to hold for calls not yet written. Walks the AST (not the
    source text, so a comment cannot satisfy it) of every bundle module and fails
    on any subprocess call that asks for text without naming an encoding."""
    import ast
    import os
    from conftest import SERVER_PLUGIN
    offenders = []
    for root, _dirs, files in os.walk(SERVER_PLUGIN):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "subprocess"
                        and node.func.attr in ("run", "Popen", "check_output", "check_call", "call")):
                    continue
                kw = {k.arg for k in node.keywords}
                if kw & {"text", "universal_newlines"} and "encoding" not in kw:
                    offenders.append(f"{os.path.relpath(path, SERVER_PLUGIN)}:{node.lineno}")
    assert not offenders, "text-mode subprocess calls with no encoding: " + ", ".join(offenders)
