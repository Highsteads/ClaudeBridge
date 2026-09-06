#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_actions.py
# Description: The Actions.xml guard behind execute_device_action — the three
#              ways Indigo's own executeAction fails silently, each turned into
#              a refusal a caller can act on (ClaudeBridge v2.25.0).
# Author:      CliveS & Claude Opus 5
# Date:        06-09-2026
# Version:     1.0

import os
import xml.etree.ElementTree as ET

import pytest

from mcp_server.common import plugin_actions


# A cut-down Actions.xml carrying every shape that matters: a device action with
# real fields, a device action with only layout fields, and a plugin-level action.
SAMPLE = """<?xml version="1.0"?>
<Actions>
    <Action id="setTimerStartValue" deviceFilter="self.timer" uiPath="DeviceActions">
        <Name>Set Timer Start Value</Name>
        <CallbackMethod>setTimerStartValue</CallbackMethod>
        <ConfigUI>
            <Field id="explain" type="label">
                <Label>Layout only.</Label>
            </Field>
            <Field id="sep" type="separator"/>
            <Field id="amount" type="textfield" defaultValue="60"/>
            <Field id="amountType" type="menu" defaultValue="seconds"/>
        </ConfigUI>
    </Action>
    <Action id="refreshState" deviceFilter="self.garageDoor">
        <Name>Re-read Door State</Name>
        <CallbackMethod>actionRefreshState</CallbackMethod>
        <ConfigUI>
            <Field id="lbl" type="label"><Label>Nothing to set.</Label></Field>
        </ConfigUI>
    </Action>
    <Action id="generateReport" uiPath="PluginActions">
        <Name>Generate Report</Name>
        <CallbackMethod>actionGenerateReport</CallbackMethod>
        <ConfigUI>
            <Field id="reportDays" type="menu" defaultValue="30"/>
        </ConfigUI>
    </Action>
</Actions>
"""


@pytest.fixture(scope="module")
def actions():
    return plugin_actions.parse_actions_xml(SAMPLE)


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_every_action_is_found(actions):
    assert set(actions) == {"setTimerStartValue", "refreshState", "generateReport"}


def test_devicefilter_marks_a_device_action(actions):
    """This flag is the whole guard — if it stops being read, the tool is a wrapper."""
    assert actions["setTimerStartValue"]["device_action"] is True
    assert actions["refreshState"]["device_action"] is True
    assert actions["generateReport"]["device_action"] is False


def test_layout_fields_are_not_reported_as_props(actions):
    """A caller told to fill in a 'separator' would go looking for a value."""
    assert actions["setTimerStartValue"]["fields"] == ["amount", "amountType"]
    assert actions["refreshState"]["fields"] == []


def test_name_and_callback_are_carried(actions):
    assert actions["setTimerStartValue"]["name"] == "Set Timer Start Value"
    assert actions["generateReport"]["callback"] == "actionGenerateReport"


def test_action_without_an_id_is_skipped():
    parsed = plugin_actions.parse_actions_xml(
        '<Actions><Action><Name>No id</Name></Action></Actions>'
    )
    assert parsed == {}


def test_malformed_xml_raises_for_the_caller_to_handle():
    with pytest.raises(ET.ParseError):
        plugin_actions.parse_actions_xml("<Actions><Action id='x'>")


# ── The three silent failures ────────────────────────────────────────────────

def test_unknown_action_id_is_refused(actions):
    """Indigo returns cleanly for a misspelt action id and does nothing."""
    verdict = plugin_actions.check_call(actions, "setTimerStartVlaue", 123)
    assert verdict["ok"] is False
    assert "not an action this plugin declares" in verdict["error"]


def test_device_action_without_a_device_is_refused(actions):
    """The Email+ fault: props arrive, the DEVICE is what was missing."""
    verdict = plugin_actions.check_call(actions, "setTimerStartValue", None,
                                        {"amount": "43"})
    assert verdict["ok"] is False
    assert "DEVICE action" in verdict["error"]
    assert "self.timer" in verdict["error"]


def test_device_action_with_a_device_is_allowed(actions):
    verdict = plugin_actions.check_call(actions, "setTimerStartValue", 1984141373,
                                        {"amount": "43", "amountType": "seconds"})
    assert verdict["ok"] is True
    assert verdict["error"] == ""
    assert verdict["warnings"] == []


def test_plugin_level_action_needs_no_device(actions):
    verdict = plugin_actions.check_call(actions, "generateReport", None,
                                        {"reportDays": "30"})
    assert verdict["ok"] is True
    assert verdict["warnings"] == []


# ── Warnings: allowed, but worth saying ──────────────────────────────────────

def test_device_id_on_a_plugin_action_warns_but_proceeds(actions):
    verdict = plugin_actions.check_call(actions, "generateReport", 999)
    assert verdict["ok"] is True
    assert any("plugin-level action" in w for w in verdict["warnings"])


def test_undeclared_prop_is_flagged_as_a_likely_typo(actions):
    verdict = plugin_actions.check_call(actions, "setTimerStartValue", 1,
                                        {"amount": "43", "amuntType": "seconds"})
    assert verdict["ok"] is True
    assert any("amuntType" in w for w in verdict["warnings"])


def test_an_action_declaring_no_fields_accepts_any_props(actions):
    """Every IWS hidden action has no ConfigUI and legitimately takes props."""
    verdict = plugin_actions.check_call(actions, "refreshState", 1,
                                        {"source": "claude"})
    assert verdict["ok"] is True
    assert verdict["warnings"] == []


# ── Reading from disk ────────────────────────────────────────────────────────

def test_empty_folder_path_degrades_rather_than_raising():
    result = plugin_actions.read_plugin_actions("")
    assert result["available"] is False
    assert "unknown plugin id" in result["reason"]


def test_missing_actions_xml_degrades(tmp_path):
    result = plugin_actions.read_plugin_actions(str(tmp_path))
    assert result["available"] is False
    assert "no Actions.xml" in result["reason"]


def test_malformed_actions_xml_degrades(tmp_path):
    target = tmp_path / "Contents" / "Server Plugin"
    target.mkdir(parents=True)
    (target / "Actions.xml").write_text("<Actions><Action id='x'>", encoding="utf-8")
    result = plugin_actions.read_plugin_actions(str(tmp_path))
    assert result["available"] is False
    assert "did not parse" in result["reason"]


def test_a_real_bundle_layout_is_read(tmp_path):
    target = tmp_path / "Contents" / "Server Plugin"
    target.mkdir(parents=True)
    (target / "Actions.xml").write_text(SAMPLE, encoding="utf-8")
    result = plugin_actions.read_plugin_actions(str(tmp_path))
    assert result["available"] is True
    assert "setTimerStartValue" in result["actions"]
    assert result["path"].endswith(os.path.join("Server Plugin", "Actions.xml"))


def test_non_ascii_action_name_does_not_break_the_read(tmp_path):
    """Indigo's embedded Python defaults open() to ASCII — the encoding is explicit."""
    target = tmp_path / "Contents" / "Server Plugin"
    target.mkdir(parents=True)
    (target / "Actions.xml").write_text(
        '<Actions><Action id="a"><Name>Éclairage — salon</Name></Action></Actions>',
        encoding="utf-8")
    result = plugin_actions.read_plugin_actions(str(tmp_path))
    assert result["available"] is True
    assert result["actions"]["a"]["name"] == "Éclairage — salon"


# ── Discovery listing ────────────────────────────────────────────────────────

def test_summary_is_sorted_and_says_which_need_a_device(actions):
    summary = plugin_actions.summarise_actions(actions)
    assert [row["action_type_id"] for row in summary] == [
        "generateReport", "refreshState", "setTimerStartValue"]
    by_id = {row["action_type_id"]: row for row in summary}
    assert by_id["generateReport"]["needs_device"] is False
    assert by_id["setTimerStartValue"]["needs_device"] is True
    assert by_id["setTimerStartValue"]["props"] == ["amount", "amountType"]
