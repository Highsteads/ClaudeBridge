#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_battery.py
# Description: battery_pct across the conventions plugins use: battery and
#              batteryLevel states, the native property, binary OK/LOW flags, USB
#              power and out-of-range sentinels.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2101_fixes.py (v2.10.1), test_v2132_battery_binary.py (v2.13.2),
#   test_v2202_low_fixes.py (09-Aug-2026 review)


from conftest import FakeDevice

# The three files each had their own copy of this double.
_FakeDev = FakeDevice
_Dev = FakeDevice


# ── battery_pct: covers battery / batteryLevel state + native property ───────
def test_battery_pct_reads_battery_state():
    from mcp_server.common.battery import battery_pct
    # z2m convention: the `battery` custom state (the 43-device majority)
    assert battery_pct(_FakeDev(states={"battery": 87})) == 87


def test_battery_pct_reads_batterylevel_state():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={"batteryLevel": 12})) == 12


def test_battery_pct_reads_native_property():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={}, native=5)) == 5


def test_battery_pct_none_when_absent():
    from mcp_server.common.battery import battery_pct
    assert battery_pct(_FakeDev(states={"temperature": 21})) is None
    assert battery_pct(_FakeDev(states={"battery": ""})) is None


# ── binary OK/LOW conventions and USB power (v2.13.2) ─────────────────────────

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


# ── Battery reporting ────────────────────────────────────────────────────────
def test_battery_low_flag_read_as_a_string_is_not_truthy():
    """A "False" string state meant every OK sensor reported as flat."""
    from mcp_server.common.battery import battery_pct

    assert battery_pct(_Dev({"battery": 0, "batteryLow": "false"})) is None
    assert battery_pct(_Dev({"battery": 0, "batteryLow": "False"})) is None
    assert battery_pct(_Dev({"battery": 0, "batteryLow": "true"})) == 1
    assert battery_pct(_Dev({"battery": 0, "batteryLow": True})) == 1


def test_out_of_range_battery_reads_as_unknown():
    """255 is the classic 'unknown' sentinel. Reporting it as a percentage puts
    a possibly-failing sensor at the healthy end of a low-battery sweep."""
    from mcp_server.common.battery import battery_pct

    assert battery_pct(_Dev({"battery": 255})) is None
    assert battery_pct(_Dev({"battery": -5})) is None
    assert battery_pct(_Dev({"battery": 101})) is None
    assert battery_pct(_Dev({"battery": 100})) == 100
    assert battery_pct(_Dev({"battery": 42})) == 42
