#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_indidb_parse_failures.py
# Description: A database file that will not parse is retried with a growing
#              back-off, and one WARNING is logged once the SAME file (path,
#              mtime, size) has failed three times. It used to be re-parsed
#              every 2 seconds for ever, at DEBUG, with nothing said.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
from types import SimpleNamespace

import pytest

from mcp_server.adapters.indidb import store as store_mod
from mcp_server.adapters.indidb.store import IndiDbStructureStore


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    path = tmp_path / "Broken.indiDb"
    path.write_text("<not xml", encoding="utf-8")
    attempts = []

    def _fail(p):
        attempts.append(p)
        raise ValueError("unparseable")

    clock = {"t": 1000.0}
    monkeypatch.setattr(store_mod, "parse_indidb", _fail)
    monkeypatch.setattr(store_mod, "time", SimpleNamespace(monotonic=lambda: clock["t"]))
    s = IndiDbStructureStore(lambda: str(path), logger=logging.getLogger("t-indidb"),
                             stat_throttle_seconds=0.0)
    return s, attempts, clock, path


def test_an_unchanged_broken_file_is_not_reparsed_on_every_call(rig):
    s, attempts, clock, _ = rig
    for _ in range(20):
        s.get_all_structures("trigger")
    assert len(attempts) == 1
    clock["t"] += 2.5
    s.get_all_structures("trigger")
    assert len(attempts) == 2
    clock["t"] += 5
    s.get_all_structures("trigger")
    assert len(attempts) == 2, "the second back-off is longer"


def test_three_failures_of_the_same_file_warn_once(rig, caplog):
    s, attempts, clock, _ = rig
    with caplog.at_level(logging.DEBUG, logger="t-indidb"):
        for _ in range(6):
            s.get_all_structures("trigger")
            clock["t"] += 1000
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(attempts) >= 4
    assert len(warnings) == 1 and "3 times" in warnings[0].getMessage()


def test_a_changed_file_is_tried_at_once(rig):
    s, attempts, clock, path = rig
    s.get_all_structures("trigger")
    path.write_text("<still not xml, but different", encoding="utf-8")
    s.get_all_structures("trigger")
    assert len(attempts) == 2
