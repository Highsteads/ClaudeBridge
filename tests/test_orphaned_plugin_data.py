#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_orphaned_plugin_data.py
# Description: Regression tests for find_orphaned_plugin_data after 20-08-2026.
#              The tool scanned Preferences/Plugins SUBDIRECTORIES only, so the
#              per-plugin .indiPref FILES — which is where most plugins keep all
#              their data — were invisible. A live sweep that day turned up 13
#              orphan prefs files (two holding plaintext credentials) and three
#              dead LaunchAgents, none of which the tool reported.
# Author:      CliveS & Claude Opus 5
# Date:        20-08-2026
# Version:     1.0

import os
import plistlib
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.system_tools import system_tools_handler as sth
from mcp_server.tools.system_tools.system_tools_handler import SystemToolsHandler

from test_dispatch import _LOGGER


def _handler():
    return SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)


def _write_agent(path, argv):
    with open(path, "wb") as fh:
        plistlib.dump({"Label": os.path.basename(path)[:-6],
                       "ProgramArguments": argv}, fh)


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """A miniature Preferences/Plugins + LaunchAgents pair on disk."""
    prefs  = tmp_path / "Preferences" / "Plugins"
    agents = tmp_path / "LaunchAgents"
    prefs.mkdir(parents=True)
    agents.mkdir()

    (prefs / "com.clives.indigoplugin.live").mkdir()          # installed, dir
    (prefs / "com.clives.indigoplugin.live.indiPref").write_text("<Prefs/>")
    (prefs / "com.clives.indigoplugin.dead.indiPref").write_text("<Prefs/>")
    (prefs / "com.clives.indigoplugin.gonedir").mkdir()       # orphan, dir
    (prefs / "com.perceptiveautomation.indigoplugin.zwave.indiPref").write_text("<Prefs/>")
    (prefs / "com.perceptiveautomation.indigoplugin.scriptexecutor.external.indiPref").write_text("<Prefs/>")
    (prefs / ".DS_Store").write_text("junk")

    monkeypatch.setattr(sth, "_prefs_plugins_dir", lambda: str(prefs))
    monkeypatch.setattr(sth, "_launch_agents_dir", lambda: str(agents))
    monkeypatch.setattr(sth, "_installed_bundle_ids",
                        lambda: {"com.clives.indigoplugin.live"})
    return prefs, agents


def test_orphan_prefs_FILE_is_found(estate):
    """The regression: a .indiPref file with no installed plugin behind it."""
    result = _handler().find_orphaned_plugin_data()
    ids = {o["bundle_id"] for o in result["orphaned"]}
    assert "com.clives.indigoplugin.dead" in ids
    assert "com.clives.indigoplugin.gonedir" in ids          # dirs still work
    assert "com.clives.indigoplugin.live" not in ids
    kinds = {o["bundle_id"]: o["kind"] for o in result["orphaned"]}
    assert kinds["com.clives.indigoplugin.dead"] == "prefs_file"
    assert kinds["com.clives.indigoplugin.gonedir"] == "dir"


def test_indigo_builtins_are_not_orphans(estate):
    """Z-Wave and the script executors have prefs but no bundle in Plugins/."""
    result = _handler().find_orphaned_plugin_data()
    ids = {o["bundle_id"] for o in result["orphaned"]}
    assert "com.perceptiveautomation.indigoplugin.zwave" not in ids
    assert "com.perceptiveautomation.indigoplugin.scriptexecutor.external" not in ids
    assert result["builtin_count"] == 2


def test_stray_files_are_ignored(estate):
    """.DS_Store is not a bundle id."""
    result = _handler().find_orphaned_plugin_data()
    assert ".DS_Store" not in {o["bundle_id"] for o in result["orphaned"]}


def test_launch_agent_with_missing_script_is_stale(estate, tmp_path):
    """The live case: interpreter present, script gone with the old version folder."""
    _, agents = estate
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n")
    _write_agent(str(agents / "com.indigo.proxy.plist"),
                 [str(node), str(tmp_path / "Indigo 2024.2" / "proxy.js")])

    stale = _handler().find_orphaned_plugin_data()["stale_launch_agents"]
    assert [a["label"] for a in stale] == ["com.indigo.proxy"]
    assert "proxy.js" in stale[0]["reasons"][0]


def test_live_launch_agent_is_left_alone(estate, tmp_path):
    """A working agent must never be reported — a check that cries wolf gets ignored."""
    _, agents = estate
    script = tmp_path / "relay.py"
    script.write_text("")
    python = tmp_path / "python3"
    python.write_text("")
    _write_agent(str(agents / "com.clives.claudebridge.webhookrelay.plist"),
                 [str(python), "-u", str(script)])

    assert _handler().find_orphaned_plugin_data()["stale_launch_agents"] == []


def test_malformed_plist_is_skipped_not_raised(estate):
    _, agents = estate
    (agents / "broken.plist").write_text("this is not a plist")
    result = _handler().find_orphaned_plugin_data()
    assert result["success"] is True
    assert result["stale_launch_agents"] == []


def test_missing_launch_agents_dir_is_harmless(estate, monkeypatch, tmp_path):
    monkeypatch.setattr(sth, "_launch_agents_dir", lambda: str(tmp_path / "nope"))
    result = _handler().find_orphaned_plugin_data()
    assert result["success"] is True
    assert result["stale_launch_agent_count"] == 0
