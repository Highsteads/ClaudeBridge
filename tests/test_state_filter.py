#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_state_filter.py
# Description: Ordering operators (gt/gte/lt/lte) must not raise on string/None
#              state values — Indigo serialises many states as strings.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.0


from mcp_server.common.state_filter import StateFilter


def test_gt_on_string_state_does_not_raise_and_matches():
    # Indigo stores e.g. battery as the string "80".
    entity = {"name": "Sensor", "states": {"battery": "80"}}
    assert StateFilter.matches_state(entity, {"battery": {"gt": 50}}) is True
    assert StateFilter.matches_state(entity, {"battery": {"gt": 90}}) is False


def test_ordering_on_none_returns_false_not_raises():
    entity = {"name": "Sensor", "states": {"battery": None}}
    # Must not raise TypeError — non-numeric/None is "does not match".
    assert StateFilter.matches_state(entity, {"battery": {"lt": 20}}) is False


def test_ordering_on_nonnumeric_string_returns_false():
    entity = {"name": "Dev", "states": {"mode": "auto"}}
    assert StateFilter.matches_state(entity, {"mode": {"gte": 5}}) is False


def test_numeric_float_string_compares_correctly():
    entity = {"name": "Therm", "states": {"temp": "21.5"}}
    assert StateFilter.matches_state(entity, {"temp": {"gte": 21.5}}) is True
    assert StateFilter.matches_state(entity, {"temp": {"lt": 21.5}}) is False


# ── #36 state_filter: eq/ne are numeric-aware ────────────────────────────────

def test_loose_eq_numeric_string_vs_number():
    from mcp_server.common.state_filter import StateFilter
    assert StateFilter._loose_eq("72.5", 72.5) is True
    assert StateFilter._loose_eq("20", 20) is True
    assert StateFilter._loose_eq("on", "on") is True
    assert StateFilter._loose_eq("on", "off") is False
    assert StateFilter._loose_eq(None, 5) is False


def test_state_filter_eq_matches_stringy_numeric_state():
    from mcp_server.common.state_filter import StateFilter
    entity = {"id": 1, "states": {"temperature": "21.5"}}
    # eq against a NUMBER must match a numeric string state
    assert StateFilter.matches_state(entity, {"temperature": {"eq": 21.5}}) is True
    assert StateFilter.matches_state(entity, {"temperature": {"ne": 30}}) is True
    # simple-equality form too
    assert StateFilter.matches_state(entity, {"temperature": 21.5}) is True


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
