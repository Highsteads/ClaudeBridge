#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2132_battery_binary.py
# Description: Regression tests for the v2.13.2 battery_pct fix — binary
#              OK/LOW battery conventions (Ecowitt, UniversalZWaveSensor) and
#              USB-powered z2m devices must not be misread as 0% / 1%.
# Author:      CliveS & Claude Fable 5
# Date:        23-07-2026
# Version:     1.0


class _FakeDev:
    def __init__(self, states=None, native=None):
        self.states = states or {}
        if native is not None:
            self.batteryLevel = native


def test_binary_ok_is_not_a_percentage():
    from mcp_server.common.battery import battery_pct
    # Ecowitt convention: battery=0 + batteryLow=False means OK, not 0%
    assert battery_pct(_FakeDev(states={"battery": 0, "batteryLow": False})) is None


def test_binary_low_flags_as_one_percent():
    from mcp_server.common.battery import battery_pct
    # UZWS convention: battery=1 + batteryLow=True means LOW — keep it in the
    # low-battery list, floored at 1 so it never reads as a healthy value
    assert battery_pct(_FakeDev(states={"battery": 1, "batteryLow": True})) == 1
    assert battery_pct(_FakeDev(states={"battery": 0, "batteryLow": True})) == 1


def test_bare_zero_means_unknown_or_usb():
    from mcp_server.common.battery import battery_pct
    # z2m reports battery=0 for USB-fed FP300s — not a flat cell. A genuinely
    # flat battery stops reporting before 0; the stale-device audit owns that.
    assert battery_pct(_FakeDev(states={"battery": 0})) is None
    assert battery_pct(_FakeDev(states={"batteryLevel": 0})) is None


def test_genuine_one_percent_still_flags():
    from mcp_server.common.battery import battery_pct
    # A real 1% with no batteryLow companion is still a percentage
    assert battery_pct(_FakeDev(states={"battery": 1})) == 1


def test_real_percentages_ignore_batterylow():
    from mcp_server.common.battery import battery_pct
    # A device carrying both a real % and a batteryLow flag keeps the %
    assert battery_pct(_FakeDev(states={"battery": 58, "batteryLow": False})) == 58
    assert battery_pct(_FakeDev(states={"battery": 12, "batteryLow": True})) == 12
