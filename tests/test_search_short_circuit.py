#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_search_short_circuit.py
# Description: search_entities returns a single result only when one name
#              EQUALS the query. Any name merely containing the query also
#              scores 1.0, so "kitchen" used to come back as one device of
#              fourteen (live, 23-09-2026).
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import logging
from unittest.mock import MagicMock

from mcp_server.tools.search_entities.main import SearchEntitiesHandler


def _hit(i, name, score=1.0):
    return {"id": i, "name": name, "_entity_type": "device", "_similarity_score": score}


class _Store:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, entity_types, top_k, similarity_threshold):
        hits = [dict(h) for h in self.hits][:top_k]
        return hits, {"total_found": len(self.hits), "total_returned": len(hits),
                      "truncated": len(self.hits) > top_k}


def _search(hits, query, **kw):
    h = SearchEntitiesHandler(MagicMock(), _Store(hits), logger=logging.getLogger("t"))
    out = h.search(query, **kw)
    return [d["name"] for d in out["results"]["devices"]], out


def test_a_substring_query_returns_every_match():
    hits = [_hit(1, ".Kitchen Spot Lights - NOT USED"), _hit(2, "Kitchen Spot Lights"),
            _hit(3, "Kitchen Left Motion"), _hit(4, "Kitchen Right Motion")]
    names, _ = _search(hits, "kitchen")
    assert len(names) == 4


def test_an_exact_name_returns_just_that_device():
    hits = [_hit(1, "Kitchen Spot Lights - Switch 2"), _hit(2, "Kitchen Spot Lights"),
            _hit(3, "Kitchen Spot Lights Scene")]
    names, out = _search(hits, "kitchen spot lights")
    assert names == ["Kitchen Spot Lights"]
    assert out["total_count"] == 1


def test_two_devices_sharing_a_name_are_both_returned_exact_first():
    hits = [_hit(1, "Patio Light Extra"), _hit(2, "Patio"), _hit(3, "patio ")]
    names, _ = _search(hits, "Patio")
    assert names[:2] == ["Patio", "patio "] and len(names) == 3


def test_shortcut_is_skipped_when_a_filter_follows(monkeypatch):
    seen = {}
    from mcp_server.tools.search_entities import main as m

    def _spy(devices, state_filter):
        seen["n"] = len(devices)
        return devices

    monkeypatch.setattr(m.StateFilter, "filter_by_state", staticmethod(_spy))
    hits = [_hit(1, "Hall Lamp Plug"), _hit(2, "Hall Lamp")]
    names, _ = _search(hits, "hall lamp", state_filter={"onState": True})
    assert seen["n"] == 2
    assert names[0] == "Hall Lamp"      # the exact name still ranks first


# ── The shortcut must not pre-empt the type filter either (09-Aug-2026 review) ─
# QueryParser over-fetches so the filters see candidates 2..50. Truncating to
# the one exact name first threw them away, and an empty answer came back when
# that single hit failed the filter. This was an AST check on the text of
# search(); it now runs the search.

def _classify_by_kind(monkeypatch):
    from mcp_server.tools.search_entities import main as m
    monkeypatch.setattr(m.DeviceClassifier, "classify_device",
                        staticmethod(lambda d: d.get("kind")))


def test_shortcut_is_skipped_when_a_type_filter_follows(monkeypatch):
    _classify_by_kind(monkeypatch)
    hits = [dict(_hit(1, "Hall Lamp"), kind="sensor"),
            dict(_hit(2, "Hall Lamp Plug"), kind="relay")]
    names, _ = _search(hits, "hall lamp", device_types=["relay"])
    assert names == ["Hall Lamp Plug"], (
        "the exact-name shortcut ran ahead of the type filter and discarded the relay")


def test_an_empty_device_types_list_is_no_filter(monkeypatch):
    _classify_by_kind(monkeypatch)
    hits = [dict(_hit(1, "Porch Light"), kind="dimmer"),
            dict(_hit(2, "Porch Sensor"), kind="sensor")]
    names, _ = _search(hits, "porch", device_types=[])
    assert len(names) == 2, "an empty device_types list stripped every device"


# ── Results carry Indigo's current values, not the index's copy (3.0) ──────────

class _Provider:
    def __init__(self, devices, variables=None):
        self.devices, self.variables = devices, variables or {}

    def get_device(self, dev_id):
        return self.devices.get(dev_id)

    def get_variable(self, var_id):
        return self.variables.get(var_id)


def test_device_hits_show_live_state_and_deleted_ones_drop_out():
    stale = [_hit(1, "Hall Lamp"), _hit(2, "Hall Lamp Plug")]
    stale[0]["onState"] = False
    provider = _Provider({1: {"id": 1, "name": "Hall Lamp", "onState": True}})   # 2 deleted
    h = SearchEntitiesHandler(provider, _Store(stale), logger=logging.getLogger("t"))
    out = h.search("hall lamp", detail="full")
    devs = out["results"]["devices"]
    assert [d["name"] for d in devs] == ["Hall Lamp"]
    assert devs[0]["onState"] is True


def test_variable_hits_show_the_live_value():
    hit = {"id": 7, "name": "Mode", "value": "old", "_entity_type": "variable",
           "_similarity_score": 1.0}
    provider = _Provider({}, {7: {"id": 7, "name": "Mode", "value": "new"}})
    h = SearchEntitiesHandler(provider, _Store([hit]), logger=logging.getLogger("t"))
    out = h.search("mode")
    assert out["results"]["variables"][0]["value"] == "new"


def test_a_state_filter_judges_the_live_state(monkeypatch):
    from mcp_server.tools.search_entities import main as m
    seen = {}

    def _spy(devices, state_filter):
        seen["on"] = [d.get("onState") for d in devices]
        return devices

    monkeypatch.setattr(m.StateFilter, "filter_by_state", staticmethod(_spy))
    stale = [_hit(1, "Hall Lamp")]
    stale[0]["onState"] = False
    provider = _Provider({1: {"id": 1, "name": "Hall Lamp", "onState": True}})
    h = SearchEntitiesHandler(provider, _Store(stale), logger=logging.getLogger("t"))
    h.search("hall lamp", state_filter={"onState": True})
    assert seen["on"] == [True]
