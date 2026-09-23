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
