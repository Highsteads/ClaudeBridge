#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_runs.py
# Description: Script writing and running, from the 3.0.1 review: a rewrite
#              keeps the script's file mode (mkstemp made it 0600), create
#              never overwrites, sys.exit(1) is a failure, backups are listed
#              by the same pattern that prunes them, the menu listing splits on
#              line feeds, and a failure in the CALLER's code logs at DEBUG
#              rather than as a red error in Indigo's event log.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import os
import stat
import subprocess
import time

import pytest

import indigo  # the conftest stub
from mcp_server.common import exec_lock
from mcp_server.tools.script_tools import script_tools_handler as st
from mcp_server.tools.scripting_shell import scripting_shell_handler as ssh

LOG = logging.getLogger("test-script-runs")


@pytest.fixture()
def scripts(tmp_path, monkeypatch):
    install = tmp_path / "Indigo 2025.2"
    install.mkdir()
    folder = tmp_path / "Python Scripts"
    folder.mkdir()
    monkeypatch.setattr(indigo.server, "getInstallFolderPath", lambda: str(install),
                        raising=False)
    return folder


@pytest.fixture(autouse=True)
def _jobs():
    exec_lock.reset_for_tests()
    yield
    deadline = time.monotonic() + 5
    while exec_lock.status()["running"] and time.monotonic() < deadline:
        time.sleep(0.01)
    exec_lock.reset_for_tests()


def _tools():
    return st.ScriptToolsHandler(data_provider=None, logger=LOG)


# ── write / create ───────────────────────────────────────────────────────────

def test_a_rewrite_keeps_the_scripts_mode(scripts):
    path = scripts / "Lamp.py"
    path.write_text("x = 1\n")
    os.chmod(path, 0o755)
    out = _tools().write_script("Lamp", "x = 2\n")
    assert out["success"] is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o755
    assert path.read_text() == "x = 2\n"


def test_a_new_script_is_0644_and_never_overwrites(scripts):
    out = _tools().create_script("Fresh", "a = 1\n")
    assert out["success"] is True
    assert stat.S_IMODE(os.stat(scripts / "Fresh.py").st_mode) == 0o644
    again = _tools().create_script("Fresh", "a = 2\n")
    assert again["success"] is False and (scripts / "Fresh.py").read_text() == "a = 1\n"


def test_create_refuses_a_file_that_appears_after_the_check(scripts, monkeypatch):
    """open(path, "x") is the guard; the isfile() check alone was a race."""
    real_isfile = os.path.isfile
    monkeypatch.setattr(st.os.path, "isfile",
                        lambda p: False if str(p).endswith("Racy.py") else real_isfile(p))
    (scripts / "Racy.py").write_text("keep = True\n")
    out = _tools().create_script("Racy", "overwritten = True\n")
    assert out["success"] is False
    assert (scripts / "Racy.py").read_text() == "keep = True\n"


def test_backups_are_listed_by_the_name_pattern(scripts):
    backups = scripts / "_backups"
    backups.mkdir()
    for name in ("a.py_old.20260901_101010.py", "a.py_old.20260902_101010_123.py",
                 "a.py_old.notes.py", "a.20260903_101010.py"):
        (backups / name).write_text("")
    out = _tools().list_script_backups("a.py_old.py")
    assert [b["filename"] for b in out["backups"]] == [
        "a.py_old.20260902_101010_123.py", "a.py_old.20260901_101010.py"]


# ── exit codes ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,ok", [
    ("import sys\nsys.exit()\n", True),
    ("import sys\nsys.exit(0)\n", True),
    ("import sys\nsys.exit(1)\n", False),
    ("import sys\nsys.exit('no lamp')\n", False),
])
def test_run_script_reads_the_exit_code(scripts, body, ok):
    (scripts / "Exit.py").write_text(body)
    out = _tools().run_script("Exit", wait_seconds=5)
    assert out["success"] is ok
    if not ok:
        assert out["error"].startswith("SystemExit:")


@pytest.mark.parametrize("code,ok", [("import sys; sys.exit(None)", True),
                                     ("import sys; sys.exit(2)", False)])
def test_execute_indigo_python_reads_the_exit_code(code, ok):
    shell = ssh.ScriptingShellHandler(data_provider=None, logger=LOG)
    out = shell.execute_indigo_python(code, wait_seconds=5)
    assert out["success"] is ok
    if not ok:
        assert out["error"] == "SystemExit: 2"


# ── log levels ───────────────────────────────────────────────────────────────

def test_a_callers_failure_is_not_an_error_in_the_event_log(scripts, caplog):
    (scripts / "Boom.py").write_text("raise KeyError('k')\n")
    shell = ssh.ScriptingShellHandler(data_provider=None, logger=LOG)
    with caplog.at_level(logging.DEBUG, logger=LOG.name):
        assert _tools().run_script("Boom", wait_seconds=5)["success"] is False
        assert shell.execute_indigo_python("1/0", wait_seconds=5)["success"] is False
    outcome = [r for r in caplog.records if "ERROR:" in r.getMessage()]
    assert len(outcome) == 2
    assert all(r.levelno == logging.DEBUG for r in outcome), \
        [(r.levelname, r.getMessage()) for r in outcome]


# ── menu listing ─────────────────────────────────────────────────────────────

def test_a_menu_title_with_a_comma_stays_one_item(monkeypatch):
    shell = ssh.ScriptingShellHandler(data_provider=None, logger=LOG)
    seen = {}

    def _run(cmd, **kwargs):
        seen["script"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "Open…\nmissing value\nSave, As…\n", "")

    monkeypatch.setattr(ssh.subprocess, "run", _run)
    out = shell.execute_client_menu_item(path=["File"], list_only=True)
    assert out["items"] == ["Open…", "missing value", "Save, As…"]
    assert "text item delimiters to linefeed" in seen["script"]
