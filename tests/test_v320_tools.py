#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v320_tools.py
# Description: The 3.2.0 tool additions, each built because raw Python kept
#              doing its job: list_devices by plugin/folder with chosen
#              fields, query_event_log filters, restart_plugin reporting how
#              the restart went, a compact one-device reply with its group,
#              a plugin's saved settings with credentials hidden, and a
#              device_history summary.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from mcp_server.common import device_props, plugin_prefs, restart_watch
from mcp_server.handlers.list_handlers import ListHandlers
from mcp_server.toolsets import devices as devtools
from mcp_server.tools.log_query import log_query_handler as lq

LOG = logging.getLogger("test-v320")


# ── list_devices: plugin, folder, fields ─────────────────────────────────────

class _Provider:
    def __init__(self, devices, folders):
        self.devices, self.folders = devices, folders

    def get_all_devices_unfiltered(self):
        return [dict(d) for d in self.devices]

    def get_device_folders(self):
        return list(self.folders)


DEVICES = [
    {"id": 1, "name": "Garage Person", "pluginId": "com.x.dahua", "folderId": 10,
     "class": "indigo.SensorDevice", "address": "10.0.0.5",
     "states": {"onOffState": False, "streamState": "connected"}},
    {"id": 2, "name": "Garage Vehicle", "pluginId": "com.x.dahua", "folderId": 10,
     "class": "indigo.SensorDevice", "address": "10.0.0.5",
     "states": {"onOffState": True, "streamState": "connected"}},
    {"id": 3, "name": "Hall Lamp", "pluginId": "com.x.z2m", "folderId": 20,
     "class": "indigo.DimmerDevice", "address": "0xabc", "states": {"brightnessLevel": 40}},
]
FOLDERS = [{"id": 10, "name": "Dahua Cameras"}, {"id": 20, "name": "Hall"}]


@pytest.fixture()
def lists():
    return ListHandlers(_Provider(DEVICES, FOLDERS), logger=LOG)


def _ctx(lists):
    from types import SimpleNamespace
    return SimpleNamespace(list_handlers=lists, logger=LOG)


def test_plugin_filter_and_fields(lists):
    out = devtools.list_devices(_ctx(lists), plugin_id="com.x.dahua",
                                fields=["address", "streamState"])
    assert out["count"] == 2 and out["total_matched"] == 2 and out["truncated"] is False
    assert out["devices"][0] == {"id": 1, "name": "Garage Person", "address": "10.0.0.5",
                                 "streamState": "connected"}
    assert "fields_not_found" not in out


def test_folder_by_name_ignoring_case_and_by_id(lists):
    by_name = devtools.list_devices(_ctx(lists), folder="hall")
    assert [d["name"] for d in by_name["devices"]] == ["Hall Lamp"]
    by_id = devtools.list_devices(_ctx(lists), folder=10)
    assert [d["id"] for d in by_id["devices"]] == [1, 2]


def test_unknown_folder_is_an_error_naming_the_real_ones(lists):
    out = devtools.list_devices(_ctx(lists), folder="Loft")
    assert out["success"] is False and "Dahua Cameras" in out["error"]


def test_misspelt_field_is_reported_not_silently_absent(lists):
    out = devtools.list_devices(_ctx(lists), fields=["brightnesslevel"])
    assert out["fields_not_found"] == ["brightnesslevel"]
    assert all(set(d) == {"id", "name"} for d in out["devices"])


def test_state_filter_combines_with_plugin_and_limit_truncates(lists):
    out = devtools.list_devices(_ctx(lists), plugin_id="com.x.dahua",
                                state_filter={"onOffState": True}, fields=["onOffState"])
    assert [d["id"] for d in out["devices"]] == [2]
    capped = devtools.list_devices(_ctx(lists), plugin_id="com.x.dahua", limit=1)
    assert capped["count"] == 1 and capped["total_matched"] == 2 and capped["truncated"]


@pytest.mark.parametrize("args", [
    {"plugin_id": "com.x.dahua", "detail": "full"},
    {"fields": []},
    {"fields": ["ok", ""]},
    {"plugin_id": "  "},
    {"plugin_id": "com.x.dahua", "limit": "lots"},
])
def test_filtered_refusals(lists, args):
    assert devtools.list_devices(_ctx(lists), **args)["success"] is False


# ── query_event_log filters ──────────────────────────────────────────────────

@pytest.fixture()
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(lq, "_LOG_ROOT", str(tmp_path))
    now = datetime.now()
    stamp = lambda minutes: (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S.000")
    lines = [
        f"{stamp(50)}\tSigenergy Manager\tpoll ok",
        f"{stamp(40)}\tSigenergy Manager Error\tModbus read failed",
        f"{stamp(30)}\tDashboards Warning\tcamera slow",
        f"{stamp(20)}\tScript Error\tTraceback (most recent call last):",
        "  File x, line 3",
        "KeyError: 'battery'",
        f"{stamp(10)}\tError (client)\tbad key",
    ]
    (tmp_path / f"{now.strftime('%Y-%m-%d')} Events.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return lq.LogQueryHandler(None, logger=LOG)


def test_source_filter_matches_the_plugins_error_source_too(logs):
    out = logs.query(source="sigenergy")
    assert [e["Message"] for e in out["entries"]] == ["poll ok", "Modbus read failed"]
    assert "last 24 hours" in out["range"]["window"]


def test_contains_searches_continuation_lines(logs):
    out = logs.query(contains="keyerror")
    assert out["count"] == 1 and out["entries"][0]["TypeStr"] == "Script Error"


def test_level_errors_and_warnings(logs):
    errors = logs.query(level="errors")
    assert [e["TypeStr"] for e in errors["entries"]] == [
        "Sigenergy Manager Error", "Script Error", "Error (client)"]
    warnings = logs.query(level="warnings")
    assert "Dashboards Warning" in [e["TypeStr"] for e in warnings["entries"]]


def test_line_count_takes_the_newest_matches_after_filtering(logs):
    out = logs.query(level="errors", line_count=1)
    assert [e["TypeStr"] for e in out["entries"]] == ["Error (client)"]


def test_bad_filters_are_refused(logs):
    assert logs.query(level="fatal")["success"] is False
    assert logs.query(source="  ")["success"] is False


def test_show_timestamp_false_is_honoured_on_the_file_path(logs):
    out = logs.query(level="errors", show_timestamp=False)
    assert all("TimeStamp" not in e for e in out["entries"])


# ── restart_plugin's log watch ───────────────────────────────────────────────

def _write(path, lines, mode="a"):
    with open(path, mode, encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def test_restart_watch_reads_only_what_came_after(tmp_path):
    day = date(2026, 9, 24)
    path = tmp_path / "2026-09-24 Events.txt"
    _write(path, ['2026-09-24 09:00:00.000\tApplication\tStarted plugin "Widget 1.0"'], "w")
    pos = restart_watch.log_position(str(tmp_path), day)
    _write(path, [
        '2026-09-24 09:05:00.000\tApplication\tStopping plugin "Widget 1.0" (pid 1)',
        '2026-09-24 09:05:01.000\tApplication\tStarting plugin "Widget 1.1" (pid 2)',
        "2026-09-24 09:05:01.500\tWidget Error\tstartup failed",
        "  Traceback line",
        '2026-09-24 09:05:02.000\tApplication\tStarted plugin "Widget 1.1"',
        "2026-09-24 09:05:02.100\tOther Plugin Error\tnot ours",
    ])
    got = restart_watch.summarise(restart_watch.read_since(str(tmp_path), pos, day), "Widget")
    assert got["started"] is True and got["version"] == "1.1"
    assert got["errors"] == 1 and got["warnings"] == 0
    assert all("not ours" not in e["Message"] for e in got["log"])
    assert "Traceback line" in got["log"][2]["Message"]


def test_restart_watch_not_started_and_crosses_midnight(tmp_path):
    _write(tmp_path / "2026-09-24 Events.txt",
           ['2026-09-24 23:59:59.000\tApplication\tStopping plugin "Widget 1.0" (pid 1)'], "w")
    pos = (date(2026, 9, 24), 0)
    early = restart_watch.summarise(
        restart_watch.read_since(str(tmp_path), pos, date(2026, 9, 24)), "Widget")
    assert early["started"] is False and early["version"] is None
    _write(tmp_path / "2026-09-25 Events.txt",
           ['2026-09-25 00:00:02.000\tApplication\tStarted plugin "Widget 1.0"'], "w")
    later = restart_watch.summarise(
        restart_watch.read_since(str(tmp_path), pos, date(2026, 9, 25)), "Widget")
    assert later["started"] is True


def test_a_similarly_named_plugin_is_not_mistaken_for_this_one(tmp_path):
    _write(tmp_path / "2026-09-24 Events.txt",
           ['2026-09-24 09:00:00.000\tApplication\tStarted plugin "Widget Pro 2.0"',
            "2026-09-24 09:00:01.000\tWidget Pro Error\tnot ours"], "w")
    got = restart_watch.summarise(
        restart_watch.read_since(str(tmp_path), (date(2026, 9, 24), 0), date(2026, 9, 24)),
        "Widget")
    # "Widget Pro" starts with "Widget " — the source test must not count its
    # lines. Its Started line names "Widget Pro 2.0", whose version would read
    # "Pro 2.0"; neither may be reported as this plugin's.
    assert got["errors"] == 0 and got["started"] is False and got["log"] == []


def test_a_failed_start_logged_by_indigo_counts_as_an_error(tmp_path):
    _write(tmp_path / "2026-09-24 Events.txt",
           ['2026-09-24 09:00:00.000\tError\tplugin "Widget 1.1" failed to start'], "w")
    got = restart_watch.summarise(
        restart_watch.read_since(str(tmp_path), (date(2026, 9, 24), 0), date(2026, 9, 24)),
        "Widget")
    assert got["errors"] == 1 and got["started"] is False


# ── compact one-device reply ─────────────────────────────────────────────────

def test_compact_device_drops_the_repeats_and_keeps_other_plugins_props():
    dev = {"id": 5, "pluginId": "com.x.dahua", "name": "Garage Person",
           "pluginProps": {"address": "a"}, "ownerProps": {"address": "a"},
           "globalProps": {"com.x.dahua": {"address": "a"},
                           "com.x.homekit": {"exposed": True}, "com.x.empty": {}},
           "sharedProps": {}, "supportsOnState": True, "batteryLevel": None,
           "capabilities": {"supportsOnState": True}}
    out = devtools.compact_device(dev)
    assert "ownerProps" not in out and "globalProps" not in out and "sharedProps" not in out
    assert out["otherPluginProps"] == {"com.x.homekit": {"exposed": True}}
    assert "supportsOnState" not in out and out["capabilities"] == {"supportsOnState": True}
    assert "batteryLevel" not in out and out["pluginProps"] == {"address": "a"}


def test_compact_device_keeps_owner_props_that_differ():
    dev = {"id": 5, "pluginId": "p", "pluginProps": {"a": 1}, "ownerProps": {"a": 2}}
    assert devtools.compact_device(dev)["ownerProps"] == {"a": 2}


def test_one_device_detail_is_checked():
    from types import SimpleNamespace
    out = devtools.get_device_by_id(SimpleNamespace(), 5, detail="huge")
    assert out["success"] is False


# ── plugin settings, credentials hidden ──────────────────────────────────────

@pytest.mark.parametrize("name,secret", [
    ("dahuaPass", True), ("networkSecurityKey", True), ("apiKey", True),
    ("serverpassword", True), ("SMTPPassword", True), ("wifi_psk", True), ("userPIN", True),
    ("pingInterval", False), ("compass", False), ("bypassCache", False), ("spinUp", False),
    ("keepalive", False), ("keyboard", False), ("authMode", False),
])
def test_setting_names(name, secret):
    assert plugin_prefs.is_secret_name(name) is secret


@pytest.fixture()
def prefs_folder(tmp_path, monkeypatch):
    folder = tmp_path / "prefs"
    folder.mkdir()
    (folder / "com.x.cam.indiPref").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<Prefs type="dict">\n'
        '\t<camPass type="string">hunter2</camPass>\n'
        '\t<holdSeconds type="string">20</holdSeconds>\n'
        '\t<pingInterval type="integer">30</pingInterval>\n'
        '\t<ratio type="real">0.5</ratio>\n'
        '\t<debug type="bool">false</debug>\n'
        '\t<relayWord type="string">opensesame</relayWord>\n'
        '\t<emptyPassword type="string"></emptyPassword>\n'
        '\t<networkSecurityKey type="vector"><Item type="integer">1</Item>'
        '<Item type="integer">2</Item></networkSecurityKey>\n'
        '\t<nested type="dict"><token type="string">abc</token>'
        '<port type="integer">80</port></nested>\n'
        '</Prefs>\n', encoding="utf-8")
    plugins = tmp_path / "plugins"
    sp = plugins / "Cam.indigoPlugin" / "Contents" / "Server Plugin"
    sp.mkdir(parents=True)
    import plistlib
    with open(plugins / "Cam.indigoPlugin" / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump({"CFBundleIdentifier": "com.x.cam"}, fh)
    (sp / "PluginConfig.xml").write_text(
        '<PluginConfig><Field id="relayWord" type="textfield" secure="true"/></PluginConfig>',
        encoding="utf-8")
    monkeypatch.setattr(plugin_prefs, "PREFS_DIR_OVERRIDE", str(folder))
    monkeypatch.setattr(device_props, "PLUGINS_DIR_OVERRIDE", str(plugins))
    monkeypatch.setattr(device_props, "_PLUGIN_SCAN_AT", None)
    device_props._CONTENTS_BY_PLUGIN.clear()
    device_props._SECURE_BY_PATH.clear()
    return folder


def test_prefs_are_typed_and_credentials_hidden(prefs_folder):
    out = plugin_prefs.read("com.x.cam")
    p = out["prefs"]
    assert p["holdSeconds"] == "20" and p["pingInterval"] == 30 and p["ratio"] == 0.5
    assert p["debug"] is False and p["nested"]["port"] == 80
    assert p["camPass"] == plugin_prefs.MASK
    assert p["relayWord"] == plugin_prefs.MASK          # secure="true" in PluginConfig.xml
    assert p["networkSecurityKey"] == plugin_prefs.MASK  # a list, hidden whole
    assert p["nested"]["token"] == plugin_prefs.MASK
    assert p["emptyPassword"] == ""                      # nothing to hide
    assert out["hidden"] == sorted(["camPass", "relayWord", "networkSecurityKey",
                                    "nested.token"])
    assert "hunter2" not in repr(out) and "opensesame" not in repr(out)


def test_prefs_refusals(prefs_folder):
    assert "No saved settings" in plugin_prefs.read("com.x.none")["error"]
    assert "not a plugin bundle id" in plugin_prefs.read("../secrets")["error"]


# ── device_history summary ───────────────────────────────────────────────────

@pytest.fixture()
def history(tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod
    db_path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE device_history_7 (id INTEGER PRIMARY KEY, ts TIMESTAMP, "
                 "voltage REAL, lastseen TEXT, neverset REAL)")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(60):
        ts = (now - timedelta(minutes=60 - i)).isoformat(sep=" ")
        rows.append((i + 1, ts, 240.0 + (i % 3) if i % 4 == 0 else None, f"t{i}", None))
    old = (now - timedelta(days=3)).isoformat(sep=" ")
    conn.execute("INSERT INTO device_history_7 VALUES (0, ?, 1.0, 'old', NULL)", (old,))
    conn.executemany("INSERT INTO device_history_7 VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mod, "_sql_logger_db", lambda: db_path)
    return mod


def test_summary_counts_writes_per_column_busiest_first(history):
    out = history.PluginDevToolsHandler(data_provider=None).device_history(7, hours=2,
                                                                          summary=True)
    assert out["success"] and out["summary"] and out["row_count"] == 60
    assert list(out["columns"]) == ["lastseen", "voltage"]
    assert out["columns"]["lastseen"]["rows_with_value"] == 60
    assert out["columns"]["voltage"] == {"rows_with_value": 15, "min": 240.0, "max": 242.0}
    assert out["never_written"] == ["neverset"]
    assert sum(out["rows_per_day"].values()) == 60        # the 3-day-old row is outside
    assert "rows" not in out


def test_summary_respects_columns_and_the_row_cap(history, monkeypatch):
    monkeypatch.setattr(history, "_SUMMARY_ROW_CAP", 10)
    out = history.PluginDevToolsHandler(data_provider=None).device_history(
        7, hours=2, summary=True, columns=["voltage"])
    assert out["row_count"] == 10 and out["truncated"] and "truncated_note" in out
    assert list(out["columns"]) == ["voltage"] and out["never_written"] == []


# ── restart_plugin waits and reports ─────────────────────────────────────────

class _FakePlugin:
    pluginDisplayName = "Widget"

    def __init__(self, log_file, lines):
        self.log_file, self.lines, self.restarted = log_file, lines, False

    def isEnabled(self):
        return True

    def restart(self, waitUntilDone=True):
        assert waitUntilDone is False
        self.restarted = True
        if self.lines:
            _write(self.log_file, self.lines)


@pytest.fixture()
def restarter(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from mcp_server.tools.plugin_control import plugin_control_handler as pch
    monkeypatch.setattr(lq, "_LOG_ROOT", str(tmp_path))
    log_file = tmp_path / f"{date.today().strftime('%Y-%m-%d')} Events.txt"
    _write(log_file, [f"{date.today()} 08:00:00.000\tApplication\t"
                      'Started plugin "Widget 0.9"'], "w")
    handler = pch.PluginControlHandler(None, logger=LOG)
    handler.RESTART_SETTLE = 0.05
    monkeypatch.setattr(handler, "_is_installed", lambda pid: True)

    def make(lines):
        plugin = _FakePlugin(log_file, lines)
        monkeypatch.setattr(pch, "indigo", SimpleNamespace(
            server=SimpleNamespace(getPlugin=lambda pid: plugin)))
        return plugin
    return handler, make


def test_restart_reports_the_new_version_and_errors(restarter):
    handler, make = restarter
    today = date.today()
    make([f"{today} 09:00:01.000\tWidget Error\tconfig missing",
          f"{today} 09:00:02.000\tApplication\tStarted plugin \"Widget 1.0\""])
    out = handler.restart_plugin("com.x.widget", wait_seconds=3)
    assert out["success"] and out["started"] is True and out["running_version"] == "1.0"
    assert out["errors"] == 1 and "1 error" in out["message"]
    assert out["waited_seconds"] < 2          # stops as soon as it has started


def test_restart_that_never_starts_says_so(restarter):
    handler, make = restarter
    make([])
    out = handler.restart_plugin("com.x.widget", wait_seconds=0.3)
    assert out["success"] and out["started"] is False and "had not logged" in out["message"]


def test_restart_without_waiting_and_bad_waits(restarter):
    handler, make = restarter
    plugin = make([])
    out = handler.restart_plugin("com.x.widget", wait_seconds=0)
    assert plugin.restarted and "started" not in out
    assert handler.restart_plugin("com.x.widget", wait_seconds="soon")["success"] is False
    assert handler.restart_plugin("com.x.widget", wait_seconds=-1)["success"] is False


def test_summary_that_overruns_its_budget_is_stopped_and_says_so(history, monkeypatch):
    monkeypatch.setattr(history, "_SUMMARY_TIME_BUDGET", -1.0)
    monkeypatch.setattr(history, "_SUMMARY_PROGRESS_STEPS", 1)
    out = history.PluginDevToolsHandler(data_provider=None).device_history(7, hours=2,
                                                                          summary=True)
    assert out["success"] is False and "Ask for fewer hours" in out["error"]


def test_default_wait_covers_a_plugin_that_quiesces_before_stopping():
    """Dashboards waits 4 s for in-flight web requests before it stops and
    takes about 6.5 s to come back; a 5 s default reported every one of its
    restarts as not started. The wait ends as soon as the plugin starts, so a
    longer default costs a quick plugin nothing."""
    from mcp_server.tools.plugin_control import plugin_control_handler as pch
    assert pch.PluginControlHandler.RESTART_WAIT_DEFAULT >= 8
    assert pch.PluginControlHandler.RESTART_WAIT_DEFAULT <= pch.PluginControlHandler.RESTART_WAIT_MAX
