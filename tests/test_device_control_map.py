#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_control_map.py
# Description: who_controls gathers everything that can change one device, with
#              when it fires, its conditions and what it does; and
#              explain_device_changes gives each logged change its likely cause.
# Author:      CliveS & Claude Opus 5.5
# Date:        21-11-2026
# Version:     1.0

import base64
import datetime
import logging

import pytest

from mcp_server.adapters.indidb.store import IndiDbStructureStore
from mcp_server.tools.automation_detail import automation_detail_handler as adh
from mcp_server.tools.automation_detail import device_control_map as dcm
from mcp_server.tools.log_query import log_query_handler as lq

from test_indidb_adapter import (AG_INNER, AG_OUTER, DEV_LAMP, DEV_SENSOR, SCHED_NIGHT,
                                 SYNTHETIC_DB, TRIG_MOTION)

LOG = logging.getLogger("test-device-control-map")

SCHED_LINKED = 919191919
TRIG_OFF = 939393939
LINKED_SCRIPT = "Lamp_Evening.py"


def _link_blob(path):
    """Held in lower case below, as Indigo's own bookmark held a real one.
    A stand-in for Indigo's ScriptLink2 bookmark: base64 bytes holding the
    path in printable ASCII, which is all decode_script_link reads."""
    raw = b"\x00\x01book\x00" + path.encode("ascii") + b"\x00\x02"
    return base64.b64encode(raw).decode("ascii")


def _db_with_linked_schedule():
    extra = f"""
            <TDTrigger type="dict">
                <ID type="integer">{SCHED_LINKED}</ID>
                <Name type="string">Evening Lamp Script</Name>
                <Class type="integer">100</Class>
                <Enabled type="bool">false</Enabled>
                <Stealth type="bool">true</Stealth>
                <TimeType type="integer">0</TimeType>
                <DateType type="integer">0</DateType>
                <Time type="integer">72000</Time>
                <RepeatInterval type="integer">1</RepeatInterval>
                <Condition type="dict"><Type type="integer">0</Type></Condition>
                <ActionGroup type="dict">
                    <ActionSteps type="vector">
                        <Action type="dict">
                            <Class type="integer">101</Class>
                            <ScriptUseLink type="bool">true</ScriptUseLink>
                            <ScriptLink2 type="string">{_link_blob('/library/scripts/' + LINKED_SCRIPT.lower())}</ScriptLink2>
                        </Action>
                    </ActionSteps>
                </ActionGroup>
            </TDTrigger>
        </TDTriggerList>"""
    off_trigger = f"""
            <Trigger type="dict">
                <ID type="integer">{TRIG_OFF}</ID>
                <Name type="string">Lamp Off When Sensor Clears</Name>
                <Class type="integer">598</Class>
                <Enabled type="bool">true</Enabled>
                <Stealth type="bool">true</Stealth>
                <PluginID type="string">com.example.activity</PluginID>
                <TypeLabelPlugin type="string">Group Changed</TypeLabelPlugin>
                <MetaProps type="dict">
                    <com.example.activity type="dict">
                        <groupDevice type="string">{DEV_SENSOR}</groupDevice>
                        <fireOn type="string">deactivated</fireOn>
                    </com.example.activity>
                </MetaProps>
                <Condition type="dict"><Type type="integer">0</Type></Condition>
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
        </TriggerList>"""
    db = SYNTHETIC_DB.replace("</TDTriggerList>", extra, 1)
    return db.replace("</TriggerList>", off_trigger, 1)


class FakeDev:
    def __init__(self, dev_id, name, global_props):
        self.id = dev_id
        self.name = name
        self.globalProps = global_props


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    db = tmp_path / "Synthetic.indiDb"
    db.write_text(_db_with_linked_schedule(), encoding="utf-8")
    logs = tmp_path / "Logs"
    logs.mkdir()
    monkeypatch.setattr(lq, "_LOG_ROOT", str(logs))
    scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    (scripts / LINKED_SCRIPT).write_text(
        f"import indigo\nindigo.device.turnOn({DEV_LAMP})\n", encoding="utf-8")
    (scripts / "Unrelated.py").write_text("print('nothing here')\n", encoding="utf-8")
    prefs = tmp_path / "Prefs"
    prefs.mkdir()
    (prefs / "com.example.watchdog.indiPref").write_text(
        f'<?xml version="1.0"?><Prefs type="dict">'
        f'<watchedDevices type="string">123, {DEV_LAMP}</watchedDevices>'
        f'<interval type="integer">30</interval></Prefs>', encoding="utf-8")
    (prefs / "com.example.other.indiPref").write_text(
        '<?xml version="1.0"?><Prefs type="dict"><x type="integer">5</x></Prefs>',
        encoding="utf-8")

    pages = {
        5001: [{"index": 0, "type": "action_group", "caption": "Lamp button",
                "on_tap": [{"action_class": "device (class 1)",
                            "action": "turn on (code 4)", "device_id": DEV_LAMP}]},
               {"index": 1, "type": "device", "caption": "Sensor",
                "target": {"id": DEV_SENSOR}, "action_class": "control_devices"}],
        5002: [{"index": 0, "type": "device", "caption": "Lamp tile",
                "target": {"id": DEV_LAMP}, "action_class": "control_devices"}],
    }
    devices = [
        FakeDev(DEV_LAMP, "Test Lamp", {"com.example.plugin": {"members": str(DEV_LAMP)}}),
        FakeDev(222, "Lamp Group", {"com.example.groups": {"members": f"1,{DEV_LAMP}",
                                                           "name": "group"}}),
        FakeDev(333, "Unrelated", {"com.example.groups": {"members": "1,2"}}),
    ]
    store = IndiDbStructureStore(lambda: str(db), stat_throttle_seconds=0.0)
    detail = adh.AutomationDetailHandler(
        data_provider=None, structure_store=store,
        log_query_handler=lq.LogQueryHandler(None, logger=LOG), logger=LOG)
    cmap = dcm.DeviceControlMap(
        detail_handler=detail, structure_store=store,
        page_reader=lambda pid: (pages.get(pid), None),
        control_pages_provider=lambda: [(5001, "Living Room"), (5002, "Hall")],
        devices_provider=lambda: devices,
        prefs_dir_provider=lambda: str(prefs),
        script_dirs_provider=lambda: [str(scripts)],
        logger=LOG)
    return cmap, logs


def _by(controls, kind, cid, how=None, chain=None):
    for c in controls:
        if c["entity_type"] != kind or c["id"] != cid:
            continue
        if how is not None and c["how"] != how:
            continue
        got_chain = [a["id"] for a in c.get("via_action_groups", [])]
        if chain is not None and got_chain != chain:
            continue
        return c
    return None


# ── who_controls ─────────────────────────────────────────────────────────────

def test_a_direct_trigger_step_says_what_it_does_and_when(rig):
    cmap, _ = rig
    out = cmap.who_controls(DEV_LAMP)
    assert out["success"] is True, out
    motion = _by(out["controls"], "trigger", TRIG_MOTION, how="action step", chain=[])
    assert motion is not None, out["controls"]
    assert motion["action"] == "set brightness to 66%"
    assert motion["when"].startswith("when Test Motion Sensor onOffState")
    assert motion["conditions"] != "none"


def test_a_schedule_gives_its_time_and_the_delay_on_the_step(rig):
    cmap, _ = rig
    night = _by(cmap.who_controls(DEV_LAMP)["controls"], "schedule", SCHED_NIGHT,
                how="action step")
    assert night["when"] == "at 23:50, every day"
    assert night["action"] == "turn off after 120 seconds"
    assert night["steps"][0]["delay_seconds"] == 120
    assert night["conditions"] == "none"


def test_an_action_group_chain_names_the_route_and_the_inner_action(rig):
    cmap, _ = rig
    controls = cmap.who_controls(DEV_LAMP)["controls"]
    via = _by(controls, "trigger", TRIG_MOTION, how="action step",
              chain=[AG_OUTER, AG_INNER])
    assert via is not None, controls
    assert via["action"] == "turn on"
    inner = _by(controls, "action_group", AG_INNER, chain=[])
    assert inner["when"] == "when run by Motion Turns On Lamp, Outer Wrapper Group" or \
        inner["when"].startswith("when run by ")


def test_an_embedded_script_is_listed_as_heuristic(rig):
    cmap, _ = rig
    hit = _by(cmap.who_controls(DEV_LAMP)["controls"], "schedule", SCHED_NIGHT,
              how="embedded script")
    assert hit is not None
    assert hit["confidence"] == "heuristic"


def test_a_linked_script_file_is_traced_to_the_schedule_that_runs_it(rig):
    cmap, _ = rig
    out = cmap.who_controls(DEV_LAMP)
    linked = _by(out["controls"], "schedule", SCHED_LINKED, how="linked script")
    assert linked is not None, out["controls"]
    assert linked["enabled"] is False
    assert linked["when"] == "at 20:00, every day"
    assert linked["conditions"] == "none"
    assert linked["action"] == f"runs {LINKED_SCRIPT}, which mentions the device"
    script = [s for s in out["scripts"] if s["script"].endswith(LINKED_SCRIPT)]
    assert script and script[0]["run_by"] == ["Evening Lamp Script"]
    assert not [s for s in out["scripts"] if "Unrelated" in s["script"]]


def test_every_control_entry_carries_the_same_fields(rig):
    cmap, _ = rig
    for entry in cmap.who_controls(DEV_LAMP)["controls"]:
        missing = {"entity_type", "id", "name", "how", "when", "conditions"} - set(entry)
        assert not missing, (entry, missing)


def test_a_disabled_automation_is_listed_last_and_counted(rig):
    cmap, _ = rig
    out = cmap.who_controls(DEV_LAMP)
    assert out["controls"][-1]["enabled"] is False
    assert "1 of the automations is disabled" in out["summary"]


def test_control_page_buttons_that_act_on_it_are_found(rig):
    cmap, _ = rig
    pages = cmap.who_controls(DEV_LAMP)["control_pages"]
    found = {(p["page"], p["element"]) for p in pages}
    assert ("Living Room", "Lamp button") in found
    assert ("Hall", "Lamp tile") in found
    assert ("Living Room", "Sensor") not in found
    button = [p for p in pages if p["element"] == "Lamp button"][0]
    assert button["does"] == "tapping it will turn on"


def test_other_devices_holding_the_id_are_found_but_not_the_device_itself(rig):
    cmap, _ = rig
    held = cmap.who_controls(DEV_LAMP)["plugin_devices"]
    assert [(h["device"], h["plugin"], h["settings"]) for h in held] == \
        [("Lamp Group", "com.example.groups", ["members"])]


def test_plugin_settings_files_holding_the_id_are_found(rig):
    cmap, _ = rig
    prefs = cmap.who_controls(DEV_LAMP)["plugin_settings"]
    assert prefs == [{"plugin": "com.example.watchdog", "settings": ["watchedDevices"],
                      "confidence": "heuristic"}]


def test_what_only_reads_the_device_is_kept_apart(rig):
    cmap, _ = rig
    out = cmap.who_controls(DEV_LAMP)
    assert [c["id"] for c in out["checks_it"]] == [TRIG_MOTION]
    sensor = cmap.who_controls(DEV_SENSOR)
    assert [r["id"] for r in sensor["reacts_to_it"]] == [TRIG_MOTION]


def test_the_sources_can_be_switched_off(rig):
    cmap, _ = rig
    out = cmap.who_controls(DEV_LAMP, include_scripts=False, include_plugins=False,
                            include_control_pages=False)
    assert out["scripts"] == [] and out["plugin_devices"] == []
    assert out["plugin_settings"] == [] and out["control_pages"] == []
    assert _by(out["controls"], "schedule", SCHED_LINKED) is None


def test_an_unknown_device_is_refused(rig):
    cmap, _ = rig
    out = cmap.who_controls(999999999)
    assert out["success"] is False and "not found" in out["error"]


def test_the_notes_say_what_is_not_covered(rig):
    cmap, _ = rig
    notes = " ".join(cmap.who_controls(DEV_LAMP)["notes"])
    assert "HomeKit" in notes and "explain_device_changes" in notes


# ── explain_device_changes ───────────────────────────────────────────────────

def _line(ts, source, message):
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\t{source}\t{message}"


def _write(logs, lines):
    by_day = {}
    for ts, text in lines:
        by_day.setdefault(ts.date(), []).append(text)
    for day, texts in by_day.items():
        (logs / f"{day.isoformat()} Events.txt").write_text("\n".join(texts) + "\n",
                                                            encoding="utf-8")


def _evening_week(logs):
    """Three evenings at 20:00 the motion trigger turns the lamp on (logged
    sent, then received); one lunchtime change with nothing behind it; and
    status requests that are not changes."""
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    lines = []
    for back in (1, 2, 3):
        at = today - datetime.timedelta(days=back) + datetime.timedelta(hours=20)
        lines += [
            (at - datetime.timedelta(seconds=2), _line(at - datetime.timedelta(seconds=2),
                                                       "Trigger", "Motion Turns On Lamp")),
            (at, _line(at, "Z-Wave", 'sent "Test Lamp" on')),
            (at + datetime.timedelta(seconds=1),
             _line(at + datetime.timedelta(seconds=1), "Z-Wave",
                   'received "Test Lamp" status update is on')),
            (at + datetime.timedelta(minutes=5),
             _line(at + datetime.timedelta(minutes=5), "Z-Wave",
                   'sent "Test Lamp" status request')),
        ]
    noon = today - datetime.timedelta(days=2) + datetime.timedelta(hours=13)
    lines.append((noon, _line(noon, "Z-Wave", 'received "Test Lamp" status update is off')))
    lines.sort(key=lambda p: p[0])
    _write(logs, lines)


def test_each_change_gets_its_cause_and_the_summary_groups_them(rig):
    cmap, logs = rig
    _evening_week(logs)
    out = cmap.explain_device_changes(DEV_LAMP, days=7)
    assert out["success"] is True, out
    assert out["change_count"] == 4               # pairs counted once, requests ignored
    top = out["by_cause"][0]
    assert top["count"] == 3 and top["cause"] == "trigger Motion Turns On Lamp"
    assert top["earliest"] == top["latest"] == "20:00"
    manual = [g for g in out["by_cause"] if g["cause"].startswith("nothing logged")]
    assert manual and manual[0]["count"] == 1
    assert out["events"][0]["likely_cause"]["id"] == TRIG_MOTION
    assert out["events"][0]["day"] in dcm._WEEKDAYS


def test_between_and_contains_narrow_the_changes(rig):
    cmap, logs = rig
    _evening_week(logs)
    assert cmap.explain_device_changes(DEV_LAMP, between="19:30-20:30")["change_count"] == 3
    assert cmap.explain_device_changes(DEV_LAMP, contains="off")["change_count"] == 1


def test_limit_keeps_the_newest_and_says_so(rig):
    cmap, logs = rig
    _evening_week(logs)
    out = cmap.explain_device_changes(DEV_LAMP, limit=2)
    assert len(out["events"]) == 2 and out["change_count"] == 4
    assert any("newest 2" in n for n in out["notes"])
    assert out["events"][0]["time"] > out["events"][1]["time"]


def test_a_bad_window_is_refused(rig):
    cmap, _ = rig
    out = cmap.explain_device_changes(DEV_LAMP, between="8pm")
    assert out["success"] is False and "19:30-20:30" in out["error"]


def test_no_changes_says_so(rig):
    cmap, _ = rig
    out = cmap.explain_device_changes(DEV_LAMP)
    assert out["change_count"] == 0
    assert any("No change" in n for n in out["notes"])


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expect", [
    ("19:30-20:30", (1170, 1230)), ("23:00 - 01:00", (1380, 60)), (None, None), ("", None)])
def test_parse_between(text, expect):
    assert dcm.parse_between(text) == (expect, None)


@pytest.mark.parametrize("text", ["8pm", "25:00-26:00", "10:61-11:00"])
def test_parse_between_refuses(text):
    window, problem = dcm.parse_between(text)
    assert window is None and problem


def test_a_window_across_midnight():
    window = (23 * 60, 60)
    assert dcm.in_window(datetime.datetime(2026, 1, 1, 23, 30), window)
    assert dcm.in_window(datetime.datetime(2026, 1, 1, 0, 30), window)
    assert not dcm.in_window(datetime.datetime(2026, 1, 1, 12, 0), window)


@pytest.mark.parametrize("value, hit", [
    (DEV_LAMP, True), (str(DEV_LAMP), True), (f"1, {DEV_LAMP}", True),
    ([1, DEV_LAMP], True), ({"a": {"b": str(DEV_LAMP)}}, True),
    (f"{DEV_LAMP}9", False), (True, False), ("1,2", False)])
def test_id_in_value(value, hit):
    assert dcm.id_in_value(value, DEV_LAMP) is hit


@pytest.mark.parametrize("timing, phrase", [
    ({"time_type": "absolute time of day (TimeType 0)", "at": "20:00",
      "repeat_every_days": 1}, "at 20:00, every day"),
    ({"time_type": "sun-relative (TimeType 2)", "sun_offset": "+15m",
      "repeat_every_days": 1}, "at sunset +15m, every day"),
    ({"time_type": "repeating interval (TimeType 3)", "every_seconds": 600},
     "every 600 seconds"),
    ({"time_type": "absolute time of day (TimeType 0)", "at": "07:00",
      "repeat_every_days": 0}, "at 07:00, once only"),
])
def test_schedule_when(timing, phrase):
    assert dcm.schedule_when(timing) == phrase


def test_change_text_keeps_the_words_either_side():
    assert dcm.change_text('sent "Test Lamp" on', '"Test Lamp"') == "sent on"


def test_timing_alone_never_names_a_cause(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    _write(logs, [
        (at - datetime.timedelta(seconds=3),
         _line(at - datetime.timedelta(seconds=3), "Trigger", "Kitchen Sink Leak Sensor")),
        (at, _line(at, "Z-Wave", 'sent "Test Lamp" off')),
    ])
    event = cmap.explain_device_changes(DEV_LAMP, days=1)["events"][0]
    assert event["likely_cause"] is None
    assert event["nearest_activity"]["name"] == "Kitchen Sink Leak Sensor"


def test_a_script_line_explains_a_change_whose_automation_is_hidden(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    _write(logs, [
        (at - datetime.timedelta(seconds=1),
         _line(at - datetime.timedelta(seconds=1), "Script",
               "[12:00:00.000] Test Lamp turned ON")),
        (at, _line(at, "Z-Wave", 'sent "Test Lamp" on')),
    ])
    out = cmap.explain_device_changes(DEV_LAMP, days=1)
    assert out["change_count"] == 1                 # the script line is evidence, not a change
    cause = out["events"][0]["likely_cause"]
    assert cause["entity_type"] == "script"
    assert set(cause["run_by_one_of"]) == {"Evening Lamp Script",
                                           "Lamp Off When Sensor Clears"}
    assert {h["name"] for h in out["hidden_from_event_log"]} == {
        "Evening Lamp Script", "Lamp Off When Sensor Clears"}
    assert any("stay out of the event log" in n for n in out["notes"])


def test_history_changes_forward_fills_sparse_rows():
    rows = [{"ts": "2026-11-20 08:00:00", "onoffstate": False, "brightnesslevel": 0},
            {"ts": "2026-11-20 09:00:00", "onoffstate": None, "brightnesslevel": None},
            {"ts": "2026-11-20 20:00:00", "onoffstate": True, "brightnesslevel": 60},
            {"ts": "2026-11-20 20:10:00", "onoffstate": None, "brightnesslevel": 30},
            {"ts": "2026-11-20 23:00:00", "onoffstate": "0", "brightnesslevel": None}]
    got = [(ts.strftime("%H:%M"), what) for ts, what in dcm.history_changes(reversed(rows))]
    assert got == [("20:00", "turned on at 60%"), ("20:10", "brightness 30%"),
                   ("23:00", "turned off")]


def test_a_device_its_plugin_never_logs_falls_back_to_history(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=3)
    fmt = "%Y-%m-%d %H:%M:%S"
    asked = []

    def reader(did, hours, columns):
        asked.append((did, hours, tuple(columns)))
        return {"success": True, "rows": [
            {"ts": (at - datetime.timedelta(hours=1)).strftime(fmt), "onoffstate": False},
            {"ts": at.strftime(fmt), "onoffstate": True}]}

    cmap.history_reader = reader
    _write(logs, [(at - datetime.timedelta(seconds=2),
                   _line(at - datetime.timedelta(seconds=2), "Trigger",
                         "Motion Turns On Lamp"))])
    out = cmap.explain_device_changes(DEV_LAMP, days=1)
    assert out["change_source"] == "SQL Logger history"
    assert out["change_count"] == 1
    assert out["events"][0]["what"] == "turned on"
    assert out["events"][0]["likely_cause"]["id"] == TRIG_MOTION
    assert asked[0] == (DEV_LAMP, 24, ("onoffstate", "brightnesslevel"))


def test_history_is_not_read_when_the_log_has_the_changes(rig):
    cmap, logs = rig
    _evening_week(logs)
    def reader(did, hours, columns):
        if did == DEV_LAMP:
            pytest.fail("the lamp's own history was read although the log had its changes")
        return {"success": False, "error": "no table"}
    cmap.history_reader = reader
    assert cmap.explain_device_changes(DEV_LAMP)["change_source"] == "event log"


def _sensor_history(times):
    fmt = "%Y-%m-%d %H:%M:%S"

    def reader(did, hours, columns):
        if did != DEV_SENSOR:
            return {"success": False, "error": "no table"}
        rows = [{"ts": ts.strftime(fmt), "onoffstate": None} for ts in times]   # empty rows
        rows += [{"ts": ts.strftime(fmt), "onoffstate": 1} for ts in times]
        return {"success": True, "rows": rows}
    return reader


def test_a_change_with_no_log_line_is_traced_through_what_its_trigger_watches(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    cmap.history_reader = _sensor_history([at])
    _write(logs, [(at, _line(at, "Z-Wave", 'sent "Test Lamp" set brightness to 30'))])
    cause = cmap.explain_device_changes(DEV_LAMP, days=1)["events"][0]["likely_cause"]
    assert cause["id"] == TRIG_MOTION, cause
    assert cause["confidence"] == "heuristic"
    assert "Test Motion Sensor changed 0.0 seconds before" in cause["evidence"][0]


def test_the_trigger_for_the_matching_direction_wins(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    cmap.history_reader = _sensor_history([at])
    _write(logs, [(at, _line(at, "Z-Wave", 'sent "Test Lamp" off'))])
    cause = cmap.explain_device_changes(DEV_LAMP, days=1)["events"][0]["likely_cause"]
    assert cause["id"] == TRIG_OFF, cause
    assert any("stay out of the event log" in e for e in cause["evidence"])
    assert "or_possibly" not in cause


def test_a_watched_device_that_did_not_change_names_no_cause(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    cmap.history_reader = _sensor_history([at - datetime.timedelta(minutes=10)])
    _write(logs, [(at, _line(at, "Z-Wave", 'sent "Test Lamp" on'))])
    assert cmap.explain_device_changes(DEV_LAMP, days=1)["events"][0]["likely_cause"] is None


@pytest.mark.parametrize("what, direction", [
    ("sent on", "on"), ("sent off", "off"), ("sent set brightness to 30", "on"),
    ("turned off", "off"), ("status update", None)])
def test_change_direction(what, direction):
    assert dcm.change_direction(what) == direction


@pytest.mark.parametrize("text, direction", [
    ("Kitchen Light On If Any Occupancy  Sensor ON", "on"),
    ("Turn Off Kitchen Light When No Motion", "off"),
    ("runs Kitchen_Lights_Off.py, which mentions the device", "off"),
    ("Hall Lamp Toggle", None)])
def test_word_direction(text, direction):
    assert dcm.word_direction(text) == direction


def test_ids_in_finds_ids_in_plugin_settings():
    props = {"com.x": {"groupDevice": "1389343786", "fireOn": "activated", "n": 5,
                       "list": [444555666, "1,2"]}}
    assert sorted(dcm.ids_in(props)) == [444555666, 1389343786]


def test_a_history_row_with_no_value_is_not_a_change(rig):
    cmap, logs = rig
    at = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=2)
    fmt = "%Y-%m-%d %H:%M:%S"
    cmap.history_reader = lambda did, hours, columns: {"success": True, "rows": [
        {"ts": at.strftime(fmt), "onoffstate": None, "battery": None},
        {"ts": (at - datetime.timedelta(minutes=10)).strftime(fmt), "onoffstate": 1}]}
    _write(logs, [(at, _line(at, "Z-Wave", 'sent "Test Lamp" on'))])
    assert cmap.explain_device_changes(DEV_LAMP, days=1)["events"][0]["likely_cause"] is None
