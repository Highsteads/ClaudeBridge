#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_automation_detail.py
# Description: Tests for the automation introspection handler + renderer
#              (get_*_details, find_automation_references, investigate_event)
#              added in ClaudeBridge v2.12.0.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import datetime

import pytest

from mcp_server.adapters.indidb.store import IndiDbStructureStore
from mcp_server.tools.automation_detail import detail_renderer
from mcp_server.tools.automation_detail.automation_detail_handler import (
    AutomationDetailHandler,
)

from test_indidb_adapter import (
    SYNTHETIC_DB, DEV_LAMP, DEV_SENSOR, VAR_MODE,
    AG_INNER, AG_OUTER, TRIG_MOTION, SCHED_NIGHT,
)

NAMES = {
    ("device", DEV_LAMP):        "Test Lamp",
    ("device", DEV_SENSOR):      "Test Motion Sensor",
    ("variable", VAR_MODE):      "house_mode",
    ("action_group", AG_INNER):  "Inner Lamp Group",
    ("action_group", AG_OUTER):  "Outer Wrapper Group",
}


def _name_lookup(kind, entity_id):
    return NAMES.get((kind, entity_id))


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "Synthetic.indiDb"
    path.write_text(SYNTHETIC_DB, encoding="utf-8")
    return IndiDbStructureStore(lambda: str(path), stat_throttle_seconds=0.0)


class FakeLogQuery:
    """Stub with the _read_log_range surface investigate_event uses."""

    def __init__(self, entries):
        self.entries = entries

    def _read_log_range(self, after_dt, before_dt, line_count):
        return self.entries


@pytest.fixture()
def handler(store):
    return AutomationDetailHandler(
        data_provider=None, structure_store=store, log_query_handler=None)


# ── Renderer: conditions ─────────────────────────────────────────────────────

def test_render_compound_condition(store):
    record = store.get_structure("trigger", TRIG_MOTION)
    rendered = detail_renderer.render_condition(record["Condition"], _name_lookup)
    assert rendered["type"].startswith("compound")
    assert rendered["logic"].startswith("AND")
    inner_types = [c["type"] for c in rendered["conditions"]]
    assert any(t.startswith("variable comparison") for t in inner_types)
    assert any(t.startswith("device state comparison") for t in inner_types)
    var_cond = rendered["conditions"][0]
    assert var_cond["variable"] == {"id": VAR_MODE, "name": "house_mode"}


def test_render_always_condition():
    assert detail_renderer.render_condition(None, _name_lookup) == {"type": "always"}
    assert detail_renderer.render_condition({"Type": 0}, _name_lookup)["type"].startswith("always")


# ── Renderer: action steps ───────────────────────────────────────────────────

def test_render_action_steps_decoding(store):
    record = store.get_structure("trigger", TRIG_MOTION)
    steps = detail_renderer.render_action_steps(
        record["ActionGroup"]["ActionSteps"], _name_lookup)
    assert len(steps) == 3
    # Brightness value 660 is tenths of a percent.
    assert steps[0]["action"].startswith("set brightness")
    assert steps[0]["brightness_percent"] == 66.0
    assert steps[0]["device"] == {"id": DEV_LAMP, "name": "Test Lamp"}
    assert steps[1]["action_group"] == {"id": AG_OUTER, "name": "Outer Wrapper Group"}
    assert steps[2]["variable"] == {"id": VAR_MODE, "name": "house_mode"}
    assert steps[2]["value"] == "active"


def test_render_embedded_script_and_delay(store):
    record = store.get_structure("schedule", SCHED_NIGHT)
    steps = detail_renderer.render_action_steps(
        record["ActionGroup"]["ActionSteps"], _name_lookup, include_scripts=True)
    assert steps[0]["delay_seconds"] == 120
    script = steps[1]["script"]
    assert script["kind"] == "embedded"
    assert str(DEV_LAMP) in script["source"]

    trimmed = detail_renderer.render_action_steps(
        record["ActionGroup"]["ActionSteps"], _name_lookup, include_scripts=False)
    assert "source" not in trimmed[1]["script"]
    assert trimmed[1]["script"]["lines"] == 2


# ── Handler: get_details ─────────────────────────────────────────────────────

def test_get_trigger_details(handler):
    details = handler.get_details("trigger", TRIG_MOTION)
    assert details["success"] is True
    assert details["name"] == "Motion Turns On Lamp"
    assert details["event"]["device"]["id"] == DEV_SENSOR
    assert details["event"]["change"].startswith("becomes on/true")
    assert len(details["action_steps"]) == 3
    assert details["structure_source"]["available"] is True


def test_get_schedule_details_timing(handler):
    details = handler.get_details("schedule", SCHED_NIGHT)
    assert details["success"] is True
    assert details["timing"]["at"] == "23:50"
    assert details["timing"]["repeat_every_days"] == 1


def test_get_details_by_name_and_missing(handler):
    by_name = handler.get_details("action_group", "Inner Lamp Group")
    assert by_name["success"] is True and by_name["id"] == AG_INNER
    missing = handler.get_details("trigger", 999)
    assert missing["success"] is False and "not found" in missing["error"]
    bad_type = handler.get_details("banana", 1)
    assert bad_type["success"] is False


# ── Handler: find_automation_references ──────────────────────────────────────

def test_find_references_roles_and_chain(handler):
    result = handler.find_automation_references(
        "device", DEV_LAMP, include_server_check=False)
    assert result["success"] is True
    assert result["target"]["name"] == "Test Lamp"
    by_role = {}
    for ref in result["references"]:
        by_role.setdefault(ref["role"], []).append(ref)
    assert "acts_on" in by_role and "condition_reads" in by_role
    chained = [r for r in result["references"]
               if "via_action_groups" in r and r["id"] == TRIG_MOTION]
    assert chained
    chain_names = [ag["name"] for ag in chained[0]["via_action_groups"]]
    assert chain_names == ["Outer Wrapper Group", "Inner Lamp Group"]
    assert all(ref["source"] == "database_file" for ref in result["references"])


def test_find_references_requires_numeric_id(handler):
    result = handler.find_automation_references("device", "Test Lamp")
    assert result["success"] is False


# ── Handler: investigate_event ───────────────────────────────────────────────

def _log_entry(ts, source, message):
    return {"TimeStamp": ts.strftime("%Y-%m-%d %H:%M:%S.000"),
            "TypeStr": source, "Message": message}


def test_investigate_event_ranks_structural_cause_first(store):
    now = datetime.datetime.now().replace(microsecond=0)
    entries = [
        _log_entry(now - datetime.timedelta(seconds=95), "Schedule",
                   "Nightly Lamp Off"),
        _log_entry(now - datetime.timedelta(seconds=3), "Trigger",
                   "Motion Turns On Lamp"),
        _log_entry(now - datetime.timedelta(seconds=2), "Action Group",
                   "Some Unrelated Group"),
        _log_entry(now, "Z-Wave",
                   'received "Test Lamp" status update is on'),
    ]
    handler = AutomationDetailHandler(
        data_provider=None, structure_store=store,
        log_query_handler=FakeLogQuery(entries))

    result = handler.investigate_event(device_id=DEV_LAMP,
                                       lookback_seconds=60)
    assert result["success"] is True
    assert result["target_event"]["device"]["name"] == "Test Lamp"
    candidates = result["candidates"]
    assert candidates, "expected ranked candidates"
    top = candidates[0]
    assert top["name"] == "Motion Turns On Lamp"
    assert top["relationship"]["role"] == "acts_on"
    # The schedule fired outside the 60s lookback — must be absent.
    assert all(c["name"] != "Nightly Lamp Off" for c in candidates)
    unrelated = [c for c in candidates if c["name"] == "Some Unrelated Group"]
    assert unrelated and "temporal proximity only" in unrelated[0]["evidence"][-1]


def test_investigate_event_no_match(store):
    handler = AutomationDetailHandler(
        data_provider=None, structure_store=store,
        log_query_handler=FakeLogQuery([]))
    result = handler.investigate_event(search_text="never logged anywhere")
    assert result["success"] is False
    assert "hint" in result


def test_investigate_event_requires_target(store):
    handler = AutomationDetailHandler(
        data_provider=None, structure_store=store,
        log_query_handler=FakeLogQuery([]))
    result = handler.investigate_event()
    assert result["success"] is False
