#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_control_resolve.py
# Description: device_control switches a device by NAME, so it must act only
#              when the name means one device. An exact name wins; otherwise a
#              single confident candidate; two or more is a refusal.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from mcp_server.toolsets.devices import resolve_device_for_control

resolve = resolve_device_for_control


def _d(i, name, score):
    return {"id": i, "name": name, "relevance_score": score}


def test_exact_name_wins_over_longer_names():
    devs = [_d(1, "Hall Lamp Plug", 1.0), _d(2, "Hall Lamp", 1.0)]
    dev, refusal = resolve("hall lamp", devs)
    assert refusal is None and dev["id"] == 2


def test_two_substring_matches_are_refused():
    devs = [_d(1, "Hall Lamp Plug", 1.0), _d(2, "Hall Lamp Left", 1.0)]
    dev, refusal = resolve("hall lamp", devs)
    assert dev is None
    assert refusal["success"] is False
    assert {c["id"] for c in refusal["candidates"]} == {1, 2}


def test_one_confident_candidate_is_used():
    devs = [_d(1, "Garage Door Relay", 0.95), _d(2, "Hall Lamp", 0.2)]
    dev, refusal = resolve("garage relay", devs)
    assert refusal is None and dev["id"] == 1


def test_no_confident_candidate_is_refused_with_suggestions():
    dev, refusal = resolve("xyz", [_d(1, "Hall Lamp", 0.3)])
    assert dev is None and refusal["suggestions"] == ["Hall Lamp"]


def test_duplicate_exact_names_are_refused():
    devs = [_d(1, "Patio", 1.0), _d(2, "Patio", 1.0)]
    dev, refusal = resolve("Patio", devs)
    assert dev is None and "device id" in refusal["error"]
