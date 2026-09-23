#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_dependencies.py
# Description: get_dependencies converts Indigo's nested lists into real JSON arrays.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v210_fixes.py (v2.10.0)


import json


# ── H10: get_dependencies deep-converts nested lists ─────────────────────────

def test_deps_to_plain_deep_converts_nested_lists():
    from mcp_server.tools.extended_tools.extended_tools_handler import _deps_to_plain
    # Emulate getDependencies() shape: a mapping of bucket -> list of {ID,Name}.
    deps = {
        "devices":     [{"ID": 1, "Name": "Kitchen Light"}],
        "triggers":    [],
        "schedules":   [{"ID": 5, "Name": "Nightly"}],
    }
    out = _deps_to_plain(deps)
    assert out["devices"] == [{"ID": 1, "Name": "Kitchen Light"}]
    assert out["schedules"][0]["Name"] == "Nightly"
    assert out["triggers"] == []
    # Crucially, the nested lists survive a JSON round-trip as real arrays,
    # not the {} the encoder produced for a raw indigo.List.
    assert json.loads(json.dumps(out))["devices"][0]["ID"] == 1
