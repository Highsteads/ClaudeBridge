#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_path_safety.py
# Description: script_tools._resolve must collapse any client-supplied name to a
#              flat basename inside the scripts folder — no path traversal or
#              absolute-path injection.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.0

import os

import pytest

import indigo  # the conftest stub
from mcp_server.tools.script_tools import script_tools_handler as st


@pytest.fixture()
def fake_scripts_dir(tmp_path, monkeypatch):
    """Point _scripts_dir() at a temp 'Python Scripts' folder via the stubbed
    indigo.server.getInstallFolderPath()."""
    install = tmp_path / "Indigo 2025.2"
    install.mkdir()
    (tmp_path / "Python Scripts").mkdir()
    monkeypatch.setattr(indigo.server, "getInstallFolderPath",
                        lambda: str(install), raising=False)
    return tmp_path / "Python Scripts"


@pytest.mark.parametrize("evil", [
    "../../etc/passwd",
    "/etc/cron.d/evil",
    "../../../Library/LaunchAgents/evil",
    "subdir/../../escape",
])
def test_traversal_collapses_to_flat_name_inside_scripts(evil, fake_scripts_dir):
    resolved = os.path.realpath(st._resolve(evil))
    base = os.path.realpath(str(fake_scripts_dir))
    # Resolved path stays inside the scripts folder...
    assert resolved == base or resolved.startswith(base + os.sep)
    # ...and is a single flat .py file (no directory components survived).
    assert os.path.dirname(resolved) == base
    assert resolved.endswith(".py")


def test_empty_name_rejected(fake_scripts_dir):
    with pytest.raises(ValueError):
        st._resolve("   ")


def test_normal_name_resolves_in_scripts_dir(fake_scripts_dir):
    resolved = os.path.realpath(st._resolve("MyScript"))
    base = os.path.realpath(str(fake_scripts_dir))
    assert resolved == os.path.join(base, "MyScript.py")
