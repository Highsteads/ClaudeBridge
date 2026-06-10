#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_subscription_store.py
# Description: Persistence tests for the webhook SubscriptionStore: 0600 perms
#              on save AND re-asserted on load (the v2.8.6 restore-from-backup
#              fix), atomic corrupt-file handling (backup + empty load, never
#              a crash), and secrets surviving a save/load roundtrip.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import logging
import os
import stat

from mcp_server.webhooks.subscription_model import Subscription
from mcp_server.webhooks.subscription_store import SubscriptionStore

_LOGGER = logging.getLogger("test-substore")


def _perm(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _store(tmp_path):
    return SubscriptionStore(str(tmp_path / "webhooks.json"), logger=_LOGGER)


def _sub(**kw):
    defaults = dict(webhook_url="https://hooks.example.com/x",
                    entity_type="device", entity_id=123,
                    auth_token="bearer-secret")
    defaults.update(kw)
    return Subscription(**defaults)


def test_save_writes_0600(tmp_path):
    store = _store(tmp_path)
    store.save([_sub()])
    assert _perm(str(tmp_path / "webhooks.json")) == 0o600


def test_load_reasserts_0600_on_loosened_file(tmp_path):
    # A file restored from a backup (Time Machine, manual cp) keeps the
    # backup's permissions — load() must clamp it back down because the file
    # holds signing keys.
    store = _store(tmp_path)
    store.save([_sub()])
    path = str(tmp_path / "webhooks.json")
    os.chmod(path, 0o644)
    assert _perm(path) == 0o644
    subs = store.load()
    assert _perm(path) == 0o600
    assert len(subs) == 1


def test_roundtrip_preserves_secrets_and_identity(tmp_path):
    store = _store(tmp_path)
    original = _sub(description="leak alert")
    store.save([original])
    loaded = store.load()[0]
    assert loaded.subscription_id == original.subscription_id
    assert loaded.signing_key == original.signing_key      # must persist or
    assert loaded.auth_token == original.auth_token        # receivers break
    assert loaded.webhook_url == original.webhook_url
    assert loaded.entity_id == 123
    assert loaded.enabled is True


def test_missing_file_loads_empty(tmp_path):
    assert _store(tmp_path).load() == []


def test_corrupt_file_is_backed_up_and_loads_empty(tmp_path):
    path = tmp_path / "webhooks.json"
    path.write_text("{definitely not json", encoding="utf-8")
    store = _store(tmp_path)
    assert store.load() == []
    assert not path.exists()                               # moved aside…
    assert (tmp_path / "webhooks.json.corrupt").exists()   # …never deleted


def test_unparseable_record_is_skipped_not_fatal(tmp_path):
    store = _store(tmp_path)
    good = _sub()
    store.save([good])
    # Corrupt one record in an otherwise valid file: a list where a dict is
    # expected makes Subscription.from_dict raise for that record only.
    import json
    path = str(tmp_path / "webhooks.json")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    payload["subscriptions"].append(["not", "a", "dict"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].subscription_id == good.subscription_id
