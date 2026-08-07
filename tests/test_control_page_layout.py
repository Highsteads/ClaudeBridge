#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_control_page_layout.py
# Description: Tests for control-page layout reading — decoding raw PageElemList
#              entries and flagging controls whose target no longer exists.
#              Fixture is a REAL capture from a live Indigo control page, not a
#              hand-written guess at the shape.
# Author:      CliveS & Claude Opus 5
# Date:        06-08-2026
# Version:     1.0

import sys
from unittest.mock import MagicMock

from mcp_server.common.control_page import (
    FULL_PAGE_FLAGS, PAGE_ELEMENT_TYPES, PAGE_FLAGS_WITH_ACTIONS,
    describe_action_steps, describe_element,
)
from mcp_server.tools.extended_tools.extended_tools_handler import ExtendedToolsHandler

from test_dispatch import _LOGGER


# ── real capture ──────────────────────────────────────────────────────────────
# Lifted verbatim from indigo.rawServerRequest("GetControlPage", …) against a
# live 600x200 page on 06-08-2026. Using the real shape matters: a hand-written
# fixture would have encoded my assumptions about the reply rather than Indigo's.

REAL_SERVER_ICON = {
    "CaptionPlacement": 4, "ControlType": 201, "ObjVers": 9, "Position": "2 2",
    "ServerIndex": 0, "ShowStateImage": True, "ShowStateText": False,
    "Size": "18 18", "StateTextAlignment": 0,
}

REAL_DEVICE_LIGHT = {
    "CaptionCurHeight": 13, "CaptionCurWidth": 81, "CaptionName": "Bathroom Light",
    "CaptionWraps": False, "ControlType": 1, "ImageFileName": "lightbulb_large.png",
    "ObjVers": 9, "Position": "48 59", "ServerActionClass": 1, "ServerActionType": 1,
    "ServerIndex": 2, "ShowStateImage": True, "ShowStateText": False, "Size": "26 39",
    "TargetElemID": 1484056336, "TargetElemName": "Bathroom Light",
    "TargetElemSubKey": "onOffState", "ValueLong": "off", "ValueRaw": "off",
}

REAL_DEVICE_THERMOSTAT = {
    "CaptionName": "Bathroom Radiator", "ControlType": 1,
    "ImageFileName": "Temperature Sensor.png", "Position": "53 129",
    "ServerActionClass": 3, "ServerActionType": 3, "ServerIndex": 5, "Size": "38 38",
    "TargetElemID": 1886011292, "TargetElemName": "Bathroom Radiator",
    "TargetElemSubKey": "temperatureInputsAll", "ValueLong": "19.0", "ValueRaw": "19.0",
}


# ── decoding ──────────────────────────────────────────────────────────────────

def test_decodes_a_real_device_control():
    el = describe_element(REAL_DEVICE_LIGHT)
    assert el["type"] == "device" and el["type_code"] == 1
    assert el["index"] == 2
    assert el["caption"] == "Bathroom Light"
    assert el["position"] == {"x": 48, "y": 59}
    assert el["size"] == {"width": 26, "height": 39}
    assert el["displayed_value"] == "off"
    assert el["image"] == "lightbulb_large.png"
    assert el["action_class"] == "control_devices"
    assert el["target"] == {"id": 1484056336, "name": "Bathroom Light",
                            "state": "onOffState", "collection": "devices"}


def test_decodes_a_thermostat_action_class():
    # Same element type, different action class — proves the class is decoded
    # from its own field rather than inferred from the element type.
    el = describe_element(REAL_DEVICE_THERMOSTAT)
    assert el["action_class"] == "control_thermostat"
    assert el["target"]["state"] == "temperatureInputsAll"


def test_page_furniture_has_no_target():
    el = describe_element(REAL_SERVER_ICON)
    assert el["type"] == "server_icon"
    assert "target" not in el
    assert el["caption_placement"] == "left_of_image"


def test_unknown_type_code_is_reported_not_invented():
    el = describe_element({"ControlType": 4242, "ServerIndex": 0})
    assert el["type"] == "unknown(4242)"
    assert el["type_code"] == 4242


def test_malformed_geometry_is_dropped_not_guessed():
    el = describe_element({"ControlType": 1, "Position": "nonsense", "Size": "1 2 3"})
    assert "position" not in el and "size" not in el


def test_target_collection_matches_element_type():
    for code, coll in ((1, "devices"), (2, "variables"),
                       (4, "actionGroups"), (5, "controlPages")):
        el = describe_element({"ControlType": code, "TargetElemID": 1})
        assert el["target"]["collection"] == coll, code
    # A video control carries no addressable Indigo object.
    el = describe_element({"ControlType": 3, "TargetElemID": 1})
    assert el["target"]["collection"] is None


def test_full_page_flags_matches_indigos_own_constant():
    # utils.FULL_PAGE_FLAGS = calc_getPage_flags(False, True, False, False).
    # Wrong flags return a page with no PageElemList at all.
    assert FULL_PAGE_FLAGS == 65538


def test_we_ask_for_actions_not_indigos_default_flags():
    """Indigo's own FULL_PAGE_FLAGS sets ignore_actions=True despite the name.

    Using it means every element comes back with an empty ActionGroup, so a
    button's entire purpose is invisible and the page reads as though nothing
    on it does anything. That shipped in 2.19.0 and was only caught by
    importing a real page and noticing its light reported no action.
    """
    assert PAGE_FLAGS_WITH_ACTIONS == 65536
    assert PAGE_FLAGS_WITH_ACTIONS != FULL_PAGE_FLAGS


# ── what tapping an element does ──────────────────────────────────────────────

def test_decodes_a_device_toggle_step():
    steps = describe_action_steps(
        {"ActionSteps": [{"Class": 1, "DeviceAction": 6, "DeviceID": 1484056336}]})
    assert len(steps) == 1
    assert "toggle" in steps[0]["action"]
    assert "device action" in steps[0]["action_class"]
    assert steps[0]["device_id"] == 1484056336


def test_decodes_a_brightness_step_with_its_value():
    steps = describe_action_steps({"ActionSteps": [
        {"Class": 1, "DeviceAction": 7, "DeviceActionValue": 750, "DeviceID": 9}]})
    assert "set brightness" in steps[0]["action"]
    assert steps[0]["value"] == 750


def test_decodes_a_thermostat_step():
    steps = describe_action_steps(
        {"ActionSteps": [{"Class": 3, "HVACAction": 0, "DeviceID": 9}]})
    assert "set heat setpoint" in steps[0]["action"]


def test_unknown_action_codes_carry_the_raw_number():
    steps = describe_action_steps(
        {"ActionSteps": [{"Class": 1, "DeviceAction": 4242, "DeviceID": 9}]})
    assert "4242" in steps[0]["action"]


def test_display_only_elements_have_no_on_tap():
    el = describe_element(dict(REAL_DEVICE_LIGHT, ActionGroup={"ActionSteps": []}))
    assert "on_tap" not in el


def test_a_missing_or_malformed_action_group_is_survivable():
    assert describe_action_steps(None) == []
    assert describe_action_steps({}) == []
    assert describe_action_steps({"ActionSteps": "not a list"}) == []


def test_element_surfaces_the_client_side_action():
    """1014 is how a thermostat or dimmer gets its popup. Without it a setpoint
    control is indistinguishable from a read-only sensor tile."""
    el = describe_element({"ControlType": 1, "TargetElemID": 7,
                           "ClientActionType": 1014, "ShowStateText": True})
    assert el["client_action"] == "popup controls"
    assert el["client_action_code"] == 1014
    assert el["shows_state_text"] is True


def test_client_action_none_is_omitted_rather_than_reported_as_a_behaviour():
    for value in (0, None):
        el = describe_element({"ControlType": 1, "ClientActionType": value})
        assert "client_action" not in el, value


def test_every_element_type_code_is_distinct():
    assert len(set(PAGE_ELEMENT_TYPES.values())) == len(PAGE_ELEMENT_TYPES)


# ── broken-reference detection ────────────────────────────────────────────────

class _Collection:
    """Mimics an indigo collection's `in` behaviour with integer ids."""

    def __init__(self, ids):
        self._ids = set(ids)

    def __contains__(self, key):
        return key in self._ids


def _handler():
    return ExtendedToolsHandler(data_provider=MagicMock(), logger=_LOGGER)


def test_flags_a_control_whose_device_was_deleted(monkeypatch):
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", _Collection([1484056336]), raising=False)

    elements = [describe_element(REAL_DEVICE_LIGHT),
                describe_element(dict(REAL_DEVICE_THERMOSTAT))]
    missing = _handler()._flag_missing_targets(elements)

    assert missing == 1
    assert elements[0]["target"]["exists"] is True
    assert elements[1]["target"]["exists"] is False


def test_furniture_is_never_counted_as_a_broken_reference(monkeypatch):
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", _Collection([]), raising=False)
    elements = [describe_element(REAL_SERVER_ICON)]
    assert _handler()._flag_missing_targets(elements) == 0


def test_a_target_with_no_indigo_collection_is_skipped_cleanly(monkeypatch):
    """A video control carries a TargetElemID but points at no addressable
    Indigo collection, so `collection` is None. Without the collection guard
    this reaches getattr(indigo, None), which raises TypeError — a crash on a
    page that merely contains a camera. The element-has-a-target check alone
    does NOT cover this: found by mutation testing, where dropping the guard
    survived a suite that only ever fed it elements with no target at all."""
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", _Collection([]), raising=False)

    video = describe_element({"ControlType": 3, "ServerIndex": 0,
                              "TargetElemID": 12345, "TargetElemName": "Front Door Cam"})
    assert video["target"]["collection"] is None

    elements = [video]
    assert _handler()._flag_missing_targets(elements) == 0
    assert "exists" not in elements[0]["target"]     # unknown, not asserted either way


# ── the tool ──────────────────────────────────────────────────────────────────

class _FakePage:
    id, name, folderId = 1735784515, "Test page", 0
    hideTabBar, description = True, ""
    width, height = 600, 200
    displayInRemoteUI = True


def _fake_pages(monkeypatch):
    ind = sys.modules["indigo"]
    pages = MagicMock()
    pages.__getitem__ = lambda self, k: _FakePage()
    monkeypatch.setattr(ind, "controlPages", pages, raising=False)
    monkeypatch.setattr(ind, "devices", _Collection([1484056336, 1886011292]),
                        raising=False)
    return ind


def test_get_control_page_returns_the_layout(monkeypatch):
    ind = _fake_pages(monkeypatch)
    seen = {}

    def fake_raw(name, args=None):
        seen["name"], seen["args"] = name, args
        light = dict(REAL_DEVICE_LIGHT, ActionGroup={"ActionSteps": [
            {"Class": 1, "DeviceAction": 6, "DeviceID": 1484056336}]})
        return {"PageElemList": [REAL_SERVER_ICON, light, REAL_DEVICE_THERMOSTAT]}

    monkeypatch.setattr(ind, "rawServerRequest", fake_raw, raising=False)

    result = _handler().get_control_page(1735784515)
    page = result["control_page"]
    assert result["success"] is True
    assert seen["name"] == "GetControlPage"
    # Must be the with-actions flags, or every on_tap comes back empty.
    assert seen["args"]["GetPageFlags"] == PAGE_FLAGS_WITH_ACTIONS
    assert "toggle" in page["elements"][1]["on_tap"][0]["action"]
    assert page["element_count"] == 3
    assert page["width"] == 600 and page["height"] == 200
    assert [e["type"] for e in page["elements"]] == ["server_icon", "device", "device"]
    assert "broken_references" not in page      # both devices exist


def test_get_control_page_reports_broken_references(monkeypatch):
    ind = _fake_pages(monkeypatch)
    monkeypatch.setattr(ind, "devices", _Collection([]), raising=False)
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: {"PageElemList": [REAL_DEVICE_LIGHT]},
                        raising=False)

    page = _handler().get_control_page(1735784515)["control_page"]
    assert page["broken_references"] == 1


def test_get_control_page_degrades_without_the_raw_api(monkeypatch):
    ind = _fake_pages(monkeypatch)
    monkeypatch.delattr(ind, "rawServerRequest", raising=False)

    page = _handler().get_control_page(1735784515)["control_page"]
    # Still returns the page's own properties, and SAYS why contents are absent
    # rather than presenting an empty page as a page with nothing on it.
    assert page["name"] == "Test page"
    assert page["elements"] == []
    assert "rawServerRequest" in page["elements_note"]


def test_get_control_page_survives_a_failing_raw_call(monkeypatch):
    ind = _fake_pages(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("server said no")

    monkeypatch.setattr(ind, "rawServerRequest", boom, raising=False)
    result = _handler().get_control_page(1735784515)
    assert result["success"] is True
    assert "server said no" in result["control_page"]["elements_note"]


def test_one_bad_element_does_not_lose_the_rest(monkeypatch):
    ind = _fake_pages(monkeypatch)
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: {"PageElemList": [REAL_DEVICE_LIGHT, None]},
                        raising=False)
    page = _handler().get_control_page(1735784515)["control_page"]
    assert page["element_count"] == 2
    assert page["elements"][0]["type"] == "device"
    assert page["elements"][1]["type"] == "undecodable"


def test_the_dead_controls_key_is_gone(monkeypatch):
    """`cp.controls` never existed on any Indigo version, so the old branch
    always returned an empty list and the tool quietly reported a page with no
    contents. Guards against it being reintroduced."""
    ind = _fake_pages(monkeypatch)
    monkeypatch.setattr(ind, "rawServerRequest",
                        lambda *a, **k: {"PageElemList": [REAL_DEVICE_LIGHT]},
                        raising=False)
    page = _handler().get_control_page(1735784515)["control_page"]
    assert "controls" not in page
