#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_postgres_live.py
# Description: device_history and variable_history against a REAL PostgreSQL
#              server, through the SQL Logger's own driver. Skipped unless a
#              server is named in the environment, because it needs one:
#
#                CB_TEST_PG_PORT=55432 CB_TEST_PG_PASSWORD=... python3 -m pytest \
#                    tests/test_history_postgres_live.py
#
#              Also CB_TEST_PG_HOST (127.0.0.1), CB_TEST_PG_USER (postgres),
#              CB_TEST_PG_DATABASE (indigo_history, which must exist) and
#              CB_TEST_INDIGO_BASE (the Indigo install folder holding the SQL
#              Logger plugin; found automatically on an Indigo server).
#              The server must accept MD5 or password login: the SQL Logger's
#              driver cannot do SCRAM, so a server it can log to never needs it.
#              It makes its own tables (device_history_9001, _9002,
#              variable_history_9001) and removes them. Each run is repeated
#              with the database set to three different time zones, because
#              the logger's ts carries no zone and is the part most likely to
#              be read wrong: the answers must not depend on it.
# Author:      CliveS & Claude Sonnet 5.5
# Date:        19-10-2026
# Version:     1.0

import glob
import os
from datetime import datetime, timedelta

import pytest

PORT = os.environ.get("CB_TEST_PG_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="set CB_TEST_PG_PORT to a PostgreSQL server")

HOST = os.environ.get("CB_TEST_PG_HOST", "127.0.0.1")
USER = os.environ.get("CB_TEST_PG_USER", "postgres")
PASSWORD = os.environ.get("CB_TEST_PG_PASSWORD", "")
DATABASE = os.environ.get("CB_TEST_PG_DATABASE", "indigo_history")

ZONES = ["Europe/London", "Pacific/Auckland", "America/New_York"]


def _indigo_base():
    given = os.environ.get("CB_TEST_INDIGO_BASE")
    if given:
        return given
    found = sorted(glob.glob("/Library/Application Support/Perceptive Automation/Indigo 20*"))
    if not found:
        pytest.skip("no Indigo install with a SQL Logger plugin to borrow the driver from")
    return found[-1]


def _settings(password=None):
    return {"host": HOST, "port": int(PORT), "database": DATABASE, "user": USER,
            "password": PASSWORD if password is None else password}


def _near(a, b, seconds):
    return abs((a - b).total_seconds()) <= seconds


def _local(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


@pytest.fixture(params=ZONES)
def pg(request, tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import history_postgres as pgh
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    base = _indigo_base()
    driver = pgh.load_driver(base)
    admin = driver(host=HOST, port=int(PORT), user=USER, password=PASSWORD, database=DATABASE)
    admin.execute(f"ALTER DATABASE {DATABASE} SET timezone = '{request.param}'")
    admin.close()
    # A new connection now writes and reads in the chosen zone, as the logger's would.
    db = driver(host=HOST, port=int(PORT), user=USER, password=PASSWORD, database=DATABASE)

    for table in ("device_history_9001", "device_history_9002", "variable_history_9001"):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute('CREATE TABLE device_history_9001 (id integer primary key generated always as '
               'identity, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP, watts real, flag boolean, '
               'name text, "order" text, neverset real)')
    db.execute("INSERT INTO device_history_9001 (ts, watts, flag, name) "
               "SELECT (now() - (g * interval '3 minutes'))::timestamp, (g % 7)::real, "
               "(g % 2 = 0), CASE WHEN g % 2 = 1 THEN 'on' END "
               "FROM generate_series(100, 1, -1) g")
    db.execute("CREATE TABLE variable_history_9001 (id integer primary key generated always as "
               "identity, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP, value text)")
    db.execute("INSERT INTO variable_history_9001 (ts, value) VALUES "
               "((now() - interval '30 hours')::timestamp, 'off'), "
               "((now() - interval '5 hours')::timestamp, 'on'), "
               "((now() - interval '3 hours')::timestamp, 'off'), "
               "((now() - interval '1 hours')::timestamp, 'on')")

    # An Indigo-shaped folder: the real Plugins (for the driver) beside a
    # Preferences tree holding a SQL Logger preferences file for this server.
    fake_base = tmp_path / "Indigo 2025.2"
    (fake_base / "Preferences" / "Plugins").mkdir(parents=True)
    os.symlink(os.path.join(base, "Plugins"), fake_base / "Plugins")
    escaped = PASSWORD.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    (fake_base / "Preferences" / "Plugins" / mod._SQL_LOGGER_PREFS).write_text(
        f'<Prefs><databaseType type="string">postgresql</databaseType>'
        f'<postgresqlHost type="string">{HOST}:{PORT}</postgresqlHost>'
        f'<postgresqlUser type="string">{USER}</postgresqlUser>'
        f'<postgresqlPassword type="string">{escaped}</postgresqlPassword>'
        f'<postgresqlDatabase type="string">{DATABASE}</postgresqlDatabase></Prefs>',
        encoding="utf-8")
    monkeypatch.setattr(mod, "_indigo_base", lambda: str(fake_base))

    class Env:
        pass

    e = Env()
    e.mod, e.pgh, e.db, e.driver, e.zone = mod, pgh, db, driver, request.param
    e.handler = mod.PluginDevToolsHandler(data_provider=None)
    yield e

    for table in ("device_history_9001", "device_history_9002", "variable_history_9001"):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute(f"ALTER DATABASE {DATABASE} RESET timezone")
    db.close()


def test_rows_come_back_with_the_right_local_times_whatever_the_servers_zone(pg):
    reply = pg.handler.device_history(9001, hours=24, limit=500)
    assert reply["success"] is True, reply
    assert reply["source"] == "postgresql"
    assert reply["credentials_from"] == "SQL Logger settings"
    assert reply["row_count"] == 100
    now = datetime.now()
    assert _near(_local(reply["ts_newest"]), now - timedelta(minutes=3), 90), reply["ts_newest"]
    assert _near(_local(reply["ts_oldest"]), now - timedelta(minutes=300), 90), reply["ts_oldest"]
    first = reply["rows"][0]
    assert first["watts"] == 1.0 and first["flag"] is False and first["name"] == "on"
    assert "neverset" not in reply["columns"]


def test_the_window_is_cut_at_the_right_moment(pg):
    two_hours = pg.handler.device_history(9001, hours=2, limit=500)
    assert two_hours["success"] is True
    assert two_hours["row_count"] in (39, 40), two_hours["row_count"]
    nothing = pg.handler.device_history(9001, hours=1, limit=500)
    assert nothing["row_count"] in (19, 20), nothing["row_count"]


def test_named_columns_limit_and_errors(pg):
    reply = pg.handler.device_history(9001, columns=["watts"], limit=5)
    assert reply["columns"] == ["ts", "watts"] and reply["row_count"] == 5 and reply["truncated"]
    bad = pg.handler.device_history(9001, columns=["nope"])
    assert bad["success"] is False and "Valid columns" in bad["error"]
    missing = pg.handler.device_history(123456)
    assert missing["success"] is False and "No SQL Logger table" in missing["error"]


def test_the_summary_counts_and_handles_a_boolean_column(pg):
    reply = pg.handler.device_history(9001, summary=True)
    assert reply["success"] is True, reply
    assert reply["row_count"] == 100 and reply["truncated"] is False
    assert sum(reply["rows_per_day"].values()) == 100
    cols = reply["columns"]
    assert cols["watts"] == {"rows_with_value": 100, "min": 0.0, "max": 6.0}
    assert cols["flag"] == {"rows_with_value": 100, "min": 0, "max": 1}
    assert cols["name"]["rows_with_value"] == 50
    assert reply["never_written"] == ["neverset"] or "neverset" in reply["never_written"]
    now = datetime.now()
    assert _near(_local(reply["ts_newest"]), now - timedelta(minutes=3), 90)


def test_a_variable_reads_rows_and_the_value_before_the_window(pg):
    reply = pg.handler.variable_history(9001, hours=24, name="Heating")
    assert reply["success"] is True, reply
    assert reply["name"] == "Heating"
    assert reply["value_before"]["value"] == "off"
    assert [r["value"] for r in reply["rows"]] == ["on", "off", "on"]
    assert _near(_local(reply["rows"][0]["ts"]), datetime.now() - timedelta(hours=1), 120)
    assert _near(_local(reply["value_before"]["ts"]), datetime.now() - timedelta(hours=30), 120)


def test_a_variable_summary_says_how_long_each_value_held(pg):
    reply = pg.handler.variable_history(9001, hours=24, summary=True)
    assert reply["success"] is True, reply
    held = {v["value"]: v["seconds_held"] for v in reply["values"]}
    assert abs(held["on"] - 3 * 3600) < 180, held
    assert abs(held["off"] - 21 * 3600) < 180, held
    assert reply["changes"] == 3


def test_the_connection_cannot_write(pg):
    history = pg.pgh.PostgresHistory.connect([("t", _settings())], _indigo_base())
    try:
        with pytest.raises(Exception) as err:
            history._conn.prepare("INSERT INTO device_history_9001 (watts) VALUES ($1)")(1.0)
        assert getattr(err.value, "code", None) == "25006"
    finally:
        history.close()


def test_a_wrong_password_falls_through_to_the_next_login_and_is_never_shown(pg):
    history = pg.pgh.PostgresHistory.connect(
        [("bad", _settings("wrong-password-xyz")), ("good", _settings())], _indigo_base())
    try:
        assert history.source == "good"
    finally:
        history.close()
    with pytest.raises(pg.pgh.HistoryDbUnavailable) as err:
        pg.pgh.PostgresHistory.connect(
            [("one", _settings("wrong-password-xyz")), ("two", _settings("another-wrong-one"))],
            _indigo_base())
    text = str(err.value)
    assert "one" in text and "two" in text
    assert "wrong-password-xyz" not in text and "another-wrong-one" not in text


def test_a_summary_over_its_time_budget_is_cancelled_and_the_connection_survives(pg):
    pg.db.execute("CREATE TABLE device_history_9002 (id integer primary key generated always as "
                  "identity, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP, watts real)")
    pg.db.execute("INSERT INTO device_history_9002 (ts, watts) SELECT (now() - "
                  "(g * interval '1 second'))::timestamp, g::real FROM generate_series(400000, 1, -1) g")
    history = pg.pgh.PostgresHistory.connect([("t", _settings())], _indigo_base())
    try:
        with pytest.raises(pg.pgh.BudgetExceeded):
            history.summary("device_history_9002", [("watts", "real")], 1, 1_000_000, 0.001)
        assert history.has_table("device_history_9002")      # still usable afterwards
    finally:
        history.close()
    pg.mod._SUMMARY_TIME_BUDGET = 0.001
    try:
        reply = pg.handler.device_history(9002, hours=100, summary=True)
    finally:
        pg.mod._SUMMARY_TIME_BUDGET = 5.0
    assert reply["success"] is False and "took longer" in reply["error"]


def test_an_unreachable_server_is_a_clear_error_inside_the_time_limit(pg, tmp_path, monkeypatch):
    import time
    prefs = os.path.join(pg.mod._indigo_base(), "Preferences", "Plugins", pg.mod._SQL_LOGGER_PREFS)
    text = open(prefs, encoding="utf-8").read().replace(f"{HOST}:{PORT}", f"{HOST}:1")
    open(prefs, "w", encoding="utf-8").write(text)
    started = time.monotonic()
    reply = pg.handler.device_history(9001)
    assert time.monotonic() - started < 10
    assert reply["success"] is False and reply["sql_logger_type"] == "postgresql"
    assert "Could not connect" in reply["error"]
    assert PASSWORD == "" or PASSWORD not in reply["error"]
