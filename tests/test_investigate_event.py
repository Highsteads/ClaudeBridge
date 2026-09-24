#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_investigate_event.py
# Description: investigate_event searches the whole window it is given. It
#              read through the query_event_log reader, whose 2000-entry cap
#              kept only the newest ~1.5 days of this house's log whatever
#              search_days said. Also: a delayed action is logged under
#              "Schedule" whatever queued it, and the message names the kind.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import datetime
import logging

import pytest

from mcp_server.adapters.indidb.store import IndiDbStructureStore
from mcp_server.tools.automation_detail import automation_detail_handler as adh
from mcp_server.tools.log_query import log_query_handler as lq

from test_indidb_adapter import DEV_LAMP, SYNTHETIC_DB, TRIG_MOTION

LOG = logging.getLogger("test-investigate")


def _line(ts, source, message):
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\t{source}\t{message}"


def _write_logs(folder, lines):
    by_day = {}
    for ts, text in lines:
        by_day.setdefault(ts.date(), []).append(text)
    for day, texts in by_day.items():
        (folder / f"{day.isoformat()} Events.txt").write_text("\n".join(texts) + "\n",
                                                              encoding="utf-8")


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    db = tmp_path / "Synthetic.indiDb"
    db.write_text(SYNTHETIC_DB, encoding="utf-8")
    logs = tmp_path / "Logs"
    logs.mkdir()
    monkeypatch.setattr(lq, "_LOG_ROOT", str(logs))
    handler = adh.AutomationDetailHandler(
        data_provider=None,
        structure_store=IndiDbStructureStore(lambda: str(db), stat_throttle_seconds=0.0),
        log_query_handler=lq.LogQueryHandler(None, logger=LOG), logger=LOG)
    return handler, logs


def _busy_day(target, cause_source, cause_message, noise=3000):
    """The cause and the target, then a busy log after them — more than 2000
    lines, all newer than the event, as on a real day."""
    lines = [(target - datetime.timedelta(seconds=3),
              _line(target - datetime.timedelta(seconds=3), cause_source, cause_message)),
             (target, _line(target, "Z-Wave", 'received "Test Lamp" status update is on'))]
    step = datetime.timedelta(hours=28) / max(noise, 1)
    for i in range(1, noise + 1):
        ts = target + step * i
        lines.append((ts, _line(ts, "Z-Wave", f"received \"Some Sensor\" temperature {i}")))
    return lines


def test_an_event_behind_more_than_2000_newer_lines_is_found(rig):
    handler, logs = rig
    target = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=30)
    _write_logs(logs, _busy_day(target, "Trigger", "Motion Turns On Lamp"))
    out = handler.investigate_event(device_id=DEV_LAMP, search_days=2)
    assert out["success"] is True, out
    assert out["target_event"]["timestamp"].startswith(target.strftime("%Y-%m-%d %H:%M:%S"))
    assert out["candidates"][0]["id"] == TRIG_MOTION
    assert out["log_scan"]["truncated"] is False


def test_a_delayed_action_is_credited_to_the_trigger_that_queued_it(rig):
    handler, logs = rig
    target = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(minutes=5)
    _write_logs(logs, _busy_day(target, "Schedule",
                                'trigger "Motion Turns On Lamp" (delayed action)', noise=10))
    out = handler.investigate_event(device_id=DEV_LAMP)
    top = out["candidates"][0]
    assert top["entity_type"] == "trigger" and top["id"] == TRIG_MOTION
    assert top["name"] == "Motion Turns On Lamp"


def test_a_cut_scan_says_so(rig, monkeypatch):
    handler, logs = rig
    monkeypatch.setattr(adh, "INVESTIGATE_MAX_ENTRIES", 50)
    target = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(minutes=5)
    lines = _busy_day(target, "Trigger", "Motion Turns On Lamp", noise=0)
    for i in range(200):
        ts = target - datetime.timedelta(minutes=10 + i)
        lines.append((ts, _line(ts, "Trigger", f"Other Trigger {i}")))
    _write_logs(logs, sorted(lines))
    out = handler.investigate_event(device_id=DEV_LAMP)
    assert out["success"] is True
    assert out["log_scan"]["truncated"] is True
    assert any("only the newest were searched" in n for n in out["notes"])


def test_query_event_log_keeps_its_own_2000_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(lq, "_LOG_ROOT", str(tmp_path))
    start = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=1)
    _write_logs(tmp_path, [(start + datetime.timedelta(seconds=i),
                            _line(start + datetime.timedelta(seconds=i), "X", f"m{i}"))
                           for i in range(2500)])
    entries, meta = lq.LogQueryHandler(None, logger=LOG)._read_log_range(start, None, None)
    assert len(entries) == 2000 and meta["truncated"] is True
    entries, _ = lq.LogQueryHandler(None, logger=LOG)._read_log_range(start, None, None,
                                                                       limit=None)
    assert len(entries) == 2500


def test_the_log_folder_comes_from_indigo_at_call_time(tmp_path, monkeypatch):
    import indigo
    (tmp_path / "Logs").mkdir()
    monkeypatch.setattr(lq, "_LOG_ROOT", None)
    monkeypatch.setattr(indigo.server, "getInstallFolderPath", lambda: str(tmp_path))
    assert lq._log_root() == str(tmp_path / "Logs")
    monkeypatch.setattr(indigo.server, "getInstallFolderPath", lambda: None)
    assert lq._log_root().endswith("Logs"), "falls back to the bundle-relative folder"


def test_lines_it_cannot_use_do_not_count_against_the_cap(rig, monkeypatch):
    """Only automation activity and lines naming the target are held, so a
    busy log of unrelated sensor chatter cannot push the event out."""
    handler, logs = rig
    monkeypatch.setattr(adh, "INVESTIGATE_MAX_ENTRIES", 50)
    target = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=3)
    _write_logs(logs, _busy_day(target, "Trigger", "Motion Turns On Lamp", noise=500))
    out = handler.investigate_event(device_id=DEV_LAMP)
    assert out["success"] is True and out["log_scan"]["truncated"] is False
    assert out["log_scan"]["relevant_lines"] == 2
