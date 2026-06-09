#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_json_filter.py
# Description: Regression — filter_json must NOT recurse into a kept sub-object
#              (a device's `states` dict) with the top-level keep-list, which
#              previously stripped every state reading on the minimal search path.
# Author:      CliveS & Claude Opus 4.8
# Date:        09-06-2026
# Version:     1.0

from mcp_server.common.json_encoder import filter_json


def test_kept_states_dict_is_preserved_verbatim():
    device = {
        "id": 123,
        "name": "Kitchen Sensor",
        "states": {"temperature": 21.5, "humidity": 60},
        "_internal": "drop me",
    }
    keep = ["id", "name", "states"]
    out = filter_json(device, keep)

    assert out["id"] == 123
    assert out["name"] == "Kitchen Sensor"
    # The whole states dict must survive — temperature/humidity are NOT in the
    # top-level keep-list and must not be stripped.
    assert out["states"] == {"temperature": 21.5, "humidity": 60}
    assert "_internal" not in out


def test_list_of_devices_keeps_states():
    devices = [
        {"id": 1, "name": "A", "states": {"onOffState": True}},
        {"id": 2, "name": "B", "states": {"sensorValue": 42}},
    ]
    out = filter_json(devices, ["id", "name", "states"])
    assert out[0]["states"] == {"onOffState": True}
    assert out[1]["states"] == {"sensorValue": 42}


def test_unlisted_keys_are_dropped():
    out = filter_json({"id": 1, "name": "X", "address": "10.0.0.5"}, ["id", "name"])
    assert out == {"id": 1, "name": "X"}
