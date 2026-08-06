#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_raw_server_api.py
# Description: Tests for the v2.18.0 raw-server-access batch — the audit walker
#              covering top-level indigo.<fn> callables (the blind spot that hid
#              the rawServer* family), the read-only guard on raw_server_request,
#              and the general indigo->plain deep converter.
# Author:      CliveS & Claude Opus 5
# Date:        06-08-2026
# Version:     1.0

import sys
import types
from unittest.mock import MagicMock

from mcp_server.common.indigo_plain import MAX_DEPTH, to_plain
from mcp_server.tools.system_tools.system_tools_handler import SystemToolsHandler

from test_dispatch import _LOGGER


# ── Boost.Python-alike containers ─────────────────────────────────────────────
# The real indigo.Dict/indigo.List are NOT dict/list subclasses. That is the
# whole reason the converter exists, so the fakes must not be subclasses either
# or the tests would pass against a converter that only ever handled real dicts.

class FakeIndigoDict:
    def __init__(self, data):
        self._d = dict(data)

    def keys(self):
        return self._d.keys()

    def __getitem__(self, k):
        return self._d[k]


class FakeIndigoList:
    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


# ── the converter ─────────────────────────────────────────────────────────────

def test_to_plain_passes_scalars_through():
    assert to_plain(None) is None
    assert to_plain(True) is True
    assert to_plain(3) == 3
    assert to_plain(2.5) == 2.5
    assert to_plain("hello") == "hello"


def test_to_plain_converts_nested_indigo_containers():
    raw = FakeIndigoDict({
        "ID": 1089773899,
        "PageElemList": FakeIndigoList([
            FakeIndigoDict({"Name": "Lamp", "ServerIndex": 0}),
            FakeIndigoDict({"Name": "Door", "ServerIndex": 1}),
        ]),
    })
    out = to_plain(raw)
    assert isinstance(out, dict) and isinstance(out["PageElemList"], list)
    assert out["ID"] == 1089773899
    assert out["PageElemList"][1] == {"Name": "Door", "ServerIndex": 1}


def test_to_plain_does_not_shred_a_string_into_characters():
    # A str is iterable; a naive sequence branch turns "abc" into ["a","b","c"].
    assert to_plain(FakeIndigoDict({"Name": "abc"})) == {"Name": "abc"}


def test_to_plain_degrades_unknown_types_rather_than_raising():
    class Exotic:
        def __repr__(self):
            return "<exotic>"

    assert to_plain(Exotic()) == "<exotic>"


def test_to_plain_bounds_runaway_depth():
    node = FakeIndigoDict({"leaf": 1})
    for _ in range(MAX_DEPTH + 5):
        node = FakeIndigoDict({"child": node})
    assert "max depth exceeded" in repr(to_plain(node))


# ── the read-only guard ───────────────────────────────────────────────────────

def _handler():
    return SystemToolsHandler(data_provider=MagicMock(), logger=_LOGGER)


def test_raw_server_request_refuses_a_mutating_name(monkeypatch):
    ind = sys.modules["indigo"]
    called = []
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: called.append(a), raising=False)

    result = _handler().raw_server_request("SetControlPage", {"ID": 1})
    assert result["success"] is False
    assert "refused" in result["error"]
    # The point is that it never reached the server, not merely that it reported failure.
    assert called == []


def test_raw_server_request_refuses_a_non_identifier(monkeypatch):
    ind = sys.modules["indigo"]
    called = []
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: called.append(a), raising=False)

    for bad in ["Get Control Page", "Get;drop", "", "Get-Page"]:
        result = _handler().raw_server_request(bad)
        assert result["success"] is False, bad
    assert called == []


def test_raw_server_request_refuses_non_object_args(monkeypatch):
    ind = sys.modules["indigo"]
    called = []
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: called.append(a), raising=False)

    result = _handler().raw_server_request("GetControlPage", "ID=1")
    assert result["success"] is False and "args" in result["error"]
    assert called == []


def test_raw_server_request_passes_a_get_through_and_converts(monkeypatch):
    ind = sys.modules["indigo"]
    seen = {}

    def fake(name, args=None):
        seen["name"], seen["args"] = name, args
        return FakeIndigoDict({"ID": 7, "PageElemList": FakeIndigoList([
            FakeIndigoDict({"Name": "Lamp"})])})

    monkeypatch.setattr(ind, "rawServerRequest", fake, raising=False)

    result = _handler().raw_server_request("GetControlPage",
                                           {"ID": 7, "GetPageFlags": 65538})
    assert result["success"] is True
    assert seen["name"] == "GetControlPage"
    assert seen["args"] == {"ID": 7, "GetPageFlags": 65538}
    assert result["result"]["PageElemList"] == [{"Name": "Lamp"}]
    assert "unsupported" in result["note"]


def test_raw_server_request_reports_a_missing_api(monkeypatch):
    ind = sys.modules["indigo"]
    monkeypatch.delattr(ind, "rawServerRequest", raising=False)
    result = _handler().raw_server_request("GetControlPage")
    assert result["success"] is False and "not present" in result["error"]


# ── the audit blind spot ──────────────────────────────────────────────────────

def test_audit_api_coverage_walks_top_level_functions(monkeypatch):
    """The regression this batch exists for.

    Five undocumented rawServer* callables sit at indigo.<name>, outside every
    command namespace, so the namespace-only walk reported '0 new, 0 removed'
    while never having seen them. Fails against any walker that only descends
    namespaces.
    """
    ind = sys.modules["indigo"]

    def top_level_fn():
        return None

    monkeypatch.setattr(ind, "aNovelTopLevelFunction", top_level_fn, raising=False)
    monkeypatch.setattr(ind, "server",
                        types.SimpleNamespace(version="2025.2.0"), raising=False)

    result = _handler().audit_api_coverage()
    assert result["success"] is True
    assert "aNovelTopLevelFunction" in result["new_since_baseline"]


def test_audit_api_coverage_excludes_classes_and_modules(monkeypatch):
    """Classes and modules leak into indigo's namespace (indigo.Dict, and stdlib
    imports such as sys/socket). A class is callable, so without the filter the
    baseline would churn on every one of them."""
    ind = sys.modules["indigo"]

    class ANovelClass:
        pass

    monkeypatch.setattr(ind, "ANovelClass", ANovelClass, raising=False)
    monkeypatch.setattr(ind, "aNovelModule", types.ModuleType("x"), raising=False)
    monkeypatch.setattr(ind, "server",
                        types.SimpleNamespace(version="2025.2.0"), raising=False)

    result = _handler().audit_api_coverage()
    assert "ANovelClass" not in result["new_since_baseline"]
    assert "aNovelModule" not in result["new_since_baseline"]


def test_baseline_carries_the_known_top_level_functions():
    """The seven live top-level callables are in the frozen baseline, so a clean
    audit means 'nothing changed' rather than 'we have never looked'."""
    from mcp_server.tools.system_tools.api_baseline import API_BASELINE

    for name in ("rawServerRequest", "rawServerCommand",
                 "rawServerRequestPacketXml", "rawServerCommandPacketXml",
                 "acquireCallbackCompleteHandler"):
        assert name in API_BASELINE, name
