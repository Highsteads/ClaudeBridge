#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_cache_freshness.py
# Description: Three ways the read cache used to serve stale answers: the
#              script readers were cached though scripts change outside Claude
#              Bridge, a variable rename or move never told the cache, and a
#              background exec job that changed things after its call returned
#              left answers cached from before it.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import FakeDevice, load_plugin_module
from mcp_server import registry
from mcp_server.common import exec_lock
from mcp_server.common.tool_cache import ToolCache
from mcp_server.mcp_handler import MCPHandler

_LOG = logging.getLogger("test-cache-freshness")


@pytest.mark.parametrize("name", ["read_script", "list_python_scripts"])
def test_the_script_readers_are_not_cached(name):
    assert registry.spec_for(name).cacheable is False
    cache = ToolCache(default_ttl=60, logger=_LOG)
    first, _ = cache.get_or_compute(name, {}, lambda: "old source")
    second, hit = cache.get_or_compute(name, {}, lambda: "new source")
    assert (first, second, hit) == ("old source", "new source", False)


# ── a variable rename or move ────────────────────────────────────────────────

def _plugin():
    mod = load_plugin_module()
    p = object.__new__(mod.Plugin)
    p.pluginId = "com.clives.indigoplugin.claudebridge"
    p.logger = _LOG
    cache = MagicMock()
    p.mcp_handler = SimpleNamespace(entity_index_manager=MagicMock(), tool_cache=cache)
    p.webhooks_enabled = False
    p.webhook_manager = None
    p.webhook_dispatcher = None
    return p, cache


def _var(**kw):
    base = dict(id=5, name="house_mode", folderId=0, readOnly=False, value="home")
    base.update(kw)
    return FakeDevice(**base)


@pytest.mark.parametrize("change", [{"name": "house_mode_old"}, {"folderId": 99}])
def test_a_rename_or_move_marks_the_variable_domain(change):
    p, cache = _plugin()
    p.variableUpdated(_var(), _var(**change))
    cache.note_external_change.assert_called_with("variable")


def test_a_value_change_still_marks_it_and_a_non_change_does_not():
    p, cache = _plugin()
    p.variableUpdated(_var(), _var(value="away"))
    assert cache.note_external_change.call_count == 1
    p.variableUpdated(_var(), _var())
    assert cache.note_external_change.call_count == 1


# ── a background exec job finishing ──────────────────────────────────────────

@pytest.fixture
def clean_jobs():
    exec_lock.reset_for_tests()
    yield
    exec_lock.set_finish_listener(None)
    exec_lock.reset_for_tests()


def test_a_job_that_finishes_after_its_call_clears_the_cache(clean_jobs):
    h = object.__new__(MCPHandler)
    h.logger = _LOG
    h.tool_cache = ToolCache(default_ttl=60, logger=_LOG)
    exec_lock.set_finish_listener(h._on_exec_job_finished)

    release = threading.Event()
    job, refusal = exec_lock.start("execute_indigo_python", "", lambda: (release.wait(5), {"success": True})[1])
    assert refusal is None
    # The call "returns" while the job runs on; a read is cached in between.
    assert exec_lock.wait(job, 0)["status"] == "running"
    h.tool_cache.get_or_compute("list_devices", {}, lambda: "before the job")
    assert h.tool_cache.get_or_compute("list_devices", {}, lambda: "x")[1] is True

    release.set()
    job.done.wait(5)
    job.thread.join(5)
    value, hit = h.tool_cache.get_or_compute("list_devices", {}, lambda: "after the job")
    assert (value, hit) == ("after the job", False)


def test_stop_removes_only_its_own_listener(clean_jobs):
    h = object.__new__(MCPHandler)
    h.logger = _LOG
    h.tool_cache = ToolCache(default_ttl=60, logger=_LOG)
    h.entity_index_manager = None
    exec_lock.set_finish_listener(h._on_exec_job_finished)
    h.stop()
    assert exec_lock._on_finished is None

    other = MagicMock()
    exec_lock.set_finish_listener(other)
    h.stop()
    assert exec_lock._on_finished is other
