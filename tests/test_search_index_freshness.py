#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_search_index_freshness.py
# Description: The search index is rebuilt when Indigo says a device, variable
#              or action group was added, removed, renamed or moved - on the
#              next search, not after every execute_indigo_python / run_script.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Until 3.0 every exec call rebuilt the whole index (about 1,600 rebuilds in
# ten weeks, almost none of them after a rename). Now the plugin's change
# callbacks mark the index dirty and search rebuilds it first. The 300 s
# periodic rebuild stays as the safety net.

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import load_plugin_module
from mcp_server.common.entity_index import EntityIndexManager, index_fields_changed
from mcp_server.tools.search_entities.main import SearchEntitiesHandler

_LOG = logging.getLogger("test-index-freshness")


# ── #43 search refresh wired for structure-changing tools ────────────────────

def test_search_refresh_tools_set():
    from mcp_server import registry
    s = registry.search_refresh_names()
    for t in ("delete_device", "rename_device", "variable_create", "variable_delete",
              "delete_automation", "delete_folder", "duplicate"):
        assert t in s, t
    # a pure device on/off must NOT trigger a full index rebuild
    assert "device_control" not in s
    # Nor may arbitrary code: it rebuilt the index about 1,600 times in ten
    # weeks. Indigo's own change callbacks mark the index dirty instead.
    for t in ("execute_indigo_python", "run_script"):
        assert t not in s, t


# ── The manager: mark, then rebuild on demand ────────────────────────────────

class _Provider:
    """Counts rebuilds; the devices it reports can be changed between them."""

    def __init__(self, names=("Hall Lamp",)):
        self.names = list(names)
        self.reads = 0
        self.during_read = None

    def get_all_entities_for_index(self):
        self.reads += 1
        if self.during_read:
            self.during_read()
        return {"devices": [{"id": i, "name": n, "description": "", "model": ""}
                            for i, n in enumerate(self.names, 1)],
                "variables": [], "actions": []}


def _running_manager(provider):
    """A manager past its warmup, without the background threads."""
    m = EntityIndexManager(provider, logger=_LOG, update_interval=0)
    m._initialize_entity_index()
    m.update_now()
    m._running = True
    return m


def test_mark_dirty_then_refresh_rebuilds_once():
    p = _Provider()
    m = _running_manager(p)
    assert p.reads == 1 and m.is_dirty is False
    assert m.refresh_if_dirty() is False           # clean: no rebuild
    assert p.reads == 1
    m.mark_dirty()
    assert m.refresh_if_dirty() is True
    assert p.reads == 2 and m.is_dirty is False
    assert m.refresh_if_dirty() is False           # and only once
    assert p.reads == 2


def test_any_rebuild_clears_the_mark():
    """The periodic rebuild covers a change marked before it started."""
    p = _Provider()
    m = _running_manager(p)
    m.mark_dirty()
    m.update_now()
    assert m.is_dirty is False
    assert m.refresh_if_dirty() is False and p.reads == 2


def test_a_change_during_a_rebuild_is_not_lost():
    p = _Provider()
    m = _running_manager(p)
    m.mark_dirty()
    p.during_read = m.mark_dirty                   # a rename lands mid-rebuild
    m.refresh_if_dirty()
    assert m.is_dirty is True, "the mid-rebuild change was wiped with the old mark"


def test_a_failed_rebuild_stays_dirty():
    p = _Provider()
    m = _running_manager(p)
    m.mark_dirty()

    def _boom():
        raise RuntimeError("IOM walk failed")
    p.during_read = _boom
    assert m.refresh_if_dirty() is False
    assert m.is_dirty is True, "a failed rebuild must be retried by the next search"


def test_nothing_to_rebuild_before_warmup():
    p = _Provider()
    m = EntityIndexManager(p, logger=_LOG, update_interval=0)
    m._initialize_entity_index()
    m.mark_dirty()
    assert m.refresh_if_dirty() is False and p.reads == 0


def test_search_sees_a_rename_as_soon_as_it_is_marked():
    """End to end through the real search handler and the real index."""
    p = _Provider(["Hall Lamp"])
    m = _running_manager(p)
    h = SearchEntitiesHandler(MagicMock(), m.get_entity_index(), logger=_LOG,
                              freshen=m.refresh_if_dirty)

    def names(query):
        return [d["name"] for d in h.search(query)["results"].get("devices", [])]

    assert names("hall lamp") == ["Hall Lamp"]
    p.names = ["Utility Heater"]                   # renamed in Indigo
    assert names("heater") == []                   # not marked: no rebuild per search
    assert p.reads == 1
    m.mark_dirty()                                 # Indigo's callback arrives
    assert names("heater") == ["Utility Heater"]
    assert p.reads == 2


def test_the_handler_wires_search_to_the_manager():
    from mcp_server.mcp_handler import MCPHandler
    h = object.__new__(MCPHandler)
    h.logger = _LOG
    h.data_provider = MagicMock()
    h.entity_index_manager = _running_manager(_Provider())
    h._init_handlers()
    assert h.search_handler._freshen == h.entity_index_manager.refresh_if_dirty


# ── Which changes count ──────────────────────────────────────────────────────

def _dev(**kw):
    base = dict(name="Lamp", folderId=1, enabled=True, description="", model="Plug",
                deviceTypeId="relay", pluginId="com.example", states={"onOffState": False})
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("field,value", [
    ("name", "Lamp 2"), ("folderId", 2), ("enabled", False), ("description", "x"),
    ("model", "Bulb"), ("deviceTypeId", "dimmer"), ("pluginId", "com.other"),
])
def test_a_structural_device_change_counts(field, value):
    assert index_fields_changed("device", _dev(), _dev(**{field: value})) is True


def test_a_state_change_does_not_count():
    assert index_fields_changed("device", _dev(), _dev(states={"onOffState": True})) is False


def test_variable_and_action_group_fields():
    v = SimpleNamespace(name="a", folderId=0, readOnly=False, value="1")
    assert index_fields_changed("variable", v, SimpleNamespace(**{**vars(v), "value": "2"})) is False
    assert index_fields_changed("variable", v, SimpleNamespace(**{**vars(v), "name": "b"})) is True
    g = SimpleNamespace(name="Night", folderId=0, description="")
    assert index_fields_changed("action_group", g, SimpleNamespace(**{**vars(g), "name": "Nite"})) is True
    assert index_fields_changed("action_group", g, g) is False


# ── The plugin's Indigo callbacks ────────────────────────────────────────────

SELF_ID = "com.clives.indigoplugin.claudebridge"


def _plugin():
    mod = load_plugin_module()
    p = object.__new__(mod.Plugin)
    p.pluginId = SELF_ID
    p.logger = _LOG
    manager = MagicMock()
    cache = MagicMock()
    p.mcp_handler = SimpleNamespace(entity_index_manager=manager, tool_cache=cache)
    p.webhooks_enabled = False
    p.webhook_manager = None
    p.webhook_dispatcher = None
    return p, manager, cache


def test_device_rename_marks_the_index():
    p, manager, cache = _plugin()
    p.deviceUpdated(_dev(), _dev(name="Lamp 2"))
    manager.mark_dirty.assert_called_once_with()
    assert "deviceUpdated" in p.base_calls


def test_device_state_change_does_not_mark_the_index():
    p, manager, cache = _plugin()
    p.deviceUpdated(_dev(), _dev(states={"onOffState": True}))
    manager.mark_dirty.assert_not_called()
    cache.note_external_change.assert_called_once_with("device")   # the cache still hears it


def test_own_device_stays_behind_the_loop_guard():
    """The pluginId guard still returns before the cache and the webhooks. A
    rename of our own device may mark the index: that writes nothing."""
    p, manager, cache = _plugin()
    p._webhook_on_device_change = MagicMock()
    own = dict(pluginId=SELF_ID, deviceTypeId="mcpServer")
    p._handle_mcp_server_device_update = MagicMock()
    p.deviceUpdated(_dev(**own), _dev(**own, states={"serverStatus": "Running"}))
    cache.note_external_change.assert_not_called()
    p._webhook_on_device_change.assert_not_called()
    manager.mark_dirty.assert_not_called()
    p.deviceUpdated(_dev(**own), _dev(**own, name="Claude Bridge 2"))
    manager.mark_dirty.assert_called_once_with()
    cache.note_external_change.assert_not_called()


@pytest.mark.parametrize("callback,cache_domain", [
    ("deviceCreated", "device"), ("deviceDeleted", "device"),
    ("variableCreated", "variable"), ("variableDeleted", "variable"),
    ("actionGroupCreated", None), ("actionGroupDeleted", None),
])
def test_create_and_delete_mark_the_index(callback, cache_domain):
    p, manager, cache = _plugin()
    getattr(p, callback)(SimpleNamespace(id=1, name="x"))
    manager.mark_dirty.assert_called_once_with()
    assert callback in p.base_calls, "the base class must still be reached"
    if cache_domain:
        cache.note_external_change.assert_called_once_with(cache_domain)


def test_variable_value_change_does_not_mark_but_rename_does():
    p, manager, cache = _plugin()
    old = SimpleNamespace(name="a", folderId=0, readOnly=False, value="1")
    p.variableUpdated(old, SimpleNamespace(**{**vars(old), "value": "2"}))
    manager.mark_dirty.assert_not_called()
    p.variableUpdated(old, SimpleNamespace(**{**vars(old), "name": "b"}))
    manager.mark_dirty.assert_called_once_with()


def test_action_group_rename_marks_the_index():
    p, manager, _ = _plugin()
    g = SimpleNamespace(name="Night", folderId=0, description="")
    p.actionGroupUpdated(g, g)
    manager.mark_dirty.assert_not_called()
    p.actionGroupUpdated(g, SimpleNamespace(**{**vars(g), "name": "Nite"}))
    manager.mark_dirty.assert_called_once_with()


def test_marking_never_raises_without_a_handler():
    p, _, _ = _plugin()
    p.mcp_handler = None
    p.deviceCreated(SimpleNamespace(id=1, name="x"))    # must not raise
