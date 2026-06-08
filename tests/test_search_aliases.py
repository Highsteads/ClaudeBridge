#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_search_aliases.py
# Description: The type-alias keyword bridge added to the in-memory search store
#              (v2.7.3) must (a) make category words like "light"/"plug"/"motion"
#              find devices by deviceTypeId even when the word isn't in the name,
#              (b) NEVER lower an existing name/description score (parity), and
#              (c) never leak alias text into results.
# Author:      CliveS & Claude Opus 4.8
# Date:        08-06-2026
# Version:     1.0

import pytest

from mcp_server.common.vector_store.main import VectorStore
from mcp_server.common.vector_store.type_aliases import aliases_for, TYPE_ALIASES


# Representative slice of the real estate (deviceTypeId + class as dict(dev) yields).
DEVICES = [
    {"id": 1, "name": "Lounge Lamp",            "deviceTypeId": "z2mLight",          "class": "DimmerDevice"},
    {"id": 2, "name": "Colour Lamp Plug",       "deviceTypeId": "shellyRelay",       "class": "RelayDevice"},
    {"id": 3, "name": "Drive Right Motion",     "deviceTypeId": "zwOnOffSensorType", "class": "SensorDevice"},
    {"id": 4, "name": "Bathroom Boiler Leak",   "deviceTypeId": "z2mSensor",         "class": "SensorDevice"},
    {"id": 5, "name": "Bathroom Radiator",      "deviceTypeId": "ramsesZoneThermostat", "class": "ThermostatDevice"},
    {"id": 6, "name": "Front Door Lock",        "deviceTypeId": "zwLockType",        "class": "RelayDevice"},
    {"id": 7, "name": "Kitchen Light",          "deviceTypeId": "z2mLight",          "class": "DimmerDevice"},
    # Unknown future type, no TYPE_ALIASES entry — must bridge via class fallback.
    {"id": 8, "name": "Mystery Glow",           "deviceTypeId": "futureBulbX",       "class": "DimmerDevice"},
    # Another z2mSensor that is NOT a leak sensor — used to prove the generic
    # catch-all type is not falsely tagged "leak".
    {"id": 9, "name": "Hallway Presence",       "deviceTypeId": "z2mSensor",         "class": "SensorDevice"},
]
VARIABLES = [
    {"id": 100, "name": "battery_optimiser_status"},
    {"id": 101, "name": "light_level"},
]
ACTIONS = [
    {"id": 200, "name": "Goodnight Scene"},
]


@pytest.fixture
def store():
    s = VectorStore(db_path=":test:")
    s.update_embeddings(DEVICES, VARIABLES, ACTIONS)
    return s


def _names(results):
    return [r["name"] for r in results]


# ── Alias bridge: category words find devices by type ───────────────────────

def test_light_finds_dimmers_by_type(store):
    results, _ = store.search("light", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    names = _names(results)
    assert "Lounge Lamp" in names      # z2mLight, no "light" in name — bridged via alias
    assert "Kitchen Light" in names    # also matches by name
    assert "Mystery Glow" in names     # unknown type, bridged via class fallback


def test_plug_finds_relay(store):
    results, _ = store.search("plug", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    assert "Colour Lamp Plug" in _names(results)


def test_motion_finds_motion_sensor(store):
    results, _ = store.search("motion", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    assert "Drive Right Motion" in _names(results)


def test_leak_finds_leak_sensor(store):
    results, _ = store.search("leak", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    assert "Bathroom Boiler Leak" in _names(results)


def test_leak_does_not_falsely_match_generic_z2m_sensors(store):
    # z2mSensor is a catch-all type; "leak" must NOT pull in a non-leak z2mSensor.
    # The real leak sensor is found by NAME, not by tagging the whole type "leak".
    results, _ = store.search("leak", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    assert "Hallway Presence" not in _names(results)


def test_radiator_and_heating_find_thermostat(store):
    for q in ("radiator", "heating", "trv"):
        results, _ = store.search(q, entity_types=["devices"], top_k=10, similarity_threshold=0.3)
        assert "Bathroom Radiator" in _names(results), f"query {q!r} missed the radiator"


# ── Parity: a real name match always beats an alias-only match ──────────────

def test_name_match_outranks_alias_match(store):
    results, _ = store.search("light", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    # "Kitchen Light" / "light_level" contain the word -> 0.95+; alias-only
    # devices (Lounge Lamp) score 0.7. Top result must be a name match.
    assert results[0]["_similarity_score"] >= 0.95


def test_exact_name_still_scores_one(store):
    results, _ = store.search("Kitchen Light", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    top = results[0]
    assert top["name"] == "Kitchen Light"
    assert top["_similarity_score"] == 1.0


def test_unrelated_query_unaffected_by_aliases(store):
    # "bathroom" is a name word, not an alias word — behaviour identical to before.
    results, _ = store.search("bathroom", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    names = _names(results)
    assert "Bathroom Boiler Leak" in names
    assert "Bathroom Radiator" in names
    assert "Lounge Lamp" not in names  # no spurious alias match


# ── Variables / actions have no deviceTypeId -> no aliases ──────────────────

def test_variables_get_no_aliases():
    assert aliases_for({"id": 100, "name": "battery_optimiser_status"}) == ""
    assert aliases_for({"id": 200, "name": "Goodnight Scene"}) == ""


def test_light_does_not_alias_match_a_variable(store):
    # The variable "light_level" matches by NAME (fine), but a variable with no
    # "light" in its name must not be pulled in by device aliases.
    results, _ = store.search("plug", entity_types=["variables"], top_k=10, similarity_threshold=0.3)
    assert results == []  # no variable named/aliased "plug"


# ── No leak: aliases never appear in returned dicts ─────────────────────────

def test_results_do_not_leak_alias_text(store):
    results, _ = store.search("light", entity_types=["devices"], top_k=10, similarity_threshold=0.3)
    for r in results:
        assert "_search_aliases" not in r
        # only the two documented underscore keys are injected
        underscore_keys = {k for k in r if k.startswith("_")}
        assert underscore_keys == {"_similarity_score", "_entity_type"}


# ── Curation sanity ─────────────────────────────────────────────────────────

def test_alias_values_are_lowercase_strings():
    for k, v in TYPE_ALIASES.items():
        assert isinstance(v, str) and v == v.lower(), f"{k} alias must be lowercase"


def test_class_fallback_bridges_unknown_type():
    # No TYPE_ALIASES entry, but RelayDevice class -> switch/plug synonyms.
    al = aliases_for({"deviceTypeId": "someNewRelayX", "class": "RelayDevice"})
    assert "switch" in al and "plug" in al
