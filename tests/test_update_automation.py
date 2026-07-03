#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_update_automation.py
# Description: Tests for update_trigger / update_schedule / update_action_group
#              and the enable/disable duration auto-revert parameters
#              (ClaudeBridge v2.12.0).
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import sys
import types
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.schedule_control.schedule_control_handler import (
    ScheduleControlHandler,
)


class FakeCollection:
    """Duck-type of an Indigo element collection (in / [] / iteration)."""

    def __init__(self, items):
        self._items = dict(items)

    def __contains__(self, key):
        return key in self._items

    def __getitem__(self, key):
        return self._items[key]

    def __iter__(self):
        return iter(self._items)


class FakeTrigger:
    """Device-state-change trigger double with replaceOnServer tracking."""

    _FIELDS = {"id", "name", "description", "enabled", "deviceId",
               "stateSelector", "stateSelectorIndex", "stateChangeType",
               "stateValue", "replaced"}

    def __init__(self, elem_id, name):
        object.__setattr__(self, "replaced", False)
        object.__setattr__(self, "id", elem_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", "")
        object.__setattr__(self, "enabled", True)
        object.__setattr__(self, "deviceId", 111222333)
        object.__setattr__(self, "stateSelector", "onOffState")
        object.__setattr__(self, "stateSelectorIndex", 0)
        object.__setattr__(self, "stateChangeType", "BecomesTrue")
        object.__setattr__(self, "stateValue", "")

    def __setattr__(self, attr, value):
        # Mirror the IOM: only the subclass's real attributes are settable.
        if attr not in self._FIELDS:
            raise AttributeError(
                f'the attribute "{attr}" is read-only on this instance')
        object.__setattr__(self, attr, value)

    def replaceOnServer(self):
        object.__setattr__(self, "replaced", True)


class FakeSchedule:
    def __init__(self, elem_id, name):
        self.id = elem_id
        self.name = name
        self.description = ""
        self.enabled = True
        self.replaced = False

    def replaceOnServer(self):
        self.replaced = True


TRIG_ID = 565656565
SCHED_ID = 787878787
AG_ID = 121212121
DEV_ID = 111222333


@pytest.fixture()
def indigo_stub(monkeypatch):
    ind = sys.modules["indigo"]
    trigger = FakeTrigger(TRIG_ID, "Motion Turns On Lamp")
    schedule = FakeSchedule(SCHED_ID, "Nightly Lamp Off")
    action_group = FakeSchedule(AG_ID, "Inner Lamp Group")

    monkeypatch.setattr(ind, "triggers", FakeCollection({TRIG_ID: trigger}),
                        raising=False)
    monkeypatch.setattr(ind, "schedules", FakeCollection({SCHED_ID: schedule}),
                        raising=False)
    monkeypatch.setattr(ind, "actionGroups",
                        FakeCollection({AG_ID: action_group}), raising=False)
    monkeypatch.setattr(ind, "devices", FakeCollection({DEV_ID: object()}),
                        raising=False)
    monkeypatch.setattr(ind, "variables", FakeCollection({}), raising=False)
    monkeypatch.setattr(
        ind, "kStateChange",
        types.SimpleNamespace(BecomesTrue="BecomesTrue",
                              BecomesFalse="BecomesFalse",
                              Changes="Changes"),
        raising=False)
    monkeypatch.setattr(ind, "trigger", MagicMock(), raising=False)
    monkeypatch.setattr(ind, "schedule", MagicMock(), raising=False)
    return ind


@pytest.fixture()
def handler(indigo_stub):
    return ScheduleControlHandler(data_provider=None)


# ── update_trigger ───────────────────────────────────────────────────────────

def test_update_trigger_rename_reports_before_after(handler, indigo_stub):
    result = handler.update_trigger(TRIG_ID, {"name": "New Trigger Name"})
    assert result["success"] is True
    assert result["before"]["name"] == "Motion Turns On Lamp"
    assert result["after"]["name"] == "New Trigger Name"
    assert indigo_stub.triggers[TRIG_ID].replaced is True
    assert "warning" not in result


def test_update_trigger_event_settings_with_enum(handler, indigo_stub):
    result = handler.update_trigger(TRIG_ID, {
        "device_id": DEV_ID,
        "state_change_type": "becomes_false",
        "state_value": "42",
    })
    assert result["success"] is True
    trigger = indigo_stub.triggers[TRIG_ID]
    assert trigger.stateChangeType == "BecomesFalse"
    assert trigger.stateValue == "42"


def test_update_trigger_invalid_enum_lists_valid_values(handler):
    result = handler.update_trigger(TRIG_ID,
                                    {"state_change_type": "goes_sideways"})
    assert result["success"] is False
    assert "BecomesTrue" in result["error"]


def test_update_trigger_rejects_unknown_device(handler):
    result = handler.update_trigger(TRIG_ID, {"device_id": 999})
    assert result["success"] is False
    assert "does not match an existing device" in result["error"]


def test_update_trigger_rejects_unknown_field(handler):
    result = handler.update_trigger(TRIG_ID, {"colour": "red"})
    assert result["success"] is False
    assert "not editable" in result["error"]


def test_update_trigger_wrong_subclass_surfaces_error(handler):
    # variable_* fields don't exist on a device-state-change trigger.
    result = handler.update_trigger(TRIG_ID, {"variable_value": "x"})
    assert result["success"] is False
    assert "variable-change triggers" in result["error"]


def test_update_trigger_not_found(handler):
    result = handler.update_trigger(424242, {"name": "x"})
    assert result["success"] is False


# ── update_schedule / update_action_group ────────────────────────────────────

def test_update_schedule_name_description_only(handler, indigo_stub):
    ok = handler.update_schedule(SCHED_ID, {"description": "tidied"})
    assert ok["success"] is True
    assert indigo_stub.schedules[SCHED_ID].description == "tidied"
    # Timing is read-only on live instances — the field map must refuse it.
    refused = handler.update_schedule(SCHED_ID, {"time_type": 0})
    assert refused["success"] is False
    assert "not editable" in refused["error"]


def test_update_action_group_rename(handler, indigo_stub):
    result = handler.update_action_group("Inner Lamp Group", {"name": "Renamed"})
    assert result["success"] is True
    assert indigo_stub.actionGroups[AG_ID].name == "Renamed"


# ── enable/disable timing parameters ─────────────────────────────────────────

def test_disable_trigger_with_auto_revert(handler, indigo_stub):
    result = handler.disable_trigger(TRIG_ID, duration_seconds=1800)
    assert result["success"] is True
    assert "auto-reverts to enabled after 1800s" in result["message"]
    _, kwargs = indigo_stub.trigger.enable.call_args
    assert kwargs == {"value": False, "duration": 1800}


def test_enable_schedule_with_delay_and_duration(handler, indigo_stub):
    result = handler.enable_schedule(SCHED_ID, delay_seconds=60,
                                     duration_seconds=3600)
    assert result["success"] is True
    _, kwargs = indigo_stub.schedule.enable.call_args
    assert kwargs == {"value": True, "delay": 60, "duration": 3600}


def test_enable_trigger_without_timing_keeps_plain_call(handler, indigo_stub):
    result = handler.enable_trigger(TRIG_ID)
    assert result["success"] is True
    assert "auto-revert" not in result["message"]
    _, kwargs = indigo_stub.trigger.enable.call_args
    assert kwargs == {"value": True}
