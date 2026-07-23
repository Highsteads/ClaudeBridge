#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2130_borrows.py
# Description: Tests for the v2.13.0 mcp-lite borrow batch: indidb anomaly
#              counter + path-keyed cache, device_history column allowlist +
#              PK-range window + query_only, and the search synonym layer.
# Author:      CliveS & Claude Opus 4.8
# Date:        23-07-2026
# Version:     1.0

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.adapters.indidb.parser import parse_indidb
from mcp_server.adapters.indidb.store import IndiDbStructureStore
from mcp_server.common.vector_store.main import VectorStore
from mcp_server.common.vector_store.synonyms import variants_for_query

from test_indidb_adapter import SYNTHETIC_DB, TRIG_MOTION


# ── indidb: anomaly counter ──────────────────────────────────────────────────

BROKEN_TRIGGER = """\
        <Trigger type="dict">
            <Name type="string">Corrupt No-ID Trigger</Name>
            <Class type="integer">501</Class>
        </Trigger>
"""


@pytest.fixture()
def broken_db(tmp_path):
    content = SYNTHETIC_DB.replace(
        "<TriggerList type=\"vector\">",
        "<TriggerList type=\"vector\">\n" + BROKEN_TRIGGER)
    path = tmp_path / "Broken.indiDb"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_parser_counts_skipped_records(broken_db):
    parsed = parse_indidb(broken_db)
    assert parsed.skipped_records == 1
    # The good trigger still parses.
    assert TRIG_MOTION in parsed.triggers


def test_store_surfaces_skipped_in_freshness(broken_db):
    store = IndiDbStructureStore(lambda: broken_db, stat_throttle_seconds=0.0)
    freshness = store.freshness()
    assert freshness["available"] is True
    assert freshness["skipped_records"] == 1
    assert "skipped" in freshness["note"]


def test_clean_parse_reports_no_skips(tmp_path):
    path = tmp_path / "Clean.indiDb"
    path.write_text(SYNTHETIC_DB, encoding="utf-8")
    store = IndiDbStructureStore(lambda: str(path), stat_throttle_seconds=0.0)
    freshness = store.freshness()
    assert "skipped_records" not in freshness


# ── indidb: path in the cache key ────────────────────────────────────────────

def test_store_invalidates_on_database_switch(tmp_path):
    db_a = tmp_path / "A.indiDb"
    db_b = tmp_path / "B.indiDb"
    db_a.write_text(SYNTHETIC_DB, encoding="utf-8")
    # Same-LENGTH name so both files have identical size — the point of the
    # test is that only the path distinguishes them.
    db_b.write_text(SYNTHETIC_DB.replace("Motion Turns On Lamp",
                                         "Motion Turns Off Fan"),
                    encoding="utf-8")
    # Same mtime AND size would previously satisfy the (mtime,size)-only key.
    same_time = time.time() - 100
    os.utime(db_a, (same_time, same_time))
    os.utime(db_b, (same_time, same_time))
    assert os.path.getsize(db_a) == os.path.getsize(db_b)

    current = {"path": str(db_a)}
    store = IndiDbStructureStore(lambda: current["path"],
                                 stat_throttle_seconds=0.0)
    assert store.get_structure("trigger", TRIG_MOTION)["Name"] == "Motion Turns On Lamp"
    current["path"] = str(db_b)  # server switches databases
    assert store.get_structure("trigger", TRIG_MOTION)["Name"] == "Motion Turns Off Fan"


# ── device_history: allowlist, PK-range, query_only ──────────────────────────

@pytest.fixture()
def history_handler(tmp_path, monkeypatch):
    """PluginDevToolsHandler wired at a synthetic SQL Logger database."""
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    db_path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE device_history_123 ("
        "id INTEGER PRIMARY KEY, ts TIMESTAMP, batterysoc REAL, pvpower REAL)")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(200):
        ts = (now - timedelta(minutes=200 - i)).isoformat(sep=" ")
        rows.append((i + 1, ts, 50.0 + i * 0.1, None if i % 2 else i * 10.0))
    conn.executemany("INSERT INTO device_history_123 VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()

    monkeypatch.setattr(mod, "_sql_logger_db", lambda: db_path)
    handler = mod.PluginDevToolsHandler(data_provider=None)
    return handler


def test_history_unknown_column_is_hard_error(history_handler):
    result = history_handler.device_history(123, columns=["batterySoc"])
    assert result["success"] is False
    assert "batterySoc" in result["error"]
    assert "batterysoc" in result["error"]  # valid set named, lowercase


def test_history_valid_columns_and_window(history_handler):
    result = history_handler.device_history(123, hours=1,
                                            columns=["batterysoc"])
    assert result["success"] is True
    assert result["columns"][0] == "ts"
    # 1-hour window over minute-spaced rows: about 60, never all 200.
    assert 50 <= result["row_count"] <= 65
    assert all(row["batterysoc"] is not None for row in result["rows"])


def test_history_probe_branch_uses_window(history_handler):
    result = history_handler.device_history(123, hours=1)
    assert result["success"] is True
    assert "batterysoc" in result["columns"]
    assert "pvpower" in result["columns"]


def test_history_empty_window(history_handler, monkeypatch):
    # All rows are older than a tiny window anchored far in the future is
    # impossible here, so instead: request rows newer than now+1h via a
    # 0-hour... hours is clamped to >=1; simulate instead a device whose
    # rows all predate the window by shrinking to 1 hour on an old-only table.
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod
    db_path = mod._sql_logger_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE device_history_456 ("
        "id INTEGER PRIMARY KEY, ts TIMESTAMP, watts REAL)")
    old = (datetime.now(timezone.utc).replace(tzinfo=None)
           - timedelta(days=30)).isoformat(sep=" ")
    conn.execute("INSERT INTO device_history_456 VALUES (1, ?, 42.0)", (old,))
    conn.commit()
    conn.close()
    result = history_handler.device_history(456, hours=1, columns=["watts"])
    assert result["success"] is True
    assert result["row_count"] == 0


def test_rowid_floor_binary_search(history_handler):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod
    db_path = mod._sql_logger_db()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = (now - timedelta(minutes=30)).isoformat(sep=" ")
    floor_id = history_handler._rowid_floor_for_ts(cur, "device_history_123", cutoff)
    # Row ids are minute-spaced ending ~now: the floor should sit ~30 rows
    # from the top (id 200), i.e. around id 171.
    assert 168 <= floor_id <= 174
    cur.execute("SELECT MIN(ts) FROM device_history_123 WHERE id >= ?", (floor_id,))
    assert cur.fetchone()[0] >= cutoff
    conn.close()


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
    store = VectorStore(db_path="/dev/null")
    store.update_embeddings(devices=devices, variables=[], actions=[])
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
