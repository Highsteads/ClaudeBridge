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
