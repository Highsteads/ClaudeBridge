#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_colour.py
# Description: set_color sends setColorLevels the argument names and ranges the
#              official docs give: redLevel/greenLevel/blueLevel/whiteLevel
#              0-100 and whiteTemperature 1200-15000 Kelvin. It used to send
#              rLevel/gLevel/bLevel at 0-255.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import pytest

from conftest import FakeDevice


class _Dimmer:
    def __init__(self):
        self.calls = []

    def setColorLevels(self, dev_id, **kwargs):
        self.calls.append((dev_id, kwargs))


@pytest.fixture()
def rig(monkeypatch):
    import indigo
    from mcp_server.adapters.indigo_data_provider import IndigoDataProvider
    dimmer = _Dimmer()
    monkeypatch.setattr(indigo, "devices", {7: FakeDevice(id=7, name="Lamp")})
    monkeypatch.setattr(indigo, "dimmer", dimmer, raising=False)
    return IndigoDataProvider(), dimmer


def test_rgb_is_scaled_to_indigos_0_to_100_levels(rig):
    provider, dimmer = rig
    out = provider.set_color(7, 255, 128, 0)
    assert out["success"] is True
    assert dimmer.calls == [(7, {"redLevel": 100.0, "greenLevel": 50.2, "blueLevel": 0.0})]


def test_white_and_temperature_use_the_documented_names(rig):
    provider, dimmer = rig
    provider.set_color(7, 0, 0, 0, white=40, white_temperature=2700)
    assert dimmer.calls[0][1] == {"redLevel": 0.0, "greenLevel": 0.0, "blueLevel": 0.0,
                                  "whiteLevel": 40.0, "whiteTemperature": 2700}


@pytest.mark.parametrize("kwargs,needle", [
    ({"red": 300, "green": 0, "blue": 0}, "red must be 0-255"),
    ({"red": 0, "green": 0, "blue": 0, "white": 180}, "white must be 0-100"),
    ({"red": 0, "green": 0, "blue": 0, "white_temperature": 900}, "1200-15000"),
    ({"red": 0, "green": 0, "blue": 0, "white_temperature": 20000}, "1200-15000"),
    ({"red": True, "green": 0, "blue": 0}, "red must be a number"),
])
def test_out_of_range_values_are_refused_not_clamped(rig, kwargs, needle):
    provider, dimmer = rig
    out = provider.set_color(7, **kwargs)
    assert out["success"] is False and needle in out["error"]
    assert dimmer.calls == []
