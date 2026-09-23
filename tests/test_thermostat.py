#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_thermostat.py
# Description: set_hvac_mode refuses a non-string mode cleanly.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2202_low_fixes.py (09-Aug-2026 review)


# ── Arguments are coerced before they are compared ───────────────────────────

def test_hvac_mode_rejects_a_non_string_cleanly():
    """mode.lower() ran outside the try, so a number raised AttributeError."""
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider

    provider = object.__new__(IndigoDataProvider)
    result = provider.set_hvac_mode(1, 42)
    assert result["success"] is False
    assert "Unknown HVAC mode" in result["error"]

    result = provider.set_hvac_mode(1, None)
    assert result["success"] is False
