#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_entity_index_rebuilds.py
# Description: Search-index rebuilds run one at a time, so the one that read
#              Indigo last is the one that loads last, a queued rebuild that a
#              later one already covered is skipped, and any failed rebuild
#              leaves the index marked dirty so the next search retries.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import threading
import time

import pytest

from mcp_server.common.entity_index import EntityIndexManager

_LOG = logging.getLogger("test-entity-index-rebuilds")


class _Provider:
    """Hands out snapshots in order. The first read blocks until released,
    standing in for a slow IOM walk that another rebuild overtakes."""

    def __init__(self):
        self.calls = 0
        self.release = threading.Event()
        self.first_entered = threading.Event()
        self.fail = False

    def get_all_entities_for_index(self):
        self.calls += 1
        n = self.calls
        if self.fail:
            raise RuntimeError("IOM walk failed")
        if n == 1:
            self.first_entered.set()
            self.release.wait(5)
        return {"devices": [{"id": n, "name": f"snapshot {n}"}], "variables": [], "actions": []}


class _Index:
    def __init__(self):
        self.loaded = []

    def load_entities(self, devices, variables, actions):
        self.loaded.append(devices[0]["name"])

    def close(self):
        pass


def _manager(provider):
    m = EntityIndexManager(data_provider=provider, logger=_LOG, update_interval=0)
    m.entity_index = _Index()
    return m


def test_an_overtaken_rebuild_cannot_load_older_data_last():
    provider = _Provider()
    m = _manager(provider)
    slow = threading.Thread(target=m.update_now)
    slow.start()
    assert provider.first_entered.wait(5)
    fast = threading.Thread(target=m.update_now)     # asked while the slow one reads
    fast.start()
    time.sleep(0.3)                                   # an unserialised rebuild would finish now
    provider.release.set()
    slow.join(5)
    fast.join(5)
    assert m.entity_index.loaded == ["snapshot 1", "snapshot 2"], \
        "the older snapshot was loaded after the newer one"


def test_two_requests_queued_behind_one_rebuild_share_the_next():
    """Both asked while rebuild 1 was reading. Whichever runs next (rebuild 2)
    started after both asked, so the other has nothing left to do."""
    provider = _Provider()
    m = _manager(provider)
    first = threading.Thread(target=m.update_now)
    first.start()
    assert provider.first_entered.wait(5)
    queued = [threading.Thread(target=m.update_now) for _ in range(2)]
    for t in queued:
        t.start()
    time.sleep(0.2)
    provider.release.set()
    for t in [first, *queued]:
        t.join(5)
    assert provider.calls == 2, f"expected 2 IOM walks, got {provider.calls}"
    assert m.entity_index.loaded == ["snapshot 1", "snapshot 2"]


def test_a_dirty_index_is_rebuilt_even_when_covered():
    provider = _Provider()
    provider.release.set()
    m = _manager(provider)
    m.update_now()
    m.mark_dirty()
    before = provider.calls
    m.update_now()
    assert provider.calls == before + 1 and not m.is_dirty


@pytest.mark.parametrize("entry", ["update_now", "background"])
def test_a_failed_rebuild_leaves_the_index_dirty(entry):
    provider = _Provider()
    provider.release.set()
    provider.fail = True
    m = _manager(provider)
    assert not m.is_dirty
    if entry == "update_now":
        with pytest.raises(RuntimeError):
            m.update_now()
    else:
        # The refresh_async worker swallows the exception; the flag must still be set.
        m._running = True
        m.refresh_async()
        for t in list(m._refresh_threads):
            t.join(5)
    assert m.is_dirty, "a failed rebuild was trusted as current"
