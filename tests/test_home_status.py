#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_home_status.py
# Description: home_status keeps a legitimate zero reading.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2201_medium_fixes.py (09-Aug-2026 review)


# ── Zero is a reading ────────────────────────────────────────────────────────

def test_first_present_helper_keeps_a_legitimate_zero():
    """`or` chains reported a flat battery or no sun as 'unavailable'."""
    from mcp_server.tools.home_status.home_status_handler import _first

    assert _first({"batterySOC": 0}, "batterySOC", "soc") == 0
    assert _first({"batterySOC": None, "soc": 0.0}, "batterySOC", "soc") == 0.0
    assert _first({}, "batterySOC", "soc") is None
    assert _first({"soc": 55}, "batterySOC", "soc") == 55
