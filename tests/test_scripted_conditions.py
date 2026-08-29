#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_scripted_conditions.py
# Description: Tests for scripted-condition decoding, quoted-name matching in
#              embedded scripts, and cross-class ID collisions in the reverse
#              index (ClaudeBridge v2.23.0).
# Author:      CliveS & Claude Opus 5
# Date:        29-08-2026
# Version:     1.0

import textwrap

import pytest

from mcp_server.adapters.indidb.parser import parse_indidb
from mcp_server.adapters.indidb.reverse_index import (
    Reference,
    ReverseIndex,
    build_reverse_index,
)
from mcp_server.tools.automation_detail import detail_renderer

# Ids sit above MIN_HEURISTIC_ID so the text heuristics can see them.
DEV_LAMP    = 111222333
DEV_PUMP    = 222333444
VAR_HOLIDAY = 333444555
VAR_SPRINK  = 444555666
AG_SCRIPTED = 555666777
TRIG_GARAGE = 666777888
SCHED_DUSK  = 777888999

# One integer naming BOTH a device and a variable. Indigo guarantees ids are
# unique only WITHIN a class, so this is legal — just very unlikely.
CLASH_ID = 888999111

CONDITION_SCRIPT = (
    "FRIDAY_SPRINKLERS_AUTO_OFF_ID = %d\n"
    "if indigo.variables[FRIDAY_SPRINKLERS_AUTO_OFF_ID].value == &quot;true&quot;:\n"
    "    return False\n"
    "return True" % VAR_SPRINK
)

SCRIPTED_DB = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Database type="dict">
        <AppVers type="string">2025.2.0</AppVers>
        <DeviceList type="vector">
            <Device type="dict">
                <ID type="integer">{DEV_LAMP}</ID>
                <Name type="string">Garage Overheads</Name>
            </Device>
            <Device type="dict">
                <ID type="integer">{DEV_PUMP}</ID>
                <Name type="string">Sprinkler Pump</Name>
            </Device>
            <Device type="dict">
                <ID type="integer">{CLASH_ID}</ID>
                <Name type="string">Clashing Device</Name>
            </Device>
        </DeviceList>
        <VariableList type="vector">
            <Variable type="dict">
                <ID type="integer">{VAR_HOLIDAY}</ID>
                <Name type="string">holiday_mode</Name>
            </Variable>
            <Variable type="dict">
                <ID type="integer">{VAR_SPRINK}</ID>
                <Name type="string">friday_sprinklers_auto_off</Name>
            </Variable>
            <Variable type="dict">
                <ID type="integer">{CLASH_ID}</ID>
                <Name type="string">clashing_variable</Name>
            </Variable>
        </VariableList>
        <TriggerList type="vector">
            <Trigger type="dict">
                <ID type="integer">{TRIG_GARAGE}</ID>
                <Name type="string">Garage Overheads ON Auto Turn Off 15 Min</Name>
                <Class type="integer">501</Class>
                <Enabled type="bool">true</Enabled>
                <DeviceID type="integer">{DEV_LAMP}</DeviceID>
                <DeviceStateChange type="integer">110</DeviceStateChange>
                <Condition type="dict">
                    <Type type="integer">4</Type>
                    <ScriptSource type="string">{CONDITION_SCRIPT}</ScriptSource>
                    <ScriptType type="integer">0</ScriptType>
                </Condition>
                <ActionGroup type="dict">
                    <ActionSteps type="vector">
                        <Action type="dict">
                            <Class type="integer">1</Class>
                            <DeviceID type="integer">{DEV_LAMP}</DeviceID>
                            <DeviceAction type="integer">5</DeviceAction>
                        </Action>
                    </ActionSteps>
                </ActionGroup>
            </Trigger>
        </TriggerList>
        <TDTriggerList type="vector">
            <TDTrigger type="dict">
                <ID type="integer">{SCHED_DUSK}</ID>
                <Name type="string">Dusk Sweep</Name>
                <Class type="integer">100</Class>
                <Enabled type="bool">true</Enabled>
                <TimeType type="integer">0</TimeType>
                <DateType type="integer">0</DateType>
                <Time type="integer">72000</Time>
                <Condition type="dict">
                    <Type type="integer">100</Type>
                    <ConditionList type="dict">
                        <Logic type="integer">1</Logic>
                        <Conditions type="vector">
                            <Condition type="dict">
                                <Type type="integer">4</Type>
                                <ScriptSource type="string">dev = indigo.devices[&quot;Sprinkler Pump&quot;]
    return indigo.variables[&quot;holiday_mode&quot;].value != &quot;true&quot;</ScriptSource>
                                <ScriptType type="integer">0</ScriptType>
                            </Condition>
                            <Condition type="dict">
                                <Type type="integer">3</Type>
                                <VarID type="integer">{VAR_HOLIDAY}</VarID>
                                <VarState type="integer">1</VarState>
                            </Condition>
                        </Conditions>
                    </ConditionList>
                </Condition>
                <ActionGroup type="dict"><ActionSteps type="vector"/></ActionGroup>
            </TDTrigger>
        </TDTriggerList>
        <ActionGroupList type="vector">
            <ActionGroup type="dict">
                <ID type="integer">{AG_SCRIPTED}</ID>
                <Name type="string">Clash Prober</Name>
                <Condition type="dict"><Type type="integer">0</Type></Condition>
                <ActionSteps type="vector">
                    <Action type="dict">
                        <Class type="integer">101</Class>
                        <ScriptUseLink type="bool">false</ScriptUseLink>
                        <ScriptSource type="string">thing = {CLASH_ID}</ScriptSource>
                        <ScriptType type="integer">0</ScriptType>
                    </Action>
                </ActionSteps>
            </ActionGroup>
        </ActionGroupList>
    </Database>
""").format(
    DEV_LAMP=DEV_LAMP, DEV_PUMP=DEV_PUMP, VAR_HOLIDAY=VAR_HOLIDAY,
    VAR_SPRINK=VAR_SPRINK, AG_SCRIPTED=AG_SCRIPTED, TRIG_GARAGE=TRIG_GARAGE,
    SCHED_DUSK=SCHED_DUSK, CLASH_ID=CLASH_ID, CONDITION_SCRIPT=CONDITION_SCRIPT,
)

NAMES = {
    ("device", DEV_LAMP):        "Garage Overheads",
    ("device", DEV_PUMP):        "Sprinkler Pump",
    ("variable", VAR_HOLIDAY):   "holiday_mode",
    ("variable", VAR_SPRINK):    "friday_sprinklers_auto_off",
}


def _name_lookup(kind, entity_id):
    return NAMES.get((kind, entity_id), f"<{kind} {entity_id}>")


@pytest.fixture()
def parsed(tmp_path):
    path = tmp_path / "Scripted.indiDb"
    path.write_text(SCRIPTED_DB, encoding="utf-8")
    return parse_indidb(str(path))


@pytest.fixture()
def index(parsed):
    return build_reverse_index(parsed)


def _roles(index, kind, entity_id):
    return {(r["entity_type"], r["id"], r["role"])
            for r in index.references_to(kind, entity_id)}


# ── Rendering ────────────────────────────────────────────────────────────────

def test_scripted_condition_renders_its_source(parsed):
    record = parsed.triggers[TRIG_GARAGE]
    rendered = detail_renderer.render_condition(record["Condition"], _name_lookup)
    assert rendered["type"].startswith("scripted condition")
    assert "type 4" in rendered["type"], "the raw code must stay visible"
    assert rendered["script"]["kind"] == "embedded"
    assert rendered["script"]["language"].startswith("python")
    assert str(VAR_SPRINK) in rendered["script"]["source"]


def test_scripted_condition_honours_include_scripts(parsed):
    record = parsed.triggers[TRIG_GARAGE]
    rendered = detail_renderer.render_condition(record["Condition"], _name_lookup,
                                                include_scripts=False)
    script = rendered["script"]
    assert "source" not in script
    assert script["lines"] == 4
    # A line count alone says nothing about what the script does.
    assert script["first_line"].startswith("FRIDAY_SPRINKLERS_AUTO_OFF_ID")


def test_long_source_is_capped_and_says_so(parsed):
    """Truncation must never be silent — a cut-off script reads as a whole one."""
    long_source = "x = 1  # padding\n" * 500
    script = detail_renderer.render_embedded_script(long_source, 0, True)
    assert len(script["source"]) == detail_renderer.MAX_SCRIPT_CHARS
    assert script["truncated"] is True
    assert str(len(long_source)) in script["note"]
    assert script["chars"] == len(long_source), "the real size must survive the cut"


def test_short_source_is_not_marked_truncated(parsed):
    script = detail_renderer.render_embedded_script("return True", 0, True)
    assert script["source"] == "return True"
    assert script["truncated"] is False


def test_empty_script_carries_no_source_keys():
    script = detail_renderer.render_embedded_script("", 0, True)
    assert script["lines"] == 0 and script["chars"] == 0
    assert "source" not in script and "first_line" not in script


def test_detail_renderers_pass_the_flag_through(parsed):
    with_source = detail_renderer.render_trigger_details(
        parsed.triggers[TRIG_GARAGE], _name_lookup, include_scripts=True)
    without = detail_renderer.render_trigger_details(
        parsed.triggers[TRIG_GARAGE], _name_lookup, include_scripts=False)
    assert "source" in with_source["condition"]["script"]
    assert "source" not in without["condition"]["script"]


def test_nested_scripted_condition_still_renders(parsed):
    rendered = detail_renderer.render_schedule_details(
        parsed.schedules[SCHED_DUSK], _name_lookup)["condition"]
    assert rendered["type"].startswith("compound")
    nested = rendered["conditions"]
    assert len(nested) == 2, "a compound must not lose a leg to the script branch"
    assert any(c["type"].startswith("scripted condition") for c in nested)


def test_compound_carrying_a_script_key_keeps_its_legs():
    """Type 100 is excluded from the script branch on purpose."""
    condition = {
        "Type": 100,
        "ScriptSource": "return True",
        "ConditionList": {"Logic": 1, "Conditions": [{"Type": 0}]},
    }
    rendered = detail_renderer.render_condition(condition, _name_lookup)
    assert rendered["conditions"], "nested list must survive"


# ── Reverse index ────────────────────────────────────────────────────────────

def test_condition_script_id_is_found(index):
    """The delete-hazard case: a variable referenced ONLY by a condition script."""
    roles = _roles(index, "variable", VAR_SPRINK)
    assert ("trigger", TRIG_GARAGE, "condition_reads") in roles


def test_condition_script_reference_is_marked_heuristic(index):
    refs = [r for r in index.references_to("variable", VAR_SPRINK)
            if r["id"] == TRIG_GARAGE]
    assert refs and refs[0]["confidence"] == "heuristic"
    assert str(VAR_SPRINK) in refs[0]["detail"]


def test_quoted_name_in_a_condition_script_is_found(index):
    """indigo.devices["Sprinkler Pump"] — no numeric id anywhere."""
    roles = _roles(index, "device", DEV_PUMP)
    assert ("schedule", SCHED_DUSK, "condition_reads") in roles


def test_decoded_condition_beats_the_text_match(index):
    """holiday_mode is read by BOTH a Type 3 condition and the script beside it."""
    refs = [r for r in index.references_to("variable", VAR_HOLIDAY)
            if r["id"] == SCHED_DUSK and r["role"] == "condition_reads"]
    assert len(refs) == 1
    assert "confidence" not in refs[0], "the decoded reference must win"


def test_cross_class_id_collision_reports_both_entities(index):
    """An id naming a device AND a variable must not silently pick one."""
    device_roles = _roles(index, "device", CLASH_ID)
    variable_roles = _roles(index, "variable", CLASH_ID)
    assert ("action_group", AG_SCRIPTED, "script_reference") in device_roles
    assert ("action_group", AG_SCRIPTED, "script_reference") in variable_roles


def test_unrelated_numbers_do_not_match(index):
    """Only ids belonging to real entities are reported."""
    assert index.references_to("variable", 999000111) == []


# ── Reference collapse ───────────────────────────────────────────────────────

@pytest.mark.parametrize("heuristic_first", [True, False])
def test_exact_reference_survives_either_order(heuristic_first):
    """Same container + role: the decoded reference must win regardless of order."""
    index = ReverseIndex()
    exact = Reference("trigger", TRIG_GARAGE, "condition_reads",
                      detail="decoded")
    guess = Reference("trigger", TRIG_GARAGE, "condition_reads",
                      detail="text match", confidence="heuristic")
    for ref in ((guess, exact) if heuristic_first else (exact, guess)):
        index.add(("variable", VAR_HOLIDAY), ref)

    refs = index.references_to("variable", VAR_HOLIDAY)
    assert len(refs) == 1
    assert "confidence" not in refs[0]
    assert refs[0]["detail"] == "decoded"
