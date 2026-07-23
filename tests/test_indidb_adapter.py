#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_indidb_adapter.py
# Description: Unit tests for the read-only .indiDb adapter (parser, reverse
#              index, cached store) added in ClaudeBridge v2.12.0.
# Author:      CliveS & Claude Fable 5
# Date:        03-07-2026
# Version:     1.0

import os
import textwrap
import time

import pytest

from mcp_server.adapters.indidb.parser import parse_indidb, decode_typed_element
from mcp_server.adapters.indidb.reverse_index import build_reverse_index
from mcp_server.adapters.indidb.store import IndiDbStructureStore

# Entity ids used throughout the synthetic database (all above the
# MIN_HEURISTIC_ID floor so the heuristics can see them).
DEV_LAMP     = 111222333
DEV_SENSOR   = 444555666
DEV_TRV      = 555666777
VAR_MODE     = 777888999
AG_INNER     = 121212121
AG_OUTER     = 343434343
TRIG_MOTION  = 565656565
SCHED_NIGHT  = 787878787

SYNTHETIC_DB = textwrap.dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Database type="dict">
        <AppVers type="string">2025.2.0</AppVers>
        <DeviceList type="vector">
            <Device type="dict">
                <ID type="integer">{DEV_LAMP}</ID>
                <Name type="string">Test Lamp</Name>
                <States type="dict"><onOffState type="bool">false</onOffState></States>
            </Device>
            <Device type="dict">
                <ID type="integer">{DEV_SENSOR}</ID>
                <Name type="string">Test Motion Sensor</Name>
            </Device>
            <Device type="dict">
                <ID type="integer">{DEV_TRV}</ID>
                <Name type="string">Test Radiator TRV</Name>
            </Device>
        </DeviceList>
        <VariableList type="vector">
            <Variable type="dict">
                <ID type="integer">{VAR_MODE}</ID>
                <Name type="string">house_mode</Name>
                <Value type="string">home</Value>
            </Variable>
        </VariableList>
        <TriggerList type="vector">
            <Trigger type="dict">
                <ID type="integer">{TRIG_MOTION}</ID>
                <Name type="string">Motion Turns On Lamp</Name>
                <Class type="integer">501</Class>
                <Enabled type="bool">true</Enabled>
                <DeviceID type="integer">{DEV_SENSOR}</DeviceID>
                <DeviceStateChange type="integer">110</DeviceStateChange>
                <DeviceStateSelector type="string">onOffState</DeviceStateSelector>
                <Condition type="dict">
                    <Type type="integer">100</Type>
                    <ConditionList type="dict">
                        <Logic type="integer">1</Logic>
                        <Conditions type="vector">
                            <Condition type="dict">
                                <Type type="integer">3</Type>
                                <VarID type="integer">{VAR_MODE}</VarID>
                                <VarState type="integer">0</VarState>
                            </Condition>
                            <Condition type="dict">
                                <Type type="integer">7</Type>
                                <DevID type="integer">{DEV_LAMP}</DevID>
                                <DevState type="string">onOffState</DevState>
                                <DevComp type="integer">1</DevComp>
                            </Condition>
                        </Conditions>
                    </ConditionList>
                </Condition>
                <ActionGroup type="dict">
                    <ActionSteps type="vector">
                        <Action type="dict">
                            <Class type="integer">1</Class>
                            <DeviceID type="integer">{DEV_LAMP}</DeviceID>
                            <DeviceAction type="integer">7</DeviceAction>
                            <DeviceActionValue type="integer">660</DeviceActionValue>
                        </Action>
                        <Action type="dict">
                            <Class type="integer">100</Class>
                            <ActionGroupID type="integer">{AG_OUTER}</ActionGroupID>
                        </Action>
                        <Action type="dict">
                            <Class type="integer">201</Class>
                            <VarID type="integer">{VAR_MODE}</VarID>
                            <VarAction type="integer">0</VarAction>
                            <VarValue type="string">active</VarValue>
                        </Action>
                    </ActionSteps>
                </ActionGroup>
            </Trigger>
        </TriggerList>
        <TDTriggerList type="vector">
            <TDTrigger type="dict">
                <ID type="integer">{SCHED_NIGHT}</ID>
                <Name type="string">Nightly Lamp Off</Name>
                <Class type="integer">100</Class>
                <Enabled type="bool">true</Enabled>
                <TimeType type="integer">0</TimeType>
                <DateType type="integer">0</DateType>
                <Time type="integer">85800</Time>
                <RepeatInterval type="integer">1</RepeatInterval>
                <RandomizeAmount type="integer">0</RandomizeAmount>
                <Condition type="dict"><Type type="integer">0</Type></Condition>
                <ActionGroup type="dict">
                    <ActionSteps type="vector">
                        <Action type="dict">
                            <Class type="integer">1</Class>
                            <DeviceID type="integer">{DEV_LAMP}</DeviceID>
                            <DeviceAction type="integer">5</DeviceAction>
                            <DeviceActionValue type="integer">0</DeviceActionValue>
                            <DelayAction type="bool">true</DelayAction>
                            <DelayAmount type="integer">120</DelayAmount>
                        </Action>
                        <Action type="dict">
                            <Class type="integer">101</Class>
                            <ScriptUseLink type="bool">false</ScriptUseLink>
                            <ScriptSource type="string">import indigo
    indigo.device.turnOff({DEV_LAMP})</ScriptSource>
                            <ScriptType type="integer">0</ScriptType>
                        </Action>
                        <Action type="dict">
                            <Class type="integer">3</Class>
                            <DeviceID type="integer">{DEV_TRV}</DeviceID>
                            <HVACAction type="integer">0</HVACAction>
                            <HVACActionValue type="string">18.5</HVACActionValue>
                        </Action>
                        <Action type="dict">
                            <Class type="integer">9</Class>
                            <DeviceID type="integer">{DEV_SENSOR}</DeviceID>
                            <DeviceAction type="integer">30</DeviceAction>
                        </Action>
                    </ActionSteps>
                </ActionGroup>
            </TDTrigger>
        </TDTriggerList>
        <ActionGroupList type="vector">
            <ActionGroup type="dict">
                <ID type="integer">{AG_INNER}</ID>
                <Name type="string">Inner Lamp Group</Name>
                <ActionSteps type="vector">
                    <Action type="dict">
                        <Class type="integer">1</Class>
                        <DeviceID type="integer">{DEV_LAMP}</DeviceID>
                        <DeviceAction type="integer">4</DeviceAction>
                        <DeviceActionValue type="integer">0</DeviceActionValue>
                    </Action>
                </ActionSteps>
            </ActionGroup>
            <ActionGroup type="dict">
                <ID type="integer">{AG_OUTER}</ID>
                <Name type="string">Outer Wrapper Group</Name>
                <ActionSteps type="vector">
                    <Action type="dict">
                        <Class type="integer">100</Class>
                        <ActionGroupID type="integer">{AG_INNER}</ActionGroupID>
                    </Action>
                    <Action type="dict">
                        <Class type="integer">999</Class>
                        <PluginID type="string">com.example.testplugin</PluginID>
                        <TypeLabelPlugin type="string">Send Fancy Command</TypeLabelPlugin>
                        <MetaProps type="dict">
                            <com.example.testplugin type="dict">
                                <targetDevice type="string">{DEV_SENSOR}</targetDevice>
                            </com.example.testplugin>
                        </MetaProps>
                    </Action>
                </ActionSteps>
            </ActionGroup>
        </ActionGroupList>
    </Database>
""")


@pytest.fixture()
def db_file(tmp_path):
    path = tmp_path / "Synthetic.indiDb"
    path.write_text(SYNTHETIC_DB, encoding="utf-8")
    return str(path)


@pytest.fixture()
def parsed(db_file):
    return parse_indidb(db_file)


# ── decode_typed_element ─────────────────────────────────────────────────────

def test_decode_typed_values():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(
        '<X type="dict">'
        '<A type="integer">42</A><B type="real">3.5</B>'
        '<C type="bool">true</C><D type="string">hi</D>'
        '<E type="vector"><F type="integer">1</F></E>'
        '</X>')
    decoded = decode_typed_element(root)
    assert decoded == {"A": 42, "B": 3.5, "C": True, "D": "hi", "E": [1]}


# ── parser ───────────────────────────────────────────────────────────────────

def test_parse_counts_and_names(parsed):
    assert parsed.counts() == {"triggers": 1, "schedules": 1, "action_groups": 2}
    assert parsed.device_names[DEV_LAMP] == "Test Lamp"
    assert parsed.variable_names[VAR_MODE] == "house_mode"


def test_parse_trigger_structure(parsed):
    trigger = parsed.triggers[TRIG_MOTION]
    assert trigger["Class"] == 501
    assert trigger["DeviceID"] == DEV_SENSOR
    steps = trigger["ActionGroup"]["ActionSteps"]
    assert [s["Class"] for s in steps] == [1, 100, 201]


def test_parse_rejects_torn_file(tmp_path):
    path = tmp_path / "Torn.indiDb"
    path.write_text(SYNTHETIC_DB[: len(SYNTHETIC_DB) // 2], encoding="utf-8")
    with pytest.raises(Exception):
        parse_indidb(str(path))


# ── reverse index ────────────────────────────────────────────────────────────

@pytest.fixture()
def index(parsed):
    return build_reverse_index(parsed)


def _roles_for(index, kind, entity_id, container_id=None):
    refs = index.references_to(kind, entity_id)
    if container_id is not None:
        refs = [r for r in refs if r["id"] == container_id]
    return {r["role"] for r in refs}


def test_trigger_watches_its_event_device(index):
    assert "watches" in _roles_for(index, "device", DEV_SENSOR, TRIG_MOTION)


def test_compound_condition_reads_recursed(index):
    assert "condition_reads" in _roles_for(index, "variable", VAR_MODE, TRIG_MOTION)
    assert "condition_reads" in _roles_for(index, "device", DEV_LAMP, TRIG_MOTION)


def test_action_steps_indexed(index):
    assert "acts_on" in _roles_for(index, "device", DEV_LAMP, TRIG_MOTION)
    assert "sets" in _roles_for(index, "variable", VAR_MODE, TRIG_MOTION)
    assert "executes" in _roles_for(index, "action_group", AG_OUTER, TRIG_MOTION)


def test_embedded_script_heuristic(index):
    roles = _roles_for(index, "device", DEV_LAMP, SCHED_NIGHT)
    assert "script_reference" in roles
    assert "acts_on" in roles


def test_thermostat_and_universal_steps_index_acts_on(index):
    # Class 3 (HVAC) step on the TRV and Class 9 (universal beep) on the
    # sensor must both surface as acts_on — they were invisible pre-2.12.1.
    trv_refs = [r for r in index.references_to("device", DEV_TRV)
                if r["id"] == SCHED_NIGHT]
    assert any(r["role"] == "acts_on" and "set heat setpoint" in r.get("detail", "")
               for r in trv_refs), trv_refs
    sensor_refs = [r for r in index.references_to("device", DEV_SENSOR)
                   if r["id"] == SCHED_NIGHT]
    assert any(r["role"] == "acts_on" and "beep" in r.get("detail", "")
               for r in sensor_refs), sensor_refs


def test_lock_unlock_codes_match_runtime_enum():
    from mcp_server.adapters.indidb import schema
    # Runtime-dump verified 23-Jul-2026: Lock=28, Unlock=29, Open=30, Close=31.
    assert schema.DEVICE_ACTION_CODES[28] == "lock"
    assert schema.DEVICE_ACTION_CODES[29] == "unlock"
    assert schema.DEVICE_ACTION_CODES[30] == "open"
    assert schema.DEVICE_ACTION_CODES[31] == "close"


def test_condition_logic_orientation():
    from mcp_server.adapters.indidb import schema
    # Live-verified: 1=AND(all), 0=OR(any) — previously inverted.
    assert schema.CONDITION_LOGIC[1].startswith("AND")
    assert schema.CONDITION_LOGIC[0].startswith("OR")


def test_plugin_config_heuristic(index):
    roles = _roles_for(index, "device", DEV_SENSOR, AG_OUTER)
    assert "plugin_config_reference" in roles


def test_chain_expansion_through_action_groups(index):
    # Inner AG acts on the lamp; the trigger executes Outer which executes
    # Inner — so the trigger must appear with the AG chain attached.
    refs = index.references_to("device", DEV_LAMP)
    chained = [r for r in refs
               if r["id"] == TRIG_MOTION and "via_action_groups" in r]
    assert chained, f"no chained ref for the trigger in {refs}"
    assert chained[0]["via_action_groups"] == [AG_OUTER, AG_INNER]
    assert chained[0]["role"] == "acts_on"


def test_duplicate_references_collapsed(index):
    refs = index.references_to("device", DEV_LAMP)
    keys = [(r["entity_type"], r["id"], r["role"],
             tuple(r.get("via_action_groups", []))) for r in refs]
    assert len(keys) == len(set(keys))


# ── store ────────────────────────────────────────────────────────────────────

def test_store_parses_and_caches(db_file):
    store = IndiDbStructureStore(lambda: db_file, stat_throttle_seconds=0.0)
    assert store.get_structure("trigger", TRIG_MOTION)["Name"] == "Motion Turns On Lamp"
    assert store.lookup_name("device", DEV_LAMP) == "Test Lamp"
    assert store.lookup_name("schedule", SCHED_NIGHT) == "Nightly Lamp Off"
    freshness = store.freshness()
    assert freshness["available"] is True
    assert freshness["counts"]["triggers"] == 1


def test_store_survives_torn_rewrite(db_file):
    store = IndiDbStructureStore(lambda: db_file, stat_throttle_seconds=0.0)
    assert store.get_structure("trigger", TRIG_MOTION) is not None
    # Simulate a mid-rewrite torn file: truncated XML, new mtime.
    with open(db_file, "w", encoding="utf-8") as fh:
        fh.write(SYNTHETIC_DB[: len(SYNTHETIC_DB) // 3])
    os.utime(db_file, (time.time() + 5, time.time() + 5))
    # Last good snapshot is retained.
    assert store.get_structure("trigger", TRIG_MOTION)["Name"] == "Motion Turns On Lamp"


def test_store_refreshes_on_change(db_file):
    store = IndiDbStructureStore(lambda: db_file, stat_throttle_seconds=0.0)
    assert store.get_structure("trigger", TRIG_MOTION) is not None
    updated = SYNTHETIC_DB.replace("Motion Turns On Lamp", "Renamed Trigger")
    with open(db_file, "w", encoding="utf-8") as fh:
        fh.write(updated)
    os.utime(db_file, (time.time() + 5, time.time() + 5))
    assert store.get_structure("trigger", TRIG_MOTION)["Name"] == "Renamed Trigger"


def test_store_handles_missing_file():
    store = IndiDbStructureStore(lambda: "/nonexistent/nowhere.indiDb")
    assert store.get_structure("trigger", 1) is None
    assert store.find_references("device", 1) == []
    assert store.freshness()["available"] is False


def test_live_database_smoke():
    """Parse the real database if this machine has one (skipped elsewhere)."""
    base = "/Library/Application Support/Perceptive Automation"
    import glob
    candidates = sorted(glob.glob(os.path.join(base, "Indigo *", "Databases",
                                               "*.indiDb")), reverse=True)
    if not candidates:
        pytest.skip("no live Indigo database on this machine")
    parsed_live = parse_indidb(candidates[0])
    counts = parsed_live.counts()
    assert counts["triggers"] > 0 and counts["schedules"] > 0
    build_reverse_index(parsed_live)
