#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_search_synonyms.py
# Description: The search synonym layer: "telly" finds the TV, "lounge" the living
#              room, and a literal match still outranks a synonym.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2130_borrows.py (v2.13.0)


from mcp_server.common.entity_index.main import EntityIndex
from mcp_server.common.entity_index.synonyms import variants_for_query


# ── synonym layer ────────────────────────────────────────────────────────────

def test_variants_for_query_basic():
    variants = variants_for_query("telly")
    assert "tv" in variants and "television" in variants
    assert "telly" not in variants


def test_variants_multiword_and_phrase():
    variants = variants_for_query("lounge lamp")
    assert "living room lamp" in variants
    # "lamp" group expands too
    assert "lounge light" in variants


def test_variants_no_match_is_empty():
    assert variants_for_query("sigenmodbustcp") == []
    assert variants_for_query("") == []


def _store_with(devices):
    store = EntityIndex()
    store.load_entities(devices=devices, variables=[], actions=[])
    return store


def test_search_finds_tv_via_telly():
    store = _store_with([
        {"id": 1, "name": "Sony TV Plug", "description": "", "model": ""},
        {"id": 2, "name": "Kitchen Kettle Plug", "description": "", "model": ""},
    ])
    results, _ = store.search("telly", entity_types=["devices"])
    assert results and results[0]["name"] == "Sony TV Plug"


def test_search_finds_living_room_via_lounge():
    store = _store_with([
        {"id": 1, "name": "Living Room Lamp", "description": "", "model": ""},
        {"id": 2, "name": "Garage Light", "description": "", "model": ""},
    ])
    results, _ = store.search("lounge lamp", entity_types=["devices"])
    assert results and results[0]["name"] == "Living Room Lamp"


def test_literal_match_outranks_synonym_match():
    store = _store_with([
        {"id": 1, "name": "Telly Corner Socket", "description": "", "model": ""},
        {"id": 2, "name": "Sony TV Plug", "description": "", "model": ""},
    ])
    results, _ = store.search("telly", entity_types=["devices"])
    assert results[0]["name"] == "Telly Corner Socket"
    names = [r["name"] for r in results]
    assert "Sony TV Plug" in names


def test_search_without_synonyms_unchanged():
    store = _store_with([
        {"id": 1, "name": "Front Door Lock", "description": "", "model": ""},
    ])
    results, _ = store.search("front door", entity_types=["devices"])
    assert results and results[0]["_similarity_score"] == 1.0
