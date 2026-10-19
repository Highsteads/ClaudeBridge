#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_postgres.py
# Description: device_history and variable_history against a PostgreSQL SQL
#              Logger. The handler path is proven by running the SAME data
#              through the SQLite path and through a PostgreSQL stand-in that
#              answers the history_postgres interface, and requiring identical
#              replies. Credentials (the logger's settings first, then Claude
#              Bridge's), the order connections are tried in, and the safety of
#              what is sent to the server are tested on their own.
# Author:      CliveS & Claude Sonnet 5.5
# Date:        19-10-2026
# Version:     1.0

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

PASSWORD = "p&ss<word>-not-real"


# ── A PostgreSQL stand-in over a SQLite file ────────────────────────────────

class FakePg:
    """Answers the PostgresHistory interface from a SQLite file whose ts is UTC,
    which is what the real class returns once the server has converted it."""

    source = "SQL Logger settings"

    def __init__(self, mod, path):
        self.mod = mod
        self.conn = sqlite3.connect(path)
        self.closed = False

    def close(self):
        self.closed = True
        self.conn.close()

    def has_table(self, table):
        return bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())

    def columns(self, table):
        kinds = {"REAL": "real", "TEXT": "text", "INTEGER": "integer",
                 "TIMESTAMP": "timestamp without time zone"}
        return [(r[1], kinds.get(r[2].upper(), "text"))
                for r in self.conn.execute(f"PRAGMA table_info({table})")]

    def floor_id(self, table, hours):
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
                  - timedelta(hours=hours)).isoformat(sep=" ")
        return self.mod.PluginDevToolsHandler._rowid_floor_for_ts(self.conn.cursor(), table, cutoff)

    @staticmethod
    def _dt(text):
        return datetime.fromisoformat(text) if text else None

    def rows(self, table, names, floor_id, limit):
        sel = ", ".join(f'"{n}"' for n in names)
        out = []
        for r in self.conn.execute(
                f"SELECT {sel} FROM {table} WHERE id >= ? ORDER BY id DESC LIMIT ?", (floor_id, limit)):
            out.append(tuple(self._dt(v) if n == "ts" else v for n, v in zip(names, r)))
        return out

    def summary(self, table, states, floor_id, row_cap, budget_seconds):
        newest = self.conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
        newest = floor_id if newest is None else newest
        low_id = max(floor_id, newest - row_cap + 1)
        parts = ["COUNT(*)", "MIN(ts)", "MAX(ts)"]
        for name, _ in states:
            parts += [f'COUNT("{name}")', f'MIN("{name}")', f'MAX("{name}")']
        agg = self.conn.execute(f"SELECT {', '.join(parts)} FROM {table} WHERE id >= ?",
                                (low_id,)).fetchone()
        agg = (agg[0], self._dt(agg[1]), self._dt(agg[2])) + tuple(agg[3:])
        hours = self.conn.execute(
            f"SELECT substr(ts, 1, 13), COUNT(*) FROM {table} WHERE id >= ? GROUP BY 1",
            (low_id,)).fetchall()
        return {"truncated": low_id > floor_id, "agg": agg,
                "per_hour": [(datetime.strptime(h, "%Y-%m-%d %H"), n) for h, n in hours]}

    def variable_before(self, table, floor_id):
        r = self.conn.execute(f"SELECT ts, value FROM {table} WHERE id < ? "
                              f"ORDER BY id DESC LIMIT 1", (floor_id,)).fetchone()
        return (self._dt(r[0]), r[1]) if r else None

    def variable_rows(self, table, floor_id, limit, newest_first):
        order = "DESC" if newest_first else "ASC"
        return [(self._dt(r[0]), r[1]) for r in self.conn.execute(
            f"SELECT ts, value FROM {table} WHERE id >= ? ORDER BY id {order} LIMIT ?",
            (floor_id, limit))]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from mcp_server.tools.plugin_dev_tools import plugin_dev_tools_handler as mod

    path = str(tmp_path / "indigo_history.sqlite")
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE device_history_9 (id INTEGER PRIMARY KEY, ts TIMESTAMP, '
                 'watts REAL, name TEXT, "order" TEXT, neverset REAL)')
    conn.execute("CREATE TABLE variable_history_5 (id INTEGER PRIMARY KEY, ts TIMESTAMP, value TEXT)")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conn.executemany(
        "INSERT INTO device_history_9 VALUES (?,?,?,?,?,?)",
        [(i + 1, (now - timedelta(minutes=300 - 3 * i)).isoformat(sep=" "),
          float(i % 7), "on" if i % 2 else None, "x", None) for i in range(100)])
    conn.executemany(
        "INSERT INTO variable_history_5 VALUES (?,?,?)",
        [(1, (now - timedelta(hours=30)).isoformat(sep=" "), "off"),
         (2, (now - timedelta(hours=5)).isoformat(sep=" "), "on"),
         (3, (now - timedelta(hours=3)).isoformat(sep=" "), "off"),
         (4, (now - timedelta(hours=1)).isoformat(sep=" "), "on")])
    conn.commit()
    conn.close()

    monkeypatch.setattr(mod, "_sql_logger_db", lambda: path)
    monkeypatch.setattr(mod, "_indigo_base", lambda: str(tmp_path))

    class World:
        pass

    w = World()
    w.mod, w.path = mod, path
    w.handler = mod.PluginDevToolsHandler(data_provider=None)
    w.fakes = []

    def sqlite_mode():
        monkeypatch.setattr(mod, "_sql_logger_type", lambda: "sqlite")

    def postgres_mode():
        def connect():
            fake = FakePg(mod, path)
            w.fakes.append(fake)
            return fake
        monkeypatch.setattr(mod, "_sql_logger_type", lambda: "postgresql")
        monkeypatch.setattr(mod, "_pg_connect", connect)

    w.sqlite_mode, w.postgres_mode = sqlite_mode, postgres_mode
    return w


def _both(w, call):
    """The reply from the SQLite path and from the PostgreSQL path."""
    w.sqlite_mode()
    via_sqlite = call(w.handler)
    w.postgres_mode()
    via_pg = call(w.handler)
    return via_sqlite, via_pg


_ADDED = ("source", "credentials_from", "db_last_written")


def _same(via_sqlite, via_pg):
    assert via_pg.get("source") == "postgresql"
    assert via_pg.get("credentials_from") == "SQL Logger settings"
    for key in _ADDED:
        via_sqlite.pop(key, None)
        via_pg.pop(key, None)
    assert via_pg == via_sqlite


@pytest.mark.parametrize("call", [
    lambda h: h.device_history(9),
    lambda h: h.device_history(9, hours=1),
    lambda h: h.device_history(9, limit=5),
    lambda h: h.device_history(9, columns=["watts"]),
    lambda h: h.device_history(9, columns="watts"),
    lambda h: h.device_history(9, columns=["watts", "name"], limit=20),
    lambda h: h.device_history(9, summary=True),
    lambda h: h.device_history(9, summary=True, columns=["watts"]),
    lambda h: h.device_history(9, hours=100000),
    lambda h: h.device_history(9, columns=["nope"]),
    lambda h: h.device_history(404),
    lambda h: h.device_history("abc"),
    lambda h: h.variable_history(5),
    lambda h: h.variable_history(5, hours=2),
    lambda h: h.variable_history(5, hours=1000),
    lambda h: h.variable_history(5, limit=1),
    lambda h: h.variable_history(5, summary=True),
    lambda h: h.variable_history(5, summary=True, hours=4),
    lambda h: h.variable_history(5, name="Heating"),
    lambda h: h.variable_history(404),
])
def test_postgresql_replies_match_the_sqlite_replies(world, call):
    via_sqlite, via_pg = _both(world, call)
    if via_sqlite.get("success"):
        _same(via_sqlite, via_pg)
    else:
        assert via_pg == via_sqlite


def test_the_postgresql_connection_is_always_closed(world):
    world.postgres_mode()
    world.handler.device_history(9)
    world.handler.device_history(404)
    world.handler.variable_history(5, summary=True)
    world.handler.device_history(9, columns=["nope"])
    assert world.fakes and all(f.closed for f in world.fakes)


def test_postgresql_does_not_touch_the_sqlite_file(world, monkeypatch):
    world.postgres_mode()

    def boom(*a, **k):
        raise AssertionError("sqlite was opened")
    monkeypatch.setattr(world.mod.sqlite3, "connect", boom)
    # the stand-in itself needs sqlite, so use a connection-less fake here
    monkeypatch.setattr(world.mod, "_pg_connect", lambda: (_ for _ in ()).throw(
        world.mod._pgh.HistoryDbUnavailable("down")))
    reply = world.handler.device_history(9)
    assert reply["success"] is False and reply["sql_logger_type"] == "postgresql"
    assert reply["error"] == "down"
    reply = world.handler.variable_history(5)
    assert reply["success"] is False and reply["error"] == "down"


def test_a_summary_cut_off_by_the_server_says_so(world, monkeypatch):
    world.postgres_mode()
    real = FakePg.summary

    def slow(self, *a, **k):
        raise world.mod._pgh.BudgetExceeded()
    monkeypatch.setattr(FakePg, "summary", slow)
    reply = world.handler.device_history(9, summary=True)
    assert reply["success"] is False and "took longer" in reply["error"]
    monkeypatch.setattr(FakePg, "summary", real)


def test_an_unreadable_database_type_is_still_refused_or_read_as_sqlite(world, monkeypatch):
    monkeypatch.setattr(world.mod, "_sql_logger_type", lambda: "mysql")
    reply = world.handler.device_history(9)
    assert reply["success"] is False and "mysql" in reply["error"]
    monkeypatch.setattr(world.mod, "_sql_logger_type", lambda: None)
    assert world.handler.device_history(9)["success"] is True


# ── Credentials ─────────────────────────────────────────────────────────────

@pytest.fixture()
def pgh():
    from mcp_server.tools.plugin_dev_tools import history_postgres
    return history_postgres


def _prefs(tmp_path, body):
    p = tmp_path / "logger.indiPref"
    p.write_text(f'<?xml version="1.0"?><Prefs>{body}</Prefs>', encoding="utf-8")
    return str(p)


def test_the_logger_settings_are_read_and_the_port_split_off(pgh, tmp_path):
    path = _prefs(tmp_path,
                  '<databaseType type="string">postgresql</databaseType>'
                  '<postgresqlHost type="string">db.example.test:6543</postgresqlHost>'
                  '<postgresqlUser type="string">indigo</postgresqlUser>'
                  f'<postgresqlPassword type="string">{PASSWORD.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}</postgresqlPassword>'
                  '<postgresqlDatabase type="string">history</postgresqlDatabase>')
    got = pgh.logger_settings(path)
    assert got == {"host": "db.example.test", "port": 6543, "database": "history",
                   "user": "indigo", "password": PASSWORD}


def test_keys_the_logger_never_saved_take_its_own_defaults(pgh, tmp_path):
    path = _prefs(tmp_path, '<postgresqlPassword type="string">pw</postgresqlPassword>')
    got = pgh.logger_settings(path)
    assert got == {"host": "127.0.0.1", "port": 5432, "database": "indigo_history",
                   "user": "postgres", "password": "pw"}


def test_an_empty_password_is_allowed_but_an_empty_host_is_not(pgh, tmp_path):
    ok = _prefs(tmp_path, '<postgresqlPassword type="string"></postgresqlPassword>')
    assert pgh.logger_settings(ok)["password"] == ""
    bad = _prefs(tmp_path, '<postgresqlHost type="string"> </postgresqlHost>')
    assert pgh.logger_settings(bad) is None


def test_missing_or_broken_logger_preferences_give_nothing(pgh, tmp_path):
    assert pgh.logger_settings(str(tmp_path / "nope.indiPref")) is None
    broken = tmp_path / "broken.indiPref"
    broken.write_text("<Prefs><unclosed>", encoding="utf-8")
    assert pgh.logger_settings(str(broken)) is None


def test_claude_bridge_settings_come_secrets_first_then_configure(pgh):
    secrets = {"CLAUDEBRIDGE_PG_HOST": "s.example.test:7000", "CLAUDEBRIDGE_PG_DATABASE": "sdb",
               "CLAUDEBRIDGE_PG_USER": "su", "CLAUDEBRIDGE_PG_PASSWORD": "sp"}
    prefs = {"history_pg_host": "c.example.test", "history_pg_database": "cdb",
             "history_pg_user": "cu", "history_pg_password": "cp"}
    got = pgh.claude_bridge_settings(secrets, prefs)
    assert [label for label, _ in got] == ["Claude Bridge (IndigoSecrets.py)",
                                           "Claude Bridge (Configure)"]
    assert got[0][1]["port"] == 7000 and got[1][1]["port"] == 5432
    assert pgh.claude_bridge_settings({}, {}) == []
    assert pgh.claude_bridge_settings({}, None) == []


def test_candidates_are_the_logger_then_claude_bridge(world, monkeypatch, tmp_path):
    mod = world.mod
    from types import SimpleNamespace
    monkeypatch.setattr(mod, "indigo", SimpleNamespace(
        activePlugin=SimpleNamespace(pluginPrefs={})), raising=False)
    prefs_dir = tmp_path / "Preferences" / "Plugins"
    prefs_dir.mkdir(parents=True)
    (prefs_dir / mod._SQL_LOGGER_PREFS).write_text(
        '<Prefs><postgresqlHost>logger.example.test</postgresqlHost></Prefs>', encoding="utf-8")
    (tmp_path.parent / "IndigoSecrets.py").write_text(
        'CLAUDEBRIDGE_PG_HOST="own.example.test"\nCLAUDEBRIDGE_PG_DATABASE="d"\n'
        'CLAUDEBRIDGE_PG_USER="u"\nCLAUDEBRIDGE_PG_PASSWORD="p"\n', encoding="utf-8")
    try:
        got = mod._pg_candidates()
    finally:
        (tmp_path.parent / "IndigoSecrets.py").unlink()
    assert [label for label, _ in got] == ["SQL Logger settings", "Claude Bridge (IndigoSecrets.py)"]
    assert got[0][1]["host"] == "logger.example.test"
    assert got[1][1]["host"] == "own.example.test"


# ── Connecting ──────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, sql):
        self.executed.append(sql)

    def close(self):
        self.closed = True


def _cand(label, password="pw"):
    return (label, {"host": "h", "port": 5432, "database": "d", "user": "u", "password": password})


def test_the_first_login_that_connects_is_used_and_the_connection_is_made_read_only(pgh):
    tried = []

    def opener(**kw):
        tried.append(kw)
        if kw["password"] == "bad":
            raise RuntimeError("password authentication failed")
        return FakeConn()
    pg = pgh.PostgresHistory.connect([_cand("first", "bad"), _cand("second", "good")],
                                     "/nowhere", opener=opener)
    assert pg.source == "second"
    assert [t["password"] for t in tried] == ["bad", "good"]
    assert all(t["connect_timeout"] == pgh.CONNECT_TIMEOUT for t in tried)
    assert "SET default_transaction_read_only = on" in pg._conn.executed
    assert any("statement_timeout" in s for s in pg._conn.executed)


def test_when_every_login_fails_the_error_names_each_source_and_hides_passwords(pgh):
    def opener(**kw):
        raise RuntimeError(f"bad login for {kw['user']} with {kw['password']}")
    with pytest.raises(pgh.HistoryDbUnavailable) as err:
        pgh.PostgresHistory.connect([_cand("first", "s3cret-one"), _cand("second", "s3cret-two")],
                                    "/nowhere", opener=opener)
    text = str(err.value)
    assert "first" in text and "second" in text
    assert "s3cret-one" not in text and "s3cret-two" not in text


def test_no_settings_at_all_says_where_to_put_them(pgh):
    with pytest.raises(pgh.HistoryDbUnavailable) as err:
        pgh.PostgresHistory.connect([], "/nowhere", opener=lambda **k: FakeConn())
    assert "Configure" in str(err.value) and "CLAUDEBRIDGE_PG_" in str(err.value)


def test_a_missing_sql_logger_bundle_is_a_clear_error_not_a_crash(pgh, tmp_path):
    with pytest.raises(pgh.HistoryDbUnavailable) as err:
        pgh.load_driver(str(tmp_path))
    assert "SQL Logger plugin is not installed" in str(err.value)


# ── What is sent to the server ──────────────────────────────────────────────

class RecordingConn(FakeConn):
    def __init__(self, answers=None):
        super().__init__()
        self.prepared = []
        self.answers = answers or []

    def prepare(self, sql):
        self.prepared.append(sql)
        outer = self

        def run(*params):
            outer.prepared.append(("params", params))
            return outer.answers.pop(0) if outer.answers else []
        return run


def test_values_are_parameters_and_names_are_quoted(pgh):
    now = datetime(2026, 10, 19, 12, 0, 0)
    conn = RecordingConn([[(now,)], [(1, 10)], [(now,)], [(now,)]])
    pg = pgh.PostgresHistory(conn, "test")
    evil = 'device_history_1"; DROP TABLE x; --'
    pg.floor_id(evil, 24)
    sql = [s for s in conn.prepared if isinstance(s, str)]
    assert all('"device_history_1""; DROP TABLE x; --"' in s or "make_interval" in s for s in sql)
    assert all("DROP TABLE x; --\"" not in s.replace('""; DROP TABLE x; --"', "") for s in sql)
    assert any("$1" in s for s in sql)
    assert not any("24" in s for s in sql), "hours must travel as a parameter"


def test_the_timestamps_are_converted_from_the_session_zone_in_sql(pgh):
    conn = RecordingConn([[]])
    pgh.PostgresHistory(conn, "t").rows("device_history_9", ["ts", "watts"], 1, 5)
    sql = conn.prepared[0]
    assert "current_setting('TimeZone')" in sql and "AT TIME ZONE 'UTC'" in sql
    assert '"watts"' in sql and "LIMIT $2" in sql


def test_a_boolean_column_is_summarised_through_an_int_cast(pgh):
    conn = RecordingConn([[(10,)], [(5, None, None, 3, 0, 1)], []])
    pg = pgh.PostgresHistory(conn, "t")
    pg.summary("device_history_9", [("flag", "boolean")], 1, 250_000, 5.0)
    assert any('min("flag"::int)' in s for s in conn.prepared if isinstance(s, str))


def test_a_cancelled_statement_becomes_a_budget_error_and_the_timeout_is_restored(pgh):
    class Cancelled(Exception):
        code = "57014"

    class Conn(RecordingConn):
        def prepare(self, sql):
            if "count(*)" in sql:
                raise Cancelled("canceling statement due to statement timeout")
            return super().prepare(sql)
    conn = Conn([[(10,)]])
    pg = pgh.PostgresHistory(conn, "t")
    with pytest.raises(pgh.BudgetExceeded):
        pg.summary("device_history_9", [("watts", "real")], 1, 250_000, 5.0)
    assert f"SET statement_timeout = {pgh.QUERY_TIMEOUT_MS}" == conn.executed[-1]
