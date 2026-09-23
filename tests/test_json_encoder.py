#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_json_encoder.py
# Description: indigo.Dict and indigo.List survive JSON encoding.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
#
# Moved unchanged from the release-named files in the 3.0 spring clean:
#   test_v2201_medium_fixes.py (09-Aug-2026 review)


from conftest import FakeIndigoDict, FakeIndigoList

# Shared doubles (conftest.py): iterable / keyed, but NOT list or dict subclasses.
_FakeIndigoList = FakeIndigoList
_FakeIndigoDict = FakeIndigoDict


# ── indigo.Dict / indigo.List must survive JSON encoding ─────────────────────
def test_encoder_does_not_silently_flatten_indigo_containers():
    """These are Boost.Python types, so the __dict__ fallback yielded {}."""
    import json

    from mcp_server.common.json_encoder import safe_json_dumps

    payload = _FakeIndigoDict({"devices": _FakeIndigoList([1, 2, 3])})
    out = json.loads(safe_json_dumps(payload))
    assert out == {"devices": [1, 2, 3]}, (
        "a nested indigo container serialised to {} — the documented silent-loss trap"
    )
