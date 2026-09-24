#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_resolution.py
# Description: A device NAME resolves to one device or is refused. Words in the
#              name must not set the search's result count ("Landing One" read
#              as "one result" and returned "Landing One Nightlight"), and a
#              lone spelling-similarity match ("Landing Two" -> "Landing One")
#              is named back to the caller, never switched.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp_server.tools.search_entities.main import SearchEntitiesHandler
from mcp_server.toolsets.devices import resolve_device, resolve_device_for_control


def _d(i, name, score):
    return {"id": i, "name": name, "relevance_score": score}


# ── resolve_device_for_control ───────────────────────────────────────────────

def test_a_single_loose_match_is_refused_with_the_candidate_named():
    dev, refusal = resolve_device_for_control("Landing Two", [_d(4, "Landing One", 0.82)])
    assert dev is None
    assert "Landing One" in refusal["error"] and "nothing was switched" in refusal["error"]
    assert refusal["candidates"][0]["id"] == 4


def test_a_single_match_holding_every_word_is_used():
    dev, refusal = resolve_device_for_control("garage relay",
                                              [_d(1, "Garage Door Relay", 0.95)])
    assert refusal is None and dev["id"] == 1


def test_a_synonym_match_is_not_acted_on():
    dev, refusal = resolve_device_for_control("telly", [_d(9, "TV Plug", 0.9)])
    assert dev is None and "TV Plug" in refusal["error"]


# ── the search behind it ─────────────────────────────────────────────────────

class _Store:
    def __init__(self, hits):
        self.hits, self.top_k = hits, None

    def search(self, query, entity_types, top_k, similarity_threshold):
        self.top_k = top_k
        hits = [dict(h) for h in self.hits][:top_k]
        return hits, {"total_found": len(self.hits), "total_returned": len(hits),
                      "truncated": len(self.hits) > top_k}


def _hit(i, name):
    return {"id": i, "name": name, "_entity_type": "device", "_similarity_score": 1.0}


def test_a_word_in_the_query_no_longer_sets_the_count_when_top_k_is_given():
    store = _Store([_hit(1, "Landing One Nightlight"), _hit(2, "Landing One")])
    names = {1: "Landing One Nightlight", 2: "Landing One"}
    provider = MagicMock()
    provider.get_device = lambda i: {"id": i, "name": names[i]}
    handler = SearchEntitiesHandler(provider, store, logger=logging.getLogger("t"))
    handler.search("Landing One", entity_types=["devices"], top_k=50)
    assert store.top_k == 50
    handler.search("Landing One", entity_types=["devices"])
    assert store.top_k == 1, "without the override the parser still reads 'one'"


def test_resolve_device_asks_for_a_fixed_count_and_finds_the_exact_name():
    seen = {}

    def _search(query=None, entity_types=None, detail=None, top_k=None, **_):
        seen["top_k"] = top_k
        return {"results": {"devices": [_d(1, "Landing One Nightlight", 1.0),
                                        _d(2, "Landing One", 1.0)]}}

    ctx = SimpleNamespace(search_handler=SimpleNamespace(search=_search))
    device_id, match, refusal = resolve_device(ctx, "Landing One")
    assert refusal is None and device_id == 2 and match["matched_device"] == "Landing One"
    assert seen["top_k"] >= 50
