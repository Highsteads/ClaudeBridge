#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2201_medium_fixes.py
# Description: Regression tests for the medium-severity batch of the 09-Aug-2026
#              deep review. Each test states the wrong behaviour it pins down.
# Author:      CliveS & Claude Opus 5
# Date:        09-08-2026
# Version:     1.0

import ast
import os

import pytest

from conftest import SERVER_PLUGIN


# ── Bools must never be accepted as entity IDs ───────────────────────────────
# bool subclasses int, so an isinstance(x, int) check waves True/False through
# as IDs 1 and 0. folder_id 0 is a REAL destination (root), which is what makes
# a stray `false` dangerous rather than merely wrong.

def test_extended_tools_coerce_id_rejects_bools():
    from mcp_server.tools.extended_tools.extended_tools_handler import _coerce_id

    assert _coerce_id(42) == 42
    assert _coerce_id("42") == 42
    for bad in (True, False):
        with pytest.raises(ValueError):
            _coerce_id(bad)


@pytest.mark.parametrize("module_path,func_name,arg_name", [
    ("mcp_server/tools/variable_control/variable_control_handler.py",
     "update", "variable_id"),
    ("mcp_server/tools/action_control/action_control_handler.py",
     "execute", "action_group_id"),
])
def test_handlers_check_bool_before_int(module_path, func_name, arg_name):
    """The bool guard must come BEFORE the isinstance(int) acceptance."""
    with open(os.path.join(SERVER_PLUGIN, module_path), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert fn is not None, f"{func_name} not found in {module_path}"
    src = ast.unparse(fn)
    assert f"isinstance({arg_name}, bool)" in src, (
        f"{func_name} accepts a bool as {arg_name} — True/False would act on "
        f"entity 1 or 0"
    )


# ── Indigo variables are strings, with Indigo's own conventions ──────────────

def test_variable_string_conversion_is_shared_and_correct():
    """create_variable used a bare str() and wrote "True"/"None".

    The update path normalised these in v2.10.1 and the create path was missed,
    so the two are now one helper.
    """
    from mcp_server.adapters.indigo_data_provider import _to_variable_string

    assert _to_variable_string(True) == "true"      # not "True"
    assert _to_variable_string(False) == "false"
    assert _to_variable_string(None) == ""          # not "None"
    assert _to_variable_string(21.5) == "21.5"
    assert _to_variable_string("on") == "on"


# ── State filtering ──────────────────────────────────────────────────────────

def test_unknown_operator_fails_closed():
    """A typo'd operator used to make the condition a no-op that matched all."""
    from mcp_server.common.state_filter import StateFilter

    entity = {"id": 1, "states": {"temperature": "21.5"}}
    assert StateFilter.matches_state(entity, {"temperature": {"gte_": 100}}) is False


def test_known_operators_still_match_after_the_fail_closed_change():
    """Guards the regression the fail-closed default first introduced.

    An `elif op == "eq" and not matched` chain sends a PASSING eq to the else,
    so adding `else: return False` broke every successful equality match. The
    branches now separate operator identity from outcome.
    """
    from mcp_server.common.state_filter import StateFilter

    entity = {"id": 1, "states": {"temperature": "21.5", "mode": "heat"}}
    assert StateFilter.matches_state(entity, {"temperature": {"eq": 21.5}}) is True
    assert StateFilter.matches_state(entity, {"temperature": {"gt": 20}}) is True
    assert StateFilter.matches_state(entity, {"temperature": {"lte": 22}}) is True
    assert StateFilter.matches_state(entity, {"mode": {"ne": "cool"}}) is True
    assert StateFilter.matches_state(entity, {"mode": {"contains": "hea"}}) is True
    assert StateFilter.matches_state(entity, {"mode": {"regex": "^h"}}) is True


def test_bool_condition_matches_a_stringy_boolean_state():
    """Plugins publish booleans as the strings 'true'/'True'; float() raises."""
    from mcp_server.common.state_filter import StateFilter

    for raw in ("true", "True", "1", "on"):
        entity = {"id": 1, "states": {"occupied": raw}}
        assert StateFilter.matches_state(entity, {"occupied": {"eq": True}}) is True
        assert StateFilter.matches_state(entity, {"occupied": {"eq": False}}) is False

    # An unrecognised string is NO MATCH — never a default.
    entity = {"id": 1, "states": {"occupied": "sort of"}}
    assert StateFilter.matches_state(entity, {"occupied": {"eq": True}}) is False
    assert StateFilter.matches_state(entity, {"occupied": {"eq": False}}) is False


# ── Zero is a reading ────────────────────────────────────────────────────────

def test_first_present_helper_keeps_a_legitimate_zero():
    """`or` chains reported a flat battery or no sun as 'unavailable'."""
    from mcp_server.tools.home_status.home_status_handler import _first

    assert _first({"batterySOC": 0}, "batterySOC", "soc") == 0
    assert _first({"batterySOC": None, "soc": 0.0}, "batterySOC", "soc") == 0.0
    assert _first({}, "batterySOC", "soc") is None
    assert _first({"soc": 55}, "batterySOC", "soc") == 55


# ── indigo.Dict / indigo.List must survive JSON encoding ─────────────────────

class _FakeIndigoList:
    """Stands in for indigo.List: iterable, but NOT a list subclass."""

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


class _FakeIndigoDict:
    """Stands in for indigo.Dict: has keys(), but NOT a dict subclass."""

    def __init__(self, mapping):
        self._m = dict(mapping)

    def keys(self):
        return self._m.keys()

    def __getitem__(self, key):
        return self._m[key]


def test_encoder_does_not_silently_flatten_indigo_containers():
    """These are Boost.Python types, so the __dict__ fallback yielded {}."""
    import json

    from mcp_server.common.json_encoder import safe_json_dumps

    payload = _FakeIndigoDict({"devices": _FakeIndigoList([1, 2, 3])})
    out = json.loads(safe_json_dumps(payload))
    assert out == {"devices": [1, 2, 3]}, (
        "a nested indigo container serialised to {} — the documented silent-loss trap"
    )


# ── InfluxQL: the unquoted parameters need an allowlist, not escaping ────────

def test_aggregation_and_interval_are_allowlisted():
    from mcp_server.common.influxdb.queries import InfluxDBQueryBuilder

    b = InfluxDBQueryBuilder()
    q = b.build_aggregation_query("Lamp", "brightness", "mean", group_by_time="1h")
    assert "MEAN(" in q
    assert "GROUP BY time(1h)" in q

    with pytest.raises(ValueError):
        b.build_aggregation_query("Lamp", "brightness",
                                  "MEAN(x) FROM y; DROP MEASUREMENT z --")
    with pytest.raises(ValueError):
        b.build_aggregation_query("Lamp", "brightness", "mean",
                                  group_by_time="1h) --")


# ── The exact-match short-circuit must not pre-empt the filters ──────────────

def test_short_circuit_skipped_when_a_filter_will_run():
    """QueryParser over-fetches SO the filters see candidates 2..50.

    Truncating to one first threw them away, and an empty answer came back when
    the single top hit failed the filter.
    """
    src_path = os.path.join(SERVER_PLUGIN, "mcp_server", "tools",
                            "search_entities", "main.py")
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "search")
    src = ast.unparse(fn)
    assert "device_types is None and state_filter is None" in src, (
        "the 0.95 short-circuit still runs ahead of the type/state filters"
    )
    assert "if not device_types:" in src, (
        "an empty device_types list still reaches the filter and strips every device"
    )


# ── Cache invalidation must cover every mutator ──────────────────────────────

def test_update_writers_invalidate_their_caches():
    """Triggers/schedules/action groups have no domain counter, so nothing else
    drops their buckets — a renamed trigger read stale for the whole TTL."""
    from mcp_server.common.tool_cache import _INVALIDATION_MAP

    for tool in ("update_trigger", "update_schedule", "update_action_group"):
        assert tool in _INVALIDATION_MAP, f"{tool} invalidates nothing"
        assert _INVALIDATION_MAP[tool], f"{tool} maps to an empty bucket set"


# ── A sensitive tool's failure must not ship the secret by another name ──────

def test_error_scrub_drops_traceback_and_output():
    """Replacing only `error` left `traceback` carrying the same text verbatim."""
    import json

    from mcp_server.mcp_handler import MCPHandler

    raw = json.dumps({
        "success":   False,
        "error":     "auth failed for sk-secret-123",
        "traceback": "Traceback...\nRuntimeError: auth failed for sk-secret-123",
        "stdout":    "printing sk-secret-123",
        "stderr":    "sk-secret-123",
        "path":      "/Library/.../Nightly.py",
        "timed_out": True,
    })
    out = json.loads(MCPHandler._scrub_error_result(raw))

    assert out["success"] is False
    assert out["timed_out"] is True          # control flow survives
    for leaked in ("traceback", "stdout", "stderr", "path"):
        assert leaked not in out, f"{leaked} survived the scrub"
    assert "sk-secret-123" not in json.dumps(out)


# ── A deployed proxy carrying a live token must not be world-readable ────────

def test_install_chmods_the_deployed_proxy():
    path = os.path.join(SERVER_PLUGIN, "install.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "_chmod_600" in src and "0o600" in src, (
        "install.py writes the live bearer token into the proxy without "
        "tightening its permissions"
    )
    tree = ast.parse(src)
    for fn_name in ("install_proxy_script", "patch_proxy_bearer_token"):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
        assert fn is not None, f"{fn_name} not found"
        assert "_chmod_600" in ast.unparse(fn), f"{fn_name} leaves the proxy readable"
